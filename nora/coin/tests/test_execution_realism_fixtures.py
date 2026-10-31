"""Kiểm toán Fixture Độc lập cho Tính Hiện thực Thực thi (Execution Realism / GATE 3).

Kiểm tra:
1. Signal tại close nến T KHÔNG ĐƯỢC khớp ở close nến T, mà PHẢI khớp tại OPEN nến T+1.
2. Signal tại nến cuối cùng (không có nến tiếp theo) KHÔNG ĐƯỢC khớp (không có next observation open).
3. Trượt giá và spread proxy được áp dụng đúng (BTC 3 bps, ETH 5 bps) trên giá OPEN nến T+1.
4. Stop Loss xuyên qua (Gap-through SL): Khi nến sau mở cửa gap qua mức SL, lệnh SL khớp theo quote mở cửa và proxy trượt giá stop x2.
5. Same-bar SL/TP adverse ordering: Khi cả mức SL và TP đều bị chạm trong cùng một nến, lệnh SL phải được ưu tiên kích hoạt trước (quy tắc bảo thủ chống overfit).
"""
import os
import sys
import inspect
from pathlib import Path
from decimal import Decimal
import numpy as np
import pytest

COIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COIN_ROOT))

from backend.analys.param import StrategyParams
from backend.analys.position import SlotSpec
from backend.core.backtest import NautilusRun, _open_quote_ticks
from backend.core.backtest import build_slots
from backend.core.strategy import NoraSlotStrategy
from backend.core import catalog as cat
from backend.analys.alpha import RiskConfig
from backend.models.models import PositionType
from nautilus_trader.backtest.modules import SimulationModule
from nautilus_trader.backtest.config import SimulationModuleConfig


def test_execution_defaults_keep_live_on_nautilus_matching_engine():
    assert inspect.signature(NoraSlotStrategy.__init__).parameters["execution_target"].default == "nautilus"
    assert inspect.signature(build_slots).parameters["execution_target"].default == "nautilus"
    assert inspect.signature(NautilusRun.__init__).parameters["execution_target"].default == "nautilus"


def test_default_backtest_uses_native_nautilus_next_open_quote_fill(monkeypatch):
    monkeypatch.setattr(NautilusRun, "KEEP_REPORTS", True)
    symbol = "BTC-USDT-SWAP"
    frame = "5m"
    fr_ms = 5 * 60_000
    times = [0, fr_ms]
    ds = SimpleStubDataSource(
        symbol,
        frame,
        times,
        opens=[100.0, 104.0],
        highs=[105.0, 108.0],
        lows=[99.0, 103.0],
        closes=[102.0, 106.0],
        vols=[10.0, 15.0],
    )
    slot = make_slot(symbol)
    book = {
        "symbol": symbol,
        "data": {"t": np.array(times, dtype=np.int64)},
        "entries": [{
            "strategy": "NATIVE_DEFAULT",
            "slot": slot,
            "match": np.array([True, False], dtype=bool),
            "stop": np.array([False, False], dtype=bool),
            "vol": None,
            "dca": None,
        }],
    }
    risk = RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=1e12, kill_switch_dd_pct=0.0)
    res = NautilusRun(
        books=[book],
        initial_capital=10_000.0,
        risk=risk,
        trade_start_ts=0,
        end_ts=2 * fr_ms,
        base_frame=frame,
        close_at_end=True,
        data=ds,
    ).run()
    assert len(res["open_positions"]) == 1
    entry = res["open_positions"][0]
    assert entry["entry_price"] == 104.1
    assert entry["opened"] == fr_ms
    fill = res["reports"]["fills"].iloc[0]
    assert fill["type"] == "MARKET"
    assert fill["side"] == "BUY"
    assert fill["status"] == "FILLED"
    assert fill["avg_px"] == 104.1
    assert fill["ts_last"].value == fr_ms * 1_000_000 + 2


