"""REFERENCE ENGINE (test code, NOT shipped): bản chụp ĐÓNG BĂNG của vòng lặp Python từng phút (execution.PositionTracker +
BacktestEngine.run + PortfolioEngine.run) trước khi thay bằng kernel numba (backend/core/backtest/kernel.py).

Dùng duy nhất để đối chiếu BIT-IDENTICAL: test/test_kernel_parity.py so kernel với bản này (cùng golden snapshot).
KHÔNG sửa logic ở đây — nếu ngữ nghĩa engine đổi có chủ đích thì cập nhật bản này cùng lúc với snapshot golden.
Sinh ra bằng cách chép nguyên văn execution.py / engine.py:BacktestEngine / portfolio.py:PortfolioEngine rồi đổi tên lớp (Ref*).
"""
import contextlib
import io
import os
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from backend.core.data import shared as shared_data
from backend.core.backtest.engine import BacktestEngine as _ProdEngine
from backend.core.backtest.engine import FRAME_MS, collect_field_refs
from backend.core.backtest.portfolio import _DATA_CACHE, RiskConfig, _strategy_flow
from backend.core.signals import kernels
from backend.core.signals.evaluator import VectorEvaluator, lag_key


import itertools
import time
from backend.core.params.schema import StrategyParams
from backend.core.execute.models import OrderModel, OrderType, PositionModel, PositionStatus, PositionType

# Bộ đếm id toàn cục, tăng dần và không trùng (int(time.time()*1000) trùng khi
# nhiều lệnh mở trong cùng 1 ms). Bắt đầu từ epoch-ms * 1000 để vẫn sắp xếp theo thời gian.
_ID_SEQ = itertools.count(int(time.time() * 1000) * 1000)


def _next_id() -> int:
    return next(_ID_SEQ)


class RefCapitalLedger:
    """Sổ vốn chung của một lần chạy — nguồn sự thật duy nhất cho phân bổ vốn.

    equity   : vốn đã chốt (vốn đầu + Σ lãi/lỗ đã đóng + funding đã trả/nhận).
    reserved : tiền đang bị khoá trong các vị thế mở (ký quỹ + phí vào lệnh đã trả).
    free     : equity × usage − reserved. Mọi lệnh vào / tầng DCA phải giữ chỗ được từ free,
               nên nhiều flow cùng lúc KHÔNG thể dùng quá vốn (lỗi cũ: mỗi flow tự dùng 100%).
    """

    def __init__(self, capital: float, usage: float = 1.0):
        self.initial = float(capital)
        self.equity = float(capital)
        self.reserved = 0.0
        self.usage = max(0.0, min(float(usage), 1.0))
        self.rejected = 0  # số lần vào lệnh/tầng bị từ chối vì không đủ vốn

    def free(self) -> float:
        return self.equity * self.usage - self.reserved

    def reserve(self, amount: float) -> bool:
        if amount <= 0 or amount > self.free() + 1e-9:
            self.rejected += 1
            return False
        self.reserved += amount
        return True

    def release(self, amount: float) -> None:
        self.reserved = max(0.0, self.reserved - amount)

    def settle(self, cash_delta: float) -> None:
        self.equity += cash_delta


