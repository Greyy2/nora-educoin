"""Live routes (/api/studio/live): Paper, Testnet và Live bots qua Nautilus TradingNode (P17 T5).

Các endpoint:
- GET /api/studio/live/environments: trạng thái từng môi trường
- POST /api/studio/live/test_connection: kiểm tra khoá OKX
- POST /api/studio/live/bot: khởi chạy bot (paper/testnet/live)
- GET /api/studio/live/bots: danh sách bot đang có
- GET /api/studio/live/bot/{bot_id}: thông tin chi tiết bot
- POST /api/studio/live/bot/{bot_id}/stop: dừng bot
- GET /api/studio/live/bot/{bot_id}/trades: lịch sử lệnh/khớp của bot
- GET /api/studio/live/bot/{bot_id}/compare: đối chiếu bot với backtest replay
- Các endpoint cũ (chỉ đọc): /live/bot, /live/trades, /live/archive
"""
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.adapter.exchange import (
    get_environments_status, test_okx_api_connection,
    list_bots, get_bot_detail, stop_bot, get_bot_trades, delete_bot, new_bot_id, find_bot_dir,
    archived_bot, archived_trades, archived_compare_events, archived_bots_index,
)
from backend.jobs.runner import launch, JobBusy
from backend.jobs.runner.runner import running_live_bot_info
from backend.jobs import live_supervisor

router = APIRouter(prefix="/api/studio", tags=["live"])


class TestConnectionRequest(BaseModel):
    mode: str = Field("demo", pattern="^(demo|live)$", description="demo: OKX Demo Trading; live: tài khoản thật")


class StopBotRequest(BaseModel):
    close: Optional[bool] = Field(None, description="Đóng các vị thế đang mở (True) hoặc giữ nguyên (False)")


class StartBotRequest(BaseModel):
    mode: str = Field("paper", pattern="^(paper|testnet|live)$")
    alpha_id: Optional[str] = None
    code: Optional[str] = None
    symbols: List[str] = Field(default_factory=lambda: ["BTC-USDT-SWAP"])
    capital: float = Field(1000.0, gt=0)
    base_frame: Optional[str] = "1h"
    confirm_live: Optional[bool] = False
    enter_on_start: bool = False
    signal_tf: Optional[str] = Field(None, description="Khung tín hiệu của dòng bộ chọn (đã backtest lãi); bắt buộc khi from_picker")
    from_picker: bool = False
    params: Optional[Dict[str, Any]] = None
    backtest_job_id: Optional[str] = None
    book_source: Optional[str] = Field(None, pattern="^(main|explore)$", description="Sổ của dòng bộ chọn (main|explore); mặc định lấy theo dòng khớp")


class BatchBotRequest(BaseModel):
    bot_ids: List[str] = Field(..., min_length=1, description="Danh sách bot_id cần thực hiện")
    close: Optional[bool] = Field(True, description="Đóng vị thế (chỉ áp dụng khi stop)")
    mode: Optional[str] = Field(None, pattern="^(paper|testnet|live)$")


@router.on_event("startup")
def _start_live_supervisor() -> None:
    """Chạy lại bot chết (không do người dùng dừng) khi API khởi động và mỗi 30 giây; bot còn tiến trình sống không bị động tới."""
    live_supervisor.start()


@router.get("/environments")
@router.get("/live/environments")
def get_environments() -> Dict[str, Any]:
    """Trạng thái từng môi trường: backtest, paper, testnet, live."""
    return get_environments_status()


@router.post("/live/test_connection")
def post_test_connection(body: Optional[TestConnectionRequest] = None) -> Dict[str, Any]:
    """Kiểm tra kết nối OKX thật (không đặt lệnh)."""
    return test_okx_api_connection(mode=body.mode if body else "demo")


