"""API phễu kiểm duyệt alpha (/api/studio/funnel): tạo lượt chạy (job nền qua run_limited), liệt kê, thống kê từng tầng, bảng alpha, chi tiết alpha,
danh sách lệnh (phân trang, tính lại cho alpha bị loại ở S1), đưa alpha FINAL vào kho alpha. Hợp đồng: docs/funnel_contract.md.

Job nặng chạy ở tiến trình riêng (backend.optimize.funnel.run qua backend/utils/ops/run_limited.sh) bằng cơ chế job của backend/api/jobs/batch.py: loại job
`funnel_run` (danh sách trắng cờ + nhãn nằm ở batch.KINDS / batch.job_label). Handler chỉ đọc kho (SQLite chỉ đọc + parquet) nên là `def` thường (FastAPI chạy trong threadpool).
"""
import json
import os
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.api.jobs import batch as batch_jobs
from backend.optimize.funnel import gates
from backend.optimize.funnel.generate import count_params
from backend.optimize.funnel.recompute import read_cached
from backend.carlo.monte_carlo import with_gate_thresholds
from backend.optimize.funnel.stats import scalar_metrics, stage_stats
from backend.optimize.funnel.storage import RunStore, atomic_write_json

router = APIRouter(prefix="/api/studio/funnel", tags=["funnel"])

KIND = "funnel_run"
assert KIND in batch_jobs.KINDS

MAX_ALPHAS = 1_000_000
LARGE_ALPHAS = 200_000
_RUN_RE = re.compile(r"^fr-[0-9A-Za-z_-]{1,40}$|^[0-9A-Za-z_-]{3,48}$")
_ALPHA_RE = re.compile(r"^[0-9a-f]{8,64}$")
SORT_COLS = {"ret_pct": "m.ret_pct", "mdd_pct": "m.mdd_pct", "sharpe": "m.sharpe", "trades": "m.trades", "win_rate": "m.win_rate",
             "profit_factor": "m.profit_factor", "score": "m.score", "order": "a.ord", "ord": "a.ord", "final_scale": "a.final_scale",
             # số đo mở rộng (metrics_json; core/metrics/portfolio.flat_extras) — sắp xếp qua json_extract
             **{k: f"json_extract(m.metrics_json, '$.{k}')" for k in (
                 "cagr_pct", "calmar", "cvar95_pct", "max_dd_days", "payoff", "expectancy_pct", "max_consec_losses", "top5_share_pct",
                 "mae_worst_pct", "liq_proximity_max_pct", "liquidations", "fee_drag_pct", "mdd_daily_pct", "mdd_intrabar_pct", "sortino")}}


# ─── Đường dẫn / mở kho ─────────────────────────────────────────────────────
def funnel_root() -> str:
    from backend.db.data_layout import cache_dir
    return cache_dir(None, "funnel")


def alphas_dir() -> str:
    return os.environ.get("NORA_ALPHAS_DIR") or os.path.join(batch_jobs.NORA_DIR, "data", "alphas")


def _run_dir(run_id: str) -> str:
    if not _RUN_RE.match(run_id):
        raise HTTPException(422, "run_id không hợp lệ")
    return os.path.join(funnel_root(), run_id)


def _open(run_id: str) -> RunStore:
    d = _run_dir(run_id)
    if not os.path.isfile(os.path.join(d, "results.sqlite")):
        raise HTTPException(404, f"không có lượt phễu {run_id} (hoặc chưa bắt đầu chạy)")
    return RunStore(d, read_only=True)


def _stage(stage: str) -> str:
    if stage not in gates.STAGE_IDX:
        raise HTTPException(404, f"không có tầng {stage!r}; có: {gates.STAGES}")
    return stage


def _alpha_id(alpha_id: str) -> str:
    if not _ALPHA_RE.match(alpha_id):
        raise HTTPException(422, "alpha_id không hợp lệ")
    return alpha_id


# ─── Đệm kết quả nặng (tính lại trong request ăn GIL của mọi request khác) ──────────────────────────────────
LIVE_MIN_INTERVAL_S = 15.0      # lượt đang chạy: kho đổi liên tục nhưng không tính lại thống kê/đếm tầng thường hơn mức này


class _Lru:
    """LRU nhỏ, an toàn đa luồng (khoá chỉ giữ lúc get/put, KHÔNG giữ khi tính)."""

    def __init__(self, size: int):
        self.size, self._d, self._lock = size, OrderedDict(), threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key]
        return None

    def put(self, key, value) -> None:
        with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self.size:
                self._d.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


