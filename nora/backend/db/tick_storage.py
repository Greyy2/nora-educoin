"""Tick and multi-timeframe candle storage layer.
Stores ticks into data/{SYMBOL}/ticks.parquet and automatically syncs all minute & hour .pkl frames.
"""
import os
import re
import time
from typing import List, Optional, Dict, Any
import pandas as pd
import numpy as np

TICK_COLUMNS = [
    "timestamp_ms",
    "price",
    "volume_usd",
    "amount",
    "side",
    "block_number",
    "tx_hash",
]

PKL_COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]

STANDARD_MINUTE_FRAMES = [1, 5, 10, 15]
STANDARD_HOUR_FRAMES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]


from .data_layout import (  # noqa: E402
    asset_dir_for_write,
    clean_name,
    default_data_root,
    resolve_asset_dir,
)


def symbol_dir(symbol: str, data_root: Optional[str] = None, create: bool = False, venue: str = "dex") -> str:
    """Thư mục tài sản. KHÔNG tạo thư mục khi chỉ đọc (trước đây tạo thư mục rỗng mỗi lần gọi).

    create=True chỉ dùng cho bộ ghi (vd. lưu tick DEX) -> <root>/<venue>/<SYM>.
    """
    root = data_root or default_data_root()
    found = resolve_asset_dir(symbol, data_root=root)
    if found:
        return found
    if create:
        return asset_dir_for_write(venue, symbol, data_root=root)
    return os.path.join(root, venue, clean_name(symbol))  # đường dẫn chưa tồn tại


def resolve_tick_file(symbol: str, data_root: Optional[str] = None) -> Optional[str]:
    s_dir = symbol_dir(symbol, data_root)
    path = os.path.join(s_dir, "ticks.parquet")
    if os.path.isfile(path):
        return path
    # Fallback to old flat location if exists
    flat_path = os.path.join(data_root or default_data_root(), "ticks", f"{symbol}.parquet")
    if os.path.isfile(flat_path):
        return flat_path
    return None


def save_ticks_and_sync_candles(
    df_new_ticks: pd.DataFrame,
    symbol: str,
    data_root: Optional[str] = None,
    sync_all_timeframes: bool = False,
) -> Dict[str, Any]:
    """
    1. Merge new ticks into data/{SYMBOL}/ticks.parquet (deduplicated).
    2. Ghi metadata ticks vào manifest.json.
    3. Cấm sync_all_timeframes vì nến chỉ được resample qua core/resampler.py.
    """
    if sync_all_timeframes:
        raise ValueError("sync_all_timeframes is deprecated and forbidden. Ticks must only be written to ticks.parquet, and candles are resampled strictly via resampler.py")

    s_dir = symbol_dir(symbol, data_root, create=True, venue="dex")
    tick_path = os.path.join(s_dir, "ticks.parquet")

    # 1. Merge with existing ticks if present
    if os.path.isfile(tick_path):
        try:
            df_old = pd.read_parquet(tick_path)
            combined = pd.concat([df_old, df_new_ticks], ignore_index=True)
        except Exception:
            combined = df_new_ticks.copy()
    else:
        combined = df_new_ticks.copy()

    # Deduplicate ticks by tx_hash if present, or timestamp_ms & price
    if "tx_hash" in combined.columns and combined["tx_hash"].nunique() > 1:
        valid_hash = combined["tx_hash"].str.len() > 5
        hashed = combined[valid_hash].drop_duplicates(subset=["tx_hash"])
        unhashed = combined[~valid_hash].drop_duplicates(subset=["timestamp_ms", "price"])
        combined = pd.concat([hashed, unhashed], ignore_index=True)
    else:
        combined = combined.drop_duplicates(subset=["timestamp_ms", "price", "amount"])

    # Retain strictly the last 90 days (3 months) of DEX data
    cutoff_ms = int(time.time() * 1000) - int(90 * 24 * 3600 * 1000)
    combined = combined[combined["timestamp_ms"] >= cutoff_ms]

    combined = combined.sort_values("timestamp_ms").reset_index(drop=True)
    
    # Save parquet
    cols = [c for c in TICK_COLUMNS if c in combined.columns]
    combined[cols].to_parquet(tick_path, engine="pyarrow", compression="snappy", index=False)

    # 2. Update manifest.json ticks metadata
    manifest_path = os.path.join(s_dir, "manifest.json")
    if os.path.isfile(manifest_path):
        try:
            import json
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            manifest["ticks"] = {
                "source": "geckoterminal_trades",
                "synthetic": False,
                "start_ts": int(combined["timestamp_ms"].min()) if not combined.empty else 0,
                "end_ts": int(combined["timestamp_ms"].max()) if not combined.empty else 0,
                "rows": len(combined),
            }
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
        except Exception:
            pass

    return {
        "symbol": symbol,
        "tick_path": tick_path,
        "total_ticks": len(combined),
        "updated_frames": [],
    }


def _merge_and_save_pkl(path: str, new_df: pd.DataFrame) -> None:
    """Merge new OHLCV candles with existing .pkl file without gaps."""
    if new_df.empty:
        return
    
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        try:
            old_df = pd.read_pickle(path)
            if all(c in old_df.columns for c in PKL_COLUMNS):
                merged = pd.concat([old_df, new_df], ignore_index=True)
                merged["open_time"] = merged["open_time"].astype("int64")
                # Trim data older than 90 days (3 months)
                cutoff_ms = int(time.time() * 1000) - int(90 * 24 * 3600 * 1000)
                merged = merged[merged["open_time"] >= cutoff_ms]
                # Keep latest update for the same open_time bucket
                merged = merged.drop_duplicates(subset=["open_time"], keep="last").sort_values("open_time").reset_index(drop=True)
                merged[PKL_COLUMNS].to_pickle(path)
                return
        except Exception:
            pass

    # Save fresh (also trimmed to 90 days)
    cutoff_ms = int(time.time() * 1000) - int(90 * 24 * 3600 * 1000)
    trimmed_new = new_df[new_df["open_time"] >= cutoff_ms].copy()
    trimmed_new[PKL_COLUMNS].to_pickle(path)


