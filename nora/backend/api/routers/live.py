"""Bot giao dịch theo sổ (/api/studio/live): khởi chạy job nền `live_bot` (OKX: paper | demo | live) và xem trạng thái (state.json + sự kiện).
Dừng bot: POST /api/studio/book/jobs/{job_id}/cancel (SIGTERM -> bot thoát sau bước hiện tại, trạng thái đã lưu)."""
import json
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.jobs import batch as batch_jobs

router = APIRouter(prefix="/api/studio/live", tags=["live"])


class BotRequest(BaseModel):
    mode: str = Field("paper", pattern="^(paper|demo|live)$",
                      description="paper: dữ liệu thật, khớp mô phỏng; demo: OKX Demo Trading (vốn ảo); live: OKX tài khoản thật")
    venue: str = Field("okx", pattern="^(okx|binance)$", description="okx = sàn triển khai; binance chỉ để tham khảo (paper / testnet)")
    once: bool = Field(False, description="chỉ chạy một bước (kiểm tra)")
    capital: float = Field(10000.0, gt=0, le=1e9, description="vốn ban đầu của chế độ paper")
    confirm_live: bool = Field(False, description="bắt buộc true với mode live (vốn thật)")
    book: str = Field("main", pattern="^(main|explore)$",
                      description="main = sổ đã kiểm định; explore = sổ thử nghiệm data/alphas/explore (chỉ paper/demo)")


def _running(venue: str, mode: str, book: str = "main"):
    return [j for j in batch_jobs.list_jobs(limit=50, kind="live_bot")
            if j.get("status") in ("running", "queued") and (j.get("params") or {}).get("mode") == mode
            and (j.get("params") or {}).get("venue", "okx") == venue and (j.get("params") or {}).get("book", "main") == book]


def _sdir(venue: str, mode: str, book: str) -> str:
    from backend.db.data_layout import cache_dir
    from backend.live.bot import state_key
    return cache_dir(None, "live", state_key(venue, mode, book))


@router.post("/bot")
def start_bot(req: BotRequest) -> Dict[str, Any]:
    if req.mode == "live" and not req.confirm_live:
        raise HTTPException(422, "mode live đặt lệnh bằng vốn thật — cần confirm_live=true")
    if req.mode == "live" and req.book == "explore":
        raise HTTPException(422, "sổ thử nghiệm không chạy live")
    if _running(req.venue, req.mode, req.book):
        raise HTTPException(409, f"bot {req.venue} {req.mode} ({req.book}) đang chạy (job {_running(req.venue, req.mode, req.book)[0].get('id')})")
    return batch_jobs.http_launch("live_bot", {"mode": req.mode, "venue": req.venue, "once": req.once, "capital": req.capital,
                                               "confirm_live": req.confirm_live, "book": req.book})