def test_default_backtest_does_not_fill_signal_on_final_bar():
    symbol = "BTC-USDT-SWAP"
    frame = "5m"
    fr_ms = 5 * 60_000
    times = [0]
    ds = SimpleStubDataSource(
        symbol,
        frame,
        times,
        opens=[100.0],
        highs=[105.0],
        lows=[99.0],
        closes=[102.0],
        vols=[10.0],
    )
    slot = make_slot(symbol)
    book = {
        "symbol": symbol,
        "data": {"t": np.array(times, dtype=np.int64)},
        "entries": [{
            "strategy": "FINAL_BAR_SIGNAL",
            "slot": slot,
            "match": np.array([True], dtype=bool),
            "stop": np.array([False], dtype=bool),
            "vol": None,
            "dca": None,
        }],
    }
    risk = RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=1e12, kill_switch_dd_pct=0.0)
    res = NautilusRun(
        books=[book],
        initial_capital=10_000.0,
        risk=risk,
        trade_start_ts=0,
        end_ts=fr_ms,
        base_frame=frame,
        close_at_end=True,
        data=ds,
    ).run()

    assert res["open_positions"] == []
    assert res["positions"] == []
    assert res["orders"] == []


def test_native_stop_market_gap_applies_double_proxy_slippage(monkeypatch):
    monkeypatch.setattr(NautilusRun, "KEEP_REPORTS", True)
    symbol = "BTC-USDT-SWAP"
    frame = "5m"
    fr_ms = 5 * 60_000
    times = [0, fr_ms, 2 * fr_ms]
    ds = SimpleStubDataSource(
        symbol,
        frame,
        times,
        opens=[100.0, 100.0, 90.0],
        highs=[105.0, 101.0, 91.0],
        lows=[99.0, 99.0, 89.0],
        closes=[100.0, 100.0, 90.0],
        vols=[10.0, 10.0, 10.0],
        tick_sz="0.01",
    )
    slot = make_slot(symbol, sl=5.0)
    book = {
        "symbol": symbol,
        "data": {"t": np.array(times, dtype=np.int64)},
        "entries": [{
            "strategy": "NATIVE_SL_GAP",
            "slot": slot,
            "match": np.array([True, False, False], dtype=bool),
            "stop": np.array([False, False, False], dtype=bool),
            "vol": None,
            "dca": None,
        }],
    }
    risk = RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=1e12, kill_switch_dd_pct=0.0)
    res = NautilusRun(
        books=[book],
        initial_capital=10_000.0,
        risk=risk,
        trade_start_ts=0,
        end_ts=3 * fr_ms,
        base_frame=frame,
        close_at_end=True,
        data=ds,
    ).run()

    assert len(res["positions"]) == 1
    assert res["positions"][0].status.name == "SL"
    stop_fill = res["reports"]["fills"].iloc[-1]
    assert stop_fill["type"] == "STOP_MARKET"
    assert stop_fill["avg_px"] == 89.94
    assert stop_fill["ts_last"].value == 2 * fr_ms * 1_000_000 + 2


@pytest.mark.parametrize(
    ("symbol", "pos_type", "highs", "lows", "expected_fill"),
    [
        ("BTC-USDT-SWAP", PositionType.LONG, [101.0, 101.0, 101.0, 101.0], [99.0, 99.0, 94.0, 99.0], 93.94),
        ("ETH-USDT-SWAP", PositionType.SHORT, [101.0, 101.0, 106.0, 101.0], [99.0, 99.0, 99.0, 99.0], 106.11),
    ],
)
def test_native_intrabar_stop_applies_double_proxy_slippage(monkeypatch, symbol, pos_type, highs, lows, expected_fill):
    monkeypatch.setattr(NautilusRun, "KEEP_REPORTS", True)
    frame = "5m"
    fr_ms = 5 * 60_000
    times = [0, fr_ms, 2 * fr_ms, 3 * fr_ms]
    ds = SimpleStubDataSource(
        symbol,
        frame,
        times,
        opens=[100.0, 100.0, 100.0, 100.0],
        highs=highs,
        lows=lows,
        closes=[100.0, 100.0, 100.0, 100.0],
        vols=[10.0, 10.0, 10.0, 10.0],
        tick_sz="0.01",
    )
    slip = 0.0005 if symbol.startswith("ETH-") else 0.0003
    slot = make_slot(symbol, pos_type=pos_type, sl=5.0, slippage_rate=slip)
    book = {
        "symbol": symbol,
        "data": {"t": np.array(times, dtype=np.int64)},
        "entries": [{
            "strategy": "NATIVE_SL_INTRABAR",
            "slot": slot,
            "match": np.array([True, False, False, False], dtype=bool),
            "stop": np.array([False, False, False, False], dtype=bool),
            "vol": None,
            "dca": None,
        }],
    }
    risk = RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=1e12, kill_switch_dd_pct=0.0)
    res = NautilusRun(
        books=[book],
        initial_capital=10_000.0,
        risk=risk,
        trade_start_ts=0,
        end_ts=4 * fr_ms,
        base_frame=frame,
        close_at_end=True,
        data=ds,
    ).run()

    assert len(res["positions"]) == 1
    assert res["positions"][0].status.name == "SL"
    stop_fill = res["reports"]["fills"].iloc[-1]
    assert stop_fill["type"] == "STOP_MARKET"
    assert stop_fill["avg_px"] == expected_fill
    assert stop_fill["ts_last"].value == 3 * fr_ms * 1_000_000