def aggregate_from_1m(df_1m: pd.DataFrame, bucket_ms: int) -> pd.DataFrame:
    """Aggregate 1m candles into higher timeframe buckets."""
    if df_1m.empty:
        return pd.DataFrame(columns=PKL_COLUMNS)
    
    df = df_1m.copy()
    df["_bucket"] = (df["open_time"] // bucket_ms) * bucket_ms
    grouped = (
        df.groupby("_bucket", as_index=False)
        .agg(
            open_time=("_bucket", "first"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
    )
    return grouped[PKL_COLUMNS].sort_values("open_time").reset_index(drop=True)


def load_ticks_df(
    symbol: str,
    start_ms: Optional[Any] = 0,
    end_ms: Optional[Any] = 0,
    data_root: Optional[str] = None,
) -> pd.DataFrame:
    # If 2nd arg is string, caller meant data_root
    if isinstance(start_ms, str) and data_root is None:
        data_root = start_ms
        start_ms = 0

    path = resolve_tick_file(symbol, data_root=data_root)
    if not path or not os.path.isfile(path):
        return pd.DataFrame(columns=TICK_COLUMNS)
    
    df = pd.read_parquet(path)
    if start_ms and isinstance(start_ms, (int, float)) and start_ms > 0:
        df = df[df["timestamp_ms"] >= start_ms]
    if end_ms and isinstance(end_ms, (int, float)) and end_ms > 0:
        df = df[df["timestamp_ms"] <= end_ms]
    return df.reset_index(drop=True)


def resample_ticks_to_bars(df_ticks: pd.DataFrame, bar_type: str = "time", param: Any = "1m") -> pd.DataFrame:
    """
    Resample tick stream into bars:
    - bar_type='time': 1m, 5m, 1h
    - bar_type='tick': N ticks per bar
    - bar_type='volume': V token volume per bar
    - bar_type='dollar': D USD volume per bar
    """
    if df_ticks.empty:
        return pd.DataFrame(columns=PKL_COLUMNS)

    df = df_ticks.sort_values("timestamp_ms").copy()

    if bar_type == "time":
        # 1m time bucket ms
        bucket_ms = 60 * 1000
        if isinstance(param, str) and param.endswith("m"):
            bucket_ms = int(param[:-1]) * 60 * 1000
        elif isinstance(param, str) and param.endswith("h"):
            bucket_ms = int(param[:-1]) * 3600 * 1000

        df["_bucket"] = (df["timestamp_ms"] // bucket_ms) * bucket_ms
        grouped = df.groupby("_bucket", as_index=False).agg(
            open_time=("_bucket", "first"),
            open=("price", "first"),
            high=("price", "max"),
            low=("price", "min"),
            close=("price", "last"),
            volume=("amount", "sum"),
        )
        return grouped[PKL_COLUMNS].sort_values("open_time").reset_index(drop=True)

    elif bar_type == "tick":
        n_ticks = int(param)
        df["group"] = np.arange(len(df)) // n_ticks
        bars = df.groupby("group").agg({
            "timestamp_ms": "first",
            "price": ["first", "max", "min", "last"],
            "amount": "sum",
        })
        bars.columns = ["open_time", "open", "high", "low", "close", "volume"]
        return bars.reset_index(drop=True)

    elif bar_type == "dollar":
        dollar_thresh = float(param)
        df["cum_usd"] = df["volume_usd"].cumsum()
        df["group"] = (df["cum_usd"] // dollar_thresh).astype(int)
        bars = df.groupby("group").agg({
            "timestamp_ms": "first",
            "price": ["first", "max", "min", "last"],
            "amount": "sum",
        })
        bars.columns = ["open_time", "open", "high", "low", "close", "volume"]
        return bars.reset_index(drop=True)

    elif bar_type == "volume":
        vol_thresh = float(param)
        df["cum_vol"] = df["amount"].cumsum()
        df["group"] = (df["cum_vol"] // vol_thresh).astype(int)
        bars = df.groupby("group").agg({
            "timestamp_ms": "first",
            "price": ["first", "max", "min", "last"],
            "amount": "sum",
        })
    return pd.DataFrame(columns=PKL_COLUMNS)


def load_candle_df(symbol: str, timeframe: str = "1h", data_root: Optional[str] = None) -> pd.DataFrame:
    """Load candle DataFrame from data/{SYMBOL}/{timeframe}.pkl or fallback to CSV."""
    s_dir = symbol_dir(symbol, data_root)
    # 1. Check pkl in symbol folder
    clean_tf = timeframe.lower().strip()
    pkl_file = os.path.join(s_dir, f"{clean_tf}.pkl")
    if os.path.isfile(pkl_file) and os.path.getsize(pkl_file) > 0:
        try:
            df = pd.read_pickle(pkl_file)
            if not df.empty and "close" in df.columns:
                return df
        except Exception:
            pass

    # Không tự dựng nến từ tick khi thiếu pkl: nến chỉ có một nguồn duy nhất là
    # 1m.pkl + core/resampler.py. Thiếu pkl -> trả rỗng để gate chặn rõ ràng.
    return pd.DataFrame(columns=PKL_COLUMNS)

