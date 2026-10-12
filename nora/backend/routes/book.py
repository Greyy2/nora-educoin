"""API sổ chiến lược: xem sổ hiện tại, chạy backtest / WFA danh mục / Monte Carlo như job nền, trạng thái job, dashboard + lệnh danh mục.

Job nặng chạy ở tiến trình riêng qua ops/run_limited.sh (backend/jobs/runner.py); handler ở đây chỉ validate + khởi chạy / đọc file
nên nhanh và là `def` thường (FastAPI chạy trong threadpool). Logic Monte Carlo ở carlo/carlo.py (mc_report).
"""
import json
import math
import os
import threading
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.data.data import benchmark_daily_closes
from backend.metrics import charts as feeds
from backend.metrics import charts as pd_mod
from backend.routes import process as modes
from backend.jobs import runner as batch_jobs
from backend.routes import process as batch_jobs_routes
from backend.models.storage import alpha_file
from backend.carlo.carlo import mc_report, MC_MAX_SIMULATIONS, MC_MIN_SIMULATIONS, MC_RUIN_THRESHOLD_PCT, STRESS_MAX_MDD_PCT, STRESS_SCENARIOS

book_router = APIRouter(prefix="/api/studio/book", tags=["book"])

MC_MIN_DAYS, MC_MAX_DAYS = 20, 5000
from backend.strategies import metrics_row as _metrics   # MỘT định nghĩa (strategies.py), cùng khoá/logic


# ─── Mô hình yêu cầu ────────────────────────────────────────────────────────
MODE_FIELD = dict(pattern="^(basic|advanced)$", description="basic: máy chủ BỎ QUA tham số client, dùng preset (data/alpha/presets.json); "
                                                          "advanced: kiểm mọi tham số theo params_schema (xem docs/ui_contract.md §\"Chế độ chạy\")")


