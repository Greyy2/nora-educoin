"""Focused execution fixtures for EDU's native Nautilus matching path."""

import os
import sys
from pathlib import Path

import numpy as np

EDU_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EDU_ROOT))
os.environ["NORA_DATA_ROOT"] = str(EDU_ROOT / "data")

from backend.analys.alpha import RiskConfig
from backend.analys.param import StrategyParams
from backend.analys.position import SlotSpec
from backend.core.backtest import NautilusRun
from backend.core import catalog as cat
from backend.models.models import PositionType


class StubDataSource:
    def __init__(self, symbol, times, opens, highs, lows, closes, tick_size="0.1"):
        self.symbol = symbol
        self.arrays = {
            "t": np.asarray(times, dtype=np.int64),
            "o": np.asarray(opens, dtype=np.float64),
            "h": np.asarray(highs, dtype=np.float64),
            "l": np.asarray(lows, dtype=np.float64),
            "c": np.asarray(closes, dtype=np.float64),
            "v": np.full(len(times), 10.0, dtype=np.float64),
        }
        self.spec = {
            "tickSz": tick_size,
            "lotSz": "0.01",
            "ctVal": "1.0",
            "minSz": "0.01",
            "margin_init": "0.1",
            "margin_maint": "0.05",
            "maker_fee": "0.0002",
            "taker_fee": "0.0005",
            "base_symbol": symbol.split("-")[0],
        }

    def exec_arrays(self, symbol, frame, start, end):
        return self.arrays

    def instrument_spec(self, symbol):
        return self.spec


def make_slot(symbol, stop_loss=0.0, pos_type=PositionType.LONG, slippage_rate=0.0003):
    params = StrategyParams(
        market="perp",
        leverage=1,
        stop_loss_rate=stop_loss,
        take_profit_rate=0.0,
        fee_rate=0.0005,
        maker_fee_rate=0.0002,
        slippage_rate=slippage_rate,
        order_size_pct=0.1,
        max_capital_usage=1.0,
    )
    return SlotSpec(
        account_id=0,
        campaign_id=0,
        symbol=symbol,
        flow_name="edu_execution_fixture",
        params=params,
        pos_type=pos_type,
        initial_capital=10_000.0,
    )


def make_book(symbol, times, matches, slot):
    return {
        "symbol": symbol,
        "data": {"t": np.asarray(times, dtype=np.int64)},
        "entries": [{
            "strategy": "EDU_EXECUTION_FIXTURE",
            "slot": slot,
            "match": np.asarray(matches, dtype=bool),
            "stop": np.zeros(len(times), dtype=bool),
            "vol": None,
            "dca": None,
        }],
    }


def make_risk():
    return RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=1e12, kill_switch_dd_pct=0.0)


def test_edu_market_signal_fills_next_open_with_coin_btc_proxy(monkeypatch):
    monkeypatch.setattr(NautilusRun, "KEEP_REPORTS", True)
    symbol = "BTC-USDT-SWAP"
    frame_ms = 5 * 60_000
    times = [0, frame_ms, 2 * frame_ms]
    source = StubDataSource(symbol, times, [100.0, 104.0, 106.0], [105.0, 108.0, 107.0],
                            [99.0, 103.0, 105.0], [102.0, 106.0, 105.5])
    run = NautilusRun(
        [make_book(symbol, times, [True, False, False], make_slot(symbol))],
        10_000.0,
        make_risk(),
        0,
        3 * frame_ms,
        "5m",
        True,
        source,
    ).run()

    assert run["open_positions"][0]["entry_price"] == 104.1
    fill = run["reports"]["fills"].iloc[0]
    assert fill["avg_px"] == 104.1
    assert fill["ts_last"].value == frame_ms * 1_000_000 + 2


def test_edu_signal_on_final_bar_remains_unfilled():
    symbol = "BTC-USDT-SWAP"
    frame_ms = 5 * 60_000
    times = [0]
    source = StubDataSource(symbol, times, [100.0], [105.0], [99.0], [102.0])

    result = NautilusRun(
        [make_book(symbol, times, [True], make_slot(symbol))],
        10_000.0,
        make_risk(),
        0,
        frame_ms,
        "5m",
        True,
        source,
    ).run()

    assert result["open_positions"] == []
    assert result["positions"] == []
    assert result["orders"] == []


def test_edu_gap_stop_uses_coin_double_slippage_proxy(monkeypatch):
    monkeypatch.setattr(NautilusRun, "KEEP_REPORTS", True)
    symbol = "BTC-USDT-SWAP"
    frame_ms = 5 * 60_000
    times = [0, frame_ms, 2 * frame_ms]
    source = StubDataSource(
        symbol,
        times,
        [100.0, 100.0, 90.0],
        [105.0, 101.0, 91.0],
        [99.0, 99.0, 89.0],
        [100.0, 100.0, 90.0],
        tick_size="0.01",
    )

    result = NautilusRun(
        [make_book(symbol, times, [True, False, False], make_slot(symbol, stop_loss=5.0))],
        10_000.0,
        make_risk(),
        0,
        3 * frame_ms,
        "5m",
        True,
        source,
    ).run()

    assert len(result["positions"]) == 1
    assert result["positions"][0].status.name == "SL"
    fill = result["reports"]["fills"].iloc[-1]
    assert fill["type"] == "STOP_MARKET"
    assert fill["avg_px"] == 89.94
    assert fill["ts_last"].value == 2 * frame_ms * 1_000_000 + 2


def test_edu_eth_short_stop_uses_coin_double_slippage_proxy(monkeypatch):
    monkeypatch.setattr(NautilusRun, "KEEP_REPORTS", True)
    symbol = "ETH-USDT-SWAP"
    frame_ms = 5 * 60_000
    times = [0, frame_ms, 2 * frame_ms, 3 * frame_ms]
    source = StubDataSource(
        symbol,
        times,
        [100.0, 100.0, 100.0, 100.0],
        [101.0, 101.0, 106.0, 101.0],
        [99.0, 99.0, 99.0, 99.0],
        [100.0, 100.0, 100.0, 100.0],
        tick_size="0.01",
    )

    result = NautilusRun(
        [make_book(symbol, times, [True, False, False, False],
                   make_slot(symbol, stop_loss=5.0, pos_type=PositionType.SHORT, slippage_rate=0.0005))],
        10_000.0,
        make_risk(),
        0,
        4 * frame_ms,
        "5m",
        True,
        source,
    ).run()

    assert len(result["positions"]) == 1
    assert result["positions"][0].status.name == "SL"
    fill = result["reports"]["fills"].iloc[-1]
    assert fill["type"] == "STOP_MARKET"
    assert fill["avg_px"] == 106.11
    assert fill["ts_last"].value == 3 * frame_ms * 1_000_000


def test_edu_unlisted_catalog_asset_uses_configured_slippage(monkeypatch):
    monkeypatch.setattr(NautilusRun, "KEEP_REPORTS", True)
    symbol = "AERO-USDT-SWAP"
    frame_ms = 5 * 60_000
    times = [0, frame_ms, 2 * frame_ms]
    source = StubDataSource(symbol, times, [100.0] * 3, [101.0] * 3,
                            [99.0] * 3, [100.0] * 3)

    result = NautilusRun(
        [make_book(symbol, times, [True, False, False],
                   make_slot(symbol, slippage_rate=0.0007))],
        10_000.0,
        make_risk(),
        0,
        3 * frame_ms,
        "5m",
        True,
        source,
        execution_target="next_open",
    ).run()

    assert result["positions"][0].enter_price == 100.1
