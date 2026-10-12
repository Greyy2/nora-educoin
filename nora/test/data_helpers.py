"""Helper dữ liệu cho test.

save_synthetic   ghi nến 1m GIẢ LẬP vào ParquetDataCatalog của gốc dữ liệu cục bộ (NORA_LOCAL_DATA_ROOT) + manifest + verdict chất lượng
SyntheticData    DataSource cho engine với tài sản giả lập (nến thực thi = nến 1m thật của catalog giả lập, spec tường minh)
FrameData        DataSource truyền thẳng DataFrame 1m vào engine
"""
import os
import shutil
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

_T0 = 1_700_000_000_000 // 60_000 * 60_000


def _tiny(n: int = 3, step_ms: int = 60_000) -> pd.DataFrame:
    t = [_T0 + i * step_ms for i in range(n)]
    return pd.DataFrame({"open_time": t, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0, "is_filled": 0})


# Catalog giả lập lưu giá/khối lượng ở độ chính xác 16 chữ số thập phân (FIXED_SCALAR của Nautilus) để đọc lại BIT-IDENTICAL với float64 đã ghi
# (golden / parity so sánh từng bit). Spec của ENGINE (SYNTH_SPEC bên dưới) giữ nguyên tickSz 1e-8 như trước.
_CATALOG_SPEC = {"tickSz": "0.0000000000000001", "lotSz": "0.0000000000000001", "ctVal": "1", "minSz": "0.0000000000000001",
                 "margin_init": 0.02, "margin_maint": 0.01, "maker_fee": 0.0002, "taker_fee": 0.0005}


def save_synthetic(symbol: str, output_dir: str, df_1m_raw: pd.DataFrame, pool_address: Any = None, data_root: Optional[str] = None,
                   **_ignored: Any) -> Dict[str, Any]:
    """Ghi nến 1m giả lập của MỘT tài sản vào catalog `<data_root hoặc NORA_LOCAL_DATA_ROOT>/market/okx/catalog` (thay mọi dữ liệu cũ của tài sản), kèm manifest và
    verdict chất lượng (đủ 30 ngày mới đạt, như dữ liệu thật). Tên tài sản = `symbol`, trừ khi symbol == "perp" (bố cục cũ <tài sản>/perp): lấy tên
    thư mục `output_dir`. Chỉ nhận nến thật (cột is_filled nếu có phải = 0). Các tham số khác của save_resampled_dataset cũ bị bỏ qua. Trả verdict."""
    from backend.data import crawl, data as D
    base = os.path.basename(os.path.normpath(output_dir)) if symbol == "perp" else symbol
    root = os.path.join(data_root or os.environ["NORA_LOCAL_DATA_ROOT"], "market", "okx", "catalog")
    os.makedirs(root, exist_ok=True)
    norm = D.normalize_symbol(base)
    shutil.rmtree(os.path.join(root, "data", "bar", f"{norm}.OKX-1-MINUTE-LAST-EXTERNAL"), ignore_errors=True)
    mpath = os.path.join(root, "_manifest", f"{D.base_name(base)}.json")
    if os.path.exists(mpath):
        os.remove(mpath)
    df = df_1m_raw
    if "is_filled" in df.columns:
        df = df[df["is_filled"] == 0]
    df = df[["open_time", "open", "high", "low", "close", "volume"]].drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    crawl.commit_candles(base, df, root, spec=_CATALOG_SPEC)
    D.clear_caches()
    return D.quality_verdict(base, root)


# ── Nguồn dữ liệu GIẢ LẬP cho engine (P15-D) ─────────────────────────────────
# Engine chạy trên Nautilus: nến thực thi + spec hợp đồng lấy từ DataSource (core/models.DataSource). Nguồn mặc định (EngineData) đọc catalog Nautilus + instruments.json
# thật; test giả lập (tài sản AAA, BBB... ghi bằng save_synthetic) dùng nguồn dưới đây: nến thực thi = chính nến 1m THẬT của catalog giả lập
# (is_filled == 0), spec hợp đồng khai báo TƯỜNG MINH ở SYNTH_SPEC (giá/khối lượng mịn để không làm tròn mất cấu trúc dữ liệu giả).
# Nautilus (bar_execution) giới hạn lượng khớp mỗi nến theo volume nến; volume của dữ liệu giả (10.0 / ngẫu nhiên) không phải thanh khoản thật nên nến thực thi
# được phục vụ với SYNTH_VOLUME (thị trường đủ sâu) — các test này kiểm logic vị thế/tín hiệu, không kiểm trượt khối lượng.
SYNTH_SPEC = {"tickSz": "0.00000001", "lotSz": "0.00001", "ctVal": "1", "minSz": "0.00001",
              "margin_init": 0.02, "margin_maint": 0.01, "maker_fee": 0.0002, "taker_fee": 0.0005}
SYNTH_VOLUME = 1e9


def synthetic_exec_arrays(df, frame, start, end):
    """Nến 1m giả lập (DataFrame có open_time, open..close; bỏ nến bù is_filled != 0) -> mảng thực thi khung `frame` (cùng hàm gộp catalog.aggregate_frame)."""
    from backend.data.data import aggregate_frame
    if "is_filled" in df.columns:
        df = df[df["is_filled"] == 0]
    t = df["open_time"].to_numpy(dtype="int64")
    keep = (t >= int(start)) & (t <= int(end))
    arr = {"t": t[keep], "o": df["open"].to_numpy(dtype=float)[keep], "h": df["high"].to_numpy(dtype=float)[keep], "l": df["low"].to_numpy(dtype=float)[keep],
           "c": df["close"].to_numpy(dtype=float)[keep], "v": np.full(int(keep.sum()), SYNTH_VOLUME)}
    return aggregate_frame(arr, frame)


def _synthetic_class():
    from backend.data.data import EngineData

    class Synthetic(EngineData):
        """EngineData với nến thực thi lấy từ candles() 1m của kho giả lập (catalog giả lập trong NORA_LOCAL_DATA_ROOT) + SYNTH_SPEC."""

        def exec_arrays(self, symbol, frame, start, end):
            return synthetic_exec_arrays(self.candles(symbol, "1m", int(start), int(end)), frame, start, end)

        def instrument_spec(self, symbol):
            return dict(SYNTH_SPEC)

    return Synthetic


def SyntheticData():
    """Nguồn dữ liệu giả lập dựa trên catalog giả lập (xem conftest.synthetic_data)."""
    return _synthetic_class()()


class FrameData:
    """Nguồn dữ liệu cho test truyền thẳng DataFrame 1m vào engine (BacktestEngine.df_base...): chỉ phục vụ phần thực thi + spec; engine không đọc gì khác từ đây."""

    def __init__(self, frames):
        from backend.data.data import normalize_symbol
        self.frames = {normalize_symbol(k): v for k, v in frames.items()}

    def exec_arrays(self, symbol, frame, start, end):
        from backend.data.data import normalize_symbol
        return synthetic_exec_arrays(self.frames[normalize_symbol(symbol)], frame, start, end)

    def instrument_spec(self, symbol):
        return dict(SYNTH_SPEC)
