"""Đường dẫn file của các lệnh chạy (entry point `python -m backend.<gói>.<lệnh>`) để test nạp lại module từ file."""
import os

COMMAND_DIRS = {
    "build_strategy_book": "optimize", "optimize_alphas": "optimize", "run_funnel": "optimize", "build_presets": "optimize",
    "build_alpha_registry": "optimize", "portfolio_sizing": "optimize", "robustness_check": "optimize",
    "validate_book": "wfa",
    "run_book_backtest": "core/backtest", "smoke_check": "core/backtest", "check_signals_strategies": "core/backtest",
    "bench_engine": "core/backtest",
    "make_mock_feeds": "core/analytics", "promote_staging": "core/data",
    "research_maker_scalp": "core/research", "research_topbots": "core/research", "research_trend_portfolio": "core/research",
}


def command_path(name: str) -> str:
    return os.path.join(os.path.dirname(__file__), "..", "backend", *COMMAND_DIRS[name].split("/"), f"{name}.py")