class NextOpenModuleConfig(SimulationModuleConfig, frozen=True):
    pass


class NextOpenExecutionModule(SimulationModule):
    def __init__(self):
        super().__init__(NextOpenModuleConfig())
        self.pending_intents = []

    def queue_intent(self, slot, side, qty):
        self.pending_intents.append((slot, side, qty))

    def pre_process(self, data):
        if not hasattr(self, "_adjusted"):
            self._adjusted = True
            from nautilus_trader.model.objects import Money
            from nautilus_trader.model.currencies import USDT
            self.exchange.adjust_account(Money(-50.0, USDT))

    def process(self, ts_now: int):
        pass

    def reset(self):
        self.pending_intents.clear()

    def log_diagnostics(self, logger):
        pass


def test_subclass_simulation_module():
    mod = NextOpenExecutionModule()
    assert mod is not None


from nautilus_trader.backtest.engine import BacktestEngine as NautilusEngine
from nautilus_trader.backtest.config import BacktestEngineConfig
from nautilus_trader.config import LoggingConfig, RiskEngineConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.objects import Money


def test_simulation_module_intercepts_bar():
    mod = NextOpenExecutionModule()
    eng = NautilusEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True), risk_engine=RiskEngineConfig(bypass=True), run_analysis=False))
    eng.add_venue(venue=cat.VENUE_OKX, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN, base_currency=USDT,
                  starting_balances=[Money(10000.0, USDT)], bar_execution=True, modules=[mod])
    assert mod.exchange is not None

    symbol = "BTC-USDT-SWAP"
    inst = cat.build_instrument(symbol, {
        "tickSz": "0.1", "lotSz": "0.01", "ctVal": "1.0", "minSz": "0.01",
        "margin_init": "0.1", "margin_maint": "0.05", "maker_fee": "0.0002", "taker_fee": "0.0005"
    })
    eng.add_instrument(inst)

    from nautilus_trader.trading.strategy import Strategy, StrategyConfig
    from nautilus_trader.model.enums import OrderSide
    from nautilus_trader.model.objects import Quantity

    class TestStrategy(Strategy):
        def __init__(self, mod, inst):
            super().__init__(StrategyConfig(strategy_id="TEST"))
            self.mod = mod
            self.inst = inst
            self.fills = []

        def on_start(self):
            self.subscribe_bars(cat.get_bar_type("BTC-USDT-SWAP", "5m"))

        def on_bar(self, bar):
            if bar.open.as_double() == 100.0:  # Bar 0
                self.mod.queue_intent(self, OrderSide.BUY, Quantity.from_str("0.01"))

        def on_order_filled(self, event):
            self.fills.append((event.last_px.as_double(), event.ts_event))

    strat = TestStrategy(mod, inst)
    eng.add_strategy(strat)

    fr_ms = 300_000
    times = [0, fr_ms]
    opens = [100.0, 104.0]
    highs = [105.0, 108.0]
    lows = [99.0, 103.0]
    closes = [102.0, 106.0]
    vols = [10.0, 15.0]
    arr = {"t": np.array(times), "o": np.array(opens), "h": np.array(highs), "l": np.array(lows), "c": np.array(closes), "v": np.array(vols)}
    bars = cat.bars_from_arrays(symbol, arr, "5m", inst)
    eng.add_data(bars)
    eng.run()

    acct = eng.cache.account_for_venue(cat.VENUE_OKX)
    bal = acct.balance_total(USDT).as_double()
    print("Account balance after adjust_account:", bal)
    assert bal == 9950.0, f"Expected 9950.0 after -50.0 adjustment, got {bal}!"


