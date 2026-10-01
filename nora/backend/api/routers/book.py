"""API sổ chiến lược (strategy book): xem sổ hiện tại + chạy backtest danh mục / WFA danh mục / dựng sổ như job nền.

Job nặng chạy ở tiến trình riêng qua scripts/run_limited.sh (xem backend/studio_pipeline/batch_jobs.py), handler ở đây chỉ
khởi chạy / đọc file nên nhanh và là `def` thường (FastAPI chạy trong threadpool).
"""
import json
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.studio_pipeline import batch_jobs

router = APIRouter(prefix="/api/studio/book", tags=["book"])

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


class WfaRequest(_DateRange):
    report_dir: Optional[str] = Field(None, max_length=256, description="Lần chạy build_strategy_book trong data/_cache/book/")
    include_rejected: bool = False
    candidates: Optional[List[str]] = Field(None, max_length=16)
    n: int = Field(3, ge=1, le=50)
    start: Optional[str] = None
    end: Optional[str] = None
    train_days: Optional[int] = Field(None, ge=7, le=1000)
    test_days: Optional[int] = Field(None, ge=1, le=365)
    risk_per_trade_pct: Optional[float] = Field(None, gt=0.0, le=5.0)

    @model_validator(mode="after")
    def _one_source(self):
        if bool(self.report_dir) == bool(self.candidates):
            raise ValueError("chọn đúng một: report_dir hoặc candidates")
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


def _catalog() -> List[Dict[str, Any]]:
    from backend.alpha.strategy_book import CANDIDATES
    return [{"id": c["id"], "family": c["family"], "side": c["side"], "description": c["description"],
             "space": c["space"]} for c in CANDIDATES]


# ─── Điểm cuối ──────────────────────────────────────────────────────────────
@router.get("/")
def get_book():
    book = None
    path = book_path()
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                book = _book_summary(json.load(fh))
        except (OSError, ValueError, KeyError) as e:
            raise HTTPException(500, f"book.json hỏng: {e}")
    return {"book": book, "wfa": latest_wfa_summary(), "candidates": _catalog()}


def _launch(kind: str, params: Dict[str, Any]) -> Dict[str, str]:
    try:
        job_id = batch_jobs.launch(kind, batch_jobs.build_args(kind, params))
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
def get_jobs(limit: int = 20):
    return {"jobs": batch_jobs.list_jobs(limit)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    try:
        s = batch_jobs.status(job_id)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    if s is None:
        raise HTTPException(404, "không có job này")
    return s
