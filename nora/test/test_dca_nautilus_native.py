"""Kiểm thử chiến lược DCA Native (Dollar Cost Averaging / Scaling in) trên Nautilus Trader.

Mục tiêu thử nghiệm theo yêu cầu của A Sơn:
- Độc lập 100%, không can thiệp hay sửa đổi core hệ thống.
- Chạy với đúng 1 cặp tài sản: BTC (BTC-USDT-SWAP).
- Đánh giá khả năng của Nautilus Trader trong việc:
  1. Vào lệnh ban đầu khi RSI quá bán (< 30).
  2. Tự động nhồi thêm các tầng lệnh DCA khi giá đi ngược xu hướng.
  3. Nautilus tự động tính toán lại giá vốn trung bình (avg_px_open) sau mỗi tầng.
  4. Chốt lời hoặc cắt lỗ theo toàn bộ rổ vị thế từ giá vốn trung bình mới.
"""
import os
import pytest
from decimal import Decimal

from nautilus_trader.trading.strategy import Strategy, StrategyConfig
from nautilus_trader.indicators import RelativeStrengthIndex
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.data import Bar

from backend.alpha.compile import compile_code
from backend.nautilus.backtest import run_native
from backend.jobs.tasks import run_custom


DCA_NATIVE_CODE = '''
from nautilus_trader.trading.strategy import Strategy, StrategyConfig
from nautilus_trader.indicators import RelativeStrengthIndex
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.data import Bar

class DcaNautilusStrategy(Strategy):
    """Chiến lược DCA Native trên Nautilus Trader (1 cặp BTC)."""
    timeframe = "1h"
    symbols = ["BTC"]

    def __init__(
        self,
        config: StrategyConfig,
        instrument=None,
        bar_type=None,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        dca_step_pct: float = 0.015,       # Giảm 1.5% so với lần trước thì nhồi tầng
        max_layers: int = 3,               # Tối đa 3 tầng nhồi (tổng 4 lệnh)
        size_multiplier: float = 1.2,      # Nhân 1.2x khối lượng cho mỗi tầng sau
        take_profit_pct: float = 0.015,    # Chốt lời 1.5% từ giá vốn trung bình
        stop_loss_pct: float = 0.05,       # Cắt lỗ 5.0% từ giá vốn trung bình
        base_qty: float = 0.01,            # Khối lượng lệnh đầu (0.01 BTC)
    ):
        super().__init__(config)
        self.instrument = instrument
        self.bar_type = bar_type
        self.rsi_period = int(rsi_period)
        self.rsi_oversold = float(rsi_oversold)
        self.dca_step_pct = float(dca_step_pct)
        self.max_layers = int(max_layers)
        self.size_multiplier = float(size_multiplier)
        self.take_profit_pct = float(take_profit_pct)
        self.stop_loss_pct = float(stop_loss_pct)
        self.base_qty = float(base_qty)

        self.rsi = RelativeStrengthIndex(self.rsi_period)
        self.layer = 0
        self.last_fill_px = 0.0
        self.total_fills = 0
        self.dca_layer_fills = 0

    def on_start(self):
        self.subscribe_bars(self.bar_type)

    def on_bar(self, bar: Bar):
        # 1. Cập nhật chỉ báo RSI
        self.rsi.handle_bar(bar)
        if not self.rsi.initialized:
            return

        # Kiểm tra chống spam lệnh / chống lag: nếu đang có lệnh mở chưa khớp thì bỏ qua
        if len(self.cache.orders_open(instrument_id=self.instrument.id)) > 0:
            return

        current_px = float(bar.close)
        positions = self.cache.positions_open(instrument_id=self.instrument.id)
        pos = positions[0] if positions else None

        # 2. Chưa có vị thế: Xét tín hiệu bắt đáy vào lệnh ban đầu (Layer 0)
        if pos is None or pos.is_closed:
            self.layer = 0
            self.last_fill_px = 0.0
            if self.rsi.value < self.rsi_oversold:
                qty = self.instrument.make_qty(self.base_qty)
                order = self.order_factory.market(self.instrument.id, OrderSide.BUY, qty)
                self.submit_order(order)
            return

        # 3. Đang có vị thế LONG
        if pos.is_long:
            avg_px = float(pos.avg_px_open)

            # A. Chốt lời từ GIÁ VỐN TRUNG BÌNH (avg_px)
            if current_px >= avg_px * (1.0 + self.take_profit_pct):
                self.close_position(pos)
                return

            # B. Cắt lỗ từ GIÁ VỐN TRUNG BÌNH
            if current_px <= avg_px * (1.0 - self.stop_loss_pct):
                self.close_position(pos)
                return

            # C. Điều kiện NHỒI TẦNG DCA:
            ref_px = self.last_fill_px if self.last_fill_px > 0 else avg_px
            if current_px <= ref_px * (1.0 - self.dca_step_pct) and self.layer < self.max_layers:
                next_qty_val = round(self.base_qty * (self.size_multiplier ** (self.layer + 1)), 4)
                qty = self.instrument.make_qty(next_qty_val)
                order = self.order_factory.market(self.instrument.id, OrderSide.BUY, qty)
                self.submit_order(order)

    def on_order_filled(self, event):
        self.total_fills += 1
        if event.order_side == OrderSide.BUY:
            self.last_fill_px = float(event.last_px)
            self.layer += 1
            if self.layer > 1:
                self.dca_layer_fills += 1

    def on_position_closed(self, event):
        self.layer = 0
        self.last_fill_px = 0.0
'''


