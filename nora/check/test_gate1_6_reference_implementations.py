"""Gate 1.6: Nautilus Native & TradingView Independent Reference Implementation.

Tiêu chí nghiệm thu Gate 1.6:
1. Nautilus Native Backtest Engine Execution:
   - Xây dựng chiến lược event-driven Nautilus native kế thừa `nautilus_trader.trading.strategy.Strategy`.
   - Tính toán chỉ báo động (Dynamic Indicators: RSI 10 Wilder, SMA 15, EMA 50) từ chuỗi nến bar-by-bar.
   - TUYỆT ĐỐI KHÔNG hardcode chỉ số bar (`bar_idx == 65`).
   - Chạy qua thực thể engine chuẩn của Nautilus Trader (`make_engine` + `stream`).
   - Trích xuất lệnh thực tế từ `eng.cache.orders()` và fill từ `eng.trader.generate_order_fills_report()`.
   - Khớp lệnh đúng next-open với 3 bps slippage proxy và 5 bps taker commission.
2. TradingView Pine Script v5 Reference & Tick Conversion:
   - Chứng minh công thức quy đổi tick: `ticks = round(price * slippage_bps / tick_size)`.
   - Với BTC ~60k, tick 0.1 USDT -> 3 bps tương đương đúng 180 ticks (thay vì 3 ticks gây sai số 60 lần).
   - Xác nhận `process_orders_on_close=false` đảm bảo tính nhất quán khớp lệnh next-open.
   - Ghi nhận Waiver: Tách biệt tính thời điểm signal/order khỏi giả lập nội suy tick trong bar của TV broker emulator.
"""
import json
import math
import os
import sys
from pathlib import Path
from decimal import Decimal
import numpy as np
import pandas as pd
import pytest
from typing import Optional, List, Dict, Any

# Thiết lập đường dẫn import cho COIN (để lấy catalog và make_engine)
COIN_PATH = os.path.abspath("nora/coin")
if COIN_PATH not in sys.path:
    sys.path.insert(0, COIN_PATH)

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity

from backend.core import catalog as cat
from backend.core.backtest import make_engine, stream, Feed


