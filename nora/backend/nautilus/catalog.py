"""Catalog Nautilus của Nora: instrument OKX perp, BarType, dựng Bar và ghi ParquetDataCatalog.

- Instrument OKX perp dựng từ data/market/okx/instruments.json (spec thật: tickSz, lotSz, ctVal, minSz, phí). Khối lượng của Nautilus tính bằng
  đồng COIN (base_currency = BTC, ETH...), nên size_increment = lotSz × ctVal (1 hợp đồng = ctVal coin).
- Nến thực thi: 1m EXTERNAL, ts_event = ts_init = GIỜ ĐÓNG nến.
- ĐỌC nến (pyarrow, gộp khung, ký hiệu) nằm ở backend/data/data.py (không import nautilus_trader); file này chỉ dựng đối tượng Nautilus và ghi catalog.
"""
import json
import os
import threading
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, CurrencyType, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Currency, Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import BarDataWrangler

from backend.data.data import CatalogError, default_catalog_path, frame_ms, normalize_symbol
from backend.models.storage import NORA_DATA_ROOT

INSTRUMENTS_PATH = os.path.join(NORA_DATA_ROOT, "market", "okx", "instruments.json")

VENUE_OKX = Venue("OKX")

_FRAME_TO_SPEC = {
    "1m": (1, BarAggregation.MINUTE), "5m": (5, BarAggregation.MINUTE), "15m": (15, BarAggregation.MINUTE),
    "1h": (1, BarAggregation.HOUR), "4h": (4, BarAggregation.HOUR), "24h": (1, BarAggregation.DAY), "1d": (1, BarAggregation.DAY),
}


_CACHE_INSTRUMENTS: Dict[Tuple[str, Optional[float], Optional[float]], CryptoPerpetual] = {}
_CACHE_LOCK = threading.RLock()
_SPECS: Dict[str, Any] = {"mtime": None, "data": {}}


def get_catalog_root() -> str:
    """Thư mục catalog đang dùng (MỘT định nghĩa: data.default_catalog_path)."""
    root = default_catalog_path()
    os.makedirs(root, exist_ok=True)
    return root


def load_instruments_specs() -> Dict[str, Any]:
    """instruments.json (spec OKX thật); đọc lại khi file đổi."""
    with _CACHE_LOCK:
        try:
            mt = os.path.getmtime(INSTRUMENTS_PATH)
        except OSError:
            raise CatalogError(f"thiếu {INSTRUMENTS_PATH} (chạy test/scripts/fetch_instruments.py)")
        if _SPECS["mtime"] != mt:
            with open(INSTRUMENTS_PATH, "r", encoding="utf-8") as f:
                _SPECS["data"] = json.load(f).get("instruments", {})
            _SPECS["mtime"] = mt
            _CACHE_INSTRUMENTS.clear()
        return _SPECS["data"]


def _decimals(x: Decimal) -> int:
    return max(0, -x.normalize().as_tuple().exponent)


def coin_currency(code: str) -> Currency:
    """Tiền tệ của đồng coin (base_currency của perp), vd BTC — KHÔNG phải USDT."""
    try:
        return Currency.from_str(code)
    except Exception:
        return Currency(code, 8, 0, code, CurrencyType.CRYPTO)


def instrument_spec(symbol: str) -> Dict[str, Any]:
    """Spec OKX thật của symbol (tickSz, lotSz, ctVal, minSz, margin_init, margin_maint, maker_fee, taker_fee, base_symbol?) từ instruments.json."""
    norm = normalize_symbol(symbol)
    spec = load_instruments_specs().get(norm)
    if spec is None:
        raise CatalogError(f"{norm}: không có trong instruments.json")
    return spec


def build_instrument(symbol: str, spec: Dict[str, Any], maker_fee: Optional[float] = None, taker_fee: Optional[float] = None) -> CryptoPerpetual:
    """CryptoPerpetual OKX từ `spec` (DataSource.instrument_spec). maker_fee/taker_fee (tỉ lệ) ghi đè phí spec — phí của engine = phí của slot
    (Nautilus tính hoa hồng từ đây)."""
    norm = normalize_symbol(symbol)
    key = (norm, tuple(sorted((k, str(v)) for k, v in spec.items())), None if maker_fee is None else float(maker_fee),
           None if taker_fee is None else float(taker_fee))
    with _CACHE_LOCK:
        if key in _CACHE_INSTRUMENTS:
            return _CACHE_INSTRUMENTS[key]
    tick = Decimal(str(spec["tickSz"]))
    ct_val = Decimal(str(spec["ctVal"]))
    step = Decimal(str(spec["lotSz"])) * ct_val            # coin mỗi lot
    min_qty = Decimal(str(spec.get("minSz", spec["lotSz"]))) * ct_val
    p_prec, s_prec = _decimals(tick), _decimals(step)
    inst = CryptoPerpetual(
        instrument_id=InstrumentId(Symbol(norm), VENUE_OKX), raw_symbol=Symbol(norm),
        base_currency=coin_currency(spec.get("base_symbol", norm.split("-")[0])), quote_currency=USDT, settlement_currency=USDT,
        is_inverse=False, price_precision=p_prec, size_precision=s_prec,
        price_increment=Price(tick, p_prec), size_increment=Quantity(step, s_prec),
        min_quantity=Quantity(min_qty, s_prec), multiplier=Quantity.from_int(1),
        margin_init=Decimal(str(spec["margin_init"])), margin_maint=Decimal(str(spec["margin_maint"])),
        maker_fee=Decimal(str(spec["maker_fee"] if maker_fee is None else maker_fee)),
        taker_fee=Decimal(str(spec["taker_fee"] if taker_fee is None else taker_fee)),
        ts_event=0, ts_init=0,
    )
    with _CACHE_LOCK:
        _CACHE_INSTRUMENTS[key] = inst
    return inst


