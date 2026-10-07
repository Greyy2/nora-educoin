"""API backtest chiến lược Python tùy chỉnh (P7): POST /api/studio/custom/backtest -> job `custom_backtest` (core/backtest/custom_run.py).

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
    profile: str = Field("xno", pattern="^(xno|nora)$", description="xno: xấp xỉ xnoquant; nora: quản lý vị thế của Nora")
    universe: Optional[str] = Field(None, description="TOP10 (rổ xnoquant). Bỏ trống: xno = TOP10, nora = vũ trụ perp của sổ")
    symbols: Optional[List[str]] = Field(None, max_length=16, description="BTC hoặc BTC@perp; ghi đè universe")
    start: str
    end: str
    train_ratio: float = Field(0.7, ge=0.05, le=0.95)
    initial_capital: Optional[float] = Field(None, gt=0, le=1e9, description="Mặc định xno 100000, nora 10000")
    position: Optional[Dict[str, Any]] = Field(None, description="Chỉ nora: ghi đè tham số vị thế (khoá của params.builder.POSITION_KEYS)")
    market: Optional[str] = Field(None, pattern="^(perp|spot)$", description="Chỉ nora (mặc định perp)")
    run_frame: Optional[str] = Field(None, pattern="^(1m|5m|15m|1h|4h|24h)$", description="Khung chạy; mặc định xno = khung chiến lược, nora = 1m")
    exchange: Optional[str] = Field(None, max_length=32, description="Nguồn dữ liệu (thư mục data/<exchange>); bỏ trống = như hiện tại")

    @field_validator("start", "end")
    @classmethod
    def _date(cls, v):
        return batch_jobs.check_date(v)


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
