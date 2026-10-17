"""Kiểm thử định tuyến và phân loại Hybrid (P17 T4): Nora DSL ↔ Nautilus native.

Kiểm tra:
- 10 mẫu DSL chuẩn -> engine = 'dsl', lý do = 'khớp hợp đồng Nora DSL'
- 10 mẫu Native sự kiện phức tạp -> engine = 'native'
- 3 ca biên: helper ngoài, native vi phạm sandbox, code rác/lỗi cú pháp
"""
import pytest
from backend.alpha.route import classify
from backend.alpha.compile import compile_code
from backend.signal.nodes import DslError


# ─── 10 MẪU DSL CHUẨN ────────────────────────────────────────────────────────

DSL_SAMPLES = [
    # 1. Dual EMA
    """
class DualEma(SimpleAlgorithm):
    fast = 10
    slow = 20
    def __algorithm__(self):
        f = self.feat.ema(self.data.close, self.fast)
        s = self.feat.ema(self.data.close, self.slow)
        self.set_positions(f > s, position=1.0)
""",
    # 2. RSI Mean Reversion
    """
class RsiReversion(SimpleAlgorithm):
    rsi_period = 14
    def __algorithm__(self):
        r = self.feat.rsi(self.data.close, self.rsi_period)
        self.set_positions(r < 30, position=1.0)
        self.set_positions(r > 70, position=-1.0)
""",
    # 3. Keltner Breakout
    """
class KeltnerBreakout(SimpleAlgorithm):
    period = 20
    mult = 2.0
    def __algorithm__(self):
        m = self.feat.ema(self.data.close, self.period)
        a = self.feat.atr(self.data.high, self.data.low, self.data.close, 14)
        up = m + a * self.mult
        self.set_positions(self.data.close > up, position=1.0)
""",
    # 4. Bollinger Band
    """
class BollingerBand(SimpleAlgorithm):
    period = 20
    def __algorithm__(self):
        m = self.feat.sma(self.data.close, self.period)
        std = self.feat.stddev(self.data.close, self.period)
        self.set_positions(self.data.close < m - 2 * std, position=1.0)
""",
    # 5. MACD Cross
    """
class MacdCross(SimpleAlgorithm):
    def __algorithm__(self):
        macd_line, signal_line, hist = self.feat.macd(self.data.close, 12, 26, 9)
        self.set_positions(macd_line > signal_line, position=1.0)
""",
    # 6. Lifecycle on_bar style
    """
class NoraBarStrategy(NoraStrategy):
    timeframe = "1h"
    def on_bar(self):
        e = ema(close, 20)
        self.buy(crossover(close, e))
        self.close(close < e)
""",
    # 7. Donchian Breakout
    """
class DonchianBreakout(SimpleAlgorithm):
    def __algorithm__(self):
        h = self.feat.rolling_max(self.data.high, 20)
        self.set_positions(self.data.close >= h, position=1.0)
""",
    # 8. Momentum ROC
    """
class MomentumRoc(SimpleAlgorithm):
    def __algorithm__(self):
        r = self.feat.returns(self.data.close, 10)
        self.set_positions(r > 0.05, position=1.0)
""",
    # 9. SuperTrend
    """
class SuperTrend(SimpleAlgorithm):
    def __algorithm__(self):
        a = self.feat.atr(self.data.high, self.data.low, self.data.close, 10)
        self.set_positions(self.data.close > self.data.open + a, position=1.0)
""",
    # 10. Volume Weighted
    """
class VolumeWeighted(SimpleAlgorithm):
    def __algorithm__(self):
        v_ma = self.feat.sma(self.data.volume, 20)
        self.set_positions((self.data.volume > v_ma * 2) & (self.data.close > self.data.open), position=1.0)
""",
]


# ─── 10 MẪU NATIVE SỰ KIỆN PHỨC TẠP ──────────────────────────────────────────