@router.post("/live/bot")
def post_start_bot(body: StartBotRequest) -> Dict[str, Any]:
    """Khởi động bot Live / Paper / Testnet qua Nautilus TradingNode."""
    if body.mode == "live" and not body.confirm_live:
        raise HTTPException(400, "Chế độ Live tiền thật yêu cầu confirm_live=True để xác nhận")

    if body.from_picker:                    # từ bộ chọn: chỉ chạy đúng (chiến lược, khung tín hiệu) đã có backtest lãi được lưu
        from backend.analys.alpha import strategies
        if not body.alpha_id or not body.signal_tf:
            raise HTTPException(400, "Từ bộ chọn cần alpha_id và signal_tf")
        candidates = strategies.live_candidates()
        matched = next((r for r in candidates if r["id"] == body.alpha_id and r["timeframe"] == body.signal_tf and (not body.book_source or r.get("book") == body.book_source)), None)
        if not matched:
            raise HTTPException(400, f"Chiến lược {body.alpha_id} chưa có backtest lãi ở khung {body.signal_tf}")

        is_custom = body.params is not None
        cand_syms = set(matched.get("symbols") or [])
        req_syms = set(body.symbols or [])
        if cand_syms and req_syms != cand_syms:
            is_custom = True
        if is_custom:
            if not body.backtest_job_id:
                raise HTTPException(400, "Cấu hình tuỳ chỉnh bắt buộc phải có backtest_job_id đã chạy trước khi bật bot")
            from backend.jobs import runner, tasks
            jb = runner.status(body.backtest_job_id)
            if not jb or jb.get("status") != "done":
                raise HTTPException(400, f"Job backtest {body.backtest_job_id} chưa hoàn thành hoặc không tồn tại")
            rec = tasks.picker_backtest_get(body.backtest_job_id)
            if not rec:
                raise HTTPException(400, "Job backtest không phải từ bộ chọn (không có cấu hình đã lưu)")
            try:
                rs = tasks.resolve_strategy(body.alpha_id, None, body.signal_tf, body.params, body.symbols, matched.get("book"))
            except tasks.ConfigError as e:
                raise HTTPException(400, "; ".join(f"{f}: {m}" for f, m in e.errors))
            if rs["hash"] != rec.get("hash") or (rec.get("book_source") or None) != (matched.get("book") or None):
                raise HTTPException(400, "Cấu hình khác lần backtest")

    book_source = matched.get("book") if body.from_picker else body.book_source

    bot_id = new_bot_id(body.mode)          # duy nhất (thời gian + 6 hex ngẫu nhiên)
    if find_bot_dir(bot_id) is not None:    # không bao giờ ghi đè / dùng lại dữ liệu bot có sẵn
        raise HTTPException(409, f"Bot {bot_id} đã tồn tại")
    params = {
        "bot_id": bot_id,
        "mode": body.mode,
        "symbols": body.symbols,
        "capital": body.capital,
        "base_frame": body.base_frame or "1h",
        "confirm_live": bool(body.confirm_live),
        "enter_on_start": bool(body.enter_on_start),
    }
    if body.signal_tf:
        params["signal_tf"] = body.signal_tf
    if body.code:
        params["code"] = body.code
    elif body.alpha_id:
        params["alpha_id"] = body.alpha_id
    if body.params is not None:
        params["params"] = body.params
    if book_source:
        params["book_source"] = book_source
    if body.backtest_job_id is not None:
        params["backtest_job_id"] = body.backtest_job_id

    try:
        job_id = launch("live_bot", params)
    except JobBusy as e:
        info = running_live_bot_info()
        raise HTTPException(429, detail={
            "code": "BOT_LIMIT_REACHED",
            "message": str(e),
            "running_bots": info["running_bots"],
            "max_bots": info["max_bots"],
            "slots_left": info["slots_left"],
        })
    except Exception as e:
        raise HTTPException(500, f"Không thể khởi động job bot: {e}")

    return {"ok": True, "bot_id": bot_id, "job_id": job_id, "mode": body.mode}


