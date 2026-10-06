"""Kế toán thực thi (P6.3): Account (sổ vốn chung) + PositionBook (kế toán một slot).

Hai lớp này là nơi DUY NHẤT thay đổi vốn và vị thế; chỉ thay đổi qua sự kiện (events.py) nên phát lại chuỗi
sự kiện vào đối tượng mới cho đúng từng bit. Mọi biểu thức giữ nguyên thứ tự phép toán float của tracker cũ
(sao chép nguyên văn / qua policy.py). Kiểm tra trước giao dịch (`can_add`, `can_reserve`) gọi TRƯỚC khi
chấp nhận Fill; bị từ chối thì ghi OrderRejected (`PositionBook.reject`).
"""
from typing import List, Optional, Union

from backend.core.execute import policy
from backend.core.execute.events import Fill, FundingApplied, OrderRejected, PositionMarked
from backend.core.execute.models import OrderModel, OrderType, PositionModel, PositionStatus, PositionType

Event = Union[Fill, FundingApplied, OrderRejected, PositionMarked]


class Account:
    """Sổ vốn chung của một lần chạy — nguồn sự thật duy nhất cho phân bổ vốn.

    equity   : vốn đã chốt (vốn đầu + Σ lãi/lỗ đã đóng + funding đã trả/nhận).
    reserved : tiền đang bị khoá trong các vị thế mở (ký quỹ + phí vào lệnh đã trả).
    free     : equity × usage − reserved. Mọi lệnh vào / tầng DCA phải giữ chỗ được từ free,
               nên nhiều flow cùng lúc KHÔNG thể dùng quá vốn (lỗi cũ: mỗi flow tự dùng 100%).
    (Trước P6.3 tên là CapitalLedger — vẫn import được từ core/execute/ledger.py.)
    """

    def __init__(self, capital: float, usage: float = 1.0):
        self.initial = float(capital)
        self.equity = float(capital)
        self.reserved = 0.0
        self.usage = max(0.0, min(float(usage), 1.0))
        self.rejected = 0  # số lần vào lệnh/tầng bị từ chối vì không đủ vốn
        self.peak = float(capital)   # đỉnh vốn ĐÃ CHỐT (cho giảm rủi ro theo mức sụt — dd_throttle_pct)

    def free(self) -> float:
        return self.equity * self.usage - self.reserved

    def can_reserve(self, amount: float) -> bool:
        """Kiểm tra thuần (không đổi sổ): có giữ chỗ được `amount` từ vốn trống không."""
        return not (amount <= 0 or amount > self.free() + 1e-9)

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
        if self.equity > self.peak:
            self.peak = self.equity

    def close_trade(self, reserved: float, trade_cash: float) -> None:
        """Quyết toán đóng vị thế: nhả phần giữ chỗ rồi ghi lãi/lỗ giao dịch sau phí (funding đã vào sổ từ trước)."""
        self.release(reserved)
        self.settle(trade_cash)

    def apply(self, ev: Event) -> None:
        """Phần SỔ VỐN của một sự kiện (phần vị thế do PositionBook xử lý; đóng vị thế qua close_trade vì cần tiền lãi/lỗ)."""
        if isinstance(ev, Fill):
            if ev.kind in ("entry", "dca"):
                self.reserved += ev.margin + ev.fee        # đã qua can_reserve nên giữ chỗ chắc chắn được
        elif isinstance(ev, FundingApplied):
            self.settle(-ev.payment)
        elif isinstance(ev, OrderRejected):
            if ev.reason in ("capital", "no_margin"):
                self.rejected += 1


