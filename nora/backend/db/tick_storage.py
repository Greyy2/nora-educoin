"""Tick (swap on-chain) và nến local: <gốc>/dex/<SYM>/ticks.parquet cạnh nến của pool, khai báo trong manifest.json["ticks"]. Chỉ DEX có tick.

Tick là cửa sổ TRƯỢT ngắn (mặc định 3 ngày, tối đa 14): mỗi lần lưu cắt mọi tick cũ hơn cửa sổ.
Nến chỉ có một nguồn là 1m.pkl + core/data/resampler.py; tick KHÔNG sinh nến vào kho (ticks_to_1m chỉ để đối chiếu).
"""
import json
import os
import time
from typing import Any, Dict, List, Optional

import pandas as pd

TICK_COLUMNS = [
    "timestamp_ms",
    "block_number",
    "log_index",
    "tx_hash",       # khoá duy nhất của tick: "<tx>:<logIndex>"
    "price",         # USD / 1 token gốc: GIÁ KHỚP thực (đã gồm phí pool)
    "mid_price",     # USD / 1 token gốc: giá biên của pool SAU swap theo dự trữ (NaN nếu không có Sync)
    "amount",        # số lượng token gốc
    "volume_usd",
    "side",          # "buy" | "sell" — chiều của bên TAKER trên token gốc
    "reserve_base",  # dự trữ pool SAU swap (đơn vị token; NaN nếu không ghép được Sync)
    "reserve_quote",
    "quote_usd",     # USD / 1 token quote lúc swap
]
REQUIRED_TICK_COLUMNS = ["timestamp_ms", "price", "volume_usd", "amount", "side", "tx_hash"]
DEFAULT_TICK_DAYS = 3
MAX_TICK_DAYS = 14
DAY_MS = 86_400_000

PKL_COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]

STANDARD_MINUTE_FRAMES = [1, 5, 10, 15]
STANDARD_HOUR_FRAMES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]


from .data_layout import (  # noqa: E402
    clean_name,
    default_data_root,
    list_assets,
    resolve_asset_dir,
)


def symbol_dir(symbol: str, data_root: Optional[str] = None) -> str:
    """Thư mục tài sản ("BTC@perp", "dex:AERO", "AERO"). KHÔNG tạo thư mục (đường dẫn trả về có thể chưa tồn tại)."""
    root = data_root or default_data_root()
    return resolve_asset_dir(symbol, data_root=root) or os.path.join(root, "dex", clean_name(symbol))


def resolve_tick_file(symbol: str, data_root: Optional[str] = None) -> Optional[str]:
    path = os.path.join(symbol_dir(symbol, data_root), "ticks.parquet")
    return path if os.path.isfile(path) else None


def _write_json_atomic(path: str, obj: Dict[str, Any]) -> None:
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
    os.replace(path + ".tmp", path)


def save_ticks(
    df: pd.DataFrame,
    symbol: str,
    *,
    retention_days: int,
    source: str,
    extra_meta: Optional[Dict[str, Any]] = None,
    data_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Gộp `df` vào dex/<SYM>/ticks.parquet: bỏ trùng theo tx_hash (bản mới thắng), cắt tick cũ hơn retention_days, sắp theo thời gian,
    rồi ghi manifest["ticks"]. Tài sản (thư mục + manifest.json) phải có sẵn, tức là nến đã được crawl trước."""
    if not 1 <= int(retention_days) <= MAX_TICK_DAYS:
        raise ValueError(f"retention_days phải trong 1..{MAX_TICK_DAYS}, nhận {retention_days}")
    missing = [c for c in REQUIRED_TICK_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"tick thiếu cột {missing}")
    root = data_root or default_data_root()
    a_dir = os.path.join(root, "dex", clean_name(symbol))
    manifest_path = os.path.join(a_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(f"chưa có tài sản {a_dir} (thiếu manifest.json): crawl nến trước khi lưu tick")
    tick_path = os.path.join(a_dir, "ticks.parquet")

    parts = [pd.read_parquet(tick_path)] if os.path.isfile(tick_path) else []
    combined = pd.concat(parts + [df], ignore_index=True).drop_duplicates("tx_hash", keep="last")
    now_ms = int(time.time() * 1000)
    combined = combined[combined["timestamp_ms"] >= now_ms - int(retention_days) * DAY_MS]
    if combined.empty:
        raise ValueError("không còn tick nào trong cửa sổ lưu")
    order = [c for c in ("timestamp_ms", "block_number", "log_index") if c in combined.columns]
    combined = combined.sort_values(order, kind="stable").reset_index(drop=True)
    combined[[c for c in TICK_COLUMNS if c in combined.columns]].to_parquet(tick_path + ".tmp", engine="pyarrow", compression="snappy", index=False)
    os.replace(tick_path + ".tmp", tick_path)

    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    manifest["ticks"] = {
        "source": source,
        "synthetic": False,
        "start_ts": int(combined["timestamp_ms"].iloc[0]),
        "end_ts": int(combined["timestamp_ms"].iloc[-1]),
        "rows": int(len(combined)),
        "window_days": int(retention_days),
        "crawled_at": int(now_ms // 1000),
        **(extra_meta or {}),
    }
    _write_json_atomic(manifest_path, manifest)
    return {"symbol": symbol, "tick_path": tick_path, **{k: manifest["ticks"][k] for k in ("rows", "start_ts", "end_ts")}}


def tick_coverage(data_root: Optional[str] = None) -> List[Dict[str, Any]]:
    """Độ phủ tick của mọi tài sản DEX có ticks.parquet + manifest["ticks"] (đọc manifest, không đọc parquet)."""
    out = []
    for item in list_assets(data_root):
        if item["venue"] != "dex" or not os.path.isfile(os.path.join(item["path"], "ticks.parquet")):
            continue
        try:
            with open(os.path.join(item["path"], "manifest.json"), "r", encoding="utf-8") as fh:
                meta = json.load(fh).get("ticks")
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict):
            out.append({"symbol": item["symbol"], "venue": item["venue"], **{k: meta.get(k) for k in ("start_ts", "end_ts", "rows", "window_days", "source")}})
    return out


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

