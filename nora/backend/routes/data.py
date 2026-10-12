"""Routes dữ liệu và thị trường (P11): cập nhật catalog OKX, độ phủ nến, chế độ thị trường (regime).

Gộp từ: data.py, market.py.
"""
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.routes import process as batch_jobs
from backend.optimize.process.process import DEX_UNSUPPORTED, NotReady

data_router = APIRouter(prefix="/api/data", tags=["data"])
# Cập nhật nến OKX perp vào ParquetDataCatalog (job nền data_update -> backend.data.crawl.run_job); catalog + manifest ghi thẳng, không còn staging/promote.


class CrawlRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1, max_length=20)


class TicksRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1, max_length=20)   # tài sản DEX ("AERO" / "dex:AERO")
    days: int = Field(7, ge=1, le=30)


class PromoteRequest(BaseModel):
    apply: bool = False
    archive_legacy: bool = False


@data_router.post("/crawl")
def post_crawl(req: CrawlRequest):
    """Cập nhật catalog nến 1m OKX perp (rổ cố định 10 tài sản) tới hiện tại; kiểm định chất lượng ghi vào manifest."""
    from backend.data.data import UNIVERSE_BASES
    syms = [s.strip().upper() for s in req.symbols if s.strip().isalnum()]
    bad = [s for s in syms if s not in UNIVERSE_BASES]
    if bad:
        raise HTTPException(422, f"{bad}: không thuộc rổ OKX perp của Nora ({', '.join(UNIVERSE_BASES)})")
    return batch_jobs.http_launch("data_update", {"symbols": syms})


@data_router.post("/ticks/crawl")
def post_ticks_crawl(req: TicksRequest):
    """501 NOT_READY: tick swap on-chain chỉ phục vụ backtest AMM, Nautilus không hỗ trợ DEX/AMM."""
    raise NotReady(DEX_UNSUPPORTED)


@data_router.get("/ticks/coverage")
def get_ticks_coverage():
    """501 NOT_READY: xem /ticks/crawl (không có backtest tick trên Nautilus)."""
    raise NotReady(DEX_UNSUPPORTED)


@data_router.post("/promote")
def post_promote(req: PromoteRequest):
    """501 NOT_READY: không còn bước promote — job data_update ghi thẳng vào catalog (kiểm định chất lượng nằm trong manifest)."""
    raise NotReady("Không còn bước chuyển dữ liệu vào kho: data_update ghi thẳng vào catalog")


# ══════════════════════════════════════════════════════════════════════════
# PHẦN 2: THỊ TRƯỜNG & REGIME (gộp từ market.py)
# ══════════════════════════════════════════════════════════════════════════

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
    """Khoá cache theo dấu vân tay catalog của tài sản (đổi khi catalog được cập nhật)."""
    from backend.data.data import catalog_digest
    try:
        return (catalog_digest([symbol]),)
    except ValueError:
        return None


REGIME_FRAME = "15m"          # nhãn regime trên nến 15m (đặc trưng 1h/4h đã đóng) — cùng đường classifier.series với job


def regime_history(symbol: str, days: int) -> Dict[str, Any]:
    """Regime hiện tại + lịch sử `days` ngày cuối của một tài sản: các đoạn [bắt đầu, kết thúc, trạng thái], tỷ trọng thời gian, chiến lược
    được bật ở regime hiện tại theo bảng của sổ (book.REGIME_MAP)."""
    from backend.optimize.search.evaluate import WARMUP
    from backend.metrics import regime as rg
    from backend.models.params import REGIME_MAP
    from backend.data.data import read_manifest
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
    from backend.metrics import regime as rg
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
