"""Dữ liệu thị trường (/api/data): tải nến OKX (sàn triển khai, mặc định) / Binance (tham khảo) và đưa dữ liệu đã qua quality gate từ staging vào kho — đều là job nền."""
import os
from typing import List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.api.jobs import batch as batch_jobs

router = APIRouter(prefix="/api/data", tags=["data"])
STAGING = os.path.join(batch_jobs.NORA_DIR, "data_staging")   # crawl ghi vào staging; chỉ promote (qua quality gate) mới đưa vào data/


class CrawlRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1, max_length=20)
    exchange: str = Field("okx", pattern="^(okx|binance)$")   # okx = USDT-SWAP (kèm funding) -> data/okx; binance -> data/binance
    market: str = Field("um", pattern="^(spot|um)$")       # chỉ Binance: um = USDT-M perpetual (kèm funding)
    years: float = Field(3.0, gt=0, le=8)


class PromoteRequest(BaseModel):
    apply: bool = False               # False = chỉ lập kế hoạch (dry-run)
    archive_legacy: bool = False


@router.post("/crawl")
def post_crawl(req: CrawlRequest):
    """Tải nến 1m (+ funding với perp) vào data_staging/cex; sau đó POST /promote đưa tài sản qua quality gate vào data/<sàn>/cex."""
    syms = [s.strip().upper() for s in req.symbols if s.strip().isalnum()]
    out = os.path.join(STAGING, "cex")
    if req.exchange == "okx":
        return batch_jobs.http_launch("data_crawl_okx", {"symbols": syms, "years": req.years, "output_dir": out})
    return batch_jobs.http_launch("data_crawl", {"symbols": syms, "market": req.market, "years": req.years, "output_dir": out})


@router.post("/promote")
def post_promote(req: PromoteRequest):
    """Đưa tài sản đã qua quality gate từ data_staging/ vào data/<sàn>/ (apply=False: chỉ xem kế hoạch)."""
    return batch_jobs.http_launch("data_promote", {"apply": req.apply, "archive_legacy": req.archive_legacy})
