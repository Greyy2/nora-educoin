"""Test bộ chuyển đổi và thực thi Native Nautilus Trader Strategy (P15 Native)."""
import os
import pytest

from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from backend.alpha.compile import compile_code, is_nautilus_native
from backend.nautilus.runner import NativeNautilusRunner
from backend.optimize.process.tasks import run_custom

NATIVE_CODE_SAMPLE = '''
from nautilus_trader.trading.strategy import Strategy, StrategyConfig
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model.enums import OrderSide

class MyNativeStrategy(Strategy):
    """Chiến lược Native Nautilus phục vụ unit test."""
    timeframe = "1h"
    symbols = ["BTC"]

    def __init__(self, config: StrategyConfig, instrument=None, bar_type=None):
        super().__init__(config)
        self.instrument = instrument
        self.bar_type = bar_type
        self.count = 0

    def on_start(self):
        self.subscribe_bars(self.bar_type)

    def on_bar(self, bar):
        self.count += 1
        if self.count == 5:
            qty = self.instrument.make_qty(0.01)
            order = self.order_factory.market(self.instrument.id, OrderSide.BUY, qty)
            self.submit_order(order)
        elif self.count == 15:
            qty = self.instrument.make_qty(0.01)
            order = self.order_factory.market(self.instrument.id, OrderSide.SELL, qty)
            self.submit_order(order)
'''

DSL_CODE_SAMPLE = '''
class SimpleAlgo(SimpleAlgorithm):
    timeframe = "1h"
    def __algorithm__(self):
        self.set_positions(self.data.pv_close > 0, position=1)
'''


def test_is_nautilus_native():
    assert is_nautilus_native(NATIVE_CODE_SAMPLE) is True
    assert is_nautilus_native(DSL_CODE_SAMPLE) is False


def test_compile_native_strategy():
    prog = compile_code(NATIVE_CODE_SAMPLE)
    assert getattr(prog, "is_native", False) is True
    assert prog.name == "MyNativeStrategy"
    assert prog.timeframe == "1h"
    assert prog.symbols == ["BTC"]
    assert len(prog.code_hash) == 12


def test_native_runner_execution():
    prog = compile_code(NATIVE_CODE_SAMPLE)
    start_ms = 1704067200000  # 2024-01-01
    end_ms = start_ms + 3600000 * 50

    runner = NativeNautilusRunner(
        strategy_class=prog.strategy_cls,
        symbols=prog.symbols,
        start_ms=start_ms,
        end_ms=end_ms,
        initial_capital=10_000.0,
        base_frame="1h",
    )
    res = runner.run()

    assert len(res["positions"]) >= 1
    p0 = res["positions"][0]
    assert p0.symbol == "BTC-USDT-SWAP"
    assert p0.qty == 0.01
    assert p0.enter_price > 0
    assert p0.close_price > 0
    assert len(res["orders"]) >= 2
    assert len(res["equity_curve"]) >= 2
    assert res["final_equity"] > 0


def test_run_custom_native_end_to_end(monkeypatch):
    monkeypatch.setenv("NORA_ALLOW_UNLIMITED", "1")
    monkeypatch.delenv("NORA_LOCAL_DATA_ROOT", raising=False)
    monkeypatch.setenv("NORA_DATA_ROOT", "/home/vmc03/norabt/nora/data")
    params = {
        "code": NATIVE_CODE_SAMPLE,
        "symbols": ["BTC"],
        "start": "2024-01-01",
        "end": "2024-01-03",
        "initial_capital": 10000.0,
        "train_ratio": 0.7,
    }
    out = run_custom(params)
    assert out is not None
    assert "metrics" in out
    assert "final_equity" in out
    assert "series" in out
    assert "trades" in out
    assert out["final_equity"] > 0
