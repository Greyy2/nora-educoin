"""Local PKL data access for candle datasets."""
import os
import re
from typing import List, Optional

import pandas as pd

BASE_COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]
_COMPAT_COLUMNS = {"symbol", "timestamp", "close_time", "is_close"}


def default_data_root() -> str:
    return os.environ.get(
        "NORA_LOCAL_DATA_ROOT",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data")),
    )


def _frame_ms(frame: str) -> int:
    match = re.fullmatch(r"(\d+)([smhd])", frame.lower())
    if not match:
        return 0
    value = int(match.group(1))
    unit = match.group(2)
    factors = {
        "s": 1000,
        "m": 60 * 1000,
        "h": 60 * 60 * 1000,
        "d": 24 * 60 * 60 * 1000,
    }
    return value * factors[unit]


def _symbol_candidates(symbol: str) -> List[str]:
    raw = str(symbol or "").strip()
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "", raw)
    upper = cleaned.upper()
    candidates = [raw, cleaned, upper]
    for suffix in ("USDT", "USDC", "USD", "PERP"):
        if upper.endswith(suffix) and len(upper) > len(suffix):
            candidates.append(upper[: -len(suffix)])
    result: List[str] = []
    for item in candidates:
        if item and item not in result:
            result.append(item)
    return result


def resolve_symbol_dir(symbol: str, data_root: Optional[str] = None) -> Optional[str]:
    root = data_root or default_data_root()
    for candidate in _symbol_candidates(symbol):
        path = os.path.join(root, candidate)
        if os.path.isdir(path):
            return path
    return None


def has_frame(symbol: str, frame: str = "4h", data_root: Optional[str] = None) -> bool:
    """Kiểm tra sự tồn tại của file {frame}.pkl cục bộ."""
    s_dir = resolve_symbol_dir(symbol, data_root=data_root)
    if not s_dir:
        return False
    pkl_path = os.path.join(s_dir, f"{frame}.pkl")
    return os.path.isfile(pkl_path)


def has_ticks(symbol: str, data_root: Optional[str] = None) -> bool:
    """Kiểm tra sự tồn tại của tick thật. Trả về False nếu manifest đánh dấu synthetic=True."""
    s_dir = resolve_symbol_dir(symbol, data_root=data_root)
    if not s_dir:
        return False
    manifest_path = os.path.join(s_dir, "manifest.json")
    if os.path.isfile(manifest_path):
        try:
            import json
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
                if manifest.get("synthetic", False):
                    return False
        except Exception:
            pass
    tick_path = os.path.join(s_dir, "ticks.parquet")
    return os.path.isfile(tick_path)



def list_symbols(frame: str = "4h", data_root: Optional[str] = None) -> List[str]:
    root = data_root or default_data_root()
    if not os.path.isdir(root):
        return []
    symbols = []
    for name in os.listdir(root):
        symbol_dir = os.path.join(root, name)
        if os.path.isdir(symbol_dir) and os.path.isfile(os.path.join(symbol_dir, f"{frame}.pkl")):
            symbols.append(name)
    return sorted(symbols)


def fetch_candles_df(
    symbol: str,
    frame: str = "4h",
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    columns: Optional[List[str]] = None,
    db_name: str = "",
    limit: Optional[int] = None,
    data_root: Optional[str] = None,
) -> pd.DataFrame:
    symbol_dir = resolve_symbol_dir(symbol, data_root=data_root)
    if not symbol_dir:
        return pd.DataFrame()

    path = os.path.join(symbol_dir, f"{frame}.pkl")
    if not os.path.isfile(path):
        return pd.DataFrame()

    df = pd.read_pickle(path)
    if df.empty:
        return df
    if "open_time" not in df.columns:
        raise ValueError(f"Local PKL file missing open_time column: {path}")

    needed_columns = list(BASE_COLUMNS)
    if columns:
        for column in columns:
            if column in df.columns and column not in needed_columns:
                needed_columns.append(column)
    existing_columns = [column for column in needed_columns if column in df.columns]
    df = df.loc[:, existing_columns].copy()

    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
    df = df.dropna(subset=["open_time"])
    df["open_time"] = df["open_time"].astype("int64")
    df = df.sort_values("open_time").reset_index(drop=True)

    if start_ts is not None:
        df = df[df["open_time"] >= int(start_ts)]
    if end_ts is not None:
        df = df[df["open_time"] <= int(end_ts)]
    if limit:
        df = df.head(limit)

    requested = set(columns or [])
    needs_compat = not columns or bool(requested & _COMPAT_COLUMNS)
    if needs_compat:
        symbol_name = os.path.basename(symbol_dir)
        interval_ms = _frame_ms(frame)
        df["symbol"] = symbol_name
        df["timestamp"] = df["open_time"] // 1000
        df["close_time"] = df["open_time"] + interval_ms if interval_ms else df["open_time"]
        df["is_close"] = 1

    if columns is not None:
        keep = [column for column in columns if column in df.columns]
        df = df.loc[:, keep]

    return df.reset_index(drop=True)
