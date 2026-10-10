"""Catalog Nautilus của Nora (P15): ParquetDataCatalog là kho nến chuẩn duy nhất của engine.

- Instrument OKX perp dựng từ data/market/okx/instruments.json (spec thật: tickSz, lotSz, ctVal, minSz, phí). Khối lượng của Nautilus tính bằng
  đồng COIN (base_currency = BTC, ETH...), nên size_increment = lotSz × ctVal (1 hợp đồng = ctVal coin).
- Nến thực thi: 1m EXTERNAL, ts_event = ts_init = GIỜ ĐÓNG nến. Khung lớn hơn (base_frame > 1m): MỘT hàm `aggregate_frame` gộp nến 1m THẬT
  của catalog thành nến EXTERNAL căn open_time (ts_event = đóng). Không có đường pkl: thiếu catalog -> CatalogError rõ ràng.
- Đọc nhanh (không iterrows, không Bar-by-Bar): đọc parquet bằng pyarrow, giải mã số cố định 128-bit (FIXED_SCALAR) bằng numpy, rồi
  BarDataWrangler dựng Bar. Có tự kiểm giải mã so với `ParquetDataCatalog.bars` một lần mỗi tiến trình.
"""
import glob
import json
import os
import threading
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, CurrencyType, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import FIXED_SCALAR, Currency, Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import BarDataWrangler

NORA_DATA_ROOT = os.environ.get("NORA_DATA_ROOT", "/home/vmc03/norabt/nora/data")
DEFAULT_CATALOG_PATH = os.path.join(NORA_DATA_ROOT, "market", "okx", "catalog")
INSTRUMENTS_PATH = os.path.join(NORA_DATA_ROOT, "market", "okx", "instruments.json")

VENUE_OKX = Venue("OKX")
MINUTE_MS = 60_000

_FRAME_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "24h": 86_400_000, "1d": 86_400_000}
_FRAME_TO_SPEC = {
    "1m": (1, BarAggregation.MINUTE), "5m": (5, BarAggregation.MINUTE), "15m": (15, BarAggregation.MINUTE),
    "1h": (1, BarAggregation.HOUR), "4h": (4, BarAggregation.HOUR), "24h": (1, BarAggregation.DAY), "1d": (1, BarAggregation.DAY),
}


class CatalogError(RuntimeError):
    """Catalog thiếu / không đọc được dữ liệu cần thiết (không có đường dự phòng âm thầm)."""


_CACHE_INSTRUMENTS: Dict[Tuple[str, Optional[float], Optional[float]], CryptoPerpetual] = {}
_CACHE_LOCK = threading.RLock()
_SPECS: Dict[str, Any] = {"mtime": None, "data": {}}
_DECODE_CHECKED: Dict[str, bool] = {}
_BARS_CACHE: Any = None   # ByteLRU: (symbol, frame, start, end) -> mảng nến


def get_catalog_root() -> str:
    os.makedirs(DEFAULT_CATALOG_PATH, exist_ok=True)
    return DEFAULT_CATALOG_PATH


def frame_ms(frame: str) -> int:
    try:
        return _FRAME_MS[frame]
    except KeyError:
        raise ValueError(f"Khung không hợp lệ: {frame!r} (có: {list(_FRAME_MS)})")


# ─── Ký hiệu ────────────────────────────────────────────────────────────────
def normalize_symbol(symbol: str) -> str:
    """'BTC', 'BTC@perp', 'cex:btc@perp', 'BTC-USDT-SWAP' -> 'BTC-USDT-SWAP'. Tài sản DEX không có trong Nautilus -> ValueError."""
    s = symbol.strip()
    if s.lower().startswith("dex:"):
        raise ValueError(f"{symbol}: tài sản DEX (AMM) không được Nautilus hỗ trợ")
    if "@" in s:
        s = s.split("@")[0]
    if ":" in s:
        s = s.split(":")[-1]
    if not s.endswith("-SWAP"):
        s = f"{s}-SWAP" if s.upper().endswith("-USDT") else f"{s}-USDT-SWAP"
    return s.upper()


def get_base_symbol(symbol: str) -> str:
    return normalize_symbol(symbol).split("-")[0]


def get_available_symbols(data_root: Optional[str] = None) -> List[str]:
    """Danh sách perp có trong catalog (thư mục bar). Rỗng nếu chưa build catalog."""
    root = os.path.join(data_root or NORA_DATA_ROOT, "market", "okx", "catalog", "data", "bar")
    if not os.path.isdir(root):
        return []
    return sorted({d.split(".")[0] for d in os.listdir(root) if d.endswith("-1-MINUTE-LAST-EXTERNAL")})


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


