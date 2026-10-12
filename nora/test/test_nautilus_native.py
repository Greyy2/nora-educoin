"""Test bộ chuyển đổi và thực thi Native Nautilus Trader Strategy (P15 Native)."""
import os
import pytest

from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from backend.alpha.compile import compile_code, is_nautilus_native
from backend.nautilus.backtest import run_native
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

    res = run_native(prog.strategy_cls, prog.symbols, start_ms, end_ms, 10_000.0, "1h")

    assert len(res["positions"]) >= 1
    p0 = res["positions"][0]
    assert p0.symbol == "BTC"        # ký hiệu người gọi truyền vào
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


# ═══ P16: một lõi + một bộ chuyển kết quả cho đường bản địa ═══════════════════
from backend.models.models import PositionStatus
from backend.nautilus import catalog as cat

T0 = 1704067200000      # 2024-01-01
HOUR = 3_600_000


class CycleStrategy(Strategy):
    """Vào BUY 0.01 mỗi 4 nến, thoát sau 2 nến theo `mode` (tag_tp | limit | stop | market | none)."""

    def __init__(self, config: StrategyConfig, instrument=None, bar_type=None, mode: str = "limit"):
        super().__init__(config)
        self.instrument, self.bar_type, self.mode, self.n = instrument, bar_type, mode, 0

    def on_start(self):
        self.subscribe_bars(self.bar_type)

    def on_bar(self, bar):
        self.n += 1
        pos = self.cache.positions_open(instrument_id=self.instrument.id)
        qty = self.instrument.make_qty(0.01)
        px = float(bar.close)
        if not pos and self.n % 4 == 0:
            self.submit_order(self.order_factory.market(self.instrument.id, OrderSide.BUY, qty, tags=["ENTRY"]))
        elif pos and self.n % 4 == 2 and self.mode != "none":
            if self.mode == "tag_tp":
                self.close_position(pos[0], tags=["TP"])
            elif self.mode == "market":
                self.close_position(pos[0])
            elif self.mode == "limit":     # limit bán thấp hơn thị trường: khớp ngay, lãi hay lỗ tuỳ giá
                self.submit_order(self.order_factory.limit(self.instrument.id, OrderSide.SELL, qty, self.instrument.make_price(px * 0.5), reduce_only=True))
            elif self.mode == "stop":      # stop bán có mức kích hoạt trên thị trường: kích hoạt ngay
                self.submit_order(self.order_factory.stop_market(self.instrument.id, OrderSide.SELL, qty, self.instrument.make_price(px * 2.0), reduce_only=True))


def _cycle(mode: str, **kw):
    return run_native(CycleStrategy, ["BTC"], T0, T0 + HOUR * 24 * 12, 10_000.0, "1h", params={"mode": mode}, **kw)


@pytest.mark.parametrize("mode,status,reason", [("tag_tp", PositionStatus.TP, "Take-profit"), ("limit", PositionStatus.TP, "limit"),
                                                ("stop", PositionStatus.SL, "dừng"), ("market", PositionStatus.CANCEL, "Exit")])
def test_close_reason_from_closing_order_not_pnl(mode, status, reason):
    res = _cycle(mode)
    pos = [p for p in res["positions"] if p.close_reason != "End of Backtest"]       # vị thế cuối kỳ do close_at_end đóng (tag END)
    assert len(pos) > 30
    # cả lệnh lãi lẫn lỗ cùng nhãn: nhãn đến từ lệnh đóng, không từ dấu PnL
    assert any(p.real_pnl > 0 for p in pos) and any(p.real_pnl < 0 for p in pos)
    assert {p.status for p in pos} == {status}
    assert all(reason in p.close_reason for p in pos), {p.close_reason for p in pos}


