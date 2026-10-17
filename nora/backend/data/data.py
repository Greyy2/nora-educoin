"""Dùng dữ liệu thị trường cho backtest (chỉ ĐỌC): universe/symbol, manifest, nến từ ParquetDataCatalog (pyarrow, giải mã 128-bit
FIXED_SCALAR), gộp khung, nến cho tầng tín hiệu, giá ngày, cổng chất lượng (đọc verdict trong manifest) và EngineData.

KHÔNG tải mạng, KHÔNG ghi catalog (việc đó thuộc backend/data/ phần cập nhật catalog; phần đó import module này, không có chiều ngược lại).
Nguồn nến DUY NHẤT là catalog.
"""
from __future__ import annotations

import glob
import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from backend.analys.param import DEFAULT_CAPITAL, DEFAULT_TRAIN_RATIO, FRAME_MS
from backend.models.storage import NORA_DATA_ROOT, ByteLRU, env_mb, iso_date

logger = logging.getLogger("nora.data")

# ══════════════════════════════════════════════════════════════════════════
# 1. UNIVERSE VÀ KÝ HIỆU (SYMBOLS)
# ══════════════════════════════════════════════════════════════════════════

UNIVERSE: List[str] = [
    "BTC-USDT",
    "ETH-USDT",
    "SOL-USDT",
    "BNB-USDT",
    "XRP-USDT",
    "DOGE-USDT",
    "ADA-USDT",
    "AVAX-USDT",
    "LINK-USDT",
    "TRX-USDT",
]

UNIVERSE_BASES: List[str] = [s.split("-")[0] for s in UNIVERSE]

MINUTE_MS: int = 60_000
HOUR_MS: int = 3_600_000
DAY_MS: int = 86_400_000
FIXED_SCALAR: float = 10_000_000_000_000_000.0  # 10^16 FIXED_SCALAR của Nautilus (chỉ dùng pyarrow, không import thư viện Nautilus)

_PREFIX_RE = re.compile(r"^\s*(cex|dex)\s*[:/]\s*(.+)$", re.IGNORECASE)
_INSTRUMENT_RE = re.compile(r"^(.*?)\s*@\s*(perp)\s*$", re.IGNORECASE)


class CatalogError(RuntimeError):
    """Catalog thiếu / không đọc được dữ liệu cần thiết (không có đường dự phòng âm thầm)."""


def clean_name(name: str) -> str:
    """Loại bỏ ký tự lạ, đưa về chữ hoa."""
    return re.sub(r"[^A-Za-z0-9_]+", "", str(name or "").strip()).upper()


def split_instrument(symbol: str) -> Tuple[str, Optional[str]]:
    """'BTC@perp' -> ('BTC', 'perp'); 'BTC' -> ('BTC', None)."""
    match = _INSTRUMENT_RE.match(str(symbol or "").strip())
    return (match.group(1), match.group(2).lower()) if match else (str(symbol or "").strip(), None)


def parse_symbol(symbol: str) -> Tuple[Optional[str], str]:
    """'cex:btc' -> ('cex', 'BTC'); 'AERO' -> (None, 'AERO'). (Bỏ qua @perp)."""
    raw, _ = split_instrument(symbol)
    match = _PREFIX_RE.match(raw)
    if match:
        return match.group(1).lower(), clean_name(match.group(2))
    return None, clean_name(raw)


def base_name(symbol: str) -> str:
    """Tên gốc (không venue, không hậu tố @perp / -USDT-SWAP) của ký hiệu: 'BTC@perp' / 'BTC-USDT-SWAP' -> 'BTC'."""
    raw, _ = split_instrument(symbol)
    match = _PREFIX_RE.match(raw)
    return clean_name((match.group(2) if match else raw).split("-")[0])


def normalize_symbol(symbol: str) -> str:
    """'BTC', 'BTC@perp', 'cex:btc@perp', 'BTC-USDT-SWAP' -> 'BTC-USDT-SWAP'.
    Tài sản DEX (AMM) không được hỗ trợ trong catalog -> ValueError.
    """
    s = str(symbol or "").strip()
    if s.lower().startswith("dex:"):
        raise ValueError(f"{symbol}: tài sản DEX (AMM) không được Nautilus hỗ trợ")
    if "@" in s:
        s = s.split("@")[0]
    if ":" in s:
        s = s.split(":")[-1]
    s = s.strip().upper()
    if not s.endswith("-SWAP"):
        s = f"{s}-SWAP" if s.endswith("-USDT") else f"{s}-USDT-SWAP"
    return s


