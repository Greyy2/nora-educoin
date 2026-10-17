"""Kiểm tra hợp đồng giữa routes và runner.KINDS (P18 F1).
Mọi tham số mà routes gửi xuống job qua launch() phải nằm trong whitelist params của KINDS[kind].
"""
import pytest
from backend.jobs.runner import KINDS


def test_live_bot_contract():
    """Tất cả tham số live_bot gửi từ routes/live.py hoặc supervisor phải nằm trong KINDS['live_bot']['params']."""
    live_params = KINDS["live_bot"]["params"]
    # Các tham số routes/live.py có thể gửi
    route_keys = {
        "bot_id", "mode", "symbols", "capital", "base_frame",
        "confirm_live", "enter_on_start", "signal_tf", "code",
        "alpha_id", "params", "backtest_job_id"
    }
    missing = route_keys - live_params
    assert not missing, f"KINDS['live_bot']['params'] thiếu các tham số từ routes: {missing}"


def test_data_update_contract():
    params = KINDS["data_update"]["params"]
    route_keys = {"symbols"}
    assert route_keys.issubset(params)


def test_custom_backtest_contract():
    params = KINDS["custom_backtest"]["params"]
    # từ routes/alpha.py: code, symbols, start, end, train_ratio, initial_capital, position, run_frame
    route_keys = {"code", "symbols", "start", "end", "train_ratio", "initial_capital", "position", "run_frame"}
    assert route_keys.issubset(params)


def test_book_backtest_contract():
    params = KINDS["book_backtest"]["params"]
    # từ routes/process.py
    route_keys = {"book", "strategies", "symbols", "start", "end", "risk_per_trade", "stop_fill", "regime", "timeframe", "data"}
    assert route_keys.issubset(params)


def test_book_wfa_contract():
    params = KINDS["book_wfa"]["params"]
    route_keys = {"candidates", "strategies", "symbols", "start", "end", "train_days", "test_days", "step_days"}
    assert route_keys.issubset(params)


def test_all_kinds_have_valid_metadata():
    for kind, info in KINDS.items():
        assert "label_vi" in info, f"{kind} thiếu label_vi"
        assert "module" in info, f"{kind} thiếu module"
        assert "func" in info, f"{kind} thiếu func"
        assert "params" in info and isinstance(info["params"], set), f"{kind} params phải là set"