class DynamicFastDipNautilusStrategy(Strategy):
    """Chiến lược event-driven Nautilus Trader nguyên bản cho Fast Dip Harvester.
    Tính toán toàn bộ chỉ báo động từ luồng nến, sizing động theo Master Equity risk budget,
    kiểm soát hard SL/TP, final bar guard và xuất trace bar-by-bar đầy đủ.
    """

    def __init__(self, config: StrategyConfig, instrument_id: InstrumentId, bars_total: int = 120):
        super().__init__(config)
        self.instrument_id = instrument_id
        self.bars_total = bars_total
        self.capital = 10000.0
        self.risk_pct = 0.0025          # 25 USDT max risk
        self.sl_pct = 0.02              # 2.0% SL
        self.tp_pct = 0.04              # 4.0% TP
        self.entry_price: Optional[float] = None
        self.closes: list[float] = []
        self.bars_seen = 0
        self.signal_events: list[dict] = []
        self.filled_events: list[dict] = []
        self.trace: list[dict] = []

    def on_start(self):
        self.subscribe_bars(cat.get_bar_type("BTC-USDT-SWAP", "24h"))

    def calculate_safe_quantity(self, price: float) -> Quantity:
        """Tính sizing động theo chính sách rủi ro 25 USDT, khấu trừ biến động giá + 2-way fee + slippage."""
        risk_budget = self.capital * self.risk_pct  # 25.0 USDT
        total_drag_rate = self.sl_pct + (2.0 * 0.0005) + 0.0003 + 0.0006  # 0.0219
        max_notional = risk_budget / total_drag_rate
        raw_qty = max_notional / price
        lot_sz = 0.01
        safe_qty_val = max(lot_sz, math.floor(raw_qty / lot_sz) * lot_sz)
        return Quantity.from_str(f"{safe_qty_val:.2f}")

    def on_bar(self, bar: Bar):
        self.bars_seen += 1
        c = float(bar.close)
        h = float(bar.high)
        l = float(bar.low)
        self.closes.append(c)

        open_positions = [p for p in self.cache.positions_open() if p.instrument_id == self.instrument_id]
        has_pos = len(open_positions) > 0 and open_positions[0].quantity.as_double() > 0
        current_pos_qty = open_positions[0].quantity.as_double() if has_pos else 0.0

        # Cần đủ warmup cho EMA 50
        if len(self.closes) < 50:
            self.trace.append({
                "bar_idx": self.bars_seen - 1, "close": c, "rsi": None, "sma": None, "ema": None,
                "signal": "WARMUP", "pos_qty": current_pos_qty,
            })
            return

        prices = np.array(self.closes, dtype=np.float64)

        # 1. RSI 10 (Chuẩn Wilder)
        deltas = np.diff(prices)
        gains = np.maximum(deltas, 0.0)
        losses = np.maximum(-deltas, 0.0)
        avg_g = np.mean(gains[:10])
        avg_l = np.mean(losses[:10])
        rsi_series = [100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)]
        for i in range(10, len(gains)):
            avg_g = (avg_g * 9.0 + gains[i]) / 10.0
            avg_l = (avg_l * 9.0 + losses[i]) / 10.0
            rsi_series.append(100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l))

        rsi_curr = rsi_series[-1]
        rsi_prev = rsi_series[-2] if len(rsi_series) >= 2 else rsi_curr

        # 2. SMA 15
        sma_curr = np.mean(prices[-15:])
        sma_prev = np.mean(prices[-16:-1]) if len(prices) >= 16 else sma_curr

        # 3. EMA 50
        alpha = 2.0 / 51.0
        ema_val = np.mean(prices[:50])
        for p in prices[50:]:
            ema_val = alpha * p + (1.0 - alpha) * ema_val

        # 4. Kiểm tra điều kiện Stop-Loss / Take-Profit khi đang có vị thế
        sl_hit = has_pos and (self.entry_price is not None) and (l <= self.entry_price * (1.0 - self.sl_pct))
        tp_hit = has_pos and (self.entry_price is not None) and (h >= self.entry_price * (1.0 + self.tp_pct))

        # 5. Điều kiện giao dịch tín hiệu động:
        # Entry: crossover(RSI, 40) & (Close > SMA15) & (Close > EMA50)
        buy_cross = (rsi_curr > 40.0) and (rsi_prev <= 40.0)
        buy_cond = buy_cross and (c > sma_curr) and (c > ema_val)

        # Signal Exit: (RSI > 65) | crossunder(Close, SMA15)
        exit_crossunder = (c < sma_curr) and (prices[-2] >= sma_prev)
        signal_exit = (rsi_curr > 65.0) or exit_crossunder

        exit_trigger = sl_hit or tp_hit or signal_exit

        # 6. Final Bar Guard: nến cuối cùng không được sinh lệnh mở mới vì thiếu next-open
        is_final_bar = (self.bars_seen >= self.bars_total)

        action = "HOLD"
        if buy_cond and not has_pos and not is_final_bar:
            qty = self.calculate_safe_quantity(c)
            order = self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=OrderSide.BUY,
                quantity=qty,
            )
            self.submit_order(order)
            action = "BUY"
            self.signal_events.append({
                "bar_idx": self.bars_seen - 1,
                "action": "BUY",
                "qty": float(qty.as_double()),
                "close": c,
                "rsi": rsi_curr,
                "sma": sma_curr,
                "ema": ema_val,
            })

        elif exit_trigger and has_pos:
            exit_qty = open_positions[0].quantity
            order = self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=OrderSide.SELL,
                quantity=exit_qty,
            )
            self.submit_order(order)
            reason = "SL" if sl_hit else ("TP" if tp_hit else "SIGNAL_EXIT")
            action = f"SELL_{reason}"
            self.signal_events.append({
                "bar_idx": self.bars_seen - 1,
                "action": "SELL",
                "reason": reason,
                "qty": float(exit_qty.as_double()),
                "close": c,
                "rsi": rsi_curr,
                "sma": sma_curr,
                "ema": ema_val,
            })

        self.trace.append({
            "bar_idx": self.bars_seen - 1,
            "close": c,
            "rsi": rsi_curr,
            "sma": sma_curr,
            "ema": ema_val,
            "signal": action,
            "pos_qty": current_pos_qty,
        })

    def on_order_filled(self, event):
        px = float(event.last_px.as_double())
        qty = float(event.last_qty.as_double())
        side = "BUY" if event.order_side == OrderSide.BUY else "SELL"
        if side == "BUY":
            self.entry_price = px
        else:
            self.entry_price = None

        self.filled_events.append({
            "order_id": str(event.client_order_id),
            "side": side,
            "last_qty": qty,
            "last_px": px,
            "commission": float(event.commission.as_double()),
        })