def data_symbol(symbol: str, market: str = "perp") -> Tuple[str, str]:
    """Ký hiệu dữ liệu thực dùng cho engine: 'BTC' -> ('BTC@perp', 'perp')."""
    base = base_name(symbol)
    return f"{base}@perp", "perp"


def require_perp(symbols: List[str], what: str = "pipeline") -> None:
    """Chỉ chấp nhận perp (CEX). Tài sản DEX từ chối rõ ràng."""
    bad = [s for s in symbols if str(s).lower().startswith("dex:")]
    if bad:
        raise ValueError(f"{what} chưa hỗ trợ tài sản DEX {bad}: chỉ perp (CEX).")


def classify_symbols(symbols: List[str], data_root: Optional[str] = None) -> Tuple[List[str], str]:
    """Ký hiệu người dùng -> danh sách ký hiệu perp kèm venue ('cex')."""
    require_perp(symbols, "classify_symbols")
    out = [s if "@" in s else f"{s}@perp" for s in symbols]
    return out, "cex"


def default_catalog_path(data_root: Optional[str] = None) -> str:
    """Thư mục ParquetDataCatalog OKX: data_root (gốc dữ liệu hoặc chính catalog) > NORA_CATALOG_PATH > catalog trong NORA_LOCAL_DATA_ROOT (chỉ khi đã có;
    gốc dữ liệu cục bộ của test) > <NORA_DATA_ROOT>/market/okx/catalog."""
    if data_root:
        return data_root if os.path.basename(data_root) == "catalog" else os.path.join(data_root, "market", "okx", "catalog")
    env = os.environ.get("NORA_CATALOG_PATH")
    if env:
        return env
    local = os.environ.get("NORA_LOCAL_DATA_ROOT")
    if local and os.path.isdir(os.path.join(local, "market", "okx", "catalog")):
        return os.path.join(local, "market", "okx", "catalog")
    return os.path.join(os.environ.get("NORA_DATA_ROOT", NORA_DATA_ROOT), "market", "okx", "catalog")


def default_universe() -> List[str]:
    """Rổ mặc định = các tài sản perp có nến trong catalog thuộc rổ cố định (UNIVERSE_BASES).
    Các coin quét trong universe_scan.json không tự động vào default_universe để bảo vệ backtest/studio mặc định.
    """
    bar_dir_all = os.path.join(default_catalog_path(), "data", "bar")
    if not os.path.isdir(bar_dir_all):
        return sorted(UNIVERSE_BASES)
    present = {d.split("-")[0].split(".")[0] for d in os.listdir(bar_dir_all) if "1-MINUTE" in d}
    res = [b for b in UNIVERSE_BASES if b in present]
    if not res and present:
        return sorted(present)
    return res if res else sorted(UNIVERSE_BASES)


def scan_universe(data_root: Optional[str] = None) -> List[str]:
    """Danh sách các coin quét (từ universe_scan.json); fallback về default_universe nếu chưa có file quét."""
    from backend.data.crawl import scan_universe_bases
    bases = scan_universe_bases(data_root)
    return bases if bases else default_universe()


def resolve_symbols(symbols: Optional[List[str]]) -> List[str]:
    """Danh sách tên cơ sở (BTC, ETH, ...) của rổ."""
    if symbols:
        return list(dict.fromkeys(base_name(s) for s in symbols))
    names = default_universe()
    if not names:
        raise ValueError("Kho dữ liệu chưa có tài sản perp nào")
    return names


def default_window() -> Tuple[str, str]:
    """(start, end) 'YYYY-MM-DD' = khoảng thời gian chung của cả rổ từ manifest."""
    firsts, lasts = [], []
    for n in default_universe():
        m = read_manifest(n)
        if m and m.get("start_ts") and m.get("end_ts"):
            firsts.append(int(m["start_ts"]))
            lasts.append(int(m["end_ts"]))
    if not firsts:
        # Mặc định an toàn nếu chưa có manifest
        return "2024-01-01", "2025-01-01"
    return iso_date(max(firsts) + DAY_MS), iso_date(min(lasts) - DAY_MS)


def run_defaults() -> Dict[str, object]:
    start, end = default_window()
    return {
        "symbols": [f"{n}@perp" for n in default_universe()],
        "start": start,
        "end": end,
        "train_ratio": DEFAULT_TRAIN_RATIO,
        "initial_capital": DEFAULT_CAPITAL,
    }


