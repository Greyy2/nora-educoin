"""Routes dữ liệu và thị trường (P11): crawl dữ liệu, kiểm tra độ phủ nến/tick, chế độ thị trường (regime).

Gộp từ: data.py, market.py.
"""
"""Dữ liệu thị trường (/api/data): tải nến OKX (sàn triển khai, mặc định) / Binance (tham khảo) và đưa dữ liệu đã qua quality gate từ staging vào kho — đều là job nền."""
import os
from typing import Annotated, List

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints

from backend.routes import process as batch_jobs
from backend.crawl.dex import DEFAULT_TICK_DAYS, MAX_TICK_DAYS
from backend.optimize.process.process import DEX_UNSUPPORTED, NotReady

data_router = APIRouter(prefix="/api/data", tags=["data"])
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


@data_router.post("/crawl")
def post_crawl(req: CrawlRequest):
    """Tải nến 1m (+ funding với perp) vào thư mục process của job (staging/cex); sau đó POST /promote đưa tài sản qua quality gate vào data/<sàn>/cex."""
    syms = [s.strip().upper() for s in req.symbols if s.strip().isalnum()]
    if req.exchange == "okx":
        return batch_jobs.http_launch("data_crawl_okx", {"symbols": syms, "years": req.years})
    return batch_jobs.http_launch("data_crawl", {"symbols": syms, "market": req.market, "years": req.years})


@data_router.post("/ticks/crawl")
def post_ticks_crawl(req: TicksRequest):
    """501 NOT_READY: tick swap on-chain chỉ phục vụ backtest AMM, Nautilus không hỗ trợ DEX/AMM (mã crawl giữ nguyên trong backend/crawl/dex.py)."""
    raise NotReady(DEX_UNSUPPORTED)


@data_router.get("/ticks/coverage")
def get_ticks_coverage():
    """501 NOT_READY: xem /ticks/crawl (không có backtest tick trên Nautilus)."""
    raise NotReady(DEX_UNSUPPORTED)


@data_router.post("/promote")
def post_promote(req: PromoteRequest):
    """Đưa tài sản đã qua quality gate từ staging của các job crawl vào market/<sàn>/ (apply=False: chỉ xem kế hoạch)."""
    return batch_jobs.http_launch("data_promote", {"apply": req.apply, "archive_legacy": req.archive_legacy})



# ══════════════════════════════════════════════════════════════════════════
# PHẦN 2: THỊ TRƯỜNG & REGIME (gộp từ market.py)
# ══════════════════════════════════════════════════════════════════════════

import os
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

market_router = APIRouter(prefix="/api/studio/market", tags=["market"])
_CACHE: "OrderedDict[tuple, Dict[str, Any]]" = OrderedDict()
_LOCK = threading.Lock()
_MAX = 64


def _fingerprint(symbol: str) -> Optional[tuple]:
    from backend.crawl.store import resolve_symbol_dir
    d = resolve_symbol_dir(symbol)
    if not d:
        return None
    f = os.path.join(d, "1m.pkl")
    try:
        st = os.stat(f)
        return (f, st.st_mtime_ns, st.st_size)
    except OSError:
        return None


REGIME_FRAME = "15m"          # nhãn regime trên nến 15m (đặc trưng 1h/4h đã đóng) — cùng đường classifier.series với job