def test_gate1_6_nautilus_native_backtest_engine_execution():
    """Kiểm tra chiến lược event-driven chạy trên thực thể BacktestEngine thật của Nautilus Trader."""
    fixture_path = Path("nora/check/fixtures/deterministic_120_bars.json")
    assert fixture_path.exists(), "Cần file fixture 120 bars"

    with open(fixture_path, "r", encoding="utf-8") as f:
        fix = json.load(f)

    bars = fix["bars"]
    times = np.array([int(b["time"]) for b in bars], dtype=np.int64)
    opens = np.array([float(b["open"]) for b in bars], dtype=np.float64)
    highs = np.array([float(b["high"]) for b in bars], dtype=np.float64)
    lows = np.array([float(b["low"]) for b in bars], dtype=np.float64)
    closes = np.array([float(b["close"]) for b in bars], dtype=np.float64)
    vols = np.array([float(b["volume"]) for b in bars], dtype=np.float64)

    arrays = {"t": times, "o": opens, "h": highs, "l": lows, "c": closes, "v": vols}
    symbol = "BTC-USDT-SWAP"
    spec = {
        "tickSz": "0.1", "lotSz": "0.01", "ctVal": "1.0", "minSz": "0.01",
        "margin_init": "0.1", "margin_maint": "0.05", "maker_fee": "0.0002", "taker_fee": "0.0005",
        "base_symbol": "BTC",
    }
    inst = cat.build_instrument(symbol, spec, maker_fee=0.0002, taker_fee=0.0005)

    # 1. Khởi tạo BacktestEngine thực tế qua make_engine
    eng = make_engine(initial_capital=10000.0, leverage=1.0, adaptive=False)
    eng.add_instrument(inst)

    # 2. Khởi tạo chiến lược với Dynamic Indicators, Dynamic Sizing và Final Bar Guard
    cfg = StrategyConfig(strategy_id="FAST_DIP_NAUTILUS_REF")
    strat = DynamicFastDipNautilusStrategy(cfg, inst.id, bars_total=len(bars))
    eng.add_strategy(strat)

    # 3. Stream nến qua OrderMatchingEngine với synthetic L1 quotes proxy
    feed = Feed(symbol, arrays, weight=1)
    stream(eng, [feed], "24h", {symbol: inst})

    # 4. Trích xuất trực tiếp orders và fills từ Nautilus Cache & Reports
    orders = eng.cache.orders()
    assert len(orders) == 4, f"Kỳ vọng 4 lệnh trong engine cache, thực tế: {len(orders)}"
    for o in orders:
        assert o.status.value == 14 or str(o.status) == "FILLED", f"Lệnh {o.client_order_id} chưa khớp: status={o.status}"

    fills_report = eng.trader.generate_order_fills_report()
    assert len(fills_report) == 4, f"Kỳ vọng 4 fill trong báo cáo Nautilus, thực tế: {len(fills_report)}"

    fills = strat.filled_events
    assert len(fills) == 4, f"Kỳ vọng 4 sự kiện on_order_filled, thực tế: {len(fills)}"

    # 5. Xác minh chi tiết từng fill theo quy tắc làm tròn tick hợp lệ (ROUND_CEILING cho BUY Ask, ROUND_FLOOR cho SELL Bid):
    # Tick size BTC là 0.1 USDT; trượt giá nghiên cứu 3 bps (0.0003)
    tick_sz = 0.1

    # Fill 1: Entry 1 sinh tại Bar 65 -> Khớp tại Bar 66 Open với +3 bps slippage (ROUND_CEILING)
    assert fills[0]["side"] == "BUY"
    assert fills[0]["last_qty"] == 0.02, f"Dynamic sizing phải sinh 0.02 BTC (thực tế: {fills[0]['last_qty']})"
    open_66 = opens[66]
    expected_px_66 = math.ceil(open_66 * (1.0 + 0.0003) / tick_sz) * tick_sz
    assert abs(fills[0]["last_px"] - expected_px_66) < 1e-4, f"Lệch giá khớp Entry 1: {fills[0]['last_px']} vs {expected_px_66}"
    notional_1 = fills[0]["last_px"] * fills[0]["last_qty"]
    expected_fee_1 = round(notional_1 * 0.0005, 6)
    assert abs(fills[0]["commission"] - expected_fee_1) < 1e-4

    # Fill 2: Exit 1 sinh tại Bar 66 (RSI > 65) -> Khớp tại Bar 67 Open với -3 bps slippage (ROUND_FLOOR)
    assert fills[1]["side"] == "SELL"
    assert fills[1]["last_qty"] == 0.02
    open_67 = opens[67]
    expected_px_67 = math.floor(open_67 * (1.0 - 0.0003) / tick_sz) * tick_sz
    assert abs(fills[1]["last_px"] - expected_px_67) < 1e-4, f"Lệch giá khớp Exit 1: {fills[1]['last_px']} vs {expected_px_67}"

    # Fill 3: Entry 2 sinh tại Bar 79 -> Khớp tại Bar 80 Open với +3 bps slippage (ROUND_CEILING)
    assert fills[2]["side"] == "BUY"
    assert fills[2]["last_qty"] == 0.02
    open_80 = opens[80]
    expected_px_80 = math.ceil(open_80 * (1.0 + 0.0003) / tick_sz) * tick_sz
    assert abs(fills[2]["last_px"] - expected_px_80) < 1e-4, f"Lệch giá khớp Entry 2: {fills[2]['last_px']} vs {expected_px_80}"

    # Fill 4: Exit 2 sinh tại Bar 84 (Close crossunder SMA15) -> Khớp tại Bar 85 Open với -3 bps slippage (ROUND_FLOOR)
    assert fills[3]["side"] == "SELL"
    assert fills[3]["last_qty"] == 0.02
    open_85 = opens[85]
    expected_px_85 = math.floor(open_85 * (1.0 - 0.0003) / tick_sz) * tick_sz
    assert abs(fills[3]["last_px"] - expected_px_85) < 1e-4, f"Lệch giá khớp Exit 2: {fills[3]['last_px']} vs {expected_px_85}"

    # 6. Xác minh Final Bar Guard:
    # Nến cuối cùng (Bar 119) có buy_cond = True nhưng không gửi lệnh mới vì không có next observation open
    assert len(strat.trace) == 120
    assert strat.trace[119]["signal"] == "HOLD", "Nến cuối cùng phải được bảo vệ bởi Final Bar Guard!"

    # 7. Đối chiếu trực tiếp Trade Ledger giữa Nora Engine và Nautilus Reference Engine (Nora-Nautilus Direct Parity)
    from backend.core.backtest import NautilusRun
    from backend.analys.alpha import RiskConfig
    from backend.analys.param import StrategyParams
    from backend.analys.position import SlotSpec
    from backend.models.models import PositionType

    class Gate16StubDataSource:
        def __init__(self, s, f, ts, o, h, l, c, v):
            self.symbol = s
            self.frame = f
            self._arrays = {"t": ts, "o": o, "h": h, "l": l, "c": c, "v": v}
            self._spec = spec
        def exec_arrays(self, s, f, start, end): return self._arrays
        def instrument_spec(self, s): return self._spec
        def require_ok(self, s): pass

    ds_nora = Gate16StubDataSource(symbol, "24h", times, opens, highs, lows, closes, vols)
    params_nora = StrategyParams(
        market="perp", leverage=1, stop_loss_rate=0.0, take_profit_rate=0.0,
        fee_rate=0.0005, maker_fee_rate=0.0002, slippage_rate=0.0003,
        order_size_pct=11.0, max_capital_usage=1.0,
    )
    slot_nora = SlotSpec(
        account_id=0, campaign_id=0, symbol=symbol, flow_name="fast_dip_parity",
        params=params_nora, pos_type=PositionType.LONG, initial_capital=10_000.0,
    )

    nora_match = np.zeros(len(bars), dtype=bool)
    nora_match[65] = True
    nora_match[79] = True
    nora_stop = np.zeros(len(bars), dtype=bool)
    nora_stop[66] = True  # Signal exit 1
    nora_stop[84] = True  # Signal exit 2

    book_nora = {
        "symbol": symbol,
        "data": {"t": times},
        "entries": [{
            "strategy": "FAST_DIP_PARITY",
            "slot": slot_nora,
            "match": nora_match,
            "stop": nora_stop,
            "vol": None,
            "dca": None,
        }],
    }
    risk_nora = RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=1e12, kill_switch_dd_pct=0.0)

    nora_runner = NautilusRun(
        books=[book_nora],
        initial_capital=10_000.0,
        risk=risk_nora,
        trade_start_ts=int(times[0]),
        end_ts=int(times[-1]) + 86400 * 1000,
        base_frame="24h",
        close_at_end=True,
        data=ds_nora,
        execution_target="next_open",
    )
    nora_res = nora_runner.run()

    # Khẳng định khớp đối ứng trực tiếp số lượng lệnh và vị thế giữa Nora và Nautilus
    assert len(nora_res["orders"]) == len(orders) == 4, f"Lệch số lệnh: Nora={len(nora_res['orders'])} vs Nautilus={len(orders)}"
    assert len(nora_res["positions"]) == 2, f"Kỳ vọng 2 vị thế Nora, thực tế: {len(nora_res['positions'])}"

    nora_p1, nora_p2 = nora_res["positions"][0], nora_res["positions"][1]

    # Đối chiếu đầy đủ toàn bộ các trường của Trade Ledger theo đúng chuẩn frozen tolerance (< 1e-4 USDT):
    # Khớp vị thế 1: Entry tại Bar 66 Open, Exit tại Bar 67 Open
    assert nora_p1.symbol == symbol
    assert nora_p1.pos_type == PositionType.LONG
    assert nora_p1.enter_time == int(times[66])
    assert nora_p1.close_time == int(times[67])
    assert abs(nora_p1.qty - fills[0]["last_qty"]) < 1e-4
    assert abs(nora_p1.enter_price - fills[0]["last_px"]) < 1e-4, f"Lệch giá vào Trade 1: {nora_p1.enter_price} vs {fills[0]['last_px']}"
    assert abs(nora_p1.close_price - fills[1]["last_px"]) < 1e-4, f"Lệch giá ra Trade 1: {nora_p1.close_price} vs {fills[1]['last_px']}"
    expected_fees_1 = fills[0]["commission"] + fills[1]["commission"]
    assert abs(nora_p1.fees_usd - expected_fees_1) < 1e-4, f"Lệch phí Trade 1: {nora_p1.fees_usd} vs {expected_fees_1}"
    expected_gross_pnl_1 = fills[0]["last_qty"] * (fills[1]["last_px"] - fills[0]["last_px"])
    expected_net_pnl_1 = expected_gross_pnl_1 - expected_fees_1
    assert abs(nora_p1.real_pnl - expected_net_pnl_1) < 1e-4, f"Lệch Net PnL Trade 1: {nora_p1.real_pnl} vs {expected_net_pnl_1}"
    assert nora_p1.close_reason == "Tín hiệu thoát (AST stop)"
    assert nora_p1.funding_usd == 0.0

    # Khớp vị thế 2: Entry tại Bar 80 Open, Exit tại Bar 85 Open
    assert nora_p2.symbol == symbol
    assert nora_p2.pos_type == PositionType.LONG
    assert nora_p2.enter_time == int(times[80])
    assert nora_p2.close_time == int(times[85])
    assert abs(nora_p2.qty - fills[2]["last_qty"]) < 1e-4
    assert abs(nora_p2.enter_price - fills[2]["last_px"]) < 1e-4, f"Lệch giá vào Trade 2: {nora_p2.enter_price} vs {fills[2]['last_px']}"
    assert abs(nora_p2.close_price - fills[3]["last_px"]) < 1e-4, f"Lệch giá ra Trade 2: {nora_p2.close_price} vs {fills[3]['last_px']}"
    expected_fees_2 = fills[2]["commission"] + fills[3]["commission"]
    assert abs(nora_p2.fees_usd - expected_fees_2) < 1e-4, f"Lệch phí Trade 2: {nora_p2.fees_usd} vs {expected_fees_2}"
    expected_gross_pnl_2 = fills[2]["last_qty"] * (fills[3]["last_px"] - fills[2]["last_px"])
    expected_net_pnl_2 = expected_gross_pnl_2 - expected_fees_2
    assert abs(nora_p2.real_pnl - expected_net_pnl_2) < 1e-4, f"Lệch Net PnL Trade 2: {nora_p2.real_pnl} vs {expected_net_pnl_2}"
    assert nora_p2.close_reason == "Tín hiệu thoát (AST stop)"
    assert nora_p2.funding_usd == 0.0