def get_instrument(symbol: str, maker_fee: Optional[float] = None, taker_fee: Optional[float] = None) -> CryptoPerpetual:
    """Instrument từ spec THẬT của instruments.json (nguồn dữ liệu mặc định)."""
    return build_instrument(symbol, instrument_spec(symbol), maker_fee, taker_fee)


def get_bar_type(symbol: str, frame: str = "1m", internal: bool = False) -> BarType:
    step, agg = _FRAME_TO_SPEC[frame] if frame in _FRAME_TO_SPEC else (_ for _ in ()).throw(ValueError(f"Khung không hợp lệ: {frame!r}"))
    return BarType(InstrumentId(Symbol(normalize_symbol(symbol)), VENUE_OKX), BarSpecification(step, agg, PriceType.LAST),
                   AggregationSource.INTERNAL if internal else AggregationSource.EXTERNAL)


def bars_from_arrays(symbol: str, arr: Dict[str, np.ndarray], frame: str, instrument: CryptoPerpetual, lo: int = 0, hi: Optional[int] = None) -> List[Bar]:
    """Bar Nautilus (EXTERNAL, ts_event = đóng) cho arr[lo:hi] bằng BarDataWrangler (vector)."""
    hi = len(arr["t"]) if hi is None else hi
    if hi <= lo:
        return []
    ts = ((arr["t"][lo:hi] + frame_ms(frame)) * 1_000_000).astype(np.uint64)
    mat = np.ascontiguousarray(np.column_stack([arr["o"][lo:hi], arr["h"][lo:hi], arr["l"][lo:hi], arr["c"][lo:hi], arr["v"][lo:hi]]), dtype=np.float64)
    wrangler = BarDataWrangler(get_bar_type(symbol, frame), instrument)
    # BarDataWrangler.process() lê data.values (chỉ-đọc trong pandas 3) — gọi thẳng hàm dựng Bar của wrangler (cpdef dành cho map) trên ma trận ghi được.
    return list(map(wrangler._build_bar, mat, ts, ts))


def load_catalog_bars(symbol: str, start_ns: Optional[int] = None, end_ns: Optional[int] = None) -> List[Bar]:
    """Bar 1m nguyên bản của catalog theo cửa sổ ts_event (ns). Không có -> CatalogError (không có đường pkl)."""
    start = pd.Timestamp(start_ns, unit="ns", tz="UTC") if start_ns else None
    end = pd.Timestamp(end_ns, unit="ns", tz="UTC") if end_ns else None
    bars = ParquetDataCatalog(get_catalog_root()).bars(bar_types=[str(get_bar_type(symbol, "1m"))], start=start, end=end)
    if not bars:
        raise CatalogError(f"{normalize_symbol(symbol)}: catalog không có nến 1m trong cửa sổ yêu cầu")
    return bars


# ─── Ghi catalog (chỉ gọi từ backend/data/crawl.py) ──────────────────────────
def write_bars(symbol: str, df_1m: pd.DataFrame, catalog_root: Optional[str] = None, spec: Optional[Dict[str, Any]] = None) -> int:
    """Ghi nến 1m THẬT (cột open_time ms, open, high, low, close, volume = base coin) vào ParquetDataCatalog; trả số nến đã ghi.
    `spec` (tuỳ chọn) thay spec instruments.json (dùng cho dữ liệu thử). Không ghi manifest — việc đó thuộc crawl.py."""
    if df_1m.empty:
        return 0
    root = catalog_root or get_catalog_root()
    os.makedirs(root, exist_ok=True)
    instrument = build_instrument(symbol, spec) if spec is not None else get_instrument(symbol)
    arr = {"t": df_1m["open_time"].to_numpy(dtype=np.int64), "o": df_1m["open"].to_numpy(dtype=float), "h": df_1m["high"].to_numpy(dtype=float),
           "l": df_1m["low"].to_numpy(dtype=float), "c": df_1m["close"].to_numpy(dtype=float), "v": df_1m["volume"].to_numpy(dtype=float)}
    bars = bars_from_arrays(symbol, arr, "1m", instrument)
    catalog = ParquetDataCatalog(root)
    catalog.write_data([instrument])
    catalog.write_data(bars)
    return len(bars)