def regime_history(symbol: str, days: int) -> Dict[str, Any]:
    """Regime hiện tại + lịch sử `days` ngày cuối của một tài sản: các đoạn [bắt đầu, kết thúc, trạng thái], tỷ trọng thời gian, chiến lược
    được bật ở regime hiện tại theo bảng của sổ (book.REGIME_MAP)."""
    from backend.optimize.search.evaluate import WARMUP
    from backend.regime import regime as rg
    from backend.core.params import REGIME_MAP
    from backend.crawl.store import read_manifest
    m = read_manifest(symbol)
    if not m:
        return {"symbol": symbol, "error": "chưa có dữ liệu (manifest)"}
    end = int(m["end_ts"]) + 60_000
    key = ("regime", symbol, _fingerprint(symbol), end, days)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    start = end - days * 86_400_000
    s = rg.series(symbol, start - WARMUP, end, base_frame=REGIME_FRAME)
    keep = (s["t"] >= start) & s["real"]
    t, lab = s["t"][keep], s["labels"][keep]
    segs: List[List[Any]] = []
    for i, code in enumerate(lab.tolist()):
        if segs and segs[-1][2] == rg.NAMES[code]:
            segs[-1][1] = int(t[i])
        else:
            segs.append([int(t[i]), int(t[i]), rg.NAMES[code]])
    cur = rg.NAMES[int(lab[-1])] if len(lab) else "UNKNOWN"
    out = {"symbol": symbol, "as_of": int(t[-1]) if len(t) else None,
           "current": {"state": cur, "label": rg.LABEL_VI[cur], "since": segs[-1][0] if segs else None},
           "segments": segs,
           "share_pct": {n: round(100.0 * float((lab == c).mean()), 1) for c, n in enumerate(rg.NAMES) if len(lab) and (lab == c).any()},
           "strategies_on": sorted(cid for cid, cfg in REGIME_MAP.items() if cur in cfg["allowed"]),
           "strategies_off": sorted(cid for cid, cfg in REGIME_MAP.items() if cur not in cfg["allowed"])}
    with _LOCK:
        _CACHE[key] = out
        while len(_CACHE) > _MAX:
            _CACHE.popitem(last=False)
    return out


@market_router.get("/regime")
def get_regime(symbols: Optional[str] = Query(None, description="vd BTC,SOL (mặc định cả vũ trụ perp của sổ)"),
               days: int = Query(30, ge=1, le=365)):
    """Regime hiện tại + lịch sử từng tài sản (nến 15m đã đóng) và chiến lược đang bật theo bảng regime của sổ."""
    from backend.optimize.process.process import JobError
    from backend.routes.process import check_symbols
    from backend.regime import regime as rg
    from backend.optimize.book.build import perp_symbols
    try:
        syms = check_symbols([s for s in symbols.split(",") if s]) if symbols else perp_symbols()
    except JobError as e:
        raise HTTPException(422, str(e))
    return {"days": days, "frame": REGIME_FRAME, "names": list(rg.NAMES), "labels_vi": rg.LABEL_VI,
            "symbols": [regime_history(s, days) for s in syms]}


class RegimeReportRequest(BaseModel):
    symbols: Optional[List[str]] = Field(None, max_length=16, description="Mặc định cả vũ trụ perp của sổ")
    start: Optional[str] = None
    end: Optional[str] = None
    event_pct: float = Field(12.0, ge=3.0, le=50.0, description="Ngưỡng sự kiện thẳng đứng (|lợi suất 24h| %) dùng để chấm điểm")
    backtest: bool = Field(True, description="Chạy kèm sổ presets tắt/bật regime để so sánh")
    timeframe: str = Field("15m", pattern="^(15m|1h|4h)$", description="Khung chạy (nến mô phỏng)")


@market_router.post("/regime/report")
def post_regime_report(req: RegimeReportRequest):
    """Báo cáo độ chính xác regime + so sánh bật/tắt regime (job nền regime_report, kết quả ở result.json của job)."""
    from backend.optimize.process import process as batch_jobs
    from backend.routes import process as batch_jobs_routes
    p: Dict[str, Any] = {"event_pct": req.event_pct, "backtest": req.backtest, "timeframe": req.timeframe}
    try:
        if req.symbols:
            p["symbols"] = ",".join(batch_jobs_routes.check_symbols(req.symbols))
        for k in ("start", "end"):
            if getattr(req, k):
                p[k] = batch_jobs_routes.check_date(getattr(req, k))
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    return batch_jobs_routes.http_launch("regime_report", p)



ROUTERS = [data_router, market_router]
