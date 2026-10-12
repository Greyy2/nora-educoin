"""Backend của Nora: API FastAPI, adapter NautilusTrader, tín hiệu, WFA, Monte Carlo."""
from backend.models.models import set_default_data_factory as _set_factory


def _engine_data_factory():
    from backend.data.data import make_engine_data
    return make_engine_data()


_set_factory(_engine_data_factory)   # nguồn dữ liệu mặc định của tiến trình (lười: chỉ dựng ở lần data_source() đầu tiên)