def test_native_unknown_fields_are_none_not_placeholders():
    res = _cycle("limit")
    for p in res["positions"]:
        assert p.mae_pct is None and p.max_price is None and p.min_price is None and p.unit_pct is None and p.risk_usd is None
        assert p.leverage_used == 1.0 and p.layers == 1 and p.entry_equity > 0
        assert p.fees_usd == pytest.approx(p.entry_fee_usd + p.exit_fee_usd, abs=1e-9)
    assert res["skipped_no_vol"] is None and res["dca_layers_rejected"] is None
    first = res["positions"][0]
    assert first.entry_equity == pytest.approx(10_000.0)                  # vốn đã chốt lúc mở lệnh đầu = vốn đầu
    assert res["positions"][1].entry_equity == pytest.approx(10_000.0 + first.real_pnl)
    assert res["final_equity"] == pytest.approx(10_000.0 + sum(p.real_pnl for p in res["positions"]), abs=1e-6)


def test_native_leverage_is_venue_leverage():
    res = _cycle("limit", leverage=5.0)
    assert {p.leverage_used for p in res["positions"]} == {5.0}
    p = res["positions"][0]
    assert p.total_margin_usd == pytest.approx(p.enter_price * p.qty / 5.0, rel=1e-9)


def test_close_at_end_leaves_no_open_positions():
    res = _cycle("none")                       # chiến lược không bao giờ thoát: chỉ close_at_end đóng
    assert res["open_positions"] == []
    assert len(res["positions"]) >= 1
    last = res["positions"][-1]
    assert last.close_reason == "End of Backtest" and last.status == PositionStatus.CANCEL
    open_run = _cycle("none", close_at_end=False)
    assert len(open_run["open_positions"]) == 1 and len(open_run["positions"]) == len(res["positions"]) - 1


class TwoSymbolStrategy(Strategy):
    def __init__(self, config: StrategyConfig, instruments=None, bar_types=None):
        super().__init__(config)
        self.instruments, self.bar_types, self.n = instruments, bar_types, 0

    def on_start(self):
        for bt in self.bar_types:
            self.subscribe_bars(bt)

    def on_bar(self, bar):
        self.n += 1
        if self.n == 10:
            for inst in self.instruments.values():
                self.submit_order(self.order_factory.market(inst.id, OrderSide.BUY, inst.make_qty(0.01 if "BTC" in str(inst.id) else 0.1)))


def test_equity_marks_each_position_at_its_own_price():
    end = T0 + HOUR * 24 * 3
    res = run_native(TwoSymbolStrategy, ["BTC", "ETH"], T0, end, 10_000.0, "1h", close_at_end=False)
    opens = {o["symbol"]: o for o in res["open_positions"]}
    assert set(opens) == {"BTC", "ETH"}
    for sym, o in opens.items():
        last = float(cat.exec_arrays(cat.normalize_symbol(sym), "1h", T0, end)["c"][-1])
        assert o["mark_price"] == pytest.approx(last) and res["last_close"][sym] == pytest.approx(last)
        assert o["unrealized_pnl"] == pytest.approx(o["qty"] * (last - o["entry_price"]), abs=1e-6)
    assert opens["BTC"]["mark_price"] != pytest.approx(opens["ETH"]["mark_price"])      # hai giá khác hẳn nhau
    expected = res["balance"] + sum(o["unrealized_pnl"] for o in opens.values())
    assert res["final_equity"] == pytest.approx(expected, abs=1e-3)
    assert res["equity_curve"][-1]["equity"] == pytest.approx(expected, abs=1e-3)


def test_run_custom_native_has_benchmark(monkeypatch):
    monkeypatch.setenv("NORA_ALLOW_UNLIMITED", "1")
    monkeypatch.delenv("NORA_LOCAL_DATA_ROOT", raising=False)
    monkeypatch.setenv("NORA_DATA_ROOT", "/home/vmc03/norabt/nora/data")
    out = run_custom({"code": NATIVE_CODE_SAMPLE, "symbols": ["BTC"], "start": "2024-01-01", "end": "2024-01-03", "initial_capital": 10000.0, "train_ratio": 0.7})
    assert not [w for w in out["warnings"] if "benchmark" in w], out["warnings"]
    assert out["series"]["benchmark"]["final_equity"] > 0
    assert out["series"]["test"]["benchmark"] is not None
    assert out["provenance"]["engine"] == "nautilus_trader"
    assert out["by_symbol"][0]["symbol"] == "BTC@perp" and out["by_symbol"][0]["trades"] >= 1