def test_dca_strategy_compilation():
    """Kiểm tra biên dịch class DcaNautilusStrategy sang Native Strategy."""
    prog = compile_code(DCA_NATIVE_CODE)
    assert getattr(prog, "is_native", False) is True
    assert prog.name == "DcaNautilusStrategy"
    assert prog.timeframe == "1h"
    assert prog.symbols == ["BTC"]


def test_dca_native_runner_execution_on_btc():
    """Chạy thực nghiệm chiến lược DCA Native trên 1 cặp BTC bằng run_native."""
    prog = compile_code(DCA_NATIVE_CODE)
    start_ms = 1704067200000  # 2024-01-01
    end_ms = start_ms + 3600000 * 24 * 60  # 60 ngày dữ liệu 1h

    res = run_native(prog.strategy_cls, prog.symbols, start_ms, end_ms, 10_000.0, "1h")

    # Kiểm tra kết quả tổng quan
    assert "positions" in res
    assert "orders" in res
    assert "equity_curve" in res
    assert res["final_equity"] > 0

    # Kiểm tra xem có chu kỳ vị thế nào được mở và đóng
    positions = res["positions"]
    orders = res["orders"]
    print(f"\n[DCA Test] Tổng số vị thế: {len(positions)}, Tổng số lệnh khớp: {len(orders)}")
    print(f"[DCA Test] Vốn ban đầu: 10,000 USDT -> Vốn cuối: {res['final_equity']:.2f} USDT")

    if positions:
        multi_layer_positions = [p for p in positions if getattr(p, "layers", 1) > 1 or getattr(p, "qty", 0) > 0.01]
        print(f"[DCA Test] Số vị thế có nhồi tầng (scaling-in): {len(multi_layer_positions)}")
        for idx, pos in enumerate(positions[:5]):
            print(f"  Pos #{idx+1}: Qty={pos.qty:.4f}, EnterPrice={pos.enter_price:.2f}, "
                  f"ClosePrice={pos.close_price:.2f}, Status={pos.status}, PnL={pos.real_pnl:.2f} USDT")


def test_dca_run_custom_end_to_end(monkeypatch):
    """Kiểm tra tích hợp hoàn chỉnh luồng API run_custom phục vụ giao diện."""
    monkeypatch.setenv("NORA_ALLOW_UNLIMITED", "1")
    monkeypatch.delenv("NORA_LOCAL_DATA_ROOT", raising=False)
    monkeypatch.setenv("NORA_DATA_ROOT", "/home/vmc03/norabt/nora/data")

    params = {
        "code": DCA_NATIVE_CODE,
        "symbols": ["BTC"],
        "start": "2024-01-01",
        "end": "2024-01-15",
        "initial_capital": 10000.0,
        "train_ratio": 0.7,
    }
    out = run_custom(params)
    assert out is not None
    assert "metrics" in out
    assert "trades" in out
    assert "series" in out
    assert out["final_equity"] > 0
    print(f"\n[DCA API End-to-End] Return: {out['metrics'].get('return_pct', 0):.2f}%, WinRate: {out['metrics'].get('win_rate', 0):.1f}%")