class StrategyIn(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    params: Dict[str, Any] = Field(default_factory=dict, description="Chỉ dùng ở mode=advanced: khoá theo params_schema (số hoặc khung thời gian \"4h\"); "
                                                                      "thiếu khoá nào lấy từ preset. mode=basic: bỏ qua")


class _DateRange(BaseModel):
    @field_validator("start", "end", check_fields=False)
    @classmethod
    def _date(cls, v):
        return batch_jobs_routes.check_date(v) if v else v


class BacktestRequest(_DateRange):
    strategies: Optional[List[StrategyIn]] = Field(None, max_length=16, description="Bỏ trống = dùng data/alpha/book.json")
    symbols: Optional[List[str]] = Field(None, max_length=16, description="Mặc định cả vũ trụ (perp). Tài sản DEX bị từ chối 501 NOT_READY (Nautilus không hỗ trợ AMM)")
    start: str
    end: str
    risk_per_trade_pct: Optional[float] = Field(None, gt=0.0, le=5.0)
    stop_fill: str = Field("level", pattern="^(level|extreme)$")
    regime: bool = Field(False, description="Bật lọc regime + cầu chì (metrics/regime.py, models/params.py REGIME_MAP)")
    timeframe: str = Field("15m", pattern="^(15m|1h|4h)$", description="Khung chạy (nến mô phỏng); khung tín hiệu nhỏ hơn được nâng lên")
    run_frame: Optional[str] = Field(None, pattern="^(15m|1h|4h)$", description="Khung chạy (engine base_frame); có thì ghi đè timeframe. Giá trị hợp lệ = meta.frames.book")
    mode: str = Field("basic", **MODE_FIELD)
    data: str = Field("candle", pattern="^(candle|tick)$", description="candle: nến; tick: 501 NOT_READY (backtest tick/AMM chỉ dành cho DEX, Nautilus không hỗ trợ)")
    latency_ms: Optional[int] = Field(None, ge=0, le=3_600_000, description="Chỉ data=tick: trễ từ lúc nến đóng tới lúc bot hành động; bỏ trống = thời gian một block của mạng")
    gas_usd: Optional[float] = Field(None, ge=0.0, le=1000.0, description="Chỉ data=tick: gas mỗi swap (USD); bỏ trống = cấu hình của mạng")


    @model_validator(mode="after")
    def _run_frame(self):
        if self.run_frame:
            self.timeframe = self.run_frame
        return self


class WfaStrategyIn(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    configs: List[Dict[str, Any]] = Field(..., min_length=1, max_length=batch_jobs_routes.MAX_WFA_CONFIGS,
                                          description="1 cấu hình = tham số cố định (WFA chỉ kiểm OOS cuộn); mode=basic: bỏ qua, dùng preset")


class WfaRequest(_DateRange):
    report_dir: Optional[str] = Field(None, max_length=256, description="Lần chạy build_strategy_book trong data/alpha/book/")
    include_rejected: bool = False
    candidates: Optional[List[str]] = Field(None, max_length=16)
    strategies: Optional[List[WfaStrategyIn]] = Field(None, max_length=batch_jobs_routes.MAX_WFA_STRATEGIES,
                                                       description="Cấu hình do người dùng chọn: dùng ĐÚNG các cấu hình này")
    symbols: Optional[List[str]] = Field(None, max_length=16)
    n: int = Field(3, ge=1, le=50)
    start: Optional[str] = None
    end: Optional[str] = None
    train_days: Optional[int] = Field(None, ge=7, le=1000)
    test_days: Optional[int] = Field(None, ge=1, le=365)
    risk_per_trade_pct: Optional[float] = Field(None, gt=0.0, le=5.0)
    mode: str = Field("basic", **MODE_FIELD)
    step_days: Optional[int] = Field(None, ge=1, le=365, description="Chỉ advanced: bước trượt fold (mặc định = test_days)")
    embargo_days: Optional[int] = Field(None, ge=0, le=30, description="Chỉ advanced: chưa hỗ trợ (>0 -> 422)")
    sims: Optional[int] = Field(None, ge=100, le=MC_MAX_SIMULATIONS, description="Chỉ advanced: số kịch bản MC của gate WFA; < 10.000 -> custom_gates")
    mc_seed: Optional[int] = Field(None, ge=0, le=2**31 - 1)
    timeframe: str = Field("15m", pattern="^(15m|1h|4h)$", description="Khung chạy (nến mô phỏng); khung tín hiệu nhỏ hơn được nâng lên")
    regime: str = Field("off", pattern="^(off|learn)$",
                        description="learn: mỗi fold học bảng regime ↔ chiến lược trên train rồi áp lên test (metrics/regime.learn_map)")

    @model_validator(mode="after")
    def _one_source(self):
        if sum(map(bool, (self.report_dir, self.candidates, self.strategies))) != 1:
            raise ValueError("chọn đúng một: report_dir, candidates hoặc strategies")
        return self


class McRequest(BaseModel):
    wfa_job_id: Optional[str] = Field(None, max_length=64, description="Job book_wfa đã xong (lấy chuỗi lợi suất ngày OOS)")
    daily_returns: Optional[List[float]] = Field(None, min_length=MC_MIN_DAYS, max_length=MC_MAX_DAYS,
                                                 description="Lợi suất ngày dạng số thập phân (0.01 = 1%)")
    basis: str = Field("extreme", pattern="^(extreme|level)$", description="Cơ sở chuỗi lợi suất ngày OOS của job WFA: extreme (điểm xấu nhất trong ngày) hoặc level (đóng cửa ngày)")
    simulations: int = Field(MC_MIN_SIMULATIONS, ge=100, le=MC_MAX_SIMULATIONS,
                             description="Số kịch bản bootstrap; < 10.000 vẫn chạy nhưng gate.gate_eligible = false (không dùng làm gate); tối đa 50.000")
    block_days: int = Field(5, ge=1, le=30, description="Độ dài khối bootstrap (số ngày liên tiếp mỗi lần lấy mẫu)")
    horizon_days: int = Field(365, ge=5, le=730, description="Chân trời mô phỏng: số ngày của mỗi kịch bản")
    ruin_threshold_pct: float = Field(MC_RUIN_THRESHOLD_PCT, gt=0.0, le=100.0, description="Ngưỡng phá sản: một đường mô phỏng tính là cháy khi MDD >= ngưỡng này (%)")
    seed: int = Field(7, ge=0, le=2**31 - 1, description="Hạt giống ngẫu nhiên (cùng seed cho cùng kết quả)")
    scale: float = Field(1.0, gt=0.0, le=10.0, description="Hệ số nhân lên chuỗi lợi suất ngày (kích cỡ vị thế)")
    stress_max_mdd_pct: float = Field(STRESS_MAX_MDD_PCT, gt=0.0, le=100.0, description="MDD tối đa cho phép của MỌI kịch bản cực xấu (gate)")
    extra_cost_daily_pct: Optional[float] = Field(None, ge=0.0, le=5.0,
                                                  description="Phí bổ sung (%/ngày hoạt động) cho kịch bản cost_x2; bỏ trống = hằng số bảo thủ 0,07%")
    mode: str = Field("basic", **MODE_FIELD)
    stress_scenarios: Optional[List[str]] = Field(None, max_length=len(STRESS_SCENARIOS), description="Chỉ advanced: tập con kịch bản cực xấu (mặc định đủ cả); thiếu -> custom_gates")

    @model_validator(mode="after")
    def _one_source(self):
        if bool(self.wfa_job_id) == bool(self.daily_returns):
            raise ValueError("chọn đúng một: wfa_job_id hoặc daily_returns")
        return self


# ─── Đọc sổ / báo cáo ───────────────────────────────────────────────────────
def book_path() -> str:
    """Sổ đang dùng (models/storage.alpha_file: alpha/book.json; NORA_BOOK_PATH / NORA_ALPHAS_DIR ghi đè)."""
    return alpha_file("book")




def _evidence_summary(ev: Dict[str, Any]) -> Dict[str, Any]:
    top = (ev.get("dev1_top") or [{}])[0]
    return {"accepted": ev.get("accepted"), "stability": ev.get("stability"), "dev1_tried": ev.get("dev1_tried"),
            "dev1": _metrics(top.get("dev1")), "dev2_level": _metrics(top.get("dev2_level")),
            "dev2_extreme": _metrics(top.get("dev2_extreme"))}


def _book_summary(book: Dict[str, Any]) -> Dict[str, Any]:
    final = (book.get("evidence") or {}).get("final") or {}
    return {
        "status": book.get("status"), "holdout_pass": book.get("holdout_pass"), "generated_at": book.get("generated_at"),
        "source": book.get("source"), "code": book.get("code"), "universe": book.get("universe"), "windows": book.get("windows"),
        "risk": book.get("risk"), "risk_per_trade_pct": book.get("risk_per_trade_pct"),
        "strategies": [{"id": s["id"], "family": s.get("family"), "side": s.get("side"), "description": s.get("description"),
                        "params": s.get("params"), "evidence": _evidence_summary(s.get("evidence") or {})}
                       for s in book.get("strategies", [])],
        "evidence": {k: _metrics(v) for k, v in final.items()},
        "rejected_candidates": sorted((book.get("rejected_candidates") or {})),
    }


def latest_wfa_summary() -> Optional[Dict[str, Any]]:
    from backend.models.storage import run_dir
    base = run_dir("wfa")
    for name in sorted(os.listdir(base) if os.path.isdir(base) else (), reverse=True):
        path = os.path.join(base, name, "report.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                r = json.load(fh)
        except (OSError, ValueError):
            continue
        s = r.get("summary") or {}
        return {
            "report_dir": name, "window": r.get("window"), "config": r.get("config"), "risk_per_trade_pct": r.get("risk_per_trade_pct"),
            "candidates": [{"id": c.get("id"), "configs": len(c.get("configs") or [])} for c in r.get("candidates") or []],
            "gate": r.get("gate"), "source": r.get("source"),
            "summary": {k: s.get(k) for k in ("n_folds", "n_traded_folds", "positive_folds", "positive_ratio_pct", "avg_is_ret_pct",
                                              "compounded_oos_ret_pct", "worst_fold_mdd_pct", "oos_days", "oos_trades", "mc")},
        }
    return None


def default_params(space: Dict[str, List[Any]]) -> Dict[str, Any]:
    """Giá trị GIỮA của mỗi khoá trong không gian tham số (cùng quy tắc backend/jobs/evaluate.py._mid_params)."""
    return {k: v[len(v) // 2] for k, v in space.items()}


def _assets() -> List[Dict[str, Any]]:
    """Tài sản có dữ liệu: [{symbol, venue cex, market perp, candles{start_ts,end_ts}, ticks null}]. DEX/AMM không được Nautilus hỗ trợ nên không được đưa ra (dữ liệu DEX vẫn nằm trong kho)."""
    from backend.data.data import coverage
    return [{"symbol": a["symbol"], "venue": "cex", "market": "perp",
             "candles": {"start_ts": a["start_ts"], "end_ts": a["end_ts"]}, "ticks": None} for a in coverage()]


def _catalog() -> List[Dict[str, Any]]:
    from backend.strategies import CANDIDATES
    return [{"id": c["id"], "family": c["family"], "side": c["side"], "description": c["description"],
             "space": c["space"], "default_params": default_params(c["space"])} for c in CANDIDATES]


def _universe_windows(book: Optional[Dict[str, Any]]):
    """(universe, windows dạng ngày): lấy từ sổ nếu có, không thì từ vũ trụ + dữ liệu hiện có (như build_strategy_book.windows)."""
    from backend.strategies import perp_symbols
    universe = (book or {}).get("universe") or perp_symbols()
    windows = (book or {}).get("windows")
    if not windows:
        try:
            import pandas as pd
            from backend.data.data import read_manifest
            ms = [read_manifest(s) for s in universe]
            start = max(int(m["start_ts"]) for m in ms) + 20 * 86_400_000
            end = min(int(m["end_ts"]) for m in ms)
            span = end - start
            fmt = lambda t: f"{pd.Timestamp(int(t), unit='ms'):%Y-%m-%d}"
            windows = {"start": fmt(start), "dev1_end": fmt(start + int(span * 0.4)), "dev2_end": fmt(start + int(span * 0.8)),
                       "end": fmt(end)}
        except (TypeError, ValueError, KeyError):   # thiếu dữ liệu/manifest
            windows = None
    return universe, windows


# ─── Điểm cuối ──────────────────────────────────────────────────────────────
@book_router.get("/")
def get_book():
    book, raw = None, None
    path = book_path()
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            book = _book_summary(raw)
        except (OSError, ValueError, KeyError) as e:
            raise HTTPException(500, f"book.json hỏng: {e}")
    wfa = latest_wfa_summary()
    universe, windows = _universe_windows(raw)
    # "wfa" giữ cho client cũ; "latest_wfa" + "catalog" theo docs/ui_contract.md §1 ("candidates" cũng giữ nguyên)
    catalog = _catalog()
    return {"book": book, "wfa": wfa, "latest_wfa": wfa, "candidates": catalog, "catalog": catalog,
            "universe": universe, "windows": windows, "assets": _assets()}


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise HTTPException(500, f"{os.path.basename(path)} hỏng: {e}")


@book_router.post("/backtest")
def post_backtest(req: BacktestRequest):
    if not req.strategies and not os.path.isfile(book_path()):
        raise HTTPException(409, "chưa có data/alpha/book.json — truyền strategies hoặc dựng sổ trước (POST /build)")
    return modes.launch_backtest(req)


@book_router.post("/wfa")
def post_wfa(req: WfaRequest):
    return modes.launch_wfa(req)


@book_router.get("/jobs")
def get_jobs(limit: int = 20, kind: Optional[str] = None):
    try:
        return {"jobs": batch_jobs.list_jobs(limit, kind)}
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))


@book_router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request, response: Response, lite: bool = False):
    """lite=true: bỏ result.trade_list (UI phân trang lệnh qua /api/studio/portfolio/trades). Job done/failed/cancelled: ETag + Cache-Control
    private, max-age=86400 và If-None-Match -> 304 (không đọc result.json); đang chạy/queued: no-store."""
    try:
        etag = batch_jobs.status_etag(job_id, lite)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    cc = "private, max-age=86400"
    if etag:
        inm = {t.strip().removeprefix("W/") for t in request.headers.get("if-none-match", "").split(",")}
        if etag in inm or "*" in inm:
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": cc})
    try:
        s = batch_jobs.status(job_id)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    if s is None:
        if batch_jobs.ephemeral_gone(job_id):
            raise batch_jobs.EphemeralGone(job_id)
        raise HTTPException(404, "không có job này")
    if s.get("status") in batch_jobs.TERMINAL_STATES:
        etag = batch_jobs.status_etag(job_id, lite) or etag   # tính lại sau status(): job vừa được _finish ghi job.json
        response.headers["Cache-Control"] = cc
        if etag:
            response.headers["ETag"] = etag
    else:
        response.headers["Cache-Control"] = "no-store"
    s = modes.decorate(s)
    return batch_jobs.status_lite(s) if lite else s


@book_router.post("/jobs/{job_id}/cancel")
def post_cancel(job_id: str):
    """Huỷ job đang chạy/chờ: SIGTERM cả nhóm tiến trình; CLI flush kho kết quả rồi thoát -> có thể chạy tiếp bằng --resume <run_dir>."""
    try:
        s = batch_jobs.cancel(job_id)
    except batch_jobs.JobError as e:
        raise HTTPException(409 if "không còn chạy" in str(e) else 422, str(e))
    if s is None:
        raise HTTPException(404, "không có job này")
    return s


# ─── Monte Carlo ngày (đồng bộ, nhẹ) ────────────────────────────────────────
@book_router.post("/mc")
def post_mc(req: McRequest):
    """Block bootstrap (mặc định 10.000 kịch bản) lợi suất ngày OOS của một job book_wfa (hoặc chuỗi tự gửi); trả tóm tắt + fan + histogram
    + `stress` (kịch bản cực xấu tất định + worst_bootstrap) + `worst_path` + `gate` (checks thực tế/yêu cầu, gate_eligible).
    mode=basic: bỏ qua mọi tham số MC của client (10.000 kịch bản, đủ 6 kịch bản cực xấu, gate chuẩn).
    mode=advanced: dùng tham số client; ngưỡng gate khác chuẩn / < 10.000 kịch bản / thiếu kịch bản cực xấu -> params.custom_gates=true (không promote được)."""
    cfg = modes.resolve_mc(req)
    custom = False
    if req.wfa_job_id:
        try:
            job = batch_jobs.status(req.wfa_job_id)
        except batch_jobs.JobError as e:
            raise HTTPException(422, str(e))
        if job is None:
            raise HTTPException(404, "không có job này")
        if job.get("kind") != "book_wfa":
            raise HTTPException(422, "wfa_job_id phải là job book_wfa")
        if job.get("status") != "done" or not job.get("result"):
            raise HTTPException(409, f"job WFA chưa xong (trạng thái {job.get('status')})")
        custom = bool(job.get("custom_gates"))   # nguồn đã dùng gate tuỳ chỉnh -> kết quả cũng không promote được
        summary = job["result"].get("summary") or {}
        daily = (summary.get("oos_daily") or {}).get(req.basis) or []
        shock = summary.get("shock")   # WFA ghi vị thế ngược chiều lớn nhất -> thêm kịch bản trend thẳng đứng
        turnover = summary.get("turnover_daily")   # WFA ghi vòng quay vốn đo từ lệnh OOS -> kịch bản cost_x2 (job cũ không có -> không đo được)
        source = {"kind": "wfa", "job_id": req.wfa_job_id, "basis": req.basis}
        provenance = job["result"].get("provenance")   # nguồn gốc của lần chạy engine tạo ra chuỗi OOS
    else:
        provenance = None   # chỉ chuỗi ngày người dùng gửi: không có lần chạy engine nào
        daily, source, shock, turnover = req.daily_returns, {"kind": "daily_returns"}, None, None   # chỉ chuỗi ngày: không biết vòng quay
        # kiểm ở đây (không trong validator pydantic): lỗi validator kèm đầu vào NaN làm FastAPI không dựng được phản hồi 422
        if not all(math.isfinite(x) and x > -1.0 for x in daily):
            raise HTTPException(422, "daily_returns phải hữu hạn và > -1 (-100%)")
    if len(daily) < MC_MIN_DAYS:
        raise HTTPException(422, f"cần >= {MC_MIN_DAYS} lợi suất ngày (có {len(daily)})")
    return mc_report(daily, cfg, shock=shock, turnover=turnover, provenance=provenance, source=source, basis=req.basis, custom=custom)



# ─── Danh mục đầu tư (dashboard + lệnh của job backtest) ──────────────────────
portfolio_router = APIRouter(prefix="/api/studio/portfolio", tags=["portfolio"])

_CACHE = pd_mod.LruCache(32)
_LOCK = threading.Lock()


def snapshot_benchmark(result: Dict[str, Any], benchmark: str = "BTC@perp") -> Optional[pd.Series]:
    """Giá đóng cửa ngày của benchmark trong cửa sổ của `result`; None nếu thiếu cấu hình/dữ liệu (bench = null)."""
    cfg = result.get("config") or {}
    if not (cfg.get("start") and cfg.get("end")):
        return None
    try:
        return benchmark_daily_closes(benchmark, cfg["start"], cfg["end"])
    except Exception:   # noqa: BLE001  (thiếu dữ liệu benchmark thì vẫn trả dashboard)
        return None


def _latest_done_backtest() -> Optional[str]:
    for j in batch_jobs.list_jobs(100, "book_backtest"):
        if j.get("status") == "done":
            return j["id"]
    return None


@portfolio_router.get("/dashboard")
def get_dashboard(source: str = Query("backtest", pattern="^backtest$"), job_id: Optional[str] = None,
                  period: str = Query("ALL", pattern="^(1M|3M|YTD|1Y|ALL)$")):
    if not job_id:   # không truyền job: lấy job backtest xong gần nhất (payload.source.job_id cho biết đã dùng job nào)
        job_id = _latest_done_backtest()
        if not job_id:
            return {"available": False, "reason": "Chưa có job backtest nào hoàn tất — chạy Backtest trước."}
    try:
        rpath = os.path.join(batch_jobs.job_dir(job_id), "result.json")
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    key = (job_id, period, os.path.getmtime(rpath) if os.path.isfile(rpath) else None)
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    try:
        job = batch_jobs.status(job_id)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    if job is None:
        raise HTTPException(404, "không có job này")
    if job.get("kind") != "book_backtest":
        raise HTTPException(422, "job_id phải là job book_backtest")
    if job.get("status") != "done" or not job.get("result"):
        raise HTTPException(409, f"job chưa xong (trạng thái {job.get('status')})")
    res = job["result"]
    feed = feeds.BacktestFeed(res, job_id, batch_jobs.job_label(job["kind"], job.get("params")))
    snap = feed.fetch()
    payload = pd_mod.build_from_snapshot(snap, period, snapshot_benchmark(res))
    with _LOCK:
        _CACHE.put(key, payload)
    return payload


def _result_for(job_id: Optional[str]):
    """Kết quả book_backtest của job: (result, job_id)."""
    job_id = job_id or _latest_done_backtest()
    if not job_id:
        raise HTTPException(404, "Chưa có job backtest nào hoàn tất — chạy Backtest trước.")
    try:   # trang/bộ lọc khác nhau của cùng job: không parse lại result.json (đệm theo job + mtime/size; chỉ nạp sau khi đã qua kiểm tra bên dưới)
        st = os.stat(os.path.join(batch_jobs.job_dir(job_id), "result.json"))
        rkey = ("result", job_id, st.st_mtime_ns, st.st_size)
    except (OSError, batch_jobs.JobError):
        rkey = None
    if rkey is not None:
        with _LOCK:
            hit = _CACHE.get(rkey)
        if hit is not None:
            return hit, job_id
    try:
        job = batch_jobs.status(job_id)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    if job is None:
        raise HTTPException(404, "không có job này")
    if job.get("kind") != "book_backtest" or job.get("status") != "done" or not job.get("result"):
        raise HTTPException(409, "job phải là book_backtest đã xong")
    if rkey is not None:
        with _LOCK:
            _CACHE.put(rkey, job["result"])
    return job["result"], job_id


TRADE_SORT = {"close_time", "enter_time", "pnl", "pnl_pct", "mae_pct", "notional", "symbol", "strategy"}


@portfolio_router.get("/trades")
def get_portfolio_trades(source: str = Query("backtest", pattern="^backtest$"), job_id: Optional[str] = None,
               period: str = Query("ALL", pattern="^(1M|3M|YTD|1Y|ALL)$"), strategy: Optional[str] = None, symbol: Optional[str] = None,
               side: Optional[str] = Query(None, pattern="^(LONG|SHORT)$"), outcome: Optional[str] = Query(None, pattern="^(win|loss|breakeven)$"),
               sort: str = "-close_time", offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=2000),
               format: str = Query("json", pattern="^(json|csv)$")):
    """Danh sách lệnh đã đóng của job backtest (lọc: kỳ / chiến lược — id hoặc HỌ chiến lược / tài sản / chiều / kết quả), sắp xếp, phân trang;
    format=csv trả toàn bộ hàng đã lọc (không phân trang)."""
    from backend.metrics.trades import strategy_family
    res, jid = _result_for(job_id)
    rows = [t for t in res.get("trade_list") or [] if t.get("close_time") is not None]
    if period != "ALL":
        nav = pd_mod.daily_nav_series(res)
        if len(nav):
            cut = pd_mod._cutoff(nav.index[-1], period)
            if cut is not None:
                start_ms = int((cut + pd_mod.pd.Timedelta(days=1)).value // 1_000_000)
                rows = [t for t in rows if t["close_time"] >= start_ms]
    if strategy:
        rows = [t for t in rows if t.get("strategy") == strategy or strategy_family(t.get("strategy")) == strategy]
    if symbol:
        want = symbol if "@" in symbol else f"{symbol.upper()}@perp"
        rows = [t for t in rows if t.get("symbol") in (symbol, want)]
    if side:
        rows = [t for t in rows if t.get("side") == side]
    if outcome:
        rows = [t for t in rows if (outcome == "win" and t["pnl"] > 0) or (outcome == "loss" and t["pnl"] < 0) or (outcome == "breakeven" and t["pnl"] == 0)]
    key = sort.lstrip("-")
    if key not in TRADE_SORT:
        raise HTTPException(422, f"sort phải là một trong {sorted(TRADE_SORT)} (thêm '-' để giảm dần)")
    rows = sorted(rows, key=lambda t: (t.get(key) is None, t.get(key) if t.get(key) is not None else 0), reverse=sort.startswith("-"))
    if format == "csv":
        import csv
        import io
        from fastapi.responses import Response
        cols = ["close_time", "enter_time", "symbol", "strategy", "side", "enter_price", "avg_price", "close_price", "qty", "notional",
                "margin_usd", "leverage", "layers", "pnl", "pnl_pct", "fees_usd", "funding_usd", "mae_pct", "status", "close_reason"]
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="trades_backtest_{jid}.csv"'})
    total = len(rows)
    return {"items": rows[offset:offset + limit], "total": total, "offset": offset, "limit": limit, "job_id": jid,
            "strategies": sorted({t.get("strategy") for t in res.get("trade_list") or [] if t.get("strategy")}),
            "families": sorted({strategy_family(t.get("strategy")) for t in res.get("trade_list") or [] if t.get("strategy")}),
            "symbols": sorted({t.get("symbol") for t in res.get("trade_list") or [] if t.get("symbol")})}


ROUTERS = [book_router, portfolio_router]