class RefPositionTracker:
    """Theo dõi vòng đời vị thế của một flow: Entry -> DCA -> TP / SL / Trailing / Timeout / Liq / Exit."""

    def __init__(
        self,
        account_id: int,
        campaign_id: int,
        symbol: str,
        flow_name: str,
        params: StrategyParams,
        pos_type: PositionType,
        initial_capital: float = 10000.0,
        ledger: Optional[RefCapitalLedger] = None,
    ):
        self.account_id = account_id
        self.campaign_id = campaign_id
        self.symbol = symbol
        self.flow_name = flow_name
        self.params = params
        self.pos_type = pos_type
        self.is_long = pos_type == PositionType.LONG

        self.market = str(getattr(params, "market", "spot") or "spot").lower()
        if self.market not in ("spot", "perp"):
            raise ValueError(f"market phải là 'spot' hoặc 'perp', nhận '{self.market}'")
        if self.market == "spot" and not self.is_long:
            raise ValueError(f"Flow '{flow_name}': thị trường spot không bán khống được — dùng market='perp' cho SHORT.")
        self.leverage = 1.0 if self.market == "spot" else max(1.0, float(params.leverage or 1.0))
        self.mmr = max(0.0, float(getattr(params, "maintenance_margin_rate", 0.005) or 0.0))
        # Phí: taker cho lệnh market (vào ở open, SL, trailing, timeout, tín hiệu thoát);
        #      maker cho lệnh limit (tầng DCA, chốt lời). fee_rate cũ = taker.
        self.fee_rate = max(0.0, float(params.fee_rate or 0.0))
        maker = getattr(params, "maker_fee_rate", None)
        self.maker_fee_rate = self.fee_rate if maker is None else max(0.0, float(maker))
        self.slippage_rate = max(0.0, float(params.slippage_rate or 0.0))
        self.capital = float(initial_capital)
        self.capital_usage = max(0.0, min(float(params.max_capital_usage or 1.0), 1.0))
        self.ledger = ledger if ledger is not None else RefCapitalLedger(self.capital, self.capital_usage)
        self.max_capital = self.capital * self.capital_usage

        # Giá trị gốc của tham số thoát lệnh; mỗi vị thế quy đổi sang % lúc vào lệnh (_apply_exit_unit).
        self.base_sl = max(0.0, float(params.stop_loss_rate or 0.0))
        self.base_tp = max(0.0, float(params.take_profit_rate or 0.0))
        self.base_trail = max(0.0, float(params.trailing_stop or 0.0))
        self.base_trail_act = max(0.0, float(getattr(params, "trailing_activation_pct", 0.0) or 0.0))
        self.timeout_ms = max(0, int(params.timeout or 0)) * 60_000
        self.cooldown_ms = max(0, int(getattr(params, "cooldown", 0) or 0)) * 60_000
        self.last_close_time: Optional[int] = None   # thời điểm đóng vị thế gần nhất (cho cooldown)
        self.dca_rejected = 0       # số tầng DCA bị từ chối vì hết ngân sách vốn (không đổi logic khớp lệnh)
        self.stop_fill = str(getattr(params, "stop_fill", "level") or "level").lower()
        # lệnh limit (tầng DCA, chốt lời) chỉ khớp khi giá đi QUA mức bấy nhiêu % (hàng đợi sổ lệnh); 0 = chạm là khớp
        self.limit_through = max(0.0, float(getattr(params, "limit_through_pct", 0.0) or 0.0)) / 100.0
        if self.stop_fill not in ("level", "extreme"):
            raise ValueError(f"stop_fill phải là 'level' hoặc 'extreme', nhận '{self.stop_fill}'")
        self.exit_unit = str(getattr(params, "exit_unit", "pct") or "pct").lower()
        if self.exit_unit not in ("pct", "atr"):
            raise ValueError(f"exit_unit phải là 'pct' hoặc 'atr', nhận '{self.exit_unit}'")
        self.atr_frame = str(getattr(params, "atr_frame", "1h") or "1h")
        self.atr_period = int(getattr(params, "atr_period", 14) or 14)
        self.sizing = str(getattr(params, "sizing", "margin_pct") or "margin_pct").lower()
        if self.sizing not in ("margin_pct", "risk"):
            raise ValueError(f"sizing phải là 'margin_pct' hoặc 'risk', nhận '{self.sizing}'")
        self.risk_pct = max(0.0, float(getattr(params, "risk_per_trade_pct", 0.5) or 0.0))
        self.max_notional_pct = max(0.0, float(getattr(params, "max_notional_pct", 100.0) or 0.0))
        if self.sizing == "risk" and self.base_sl <= 0:
            raise ValueError(f"Flow '{flow_name}': sizing='risk' cần stop_loss_rate > 0 (rủi ro đo tại SL).")

        layers = max(0, int(getattr(params, "dca_max_layers", 0) or 0))
        step = float(getattr(params, "dca_step_pct", 0.0) or 0.0)
        mult = float(getattr(params, "dca_size_multiplier", 1.0) or 1.0)
        steps = [float(x) for x in (params.dca_steps or [])] or ([step] * layers if step > 0 else [])
        mults = [float(x) for x in (params.dca_multipliers or [])] or [mult] * len(steps)
        if len(mults) < len(steps):
            mults += [mults[-1] if mults else 1.0] * (len(steps) - len(mults))
        if any(s <= 0 for s in steps) or any(m <= 0 for m in mults):
            raise ValueError("Bước DCA và hệ số khối lượng phải > 0")
        self.base_dca_steps = [abs(s) for s in steps]
        self.dca_mults = mults[: len(steps)]
        self.max_leverage = self.leverage
        self.pos_leverage = self.leverage
        self.planned_risk = 0.0
        self.max_new_notional = float("inf")  # trần danh nghĩa cho lệnh sắp mở (do danh mục đặt theo max_gross_exposure)
        self.unit_pct = 0.0
        self.pending_vol = float("nan")
        self.skipped_no_vol = 0     # tín hiệu vào lệnh nhưng chưa có ATR (giai đoạn khởi động)
        self._apply_exit_unit(1.0)
        self.order_size_pct = max(0.0, float(params.order_size_pct or 0.0))

        ast = params.extra.get("ast", {}) if isinstance(params.extra, dict) else {}
        self.match_tree = self._combine_conditions(ast.get("match", []))
        self.stop_tree = self._combine_conditions(ast.get("stop", []))
        self.dca_tree = self._combine_conditions(ast.get("dca", []))
        self.dca_ok = True

        self.position: Optional[PositionModel] = None
        self.orders: List[OrderModel] = []
        self.is_open = False
        self.pending_entry = False
        self.pending_exit = False
        self._reset_state()

    def _apply_exit_unit(self, unit: float) -> None:
        """Quy đổi tham số thoát lệnh sang % cho vị thế sắp mở (unit = 1 với exit_unit='pct', = ATR% với 'atr').
        Đặt lại từ giá trị gốc mỗi vị thế: các tầng DCA bị bỏ vì hết vốn ở vị thế trước không ảnh hưởng vị thế sau."""
        self.sl_pct = self.base_sl * unit
        self.tp_pct = self.base_tp * unit
        self.trail_pct = self.base_trail * unit
        self.trail_activation_pct = self.base_trail_act * unit
        self.dca_steps = [x * unit for x in self.base_dca_steps]

    # ─── Trạng thái ─────────────────────────────────────────────────────────
    def _reset_state(self) -> None:
        self.qty = 0.0
        self.avg = 0.0
        self.margin_used = 0.0
        self.fees_paid = 0.0
        self.layer_count = 0
        self.last_fill = 0.0
        self.next_margin = 0.0
        self.entry_time = 0
        self.peak = 0.0
        self.mae_usd = 0.0
        self.reserved_here = 0.0   # tiền đã giữ chỗ trong ledger cho vị thế này
        self.funding_paid = 0.0    # funding đã trả (+) / nhận (−), đã hạch toán thẳng vào ledger
        self.entry_equity = self.ledger.equity if hasattr(self, "ledger") else 0.0

    @property
    def equity(self) -> float:
        """Vốn đã chốt hiện tại (dùng chung giữa các flow qua RefCapitalLedger)."""
        return self.ledger.equity

    @property
    def avg_entry_price(self) -> float:
        return self.avg

    def unrealized_pnl_usd(self, price: float) -> float:
        if not self.is_open or self.qty <= 0:
            return 0.0
        move = (price - self.avg) if self.is_long else (self.avg - price)
        return self.qty * move - self.fees_paid  # funding đã nằm trong ledger.equity

    def apply_funding(self, rate: float, price: float) -> float:
        """Funding perp: long trả qty·giá·rate khi rate > 0 (short nhận), và ngược lại. Hạch toán ngay."""
        if not self.is_open or self.market != "perp" or self.qty <= 0:
            return 0.0
        payment = self.qty * price * rate * (1.0 if self.is_long else -1.0)
        self.funding_paid += payment
        self.ledger.settle(-payment)
        return payment

    def _liq_price(self) -> Optional[float]:
        if self.market != "perp" or self.qty <= 0:
            return None
        if self.is_long:
            return self.avg * (1.0 - 1.0 / self.pos_leverage + self.mmr)
        return self.avg * (1.0 + 1.0 / self.pos_leverage - self.mmr)

    def _reached(self, level: float, extreme: float) -> bool:
        return extreme <= level if self.is_long else extreme >= level

    def _gap_fill(self, level: float, open_price: float) -> float:
        """Giá khớp khi chạm mức: nếu open đã vượt qua mức (gap) thì khớp ở open."""
        if self.is_long:
            return min(level, open_price)
        return max(level, open_price)

    # ─── Hành động ──────────────────────────────────────────────────────────
    def _add_layer(self, t: int, price: float, margin: float, market_order: bool, reason: str) -> bool:
        fill = price * (1 + self.slippage_rate if self.is_long else 1 - self.slippage_rate) if market_order else price
        notional = margin * self.pos_leverage
        fee = notional * (self.fee_rate if market_order else self.maker_fee_rate)
        if margin <= 0 or fill <= 0 or self.margin_used + margin + self.fees_paid + fee > self.max_capital + 1e-9:
            return False
        if not self.ledger.reserve(margin + fee):
            return False
        self.reserved_here += margin + fee
        qty = notional / fill
        new_qty = self.qty + qty
        self.avg = (self.avg * self.qty + fill * qty) / new_qty
        self.qty = new_qty
        self.margin_used += margin
        self.fees_paid += fee
        self.layer_count += 1
        self.last_fill = fill
        oid = _next_id()
        if self.position is None:
            self.entry_time = t
            self.peak = fill
            self.position = PositionModel(
                result_id=oid, account_id=self.account_id, campaign_id=self.campaign_id, symbol=self.symbol,
                pos_type=self.pos_type, phase=0, enter_time=t, enter_price=fill, status=PositionStatus.OPEN,
                flow=self.flow_name, start_reason=reason, max_price=fill, min_price=fill,
                entry_equity=self.equity, entry_margin_usd=margin, entry_notional_usd=notional, entry_fee_usd=fee,
            )
        self.orders.append(OrderModel(
            order_id=oid, account_id=self.account_id, position_id=self.position.result_id, order_time=t,
            order_type=OrderType.BUY if self.is_long else OrderType.SELL, order_price=fill, qty=qty,
            phase=self.layer_count - 1, fee_usd=fee, liquidity="taker" if market_order else "maker",
        ))
        self.is_open = True
        return True

    def _open(self, t: int, open_price: float) -> None:
        if self.equity <= 0:
            return  # cháy tài khoản: không mở lệnh mới
        unit = 1.0
        if self.exit_unit == "atr":
            unit = self.pending_vol
            if not (unit > 0):  # NaN khi chưa đủ nến khởi động ATR
                self.skipped_no_vol += 1
                return
        self._apply_exit_unit(unit)
        self.unit_pct = unit if self.exit_unit == "atr" else 0.0
        self.entry_equity = self.equity
        self.max_capital = self.equity * self.capital_usage
        budget = min(self.max_capital, self.ledger.free())
        self.pos_leverage = self.max_leverage
        self.planned_risk = 0.0
        if self.sizing == "risk":
            margin = self._risk_margin()
        else:
            margin = self.equity * self.order_size_pct / 100.0
        margin = min(margin, budget / (1.0 + self.pos_leverage * self.fee_rate),
                     self.max_new_notional / self.pos_leverage)
        if self.sizing == "risk" and margin > 0:
            self.planned_risk = min(self.planned_risk, margin * self.pos_leverage * (self.sl_pct / 100.0 + 2.0 * (
                self.fee_rate + self.slippage_rate)) * self._layer_mult_total())
        if margin <= 0:
            self.ledger.rejected += 1  # tín hiệu vào lệnh nhưng không còn vốn trống
            return
        if self._add_layer(t, open_price, margin, market_order=True, reason="Tín hiệu vào lệnh (AST match)"):
            self.next_margin = margin
            self.position.unit_pct = self.unit_pct
            self.position.leverage_used = self.pos_leverage
            self.position.risk_usd = self.planned_risk

    def _layer_mult_total(self) -> float:
        """Tổng khối lượng các tầng (lệnh đầu = 1) theo hệ số DCA."""
        total, m = 1.0, 1.0
        for k in self.dca_mults[: len(self.dca_steps)]:
            m *= k
            total += m
        return total

    def _risk_margin(self) -> float:
        """Khối lượng theo rủi ro: nếu chạm SL (tính cả mọi tầng DCA dự kiến và phí khứ hồi taker + trượt)
        thì mất ~risk_per_trade_pct% vốn. Danh nghĩa bị chặn bởi max_notional_pct% vốn.
        Perp: đòn bẩy thực = min(đòn bẩy tham số, mức để giá thanh lý cách giá vào >= 1,5 × khoảng SL)."""
        sl = self.sl_pct / 100.0
        cost = 2.0 * (self.fee_rate + self.slippage_rate)
        total_mult = self._layer_mult_total()
        notional = self.equity * self.risk_pct / 100.0 / (sl + cost)
        notional = min(notional, self.equity * self.max_notional_pct / 100.0)
        if self.market == "perp":
            safe = int(1.0 / (1.5 * sl + self.mmr)) if sl > 0 else int(self.max_leverage)
            self.pos_leverage = float(max(1, min(int(self.max_leverage), safe)))
        self.planned_risk = notional * (sl + cost)
        return notional / total_mult / self.pos_leverage

    def _close(self, t: int, raw_price: float, status: PositionStatus, reason: str, market_order: bool) -> PositionModel:
        if market_order and status != PositionStatus.LIQ:
            price = raw_price * (1 - self.slippage_rate if self.is_long else 1 + self.slippage_rate)
        else:
            price = raw_price
        gross = self.qty * ((price - self.avg) if self.is_long else (self.avg - price))
        exit_fee = self.qty * price * (self.fee_rate if market_order or status == PositionStatus.LIQ else self.maker_fee_rate)
        trade_cash = gross - self.fees_paid - exit_fee          # phần chưa vào ledger (funding đã vào)
        if status == PositionStatus.LIQ:                         # isolated: mất tối đa ký quỹ + phí đã trả
            trade_cash = max(trade_cash, -(self.margin_used + self.fees_paid + exit_fee))
        # Nhả phần giữ chỗ (ký quỹ + phí vào lệnh), vốn thay đổi đúng bằng lãi/lỗ giao dịch sau phí.
        self.ledger.release(self.reserved_here)
        self.ledger.settle(trade_cash)
        net = trade_cash - self.funding_paid
        pos = self.position
        pos.close_time = t
        pos.close_price = price
        pos.status = status
        pos.close_reason = reason
        pos.exit_fee_usd = exit_fee
        pos.real_pnl = net
        pos.entry_equity = self.entry_equity
        pos.profit_pct = net / self.entry_equity * 100.0 if self.entry_equity > 0 else 0.0
        pos.qty = self.qty
        pos.layers = self.layer_count
        pos.avg_price = self.avg
        pos.total_margin_usd = self.margin_used
        pos.fees_usd = self.fees_paid + exit_fee
        pos.funding_usd = self.funding_paid
        pos.mae_pct = min(0.0, self.mae_usd / self.entry_equity * 100.0) if self.entry_equity > 0 else 0.0
        self.orders.append(OrderModel(
            order_id=_next_id(), account_id=self.account_id, position_id=pos.result_id, order_time=t,
            order_type=OrderType.SELL if self.is_long else OrderType.BUY, order_price=price, qty=self.qty,
            phase=self.layer_count, fee_usd=exit_fee,
            liquidity="liquidation" if status == PositionStatus.LIQ else ("taker" if market_order else "maker"),
        ))
        self.is_open = False
        self.pending_exit = False
        self.position = None
        self.last_close_time = t
        self._reset_state()
        return pos

    def _status_by_pnl(self, price: float) -> PositionStatus:
        move = (price - self.avg) if self.is_long else (self.avg - price)
        return PositionStatus.TP if move > 0 else PositionStatus.SL

    # ─── Một nến ────────────────────────────────────────────────────────────
    def on_bar(self, t: int, o: float, h: float, l: float, c: float,
               entry_signal: bool, stop_signal: bool, can_open: bool = True,
               vol: float = float("nan"), dca_gate: bool = True) -> Optional[PositionModel]:
        """Xử lý một nến 1m có giao dịch. Trả vị thế vừa đóng (nếu có).
        vol = ATR% (natr) của khung atr_frame đã đóng tại cuối nến này — dùng khi lệnh vào chờ được đặt ở nến này."""
        closed: Optional[PositionModel] = None

        # 1. Đầu nến
        if self.is_open:
            if self.pending_exit:
                closed = self._close(t, o, self._status_by_pnl(o), "Tín hiệu thoát (AST stop)", market_order=True)
            elif self.timeout_ms and t - self.entry_time >= self.timeout_ms:
                closed = self._close(t, o, self._status_by_pnl(o), "Hết thời gian giữ lệnh", market_order=True)
        if closed is None and not self.is_open and self.pending_entry:
            self.pending_entry = False
            if can_open:
                self._open(t, o)

        # 2-3. Trong nến
        if self.is_open and closed is None:
            if self.position is not None:
                self.position.max_price = max(self.position.max_price, h)
                self.position.min_price = min(self.position.min_price, l)
            closed = self._intrabar(t, o, h, l)

        # 4. Cuối nến
        if self.is_open:
            adverse = l if self.is_long else h
            self.mae_usd = min(self.mae_usd, self.unrealized_pnl_usd(adverse))
            self.peak = max(self.peak, h) if self.is_long else min(self.peak, l)
            if stop_signal:
                self.pending_exit = True
        elif closed is None and entry_signal and (
                not self.cooldown_ms or self.last_close_time is None or t - self.last_close_time >= self.cooldown_ms):
            self.pending_entry = True
            self.pending_vol = vol
        self.dca_ok = bool(dca_gate)
        return closed

    def _intrabar(self, t: int, o: float, h: float, l: float) -> Optional[PositionModel]:
        adverse = l if self.is_long else h
        favorable = h if self.is_long else l
        sign = 1.0 if self.is_long else -1.0
        dca_filled = False

        while True:
            events: List[Tuple[float, int, str]] = []  # (mức, ưu tiên khi hoà: thoát trước, loại)
            k = self.layer_count - 1
            dca_level = None
            if k < len(self.dca_steps) and self.dca_ok:
                dca_level = self.last_fill * (1 - sign * self.dca_steps[k] / 100.0)
                trigger = dca_level * (1 - sign * self.limit_through) if self.limit_through else dca_level
                events.append((trigger, 1, "dca"))
            if self.sl_pct:
                events.append((self.avg * (1 - sign * self.sl_pct / 100.0), 0, "sl"))
            if self.trail_pct:
                gain_pct = sign * (self.peak - self.avg) / self.avg * 100.0 if self.avg else 0.0
                if gain_pct >= self.trail_activation_pct:
                    events.append((self.peak * (1 - sign * self.trail_pct / 100.0), 0, "trail"))
            liq = self._liq_price()
            if liq is not None and liq > 0:
                events.append((liq, 0, "liq"))
            reached = [e for e in events if self._reached(e[0], adverse)]
            if not reached:
                break
            # long: mức cao nhất bị chạm trước khi giá rơi xuống; short: mức thấp nhất
            level, _, kind = (max(reached, key=lambda e: (e[0], -e[1])) if self.is_long
                              else min(reached, key=lambda e: (e[0], e[1])))
            price = self._gap_fill(level, o)
            if kind == "dca":
                price = self._gap_fill(dca_level, o)        # lệnh limit khớp ở giá đặt (hoặc giá mở nếu gap qua mức)
                margin = self.next_margin * self.dca_mults[k]
                if self._add_layer(t, price, margin, market_order=False, reason="DCA"):
                    self.next_margin = margin
                    dca_filled = True
                    continue
                self.dca_rejected += 1
                self.dca_steps = self.dca_steps[: k]  # hết vốn: không nhồi thêm tầng nào nữa
                continue
            if kind == "liq":
                return self._close(t, price, PositionStatus.LIQ, "Thanh lý (perp)", market_order=False)
            if self.stop_fill == "extreme":
                # Bi quan: lệnh stop-market khớp ở giá xấu nhất của nến (cú giật xuyên mức trong nến).
                price = min(price, adverse) if self.is_long else max(price, adverse)
            if kind == "sl":
                return self._close(t, price, PositionStatus.SL, "Stop-loss (từ giá TB)", market_order=True)
            return self._close(t, price, self._status_by_pnl(price), "Trailing stop", market_order=True)

        if self.tp_pct and not dca_filled:
            tp_level = self.avg * (1 + sign * self.tp_pct / 100.0)
            need = tp_level * (1 + sign * self.limit_through) if self.limit_through else tp_level
            if (favorable >= need) if self.is_long else (favorable <= need):
                price = max(tp_level, o) if self.is_long else min(tp_level, o)
                return self._close(t, price, PositionStatus.TP, "Take-profit (từ giá TB)", market_order=False)
        return None

    def force_close(self, t: int, raw_price: float, reason: str = "End of Backtest") -> Optional[PositionModel]:
        if not self.is_open:
            return None
        self.pending_entry = False
        return self._close(t, raw_price, PositionStatus.CANCEL, reason, market_order=True)

    @staticmethod
    def _combine_conditions(blocks: List[Dict[str, Any]]) -> List[Any]:
        combined: List[Any] = []
        if not isinstance(blocks, list):
            return combined
        for block in blocks:
            if isinstance(block, dict) and isinstance(block.get("condition", []), list):
                combined.extend(block.get("condition", []))
        return combined



