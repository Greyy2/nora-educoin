"""Nora Core Execution Engine (Nautilus Trader Core).

Đúng 5 file vận hành và xử lý với Nautilus Trader:
- catalog.py:   ParquetDataCatalog, instruments, bar types.
- backtest.py:  make_engine, stream, NautilusRun, run_native.
- engine.py:    BacktestEngine, PortfolioEngine runner.
- strategy.py:  NoraSlotStrategy, NativeNautilusRunner.
- portfolio.py: Coordinator (execution risk, margin, balance, kill-switch).
"""
import json
import urllib.request
from typing import Any, Dict

try:
    import nautilus_trader
    NAUTILUS_VERSION = nautilus_trader.__version__
    NAUTILUS_AVAILABLE = True
except ImportError:
    NAUTILUS_VERSION = "not_installed"
    NAUTILUS_AVAILABLE = False

ENGINE_NAME = "nautilus_trader"


def get_version_info() -> Dict[str, Any]:
    return {
        "installed": NAUTILUS_AVAILABLE,
        "version": NAUTILUS_VERSION,
        "docs_url": "https://nautilustrader.io/docs/",
        "github_url": "https://github.com/nautechsystems/nautilus_trader",
        "pypi_url": "https://pypi.org/project/nautilus-trader/",
    }


def check_for_updates() -> Dict[str, Any]:
    info = get_version_info()
    if not NAUTILUS_AVAILABLE:
        return {**info, "has_update": True, "latest_version": "unknown", "message": "Chưa cài đặt nautilus-trader"}
    try:
        req = urllib.request.Request(
            "https://pypi.org/pypi/nautilus-trader/json",
            headers={"User-Agent": "Nora-Backtest-Updater/1.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            latest = data.get("info", {}).get("version", NAUTILUS_VERSION)
            has_update = latest != NAUTILUS_VERSION
            return {
                **info,
                "latest_version": latest,
                "has_update": has_update,
                "message": f"Đã có phiên bản mới: {latest}" if has_update else "Đang dùng phiên bản mới nhất."
            }
    except Exception as e:
        return {
            **info,
            "has_update": False,
            "latest_version": NAUTILUS_VERSION,
            "error": str(e),
            "message": "Không kết nối được PyPI để kiểm tra cập nhật."
        }


from backend.core import catalog
from backend.core.backtest import NautilusRun, make_engine, run_native, stream
from backend.core.engine import BacktestEngine, PortfolioEngine
from backend.core.portfolio import (
    Coordinator,
    EntryIntent,
    MasterPortfolioLedger,
    PortfolioAdmissionController,
    RiskPolicyConfig,
    SleeveState,
    get_master_portfolio_ledger,
    get_portfolio_admission_controller,
    get_live_master_ledger,
)
from backend.core.strategy import NoraSlotStrategy
from backend.core.strategy_proxima import (
    ProximaNativeStrategy,
    ProximaNativeStrategyConfig,
    RUNTIME_SAFETY_POLICY,
    EXPERIMENTAL_LOGIC_SCHEMA,
    calculate_contract_aware_sizing,
    evaluate_signal_variant_a,
    evaluate_signal_variant_b,
    resolve_exit_state_machine,
)
from backend.analys.metrics import stats
from backend.adapter import exchange as live
from backend.adapter import exchange as live_ledger

__all__ = [
    "NAUTILUS_VERSION",
    "NAUTILUS_AVAILABLE",
    "ENGINE_NAME",
    "get_version_info",
    "check_for_updates",
    "catalog",
    "make_engine",
    "stream",
    "NautilusRun",
    "run_native",
    "BacktestEngine",
    "PortfolioEngine",
    "Coordinator",
    "NoraSlotStrategy",
    "ProximaNativeStrategy",
    "ProximaNativeStrategyConfig",
    "RUNTIME_SAFETY_POLICY",
    "EXPERIMENTAL_LOGIC_SCHEMA",
    "calculate_contract_aware_sizing",
    "evaluate_signal_variant_a",
    "evaluate_signal_variant_b",
    "resolve_exit_state_machine",
    "MasterPortfolioLedger",
    "PortfolioAdmissionController",
    "RiskPolicyConfig",
    "SleeveState",
    "get_master_portfolio_ledger",
    "get_portfolio_admission_controller",
    "get_live_master_ledger",
]
