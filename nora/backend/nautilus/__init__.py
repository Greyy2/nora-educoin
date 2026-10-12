"""NautilusTrader Core Engine & Runtime (P15 Native-First).

Trung tâm khớp lệnh, mô phỏng sự kiện và vận hành chiến lược định lượng cho Nora:
- `NativeNautilusRunner` (backend.nautilus.runner): Runner thực thi class `Strategy` bản địa
- `format_nautilus_results` (backend.nautilus.results): Chuẩn hóa kết quả sang contract Nora UI
- `PortfolioEngine` / `BacktestEngine` (backend.nautilus.engine): Điều phối backtest danh mục
- `catalog` (backend.nautilus.catalog): ParquetDataCatalog và nạp nến thực thi OKX
- `version`: Phiên bản NautilusTrader ghim định mức (1.231.0)
"""
from backend.nautilus.version import NAUTILUS_VERSION, check_for_updates, get_version_info
from backend.nautilus.runner import NativeNautilusRunner
from backend.nautilus.results import format_nautilus_results
from backend.nautilus.engine import BacktestEngine, PortfolioEngine
from backend.nautilus import catalog

__all__ = [
    "NAUTILUS_VERSION",
    "check_for_updates",
    "get_version_info",
    "NativeNautilusRunner",
    "format_nautilus_results",
    "BacktestEngine",
    "PortfolioEngine",
    "catalog",
]


