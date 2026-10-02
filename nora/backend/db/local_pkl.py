"""Local PKL data access for candle datasets."""
import os
import re
from typing import List, Optional

import numpy as np
import pandas as pd

BASE_COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]
_COMPAT_COLUMNS = {"symbol", "timestamp", "close_time", "is_close"}


from .data_layout import (  # noqa: E402  (một nơi duy nhất quyết định đường dẫn)
    list_assets,
    resolve_asset_dir,
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
    """Thư mục tài sản (cex/<SYM>, dex/<SYM>, hoặc phẳng kiểu cũ). Chấp nhận 'cex:BTC', 'BTCUSDT'."""
    from .data_layout import parse_symbol, split_instrument
    _, instrument = split_instrument(symbol)
    venue, _ = parse_symbol(symbol)
    if venue or instrument:  # ký hiệu có venue/instrument rõ ràng -> chỉ phân giải chính xác, không đoán
        return resolve_asset_dir(symbol, data_root=data_root)
    for candidate in _symbol_candidates(symbol):
        path = resolve_asset_dir(candidate, data_root=data_root)
        if path:
            return path
    return None


def has_frame(symbol: str, frame: str = "4h", data_root: Optional[str] = None) -> bool:
    """Kiểm tra sự tồn tại của file {frame}.pkl cục bộ."""
    s_dir = resolve_symbol_dir(symbol, data_root=data_root)
    if not s_dir:
        return False
    pkl_path = os.path.join(s_dir, f"{frame}.pkl")
    return os.path.isfile(pkl_path)


def read_manifest(symbol: str, data_root: Optional[str] = None) -> Optional[dict]:
    """Đọc manifest.json của asset; None nếu không có hoặc hỏng."""
    s_dir = resolve_symbol_dir(symbol, data_root=data_root)
    if not s_dir:
        return None
    path = os.path.join(s_dir, "manifest.json")
    if not os.path.isfile(path):
        return None
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def has_ticks(symbol: str, data_root: Optional[str] = None, min_days: float = 0.0) -> bool:
    """True chỉ khi có tick THẬT đã được khai báo trong manifest (fail-closed).

    Yêu cầu: manifest.json tồn tại, có khối manifest["ticks"] với synthetic=False,
    file ticks.parquet tồn tại và độ phủ thời gian của tick >= min_days.
    File ticks.parquet không có manifest khai báo -> KHÔNG được coi là tick thật.
    """
    s_dir = resolve_symbol_dir(symbol, data_root=data_root)
    if not s_dir or not os.path.isfile(os.path.join(s_dir, "ticks.parquet")):
        return False
    manifest = read_manifest(symbol, data_root=data_root)
    ticks_meta = manifest.get("ticks") if manifest else None
    if not isinstance(ticks_meta, dict) or ticks_meta.get("synthetic", True) is not False:
        return False
    if min_days > 0:
        start_ts = int(ticks_meta.get("start_ts") or 0)
        end_ts = int(ticks_meta.get("end_ts") or 0)
        if end_ts <= start_ts or (end_ts - start_ts) / 86_400_000 < min_days:
            return False
    return True


def list_asset_dirs(data_root: Optional[str] = None) -> List[str]:
    """Ký hiệu các tài sản đang có (có tiền tố venue nếu tên trùng giữa cex/dex)."""
    return sorted(item["qualified"] for item in list_assets(data_root))


def fetch_candles_df(
    symbol: str,
    frame: str = "4h",
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    columns: Optional[List[str]] = None,
    db_name: str = "",
    limit: Optional[int] = None,
    data_root: Optional[str] = None,
    compat: bool = True,
) -> pd.DataFrame:
    """Nạp nến từ file pkl cục bộ.

    Tối ưu bộ nhớ:
    - Chỉ dropna / sort khi thật sự cần (file do resampler ghi đã sạch và sắp xếp).
    - Cắt cửa sổ bằng iloc TRƯỚC khi .copy(): chỉ sao chép phần trong cửa sổ.
      (CandleLoader nạp cả file để cache, nên với engine bản sao này là cả file — một lần.)
    - compat=False (CandleLoader/engine): không thêm cột symbol/timestamp/close_time/is_close.
    """
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

    # Chuẩn hóa open_time (dropna chỉ khi thật sự có NaN — tránh một bản sao cả file)
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
    if df["open_time"].isna().any():
        df = df.dropna(subset=["open_time"])
    df["open_time"] = df["open_time"].astype("int64")

    # Sort chỉ khi chưa monotonic (pkl do resampler ghi luôn đã sắp xếp)
    if not df["open_time"].is_monotonic_increasing:
        df = df.sort_values("open_time", kind="stable").reset_index(drop=True)

    # Cắt cửa sổ [start_ts, end_ts] bằng vị trí (iloc) TRƯỚC khi .copy(): không sao chép phần ngoài cửa sổ
    open_times = df["open_time"].to_numpy()
    lo = int(np.searchsorted(open_times, int(start_ts), side="left")) if start_ts is not None else 0
    hi = int(np.searchsorted(open_times, int(end_ts), side="right")) if end_ts is not None else len(df)
    df = df.iloc[lo:hi]
    if limit:
        df = df.head(limit)

    # Luôn giữ is_filled nếu có: engine cần biết nến nào là nến điền
    needed_columns = list(BASE_COLUMNS) + (["is_filled"] if "is_filled" in df.columns else [])
    if columns:
        for column in columns:
            if column in df.columns and column not in needed_columns:
                needed_columns.append(column)
    existing_columns = [column for column in needed_columns if column in df.columns]
    # .copy() tại đây — sau khi đã cắt cửa sổ, chỉ sao chép phần cần dùng
    df = df.loc[:, existing_columns].copy()

    # Cột compat chỉ thêm khi cần thiết (caller yêu cầu hoặc không chỉ định columns)
    requested = set(columns or [])
    needs_compat = compat and (not columns or bool(requested & _COMPAT_COLUMNS))
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