class SimpleStubDataSource:
    """Nguồn dữ liệu stub tối thiểu cho kiểm thử fixture thực thi."""
    def __init__(self, symbol: str, frame: str, times: list, opens: list, highs: list, lows: list, closes: list, vols: list,
                 tick_sz: str = "0.1", lot_sz: str = "0.01", maker_fee: str = "0.0002", taker_fee: str = "0.0005"):
        self.symbol = symbol
        self.frame = frame
        self._arrays = {
            "t": np.array(times, dtype=np.int64),
            "o": np.array(opens, dtype=np.float64),
            "h": np.array(highs, dtype=np.float64),
            "l": np.array(lows, dtype=np.float64),
            "c": np.array(closes, dtype=np.float64),
            "v": np.array(vols, dtype=np.float64),
        }
        self._spec = {
            "tickSz": tick_sz,
            "lotSz": lot_sz,
            "ctVal": "1.0",
            "minSz": lot_sz,
            "margin_init": "0.1",
            "margin_maint": "0.05",
            "maker_fee": maker_fee,
            "taker_fee": taker_fee,
            "base_symbol": symbol.split("-")[0] if "-" in symbol else symbol,
        }

    def exec_arrays(self, symbol: str, frame: str, start: int, end: int):
        return self._arrays

    def instrument_spec(self, symbol: str):
        return self._spec

    def require_ok(self, symbols):
        pass


def make_slot(symbol: str, pos_type: PositionType = PositionType.LONG, sl: float = 0.0, tp: float = 0.0,
              fee_rate: float = 0.0005, slippage_rate: float = 0.0003, max_leverage: float = 1.0) -> SlotSpec:
    params = StrategyParams(
        market="perp",
        leverage=int(max_leverage),
        stop_loss_rate=sl,
        take_profit_rate=tp,
        fee_rate=fee_rate,
        maker_fee_rate=0.0002,
        slippage_rate=slippage_rate,
        order_size_pct=0.1,  # 10%
        max_capital_usage=1.0,
    )
    return SlotSpec(
        account_id=0,
        campaign_id=0,
        symbol=symbol,
        flow_name="test_flow",
        params=params,
        pos_type=pos_type,
        initial_capital=10_000.0,
    )


def test_independent_fixture_signal_at_close_fills_at_next_open():
    """GATE 3 FIXTURE 1: Tín hiệu sinh lúc nến 0 đóng (close 102.0) PHẢI khớp tại open nến 1 (104.0), KHÔNG PHẢI 102.0."""
    symbol = "BTC-USDT-SWAP"
    frame = "5m"
    fr_ms = 5 * 60_000

    # 3 nến 5m
    # Bar 0: t = 0..300s, o=100.0, h=105.0, l=99.0, c=102.0
    # Bar 1: t = 300..600s, o=104.0, h=108.0, l=103.0, c=106.0
    # Bar 2: t = 600..900s, o=106.0, h=107.0, l=105.0, c=105.5
    times = [0, fr_ms, 2 * fr_ms]
    opens = [100.0, 104.0, 106.0]
    highs = [105.0, 108.0, 107.0]
    lows = [99.0, 103.0, 105.0]
    closes = [102.0, 106.0, 105.5]
    vols = [10.0, 15.0, 12.0]

    ds = SimpleStubDataSource(symbol, frame, times, opens, highs, lows, closes, vols)
    slot = make_slot(symbol, pos_type=PositionType.LONG)

    # Tín hiệu: Match tại nến 0 (close = 102.0)
    match_arr = np.array([True, False, False], dtype=bool)
    stop_arr = np.array([False, False, False], dtype=bool)

    book = {
        "symbol": symbol,
        "data": {"t": np.array(times, dtype=np.int64)},
        "entries": [{
            "strategy": "TEST_ALPHA",
            "slot": slot,
            "match": match_arr,
            "stop": stop_arr,
            "vol": None,
            "dca": None,
        }],
    }

    risk = RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=1e12, kill_switch_dd_pct=0.0)
    runner = NautilusRun(
        books=[book],
        initial_capital=10_000.0,
        risk=risk,
        trade_start_ts=0,
        end_ts=3 * fr_ms,
        base_frame=frame,
        close_at_end=True,
        data=ds,
        execution_target="next_open",
    )
    res = runner.run()

    positions = res["positions"]
    orders = res["orders"]

    assert len(positions) >= 1 or len(orders) >= 1, "Phải có lệnh hoặc vị thế được ghi nhận"
    
    # Kiểm tra fill của lệnh ENTRY
    entry_orders = [o for o in orders if getattr(o, "order_type", None) == "BUY" or getattr(o, "side", "") == "BUY"]
    first_order = entry_orders[0] if entry_orders else orders[0]
    first_fill_price = first_order.order_price

    # TIÊU CHÍ NGHIỆM THU GATE 3:
    # Giá khớp KHÔNG ĐƯỢC là giá đóng nến 0 (102.0)!
    # Giá khớp PHẢI nằm ở nến 1 (open = 104.0, có thể cộng spread proxy BTC 3 bps: ~104.03)
    assert first_fill_price != 102.0, f"Thất bại: Lệnh đang bị khớp ở close nến 0 (102.0), vi phạm causality/timing parity!"
    assert abs(first_fill_price - 104.0) < 0.5, f"Lệnh phải khớp ở open nến 1 (104.0 ± proxy), nhưng nhận {first_fill_price}"
    # Thời điểm khớp phải là open nến 1 (fr_ms = 300_000 ms)
    assert first_order.order_time >= fr_ms, f"Thời điểm lệnh ({first_order.order_time}) phải >= {fr_ms} (open nến 1)"