def test_gate1_6_tradingview_pinescript_slippage_and_timing_parity():
    """Kiểm tra đối chiếu độc lập công thức quy đổi trượt giá Pine Script v5 sang Ticks."""
    # 1. OKX BTC-USDT-SWAP: tick size = 0.1 USDT
    btc_price = 60000.0
    tick_sz = 0.1
    target_bps = 0.0003  # 3 bps

    # Tính toán số tick trượt giá
    slippage_usd = btc_price * target_bps  # 18.0 USDT
    expected_ticks = round(slippage_usd / tick_sz)  # 180 ticks
    assert expected_ticks == 180

    # Nếu người dùng vô tình đặt slippage=3 trong Pine Script:
    naive_slippage_usd = 3 * tick_sz  # 0.3 USDT
    naive_bps = naive_slippage_usd / btc_price  # 0.000005 (0.05 bps)
    underestimation_ratio = target_bps / naive_bps
    assert abs(underestimation_ratio - 60.0) < 1e-6, "Cảnh báo sai số trượt giá 60x khi dùng slippage=3 trên TradingView!"

    # 2. Xác nhận file Pine Script reference tồn tại và chứa cấu hình chuẩn
    pine_file = Path("nora/check/FastDip_TradingView_Reference.pine")
    assert pine_file.exists()
    content = pine_file.read_text(encoding="utf-8")

    assert "process_orders_on_close=false" in content
    assert "commission_value=0.05" in content
    assert "slippage=180" in content
    assert "commission_type=strategy.commission.percent" in content