@router.get("/live/candidates")
def get_live_candidates() -> Dict[str, Any]:
    """Chiến lược đã backtest có lãi (ret_pct > 0) để chọn chạy bot; id dùng làm alpha_id của POST /live/bot. Chỉ đọc."""
    from backend.analys.alpha import strategies
    rows = strategies.live_candidates()
    return {"candidates": rows, "n": len(rows)}


class CandidateBacktestRequest(BaseModel):
    alpha_id: str
    signal_tf: str
    symbols: List[str] = Field(default_factory=lambda: ["BTC-USDT-SWAP"])
    capital: float = Field(1000.0, gt=0)
    start: Optional[str] = None
    end: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    book_source: Optional[str] = Field(None, pattern="^(main|explore)$")


@router.post("/live/candidate_backtest")
def post_candidate_backtest(body: CandidateBacktestRequest) -> Dict[str, Any]:
    """Chạy backtest cho cấu hình tuỳ chỉnh từ bộ chọn (E2) ở chế độ Nhanh trước khi bật bot."""
    from backend.data.data import run_defaults
    from backend.analys.alpha import strategies as alpha_store
    from backend.analys.alpha import strategies as sb

    defaults = run_defaults()
    start = body.start or defaults.get("start")
    end = body.end or defaults.get("end")

    from backend.jobs import tasks
    try:
        rs = tasks.resolve_strategy(body.alpha_id, None, body.signal_tf, body.params, body.symbols, body.book_source)
    except tasks.ConfigError as e:
        raise HTTPException(400, "; ".join(f"{f}: {m}" for f, m in e.errors))
    rec = alpha_store.get_user_alpha(str(body.alpha_id))
    if rec is not None:
        job_id = launch("custom_backtest", {"code": rec["code"], "symbols": body.symbols, "start": start, "end": end, "initial_capital": body.capital,
                                            "run_frame": body.signal_tf, "position": rs["position"] or None})
        kind = "custom_backtest"
    else:
        syms_str = ",".join(s.split("@")[0].split("-")[0] for s in body.symbols)
        job_id = launch("book_backtest", {"strategies": [{"id": body.alpha_id, "params": rs["params"]}], "symbols": syms_str, "timeframe": body.signal_tf,
                                          "start": start, "end": end, "risk_per_trade": rs["params"].get("risk_per_trade_pct")})
        kind = "book_backtest"
    tasks.picker_backtest_save(job_id, {"alpha_id": body.alpha_id, "signal_tf": body.signal_tf, "symbols": body.symbols, "params": body.params or {},
                                        "book_source": rs.get("book"), "hash": rs["hash"]})
    return {"ok": True, "job_id": job_id, "kind": kind, "hash": rs["hash"]}


@router.get("/live/candidate_schema")
def get_candidate_schema(alpha_id: str, signal_tf: str = Query(...), book_source: Optional[str] = Query(None, pattern="^(main|explore)$")) -> Dict[str, Any]:
    """Trường tham số có thể chỉnh của chiến lược trong bộ chọn: {kind, fields: {khoá: spec}, defaults: tham số đã giải ở signal_tf}. Cùng resolve_strategy với backtest/bot."""
    from backend.jobs import tasks
    from backend.analys.alpha import strategies as alpha_store
    from backend.analys.alpha import strategies as sb

    try:
        rs = tasks.resolve_strategy(alpha_id, None, signal_tf, None, None, book_source)
    except tasks.ConfigError as e:
        raise HTTPException(400, "; ".join(f"{f}: {m}" for f, m in e.errors))
    if rs["kind"] == "system":
        return {"kind": "system", "fields": sb.BY_ID[alpha_id]["params_schema"], "defaults": rs["params"]}
    fields = {k: {"type": "text" if isinstance(v, str) else "float", "default": v, "label_vi": k, "group": "position"} for k, v in rs["position"].items()}
    return {"kind": "user", "fields": fields, "defaults": dict(rs["position"])}