def test_independent_fixture_signal_on_last_bar_remains_unfilled():
    """GATE 3 FIXTURE 2: Tín hiệu tại nến cuối cùng không có nến kế tiếp thì KHÔNG ĐƯỢC khớp."""
    symbol = "BTC-USDT-SWAP"
    frame = "5m"
    fr_ms = 5 * 60_000

    # Chỉ có 1 nến duy nhất
    times = [0]
    opens = [100.0]
    highs = [105.0]
    lows = [99.0]
    closes = [102.0]
    vols = [10.0]

    ds = SimpleStubDataSource(symbol, frame, times, opens, highs, lows, closes, vols)
    slot = make_slot(symbol, pos_type=PositionType.LONG)

    # Match ở nến duy nhất này
    match_arr = np.array([True], dtype=bool)
    stop_arr = np.array([False], dtype=bool)

    book = {
        "symbol": symbol,
        "data": {"t": np.array(times, dtype=np.int64)},
        "entries": [{
            "strategy": "TEST_ALPHA",
            "slot": slot,
            "match": match_arr,
            "stop": stop_arr,
            "vol": None,
            "dca": None,
        }],
    }

    risk = RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=1e12, kill_switch_dd_pct=0.0)
    runner = NautilusRun(
        books=[book],
        initial_capital=10_000.0,
        risk=risk,
        trade_start_ts=0,
        end_ts=fr_ms,
        base_frame=frame,
        close_at_end=True,
        data=ds,
        execution_target="next_open",
    )
    res = runner.run()

    # Vì không có nến tiếp theo, lệnh không thể khớp ở open nến kế tiếp -> KHÔNG ĐƯỢC có vị thế được mở
    assert len(res["positions"]) == 0, f"Thất bại: Nến cuối không có next-open nhưng vẫn sinh {len(res['positions'])} vị thế!"
    assert len(res["orders"]) == 0, f"Thất bại: Nến cuối không có next-open nhưng vẫn sinh {len(res['orders'])} lệnh!"


