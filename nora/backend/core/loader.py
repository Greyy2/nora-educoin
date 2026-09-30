"""Dữ liệu Nến và Data Loader tốc độ cao.

Cung cấp cơ chế nạp nến (Candle Loader) sử dụng bộ đệm (Memory Caching)
để tái sử dụng dữ liệu nến giữa các lần chạy (Backtest / Optimize),
giảm tải cho MongoDB và tăng tốc Backtest lên hàng chục lần.
"""
import os
from typing import Dict, List, Optional

import pandas as pd
from backend.db.local_pkl import (
    default_data_root,
    fetch_candles_df as fetch_local_candles_df,
    has_frame as has_local_frame,
)
from backend.db.mongo import fetch_candles_df as fetch_mongo_candles_df

# Cache lưu trữ nến đã tải: (symbol, frame) -> DataFrame
_CANDLE_CACHE: Dict[str, pd.DataFrame] = {}


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
        self._cache_key_prefix = f"{self.data_source}_{self.local_data_root}_{db_name}_{symbol}_{frame}"

    def load_data(
        self,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        columns: Optional[List[str]] = None,
        force_reload: bool = False,
    ) -> pd.DataFrame:
        """Nạp dữ liệu nến dạng DataFrame.
        
        Nếu use_cache=True, sẽ nạp toàn bộ một lần vào RAM (hoặc dùng bản đã có).
        Sau đó dùng Pandas indexing để cắt đoạn start_ts -> end_ts siêu nhanh.
        """
        cache_columns = "*" if columns is None else ",".join(sorted(columns))
        cache_key = f"{self._cache_key_prefix}_{start_ts}_{end_ts}_{cache_columns}"
        # Nếu dùng cache, thử lấy từ _CANDLE_CACHE
        if self.use_cache and not force_reload:
            if cache_key in _CANDLE_CACHE:
                df = _CANDLE_CACHE[cache_key]
                return self._slice_data(df, start_ts, end_ts, columns)

        # Giới hạn an toàn (Safe Limits): KHÔNG BAO GIỜ nạp toàn bộ DB vào RAM
        # Chỉ nạp trong khoảng thời gian start_ts -> end_ts + một chút buffer (nếu cần)
        # Hoặc dùng mặc định nếu dùng cache toàn cục nhưng vẫn phải có start/end
        load_start = start_ts
        load_end = end_ts
        
        # Ngăn chặn việc start/end bị bỏ trống gây treo server (Memory Bomb)
        if load_start is None or load_end is None:
            raise ValueError("CandleLoader require explicit start_ts and end_ts to prevent Memory Overload!")

        fetch_columns = None
        if not self.use_cache and columns is not None:
            fetch_columns = list(dict.fromkeys(["open_time", *columns]))
        df = self._fetch_candles(
            start_ts=load_start,
            end_ts=load_end,
            columns=fetch_columns,
        )

        if df.empty:
            return df

        # Indexing theo open_time để tìm kiếm nhanh
        if "open_time" in df.columns:
            df.set_index("open_time", drop=False, inplace=True)
            df.sort_index(inplace=True)

        if self.use_cache:
            _CANDLE_CACHE[cache_key] = df

        return self._slice_data(df, start_ts, end_ts, columns)

    def _fetch_candles(
        self,
        start_ts: int,
        end_ts: int,
        columns: Optional[List[str]],
    ) -> pd.DataFrame:
        if self.data_source == "local":
            return fetch_local_candles_df(
                symbol=self.symbol,
                frame=self.frame,
                start_ts=start_ts,
                end_ts=end_ts,
                columns=columns,
                data_root=self.local_data_root,
            )
        if self.data_source == "mongo":
            return fetch_mongo_candles_df(
                symbol=self.symbol,
                frame=self.frame,
                start_ts=start_ts,
                end_ts=end_ts,
                columns=columns,
                db_name=self.db_name,
            )

        # Nhánh "auto": ưu tiên local data. Nếu local rỗng hoặc thiếu, raise lỗi thay vì âm thầm chuyển sang Mongo
        if has_local_frame(self.symbol, self.frame, data_root=self.local_data_root):
            local_df = fetch_local_candles_df(
                symbol=self.symbol,
                frame=self.frame,
                start_ts=start_ts,
                end_ts=end_ts,
                columns=columns,
                data_root=self.local_data_root,
            )
            if not local_df.empty:
                return local_df
            raise FileNotFoundError(
                f"Local data cho {self.symbol} ({self.frame}) rỗng trong khoảng thời gian yêu cầu. "
                "Hệ thống không âm thầm fallback sang Mongo (đặt NORA_DATA_SOURCE=mongo nếu thực sự muốn đọc Mongo)."
            )

        raise FileNotFoundError(
            f"Không tìm thấy file nến local {self.frame}.pkl cho {self.symbol} tại {self.local_data_root}. "
            "Hệ thống không âm thầm fallback sang Mongo (đặt NORA_DATA_SOURCE=mongo nếu thực sự muốn đọc Mongo)."
        )

    def _slice_data(
        self,
        df: pd.DataFrame,
        start_ts: Optional[int],
        end_ts: Optional[int],
        columns: Optional[List[str]],
    ) -> pd.DataFrame:
        """Cắt nhanh tập dữ liệu DataFrame bằng thời gian."""
        if df.empty:
            return df

        sliced = df
        if start_ts is not None and end_ts is not None:
            # Dùng .loc cắt rất nhanh nếu index là open_time
            sliced = df.loc[start_ts:end_ts]
        elif start_ts is not None:
            sliced = df.loc[start_ts:]
        elif end_ts is not None:
            sliced = df.loc[:end_ts]

        if columns is not None:
            # Đảm bảo các cột yêu cầu có tồn tại
            cols_to_keep = [c for c in columns if c in sliced.columns]
            sliced = sliced[cols_to_keep]

        return sliced

    @staticmethod
    def clear_cache():
        """Xóa bộ đệm RAM (chạy khi cần giải phóng bộ nhớ)."""
        _CANDLE_CACHE.clear()
