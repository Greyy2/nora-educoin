"""API sổ chiến lược (strategy book): xem sổ hiện tại + chạy backtest danh mục / WFA danh mục / dựng sổ như job nền.

Job nặng chạy ở tiến trình riêng qua scripts/run_limited.sh (xem backend/studio_pipeline/batch_jobs.py), handler ở đây chỉ
khởi chạy / đọc file nên nhanh và là `def` thường (FastAPI chạy trong threadpool).
"""
import json
import math
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.studio_pipeline import batch_jobs

router = APIRouter(prefix="/api/studio/book", tags=["book"])
alphas_router = APIRouter(prefix="/api/studio", tags=["book"])

MC_MIN_DAYS, MC_MAX_DAYS = 20, 5000
MC_RUIN_MAX_PCT = 5.0   # gate ruin (khớp portfolio_wfa.MAX_MC_RUIN_PCT)
_METRIC_KEYS = ("ret_pct", "mdd_pct", "sharpe", "trades", "win_pct", "symbols_positive", "halted_at")


# ─── Mô hình yêu cầu ────────────────────────────────────────────────────────
class StrategyIn(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    params: Dict[str, float] = Field(default_factory=dict, description="Thiếu khoá nào lấy mức giữa của không gian tham số ứng viên")


class _DateRange(BaseModel):
    @field_validator("start", "end", check_fields=False)
    @classmethod
    def _date(cls, v):
        return batch_jobs.check_date(v) if v else v


class BacktestRequest(_DateRange):
    strategies: Optional[List[StrategyIn]] = Field(None, max_length=16, description="Bỏ trống = dùng alphas/book.json")
    symbols: Optional[List[str]] = Field(None, max_length=16, description="Mặc định cả vũ trụ (perp)")
    start: str
    end: str
    risk_per_trade_pct: Optional[float] = Field(None, gt=0.0, le=5.0)
    stop_fill: str = Field("level", pattern="^(level|extreme)$")


class WfaStrategyIn(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    configs: List[Dict[str, float]] = Field(..., min_length=1, max_length=batch_jobs.MAX_WFA_CONFIGS,
                                            description="1 cấu hình = tham số cố định (WFA chỉ kiểm OOS cuộn)")


class WfaRequest(_DateRange):
    report_dir: Optional[str] = Field(None, max_length=256, description="Lần chạy build_strategy_book trong data/_cache/book/")
    include_rejected: bool = False
    candidates: Optional[List[str]] = Field(None, max_length=16)
    strategies: Optional[List[WfaStrategyIn]] = Field(None, max_length=batch_jobs.MAX_WFA_STRATEGIES,
                                                       description="Cấu hình do người dùng chọn: dùng ĐÚNG các cấu hình này")
    symbols: Optional[List[str]] = Field(None, max_length=16)
    n: int = Field(3, ge=1, le=50)
    start: Optional[str] = None
    end: Optional[str] = None
    train_days: Optional[int] = Field(None, ge=7, le=1000)
    test_days: Optional[int] = Field(None, ge=1, le=365)
    risk_per_trade_pct: Optional[float] = Field(None, gt=0.0, le=5.0)

    @model_validator(mode="after")
    def _one_source(self):
        if sum(map(bool, (self.report_dir, self.candidates, self.strategies))) != 1:
            raise ValueError("chọn đúng một: report_dir, candidates hoặc strategies")
        return self


class McRequest(BaseModel):
    wfa_job_id: Optional[str] = Field(None, max_length=64, description="Job book_wfa đã xong (lấy chuỗi lợi suất ngày OOS)")
    daily_returns: Optional[List[float]] = Field(None, min_length=MC_MIN_DAYS, max_length=MC_MAX_DAYS,
                                                 description="Lợi suất ngày dạng số thập phân (0.01 = 1%)")
    basis: str = Field("extreme", pattern="^(extreme|level)$")
    simulations: int = Field(4000, ge=100, le=10_000)
    block_days: int = Field(5, ge=1, le=30)
    horizon_days: int = Field(365, ge=5, le=730)
    ruin_threshold_pct: float = Field(30.0, gt=0.0, le=100.0)
    seed: int = Field(7, ge=0, le=2**31 - 1)
    scale: float = Field(1.0, gt=0.0, le=10.0)

    @model_validator(mode="after")
    def _one_source(self):
        if bool(self.wfa_job_id) == bool(self.daily_returns):
            raise ValueError("chọn đúng một: wfa_job_id hoặc daily_returns")
        return self


class BuildRequest(BaseModel):
    only: Optional[List[str]] = Field(None, max_length=16)
    n: Optional[int] = Field(None, ge=1, le=200, description="Số cấu hình thử mỗi chiến lược ở dev1 (mặc định 24)")


# ─── Đọc sổ / báo cáo ───────────────────────────────────────────────────────
def book_path() -> str:
    return os.environ.get("NORA_BOOK_PATH") or os.path.join(batch_jobs.NORA_DIR, "alphas", "book.json")


def _metrics(m: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {k: m[k] for k in _METRIC_KEYS if k in m} if isinstance(m, dict) else None


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
    from backend.db.data_layout import cache_dir
    base = cache_dir(None, "book_wfa")
    for name in sorted(os.listdir(base), reverse=True):
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
    """Giá trị GIỮA của mỗi khoá trong không gian tham số (cùng quy tắc scripts/run_book_backtest._mid_params)."""
    return {k: v[len(v) // 2] for k, v in space.items()}


def _catalog() -> List[Dict[str, Any]]:
    from backend.alpha.strategy_book import CANDIDATES
    return [{"id": c["id"], "family": c["family"], "side": c["side"], "description": c["description"],
             "space": c["space"], "default_params": default_params(c["space"])} for c in CANDIDATES]


def _universe_windows(book: Optional[Dict[str, Any]]):
    """(universe, windows dạng ngày): lấy từ sổ nếu có, không thì từ vũ trụ + dữ liệu hiện có (như build_strategy_book.windows)."""
    from backend.alpha.strategy_book import perp_symbols
    universe = (book or {}).get("universe") or perp_symbols()
    windows = (book or {}).get("windows")
    if not windows:
        try:
            import pandas as pd
            from backend.db.local_pkl import read_manifest
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
@router.get("/")
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
            "universe": universe, "windows": windows}


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise HTTPException(500, f"{os.path.basename(path)} hỏng: {e}")


@alphas_router.get("/alphas")
def get_alphas():
    """Kho alpha: registry.json + book.json (null nếu chưa có)."""
    return {"registry": _read_json(os.path.join(batch_jobs.NORA_DIR, "alphas", "registry.json")),
            "book": _read_json(book_path())}


def _launch(kind: str, params: Dict[str, Any]) -> Dict[str, str]:
    try:
        args, files = batch_jobs.build_job(kind, params)
        job_id = batch_jobs.launch(kind, args, files)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    except batch_jobs.JobBusy as e:
        raise HTTPException(429, str(e))
    return {"job_id": job_id}


@router.post("/backtest")
def post_backtest(req: BacktestRequest):
    if not req.strategies and not os.path.isfile(book_path()):
        raise HTTPException(409, "chưa có alphas/book.json — truyền strategies hoặc dựng sổ trước (POST /build)")
    return _launch("book_backtest", req.model_dump())


@router.post("/wfa")
def post_wfa(req: WfaRequest):
    return _launch("book_wfa", req.model_dump())


@router.post("/build")
def post_build(req: BuildRequest):
    return _launch("book_build", req.model_dump())


@router.get("/jobs")
def get_jobs(limit: int = 20, kind: Optional[str] = None):
    try:
        return {"jobs": batch_jobs.list_jobs(limit, kind)}
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    try:
        s = batch_jobs.status(job_id)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    if s is None:
        raise HTTPException(404, "không có job này")
    return s


# ─── Monte Carlo ngày (đồng bộ, nhẹ) ────────────────────────────────────────
@router.post("/mc")
def post_mc(req: McRequest):
    """Block bootstrap lợi suất ngày OOS của một job book_wfa (hoặc chuỗi tự gửi); trả tóm tắt + fan + histogram + gate ruin."""
    from backend.studio_pipeline.monte_carlo import run_monte_carlo_daily_detail
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
        daily = (((job["result"].get("summary") or {}).get("oos_daily")) or {}).get(req.basis) or []
        source = {"kind": "wfa", "job_id": req.wfa_job_id, "basis": req.basis}
    else:
        daily, source = req.daily_returns, {"kind": "daily_returns"}
        # kiểm ở đây (không trong validator pydantic): lỗi validator kèm đầu vào NaN làm FastAPI không dựng được phản hồi 422
        if not all(math.isfinite(x) and x > -1.0 for x in daily):
            raise HTTPException(422, "daily_returns phải hữu hạn và > -1 (-100%)")
    if len(daily) < MC_MIN_DAYS:
        raise HTTPException(422, f"cần >= {MC_MIN_DAYS} lợi suất ngày (có {len(daily)})")
    out = run_monte_carlo_daily_detail(daily, simulations=req.simulations, block_days=req.block_days, horizon_days=req.horizon_days,
                                       ruin_threshold_pct=req.ruin_threshold_pct, seed=req.seed, scale=req.scale,
                                       max_ruin_pct=MC_RUIN_MAX_PCT)
    out["params"].update(source=source, basis=req.basis)
    return out