# ─── Đọc catalog (nến 1m thật) ───────────────────────────────────────────────
def _bar_dir(symbol: str) -> str:
    return os.path.join(get_catalog_root(), "data", "bar", f"{normalize_symbol(symbol)}.OKX-1-MINUTE-LAST-EXTERNAL")


def _decode_fixed(col: pa.ChunkedArray) -> np.ndarray:
    """Cột số cố định 128-bit của Nautilus (little-endian, FIXED_SCALAR) -> float64."""
    arr = col.combine_chunks()
    buf = np.frombuffer(arr.buffers()[1], dtype=np.uint64)[2 * arr.offset: 2 * (arr.offset + len(arr))]
    return (buf[0::2].astype(np.float64) + buf[1::2].view(np.int64).astype(np.float64) * 2.0 ** 64) / FIXED_SCALAR


def read_catalog_1m(symbol: str, start_ms: int, end_ms: int) -> Dict[str, np.ndarray]:
    """Nến 1m THẬT của catalog có open_time trong [start_ms, end_ms] -> {"t" (open_time ms), "o","h","l","c","v"}. Thiếu -> CatalogError."""
    norm = normalize_symbol(symbol)
    d = _bar_dir(norm)
    files = sorted(glob.glob(os.path.join(d, "*.parquet")))
    if not files:
        raise CatalogError(f"{norm}: catalog chưa có nến 1m ({d}) — chạy test/scripts/build_catalog.py")
    lo_ns, hi_ns = (int(start_ms) + MINUTE_MS) * 1_000_000, (int(end_ms) + MINUTE_MS) * 1_000_000   # ts_event = open + 1m
    tables = [pq.read_table(f, filters=[("ts_event", ">=", lo_ns), ("ts_event", "<=", hi_ns)]) for f in files]
    table = pa.concat_tables(tables) if len(tables) > 1 else tables[0]
    out = {"t": (table.column("ts_event").to_numpy() // 1_000_000 - MINUTE_MS).astype(np.int64),
           "o": _decode_fixed(table.column("open")), "h": _decode_fixed(table.column("high")), "l": _decode_fixed(table.column("low")),
           "c": _decode_fixed(table.column("close")), "v": _decode_fixed(table.column("volume"))}
    if len(out["t"]) > 1 and bool((np.diff(out["t"]) <= 0).any()):
        order = np.argsort(out["t"], kind="stable")
        out = {k: v[order] for k, v in out.items()}
    _check_decoding(norm, out)
    return out


def _check_decoding(norm: str, got: Dict[str, np.ndarray]) -> None:
    """Một lần mỗi (tiến trình, symbol): giải mã numpy phải trùng ParquetDataCatalog.bars trên 3 nến đầu."""
    if _DECODE_CHECKED.get(norm) or len(got["t"]) == 0:
        return
    t0 = int(got["t"][0])
    bars = ParquetDataCatalog(get_catalog_root()).bars(
        bar_types=[str(get_bar_type(norm))], start=pd.Timestamp((t0 + MINUTE_MS) * 1_000_000, tz="UTC"),
        end=pd.Timestamp((t0 + 3 * MINUTE_MS) * 1_000_000, tz="UTC"))
    for i, b in enumerate(bars[:3]):
        for name, col in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c")):
            if abs(getattr(b, name).as_double() - got[col][i]) > 1e-6 * max(1.0, abs(got[col][i])):
                raise CatalogError(f"{norm}: giải mã catalog sai ({name}[{i}] {getattr(b, name)} != {got[col][i]})")
    _DECODE_CHECKED[norm] = True


def aggregate_frame(arr: Dict[str, np.ndarray], frame: str) -> Dict[str, np.ndarray]:
    """MỘT hàm gộp nến 1m thật -> nến khung `frame` căn open_time (t = open của khung): open = đầu, high = max, low = min, close = cuối,
    volume = tổng. Chỉ nến có thật được gộp (phút thiếu bỏ qua, không bù). 1m: trả nguyên."""
    step = frame_ms(frame)
    if step == MINUTE_MS or len(arr["t"]) == 0:
        return arr
    key = arr["t"] // step * step
    first = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    return {"t": key[first], "o": arr["o"][first], "h": np.maximum.reduceat(arr["h"], first), "l": np.minimum.reduceat(arr["l"], first),
            "c": arr["c"][np.r_[first[1:] - 1, len(key) - 1]], "v": np.add.reduceat(arr["v"], first)}


def _cache():
    global _BARS_CACHE
    if _BARS_CACHE is None:
        from backend.crawl.store import ByteLRU, env_mb
        _BARS_CACHE = ByteLRU(env_mb("NORA_BARS_CACHE_MB", 1500))
    return _BARS_CACHE


def exec_arrays(symbol: str, frame: str, start_ms: int, end_ms: int) -> Dict[str, np.ndarray]:
    """Nến thực thi (khung `frame`) của catalog trong [start_ms, end_ms] theo open_time; cache theo (symbol, frame, cửa sổ) trong tiến trình."""
    key = (normalize_symbol(symbol), frame, int(start_ms), int(end_ms))
    cache = _cache()
    hit = cache.get(key)
    if hit is not None:
        return hit
    out = aggregate_frame(read_catalog_1m(symbol, int(start_ms), int(end_ms)), frame)
    cache.put(key, out, sum(a.nbytes for a in out.values()))
    return out


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


def bars_frame(symbol: str, frame: str = "1h", start_ts: Optional[int] = None, end_ts: Optional[int] = None) -> pd.DataFrame:
    """Nến khung `frame` (open_time ms, open..volume) từ catalog cho biểu đồ UI — cùng hàm gộp với engine."""
    arr = exec_arrays(symbol, frame, 0 if start_ts is None else start_ts, 2 ** 62 if end_ts is None else end_ts)
    return pd.DataFrame({"open_time": arr["t"], "open": arr["o"], "high": arr["h"], "low": arr["l"], "close": arr["c"], "volume": arr["v"]})


def catalog_digest(symbols: List[str]) -> str:
    """Dấu vân tay nhanh của catalog các symbol (tên file parquet + kích thước + mtime) — khoá cache kết quả."""
    import hashlib
    h = hashlib.sha256()
    for s in sorted(normalize_symbol(x) for x in symbols):
        for f in sorted(glob.glob(os.path.join(_bar_dir(s), "*.parquet"))):
            st = os.stat(f)
            h.update(f"{os.path.basename(f)}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()[:16]


# ─── Ghi catalog (dùng bởi crawl/test script build_catalog) ──────────────────
def df_1m_to_nautilus_bars(symbol: str, df: pd.DataFrame) -> List[Bar]:
    """DataFrame 1m (open_time ms, OHLCV; chỉ nến thật is_filled==0) -> Bar Nautilus (ts_event = đóng) bằng BarDataWrangler."""
    if df.empty:
        return []
    if "is_filled" in df.columns:
        df = df[df["is_filled"] == 0]
    if df.empty:
        return []
    vol = df["volume"].to_numpy(dtype=float)
    if df.attrs.get("nora", {}).get("volume_unit") == "quote_usdt" or df.attrs.get("volume_unit") == "quote_usdt":
        vol = vol / df["close"].to_numpy(dtype=float)
    arr = {"t": df["open_time"].to_numpy(dtype=np.int64), "o": df["open"].to_numpy(dtype=float), "h": df["high"].to_numpy(dtype=float),
           "l": df["low"].to_numpy(dtype=float), "c": df["close"].to_numpy(dtype=float), "v": vol}
    return bars_from_arrays(symbol, arr, "1m", get_instrument(symbol))


def write_catalog_bars(symbol: str, df_1m: pd.DataFrame, catalog_path: Optional[str] = None) -> int:
    """Ghi nến 1m vào ParquetDataCatalog + manifest."""
    cat_path = catalog_path or get_catalog_root()
    catalog = ParquetDataCatalog(cat_path)
    catalog.write_data([get_instrument(symbol)])
    bars = df_1m_to_nautilus_bars(symbol, df_1m)
    if not bars:
        return 0
    catalog.write_data(bars)
    manifest_dir = os.path.join(cat_path, "_manifest")
    os.makedirs(manifest_dir, exist_ok=True)
    with open(os.path.join(manifest_dir, f"{get_base_symbol(symbol)}.json"), "w", encoding="utf-8") as f:
        json.dump({"symbol": normalize_symbol(symbol), "base_symbol": get_base_symbol(symbol), "updated_at": int(time.time()), "rows_1m": len(bars),
                   "start_ts_ns": bars[0].ts_event, "end_ts_ns": bars[-1].ts_event, "volume_unit": "base_coin"}, f, indent=2)
    return len(bars)