NATIVE_SAMPLES = [
    # 1. Kế thừa Strategy Nautilus chuẩn
    """
from nautilus_trader.trading.strategy import Strategy

class MyNautilusStrategy(Strategy):
    def on_bar(self, bar):
        pass
""",
    # 2. Xử lý sự kiện on_order_filled
    """
class OrderTracker:
    def on_order_filled(self, event):
        self.last_fill = event.last_px
""",
    # 3. Đặt lệnh chủ động submit_order
    """
class ExecutionBot:
    def execute(self, side, qty):
        order = self.create_order(side, qty)
        self.submit_order(order)
""",
    # 4. Giao dịch theo từng tick (on_trade_tick)
    """
class HighFrequencyTick:
    def on_trade_tick(self, tick):
        if tick.price > 100:
            self.buy_fast()
""",
    # 5. Theo dõi sổ lệnh depth (on_order_book_depth)
    """
class OrderBookImbalance:
    def on_order_book_depth(self, depth):
        bids = depth.bids()
        asks = depth.asks()
""",
    # 6. Sửa lệnh đang chờ modify_order
    """
class MarketMakerPeg:
    def update_spread(self, new_px):
        self.modify_order(self.bid_id, price=new_px)
""",
    # 7. Quản lý đồng thời portfolio động (self.portfolio)
    """
class DynamicRebalance:
    def rebalance(self):
        cash = self.portfolio.cash()
        positions = self.portfolio.positions()
""",
    # 8. Đóng toàn bộ vị thế close_all_positions
    """
class PanicGuard:
    def on_drop(self, drop_pct):
        if drop_pct > 0.1:
            self.close_all_positions()
""",
    # 9. Vòng lặp tính toán tuỳ ý (for / while)
    """
class CustomMatrixOptimizer:
    def compute(self, data):
        weights = []
        for i in range(10):
            weights.append(i * 0.1)
""",
    # 10. Callback hủy lệnh on_order_canceled
    """
class CancelHandler:
    def on_order_canceled(self, event):
        self.re_queue()
""",
]


@pytest.mark.parametrize("idx,code", list(enumerate(DSL_SAMPLES)))
def test_classify_10_dsl_samples(idx, code):
    res = classify(code)
    assert res["engine"] == "dsl", f"Mẫu DSL #{idx+1} bị nhận nhầm thành {res['engine']}"
    assert "khớp hợp đồng Nora DSL" in res["reasons"]


@pytest.mark.parametrize("idx,code", list(enumerate(NATIVE_SAMPLES)))
def test_classify_10_native_samples(idx, code):
    res = classify(code)
    assert res["engine"] == "native", f"Mẫu Native #{idx+1} bị nhận nhầm thành {res['engine']}"
    assert len(res["reasons"]) > 0


# ─── 3 CA BIÊN ───────────────────────────────────────────────────────────────

def test_edge_case_1_dsl_with_helper():
    """DSL có hàm helper toán học bên ngoài."""
    code = """
def calc_weight(x):
    return x * 0.5

class DualEma(SimpleAlgorithm):
    def __algorithm__(self):
        self.set_positions(self.data.close > self.data.open, position=calc_weight(1.0))
"""
    # Không có dấu hiệu sự kiện native -> DSL
    res = classify(code)
    assert res["engine"] == "dsl"


def test_edge_case_2_native_banned_import():
    """Native kế thừa Strategy nhưng vi phạm sandbox (import os)."""
    code = """
import os
from nautilus_trader.trading.strategy import Strategy

class BadStrategy(Strategy):
    pass
"""
    # Phân loại ra native
    res = classify(code)
    assert res["engine"] == "native"
    # Nhưng khi compile -> sandbox chặn ngay lập tức
    with pytest.raises(DslError) as exc_info:
        compile_code(code)
    assert "Cấm import 'os'" in str(exc_info.value)


def test_edge_case_3_syntax_error():
    """Mã nguồn cú pháp hỏng."""
    code = "def syntax_error( broken: : :"
    res = classify(code)
    assert res["engine"] == "dsl"
    assert "lỗi cú pháp" in res["reasons"][0]
