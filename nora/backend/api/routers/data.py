"""Dữ liệu thị trường (/api/data): tải nến Binance và đưa dữ liệu đã qua quality gate từ staging vào kho — đều là job nền."""
from typing import List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.api.jobs import batch as batch_jobs

router = APIRouter(prefix="/api/data", tags=["data"])


class CrawlRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1, max_length=20)
    market: str = Field("um", pattern="^(spot|um)$")       # um = USDT-M perpetual (kèm funding)
    years: float = Field(3.0, gt=0, le=8)


class PromoteRequest(BaseModel):
    apply: bool = False               # False = chỉ lập kế hoạch (dry-run)
    archive_legacy: bool = False


@router.post("/crawl")
def post_crawl(req: CrawlRequest):
    """Tải nến 1m (+ funding với perp) cho các tài sản; quality gate vẫn chặn ở mọi bước chạy sau."""
    syms = [s.strip().upper() for s in req.symbols if s.strip().isalnum()]
    return batch_jobs.http_launch("data_crawl", {"symbols": syms, "market": req.market, "years": req.years})


@router.post("/promote")
def post_promote(req: PromoteRequest):
    """Đưa tài sản đã qua quality gate từ data_staging/ vào data/ (apply=False: chỉ xem kế hoạch)."""
    return batch_jobs.http_launch("data_promote", {"apply": req.apply, "archive_legacy": req.archive_legacy})