def check_data(data_symbols: List[str]) -> None:
    cat_path = default_catalog_path()
    missing = []
    for s in data_symbols:
        norm = normalize_symbol(s)
        d = os.path.join(cat_path, "data", "bar", f"{norm}.OKX-1-MINUTE-LAST-EXTERNAL")
        if not os.path.isdir(d) or not glob.glob(os.path.join(d, "*.parquet")):
            missing.append(s)
    if missing:
        have = default_universe()
        raise ValueError(f"Không có dữ liệu catalog OKX cho {missing}; tài sản có: {have}")


def data_info(data_symbols: List[str], start: int, end: int, source: str) -> Tuple[Dict[str, Any], List[str]]:
    warns: List[str] = []
    digests: Dict[str, str] = {}
    for s in data_symbols:
        base = base_name(s)
        m = read_manifest(base) or {}
        digests[s] = catalog_digest([s])
        if m.get("start_ts") and start < int(m["start_ts"]):
            warns.append(f"{s}: dữ liệu bắt đầu {iso_date(int(m['start_ts']))}, sau start {iso_date(start)} — giữ tiền mặt tới nến đầu có dữ liệu")
        if m.get("end_ts") and end - DAY_MS > int(m["end_ts"]):
            warns.append(f"{s}: dữ liệu kết thúc {iso_date(int(m['end_ts']))}, trước end {iso_date(end - DAY_MS)}")
    return {"source": source, "catalog_digest": digests}, warns


# ══════════════════════════════════════════════════════════════════════════
# 2. MANIFEST VÀ COVERAGE
# ══════════════════════════════════════════════════════════════════════════

