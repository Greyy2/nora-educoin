"""Quản lý vị thế (Position management) — một flow chiến lược.

Vòng đời một nến 1m CÓ GIAO DỊCH (nến điền is_filled=1 bị bỏ qua hoàn toàn):

1. Đầu nến (giá open):
   - lệnh thoát chờ (tín hiệu stop ở nến trước) hoặc hết thời gian giữ lệnh -> đóng ở open;
   - lệnh vào chờ (tín hiệu match ở nến trước) -> mở tầng đầu ở open (+ trượt giá).
2. Trong nến — phía BẤT LỢI được xử lý theo đúng thứ tự giá chạm (long: từ trên xuống):
   tầng DCA (lệnh limit), stop-loss, trailing stop, giá thanh lý (perp). Sau mỗi tầng DCA,
   giá trung bình, SL và giá thanh lý được tính lại. Hoà mức -> ưu tiên THOÁT (bi quan).
   Giá open đã vượt mức -> khớp ở open (gap).
3. Phía CÓ LỢI: chốt lời (limit, từ giá TB) chỉ được xét nếu trong nến KHÔNG có tầng DCA nào
   khớp — không giả định "vừa nhồi ở đáy vừa chốt ở đỉnh" trong cùng một nến.
4. Cuối nến: cập nhật đỉnh/đáy có lợi (cho trailing), lỗ treo tối đa (MAE), rồi đặt lệnh chờ
   cho nến sau theo tín hiệu match/stop (tính trên nến đã đóng).

Chế độ thị trường:
- spot: đòn bẩy = 1, không cho SHORT, không thanh lý.
- perp: đòn bẩy L, ký quỹ isolated, thanh lý khi giá chạm
  long:  avg × (1 − 1/L + mmr)      short: avg × (1 + 1/L − mmr).
  Giá dùng là giá perp thật khi có dữ liệu <SYM>@perp (kèm funding); không có thì giá spot làm proxy.
- stop_fill="extreme": SL/trailing khớp ở giá xấu nhất của nến chạm mức (bi quan). Mặc định "level"
  giả định khớp đúng mức + trượt — lạc quan khi giá giật xuyên mức trong một nến.

Khối lượng: ký quỹ tầng đầu = VỐN HIỆN TẠI (vốn ban đầu + lãi/lỗ đã chốt, do engine cập nhật)
× order_size_pct%; tầng k = tầng k-1 × hệ số. Ngân sách một vị thế = vốn hiện tại lúc mở × max_capital_usage;
tầng nào vượt ngân sách thì bị bỏ qua. Vốn <= 0 -> không mở lệnh mới (cháy tài khoản).
PnL % của lệnh tính trên vốn lúc mở lệnh (để ghép lãi kép đúng trong WFA/Monte Carlo).
"""
import itertools
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.core.params import StrategyParams
from backend.db.models import OrderModel, OrderType, PositionModel, PositionStatus, PositionType

# Bộ đếm id toàn cục, tăng dần và không trùng (int(time.time()*1000) trùng khi
# nhiều lệnh mở trong cùng 1 ms). Bắt đầu từ epoch-ms * 1000 để vẫn sắp xếp theo thời gian.
_ID_SEQ = itertools.count(int(time.time() * 1000) * 1000)


def _next_id() -> int:
    return next(_ID_SEQ)


class CapitalLedger:
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


class PositionTracker:
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
        ledger: Optional[CapitalLedger] = None,
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
        self.ledger = ledger if ledger is not None else CapitalLedger(self.capital, self.capital_usage)
        self.max_capital = self.capital * self.capital_usage

        # Giá trị gốc của tham số thoát lệnh; mỗi vị thế quy đổi sang % lúc vào lệnh (_apply_exit_unit).
        self.base_sl = max(0.0, float(params.stop_loss_rate or 0.0))
        self.base_tp = max(0.0, float(params.take_profit_rate or 0.0))
        self.base_trail = max(0.0, float(params.trailing_stop or 0.0))
        self.base_trail_act = max(0.0, float(getattr(params, "trailing_activation_pct", 0.0) or 0.0))
        self.timeout_ms = max(0, int(params.timeout or 0)) * 60_000
        self.stop_fill = str(getattr(params, "stop_fill", "level") or "level").lower()
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
        """Vốn đã chốt hiện tại (dùng chung giữa các flow qua CapitalLedger)."""
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
        self._reset_state()
        return pos

    def _status_by_pnl(self, price: float) -> PositionStatus:
        move = (price - self.avg) if self.is_long else (self.avg - price)
        return PositionStatus.TP if move > 0 else PositionStatus.SL

    # ─── Một nến ────────────────────────────────────────────────────────────
    def on_bar(self, t: int, o: float, h: float, l: float, c: float,
               entry_signal: bool, stop_signal: bool, can_open: bool = True,
               vol: float = float("nan")) -> Optional[PositionModel]:
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
        elif closed is None and entry_signal:
            self.pending_entry = True
            self.pending_vol = vol
        return closed

    def _intrabar(self, t: int, o: float, h: float, l: float) -> Optional[PositionModel]:
        adverse = l if self.is_long else h
        favorable = h if self.is_long else l
        sign = 1.0 if self.is_long else -1.0
        dca_filled = False

        while True:
            events: List[Tuple[float, int, str]] = []  # (mức, ưu tiên khi hoà: thoát trước, loại)
            k = self.layer_count - 1
            if k < len(self.dca_steps):
                level = self.last_fill * (1 - sign * self.dca_steps[k] / 100.0)
                events.append((level, 1, "dca"))
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
                margin = self.next_margin * self.dca_mults[k]
                if self._add_layer(t, price, margin, market_order=False, reason="DCA"):
                    self.next_margin = margin
                    dca_filled = True
                    continue
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
            if (favorable >= tp_level) if self.is_long else (favorable <= tp_level):
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
