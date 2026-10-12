"""Strategy Optimization & Workflow Pipeline (P15 Native-First Architecture).

Tầng điều phối tối ưu hóa siêu tham số và quản lý tác vụ nền:
- `search/`: Thuật toán tìm kiếm Grid Search & Bayesian Optimization
- `funnel/`: Phễu sàng lọc Alpha 3 tầng (Screening -> Full Backtest -> Stress Test)
- `book/`: Sổ đăng ký chiến lược (Strategy Registry) và metadata
- `process/`: Task worker xử lý hàng đợi bất đồng bộ

LƯU Ý KIẾN TRÚC:
- Mọi tác vụ chạy thử nghiệm tham số đều gọi thẳng NautilusTrader BacktestEngine.
"""
from backend.models.models import set_default_data_factory as _set_factory



def _engine_data_factory():
    from backend.data.data import make_engine_data
    return make_engine_data()


_set_factory(_engine_data_factory)