def test_independent_fixture_proxy_spread_btc_and_eth():
    """GATE 3 FIXTURE 3: Spread proxy được áp dụng đúng: BTC 3 bps (0.0003), ETH 5 bps (0.0005) trên giá OPEN."""
    frame = "5m"
    fr_ms = 5 * 60_000
    times = [0, fr_ms, 2 * fr_ms]
    opens = [1000.0, 1000.0, 1000.0]
    highs = [1010.0, 1010.0, 1010.0]
    lows = [990.0, 990.0, 990.0]
    closes = [1000.0, 1000.0, 1000.0]
    vols = [10.0, 10.0, 10.0]

    # Test BTC (3 bps -> 1000 * 1.0003 = 1000.3)
    ds_btc = SimpleStubDataSource("BTC-USDT-SWAP", frame, times, opens, highs, lows, closes, vols, tick_sz="0.01")
    slot_btc = make_slot("BTC-USDT-SWAP", pos_type=PositionType.LONG)
    book_btc = {
        "symbol": "BTC-USDT-SWAP",
        "data": {"t": np.array(times, dtype=np.int64)},
        "entries": [{"strategy": "TEST_BTC", "slot": slot_btc, "match": np.array([True, False, False]), "stop": np.array([False, False, False]), "vol": None, "dca": None}],
    }
    risk = RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=1e12, kill_switch_dd_pct=0.0)
    runner_btc = NautilusRun(books=[book_btc], initial_capital=10_000.0, risk=risk, trade_start_ts=0, end_ts=3 * fr_ms, base_frame=frame, close_at_end=True, data=ds_btc, execution_target="next_open")
    res_btc = runner_btc.run()
    from backend.models.models import OrderType
    btc_entry = [o for o in res_btc["orders"] if o.order_type == OrderType.BUY][0]
    assert abs(btc_entry.order_price - 1000.3) < 0.05, f"BTC phải khớp tại 1000.3 (3 bps proxy), got {btc_entry.order_price}"

    # Test ETH (5 bps -> 1000 * 1.0005 = 1000.5)
    ds_eth = SimpleStubDataSource("ETH-USDT-SWAP", frame, times, opens, highs, lows, closes, vols, tick_sz="0.01")
    slot_eth = make_slot("ETH-USDT-SWAP", pos_type=PositionType.LONG)
    book_eth = {
        "symbol": "ETH-USDT-SWAP",
        "data": {"t": np.array(times, dtype=np.int64)},
        "entries": [{"strategy": "TEST_ETH", "slot": slot_eth, "match": np.array([True, False, False]), "stop": np.array([False, False, False]), "vol": None, "dca": None}],
    }
    runner_eth = NautilusRun(books=[book_eth], initial_capital=10_000.0, risk=risk, trade_start_ts=0, end_ts=3 * fr_ms, base_frame=frame, close_at_end=True, data=ds_eth, execution_target="next_open")
    res_eth = runner_eth.run()
    eth_entry = [o for o in res_eth["orders"] if o.order_type == OrderType.BUY][0]
    assert abs(eth_entry.order_price - 1000.5) < 0.05, f"ETH phải khớp tại 1000.5 (5 bps proxy), got {eth_entry.order_price}"


def test_independent_fixture_gap_through_stop_loss():
    """GATE 3 FIXTURE 4: Khi nến sau mở gap qua SL (ví dụ SL 95, open 90), SL PHẢI khớp ở giá open (90 ± proxy), không được giữ giá trigger 95."""
    symbol = "BTC-USDT-SWAP"
    frame = "5m"
    fr_ms = 5 * 60_000
    times = [0, fr_ms, 2 * fr_ms]
    # Bar 0: Signal match at close
    # Bar 1: Fills at open 100.0. High 101.0, Low 99.0, Close 100.0
    # Bar 2: GAP DOWN! Open 90.0, High 91.0, Low 89.0, Close 90.0
    opens = [100.0, 100.0, 90.0]
    highs = [105.0, 101.0, 91.0]
    lows = [99.0, 99.0, 89.0]
    closes = [100.0, 100.0, 90.0]
    vols = [10.0, 10.0, 10.0]

    ds = SimpleStubDataSource(symbol, frame, times, opens, highs, lows, closes, vols, tick_sz="0.01")
    # SL là 5% (từ giá vào ~100.03 -> mức SL là ~95.03)
    slot = make_slot(symbol, pos_type=PositionType.LONG, sl=5.0)
    book = {
        "symbol": symbol,
        "data": {"t": np.array(times, dtype=np.int64)},
        "entries": [{"strategy": "TEST_SL_GAP", "slot": slot, "match": np.array([True, False, False]), "stop": np.array([False, False, False]), "vol": None, "dca": None}],
    }
    risk = RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=1e12, kill_switch_dd_pct=0.0)
    runner = NautilusRun(books=[book], initial_capital=10_000.0, risk=risk, trade_start_ts=0, end_ts=3 * fr_ms, base_frame=frame, close_at_end=True, data=ds, execution_target="next_open")
    res = runner.run()

    positions = res["positions"]
    assert len(positions) == 1, "Phải có đúng 1 vị thế đã đóng"
    pos = positions[0]
    from backend.models.models import PositionStatus
    assert pos.status == PositionStatus.SL, f"Vị thế phải đóng bởi SL, got {pos.status}"
    # Giá đóng phải là giá gap open (90.0 - 3 bps proxy = ~89.97), TUYỆT ĐỐI KHÔNG ĐƯỢC LÀ ~95.03
    assert abs(pos.close_price - 95.03) > 1.0, f"Thất bại: Giá đóng bị gán nhầm trigger level 95.0 thay vì giá gap open!"
    assert abs(pos.close_price - 89.97) < 0.1, f"Giá đóng phải là ~89.97 (gap open 90 - 3 bps proxy), got {pos.close_price}"