@router.get("/live/bots")
def get_bots_list(mode: Optional[str] = Query(None, pattern="^(paper|testnet|live)$")) -> Dict[str, Any]:
    """Danh sách các bot: mode, trạng thái, uptime, PnL hiện tại."""
    bots = list_bots(mode=mode)
    return {"bots": bots}


@router.get("/live/resource_status")
def get_live_resource_status() -> Dict[str, Any]:
    """Trạng thái tài nguyên bot live: số bot đang chạy, giới hạn, RAM khả dụng. Dùng cho UI cảnh báo khi sắp hết slot."""
    return running_live_bot_info()


@router.post("/live/bots/stop")
def post_batch_stop(body: BatchBotRequest) -> Dict[str, Any]:
    """Dừng nhiều bot cùng lúc (batch stop). close=True đóng vị thế. Trả {ok, results: [{bot_id, ok, error?}]}."""
    results = []
    for bid in body.bot_ids:
        try:
            res = stop_bot(bid, close_positions=bool(body.close))
            results.append({"bot_id": bid, "ok": bool(res.get("ok")), "error": res.get("message") if not res.get("ok") else None})
        except Exception as e:
            results.append({"bot_id": bid, "ok": False, "error": str(e)})
    return {"ok": all(r["ok"] for r in results), "results": results}


@router.delete("/live/bots")
def delete_batch_bots(body: BatchBotRequest) -> Dict[str, Any]:
    """Xoá nhiều bot đã dừng/lỗi cùng lúc (batch delete). Bot đang chạy sẽ bỏ qua và báo lỗi."""
    results = []
    for bid in body.bot_ids:
        try:
            res = delete_bot(bid, body.mode)
            if res.get("running"):
                results.append({"bot_id": bid, "ok": False, "error": "Bot đang chạy, hãy dừng trước"})
            elif not res.get("ok"):
                results.append({"bot_id": bid, "ok": False, "error": res.get("message", "Không tìm thấy bot")})
            else:
                results.append({"bot_id": bid, "ok": True})
        except Exception as e:
            results.append({"bot_id": bid, "ok": False, "error": str(e)})
    return {"ok": all(r["ok"] for r in results), "results": results}


@router.get("/live/summary")
def get_live_summary() -> Dict[str, Any]:
    """Tổng hợp theo nhóm paper / live (testnet+live) từ dữ liệu bot thật: số bot, vốn, PnL, MDD lớn nhất, số lệnh khớp; tách riêng bot chưa có lệnh (D3)."""
    groups: Dict[str, Dict[str, Any]] = {}
    for g in ("paper", "live"):
        groups[g] = {"bots": 0, "running": 0, "stopped": 0, "idle_bots": 0, "active_bots": 0, "capital": 0.0, "pnl_usd": 0.0, "pnl_pct": None, "mdd_pct": None, "fills": 0}
    for b in list_bots():
        a = groups["paper" if b.get("mode") == "paper" else "live"]
        a["bots"] += 1
        a["running" if b.get("status") == "running" else "stopped"] += 1
        a["capital"] += float(b.get("capital") or 0.0)
        a["pnl_usd"] += float(b.get("pnl_usd") or 0.0)
        m = b.get("mdd_pct")
        if isinstance(m, (int, float)):
            a["mdd_pct"] = m if a["mdd_pct"] is None else max(a["mdd_pct"], m)
        bot_id = b.get("bot_id")
        n_fills = len(get_bot_trades(bot_id, raw=True)) if bot_id else 0
        a["fills"] += n_fills
        if n_fills == 0:
            a["idle_bots"] += 1
        else:
            a["active_bots"] += 1
    for a in groups.values():
        a["pnl_usd"] = round(a["pnl_usd"], 4)
        a["pnl_pct"] = round(a["pnl_usd"] / a["capital"] * 100.0, 4) if a["capital"] else None
    return groups


@router.get("/live/bot/{bot_id}")
def get_bot_by_id(bot_id: str) -> Dict[str, Any]:
    """Chi tiết bot: spec, trạng thái, đường vốn và các vị thế mở."""
    detail = get_bot_detail(bot_id)
    if detail is None:
        raise HTTPException(404, f"Không tìm thấy bot {bot_id}")
    return detail