_STATS_CACHE = _Lru(32)         # (run_id, stage, top, chữ ký kho) -> kết quả stage_stats
_STATS_LAST = _Lru(128)         # (run_id, stage, top) -> (monotonic lúc tính, kết quả): cho nhịp tính tối thiểu của lượt đang chạy
_COUNTS_CACHE = _Lru(256)       # (run_id, chữ ký kho) -> counts (stage_counts + top_reject) của _run_summary
_COUNTS_LAST = _Lru(256)        # run_id -> (monotonic, counts)
_FLIGHT: Dict[Any, threading.Lock] = {}
_FLIGHT_LOCK = threading.Lock()


def _flight(key) -> threading.Lock:
    """Khoá theo khoá đệm: nhiều request cùng hỏi một thứ -> một cái tính, số còn lại chờ rồi đọc đệm."""
    with _FLIGHT_LOCK:
        return _FLIGHT.setdefault(key, threading.Lock())


def _store_sig(d: str):
    """Chữ ký kho: (mtime_ns, size) của results.sqlite + -wal (WAL: ghi mới nằm ở -wal, file chính chỉ đổi khi checkpoint)."""
    out = []
    for n in ("results.sqlite", "results.sqlite-wal"):
        try:
            st = os.stat(os.path.join(d, n))
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


# ─── Mô hình yêu cầu ────────────────────────────────────────────────────────
class FunnelRunRequest(BaseModel):
    strategies: List[str] = Field(..., min_length=1, max_length=16)
    n_per_strategy: Optional[int] = Field(None, ge=1, le=MAX_ALPHAS, description="số alpha mỗi chiến lược (lấy mẫu theo seed)")
    full_grid: bool = False
    seed: int = Field(7, ge=0, le=2 ** 31 - 1)
    symbols: Optional[List[str]] = Field(None, max_length=16)
    windows: Optional[Dict[str, str]] = Field(None, description="ghi đè mốc YYYY-MM-DD: start, dev1_end, dev2_end, end")
    resume_run_id: Optional[str] = None
    force_large: bool = False
    space: str = Field("grid", pattern="^(grid|schema)$", description="grid = lưới nhỏ của chiến lược; schema = mọi tham số theo min/max/bước")
    timeframe: str = Field("15m", pattern="^(15m|1h|4h)$",
                           description="khung chạy (nến mô phỏng): 15m / 1h / 4h; khung tín hiệu của mọi alpha >= khung này")
    regime: str = Field("off", pattern="^(off|learn|both)$",
                        description="learn: alpha học bảng regime trên train; both: mỗi bộ tham số chạy cả off và learn (DSR/PBO đếm cả hai)")

    @field_validator("windows")
    @classmethod
    def _win(cls, v):
        if v:
            bad = sorted(set(v) - {"start", "dev1_end", "dev2_end", "end"})
            if bad:
                raise ValueError(f"windows: khoá lạ {bad}")
            for d in v.values():
                batch_jobs.check_date(d)
        return v

    @model_validator(mode="after")
    def _one(self):
        if not self.resume_run_id and bool(self.n_per_strategy) == bool(self.full_grid):
            raise ValueError("chọn đúng một: n_per_strategy hoặc full_grid")
        return self


def _planned(strategies: List[str], n: Optional[int], full_grid: bool, space: str = "grid", timeframe: str = "15m",
             regime: str = "off") -> Dict[str, int]:
    from backend.core.strategy import book as sb
    from backend.optimize.funnel.generate import incompatible, space_for
    by_id = sb.BY_ID
    bad = incompatible([by_id[s] for s in strategies], space, timeframe)
    if bad:
        raise HTTPException(422, f"chiến lược không chạy được ở khung {timeframe} (khung tín hiệu tối đa nhỏ hơn khung chạy): "
                                 + "; ".join(f"{k} ({', '.join(v)})" for k, v in bad.items()))
    from backend.optimize.funnel.generate import regime_variants
    k = len(regime_variants({}, regime))
    return {s: k * count_params(space_for(by_id[s], space, timeframe), n, full_grid) for s in strategies}


