"""Dữ liệu Nến và Data Loader tốc độ cao.

Cung cấp cơ chế nạp nến (Candle Loader) sử dụng bộ đệm (Memory Caching)
để tái sử dụng dữ liệu nến giữa các lần chạy (Backtest / Optimize),
giảm tải cho MongoDB và tăng tốc Backtest lên hàng chục lần.

Thiết kế bộ đệm (v2 — fix OOM):
- Cache CẢ FILE (toàn bộ lịch sử), không cache từng cửa sổ.
  Khoá: (data_source, data_root, db_name, symbol, frame, mtime_ns, size_bytes).
  Khi file được crawl lại, mtime_ns thay đổi → cache tự hết hạn (fix stale data).
- Cắt cửa sổ bằng searchsorted + iloc → O(log n), không sao chép bản mới.
- Giới hạn tổng RAM bằng _ByteLRU: loại LRU khi vượt ngân sách byte.
  Cấu hình qua biến môi trường NORA_CANDLE_CACHE_MB (mặc định 1024 MB).
"""
import os
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

import pandas as pd
from backend.db.local_pkl import (
    default_data_root,
    fetch_candles_df as fetch_local_candles_df,
    has_frame as has_local_frame,
    resolve_symbol_dir,
)
from backend.db.mongo import fetch_candles_df as fetch_mongo_candles_df

# ─── ByteLRU: bộ đệm giới hạn theo byte, không theo số lượng mục ────────────

class _ByteLRU:
    """LRU cache giới hạn theo tổng byte (ước tính bằng df.memory_usage(deep=True).sum()).

    Khi cache đầy: loại bỏ mục ít dùng nhất (LRU) cho đến khi đủ chỗ.
    Thread-safe ở mức GIL Python (đủ cho multiprocessing — mỗi tiến trình có cache riêng).
    """

    def __init__(self, budget_mb: float):
        self.budget: int = int(budget_mb * 1024 * 1024)
        self.used: int = 0
        self._d: "OrderedDict[str, Tuple[pd.DataFrame, int]]" = OrderedDict()

    def get(self, key: str) -> Optional[pd.DataFrame]:
        item = self._d.get(key)
        if item is None:
            return None
        self._d.move_to_end(key)
        return item[0]

    def put(self, key: str, df: pd.DataFrame) -> None:
        nbytes = int(df.memory_usage(deep=True).sum())
        if nbytes > self.budget:
            # DataFrame lớn hơn cả ngân sách: không cache để không bao giờ bị stuck
            return
        # Loại LRU cho đến khi đủ chỗ
        while self._d and self.used + nbytes > self.budget:
            _, (_, n) = self._d.popitem(last=False)
            self.used -= n
        if key in self._d:
            self.used -= self._d[key][1]
        self._d[key] = (df, nbytes)
        self.used += nbytes

    def evict(self, key: str) -> None:
        item = self._d.pop(key, None)
        if item is not None:
            self.used -= item[1]

    def clear(self) -> None:
        self._d.clear()
        self.used = 0

    def __len__(self) -> int:
        return len(self._d)


def _default_budget_mb() -> float:
    try:
        return float(os.environ.get("NORA_CANDLE_CACHE_MB", "1024"))
    except (TypeError, ValueError):
        return 1024.0


# Module-level LRU: khoá là chuỗi (data_source, data_root, db_name, symbol, frame, mtime_ns, size_bytes)
_CANDLE_CACHE: _ByteLRU = _ByteLRU(_default_budget_mb())

# Giữ alias dict-like cho cache_report() trong memwatch.py (đọc len())
# _CANDLE_CACHE đã có __len__ nên tương thích trực tiếp.