@router.get("/bot")
def bot_status(mode: str = Query("paper", pattern="^(paper|demo|live)$"), venue: str = Query("okx", pattern="^(okx|binance)$"),
               events: int = Query(50, ge=0, le=500), book: str = Query("main", pattern="^(main|explore)$")) -> Dict[str, Any]:
    d = _sdir(venue, mode, book)
    state, evs = None, []
    try:
        with open(os.path.join(d, "state.json"), encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        pass
    try:
        with open(os.path.join(d, "events.jsonl"), encoding="utf-8") as fh:
            evs = [json.loads(x) for x in fh.readlines()[-events:]] if events else []
    except (OSError, ValueError):
        pass
    if state:
        state = {**state, "trades": (state.get("trades") or [])[-100:]}
    return {"venue": venue, "mode": mode, "running": [j.get("id") for j in _running(venue, mode, book)], "state": state,
            "events": evs, "book": book}


def _equity_series(d: str, cap: int = 2000):
    """Đường vốn của bot từ events.jsonl (sự kiện "step": bar + equity), mỗi nến một điểm (giữ bản cuối), tối đa `cap` điểm cuối.
    -> (equity_series [{t, equity}], started = thời điểm "start" đầu tiên của sổ hiện tại hoặc None,
        alerts = sự kiện crit / warn từ lần khởi động gần nhất, tối đa 5 cái cuối)."""
    by_bar, started, alerts = {}, None, []
    try:
        with open(os.path.join(d, "events.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("kind") == "start":
                    started = e.get("t") if started is None else started
                    alerts = []
                elif e.get("kind") in ("crit", "warn"):
                    alerts = (alerts + [e])[-5:]
                elif e.get("kind") == "step" and isinstance(e.get("bar"), (int, float)) and isinstance(e.get("equity"), (int, float)):
                    by_bar[int(e["bar"])] = float(e["equity"])
    except OSError:
        pass
    return [{"t": t, "equity": v} for t, v in sorted(by_bar.items())][-cap:], started, alerts


@router.get("/trades")
def bot_trades(mode: str = Query("paper", pattern="^(paper|demo|live)$"), venue: str = Query("okx", pattern="^(okx|binance)$"),
               limit: int = Query(200, ge=1, le=2000), book: str = Query("main", pattern="^(main|explore)$")) -> Dict[str, Any]:
    """Lệnh của bot để xem biểu đồ tín hiệu: lệnh sàn (demo/live: state.json) + lệnh paper (paper.pkl, cùng engine backtest), vị thế đang mở.
    Thời gian theo ms. book_kind cho biết sổ (main | explore) để gọi POST /api/studio/chart/explain (book + strategy_id)."""
    import pickle
    d = _sdir(venue, mode, book)
    state: Dict[str, Any] = {}
    try:
        with open(os.path.join(d, "state.json"), encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        pass
    paper_trades, paper_pos = [], []
    try:
        with open(os.path.join(d, "paper.pkl"), "rb") as fh:
            pb = pickle.load(fh)
        paper_trades, paper_pos = list(pb.trades)[-limit:], pb.positions()
    except (OSError, EOFError, pickle.UnpicklingError, AttributeError):
        pass
    exec_pos = [{"symbol": s, **p} for s, p in (state.get("positions") or {}).items()]
    kind = state.get("book_kind") or (book if book == "explore" else None)
    if kind is None:                                   # trạng thái cũ chưa ghi book_kind: nhận theo generated_at của sổ thử nghiệm
        try:
            from backend.core.params.presets import alphas_dir
            with open(os.path.join(alphas_dir(), "explore", "book.json"), encoding="utf-8") as fh:
                kind = "explore" if json.load(fh).get("generated_at") == state.get("book") else "main"
        except (OSError, ValueError):
            kind = "main"
    strategies, symbols, tf = [], [], None
    try:
        from backend.live.bot import load_book
        b = load_book(kind=kind, mode="paper")
        strategies = [{"id": x["id"], "side": x["side"], "family": x.get("family"), "unvalidated": x["id"] in (b.get("unvalidated") or [])}
                      for x in b["strategies"]]
        symbols, tf = [u.split("@")[0] for u in b["universe"]], b.get("timeframe")
    except (SystemExit, OSError, ValueError):
        pass
    series, started, alerts = _equity_series(d)
    return {"venue": venue, "mode": mode, "book_kind": kind, "strategies": strategies, "symbols": symbols, "timeframe": tf,
            "running": [j.get("id") for j in _running(venue, mode, book)],
            "equity": state.get("equity"), "equity_series": series, "started": started,
            "halted": bool(state.get("halted")), "peak_equity": state.get("peak_equity"), "alerts": alerts, "exec": {"trades": (state.get("trades") or [])[-limit:], "positions": exec_pos},
            "paper": {"trades": paper_trades, "positions": paper_pos, "summary": state.get("paper")}}


@router.get("/compare")
def bot_compare(mode: str = Query("demo", pattern="^(demo|live)$"), venue: str = Query("okx", pattern="^(okx|binance)$"),
                book: str = Query("main", pattern="^(main|explore)$")) -> Dict[str, Any]:
    """Lệnh sàn (khớp thật) ghép với lệnh paper bóng cùng nến (engine): chênh giá vào/đóng (bps), % lãi lỗ, số tầng DCA, lệnh lệch."""
    import pickle
    from backend.live.compare import compare_trades
    d = _sdir(venue, mode, book)
    try:
        with open(os.path.join(d, "state.json"), encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        raise HTTPException(404, f"chưa có trạng thái bot {venue} {mode} ({book})")
    try:
        with open(os.path.join(d, "paper.pkl"), "rb") as fh:
            paper = list(pickle.load(fh).trades)
    except (OSError, EOFError, pickle.UnpicklingError, AttributeError):
        paper = []
    tf = None
    try:
        from backend.live.bot import load_book
        tf = load_book(kind=state.get("book_kind") or book, mode="paper").get("timeframe")
    except (SystemExit, OSError, ValueError):
        pass
    return {"venue": venue, "mode": mode, "book": book, "timeframe": tf, **compare_trades(state.get("trades") or [], paper, tf or "1h")}