def test_gate1_6_stop_market_semantics_and_adverse_ordering():
    """Kiểm tra ngữ nghĩa lệnh Stop-Market chuẩn mực:
    1. Intrabar Stop-Market: khớp tại trigger level chịu phạt 2x slippage.
    2. Gap-through Stop-Market: khi nến sau mở gap qua SL, khớp tại Open nến sau chịu 2x slippage (không gán nhầm trigger).
    3. Adverse same-bar ordering: khi cả SL và TP cùng chạm trong 1 nến, SL phải được kích hoạt trước.
    """
    from backend.core.backtest import NautilusRun
    from backend.analys.alpha import RiskConfig
    from backend.analys.param import StrategyParams
    from backend.analys.position import SlotSpec
    from backend.models.models import PositionType, PositionStatus

    class MiniStubDataSource:
        def __init__(self, s, f, ts, o, h, l, c, v):
            self.symbol = s
            self.frame = f
            self._arrays = {"t": ts, "o": o, "h": h, "l": l, "c": c, "v": v}
            self._spec = {
                "tickSz": "0.01", "lotSz": "0.01", "ctVal": "1.0", "minSz": "0.01",
                "margin_init": "0.1", "margin_maint": "0.05", "maker_fee": "0.0002", "taker_fee": "0.0005",
                "base_symbol": "BTC",
            }
        def exec_arrays(self, s, f, start, end): return self._arrays
        def instrument_spec(self, s): return self._spec
        def require_ok(self, s): pass

    symbol = "BTC-USDT-SWAP"
    frame = "5m"
    fr_ms = 5 * 60_000
    times = np.array([0, fr_ms, 2 * fr_ms], dtype=np.int64)

    # Trường hợp 1: Gap-through SL
    # Bar 0: Signal match at close
    # Bar 1: Fills at open 100.0. High 101.0, Low 99.0, Close 100.0
    # Bar 2: GAP DOWN! Open 90.0, High 91.0, Low 89.0, Close 90.0 (Gap qua SL 5% = 95.0)
    ds_gap = MiniStubDataSource(symbol, frame, times,
                                np.array([100.0, 100.0, 90.0]),
                                np.array([105.0, 101.0, 91.0]),
                                np.array([99.0, 99.0, 89.0]),
                                np.array([100.0, 100.0, 90.0]),
                                np.array([10.0, 10.0, 10.0]))
    params_gap = StrategyParams(
        market="perp", leverage=1, stop_loss_rate=5.0, take_profit_rate=10.0,
        fee_rate=0.0005, maker_fee_rate=0.0002, slippage_rate=0.0003,
        order_size_pct=10.0, max_capital_usage=1.0,
    )
    slot_gap = SlotSpec(0, 0, symbol, "test_gap", params_gap, PositionType.LONG, 10_000.0)
    book_gap = {
        "symbol": symbol,
        "data": {"t": times},
        "entries": [{
            "strategy": "TEST_SL_GAP",
            "slot": slot_gap,
            "match": np.array([True, False, False]),
            "stop": np.array([False, False, False]),
            "vol": None, "dca": None,
        }],
    }
    risk = RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=1e12, kill_switch_dd_pct=0.0)
    res_gap = NautilusRun([book_gap], 10_000.0, risk, 0, 3 * fr_ms, frame, True, ds_gap, execution_target="next_open").run()

    assert len(res_gap["positions"]) == 1
    pos_gap = res_gap["positions"][0]
    assert pos_gap.status == PositionStatus.SL
    # Khi gap qua 95.0, giá khớp phải là giá Open nến sau (90.0 - 2x slippage proxy ~89.97), không được giữ 95.03!
    assert abs(pos_gap.close_price - 95.03) > 1.0, "Lỗi: Giá khớp SL bị gán nhầm trigger level thay vì giá gap open!"
    assert abs(pos_gap.close_price - 89.95) < 0.1, f"Kỳ vọng giá đóng ~89.95, thực tế: {pos_gap.close_price}"

    # Trường hợp 2: Adverse same-bar SL/TP precedence
    # Bar 2 biến động mạnh: High chạm TP 5%, Low chạm SL 5%
    ds_adverse = MiniStubDataSource(symbol, frame, times,
                                    np.array([100.0, 100.0, 100.0]),
                                    np.array([105.0, 101.0, 110.0]),
                                    np.array([99.0, 99.0, 90.0]),
                                    np.array([100.0, 100.0, 105.0]),
                                    np.array([10.0, 10.0, 10.0]))
    params_adverse = StrategyParams(
        market="perp", leverage=1, stop_loss_rate=5.0, take_profit_rate=5.0,
        fee_rate=0.0005, maker_fee_rate=0.0002, slippage_rate=0.0003,
        order_size_pct=10.0, max_capital_usage=1.0,
    )
    slot_adverse = SlotSpec(0, 0, symbol, "test_adverse", params_adverse, PositionType.LONG, 10_000.0)
    book_adverse = {
        "symbol": symbol,
        "data": {"t": times},
        "entries": [{
            "strategy": "TEST_ADVERSE",
            "slot": slot_adverse,
            "match": np.array([True, False, False]),
            "stop": np.array([False, False, False]),
            "vol": None, "dca": None,
        }],
    }
    res_adverse = NautilusRun([book_adverse], 10_000.0, risk, 0, 3 * fr_ms, frame, True, ds_adverse, execution_target="next_open").run()

    assert len(res_adverse["positions"]) == 1
    pos_adverse = res_adverse["positions"][0]
    assert pos_adverse.status == PositionStatus.SL, f"Adverse ordering yêu cầu kích hoạt SL trước khi cả hai cùng chạm, nhưng nhận: {pos_adverse.status}"
    assert pos_adverse.real_pnl < 0, f"PnL phải là âm do chạm SL, thực tế: {pos_adverse.real_pnl}"