def _file_fingerprint(symbol: str, frame: str, data_root: Optional[str]) -> Optional[Tuple[int, int]]:
    """Trả (mtime_ns, size_bytes) của file {frame}.pkl, hoặc None nếu không tìm thấy."""
    sym_dir = resolve_symbol_dir(symbol, data_root=data_root)
    if not sym_dir:
        return None
    path = os.path.join(sym_dir, f"{frame}.pkl")
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


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

    def _cache_key(self) -> Optional[str]:
        """Khoá cache gồm fingerprint (mtime_ns, size_bytes) của file → tự hết hạn khi crawl lại."""
        if self.data_source == "mongo":
            # Mongo không có file local để lấy fingerprint → không cache theo file
            return None
        fp = _file_fingerprint(self.symbol, self.frame, self.local_data_root)
        if fp is None:
            return None
        mtime_ns, size_bytes = fp
        return f"{self.data_source}|{self.local_data_root}|{self.db_name}|{self.symbol}|{self.frame}|{mtime_ns}|{size_bytes}"

    def load_data(
        self,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        columns: Optional[List[str]] = None,
        force_reload: bool = False,
    ) -> pd.DataFrame:
        """Nạp dữ liệu nến dạng DataFrame.

        Nếu use_cache=True: cache TOÀN BỘ file vào LRU một lần (khoá theo mtime/size).
        Cắt cửa sổ start_ts→end_ts bằng searchsorted + iloc — không tạo bản sao mới.
        Mỗi file chỉ chiếm RAM một lần dù được gọi với nhiều cửa sổ khác nhau.
        """
        if start_ts is None or end_ts is None:
            raise ValueError(
                "CandleLoader require explicit start_ts and end_ts to prevent Memory Overload!"
            )

        # Thử lấy full DataFrame từ cache
        cache_key = self._cache_key() if self.use_cache and not force_reload else None
        full_df: Optional[pd.DataFrame] = None
        if cache_key is not None:
            full_df = _CANDLE_CACHE.get(cache_key)

        if full_df is None:
            # Nạp không giới hạn (toàn bộ file), rồi index để cắt nhanh
            full_df = self._fetch_full()
            if full_df.empty:
                return full_df
            # Indexing theo open_time để searchsorted hoạt động
            if "open_time" in full_df.columns and not full_df.index.equals(
                pd.RangeIndex(len(full_df))
            ):
                full_df = full_df.reset_index(drop=True)
            if "open_time" in full_df.columns:
                full_df = full_df.set_index("open_time", drop=False).sort_index()
            if cache_key is not None:
                _CANDLE_CACHE.put(cache_key, full_df)

        return self._slice_data(full_df, start_ts, end_ts, columns)

    def _fetch_full(self) -> pd.DataFrame:
        """Nạp toàn bộ lịch sử (không cắt) để cache 1 lần."""
        if self.data_source == "local":
            return fetch_local_candles_df(
                symbol=self.symbol,
                frame=self.frame,
                data_root=self.local_data_root,
            )
        if self.data_source == "mongo":
            return fetch_mongo_candles_df(
                symbol=self.symbol,
                frame=self.frame,
                db_name=self.db_name,
            )

        # Nhánh "auto": ưu tiên local, fail-fast nếu thiếu
        if has_local_frame(self.symbol, self.frame, data_root=self.local_data_root):
            local_df = fetch_local_candles_df(
                symbol=self.symbol,
                frame=self.frame,
                data_root=self.local_data_root,
            )
            if not local_df.empty:
                return local_df
            raise FileNotFoundError(
                f"Local data cho {self.symbol} ({self.frame}) rỗng. "
                "Hệ thống không âm thầm fallback sang Mongo "
                "(đặt NORA_DATA_SOURCE=mongo nếu thực sự muốn đọc Mongo)."
            )

        raise FileNotFoundError(
            f"Không tìm thấy file nến local {self.frame}.pkl cho {self.symbol} tại {self.local_data_root}. "
            "Hệ thống không âm thầm fallback sang Mongo "
            "(đặt NORA_DATA_SOURCE=mongo nếu thực sự muốn đọc Mongo)."
        )

    def _slice_data(
        self,
        df: pd.DataFrame,
        start_ts: Optional[int],
        end_ts: Optional[int],
        columns: Optional[List[str]],
    ) -> pd.DataFrame:
        """Cắt nhanh bằng .loc trên index open_time — không sao chép toàn bộ."""
        if df.empty:
            return df

        sliced = df
        if start_ts is not None and end_ts is not None:
            sliced = df.loc[start_ts:end_ts]
        elif start_ts is not None:
            sliced = df.loc[start_ts:]
        elif end_ts is not None:
            sliced = df.loc[:end_ts]

        if columns is not None:
            cols_to_keep = [c for c in columns if c in sliced.columns]
            sliced = sliced[cols_to_keep]

        return sliced

    @staticmethod
    def clear_cache() -> None:
        """Xóa toàn bộ bộ đệm RAM (gọi giữa các chiến lược ứng viên để giải phóng bộ nhớ)."""
        _CANDLE_CACHE.clear()
