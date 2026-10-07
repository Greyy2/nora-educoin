"""Dữ liệu thị trường (/api/data): tải nến OKX (sàn triển khai, mặc định) / Binance (tham khảo) và đưa dữ liệu đã qua quality gate từ staging vào kho — đều là job nền."""
import os
from typing import Annotated, List

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints

from backend.api.jobs import batch as batch_jobs
from backend.db.tick_storage import DEFAULT_TICK_DAYS, MAX_TICK_DAYS, tick_coverage

router = APIRouter(prefix="/api/data", tags=["data"])
# Crawl ghi vào <cache/process>/<job>/staging/cex (batch.launch đặt output_dir); chỉ promote (qua quality gate) mới đưa vào market/<sàn>/ rồi xoá staging.


class CrawlRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1, max_length=20)
    exchange: str = Field("okx", pattern="^(okx|binance)$")   # okx = USDT-SWAP (kèm funding) -> data/okx; binance -> data/binance
    market: str = Field("um", pattern="^(spot|um)$")       # chỉ Binance: um = USDT-M perpetual (kèm funding)
    years: float = Field(3.0, gt=0, le=8)


class TicksRequest(BaseModel):
    symbols: List[Annotated[str, StringConstraints(pattern=r"^(dex:)?[A-Za-z0-9_]{1,20}$")]] = Field(..., min_length=1, max_length=20)   # tài sản DEX ("AERO" / "dex:AERO")
    days: int = Field(DEFAULT_TICK_DAYS, ge=1, le=MAX_TICK_DAYS)


class PromoteRequest(BaseModel):
    apply: bool = False               # False = chỉ lập kế hoạch (dry-run)
    archive_legacy: bool = False


@router.post("/crawl")
def post_crawl(req: CrawlRequest):
    """Tải nến 1m (+ funding với perp) vào thư mục process của job (staging/cex); sau đó POST /promote đưa tài sản qua quality gate vào data/<sàn>/cex."""
    syms = [s.strip().upper() for s in req.symbols if s.strip().isalnum()]
    if req.exchange == "okx":
        return batch_jobs.http_launch("data_crawl_okx", {"symbols": syms, "years": req.years})
    return batch_jobs.http_launch("data_crawl", {"symbols": syms, "market": req.market, "years": req.years})


@router.post("/ticks/crawl")
def post_ticks_crawl(req: TicksRequest):
    """Tải tick (swap on-chain) của pool DEX ĐÃ có nến vào cửa sổ trượt `days` ngày, ghi cạnh nến + manifest["ticks"]. CEX chỉ có nến."""
    return batch_jobs.http_launch("data_crawl_ticks", {"symbols": req.symbols, "days": req.days})


@router.get("/ticks/coverage")
def get_ticks_coverage():
    """Độ phủ tick từng tài sản đang có: [{symbol, venue, start_ts, end_ts, rows, window_days, source}]."""
    return {"assets": tick_coverage()}


@router.post("/promote")
def post_promote(req: PromoteRequest):
    """Đưa tài sản đã qua quality gate từ staging của các job crawl vào market/<sàn>/ (apply=False: chỉ xem kế hoạch)."""
    return batch_jobs.http_launch("data_promote", {"apply": req.apply, "archive_legacy": req.archive_legacy})