# ─── Tạo lượt / ước tính ────────────────────────────────────────────────────
@router.post("/runs")
def post_run(req: FunnelRunRequest):
    """Khởi chạy phễu như job nền (hàng đợi run_limited). -> {run_id, job_id}. resume_run_id: chạy tiếp lượt đó (cấu hình lấy từ run.json)."""
    try:
        strategies = batch_jobs.check_candidate_ids(req.strategies)
        symbols = batch_jobs.check_symbols(req.symbols) if req.symbols else None
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    from backend.optimize.funnel.orchestrator import new_run_id
    if req.resume_run_id:
        run_id = req.resume_run_id
        if not os.path.isfile(os.path.join(_run_dir(run_id), "results.sqlite")):
            raise HTTPException(404, f"không có lượt {run_id} để chạy tiếp")
        params = {"resume": run_id}
        planned = None
    else:
        planned = _planned(strategies, req.n_per_strategy, req.full_grid, req.space, req.timeframe, req.regime)
        total = sum(planned.values())
        if total > MAX_ALPHAS or (total > LARGE_ALPHAS and not req.force_large):
            raise HTTPException(422, f"{total:,} alpha vượt giới hạn ({LARGE_ALPHAS:,}; trần cứng {MAX_ALPHAS:,}); giảm n_per_strategy hoặc đặt force_large")
        run_id = new_run_id()
        params = {"strategies": strategies, "seed": req.seed, "run_id": run_id, "space": req.space, "timeframe": req.timeframe, "regime": req.regime}
        params.update({"full_grid": True} if req.full_grid else {"n_per_strategy": req.n_per_strategy})
        if symbols:
            params["symbols"] = symbols
        if req.windows:
            params["windows"] = req.windows
        if total > LARGE_ALPHAS:
            params["force_large"] = True
        # bản run.json "queued" TRƯỚC khi chạy: danh sách lượt thấy ngay lượt đang xếp hàng; CLI ghi đè bằng run.json đầy đủ khi bắt đầu
        atomic_write_json(os.path.join(_run_dir(run_id), "run.json"), {
            "run_id": run_id, "status": "queued", "created": time.time(), "started": None, "finished": None, "total_alphas": total,
            "planned": planned, "config": {"strategies": strategies, "n_per_strategy": req.n_per_strategy, "full_grid": req.full_grid, "space": req.space,
                                           "timeframe": req.timeframe, "regime": req.regime, "seed": req.seed, "symbols": symbols,
                                           "windows": req.windows},
            "stages": {s: {"status": "pending"} for s in gates.STAGES}})
    try:
        job_id = batch_jobs.launch(KIND, params)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    except batch_jobs.JobBusy as e:
        raise HTTPException(429, str(e))
    atomic_write_json(os.path.join(_run_dir(run_id), "api_job.json"), {"job_id": job_id, "kind": KIND, "params": params, "launched": time.time()})
    return {"run_id": run_id, "job_id": job_id}


@router.get("/estimate")
def get_estimate(strategies: str = Query(..., description="id phân tách bằng dấu phẩy"), n_per_strategy: Optional[int] = Query(None, ge=1, le=MAX_ALPHAS),
                 full_grid: bool = False, workers: Optional[int] = Query(None, ge=1, le=64, description="bỏ trống = số worker mặc định của máy chủ"),
                 space: str = Query("grid", pattern="^(grid|schema)$"),
                 timeframe: str = Query("15m", pattern="^(15m|1h|4h)$"),
                 regime: str = Query("off", pattern="^(off|learn|both)$")):
    """Ước tính thời gian S1 (tầng chiếm gần hết thời gian) TRƯỚC khi chạy: alpha × giây/backtest / số worker, giây/backtest = TRUNG VỊ số đo của các lượt
    đã xong cùng khung + regime (optimize/funnel/estimate.py). Chưa có lượt khớp -> sec_per_backtest = null, s1_eta_s = null, measure.reason nêu lý do.
    workers bỏ trống = số worker mặc định của máy chủ (utils/parallel.default_workers, cùng số `--workers auto`). Các tầng sau chỉ chạy cho alpha còn sống."""
    try:
        ids = batch_jobs.check_candidate_ids([s for s in strategies.split(",") if s])
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    if bool(n_per_strategy) == bool(full_grid):
        raise HTTPException(422, "chọn đúng một: n_per_strategy hoặc full_grid")
    planned = _planned(ids, n_per_strategy, full_grid, space, timeframe, regime)
    total = sum(planned.values())
    from backend.optimize.funnel.estimate import measured_s1_rate
    from backend.optimize.funnel.orchestrator import PER_WORKER_MB
    from backend.utils.parallel import default_workers
    w = workers if workers is not None else default_workers(PER_WORKER_MB)
    m = measured_s1_rate(funnel_root(), timeframe, regime, jobs_root=batch_jobs.jobs_root())
    spb = m["sec_per_backtest"]
    return {"space": space, "per_strategy": planned, "total_alphas": total, "sec_per_backtest": spb, "workers": w,
            "workers_source": "client" if workers is not None else "server_default",
            "s1_eta_s": round(total * spb / w, 1) if spb is not None else None, "measure": m}


