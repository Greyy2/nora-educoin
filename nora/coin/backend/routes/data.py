"""Routes dữ liệu và thị trường: cập nhật catalog OKX, độ phủ nến, chế độ thị trường (regime)."""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.routes.studio import http_launch
from backend.jobs.runner import DEX_UNSUPPORTED, NotReady


data_router = APIRouter(prefix="/api/data", tags=["data"])
logger = logging.getLogger("backend.routes.data")
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
    from backend.data.crawl import scan_universe_bases
    allowed = set(UNIVERSE_BASES) | set(scan_universe_bases())
    syms = [s.strip().upper() for s in req.symbols if s.strip().isalnum()]
    bad = [s for s in syms if s not in allowed]
    if bad:
        raise HTTPException(422, f"{bad}: không thuộc rổ OKX perp của Nora ({', '.join(sorted(allowed))})")
    return http_launch("data_update", {"symbols": syms})


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


# ─── Thị trường & regime ───────────────────────────────────────────────────


market_router = APIRouter(prefix="/api/studio/market", tags=["market"])
_CACHE: "OrderedDict[tuple, tuple[float, Dict[str, Any]]]" = OrderedDict()
_LOCK = threading.Lock()
_MAX = 64
_CACHE_TTL_SECONDS = 60


REGIME_FRAME = "15m"          # nhãn regime trên nến 15m (đặc trưng 1h/4h đã đóng) — cùng đường classifier.series với job


STATE_TO_REGIME: Dict[str, str] = {
    "CRASH": "BEAR",
    "TREND_DOWN": "BEAR",
    "RANGE": "RANGE",
    "TREND_UP": "BULL",
    "SURGE": "BULL",
    "VOL_EXPANSION": "VOLATILE",
    "UNKNOWN": "UNKNOWN",
}


def _fetch_binance_klines(symbol: str, interval: str) -> pd.DataFrame:
    """Fetch closed OHLCV bars from the fixed public Binance USDⓈ-M futures endpoint."""
    base = symbol.split("@", 1)[0].split("-", 1)[0].upper()
    response = httpx.get(
        "https://fapi.binance.com/fapi/v1/klines",
        params={"symbol": f"{base}USDT", "interval": interval, "limit": 1000},
        timeout=5.0,
    )
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list):
        raise ValueError("Binance kline response is not a list")

    now_ms = int(time.time() * 1000)
    bars = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            raise ValueError("Binance kline response contains a malformed bar")
        close_time = int(row[6]) + 1
        if close_time > now_ms:
            continue
        bars.append({
            "open_time": int(row[0]),
            "close_time": close_time,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        })
    frame = pd.DataFrame(bars)
    if frame.empty:
        raise ValueError(f"Binance returned no closed {interval} candles for {base}USDT")
    frame = frame.drop_duplicates("close_time").sort_values("close_time").reset_index(drop=True)
    if not np.isfinite(frame[["open", "high", "low", "close", "volume"]].to_numpy()).all():
        raise ValueError("Binance kline response contains non-finite OHLCV values")
    return frame


def _align_feature(source_times: np.ndarray, values: np.ndarray, target_times: np.ndarray) -> np.ndarray:
    indexes = np.searchsorted(source_times, target_times, side="right") - 1
    aligned = np.full(len(target_times), np.nan, dtype=np.float64)
    valid = indexes >= 0
    aligned[valid] = values[indexes[valid]]
    return aligned


def _error_regime(symbol: str, error: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "error": error,
        "as_of": None,
        "as_of_iso": None,
        "regime": "UNKNOWN",
        "is_stale": True,
        "feed_status": "error",
        "source": "live_binance_feed",
        "current": {"state": "UNKNOWN", "label": "Chưa đủ dữ liệu", "since": None},
        "segments": [],
        "share_pct": {},
        "strategies_on": [],
        "strategies_off": [],
    }


