"""Tối ưu hoá alpha: sinh lưới tham số, xếp hạng, chạy; registry và xuất sổ chiến lược.

Import gói này đăng ký (LƯỜI) nguồn dữ liệu mặc định của engine — core không tự đọc đĩa. Nhà máy chỉ import backend.optimize.search.evaluate
(EngineData, make_engine_data) ở lần data_source() đầu tiên; import gói KHÔNG kéo numpy/pandas/crawl (process.py đặt env BLAS/cache sau __init__ này).
"""
from backend.core.models import set_default_data_factory as _set_factory


def _engine_data_factory():
    from backend.optimize.search.evaluate import make_engine_data
    return make_engine_data()


_set_factory(_engine_data_factory)