class RefBacktestEngine:
    """Điều phối dữ liệu, tín hiệu và các flow chiến lược."""

    MAX_BACKTEST_DAYS = 1100
    MAX_STRATEGIES = 100
    KELTNER_CONFIGS = ((17, 0.5), (20, 1.5))
    MTM_SAMPLE_MINUTES = 60
    # Bỏ qua nến "rảnh" (không vị thế mở, không lệnh chờ, không tín hiệu vào) — kết quả BIT-IDENTICAL (test golden + test bật/tắt).
    _SKIP_IDLE = True

    def __init__(self, account_id: int, campaign_id: int, symbol: str, start_ts: int, end_ts: int,
                 trade_start_ts: Optional[int] = None, initial_capital: float = 10000.0):
        self.account_id = account_id
        self.campaign_id = campaign_id
        self.symbol = symbol
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.trade_start_ts = trade_start_ts if trade_start_ts is not None else start_ts
        self.initial_capital = float(initial_capital)

        days_diff = (end_ts - start_ts) / (86400 * 1000)
        if days_diff > self.MAX_BACKTEST_DAYS:
            raise ValueError(
                f"Limit Exceeded: Yêu cầu chạy {days_diff:.1f} ngày. "
                f"Server chỉ cho phép tối đa {self.MAX_BACKTEST_DAYS} ngày để bảo vệ tài nguyên!"
            )

        self.trackers: List[RefPositionTracker] = []
        self.ledger = RefCapitalLedger(self.initial_capital)
        self.funding: Optional[pd.DataFrame] = None  # perp: funding_time, rate
        self.df_base: Optional[pd.DataFrame] = None
        self.df_4h: Optional[pd.DataFrame] = None
        self.frames: Dict[str, pd.DataFrame] = {}
        self.closed_positions = []
        self.orders = []
        self.equity_curve: List[Dict[str, float]] = []
        self.bar_hook = None  # (tuỳ chọn, dùng cho test) gọi sau mỗi nến có giao dịch: hook(engine, t)

    # ─── Cấu hình ───────────────────────────────────────────────────────────
    def add_strategy_flow(self, flow_name: str, params: StrategyParams):
        if len(self.trackers) >= self.MAX_STRATEGIES:
            raise ValueError(f"Chỉ cho phép tối đa {self.MAX_STRATEGIES} strategy flows mỗi lần chạy.")
        ast = params.extra.get("ast", {}) if isinstance(params.extra, dict) else {}
        ast_type = str(ast.get("type", "") or params.extra.get("type", "")).upper()
        if ast_type == "LONG":
            pos_type = PositionType.LONG
        elif ast_type == "SHORT":
            pos_type = PositionType.SHORT
        else:
            pos_type = PositionType.LONG if "LONG" in flow_name.upper() else PositionType.SHORT
        self.trackers.append(RefPositionTracker(
            account_id=self.account_id, campaign_id=self.campaign_id, symbol=self.symbol, flow_name=flow_name,
            params=params, pos_type=pos_type, initial_capital=self.initial_capital, ledger=self.ledger,
        ))

    def _refs_by_frame(self) -> Dict[str, Set[Tuple[str, int]]]:
        by_frame: Dict[str, Set[Tuple[str, int]]] = {}
        for tracker in self.trackers:
            for frame, column, lag in (collect_field_refs(tracker.match_tree) | collect_field_refs(tracker.stop_tree)
                                       | collect_field_refs(tracker.dca_tree)):
                by_frame.setdefault(frame, set()).add((column, lag))
            if tracker.exit_unit == "atr":  # ATR% cho SL/TP/trailing theo biến động
                by_frame.setdefault(tracker.atr_frame, set()).add((f"natr_{tracker.atr_period}", 0))
        return by_frame

    @staticmethod
    def vol_column(tracker: RefPositionTracker) -> Optional[str]:
        return f"{tracker.atr_frame}|natr_{tracker.atr_period}" if tracker.exit_unit == "atr" else None

    def _warmup_ms(self, frame: str, refs: Set[Tuple[str, int]]) -> int:
        bars = max([kernels.warmup_bars(c) + lag for c, lag in refs] + [0])
        return (bars + 2) * FRAME_MS[frame]

    # ─── Dữ liệu: dùng CHUNG đường nạp / căn khung / chỉ báo của engine thật (tham chiếu chỉ đóng băng logic khớp lệnh từng nến) ───
    base_frame = "1m"   # tham chiếu chạy trên nến 1m
    check_frames = _ProdEngine.__dict__["check_frames"]
    load_data = _ProdEngine.__dict__["load_data"]
    load_frames = _ProdEngine.__dict__["load_frames"]
    _load_funding = _ProdEngine.__dict__["_load_funding"]
    _build_matrix = _ProdEngine.__dict__["_build_matrix"]
    frame_values = _ProdEngine.__dict__["frame_values"]
    align_index = _ProdEngine.__dict__["align_index"]
    gather = _ProdEngine.__dict__["gather"]
    _prepare_candles = _ProdEngine.__dict__["_prepare_candles"]
    _enrich_4h = _ProdEngine.__dict__["_enrich_4h"]
    _keltner_suffix = _ProdEngine.__dict__["_keltner_suffix"]

    def run(self):
        if self.df_base is None or self.df_base.empty:
            return
        self.closed_positions, self.orders, self.equity_curve = [], [], []
        print(f"Bắt đầu chạy backtest cho {self.symbol} ({len(self.df_base)} nến 1 phút)...")
        started = time.time()

        df1, cols = self._build_matrix()
        n = len(df1)

        def get(frame, column, lag):
            return cols.get(f"{frame}|{lag_key(column, lag)}", np.full(n, np.nan))

        vec = VectorEvaluator(n, get)
        signals = [(vec.tree(tr.match_tree), vec.tree(tr.stop_tree), vec.tree(tr.dca_tree) if tr.dca_tree else None) for tr in self.trackers]
        vols = [cols.get(self.vol_column(tr)) if self.vol_column(tr) else None for tr in self.trackers]

        t_arr = df1["open_time"].to_numpy(dtype="int64")
        o_arr, h_arr = df1["open"].to_numpy(dtype="float64"), df1["high"].to_numpy(dtype="float64")
        l_arr, c_arr = df1["low"].to_numpy(dtype="float64"), df1["close"].to_numpy(dtype="float64")
        filled = df1["is_filled"].to_numpy() == 1
        max_open = [int(getattr(tr.params, "max_open_trades", 45) or 45) for tr in self.trackers]

        last_sample = None
        last_real = None
        self.ruined_at = None
        f_times = self.funding["funding_time"].to_numpy(dtype="int64") if self.funding is not None else np.array([], "int64")
        f_rates = self.funding["rate"].to_numpy(dtype="float64") if self.funding is not None else np.array([])
        f_idx = 0
        real_pos = np.flatnonzero(~filled)  # chỉ nến có giao dịch (nến điền is_filled=1 bị bỏ qua hoàn toàn)
        n_real = len(real_pos)
        rt = t_arr[real_pos]
        skip = self._SKIP_IDLE and self.bar_hook is None   # bar_hook (test) cần kiểm bất biến mỗi nến
        if skip:
            # Nến có tín hiệu vào của BẤT KỲ flow nào, từ trade_start_ts (trước đó on_bar không làm gì khi phẳng)
            sig_any = np.zeros(n, dtype=bool)
            for match, _stop, _gate in signals:
                sig_any |= match
            cand = np.flatnonzero(sig_any[real_pos] & (rt >= self.trade_start_ts))
        busy = False  # nến trước còn flow mở / lệnh chờ?
        step = self.MTM_SAMPLE_MINUTES * 60_000
        r = 0
        while r < n_real:
            if skip and not busy and not any(tr.is_open or tr.pending_entry or tr.pending_exit for tr in self.trackers):
                k = int(np.searchsorted(cand, r))
                land = int(cand[k]) if k < len(cand) else n_real
                if land > r:  # r..land-1: phẳng, không tín hiệu -> chỉ còn mẫu vốn theo giờ (funding no-op khi phẳng;
                    # f_idx sẽ trượt tại nến đáp xuống, lúc đó mọi flow vẫn phẳng nên không trả funding)
                    last_real = int(real_pos[land - 1])
                    j = r if last_sample is None else int(np.searchsorted(rt, last_sample + step, side="left"))
                    while j < land:
                        ij = int(real_pos[j])
                        self._sample_equity(int(rt[j]), c_arr[ij], l_arr[ij], h_arr[ij])
                        last_sample = int(rt[j])
                        j = int(np.searchsorted(rt, last_sample + step, side="left"))
                    r = land
                    continue
            i = int(real_pos[r])
            r += 1
            last_real = i
            t = int(t_arr[i])
            while f_idx < len(f_times) and f_times[f_idx] <= t:  # funding đến hạn trước/ tại nến này
                for tr in self.trackers:
                    tr.apply_funding(float(f_rates[f_idx]), float(o_arr[i]))
                f_idx += 1
            can_trade = t >= self.trade_start_ts
            open_now = sum(1 for tr in self.trackers if tr.is_open)
            closed_any = False
            busy = False
            for k, tracker in enumerate(self.trackers):
                match, stop, gate = signals[k]
                pos = tracker.on_bar(t, o_arr[i], h_arr[i], l_arr[i], c_arr[i],
                                     entry_signal=bool(match[i]) and can_trade,
                                     stop_signal=bool(stop[i]),
                                     can_open=can_trade and open_now < max_open[k],
                                     vol=float(vols[k][i]) if vols[k] is not None else float("nan"),
                                     dca_gate=bool(gate[i]) if gate is not None else True)
                if tracker.is_open or tracker.pending_entry:
                    busy = True
                if pos is not None:
                    self._collect(tracker, pos)
                    closed_any = True
                    if self.ledger.equity <= 0 and self.ruined_at is None:
                        self.ruined_at = t
            if self.bar_hook is not None:
                self.bar_hook(self, t)
            if closed_any or last_sample is None or t - last_sample >= step:
                self._sample_equity(t, c_arr[i], l_arr[i], h_arr[i])
                last_sample = t

        if last_real is not None:
            t = int(t_arr[last_real])
            for tracker in self.trackers:
                pos = tracker.force_close(t, float(o_arr[last_real]), "End of Backtest")
                if pos is not None:
                    self._collect(tracker, pos)
            self._sample_equity(t, c_arr[last_real], l_arr[last_real], h_arr[last_real])

        print(f"Hoàn thành backtest. Thu được {len(self.closed_positions)} vị thế. Mất {time.time() - started:.2f} giây.")

    def _collect(self, tracker: RefPositionTracker, pos) -> None:
        self.closed_positions.append(pos)
        self.orders.extend(tracker.orders)
        tracker.orders = []

    def _sample_equity(self, t: int, close: float, low: float, high: float) -> None:
        """Vốn mark-to-market = vốn đã chốt (ledger, gồm funding) + lãi/lỗ treo của vị thế mở."""
        mtm = sum(tr.unrealized_pnl_usd(close) for tr in self.trackers)
        worst = sum(tr.unrealized_pnl_usd(low if tr.is_long else high) for tr in self.trackers)
        self.equity_curve.append({
            "time": t,
            "equity": round(float(self.ledger.equity + mtm), 4),
            "equity_worst": round(float(self.ledger.equity + worst), 4),
        })

    def get_results(self):
        return {"positions": self.closed_positions, "orders": self.orders, "equity_curve": self.equity_curve,
                "ruined_at": getattr(self, "ruined_at", None), "final_equity": self.ledger.equity,
                "rejected_for_capital": self.ledger.rejected,
                "dca_layers_rejected": sum(tr.dca_rejected for tr in self.trackers),
                "funding_modeled": self.funding is not None,
                "funding_events": 0 if self.funding is None else int(len(self.funding))}




