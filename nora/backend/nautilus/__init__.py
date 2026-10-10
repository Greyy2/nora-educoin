"""Lớp DUY NHẤT dùng NautilusTrader (P15): catalog dữ liệu, engine (PortfolioEngine / BacktestEngine), strategy, portfolio, live, version.

Import `backend.nautilus.engine` / `backend.nautilus.catalog` trực tiếp; gói này không nạp sẵn engine (nhẹ cho các route chỉ cần version)."""
from backend.nautilus.version import NAUTILUS_VERSION, check_for_updates, get_version_info

__all__ = ["NAUTILUS_VERSION", "check_for_updates", "get_version_info"]