@router.post("/live/bot/{bot_id}/stop")
def post_stop_bot(
    bot_id: str,
    body: Optional[StopBotRequest] = None,
    close: Optional[bool] = Query(None, description="Đóng các vị thế đang mở (nếu không truyền trong body)")
) -> Dict[str, Any]:
    """ĐƯỜNG DUY NHẤT dừng bot. close=True: huỷ lệnh chờ + đóng đúng vị thế CỦA BOT (reduce-only, không đụng bot khác); close=False: giữ nguyên lệnh + vị thế."""
    close_val = True
    if body is not None and body.close is not None:
        close_val = body.close
    elif close is not None:
        close_val = close
    res = stop_bot(bot_id, close_positions=close_val)
    if not res.get("ok"):
        raise HTTPException(404, res.get("message", f"Không tìm thấy bot {bot_id}"))
    return res


@router.delete("/live/bot/{bot_id}")
def delete_bot_by_id(bot_id: str, mode: Optional[str] = Query(None, pattern="^(paper|testnet|live)$")) -> Dict[str, Any]:
    """Xoá bot đã dừng/lỗi/lưu trữ (xoá thư mục data/live/<mode>/<bot_id>)."""
    res = delete_bot(bot_id, mode)
    if res.get("running"):
        raise HTTPException(409, "Dừng bot trước khi xoá")
    if not res.get("ok"):
        raise HTTPException(404, res.get("message", f"Không tìm thấy bot {bot_id}"))
    return res


@router.post("/live/bot/{bot_id}/resume")
def post_resume_bot(bot_id: str) -> Dict[str, Any]:
    """Chạy lại bot đã dừng (status=stopped). SỮd dụng launch_params đã lưu trong bot.json. Bot đang chạy → lỗi 409."""
    from backend.core import live as lv
    from backend.jobs.runner.live import _launch_params
    b_dir = lv.find_bot_dir(bot_id)
    if not b_dir:
        raise HTTPException(404, f"Không tìm thấy bot {bot_id}")
    meta = lv._read_json(os.path.join(b_dir, "bot.json"))
    if not meta:
        raise HTTPException(404, f"Bot {bot_id} thiếu metadata")
    current_status = lv.bot_status(meta, b_dir)
    if current_status in ("running", "starting", "resuming"):
        raise HTTPException(409, f"Bot đang chạy (trạng thái: {current_status}), không cần chạy lại")
    params = _launch_params(meta)
    if not params:
        raise HTTPException(400, "Không tìm thấy cấu hình khởi động của bot (thiếu launch_params)")
    params.update(bot_id=bot_id, mode=meta.get("mode", "paper"), resume=True)
    # Xóa cờ stop cũ nếu có
    stop_file = os.path.join(b_dir, "stop")
    if os.path.isfile(stop_file):
        try:
            os.remove(stop_file)
        except OSError:
            pass
    lv.set_status(b_dir, "resuming")
    try:
        job_id = launch("live_bot", params)
    except JobBusy as e:
        lv.set_status(b_dir, "stopped")
        info = running_live_bot_info()
        raise HTTPException(429, detail={
            "code": "BOT_LIMIT_REACHED",
            "message": str(e),
            "running_bots": info["running_bots"],
            "max_bots": info["max_bots"],
            "slots_left": info["slots_left"],
        })
    except Exception as e:
        lv.set_status(b_dir, "stopped")
        raise HTTPException(500, f"Không thể chạy lại bot: {e}")
    return {"ok": True, "bot_id": bot_id, "job_id": job_id, "status": "resuming"}


@router.get("/live/bot/{bot_id}/trades")
def get_bot_trades_by_id(bot_id: str) -> Dict[str, Any]:
    """Lịch sử lệnh/khớp từ events.jsonl của bot."""
    detail = get_bot_detail(bot_id)
    if detail is None:
        raise HTTPException(404, f"Không tìm thấy bot {bot_id}")
    trades = get_bot_trades(bot_id)
    return {"bot_id": bot_id, "trades": trades, "fills": trades}