class RefPortfolioEngine:
    MTM_SAMPLE_MINUTES = 60
    # Bỏ qua phút "rảnh" (không vị thế mở, không lệnh chờ, không tín hiệu vào) — kết quả BIT-IDENTICAL (test golden + test bật/tắt).
    _SKIP_IDLE = True

    def __init__(self, symbols: List[str], strategies: List[Dict[str, Any]], start_ts: int, end_ts: int,
                 trade_start_ts: Optional[int] = None, initial_capital: float = 10000.0,
                 risk: Optional[RiskConfig] = None, venue: str = "cex", use_cache: bool = True,
                 shared_dir: Optional[str] = None, close_at_end: bool = True):
        """strategies: [{"id", "side": LONG|SHORT, "tree": AST đã thay tham số, "position": {...POSITION_KEYS}}].
        Khoá tuỳ chọn "symbols": [..] giới hạn chiến lược đó chỉ chạy trên các tài sản này (mặc định: mọi tài sản).
        close_at_end=False: KHÔNG đóng vị thế còn mở ở cuối dữ liệu (vốn cuối vẫn là MTM) — xem open_positions() (feed giả lập).
        shared_dir: thư mục dữ liệu mmap dùng chung (backend/core/backtest/shared_data.py); mặc định env NORA_SHARED_DATA_DIR.
        Có thì _load_symbol ưu tiên đọc mmap (chỉ đọc) thay vì tự dựng; không thấy khoá thì dựng như cũ."""
        if not symbols or not strategies:
            raise ValueError("Cần ít nhất một tài sản và một chiến lược")
        ids = [s["id"] for s in strategies]
        if len(set(ids)) != len(ids):
            raise ValueError("id chiến lược phải khác nhau")
        self.symbols = list(symbols)
        self.strategies = strategies
        self.start_ts, self.end_ts = int(start_ts), int(end_ts)
        self.trade_start_ts = int(trade_start_ts if trade_start_ts is not None else start_ts)
        self.initial_capital = float(initial_capital)
        self.risk = risk or RiskConfig()
        self.venue = venue
        self.use_cache = use_cache
        self.shared_dir = shared_dir or os.environ.get("NORA_SHARED_DATA_DIR") or None
        self.ledger = RefCapitalLedger(self.initial_capital)
        self.books: List[Dict[str, Any]] = []   # mỗi tài sản: dữ liệu + trackers
        self.closed_positions: List[Any] = []
        self.orders: List[Any] = []
        self.equity_curve: List[Dict[str, float]] = []
        self.halted_at: Optional[int] = None
        self.ruined_at: Optional[int] = None
        self.rejected_for_risk = 0           # số PHÚT lệnh vào bị chặn bởi giới hạn rủi ro (giữ nguyên nghĩa, golden dựa vào đây)
        self.risk_blocked_attempts = 0       # số LẦN vào lệnh bị chặn: các phút liên tiếp của cùng một tracker tính là một lần
        self.bar_hook = None  # (test) gọi sau mỗi phút: hook(engine, t)
        self.close_at_end = close_at_end
        self.last_close: Dict[str, float] = {}   # giá đóng cửa cuối của từng tài sản (đặt khi run() xong)

    # ─── Dữ liệu ────────────────────────────────────────────────────────────
    def _make_trackers(self, symbol: str, ledger: RefCapitalLedger) -> Tuple[RefBacktestEngine, List[Tuple[Dict, RefPositionTracker]]]:
        from backend.core.params.builder import build_params
        eng = RefBacktestEngine(0, 0, symbol, self.start_ts, self.end_ts, trade_start_ts=self.trade_start_ts,
                             initial_capital=self.initial_capital)
        eng.ledger = ledger
        pairs = []
        for st in self.strategies:
            if st.get("symbols") and symbol not in st["symbols"]:
                continue
            name = f"{st['side']}_{st['id']}"
            eng.add_strategy_flow(name, build_params(name, _strategy_flow(st), st["side"], st["position"],
                                                     self.venue, symbol=symbol))
            pairs.append((st, eng.trackers[-1]))
        return eng, pairs

    @staticmethod
    def _refs_signature(eng: RefBacktestEngine):
        return tuple(sorted((f, tuple(sorted(r))) for f, r in eng._refs_by_frame().items()))

    def _cache_key(self, symbol: str, eng: RefBacktestEngine) -> tuple:
        return (symbol, self.start_ts, self.end_ts, self._refs_signature(eng), any(tr.market == "perp" for tr in eng.trackers))

    def _build_symbol_data(self, eng: RefBacktestEngine) -> Dict[str, Any]:
        """Dựng `data` của một tài sản (nến thật 1m + cột kernel + funding), không đụng cache."""
        with contextlib.redirect_stdout(io.StringIO()):
            eng.load_data()
        df1, cols = eng._build_matrix()
        real = df1["is_filled"].to_numpy() == 0
        return {
            "t": df1["open_time"].to_numpy(dtype="int64")[real],
            "o": df1["open"].to_numpy(dtype="float64")[real], "h": df1["high"].to_numpy(dtype="float64")[real],
            "l": df1["low"].to_numpy(dtype="float64")[real], "c": df1["close"].to_numpy(dtype="float64")[real],
            "cols": {k: v[real] for k, v in cols.items()},
            "f_t": eng.funding["funding_time"].to_numpy(dtype="int64") if eng.funding is not None else np.array([], "int64"),
            "f_r": eng.funding["rate"].to_numpy(dtype="float64") if eng.funding is not None else np.array([]),
        }

    def _load_symbol(self, symbol: str, eng: RefBacktestEngine) -> Dict[str, Any]:
        if self.shared_dir:  # mmap chỉ đọc do tiến trình cha dựng — KHÔNG đưa vào _DATA_CACHE (không nhân bản RAM)
            plan = shared_data.plan(eng)     # chỉ đọc phần đã có (lưu theo cột); thiếu thì dựng như thường
            shared = shared_data.load(self.shared_dir, plan) if plan else None
            if shared is not None:
                return shared
        key = self._cache_key(symbol, eng)
        if self.use_cache:
            cached = _DATA_CACHE.get(key)
            if cached is not None:
                return cached
        data = self._build_symbol_data(eng)
        if self.use_cache:
            arrays = [data[k] for k in ("t", "o", "h", "l", "c", "f_t", "f_r")] + list(data["cols"].values())
            _DATA_CACHE.put(key, data, sum(a.nbytes for a in arrays))
        return data

    def load_data(self) -> None:
        self.books = []
        for sym in self.symbols:
            eng, pairs = self._make_trackers(sym, self.ledger)
            if not pairs:   # không chiến lược nào chạy trên tài sản này (chỉ xảy ra khi dùng khoá "symbols")
                continue
            # Cổng chất lượng dữ liệu BẮT BUỘC (synthetic / sai sha256 / thiếu dữ liệu -> từ chối); có cache theo file nên rẻ khi gọi lại.
            # Tiến trình cha của CLI đã gọi trước khi fork pool -> worker thừa kế cache, không đọc lại 1m.
            from backend.core.data.quality_gate import require_data_ok
            require_data_ok([sym])
            data = self._load_symbol(sym, eng)
            n = len(data["t"])
            cols = data["cols"]
            vec = VectorEvaluator(n, lambda fr, c, lag: cols.get(f"{fr}|{lag_key(c, lag)}", np.full(n, np.nan)))
            entries = []
            for st, tr in pairs:
                vcol = RefBacktestEngine.vol_column(tr)
                entries.append({
                    "strategy": st["id"], "tracker": tr,
                    "match": vec.tree(tr.match_tree), "stop": vec.tree(tr.stop_tree),
                    "vol": cols.get(vcol) if vcol else None,
                    "dca": vec.tree(tr.dca_tree) if tr.dca_tree else None,
                })
            self.books.append({"symbol": sym, "data": data, "entries": entries, "f_idx": 0})

    # ─── Giới hạn rủi ro ────────────────────────────────────────────────────
    def _gross_notional(self, last_close: List[float]) -> float:
        total = 0.0
        for b, book in enumerate(self.books):
            px = last_close[b]
            if px != px:  # NaN: tài sản chưa có nến nào
                continue
            for e in book["entries"]:
                if e["tracker"].is_open:
                    total += e["tracker"].qty * px
        return total

    def _open_counts(self) -> Tuple[int, List[int]]:
        per = [sum(1 for e in book["entries"] if e["tracker"].is_open) for book in self.books]
        return sum(per), per

    # ─── Chạy ───────────────────────────────────────────────────────────────
    def run(self) -> None:
        if not self.books:
            self.load_data()
        grid = np.unique(np.concatenate([b["data"]["t"] for b in self.books]))
        idx_maps = []
        for book in self.books:
            m = np.full(len(grid), -1, dtype=np.int64)
            m[np.searchsorted(grid, book["data"]["t"])] = np.arange(len(book["data"]["t"]))
            idx_maps.append(m)
        last_close = [float("nan")] * len(self.books)
        last_low = [float("nan")] * len(self.books)
        last_high = [float("nan")] * len(self.books)
        last_open = [float("nan")] * len(self.books)
        peak_mtm = self.initial_capital
        last_sample = None
        cap = self.risk.max_gross_exposure
        kill = self.risk.kill_switch_dd_pct / 100.0 if self.risk.kill_switch_dd_pct else 0.0

        n_grid = len(grid)
        skip = self._SKIP_IDLE and self.bar_hook is None   # bar_hook (test) cần kiểm bất biến mỗi phút
        if skip:
            # Phút có tín hiệu vào của BẤT KỲ chiến lược × tài sản nào, tính từ trade_start_ts (trước đó on_bar không làm gì)
            sig_any = np.zeros(n_grid, dtype=bool)
            for book in self.books:
                pos = np.searchsorted(grid, book["data"]["t"])
                for e in book["entries"]:
                    sig_any[pos] |= e["match"]
            cand = np.flatnonzero(sig_any & (grid >= self.trade_start_ts))
        busy = False  # vòng trước còn tracker mở / lệnh chờ?

        g = 0
        while g < n_grid:
            if skip and not busy and not self._any_active():
                land = n_grid if self.halted_at is not None else (
                    int(cand[np.searchsorted(cand, g)]) if np.searchsorted(cand, g) < len(cand) else n_grid)
                if land > g:  # g..land-1: không có gì xảy ra ngoài funding trượt, last_*, mẫu vốn theo giờ
                    peak_mtm = max(peak_mtm, self.ledger.equity)
                    last_sample = self._skip_idle(grid, idx_maps, g, land, last_sample, last_close, last_low, last_high,
                                                  last_open)
                    g = land
                    continue
            t = int(grid[g])
            can_trade = t >= self.trade_start_ts and self.halted_at is None
            touched = False
            busy = False
            for b, book in enumerate(self.books):
                i = idx_maps[b][g]
                if i < 0:
                    continue
                d = book["data"]
                o, h, l, c = d["o"][i], d["h"][i], d["l"][i], d["c"][i]
                while book["f_idx"] < len(d["f_t"]) and d["f_t"][book["f_idx"]] <= t:
                    for e in book["entries"]:
                        e["tracker"].apply_funding(float(d["f_r"][book["f_idx"]]), float(o))
                    book["f_idx"] += 1
                for e in book["entries"]:
                    tr = e["tracker"]
                    sig = bool(e["match"][i])
                    if not tr.is_open and not tr.pending_entry and not sig:
                        continue  # không có gì xảy ra với tracker này ở phút này
                    can_open = False
                    if can_trade and tr.pending_entry and not tr.is_open:
                        n_open, per = self._open_counts()
                        blocked = n_open >= self.risk.max_positions or per[b] >= self.risk.max_per_symbol
                        if not blocked:
                            last_close[b] = float(o)  # giá tại thời điểm vào lệnh
                            room = cap * self.ledger.equity - self._gross_notional(last_close)
                            tr.max_new_notional = max(0.0, room)
                            can_open = room > 0
                            blocked = not can_open
                        if blocked:
                            self.rejected_for_risk += 1
                            if e.get("blk_g") != g - 1:   # phút trước tracker này không bị chặn -> một lần vào lệnh mới bị chặn
                                self.risk_blocked_attempts += 1
                            e["blk_g"] = g
                    pos = tr.on_bar(t, o, h, l, c, entry_signal=sig and can_trade, stop_signal=bool(e["stop"][i]),
                                    can_open=can_open,
                                    vol=float(e["vol"][i]) if e["vol"] is not None else float("nan"),
                                    dca_gate=bool(e["dca"][i]) if e.get("dca") is not None else True)
                    tr.max_new_notional = float("inf")
                    if tr.is_open or tr.pending_entry:
                        busy = True
                    if pos is not None:
                        self._collect(book["symbol"], e, pos)
                        if self.ledger.equity <= 0 and self.ruined_at is None:
                            self.ruined_at = t
                last_close[b], last_low[b], last_high[b], last_open[b] = float(c), float(l), float(h), float(o)
                touched = True
            g += 1
            if not touched:
                continue
            if self.bar_hook is not None:
                self.bar_hook(self, t)
            mtm, worst = self._mtm(last_close, last_low, last_high)
            peak_mtm = max(peak_mtm, mtm)
            if kill and self.halted_at is None and worst <= peak_mtm * (1.0 - kill):
                self._halt(t, last_close)
                mtm, worst = self._mtm(last_close, last_low, last_high)
            if last_sample is None or t - last_sample >= self.MTM_SAMPLE_MINUTES * 60_000:
                self._sample(t, mtm, worst)
                last_sample = t

        t_end = int(grid[-1]) if len(grid) else self.end_ts
        self.last_close = {book["symbol"]: last_close[b] for b, book in enumerate(self.books)}
        for b, book in enumerate(self.books if self.close_at_end else ()):
            t_last = int(book["data"]["t"][-1]) if len(book["data"]["t"]) else t_end
            for e in book["entries"]:  # cùng quy ước RefBacktestEngine: đóng ở open của nến cuối của tài sản
                pos = e["tracker"].force_close(t_last, last_open[b], "End of Backtest")
                if pos is not None:
                    self._collect(book["symbol"], e, pos)
        mtm, worst = self._mtm(last_close, last_low, last_high)
        self._sample(t_end, mtm, worst)

    def _any_active(self) -> bool:
        return any(e["tracker"].is_open or e["tracker"].pending_entry or e["tracker"].pending_exit
                   for book in self.books for e in book["entries"])

    def _skip_idle(self, grid, idx_maps, g: int, land: int, last_sample, last_close, last_low, last_high, last_open):
        """Tái hiện đúng những gì vòng lặp gốc làm ở các phút rảnh g..land-1 (mọi tracker đang phẳng):
        - funding: con trỏ f_idx của từng sổ trượt qua mọi funding <= nến cuối của sổ đó trong đoạn (apply_funding là no-op khi phẳng);
        - last_close/low/high/open: nến thật cuối của từng sổ trước `land`;
        - mẫu vốn theo giờ: đúng các thời điểm lưới mà vòng gốc sẽ lấy (t - last_sample >= MTM_SAMPLE_MINUTES), vốn = ledger.equity."""
        t_lo, t_hi = int(grid[g]), int(grid[land]) if land < len(grid) else None
        for b, book in enumerate(self.books):
            d = book["data"]
            lo = int(np.searchsorted(d["t"], t_lo, side="left"))
            hi = len(d["t"]) if t_hi is None else int(np.searchsorted(d["t"], t_hi, side="left"))
            if hi <= lo:
                continue
            i = hi - 1
            book["f_idx"] = max(book["f_idx"], int(np.searchsorted(d["f_t"], d["t"][i], side="right")))
            last_close[b], last_low[b], last_high[b], last_open[b] = (
                float(d["c"][i]), float(d["l"][i]), float(d["h"][i]), float(d["o"][i]))
        step = self.MTM_SAMPLE_MINUTES * 60_000
        k = g if last_sample is None else int(np.searchsorted(grid, last_sample + step, side="left"))
        while k < land:
            mtm, worst = self._mtm(last_close, last_low, last_high)  # phẳng: = vốn đã chốt
            last_sample = int(grid[k])
            self._sample(last_sample, mtm, worst)
            k = int(np.searchsorted(grid, last_sample + step, side="left"))
        return last_sample

    def _mtm(self, last_close, last_low, last_high) -> Tuple[float, float]:
        mtm = worst = self.ledger.equity
        for b, book in enumerate(self.books):
            for e in book["entries"]:
                tr = e["tracker"]
                if tr.is_open:
                    mtm += tr.unrealized_pnl_usd(last_close[b])
                    worst += tr.unrealized_pnl_usd(last_low[b] if tr.is_long else last_high[b])
        return mtm, worst

    def _halt(self, t: int, last_close: List[float]) -> None:
        """Kill switch: đóng mọi vị thế ở giá hiện tại (market) và dừng mở lệnh mới."""
        self.halted_at = t
        for b, book in enumerate(self.books):
            for e in book["entries"]:
                tr = e["tracker"]
                tr.pending_entry = False
                pos = tr.force_close(t, last_close[b], "Kill switch danh mục")
                if pos is not None:
                    self._collect(book["symbol"], e, pos)

    def _sample(self, t: int, mtm: float, worst: float) -> None:
        self.equity_curve.append({"time": t, "equity": round(float(mtm), 4), "equity_worst": round(float(worst), 4)})   # round của Python, không phải np.round

    def _collect(self, symbol: str, entry: Dict[str, Any], pos) -> None:
        pos.symbol = symbol
        pos.strategy_id = entry["strategy"]
        self.closed_positions.append(pos)
        self.orders.extend(entry["tracker"].orders)
        entry["tracker"].orders = []

    # ─── Kết quả ────────────────────────────────────────────────────────────
    def open_positions(self) -> List[Dict[str, Any]]:
        """Vị thế còn mở sau run() (chỉ khác rỗng khi close_at_end=False), mark = giá đóng cửa cuối của tài sản."""
        out = []
        for book in self.books:
            mark = self.last_close.get(book["symbol"])
            for e in book["entries"]:
                tr = e["tracker"]
                if not tr.is_open or tr.qty <= 0 or tr.position is None or mark is None or mark != mark:
                    continue
                out.append({"symbol": book["symbol"], "strategy": e["strategy"], "side": tr.pos_type.name, "qty": tr.qty,
                            "entry_price": tr.avg, "mark_price": float(mark), "notional": tr.qty * float(mark),
                            "unrealized_pnl": tr.unrealized_pnl_usd(float(mark)), "opened": int(tr.position.enter_time),
                            "margin_usd": tr.margin_used, "leverage": tr.pos_leverage})
        return out

    def get_results(self) -> Dict[str, Any]:
        by_strategy: Dict[str, Dict[str, float]] = {}
        by_symbol: Dict[str, Dict[str, float]] = {}
        for p in self.closed_positions:
            for key, bucket in ((p.strategy_id, by_strategy), (p.symbol, by_symbol)):
                agg = bucket.setdefault(key, {"pnl_usd": 0.0, "trades": 0, "wins": 0, "fees_usd": 0.0, "funding_usd": 0.0})
                agg["pnl_usd"] += p.real_pnl
                agg["trades"] += 1
                agg["wins"] += int(p.real_pnl > 0)
                agg["fees_usd"] += p.fees_usd or 0.0
                agg["funding_usd"] += p.funding_usd or 0.0
        skipped = sum(e["tracker"].skipped_no_vol for b in self.books for e in b["entries"])
        dca_rejected = sum(e["tracker"].dca_rejected for b in self.books for e in b["entries"])
        return {
            "positions": self.closed_positions, "orders": self.orders, "equity_curve": self.equity_curve,
            "final_equity": self.ledger.equity, "initial_capital": self.initial_capital,
            "by_strategy": by_strategy, "by_symbol": by_symbol,
            "rejected_for_capital": self.ledger.rejected, "rejected_for_risk": self.rejected_for_risk,
            "risk_blocked_attempts": self.risk_blocked_attempts,
            "skipped_no_vol": skipped, "dca_layers_rejected": dca_rejected, "halted_at": self.halted_at, "ruined_at": self.ruined_at,
            "risk": asdict(self.risk), "symbols": self.symbols, "strategies": [s["id"] for s in self.strategies],
        }