# ─── Danh sách / chi tiết lượt ──────────────────────────────────────────────
def _job_status(run: Dict[str, Any], d: str) -> Dict[str, Any]:
    job_id = run.get("job_id")
    if not job_id:
        try:
            with open(os.path.join(d, "api_job.json"), encoding="utf-8") as fh:
                job_id = json.load(fh).get("job_id")
        except (OSError, ValueError):
            job_id = None
    status = run.get("status") or "unknown"
    if job_id and status in ("queued", "running"):
        try:
            j = batch_jobs.status(job_id)
        except batch_jobs.JobError:
            j = None
        if j and j.get("status") in ("queued", "running", "done", "failed", "cancelled"):
            status = j["status"]
    return {"job_id": job_id, "status": status}


def _read_run_json(d: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(d, "run.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _progress(d: str) -> Optional[Dict[str, Any]]:
    try:
        with open(os.path.join(d, "progress.json"), encoding="utf-8") as fh:
            p = json.load(fh)
        return {"stage": p.get("stage"), "done": p.get("done"), "total": p.get("total"), "eta_s": p.get("eta_s"), "rate": p.get("rate"),
                "peak_rss_mb": p.get("peak_rss_mb"), "status": p.get("status")}
    except (OSError, ValueError):
        return None


def _stage_counts(run_id: str, d: str, live: bool) -> List[Dict[str, Any]]:
    """Đếm theo tầng + lý do loại nhiều nhất của một lượt. Đệm theo chữ ký kho (mtime/size results.sqlite + -wal); lượt đang chạy:
    kho đổi mà lần tính trước < LIVE_MIN_INTERVAL_S thì dùng lại kết quả trước (danh sách lượt được poll liên tục)."""
    sig = _store_sig(d)
    key = (run_id, sig)
    hit = _COUNTS_CACHE.get(key)
    if hit is not None:
        return hit
    if live:
        last = _COUNTS_LAST.get(run_id)
        if last is not None and time.monotonic() - last[0] < LIVE_MIN_INTERVAL_S:
            return last[1]
    with _flight(("counts", run_id)):
        hit = _COUNTS_CACHE.get(key)
        if hit is not None:
            return hit
        store = RunStore(d, read_only=True)
        try:
            counts = store.stage_counts()
            tops = store.top_rejects()
        finally:
            store.close()
        for c in counts:
            t = tops.get(c["stage"])
            c["top_reject"] = {"code": t["code"], "label": gates.reason_label(t["code"]), "count": t["count"]} if t else None
        counts = [c for c in counts if c["input"] > 0 or c["done"] > 0]   # bỏ các tầng chưa có alpha nào
        _COUNTS_CACHE.put(key, counts)
        _COUNTS_LAST.put(run_id, (time.monotonic(), counts))
        return counts


def _run_summary(run_id: str, detail: bool) -> Optional[Dict[str, Any]]:
    d = os.path.join(funnel_root(), run_id)
    run = _read_run_json(d)
    if not run and not os.path.isfile(os.path.join(d, "results.sqlite")):
        return None
    st = _job_status(run, d)
    cfg = run.get("config") or {}
    counts: List[Dict[str, Any]] = []
    if os.path.isfile(os.path.join(d, "results.sqlite")):
        counts = _stage_counts(run_id, d, st["status"] in ("queued", "running"))
    prog = _progress(d) if st["status"] in ("running", "queued") else None
    out = {"run_id": run_id, "job_id": st["job_id"], "status": st["status"], "created": run.get("created"), "started": run.get("started"),
           "finished": run.get("finished"), "strategies": cfg.get("strategies"), "n_per_strategy": cfg.get("n_per_strategy"),
           "full_grid": cfg.get("full_grid"), "total_alphas": run.get("total_alphas"), "counts": counts, "progress": prog}
    if detail:
        out.update({"config": cfg, "stages": run.get("stages"), "until": run.get("until"), "wall_s": run.get("wall_s"),
                    "windows_ms": run.get("windows_ms"), "kind": KIND})
    return out


@router.get("/runs")
def get_runs(limit: int = Query(50, ge=1, le=200)):
    root = funnel_root()
    rows = []
    for name in sorted(os.listdir(root), reverse=True) if os.path.isdir(root) else []:
        if not os.path.isdir(os.path.join(root, name)):
            continue
        s = _run_summary(name, detail=False)
        if s:
            rows.append(s)
    rows.sort(key=lambda r: r.get("created") or 0, reverse=True)
    return {"runs": rows[:limit]}


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    _run_dir(run_id)
    s = _run_summary(run_id, detail=True)
    if s is None:
        raise HTTPException(404, f"không có lượt phễu {run_id}")
    return s


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    """Huỷ job của lượt (SIGTERM -> flush kho; chạy tiếp bằng POST /runs {resume_run_id})."""
    s = _run_summary(run_id, detail=False)
    if s is None or not s.get("job_id"):
        raise HTTPException(404, "không có job của lượt này")
    try:
        return batch_jobs.cancel(s["job_id"]) or {}
    except batch_jobs.JobError as e:
        raise HTTPException(409, str(e))


# ─── Thống kê tầng ──────────────────────────────────────────────────────────
@router.get("/runs/{run_id}/stages/{stage}/stats")
def get_stage_stats(run_id: str, stage: str, top: int = Query(20, ge=1, le=100)):
    # đệm GIÁ TRỊ là body JSON đã render (bytes): jsonable_encoder + dumps ~0,2 s CPU cho 450 KB, mỗi lần poll sẽ ăn GIL nếu chỉ đệm dict
    return Response(_stage_stats_body(run_id, stage, top), media_type="application/json")


def _stage_stats_body(run_id: str, stage: str, top: int) -> bytes:
    stage = _stage(stage)
    d = _run_dir(run_id)
    key = (run_id, stage, top, _store_sig(d))
    hit = _STATS_CACHE.get(key)
    if hit is not None:
        return hit
    with _flight(("stats", run_id, stage, top)):
        hit = _STATS_CACHE.get(key)     # request khác vừa tính xong trong lúc chờ khoá
        if hit is not None:
            return hit
        store = _open(run_id)
        try:
            run = store.read_run()
            done = (run.get("stages", {}).get(stage, {}) or {}).get("status") == "done"
            lk = (run_id, stage, top)
            if not done:   # lượt đang chạy: kho đổi liên tục -> không tính lại thường hơn LIVE_MIN_INTERVAL_S, trả kết quả trước
                last = _STATS_LAST.get(lk)
                if last is not None and time.monotonic() - last[0] < LIVE_MIN_INTERVAL_S:
                    return last[1]
            cache = os.path.join(store.run_dir, "stats", f"{stage}.json")
            out = None
            if done and top == 20:
                try:
                    with open(cache, encoding="utf-8") as fh:
                        out = json.load(fh)
                except (OSError, ValueError):
                    pass
            if out is None:
                out = stage_stats(store, stage, top)
                if done and top == 20:
                    try:
                        atomic_write_json(cache, out)
                    except OSError:
                        pass
            body = JSONResponse(jsonable_encoder(out)).body   # đúng đường FastAPI sẽ render dict trả về
            _STATS_CACHE.put(key, body)
            _STATS_LAST.put(lk, (time.monotonic(), body))
            return body
        finally:
            store.close()


# ─── Bảng alpha ─────────────────────────────────────────────────────────────
def _parse_sort(sort: Optional[str], has_metrics: bool) -> str:
    """`-ret_pct` = giảm dần, `ret_pct` = tăng dần; mặc định: điểm cao trước (có tầng) / thứ tự sinh. Hoà -> thứ tự sinh. NULL luôn cuối."""
    if not sort:
        sort = "-score" if has_metrics else "order"
    desc = sort.startswith("-")
    key = sort.lstrip("-+ ")
    if key not in SORT_COLS or (not has_metrics and key not in ("order", "ord", "final_scale")):
        raise HTTPException(422, f"sort không hợp lệ: {sort!r}; có: {sorted(SORT_COLS)} (thêm '-' đầu = giảm dần)")
    col = SORT_COLS[key]
    return f"{col} IS NULL, {col} {'DESC' if desc else 'ASC'}, a.ord"


@router.get("/runs/{run_id}/alphas")
def get_alphas(run_id: str, stage: Optional[str] = None, status: Optional[str] = Query(None, pattern="^(passed|rejected)$"),
               strategy: Optional[str] = None, sort: Optional[str] = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)):
    """{total, offset, limit, items:[{alpha_id, strategy, params, stage_reached, rejected_stage, reject_code, reject_msg, final_scale, metrics}]};
    `metrics` phẳng của tầng được hỏi (không có `stage`: của tầng alpha đã tới)."""
    store = _open(run_id)
    try:
        where, args = [], []
        if strategy:
            where.append("a.strategy=?")
            args.append(strategy)
        if stage:
            stage = _stage(stage)
        if stage and stage != "S0_generate":
            base = "FROM stage_metrics m JOIN alphas a ON a.alpha_id=m.alpha_id"
            where.insert(0, "m.stage=?")
            args.insert(0, stage)
            if status:
                where.append("m.passed=?")
                args.append(1 if status == "passed" else 0)
            order = _parse_sort(sort, True)
            cols = "a.alpha_id, a.strategy, a.params_json, a.stage_reached, a.rejected_stage, a.reject_code, a.reject_msg, a.final_scale, m.metrics_json"
        else:
            base = "FROM alphas a"
            if stage == "S0_generate" and status:
                where.append("a.rejected_idx IS " + ("NULL" if status == "passed" else "NOT NULL"))
            elif status:   # không chọn tầng: qua = còn sống tới nay, loại = đã bị loại ở bất kỳ tầng nào
                where.append("a.rejected_idx IS " + ("NULL" if status == "passed" else "NOT NULL"))
            order = _parse_sort(sort, False)
            cols = "a.alpha_id, a.strategy, a.params_json, a.stage_reached, a.rejected_stage, a.reject_code, a.reject_msg, a.final_scale, NULL"
        w = (" WHERE " + " AND ".join(where)) if where else ""
        with store._lock:
            total = store._con.execute(f"SELECT COUNT(*) {base}{w}", args).fetchone()[0]
            rows = store._con.execute(f"SELECT {cols} {base}{w} ORDER BY {order} LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
        items = []
        need = [r[0] for r in rows if r[8] is None]
        fallback = {}
        if need:   # không chọn tầng: lấy số đo của tầng alpha đã tới
            for r in rows:
                if r[8] is None and r[3] in gates.STAGE_IDX:
                    fallback[r[0]] = store.metrics_of([r[0]], r[3]).get(r[0])
        for a, s, p, sr, rs, rc, rm, fs, mj in rows:
            m = json.loads(mj) if mj else fallback.get(a)
            items.append({"alpha_id": a, "strategy": s, "params": json.loads(p), "stage_reached": sr, "rejected_stage": rs, "reject_code": rc,
                          "reject_msg": rm, "final_scale": fs, "metrics": scalar_metrics(m) if m else {}})
        return {"total": int(total), "offset": offset, "limit": limit, "stage": stage, "items": items}
    finally:
        store.close()


# ─── Chi tiết alpha ─────────────────────────────────────────────────────────
def _nav(rows: List[Dict[str, Any]], initial: float = gates.INITIAL_CAPITAL) -> Optional[Dict[str, List[Any]]]:
    """Nối các hàng daily (theo fold) thành một đường vốn: lãi kép liên tục từ `initial`."""
    if not rows:
        return None
    dates: List[str] = []
    values: List[float] = []
    eq = initial
    for r in rows:
        if not r["rets"]:
            continue
        for d, x in zip(pd.date_range(r["start_date"], periods=len(r["rets"]), freq="D"), r["rets"]):
            eq *= 1.0 + x
            dates.append(f"{d:%Y-%m-%d}")
            values.append(round(eq, 2))
    return {"dates": dates, "values": values}


@router.get("/runs/{run_id}/alphas/{alpha_id}")
def get_alpha(run_id: str, alpha_id: str):
    """Alpha + `stage_metrics:{tầng: số đo}` + `nav:{tầng:{dates,values}}` + `mc` (cùng dạng POST /book/mc: summary, fan, stress, gate, ...) + `scale_search`."""
    _alpha_id(alpha_id)
    store = _open(run_id)
    try:
        a = store.get_alpha(alpha_id)
        if a is None:
            raise HTTPException(404, f"không có alpha {alpha_id}")
        sm = store.alpha_metrics(alpha_id)
        nav: Dict[str, Any] = {}
        for st, col in (("S1_backtest", "S1_backtest"), ("S3_wfa", "S3_wfa"), ("S5_sizing", "S5_sizing"), ("S6_holdout", "S6_holdout")):
            n = _nav(store.read_daily(alpha_id, st, col))
            if n:
                nav[st] = n
        mcfile = store.read_mc(alpha_id) or {}
        a.pop("ord", None)
        a.pop("stage_idx", None)
        return {**a, "stage_metrics": sm, "metrics": sm.get(a["stage_reached"]) or {}, "nav": nav, "mc": with_gate_thresholds(mcfile.get("mc")),
                "mc_full_size": with_gate_thresholds(mcfile.get("mc_full_size")), "scale_search": mcfile.get("scale_search") or [], "verified": mcfile.get("verified"),
                "confirm_attempts": mcfile.get("attempts") or [], "min_size": mcfile.get("min_size"),
                "stored_trades": {st: store.has_trades(alpha_id, st) for st in ("S1_backtest", "S3_wfa", "S5_sizing", "S6_holdout")}}
    finally:
        store.close()


# ─── Lệnh ───────────────────────────────────────────────────────────────────
def _iso(ms: int) -> str:
    return f"{pd.Timestamp(int(ms), unit='ms'):%Y-%m-%dT%H:%M:%S.%f}"[:-3] + "Z"


def _trade_item(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"fold": r.get("fold"), "symbol": r["symbol"], "side": r["side"], "enter_time": _iso(r["enter_time"]), "close_time": _iso(r["close_time"]),
            "enter_price": r["enter_price"], "close_price": r["close_price"], "qty": r["qty"], "pnl_usd": r["pnl_usd"], "pnl_pct": r["pnl_pct"],
            "fees_usd": r["fees_usd"], "funding_usd": r["funding_usd"], "status": r["status"], "layers": r["layers"], "mae_pct": r["mae_pct"]}


def _run_recompute_subprocess(run_id: str, alpha_id: str) -> None:
    """Tính lại S1 ngoài tiến trình API (job funnel_recompute qua runner, run_limited --no-lock: nằm trong nora.slice); ghi đệm vào
    <run>/recomputed/. Test thay hàm này."""
    job_dir = os.path.join(_run_dir(run_id), "recomputed", f"{alpha_id}.job")
    try:
        batch_jobs.run_sync("funnel_recompute", {"run_id": run_id, "alpha_id": alpha_id}, job_dir, timeout=1800)
    except TimeoutError:
        raise HTTPException(504, "tính lại lệnh quá thời gian (30 phút)")
    except RuntimeError as e:
        raise HTTPException(500, f"tính lại lệnh thất bại: {e}")


RECOMPUTE_WAIT_S = 85.0         # request chờ tối đa ngần này (< 100 s của Cloudflare); tính tiếp ở nền, client gọi lại sẽ thấy đệm
_RECOMPUTE_POOL = ThreadPoolExecutor(2, thread_name_prefix="funnel-recompute")
_RECOMPUTE_INFLIGHT: Dict[Any, Any] = {}
_RECOMPUTE_LOCK = threading.RLock()   # RLock: add_done_callback chạy ngay trong luồng gọi nếu việc đã xong


def _recompute_done(k) -> None:
    with _RECOMPUTE_LOCK:
        _RECOMPUTE_INFLIGHT.pop(k, None)


def _recompute_bounded(run_id: str, alpha_id: str) -> Optional[JSONResponse]:
    """Chạy _run_recompute_subprocess (vẫn timeout 1800 s) ở luồng nền và chờ <= RECOMPUTE_WAIT_S. Hết hạn mà chưa xong -> 202 (việc vẫn chạy;
    gọi lại cùng URL: đang chạy thì lại chờ, xong thì đọc đệm). Xong -> None. Lỗi của việc tính (504/500) ném lại như cũ."""
    k = (run_id, alpha_id)
    with _RECOMPUTE_LOCK:
        fut = _RECOMPUTE_INFLIGHT.get(k)
        if fut is None:
            if len(_RECOMPUTE_INFLIGHT) >= 4:
                raise HTTPException(429, "đang tính lại lệnh cho nhiều alpha khác; thử lại sau")
            fut = _RECOMPUTE_INFLIGHT[k] = _RECOMPUTE_POOL.submit(_run_recompute_subprocess, run_id, alpha_id)
            fut.add_done_callback(lambda _f, k=k: _recompute_done(k))
    try:
        fut.result(timeout=RECOMPUTE_WAIT_S)
    except FutureTimeout:
        return JSONResponse({"status": "computing", "recompute": True, "retry_after_s": 30,
                             "message": "đang tính lại lệnh (có thể mất vài phút); gọi lại cùng URL sau ít phút"},
                            status_code=202, headers={"Retry-After": "30"})
    return None


@router.get("/runs/{run_id}/alphas/{alpha_id}/trades")
def get_trades(run_id: str, alpha_id: str, stage: Optional[str] = None, fold: Optional[int] = Query(None, ge=1), offset: int = Query(0, ge=0),
               limit: int = Query(100, ge=1, le=1000), recompute: bool = False):
    """{items, total, offset, limit, stage, fold, folds?, stored}. Chưa lưu lệnh (alpha bị loại ở S1): stored=false, items rỗng; `recompute=true`
    tính lại tất định rồi trả thêm `recomputed: true`. stage: S1_backtest | S3_wfa (lệnh OOS, lọc theo fold) | S5_sizing | S6_holdout | S6_holdout_extreme."""
    _alpha_id(alpha_id)
    store = _open(run_id)
    try:
        a = store.get_alpha(alpha_id)
        if a is None:
            raise HTTPException(404, f"không có alpha {alpha_id}")
        if stage is None:   # mặc định: tầng cuối cùng có lệnh đã lưu
            stage = next((s for s in ("S6_holdout", "S5_sizing", "S3_wfa", "S1_backtest") if store.has_trades(alpha_id, s)), "S1_backtest")
        if stage not in gates.STAGE_IDX and stage != "S6_holdout_extreme":
            raise HTTPException(404, f"tầng không có lệnh: {stage!r}")
        dir_stage = "S6_holdout" if stage.startswith("S6_holdout") else stage
        rows = [r for r in store.read_trades(alpha_id, dir_stage, fold) if r["stage"] == stage]
        folds = sorted({r["fold"] for r in rows if r["fold"] is not None}) if dir_stage in ("S3_wfa", "S5_sizing") else None
        if rows:
            out = {"items": [_trade_item(r) for r in rows[offset:offset + limit]], "total": len(rows), "stored": True}
            if folds is not None:
                out["folds"] = sorted({r["fold"] for r in store.read_trades(alpha_id, dir_stage) if r["fold"] is not None})
            return {**out, "offset": offset, "limit": limit, "stage": stage, "fold": fold}
        if stage != "S1_backtest" or not recompute:
            return {"items": [], "total": 0, "offset": offset, "limit": limit, "stage": stage, "fold": fold, "stored": False,
                    "can_recompute": stage == "S1_backtest" and a["rejected_stage"] == "S1_backtest"}
        if a["rejected_stage"] != "S1_backtest" and a["stage_idx"] >= 1:
            raise HTTPException(409, "alpha đã qua S1 — lệnh phải có trong kho")
        cached = read_cached(store.run_dir, alpha_id)
        if cached is None:
            pending = _recompute_bounded(run_id, alpha_id)
            if pending is not None:
                return pending
            cached = read_cached(store.run_dir, alpha_id)
            if cached is None:
                raise HTTPException(500, "tính lại lệnh không tạo ra kết quả")
        tr = cached["trades"]
        tr.sort(key=lambda r: r["enter_time"])
        return {"items": [_trade_item({**r, "fold": None}) for r in tr[offset:offset + limit]], "total": len(tr), "offset": offset, "limit": limit,
                "stage": stage, "fold": fold, "stored": False, "recomputed": True}
    finally:
        store.close()


# ─── Xuất bản sổ chung vốn từ alpha FINAL ──────────────────────────────────
class FunnelBookRequest(BaseModel):
    alpha_ids: List[str] = Field(..., min_length=1, max_length=9, description="alpha FINAL (explore: đã qua S1), mỗi chiến lược một alpha")
    risk_per_trade_pct: float = Field(..., gt=0.0, le=5.0)
    wfa_job_id: str = Field("", description="job book_wfa (advanced) đã chạy ĐÚNG các cấu hình này ở cùng rủi ro; gate phải qua "
                                            "(explore: tuỳ chọn, không bắt qua)")
    dry_run: bool = False
    explore: bool = Field(False, description="sổ thử nghiệm cho demo -> data/alphas/explore/book.json (EXPLORE_DEMO), không bao giờ live")


@router.post("/runs/{run_id}/book")
def post_funnel_book(run_id: str, req: FunnelBookRequest):
    """Job nền funnel_book (optimize/funnel/publish.py): kiểm WFA sổ, chấm holdout MỘT lần, ghi data/alphas/book.json
    (+ testnet/book.json khi holdout đạt). dry_run: chỉ báo cáo, không ghi."""
    _open(run_id).close()
    for a in req.alpha_ids:
        _alpha_id(a)
    params = {"run_id": run_id, "alpha_ids": ",".join(req.alpha_ids), "risk_per_trade_pct": req.risk_per_trade_pct,
              "wfa_job_id": req.wfa_job_id, "dry_run": req.dry_run, "explore": req.explore}
    if not req.explore and not req.wfa_job_id:
        raise HTTPException(422, "sổ chính cần wfa_job_id (gate WFA danh mục phải qua)")
    try:
        return {"job_id": batch_jobs.launch("funnel_book", params)}
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    except batch_jobs.JobBusy as e:
        raise HTTPException(429, str(e))


# ─── Đưa vào kho alpha ──────────────────────────────────────────────────────
class PromoteRequest(BaseModel):
    confirm: bool = Field(False, description="UI phải xác nhận rõ (true) — không có thì từ chối")
    note: Optional[str] = Field(None, max_length=500)


@router.post("/runs/{run_id}/alphas/{alpha_id}/promote")
def post_promote(run_id: str, alpha_id: str, req: PromoteRequest):
    """Ghi alpha FINAL vào data/alphas/registry.json (khoá mới `funnel`: s + bằng chứng) + cấu hình testnet. -> {registry_path, alpha_id, final_scale, testnet_config}."""
    _alpha_id(alpha_id)
    if not req.confirm:
        raise HTTPException(400, "cần confirm=true (xác nhận đưa alpha vào kho alpha)")
    _open(run_id).close()
    from backend.optimize.funnel.promote import promote_alpha
    try:
        return promote_alpha(_run_dir(run_id), alpha_id, alphas_dir(), req.note)
    except KeyError:
        raise HTTPException(404, f"không có alpha {alpha_id}")
    except ValueError as e:
        raise HTTPException(409, str(e))