def regime_history(symbol: str, days: int) -> Dict[str, Any]:
    """Classify live closed Binance candles; catalog history is never used as a fallback."""
    key = ("live_regime", symbol, days)
    with _LOCK:
        if key in _CACHE:
            created_at, value = _CACHE[key]
            if time.monotonic() - created_at < _CACHE_TTL_SECONDS:
                _CACHE.move_to_end(key)
                return value
            del _CACHE[key]

    from backend.analys import indicator as kernels
    from backend.analys.metrics import regime as rg
    from backend.analys.param import REGIME_MAP

    intervals = ("15m", "1h", "4h")
    with ThreadPoolExecutor(max_workers=len(intervals)) as executor:
        futures = {frame: executor.submit(_fetch_binance_klines, symbol, frame) for frame in intervals}
        frames = {frame: future.result() for frame, future in futures.items()}
    base = frames["15m"]
    base_times = base["close_time"].to_numpy(dtype=np.int64)
    features: Dict[str, Dict[str, np.ndarray]] = {}
    for frame in ("1h", "4h"):
        source = frames[frame]
        source_times = source["close_time"].to_numpy(dtype=np.int64)
        features[frame] = {}
        columns = ("roc_24", "roc_1", "bbwp_20_2_720", "er_20", "adx_14", "ema_50", "ema_200") if frame == "1h" else (
            "er_20", "adx_14", "ema_50", "ema_200"
        )
        for column in columns:
            values = kernels.compute(source, column).to_numpy(dtype=np.float64)
            features[frame][column] = _align_feature(source_times, values, base_times)

    raw = rg.raw_states(lambda frame, column: features[frame][column], len(base_times))
    labels = rg.smooth(raw, base_times)
    now_ms = int(time.time() * 1000)
    cutoff = now_ms - days * 86_400_000
    keep = base_times >= cutoff
    t, lab = base_times[keep], labels[keep]
    segs: List[List[Any]] = []
    for i, code in enumerate(lab.tolist()):
        if segs and segs[-1][2] == rg.NAMES[code]:
            segs[-1][1] = int(t[i])
        else:
            segs.append([int(t[i]), int(t[i]), rg.NAMES[code]])
    cur = rg.NAMES[int(lab[-1])] if len(lab) else "UNKNOWN"
    as_of_val = int(base_times[-1]) if len(base_times) else None
    is_stale = as_of_val is None or (now_ms - as_of_val) > 30 * 60 * 1000
    as_of_iso = (
        datetime.fromtimestamp(as_of_val / 1000, tz=timezone.utc).isoformat()
        if as_of_val is not None
        else None
    )
    regime_val = STATE_TO_REGIME.get(cur, "UNKNOWN")

    out = {
        "symbol": symbol,
        "as_of": as_of_val,
        "as_of_iso": as_of_iso,
        "regime": regime_val,
        "is_stale": is_stale,
        "feed_status": "stale" if is_stale else "active",
        "source": "live_binance_feed",
        "history_days_available": round((int(base_times[-1]) - int(base_times[0])) / 86_400_000, 2),
        "history_truncated": cutoff < int(base_times[0]),
        "current": {
            "state": cur,
            "label": rg.LABEL_VI.get(cur, "Chưa đủ dữ liệu"),
            "since": segs[-1][0] if segs else None,
        },
        "segments": segs,
        "share_pct": {
            n: round(100.0 * float((lab == c).mean()), 1)
            for c, n in enumerate(rg.NAMES)
            if len(lab) and (lab == c).any()
        },
        "strategies_on": sorted(cid for cid, cfg in REGIME_MAP.items() if cur in cfg["allowed"]),
        "strategies_off": sorted(cid for cid, cfg in REGIME_MAP.items() if cur not in cfg["allowed"]),
    }
    with _LOCK:
        _CACHE[key] = (time.monotonic(), out)
        while len(_CACHE) > _MAX:
            _CACHE.popitem(last=False)
    return out


@market_router.get("/regime")
def get_regime(symbols: Optional[str] = Query(None, description="vd BTC,SOL (mặc định các cặp perp chính)"),
               days: int = Query(30, ge=1, le=365)):
    """Current categorical regime from closed Binance candles, refreshed at most every 60 seconds."""
    from backend.routes.studio import check_symbols
    from backend.jobs.runner import JobError
    from backend.analys.metrics import regime as rg
    from backend.analys.alpha.strategies import perp_symbols
    if symbols:
        raw_syms = [s.strip() for s in symbols.split(",") if s.strip()]
        if not raw_syms:
            raise HTTPException(status_code=422, detail="Cần cung cấp ít nhất một symbol.")
        try:
            syms = check_symbols(raw_syms)
        except JobError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        syms = perp_symbols()
    if not syms:
        raise HTTPException(status_code=503, detail="COIN perpetual universe is unavailable.")

    out_symbols = []
    with ThreadPoolExecutor(max_workers=min(4, len(syms))) as executor:
        futures = [executor.submit(regime_history, symbol, days) for symbol in syms]
    for s, future in zip(syms, futures):
        try:
            out_symbols.append(future.result())
        except Exception as exc:
            logger.exception("Live regime feed failed for %s", s)
            out_symbols.append(_error_regime(s, f"{type(exc).__name__}: {exc}"))

    if symbols and out_symbols:
        primary = out_symbols[0]
    else:
        primary = next((x for x in out_symbols if "BTC" in x.get("symbol", "").upper()), out_symbols[0] if out_symbols else None)

    primary_as_of = primary.get("as_of") if primary else None
    primary_as_of_iso = primary.get("as_of_iso") if primary else None
    primary_stale = primary.get("is_stale", True) if primary else True
    primary_regime = primary.get("regime", "UNKNOWN") if primary else "UNKNOWN"
    primary_status = primary.get("feed_status", "error") if primary else "error"

    return {
        "as_of": primary_as_of,
        "as_of_iso": primary_as_of_iso,
        "regime": primary_regime,
        "confidence": None,  # Phân loại categorical trên nến đóng, không có xác suất hậu nghiệm đo lường được; không bịa số
        "cadence_sec": 60,
        "source": "live_binance_feed",
        "source_type": "closed_candle",
        "feed_status": primary_status,
        "is_stale": primary_stale,
        "days": days,
        "frame": REGIME_FRAME,
        "names": list(rg.NAMES),
        "labels_vi": rg.LABEL_VI,
        "symbols": out_symbols,
    }


ROUTERS = [data_router, market_router]