class PositionBook:
    """Kế toán một slot: qty, avg, ký quỹ, phí, tầng, PositionModel/OrderModel. Đổi trạng thái chỉ qua apply_* / apply(event)."""

    def __init__(self, account: Account, account_id: int, campaign_id: int, symbol: str, flow_name: str,
                 pos_type: PositionType, slot: int = 0, events: Optional[List[Event]] = None):
        self.account = account
        self.account_id = account_id
        self.campaign_id = campaign_id
        self.symbol = symbol
        self.flow_name = flow_name
        self.pos_type = pos_type
        self.is_long = pos_type == PositionType.LONG
        self.slot = slot
        self.events = events          # chuỗi sự kiện đã áp (None = không ghi); dùng chung giữa các book để giữ thứ tự toàn cục
        self.position: Optional[PositionModel] = None
        self.orders: List[OrderModel] = []
        self.reset()

    def reset(self) -> None:
        self.qty = 0.0
        self.avg = 0.0
        self.margin_used = 0.0
        self.fees_paid = 0.0
        self.layer_count = 0
        self.last_fill = 0.0
        self.entry_time = 0
        self.reserved_here = 0.0   # tiền đã giữ chỗ trong sổ vốn cho vị thế này
        self.funding_paid = 0.0    # funding đã trả (+) / nhận (−), đã hạch toán thẳng vào sổ vốn
        self.entry_equity = self.account.equity

    # ─── kiểm tra trước giao dịch ───────────────────────────────────────────
    def can_add(self, margin: float, fee: float, max_capital: float) -> bool:
        """Ngân sách một vị thế: ký quỹ + phí đã dùng + tầng mới không vượt max_capital."""
        return not (self.margin_used + margin + self.fees_paid + fee > max_capital + 1e-9)

    def reject(self, reason: str, kind: str, order_id: int = 0) -> None:
        ev = OrderRejected(self.slot, order_id, kind, reason)
        self.account.apply(ev)
        if self.events is not None:
            self.events.append(ev)

    # ─── sự kiện ────────────────────────────────────────────────────────────
    def apply(self, ev: Event) -> Optional[PositionModel]:
        """Áp một sự kiện (dùng khi phát lại). Trả vị thế vừa đóng nếu là Fill đóng."""
        if isinstance(ev, Fill):
            if ev.kind in ("entry", "dca"):
                self.apply_fill(ev)
                return None
            return self.apply_close(ev)
        if isinstance(ev, FundingApplied):
            self.apply_funding(ev)
        elif isinstance(ev, OrderRejected):
            self.account.apply(ev)
            if self.events is not None:
                self.events.append(ev)
        elif isinstance(ev, PositionMarked):
            self.mark(ev.high, ev.low)
        return None

    def mark(self, high: float, low: float) -> None:
        """Đầu nến của vị thế đang mở: đỉnh/đáy của PositionModel."""
        if self.position is not None:
            self.position.max_price = max(self.position.max_price, high)
            self.position.min_price = min(self.position.min_price, low)
            if self.events is not None:
                self.events.append(PositionMarked(self.slot, high, low))

    def apply_fill(self, fill: Fill) -> None:
        """Lệnh vào / nhồi tầng đã được chấp nhận (đã qua can_add + can_reserve)."""
        margin, fee, price = fill.margin, fill.fee, fill.price
        self.account.apply(fill)
        self.reserved_here += margin + fee
        qty = fill.notional / price
        new_qty = self.qty + qty
        self.avg = (self.avg * self.qty + price * qty) / new_qty
        self.qty = new_qty
        self.margin_used += margin
        self.fees_paid += fee
        self.layer_count += 1
        self.last_fill = price
        if self.position is None:
            self.entry_time = fill.t
            self.entry_equity = self.account.equity
            self.position = PositionModel(
                result_id=fill.order_id, account_id=self.account_id, campaign_id=self.campaign_id, symbol=self.symbol,
                pos_type=self.pos_type, phase=0, enter_time=fill.t, enter_price=price, status=PositionStatus.OPEN,
                flow=self.flow_name, start_reason=fill.reason, max_price=price, min_price=price,
                entry_equity=self.account.equity, entry_margin_usd=margin, entry_notional_usd=fill.notional, entry_fee_usd=fee,
            )
            self.position.unit_pct = fill.unit_pct
            self.position.leverage_used = fill.leverage_used
            self.position.risk_usd = fill.risk_usd
        self.orders.append(OrderModel(
            order_id=fill.order_id, account_id=self.account_id, position_id=self.position.result_id, order_time=fill.t,
            order_type=OrderType.BUY if self.is_long else OrderType.SELL, order_price=price, qty=qty,
            phase=self.layer_count - 1, fee_usd=fee, liquidity=fill.liquidity, slippage=fill.slip,
        ))
        if self.events is not None:
            self.events.append(fill)

    def apply_close(self, fill: Fill, status: Optional[PositionStatus] = None, reason: Optional[str] = None,
                    mae_usd: Optional[float] = None) -> PositionModel:
        """Đóng hết vị thế: lãi/lỗ gộp, phí thoát, trần thanh lý, nhả giữ chỗ, quyết toán sổ vốn, điền PositionModel + OrderModel đóng."""
        status = PositionStatus(fill.status) if status is None else status
        reason = fill.reason if reason is None else reason
        mae = fill.mae_usd if mae_usd is None else mae_usd
        price, exit_fee, slip, t = fill.price, fill.fee, fill.slip, fill.t
        gross = policy.gross_pnl(self.qty, self.avg, price, self.is_long)
        trade_cash = gross - self.fees_paid - exit_fee          # phần chưa vào sổ vốn (funding đã vào)
        if status == PositionStatus.LIQ:                         # isolated: mất tối đa ký quỹ + phí đã trả
            trade_cash = max(trade_cash, -(self.margin_used + self.fees_paid + exit_fee))
        # Nhả phần giữ chỗ (ký quỹ + phí vào lệnh), vốn thay đổi đúng bằng lãi/lỗ giao dịch sau phí.
        self.account.close_trade(self.reserved_here, trade_cash)
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
        pos.mae_pct = min(0.0, mae / self.entry_equity * 100.0) if self.entry_equity > 0 else 0.0
        self.orders.append(OrderModel(
            order_id=fill.order_id, account_id=self.account_id, position_id=pos.result_id, order_time=t,
            order_type=OrderType.SELL if self.is_long else OrderType.BUY, order_price=price, qty=self.qty,
            phase=self.layer_count, fee_usd=exit_fee, liquidity=fill.liquidity, slippage=slip,
        ))
        self.position = None
        self.reset()
        if self.events is not None:
            self.events.append(fill)
        return pos

    def apply_funding(self, ev: FundingApplied) -> float:
        self.funding_paid += ev.payment
        self.account.apply(ev)
        if self.events is not None:
            self.events.append(ev)
        return ev.payment

    def unrealized_pnl(self, price: float) -> float:
        if self.qty <= 0:
            return 0.0
        return policy.unrealized_pnl(self.qty, self.avg, price, self.fees_paid, self.is_long)  # funding đã nằm trong equity của Account
