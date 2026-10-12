"""NautilusTrader Core Engine & Runtime (P15 Native-First).

Trung tâm khớp lệnh, mô phỏng sự kiện và vận hành chiến lược định lượng cho Nora:
- `backtest` (backend.nautilus.backtest): LÕI chạy duy nhất — `make_engine`, `stream`, `NautilusRun` (DSL), `run_native` (Strategy bản địa)
- `results` (backend.nautilus.results): MỘT bộ chuyển kết quả sang contract Nora UI (đường DSL và bản địa)
- `PortfolioEngine` / `BacktestEngine` (backend.nautilus.engine): Điều phối backtest danh mục
- `catalog` (backend.nautilus.catalog): ParquetDataCatalog và nạp nến thực thi OKX
- `version`: Phiên bản NautilusTrader ghim định mức (1.231.0)
"""
from backend.nautilus.version import NAUTILUS_VERSION, check_for_updates, get_version_info
from backend.nautilus.backtest import NautilusRun, run_native
from backend.nautilus.engine import BacktestEngine, PortfolioEngine
from backend.nautilus import catalog

__all__ = [
    "NAUTILUS_VERSION",
    "check_for_updates",
    "get_version_info",
    "NautilusRun",
    "run_native",
    "BacktestEngine",
    "PortfolioEngine",
    "catalog",
]
