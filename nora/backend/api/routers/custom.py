"""API backtest chiến lược Python tùy chỉnh (P7): POST /api/studio/custom/backtest -> job `custom_backtest` (core/backtest/custom_run.py); GET /api/studio/custom/defaults = rổ + cửa sổ mặc định từ kho dữ liệu.

Theo dõi / lấy kết quả như mọi job: GET /api/studio/book/jobs/{job_id}. Biên dịch thử: api/routers/strategies.py (/compile). Lưu = POST /api/studio/alphas/user (alphas.py); chạy tạm tự xoá sau 24 h nếu không lưu.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.api.jobs import batch as batch_jobs
from backend.core.analytics import user_alphas

router = APIRouter(prefix="/api/studio/custom", tags=["custom"])


class CustomBacktestRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50_000, description="Mã Python class X(SimpleAlgorithm)")
    symbols: Optional[List[str]] = Field(None, max_length=16, description="BTC hoặc BTC@perp; bỏ trống = cả 10 tài sản OKX trong kho dữ liệu")
    start: str
    end: str
    train_ratio: float = Field(0.7, ge=0.05, le=0.95)
    initial_capital: Optional[float] = Field(None, gt=0, le=1e9, description="Mặc định 10000")
    position: Optional[Dict[str, Any]] = Field(None, description="Ghi đè tham số vị thế (khoá của params.builder.POSITION_KEYS)")
    run_frame: Optional[str] = Field(None, pattern="^(1m|5m|15m|1h|4h|24h)$", description="Khung chạy; mặc định 1m")

    @field_validator("start", "end")
    @classmethod
    def _date(cls, v):
        return batch_jobs.check_date(v)


@router.get("/defaults")
def get_run_defaults() -> Dict[str, Any]:
    """Mặc định của form chạy, tính từ kho dữ liệu OKX: {symbols (rổ perp), start, end (phần dữ liệu chung), train_ratio, initial_capital}."""
    from backend.core.backtest.run_defaults import run_defaults
    try:
        return run_defaults()
    except ValueError as e:
        raise HTTPException(503, str(e))


@router.post("/backtest")
def post_custom_backtest(req: CustomBacktestRequest) -> Dict[str, str]:
    """Khởi chạy job custom_backtest -> {"job_id"}. Lỗi code: 422 với thông điệp 'Lỗi biên dịch: dòng L, cột C: ...'."""
    try:
        params = batch_jobs.build_job("custom_backtest", req.model_dump(exclude_none=True))
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    launched = batch_jobs.http_launch("custom_backtest", params)
    user_alphas.cleanup_quietly()     # chạy tạm chỉ giữ 24 h nếu không được lưu thành alpha (core/analytics/user_alphas.py)
    return launched