def test_independent_fixture_same_bar_sl_tp_adverse_ordering():
    """GATE 3 FIXTURE 5: Khi cả SL và TP cùng chạm trong 1 nến, SL PHẢI được ưu tiên kích hoạt trước (bảo thủ chống overfitting)."""
    symbol = "BTC-USDT-SWAP"
    frame = "5m"
    fr_ms = 5 * 60_000
    times = [0, fr_ms, 2 * fr_ms]
    # Bar 0: Signal match at close
    # Bar 1: Fills at open 100.0. High 101.0, Low 99.0, Close 100.0
    # Bar 2: Cực kỳ biến động! Open 100.0, High 110.0 (chạm TP 5%), Low 90.0 (chạm SL 5%), Close 105.0
    opens = [100.0, 100.0, 100.0]
    highs = [105.0, 101.0, 110.0]
    lows = [99.0, 99.0, 90.0]
    closes = [100.0, 100.0, 105.0]
    vols = [10.0, 10.0, 10.0]

    ds = SimpleStubDataSource(symbol, frame, times, opens, highs, lows, closes, vols, tick_sz="0.01")
    # SL 5%, TP 5%
    slot = make_slot(symbol, pos_type=PositionType.LONG, sl=5.0, tp=5.0)
    book = {
        "symbol": symbol,
        "data": {"t": np.array(times, dtype=np.int64)},
        "entries": [{"strategy": "TEST_ADVERSE", "slot": slot, "match": np.array([True, False, False]), "stop": np.array([False, False, False]), "vol": None, "dca": None}],
    }
    risk = RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=1e12, kill_switch_dd_pct=0.0)
    runner = NautilusRun(books=[book], initial_capital=10_000.0, risk=risk, trade_start_ts=0, end_ts=3 * fr_ms, base_frame=frame, close_at_end=True, data=ds, execution_target="next_open")
    res = runner.run()

    positions = res["positions"]
    assert len(positions) == 1, "Phải có đúng 1 vị thế đã đóng"
    pos = positions[0]
    from backend.models.models import PositionStatus
    assert pos.status == PositionStatus.SL, f"Quy tắc adverse ordering yêu cầu vị thế phải đóng bởi SL khi cả hai cùng chạm, nhưng nhận {pos.status}"
    assert pos.real_pnl < 0, f"PnL phải là âm do chạm SL, got {pos.real_pnl}"


def test_unlisted_catalog_asset_uses_configured_slippage_without_symbol_whitelist(monkeypatch):
    monkeypatch.setattr(NautilusRun, "KEEP_REPORTS", True)
    symbol = "AERO-USDT-SWAP"
    frame_ms = 5 * 60_000
    times = [0, frame_ms, 2 * frame_ms]
    source = SimpleStubDataSource(symbol, "5m", times, [100.0] * 3, [101.0] * 3,
                                  [99.0] * 3, [100.0] * 3, [10.0] * 3)
    slot = make_slot(symbol, slippage_rate=0.0007)

    result = NautilusRun(
        [{"symbol": symbol, "data": {"t": np.asarray(times)}, "entries": [{
            "strategy": "UNLISTED_ASSET", "slot": slot,
            "match": np.asarray([True, False, False]), "stop": np.zeros(3, dtype=bool),
            "vol": None, "dca": None,
        }]}],
        10_000.0,
        RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=1e12, kill_switch_dd_pct=0.0),
        0,
        3 * frame_ms,
        "5m",
        True,
        source,
        execution_target="next_open",
    ).run()

    assert result["positions"][0].enter_price == 100.1