def read_manifest(symbol: str, data_root: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Đọc manifest của tài sản từ catalog/_manifest/<BASE>.json."""
    cat_path = default_catalog_path(data_root)
    base = base_name(symbol)
    mpath = os.path.join(cat_path, "_manifest", f"{base}.json")
    if os.path.isfile(mpath):
        try:
            with open(mpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Chuẩn hoá start_ts / end_ts thành ms
            if "start_ts_ns" in data and "start_ts" not in data:
                data["start_ts"] = data["start_ts_ns"] // 1_000_000
            if "end_ts_ns" in data and "end_ts" not in data:
                data["end_ts"] = data["end_ts_ns"] // 1_000_000
            return data
        except Exception:
            pass
    # Nếu chưa có file manifest, tổng hợp nhanh từ parquet
    norm = normalize_symbol(symbol)
    bdir = os.path.join(cat_path, "data", "bar", f"{norm}.OKX-1-MINUTE-LAST-EXTERNAL")
    files = sorted(glob.glob(os.path.join(bdir, "*.parquet")))
    if not files:
        return None
    try:
        t_first = pq.read_table(files[0], columns=["ts_event"]).column("ts_event")[0].as_py()
        t_last = pq.read_table(files[-1], columns=["ts_event"]).column("ts_event")[-1].as_py()
        start_ms = t_first // 1_000_000 - MINUTE_MS
        end_ms = t_last // 1_000_000 - MINUTE_MS
        return {
            "symbol": norm,
            "base_symbol": base,
            "start_ts": int(start_ms),
            "end_ts": int(end_ms),
            "start_ts_ns": int(t_first),
            "end_ts_ns": int(t_last),
            "volume_unit": "base_coin",
        }
    except Exception:
        return None


def coverage(data_root: Optional[str] = None) -> List[Dict[str, Any]]:
    """Thay thế list_assets: trả danh sách tài sản perp có trong catalog và phạm vi ngày."""
    cat_path = default_catalog_path(data_root)
    bar_dir = os.path.join(cat_path, "data", "bar")
    if not os.path.isdir(bar_dir):
        return []
    res = []
    for d in sorted(os.listdir(bar_dir)):
        if not d.endswith("-1-MINUTE-LAST-EXTERNAL"):
            continue
        norm = d.replace(".OKX-1-MINUTE-LAST-EXTERNAL", "")
        base = norm.split("-")[0]
        m = read_manifest(base, data_root) or {}
        res.append({
            "symbol": f"{base}@perp",
            "base": base,
            "norm": norm,
            "venue": "cex",
            "instrument": "perp",
            "path": os.path.join(bar_dir, d),
            "start_ts": m.get("start_ts"),
            "end_ts": m.get("end_ts"),
            "rows_1m": m.get("rows_1m", 0),
        })
    return res


# ══════════════════════════════════════════════════════════════════════════
# 3. ĐỌC NẾN TỪ CATALOG (PYARROW / FIXED_SCALAR)
# ══════════════════════════════════════════════════════════════════════════

def bar_dir(symbol: str, data_root: Optional[str] = None) -> str:
    norm = normalize_symbol(symbol)
    return os.path.join(default_catalog_path(data_root), "data", "bar", f"{norm}.OKX-1-MINUTE-LAST-EXTERNAL")


def _decode_fixed(col: pa.ChunkedArray) -> np.ndarray:
    """Giải mã cột số cố định 128-bit FIXED_SCALAR (little-endian) của Nautilus thành float64."""
    arr = col.combine_chunks()
    buf = np.frombuffer(arr.buffers()[1], dtype=np.uint64)[2 * arr.offset : 2 * (arr.offset + len(arr))]
    return (buf[0::2].astype(np.float64) + buf[1::2].view(np.int64).astype(np.float64) * 2.0**64) / FIXED_SCALAR


def read_1m(symbol: str, start_ms: int = 0, end_ms: int = 2**62, data_root: Optional[str] = None) -> Dict[str, np.ndarray]:
    """Nến 1m từ catalog có open_time trong [start_ms, end_ms] -> {'t', 'o', 'h', 'l', 'c', 'v'}."""
    norm = normalize_symbol(symbol)
    d = bar_dir(norm, data_root)
    files = sorted(glob.glob(os.path.join(d, "*.parquet")))
    if not files:
        raise CatalogError(f"{norm}: catalog chưa có nến 1m ({d})")
    filters = []
    if start_ms > 0:
        lo_ns = (int(start_ms) + MINUTE_MS) * 1_000_000
        filters.append(("ts_event", ">=", lo_ns))
    if end_ms < 4_000_000_000_000:
        hi_ns = (int(end_ms) + MINUTE_MS) * 1_000_000
        filters.append(("ts_event", "<=", hi_ns))
    tables = [pq.read_table(f, filters=filters if filters else None) for f in files]
    tables = [t for t in tables if len(t) > 0]
    if not tables:
        return {
            "t": np.array([], dtype=np.int64),
            "o": np.array([], dtype=np.float64),
            "h": np.array([], dtype=np.float64),
            "l": np.array([], dtype=np.float64),
            "c": np.array([], dtype=np.float64),
            "v": np.array([], dtype=np.float64),
        }
    table = pa.concat_tables(tables) if len(tables) > 1 else tables[0]
    out = {
        "t": (table.column("ts_event").to_numpy() // 1_000_000 - MINUTE_MS).astype(np.int64),
        "o": _decode_fixed(table.column("open")),
        "h": _decode_fixed(table.column("high")),
        "l": _decode_fixed(table.column("low")),
        "c": _decode_fixed(table.column("close")),
        "v": _decode_fixed(table.column("volume")),
    }
    if len(out["t"]) > 1 and bool((np.diff(out["t"]) <= 0).any()):
        order = np.argsort(out["t"], kind="stable")
        out = {k: v[order] for k, v in out.items()}
    return out


def frame_ms(frame: str) -> int:
    """Mili-giây của một khung thời gian."""
    f = "24h" if frame == "1d" else frame
    try:
        return FRAME_MS[f]
    except KeyError:
        raise ValueError(f"Khung không hợp lệ: {frame!r}")


def aggregate_frame(arr: Dict[str, np.ndarray], frame: str) -> Dict[str, np.ndarray]:
    """Gộp nến 1m thật thành khung `frame` theo open_time (t = open của khung)."""
    step = frame_ms(frame)
    if step == MINUTE_MS or len(arr["t"]) == 0:
        return arr
    key = arr["t"] // step * step
    first = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    return {
        "t": key[first],
        "o": arr["o"][first],
        "h": np.maximum.reduceat(arr["h"], first),
        "l": np.minimum.reduceat(arr["l"], first),
        "c": arr["c"][np.r_[first[1:] - 1, len(key) - 1]],
        "v": np.add.reduceat(arr["v"], first),
    }


_EXEC_CACHE: Optional[ByteLRU] = None


def _get_exec_cache() -> ByteLRU:
    global _EXEC_CACHE
    if _EXEC_CACHE is None:
        _EXEC_CACHE = ByteLRU(env_mb("NORA_BARS_CACHE_MB", 1500))
    return _EXEC_CACHE


def exec_arrays(symbol: str, frame: str, start_ms: int = 0, end_ms: int = 2**62, data_root: Optional[str] = None) -> Dict[str, np.ndarray]:
    """Nến thực thi (khung `frame`) từ catalog có cache trong tiến trình."""
    norm = normalize_symbol(symbol)
    key = (norm, frame, int(start_ms), int(end_ms), data_root or "", catalog_digest([norm], data_root))
    cache = _get_exec_cache()
    hit = cache.get(key)
    if hit is not None:
        return hit
    raw_1m = read_1m(norm, int(start_ms), int(end_ms), data_root)
    out = aggregate_frame(raw_1m, frame)
    size = sum(a.nbytes for a in out.values())
    cache.put(key, out, size)
    return out


# ── Tái tạo DataFrame nến đầy đủ (tương thích tầng tín hiệu) ─────────────────

TIMEFRAME_MAP = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "24h": "24h",
    "1d": "24h",
}

CANDLE_COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]


def fill_missing_1m_candles(df_1m: pd.DataFrame) -> pd.DataFrame:
    """Điền khoảng trống 1m vector hoá: lưới thời gian liên tục từ min_t tới max_t, nến điền có is_filled=1, volume=0."""
    if df_1m.empty:
        df_empty = df_1m.copy()
        if "is_filled" not in df_empty.columns:
            df_empty["is_filled"] = 0
        return df_empty

    df = df_1m
    if "is_filled" in df.columns:
        mask_keep = (df["is_filled"].fillna(0).astype(int) != 1)
        if not mask_keep.all():
            df = df[mask_keep]

    if df.empty:
        result = df_1m.copy()
        if "is_filled" not in result.columns:
            result["is_filled"] = 0
        return result

    # Sắp xếp và loại bỏ trùng open_time (giữ cuối)
    df = df.sort_values("open_time").drop_duplicates("open_time", keep="last")

    t_arr = np.asarray(df["open_time"], dtype=np.int64)
    o_arr = np.asarray(df["open"], dtype=np.float64)
    h_arr = np.asarray(df["high"], dtype=np.float64)
    l_arr = np.asarray(df["low"], dtype=np.float64)
    c_arr = np.asarray(df["close"], dtype=np.float64)
    v_arr = np.asarray(df["volume"], dtype=np.float64)

    min_t = int(t_arr[0])
    max_t = int(t_arr[-1])
    n_bars = (max_t - min_t) // MINUTE_MS + 1

    if len(t_arr) == n_bars:
        return pd.DataFrame({
            "open_time": t_arr,
            "open": o_arr,
            "high": h_arr,
            "low": l_arr,
            "close": c_arr,
            "volume": v_arr,
            "is_filled": np.zeros(n_bars, dtype=int),
        })

    full_times = np.arange(min_t, max_t + MINUTE_MS, MINUTE_MS, dtype=np.int64)
    out_open = np.empty(n_bars, dtype=np.float64)
    out_high = np.empty(n_bars, dtype=np.float64)
    out_low = np.empty(n_bars, dtype=np.float64)
    out_close = np.empty(n_bars, dtype=np.float64)
    out_vol = np.zeros(n_bars, dtype=np.float64)
    out_filled = np.ones(n_bars, dtype=int)

    idx = ((t_arr - min_t) // MINUTE_MS).astype(np.intp)
    out_open[idx] = o_arr
    out_high[idx] = h_arr
    out_low[idx] = l_arr
    out_close[idx] = c_arr
    out_vol[idx] = v_arr
    out_filled[idx] = 0

    missing_mask = (out_filled == 1)
    if np.any(missing_mask):
        s_close = pd.Series(list(out_close), dtype=float)
        s_close.iloc[missing_mask] = np.nan
        out_close = s_close.ffill().bfill().to_numpy()
        out_open[missing_mask] = out_close[missing_mask]
        out_high[missing_mask] = out_close[missing_mask]
        out_low[missing_mask] = out_close[missing_mask]

    return pd.DataFrame({
        "open_time": full_times,
        "open": out_open,
        "high": out_high,
        "low": out_low,
        "close": out_close,
        "volume": out_vol,
        "is_filled": out_filled,
    })


def resample_from_1m(df_1m: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample từ nến 1m (đã điền) sang khung cao hơn: label='left', closed='left', origin='start_day'."""
    if df_1m.empty:
        return pd.DataFrame(columns=CANDLE_COLUMNS)

    rule = TIMEFRAME_MAP.get(timeframe)
    if rule is None:
        if timeframe.endswith("m"):
            rule = f"{timeframe[:-1]}min"
        elif timeframe.endswith("h"):
            rule = timeframe
        else:
            raise ValueError(f"Khung không hỗ trợ: {timeframe}")

    df = df_1m.copy().sort_values("open_time").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("dt")

    resampled = df.resample(rule, closed="left", label="left", origin="start_day").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open", "close"])

    scale = 10**6 if "ns" in str(resampled.index.dtype) else (10**3 if "us" in str(resampled.index.dtype) else 1)
    resampled["open_time"] = (resampled.index.astype("int64") // scale).astype(np.int64)
    return resampled[CANDLE_COLUMNS].reset_index(drop=True)


_CANDLES_CACHE: Optional[ByteLRU] = None


def _get_candles_cache() -> ByteLRU:
    global _CANDLES_CACHE
    if _CANDLES_CACHE is None:
        _CANDLES_CACHE = ByteLRU(env_mb("NORA_DATA_CACHE_MB", 1500))
    return _CANDLES_CACHE


def _frame_cache_path(symbol: str, frame: str, digest: str, data_root: Optional[str] = None) -> str:
    root = data_root or NORA_DATA_ROOT
    cdir = os.path.join(root, "cache", "frames")
    os.makedirs(cdir, exist_ok=True)
    sym_safe = normalize_symbol(symbol).replace("/", "_").replace("-", "_")
    return os.path.join(cdir, f"{sym_safe}_{frame}_{digest}.npz")


def load_candles(
    symbol: str,
    frame: str = "1m",
    start_ms: int = 0,
    end_ms: int = 2**62,
    columns: Optional[List[str]] = None,
    use_cache: bool = True,
    data_root: Optional[str] = None,
) -> pd.DataFrame:
    """Nạp nến dạng DataFrame cho tầng chiến lược / tín hiệu.
    Tái tạo chính xác cấu trúc dữ liệu nến:
    - 1m catalog -> fill_missing_1m_candles (có cột is_filled).
    - Khung > 1m -> resample_from_1m.
    - Cache trên đĩa (.npz mmap) và trong bộ nhớ bằng ByteLRU.
    """
    norm = normalize_symbol(symbol)
    digest = catalog_digest([norm], data_root)
    cache_key = (norm, frame, int(start_ms), int(end_ms), digest)

    cache = _get_candles_cache()
    df_res: Optional[pd.DataFrame] = None
    if use_cache:
        df_res = cache.get(cache_key)

    if df_res is None:
        npz_path = _frame_cache_path(norm, frame, digest, data_root)
        if os.path.isfile(npz_path):
            try:
                with np.load(npz_path, mmap_mode="r") as npz:
                    t = npz["open_time"]
                    i0 = int(np.searchsorted(t, start_ms, side="left"))
                    i1 = int(np.searchsorted(t, end_ms, side="right"))
                    data_dict: Dict[str, Any] = {
                        "open_time": np.array(t[i0:i1], copy=False),
                        "open": np.array(npz["open"][i0:i1], copy=False),
                        "high": np.array(npz["high"][i0:i1], copy=False),
                        "low": np.array(npz["low"][i0:i1], copy=False),
                        "close": np.array(npz["close"][i0:i1], copy=False),
                        "volume": np.array(npz["volume"][i0:i1], copy=False),
                    }
                    if "is_filled" in npz.files:
                        data_dict["is_filled"] = np.array(npz["is_filled"][i0:i1], copy=False)
                    df_res = pd.DataFrame(data_dict)
            except Exception as e:
                logger.warning("Lỗi đọc cache frame %s: %s, dựng lại", npz_path, e)
                df_res = None

        if df_res is None:
            # Dựng toàn bộ lịch sử nến từ catalog để lưu cache khung trên đĩa
            arr = read_1m(norm, 0, 2**62, data_root)
            if len(arr["t"]) == 0:
                cols = CANDLE_COLUMNS + (["is_filled"] if frame == "1m" else [])
                return pd.DataFrame(columns=columns or cols)

            df_raw = pd.DataFrame({
                "open_time": arr["t"],
                "open": arr["o"],
                "high": arr["h"],
                "low": arr["l"],
                "close": arr["c"],
                "volume": arr["v"],
                "is_filled": 0,
            })
            df_1m_filled = fill_missing_1m_candles(df_raw)
            if frame == "1m":
                df_full = df_1m_filled
            else:
                df_full = resample_from_1m(df_1m_filled, frame)

            try:
                tmp_path = f"{npz_path}.{os.getpid()}.tmp.npz"
                save_kwargs = {
                    "open_time": np.asarray(df_full["open_time"], dtype=np.int64),
                    "open": np.asarray(df_full["open"], dtype=np.float64),
                    "high": np.asarray(df_full["high"], dtype=np.float64),
                    "low": np.asarray(df_full["low"], dtype=np.float64),
                    "close": np.asarray(df_full["close"], dtype=np.float64),
                    "volume": np.asarray(df_full["volume"], dtype=np.float64),
                }
                if "is_filled" in df_full.columns:
                    save_kwargs["is_filled"] = np.asarray(df_full["is_filled"], dtype=np.int64)
                np.savez(tmp_path, **save_kwargs)
                actual_tmp = tmp_path if os.path.exists(tmp_path) else f"{tmp_path}.npz"
                os.replace(actual_tmp, npz_path)
            except Exception as e:
                logger.warning("Không thể ghi cache frame %s: %s", npz_path, e)

            df_res = df_full[(df_full["open_time"] >= start_ms) & (df_full["open_time"] <= end_ms)].reset_index(drop=True)

        if use_cache and df_res is not None:
            mem = df_res.memory_usage(deep=True).sum()
            cache.put(cache_key, df_res, mem)
    if df_res is None:
        df_res = pd.DataFrame(columns=columns or CANDLE_COLUMNS)
    if columns is not None:
        avail = [c for c in columns if c in df_res.columns]
        return df_res[avail]
    return df_res


def clear_caches() -> None:
    """Xoá cache nến/mảng thực thi trong bộ nhớ (sau khi catalog đổi)."""
    for c in (_CANDLES_CACHE, _EXEC_CACHE):
        if c is not None:
            c.clear()


def catalog_digest(symbols: List[str], data_root: Optional[str] = None) -> str:
    """Dấu vân tay nhanh của catalog các symbol: sha256 tên file parquet + kích thước + mtime."""
    h = hashlib.sha256()
    for s in sorted(normalize_symbol(x) for x in symbols):
        bdir = bar_dir(s, data_root)
        for f in sorted(glob.glob(os.path.join(bdir, "*.parquet"))):
            try:
                st = os.stat(f)
                h.update(f"{os.path.basename(f)}:{st.st_size}:{int(st.st_mtime)}".encode())
            except OSError:
                pass
    return h.hexdigest()[:16]


def daily_close(symbol: str, end: int) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """(nhãn đóng ngày ms, giá đóng cửa ngày) của tài sản tới `end`."""
    arr = exec_arrays(symbol, "1h", 0, end)
    if len(arr["t"]) == 0:
        return None
    t, c = arr["t"], arr["c"]
    day = t // DAY_MS * DAY_MS
    keep = np.r_[day[1:] != day[:-1], True]
    return day[keep] + DAY_MS, c[keep]


def load_prices(symbols: List[str], end: int) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """{tên tài sản: (nhãn ngày, giá đóng)} cho các tài sản đọc được."""
    out = {}
    for s in symbols:
        r = daily_close(s, end)
        if r is not None:
            out[base_name(s)] = r
    return out


def benchmark_daily_closes(symbol: str, start_ms: int, end_ms: int) -> pd.Series:
    """Series giá đóng cửa ngày indexed by DatetimeIndex UTC."""
    r = daily_close(symbol, end_ms)
    if r is None:
        return pd.Series(dtype=float)
    t, c = r
    mask = (t >= start_ms) & (t <= end_ms)
    idx = pd.to_datetime(list(t[mask]), unit="ms", utc=True)
    return pd.Series(c[mask], index=idx, name="close")


def strategy_frames(symbols: List[str], timeframe: str, end: int, start_ms: int = 0, drop_filled: bool = False) -> Dict[str, pd.DataFrame]:
    out = {}
    for s in symbols:
        df = load_candles(s, frame=timeframe, start_ms=start_ms, end_ms=end)
        if not df.empty:
            if drop_filled and "is_filled" in df.columns:
                df = df[df["is_filled"] == 0].reset_index(drop=True)
            out[base_name(s)] = df
    return out


# ══════════════════════════════════════════════════════════════════════════
# 4. CỔNG CHẤT LƯỢNG (CHỈ ĐỌC VERDICT TRONG MANIFEST)
# ══════════════════════════════════════════════════════════════════════════
# Verdict do evaluate_data_quality (module cập nhật catalog) tính lúc cập nhật catalog và ghi vào manifest (khoá "quality"). Ở đây KHÔNG tính lại.

class DataQualityError(RuntimeError):
    """Lỗi khi dữ liệu không vượt qua cổng kiểm định chất lượng."""


_BLOCKING = ("BLOCKED", "NEEDS_MORE_DATA")
_WARNED: set = set()


def quality_verdict(symbol: str, data_root: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Verdict chất lượng đã ghi trong manifest của tài sản; None nếu manifest chưa có."""
    m = read_manifest(symbol, data_root)
    q = (m or {}).get("quality")
    return dict(q) if isinstance(q, dict) else None


def require_data_ok(
    symbols: List[str],
    data_root: Optional[str] = None,
    logger_inst: Optional[logging.Logger] = None,
) -> Dict[str, Dict[str, Any]]:
    """Cổng dữ liệu bắt buộc trước khi chạy pipeline: đọc verdict trong manifest, BLOCKED/NEEDS_MORE_DATA/thiếu verdict -> DataQualityError."""
    log = logger_inst or logger
    out: Dict[str, Dict[str, Any]] = {}
    bad: List[str] = []
    for sym in dict.fromkeys(str(s) for s in (symbols or [])):
        dq = quality_verdict(sym, data_root)
        if dq is None:
            bad.append(f"  - {sym} [CHƯA_KIỂM_ĐỊNH]: manifest chưa có verdict chất lượng — chạy job data_update (hoặc refresh_quality)")
            continue
        out[sym] = dq
        status = dq.get("status")
        if status in _BLOCKING:
            bad.append(f"  - {sym} [{status}]: " + "; ".join(str(i) for i in dq.get("issues") or []))
        elif status == "WARNING":
            msg = f"[data-gate] {sym}: WARNING — " + "; ".join(str(i) for i in dq.get("issues") or [])
            if msg not in _WARNED:
                _WARNED.add(msg)
                log.warning(msg)
    if bad:
        raise DataQualityError("Dữ liệu không đạt kiểm định chất lượng (quality gate) — từ chối chạy:\n" + "\n".join(bad))
    return out


def require_data_ok_or_exit(symbols: List[str], data_root: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    try:
        return require_data_ok(symbols, data_root)
    except DataQualityError as exc:
        raise SystemExit(str(exc)) from None


# ══════════════════════════════════════════════════════════════════════════
# 5. DATASOURCE CHO ENGINE (EngineData)
# ══════════════════════════════════════════════════════════════════════════

class EngineData:
    """DataSource chuẩn của Nora trên nền Nautilus ParquetDataCatalog."""

    def __init__(self) -> None:
        self._memo: Optional[ByteLRU] = None

    def candles(
        self,
        symbol: str,
        frame: str,
        start: int,
        end: int,
        columns: Optional[List[str]] = None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        return load_candles(symbol, frame=frame, start_ms=start, end_ms=end, columns=columns, use_cache=use_cache)

    def exec_arrays(self, symbol: str, frame: str, start: int, end: int) -> Dict[str, np.ndarray]:
        return exec_arrays(symbol, frame, start, end)

    def instrument_spec(self, symbol: str) -> Dict[str, Any]:
        from backend.core.catalog import instrument_spec
        return instrument_spec(symbol)

    def require_ok(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        return require_data_ok(symbols)

    def manifest(self, symbol: str) -> Optional[Dict[str, Any]]:
        return read_manifest(symbol)

    def base_name(self, symbol: str) -> str:
        return base_name(symbol)

    def shared_plan(self, eng: Any) -> Optional[Dict[str, Any]]:
        try:
            from backend.jobs.runner.backtest import plan
            return plan(eng)
        except ImportError:
            return None

    def shared_load(self, out_dir: str, plan_dict: Dict[str, Any]) -> Any:
        try:
            from backend.jobs.runner.backtest import load
            return load(out_dir, plan_dict)
        except ImportError:
            return None

    def shared_fill(self, out_dir: str, pe: Any, eng: Any, plan_dict: Dict[str, Any]) -> Any:
        try:
            from backend.jobs.runner.backtest import fill
            return fill(out_dir, pe, eng, plan_dict)
        except ImportError:
            return None

    def release(self) -> None:
        clear_caches()

    @property
    def memo(self) -> ByteLRU:
        if self._memo is None:
            self._memo = ByteLRU(env_mb("NORA_DATA_CACHE_MB", 1500))
        return self._memo


ENGINE_DATA = EngineData()


def make_engine_data() -> EngineData:
    return ENGINE_DATA