@router.get("/live/bot/{bot_id}/chart")
def get_bot_chart(bot_id: str, frame: Optional[str] = Query(None, pattern="^(1m|5m|15m|1h|4h|24h)$"), replay: int = Query(0, ge=0, le=1)) -> Dict[str, Any]:
    """Nến + lệnh khớp thật + tín hiệu của bot (+ replay backtest cùng spec khi replay=1). Chỉ đọc, có bộ nhớ đệm theo (bot, khung, lệnh khớp cuối)."""
    from backend.jobs.runner.live import build_chart
    try:
        return build_chart(bot_id, frame=frame, replay=bool(replay))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/live/bot/{bot_id}/compare")
def get_bot_compare_by_id(bot_id: str) -> Dict[str, Any]:
    """Đối chiếu bot thực tế với backtest replay (B6)."""
    from backend.analys.metrics.trades import compare_events
    detail = get_bot_detail(bot_id)
    if detail is None:
        raise HTTPException(404, f"Không tìm thấy bot {bot_id}")
    # Chưa có backtest replay cùng spec (B6) nên bóng sim = rỗng: KHÔNG tự đối chiếu với chính nó. matched = số cặp ghép được (0 khi chưa có replay).
    comp = compare_events(get_bot_trades(bot_id, raw=True), [], timeframe=(detail.get("spec") or {}).get("base_frame") or "1h")
    matched = int(sum(k.get("matched", 0) for k in comp.get("kinds", {}).values()))
    return {"bot_id": bot_id, **comp, "matched": matched, "replay_available": False}


# ─── Endpoint cũ (chỉ đọc cho dữ liệu lưu trữ trước P17) ─────────────────────
_MODE = Query("paper", pattern="^(paper|demo|live)$")
_VENUE = Query("okx", pattern="^(okx|binance)$")
_BOOK = Query("main", pattern="^(main|explore)$")
_ENGINE = Query(None, pattern="^(legacy|unified)$")


@router.get("/live/bot")
def get_legacy_bot(mode: str = _MODE, venue: str = _VENUE, events: int = Query(50, ge=0, le=500), book: str = _BOOK, engine: Optional[str] = _ENGINE) -> Dict[str, Any]:
    """Trạng thái bot CŨ (chỉ đọc từ data/live): status = 'archived'."""
    return archived_bot(venue, mode, book, engine, events)


@router.get("/live/trades")
def get_legacy_trades(mode: str = _MODE, venue: str = _VENUE, limit: int = Query(200, ge=1, le=2000), book: str = _BOOK, engine: Optional[str] = _ENGINE) -> Dict[str, Any]:
    """Lệnh, vị thế, đường vốn của bot cũ."""
    return archived_trades(venue, mode, book, engine, limit)


@router.get("/live/compare")
@router.get("/live/compare_events")
def get_legacy_compare(mode: str = Query("demo", pattern="^(demo|live)$"), venue: str = _VENUE, book: str = _BOOK, engine: Optional[str] = _ENGINE) -> Dict[str, Any]:
    try:
        return archived_compare_events(venue, mode, book, engine)
    except FileNotFoundError:
        raise HTTPException(404, f"không có dữ liệu bot cũ {venue} {mode} ({book})")


@router.get("/live/archive")
def get_archive() -> Dict[str, Any]:
    """Các bot cũ còn dữ liệu trên đĩa."""
    return {"bots": archived_bots_index()}


@router.get("/live/positions")
@router.get("/live/balance")
@router.get("/live/status")
@router.post("/live/order")
@router.post("/live/cancel")
def live_manual_not_supported() -> Any:
    raise HTTPException(501, detail={"code": "NOT_SUPPORTED", "message": "Đặt lệnh thủ công không được hỗ trợ ở T5"})


ROUTERS = [router]
