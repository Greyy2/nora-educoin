"""Chuyển kiểu numpy/pandas/datetime sang kiểu JSON thuần — dùng làm `default=` của json.dump.

Lỗi gốc: `default=str` biến np.bool_ thành chuỗi 'False' (truthy!) và số numpy thành chuỗi.
"""
import datetime as _dt
import math

import numpy as np


def json_default(o):
    # Lưu ý: np.float64 là lớp con của float nên json xử lý trực tiếp (NaN vẫn ra "NaN"); default chỉ gọi cho kiểu json không biết.
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (_dt.datetime, _dt.date, _dt.time)) or hasattr(o, "isoformat"):  # gồm pd.Timestamp
        return o.isoformat()
    if isinstance(o, np.datetime64):
        return str(o)
    return str(o)
