"""Dữ liệu Nến và Data Loader tốc độ cao.

Cung cấp cơ chế nạp nến (Candle Loader) sử dụng bộ đệm (Memory Caching)
để tái sử dụng dữ liệu nến giữa các lần chạy (Backtest / Optimize).

Thiết kế bộ đệm (v2 — fix OOM):
- Local pkl: cache CẢ FILE (toàn bộ lịch sử) một lần, không cache từng cửa sổ.
  Khoá: (data_source, data_root, symbol, frame, mtime_ns, size_bytes) -> file crawl lại thì tự hết hạn.
- Cửa sổ start_ts -> end_ts cắt bằng .loc trên index open_time đã sắp xếp (không sao chép).
  Kết quả là VIEW của bản trong cache: người gọi phải copy trước khi sửa (engine copy trong _prepare_candles).
- Tổng RAM giới hạn bằng ByteLRU (backend/utils/lru.py), NORA_CANDLE_CACHE_MB (mặc định 1024 MB).
- Chỉ giữ các cột engine cần (compat=False): không thêm cột symbol/timestamp/close_time/is_close.
- Mongo: KHÔNG cache, luôn nạp theo cửa sổ (không bao giờ kéo cả collection vào RAM).
"""
import os
from typing import List, Optional, Tuple

import pandas as pd
from backend.db.local_pkl import (
    default_data_root,
    fetch_candles_df as fetch_local_candles_df,
    has_frame as has_local_frame,
    resolve_symbol_dir,
)
from backend.db.mongo import fetch_candles_df as fetch_mongo_candles_df
from backend.utils.lru import ByteLRU, env_mb

_CANDLE_CACHE = ByteLRU(env_mb("NORA_CANDLE_CACHE_MB", 1024))


def _file_fingerprint(symbol: str, frame: str, data_root: Optional[str]) -> Optional[Tuple[int, int]]:
    """(mtime_ns, size_bytes) của file {frame}.pkl, hoặc None nếu không tìm thấy."""
    sym_dir = resolve_symbol_dir(symbol, data_root=data_root)
    if not sym_dir:
        return None
    try:
        st = os.stat(os.path.join(sym_dir, f"{frame}.pkl"))
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _index_by_open_time(df: pd.DataFrame) -> pd.DataFrame:
    """Index = open_time (không tên, không sao chép cột) để .loc cắt cửa sổ nhanh."""
    if df.empty or "open_time" not in df.columns:
        return df
    df.index = pd.Index(df["open_time"].to_numpy())
    if not df.index.is_monotonic_increasing:
        df = df.sort_index(kind="stable")
    return df


class CandleLoader:
    """Công cụ nạp và quản lý dữ liệu nến cho Backtest."""

    def __init__(
        self,
        symbol: str,
        frame: str = "4h",
        db_name: str = "backtest_data_1m_strategy810",
        use_cache: bool = True,
    ):
        self.symbol = symbol
        self.frame = frame
        self.db_name = db_name
        self.use_cache = use_cache
        self.data_source = os.environ.get("NORA_DATA_SOURCE", "auto").strip().lower()
        if self.data_source not in {"auto", "local", "mongo"}:
            self.data_source = "auto"
        self.local_data_root = default_data_root()

    def _cache_key(self) -> Optional[tuple]:
        fp = _file_fingerprint(self.symbol, self.frame, self.local_data_root)
        if fp is None:
            return None
        return (self.data_source, self.local_data_root, self.symbol, self.frame, *fp)

    def load_data(
        self,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        columns: Optional[List[str]] = None,
        force_reload: bool = False,
    ) -> pd.DataFrame:
        """Nạp nến trong [start_ts, end_ts] (gồm hai đầu)."""
        if start_ts is None or end_ts is None:
            raise ValueError("CandleLoader require explicit start_ts and end_ts to prevent Memory Overload!")

        if self.data_source == "mongo":
            fetch_columns = list(dict.fromkeys(["open_time", *columns])) if columns else None
            df = fetch_mongo_candles_df(symbol=self.symbol, frame=self.frame, start_ts=start_ts, end_ts=end_ts,
                                        columns=fetch_columns, db_name=self.db_name)
            return self._slice_data(_index_by_open_time(df), start_ts, end_ts, columns)

        key = self._cache_key() if self.use_cache else None
        if key is None:  # không cache: chỉ nạp đúng cửa sổ
            df = _index_by_open_time(self._fetch_local(start_ts, end_ts))
            return self._slice_data(df, start_ts, end_ts, columns)
        full_df = None if force_reload else _CANDLE_CACHE.get(key)
        if full_df is None:
            full_df = _index_by_open_time(self._fetch_local(None, None))
            if not full_df.empty:
                _CANDLE_CACHE.put(key, full_df, int(full_df.memory_usage(index=True, deep=True).sum()))
        return self._slice_data(full_df, start_ts, end_ts, columns)

    def _fetch_local(self, start_ts: Optional[int], end_ts: Optional[int]) -> pd.DataFrame:
        """Nến từ file local (đã sắp xếp; None/None = cả file), chỉ các cột engine cần.
        Không âm thầm chuyển sang Mongo."""
        if self.data_source == "auto" and not has_local_frame(self.symbol, self.frame, data_root=self.local_data_root):
            raise FileNotFoundError(
                f"Không tìm thấy file nến local {self.frame}.pkl cho {self.symbol} tại {self.local_data_root}. "
                "Hệ thống không âm thầm fallback sang Mongo (đặt NORA_DATA_SOURCE=mongo nếu thực sự muốn đọc Mongo)."
            )
        df = fetch_local_candles_df(symbol=self.symbol, frame=self.frame, start_ts=start_ts, end_ts=end_ts,
                                    data_root=self.local_data_root, compat=False)
        if df.empty and self.data_source == "auto":
            raise FileNotFoundError(
                f"Local data cho {self.symbol} ({self.frame}) rỗng. "
                "Hệ thống không âm thầm fallback sang Mongo (đặt NORA_DATA_SOURCE=mongo nếu thực sự muốn đọc Mongo)."
            )
        return df

    @staticmethod
    def _slice_data(df: pd.DataFrame, start_ts: Optional[int], end_ts: Optional[int],
                    columns: Optional[List[str]]) -> pd.DataFrame:
        if df.empty:
            return df
        sliced = df.loc[start_ts:end_ts]
        if columns is not None:
            sliced = sliced[[c for c in columns if c in sliced.columns]]
        return sliced

    @staticmethod
    def clear_cache() -> None:
        """Xóa toàn bộ bộ đệm RAM."""
        _CANDLE_CACHE.clear()
