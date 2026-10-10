"""Helper dựng tài sản thử có metadata trong attrs (thay cho việc test tự ghi manifest.json / dex_pool.json).

write_asset      thư mục tài sản tối thiểu (1m.pkl + 24h.pkl nhỏ) với attrs["nora"] = meta
patch_meta       sửa attrs["nora"] của MỌI khung pkl của một tài sản (giá trị None = xoá khoá)
set_ticks_attrs  ghi lại attrs của ticks.parquet (ticks / onchain)
"""
import os
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from backend.crawl import store

_T0 = 1_700_000_000_000 // 60_000 * 60_000


def _tiny(n: int = 3, step_ms: int = 60_000) -> pd.DataFrame:
    t = [_T0 + i * step_ms for i in range(n)]
    return pd.DataFrame({"open_time": t, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0, "is_filled": 0})


def write_asset(root: str, venue: str, sym: str, instrument: Optional[str] = None, **meta: Any) -> str:
    """<root>/<venue>/<sym>[/<instrument>]/ với 1m.pkl + 24h.pkl (3 nến) mang attrs {"venue", "symbol", **meta}. Trả thư mục tài sản."""
    d = os.path.join(root, venue, sym, *([instrument] if instrument else []))
    os.makedirs(d, exist_ok=True)
    full = {"venue": venue, "symbol": f"{sym}@{instrument}" if instrument else sym, **meta}
    for frame, step in (("1m", 60_000), ("24h", 86_400_000)):
        store.write_pickle_atomic(store.stamp_attrs(_tiny(step_ms=step), full), os.path.join(d, f"{frame}.pkl"))
    return d


def patch_meta(asset_dir: str, **updates: Any) -> Dict[str, Any]:
    """Sửa attrs["nora"] của mọi <khung>.pkl trong asset_dir; None xoá khoá. Trả metadata mới. Xoá cache metadata để lần đọc sau thấy ngay."""
    new: Dict[str, Any] = {}
    for name in sorted(os.listdir(asset_dir)):
        if not name.endswith(".pkl") or name == "funding.pkl":
            continue
        path = os.path.join(asset_dir, name)
        df = pd.read_pickle(path)
        meta = dict(df.attrs.get(store.ATTR_KEY) or {})
        for k, v in updates.items():
            if v is None:
                meta.pop(k, None)
            else:
                meta[k] = v
        store.write_pickle_atomic(store.stamp_attrs(df, meta), path)
        new = meta
    store._META_CACHE.clear()
    return new


def set_ticks_attrs(asset_dir: str, ticks: Optional[dict] = None, onchain: Optional[dict] = None) -> None:
    """Ghi lại attrs["nora"] của ticks.parquet (giữ dữ liệu)."""
    path = os.path.join(asset_dir, "ticks.parquet")
    store.write_parquet_atomic(pd.read_parquet(path), path, {"ticks": ticks, "onchain": onchain})
    store._META_CACHE.clear()


# ── Nguồn dữ liệu GIẢ LẬP cho engine (P15-D) ─────────────────────────────────
# Engine chạy trên Nautilus: nến thực thi + spec hợp đồng lấy từ DataSource (core/models.DataSource). Nguồn mặc định (EngineData) đọc catalog Nautilus + instruments.json
# thật; test giả lập (tài sản AAA, BBB... ghi bằng save_resampled_dataset) dùng nguồn dưới đây: nến thực thi = chính nến 1m THẬT của kho pkl giả lập
# (is_filled == 0), spec hợp đồng khai báo TƯỜNG MINH ở SYNTH_SPEC (giá/khối lượng mịn để không làm tròn mất cấu trúc dữ liệu giả).
# Nautilus (bar_execution) giới hạn lượng khớp mỗi nến theo volume nến; volume của dữ liệu giả (10.0 / ngẫu nhiên) không phải thanh khoản thật nên nến thực thi
# được phục vụ với SYNTH_VOLUME (thị trường đủ sâu) — các test này kiểm logic vị thế/tín hiệu, không kiểm trượt khối lượng.
SYNTH_SPEC = {"tickSz": "0.00000001", "lotSz": "0.00001", "ctVal": "1", "minSz": "0.00001",
              "margin_init": 0.02, "margin_maint": 0.01, "maker_fee": 0.0002, "taker_fee": 0.0005}
SYNTH_VOLUME = 1e9


def synthetic_exec_arrays(df, frame, start, end):
    """Nến 1m giả lập (DataFrame có open_time, open..close; bỏ nến bù is_filled != 0) -> mảng thực thi khung `frame` (cùng hàm gộp catalog.aggregate_frame)."""
    from backend.nautilus import catalog as cat
    if "is_filled" in df.columns:
        df = df[df["is_filled"] == 0]
    t = df["open_time"].to_numpy(dtype="int64")
    keep = (t >= int(start)) & (t <= int(end))
    arr = {"t": t[keep], "o": df["open"].to_numpy(dtype=float)[keep], "h": df["high"].to_numpy(dtype=float)[keep], "l": df["low"].to_numpy(dtype=float)[keep],
           "c": df["close"].to_numpy(dtype=float)[keep], "v": np.full(int(keep.sum()), SYNTH_VOLUME)}
    return cat.aggregate_frame(arr, frame)


def _synthetic_class():
    from backend.optimize.search.evaluate import EngineData

    class Synthetic(EngineData):
        """EngineData với nến thực thi lấy từ candles() 1m của kho giả lập (pkl trong NORA_LOCAL_DATA_ROOT) + SYNTH_SPEC."""

        def exec_arrays(self, symbol, frame, start, end):
            return synthetic_exec_arrays(self.candles(symbol, "1m", int(start), int(end)), frame, start, end)

        def instrument_spec(self, symbol):
            return dict(SYNTH_SPEC)

    return Synthetic


def SyntheticData():
    """Nguồn dữ liệu giả lập dựa trên kho pkl (xem conftest.synthetic_data)."""
    return _synthetic_class()()


class FrameData:
    """Nguồn dữ liệu cho test truyền thẳng DataFrame 1m vào engine (BacktestEngine.df_base...): chỉ phục vụ phần thực thi + spec; engine không đọc gì khác từ đây."""

    def __init__(self, frames):
        from backend.nautilus import catalog as cat
        self.frames = {cat.normalize_symbol(k): v for k, v in frames.items()}

    def exec_arrays(self, symbol, frame, start, end):
        from backend.nautilus import catalog as cat
        return synthetic_exec_arrays(self.frames[cat.normalize_symbol(symbol)], frame, start, end)

    def instrument_spec(self, symbol):
        return dict(SYNTH_SPEC)
