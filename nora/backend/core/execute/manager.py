"""PositionManager (P6.4) — policy một slot theo SỰ KIỆN: thay `PositionTracker.on_bar` cho paper / demo / live.

Vai trò (docs/bmad/p6_execution_design.md §1, §4): giữ trạng thái CHIẾN LƯỢC của slot (lệnh vào/thoát chờ, cooldown, timeout, đỉnh, MAE,
cổng DCA, ký quỹ tầng kế, tham số thoát đã quy đổi, trần rủi ro do danh mục đặt) và RA LỆNH cho Venue; Fill / OrderRejected do venue trả về
được áp vào Account + PositionBook (account.py — nơi duy nhất đổi vốn và vị thế). Công thức mức giá / khối lượng chỉ ở policy.py.

Một nến (`on_bar`, cùng chữ ký tracker):
  begin : lệnh thoát chờ / hết thời gian -> EXIT market; lệnh vào chờ -> sizing (policy + trần danh mục) -> ENTRY market.
  adverse: đặt SL / TRAIL / DCA / TP từ giá TB; kéo sự kiện của venue (hoà thì thoát trước) — DCA khớp: áp, tính lại lệnh chờ từ avg mới;
           DCA bị từ chối (ngân sách / vốn): cắt các tầng còn lại, dca_rejected += 1; SL / TRAIL / thanh lý: áp, đóng, kết thúc nến.
  favorable: TP (venue bỏ qua nếu nến có DCA khớp). end: đỉnh, MAE, cờ pending, cổng DCA, cooldown.

Bot sàn (P6.8b): venue không khớp theo nến mà báo sự kiện qua poll -> `sync_events()` kéo và áp ngay (DCA khớp: đặt lại SL/TP/... từ avg mới;
SL/TP/trailing khớp: đóng). `sticky_orders=True` (bot sàn) giữ nguyên lệnh đang nằm trên sàn khi tập lệnh mong muốn không đổi (không huỷ/đặt lại mỗi nến —
lệnh bảo vệ luôn nằm sẵn, ADR D2; trailing gốc không bị đặt lại làm mất đỉnh). Venue có trailing gốc (caps.native_trailing) nhận TRAIL ngay từ lúc vào
lệnh (sàn tự kích hoạt tại `activation`); sim chỉ đặt TRAIL khi đã kích hoạt theo đỉnh các nến trước.

Dựng từ một PositionTracker đã chuẩn hoá tham số (tracker còn là bộ chuẩn hoá tham số tới P6.9; manager chỉ sao chép trường, không dùng
sổ/book của tracker). `id` của OrderModel / PositionModel lấy từ `tracker._next_id()` lúc khớp (venue cấp) nên trùng thứ tự gọi của tracker.
"""
import dataclasses
from collections import Counter
from typing import Callable, List, Optional

from backend.core import position_size as policy
from backend.core.models import Account, Fill, FundingApplied, OrderRejected, PositionBook, PositionModel, PositionStatus
from backend.core.execute.tracker import PositionTracker, _book_attr
from backend.core.execute.venue import Order, OrderKind, Venue, new_order_id

_EXIT_REASON = "Tín hiệu thoát (AST stop)"
_TIMEOUT_REASON = "Hết thời gian giữ lệnh"
_SL_REASON = "Stop-loss (từ giá TB)"
_TRAIL_REASON = "Trailing stop"
_TP_REASON = "Take-profit (từ giá TB)"
_EXCHANGE_CLOSE_REASON = "Sàn đã đóng vị thế"


class PositionManager:
    """Policy vị thế một slot, điều khiển một Venue (SimVenue ở P6.4; OkxVenue ở P6.7)."""

    def __init__(self, tracker: PositionTracker, venue: Venue, slot: int = 0, account: Optional[Account] = None,
                 events: Optional[List] = None):
        if tracker.limit_taker or tracker.impact_fn is not None:
            raise NotImplementedError("PositionManager chưa hỗ trợ limit_taker / impact_fn (AMM/DEX nằm ngoài P6)")
        tr = tracker
        self.venue = venue
        self.slot = slot
        # ── tham số đã chuẩn hoá (sao chép từ tracker) ──
        self.account_id, self.campaign_id, self.symbol, self.flow_name = tr.account_id, tr.campaign_id, tr.symbol, tr.flow_name
        self.pos_type, self.is_long, self.market = tr.pos_type, tr.is_long, tr.market
        self.mmr = tr.mmr
        self.fee_rate, self.maker_fee_rate, self.slippage_rate = tr.fee_rate, tr.maker_fee_rate, tr.slippage_rate
        self.capital_usage = tr.capital_usage
        self.base_sl, self.base_tp, self.base_trail, self.base_trail_act = tr.base_sl, tr.base_tp, tr.base_trail, tr.base_trail_act
        self.timeout_ms, self.cooldown_ms = tr.timeout_ms, tr.cooldown_ms
        self.stop_fill, self.limit_through = tr.stop_fill, tr.limit_through
        self.intrabar_path = tr.intrabar_path
        self.exit_unit, self.sizing = tr.exit_unit, tr.sizing
        self.risk_pct, self.max_notional_pct = tr.risk_pct, tr.max_notional_pct
        self.base_dca_steps, self.dca_mults = list(tr.base_dca_steps), list(tr.dca_mults)
        self.max_leverage, self.order_size_pct = tr.max_leverage, tr.order_size_pct
        # ── sổ ──
        acct = account if account is not None else tr.ledger
        self.book = PositionBook(acct, self.account_id, self.campaign_id, self.symbol, self.flow_name, self.pos_type,
                                 slot=slot, events=events)
        self.max_capital = tr.max_capital
        # ── trạng thái chiến lược ──
        self.last_close_time: Optional[int] = None
        self.dca_rejected = 0
        self.pos_leverage = tr.pos_leverage
        self.planned_risk = 0.0
        self.max_new_notional = float("inf")   # trần do danh mục đặt từ risk.Admission trước mỗi on_bar
        self.max_new_risk = float("inf")
        self.risk_scale = 1.0
        self.unit_pct = 0.0
        self.pending_vol = float("nan")
        self.skipped_no_vol = 0
        self._apply_exit_unit(1.0)
        self.dca_ok = True
        self.is_open = False
        self.pending_entry = False
        self.pending_exit = False
        self._reset_state()
        add_slot = getattr(venue, "add_slot", None)
        if add_slot is not None:    # SimVenue cần chi phí khớp và cổng kiểm tra trước giao dịch của slot
            add_slot(slot, fee_rate=self.fee_rate, maker_fee_rate=self.maker_fee_rate, slippage_rate=self.slippage_rate,
                     stop_fill=self.stop_fill, gate=self._gate, intrabar_path=self.intrabar_path)

    def __setstate__(self, state: dict) -> None:
        """Pickle cũ (unified.pkl / paper.pkl trước commit 169ddd0) chưa có intrabar_path."""
        self.__dict__.update(state)
        self.__dict__.setdefault("intrabar_path", "ohlc")

    # ─── Trạng thái (cửa sổ vào book; cũng là PositionView của SimVenue) ────────
    qty = _book_attr("qty")
    avg = _book_attr("avg")
    margin_used = _book_attr("margin_used")
    fees_paid = _book_attr("fees_paid")
    layer_count = _book_attr("layer_count")
    last_fill = _book_attr("last_fill")
    entry_time = _book_attr("entry_time")
    reserved_here = _book_attr("reserved_here")
    funding_paid = _book_attr("funding_paid")
    entry_equity = _book_attr("entry_equity")
    position = _book_attr("position")
    orders = _book_attr("orders")

    @property
    def ledger(self) -> Account:
        return self.book.account

    @ledger.setter
    def ledger(self, account: Account) -> None:
        self.book.account = account

    @property
    def equity(self) -> float:
        return self.ledger.equity

    @property
    def avg_entry_price(self) -> float:
        return self.avg

    def _apply_exit_unit(self, unit: float) -> None:
        (self.sl_pct, self.tp_pct, self.trail_pct, self.trail_activation_pct,
         self.dca_steps) = policy.exit_params_scaled(unit, self.base_sl, self.base_tp, self.base_trail,
                                                     self.base_trail_act, self.base_dca_steps)

    def _reset_state(self) -> None:
        self.book.reset()
        self.next_margin = 0.0
        self.peak = 0.0
        self.mae_usd = 0.0

    def unrealized_pnl_usd(self, price: float) -> float:
        if not self.is_open or self.qty <= 0:
            return 0.0
        return self.book.unrealized_pnl(price)

    def apply_funding(self, rate: float, price: float, t: int = 0) -> float:
        if not self.is_open or self.market != "perp" or self.qty <= 0:
            return 0.0
        payment = policy.funding_payment(self.qty, price, rate, self.is_long)
        return self.book.apply_funding(FundingApplied(self.book.slot, t, rate, price, payment))

    # ─── Cổng kiểm tra trước giao dịch (venue gọi trước khi chấp nhận lệnh vào / DCA) ──
    def _gate(self, kind: str, margin: float, fee: float, price: float) -> Optional[str]:
        if margin <= 0 or price <= 0 or not self.book.can_add(margin, fee, self.max_capital):
            return "budget"        # vượt ngân sách vị thế: không đổi sổ vốn
        if not self.ledger.can_reserve(margin + fee):
            return "capital"       # không giữ chỗ được từ vốn trống: ledger.rejected += 1
        return None

    # ─── Đặt lệnh ───────────────────────────────────────────────────────────
    def _submit(self, kind: OrderKind, is_buy: bool, **kw) -> None:
        self.venue.submit(Order(new_order_id(), self.slot, kind, is_buy, **kw))

    # Bot sàn bật: giữ lệnh đang nằm trên sàn nếu tập lệnh mong muốn không đổi (xem docstring module). Mặc định tắt (sim: đặt lại mỗi nến như cũ).
    sticky_orders = False
    _placed_qty = -1.0

    @staticmethod
    def _nn(x: float) -> Optional[float]:
        return None if x != x else x

    def _order_key(self, o: Order, native: bool) -> tuple:
        n = self._nn
        if o.kind == OrderKind.TRAIL and native:       # trailing gốc: sàn tự bám đỉnh -> chỉ kích hoạt / callback quyết định lệnh có đổi không
            return (int(o.kind), n(o.activation), n(o.callback_pct))
        return (int(o.kind), n(o.level), n(o.trigger), o.notional, o.margin)

    def _desired_orders(self) -> List[Order]:
        """Tập lệnh chờ mong muốn từ avg, last_fill và peak hiện tại (DCA kế tiếp, SL, TRAIL, TP)."""
        sign = 1.0 if self.is_long else -1.0
        k = self.layer_count - 1
        caps = getattr(self.venue, "caps", None)
        native = bool(caps is not None and caps.native_trailing)
        out: List[Order] = []

        def add(kind: OrderKind, is_buy: bool, **kw) -> None:
            out.append(Order(new_order_id(), self.slot, kind, is_buy, **kw))
        if k < len(self.dca_steps) and self.dca_ok:
            level = policy.dca_level(self.last_fill, self.dca_steps[k], sign)
            margin = self.next_margin * self.dca_mults[k]
            add(OrderKind.DCA, self.is_long, level=level, trigger=policy.dca_trigger(level, self.limit_through, sign),
                notional=margin * self.pos_leverage, margin=margin, reason="DCA", post_only=True)
        if self.sl_pct:
            add(OrderKind.SL, not self.is_long, level=policy.sl_level(self.avg, self.sl_pct, sign), reason=_SL_REASON, reduce_only=True)
        path_mode = self.intrabar_path != "adverse_first"
        if self.trail_pct and (native or path_mode or policy.trail_active(self.peak, self.avg, self.trail_activation_pct, sign)):
            # level = mức stop tĩnh từ đỉnh các nến trước (SimVenue đường cũ); activation / callback_pct cho trailing gốc của sàn (OkxVenue);
            # peak / activation_pct: SimVenue đường ohlc/adaptive tự chạy đỉnh theo từng chặng và tự kiểm kích hoạt
            add(OrderKind.TRAIL, not self.is_long, level=policy.trail_level(self.peak, self.trail_pct, sign),
                activation=policy.tp_level(self.avg, self.trail_activation_pct, sign), callback_pct=self.trail_pct,
                reason=_TRAIL_REASON, reduce_only=True, peak=self.peak, activation_pct=self.trail_activation_pct)
        if self.tp_pct:
            level = policy.tp_level(self.avg, self.tp_pct, sign)
            add(OrderKind.TP, not self.is_long, level=level, trigger=policy.tp_need(level, self.limit_through, sign),
                reason=_TP_REASON, reduce_only=True, post_only=True)
        return out

    def _place_orders(self) -> None:
        """Đặt lại DCA kế tiếp / SL / TRAIL / TP từ avg, last_fill và peak hiện tại (gọi sau mỗi fill)."""
        want = self._desired_orders()
        if self.sticky_orders and self._placed_qty == self.qty:
            caps = getattr(self.venue, "caps", None)
            native = bool(caps is not None and caps.native_trailing)
            if Counter(self._order_key(o, native) for o in want) == Counter(self._order_key(o, native) for o in self.venue.open_orders(self.slot)):
                return
        self.venue.cancel_slot(self.slot)
        for o in want:
            self.venue.submit(o)
        self._placed_qty = self.qty

    # ─── Hành động ──────────────────────────────────────────────────────────
    def _status_by_pnl(self, price: float) -> PositionStatus:
        return PositionStatus.TP if policy.in_profit(price, self.avg, self.is_long) else PositionStatus.SL

    def _enrich(self, fill: Fill, **kw) -> Fill:
        """Thông tin do policy quyết định (venue không biết): tracker ghi cùng các trường này vào Fill."""
        return dataclasses.replace(fill, **kw)

    def _apply_close(self, fill: Fill) -> PositionModel:
        pos = self.book.apply_close(fill)
        self.venue.cancel_slot(self.slot)
        self.is_open = False
        self.pending_exit = False
        self.last_close_time = fill.t
        self._reset_state()
        return pos

    def _close_market(self, status: PositionStatus, reason: str, kind: str) -> PositionModel:
        self._submit(OrderKind.EXIT, not self.is_long, reason=reason)
        ev = self.venue.next_event(self.slot)
        return self._apply_close(self._enrich(ev, kind=kind, status=int(status), mae_usd=self.mae_usd))

    def _enter(self, margin: float, reason: str) -> bool:
        """Lệnh vào tầng đầu (market ở open). False nếu bị từ chối (ngân sách / vốn)."""
        self._submit(OrderKind.ENTRY, self.is_long, notional=margin * self.pos_leverage, margin=margin, reason=reason)
        ev = self.venue.next_event(self.slot)
        if isinstance(ev, OrderRejected):
            self.book.reject(ev.reason, "entry", ev.order_id)
            return False
        self.book.apply_fill(self._enrich(ev, unit_pct=self.unit_pct, leverage_used=self.pos_leverage, risk_usd=self.planned_risk))
        self.peak = ev.price
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
            margin = policy.flat_margin(self.equity, self.order_size_pct)
        if self.risk_scale != 1.0:                            # danh mục đang sụt vốn: thu nhỏ lệnh mới
            margin = margin * self.risk_scale
            self.planned_risk = self.planned_risk * self.risk_scale
        margin = policy.clamp_margin(margin, budget, self.pos_leverage, self.fee_rate, self.max_new_notional)
        if self.sizing == "risk" and margin > 0:
            total_mult = self._layer_mult_total()
            self.planned_risk = min(self.planned_risk, policy.planned_risk_cap(
                margin, self.pos_leverage, self.sl_pct,
                policy.round_trip_cost(self.fee_rate, self.slippage_rate, None, margin * self.pos_leverage * total_mult), total_mult))
        # vượt trần rủi ro đang mở của danh mục
        margin, self.planned_risk = policy.apply_risk_ceiling(margin, self.planned_risk, self.max_new_risk)
        if margin <= 0:
            self.book.reject("no_margin", "entry")  # tín hiệu vào lệnh nhưng không còn vốn trống: ledger.rejected += 1
            return
        if self._enter(margin, "Tín hiệu vào lệnh (AST match)"):
            self.next_margin = margin

    def _layer_mult_total(self) -> float:
        return policy.layer_mult_total(self.dca_mults, len(self.dca_steps))

    def _risk_margin(self) -> float:
        margin, self.pos_leverage, self.planned_risk = policy.risk_margin(
            self.equity, self.risk_pct, self.max_notional_pct, self.sl_pct, self.fee_rate, self.slippage_rate,
            None, self.market == "perp", self.max_leverage, self.mmr, self.pos_leverage, self._layer_mult_total())
        return margin

    # ─── Một nến ────────────────────────────────────────────────────────────
    def on_bar(self, t: int, o: float, h: float, l: float, c: float,
               entry_signal: bool, stop_signal: bool, can_open: bool = True,
               vol: float = float("nan"), dca_gate: bool = True) -> Optional[PositionModel]:
        """Một nến 1m có giao dịch — cùng chữ ký và kết quả với `PositionTracker.on_bar` (= `on_bar_open` + `on_bar_rest`; trả vị thế vừa đóng)."""
        closed = self.on_bar_open(t, o, h, l, c, can_open)
        return self.on_bar_rest(t, o, h, l, c, entry_signal, stop_signal, closed, vol, dca_gate)

    def on_bar_open(self, t: int, o: float, h: float, l: float, c: float, can_open: bool = True) -> Optional[PositionModel]:
        """Pha MỞ nến (như `PositionTracker.on_bar_open`): báo nến cho venue, thoát chờ / hết thời gian giữ ở open, vào lệnh chờ ở open."""
        closed: Optional[PositionModel] = None
        begin_bar = getattr(self.venue, "begin_bar", None)
        if begin_bar is not None:
            begin_bar(self.slot, t, o, h, l, c, self)

        # 1. Đầu nến
        if self.is_open:
            if self.pending_exit:
                closed = self._close_market(self._status_by_pnl(o), _EXIT_REASON, "exit")
            elif self.timeout_ms and t - self.entry_time >= self.timeout_ms:
                closed = self._close_market(self._status_by_pnl(o), _TIMEOUT_REASON, "timeout")
        if closed is None and not self.is_open and self.pending_entry:
            self.pending_entry = False
            if can_open:
                self._open(t, o)
        return closed

    def on_bar_rest(self, t: int, o: float, h: float, l: float, c: float, entry_signal: bool, stop_signal: bool,
                    closed: Optional[PositionModel] = None, vol: float = float("nan"), dca_gate: bool = True) -> Optional[PositionModel]:
        """Pha TRONG nến + cuối nến (như `PositionTracker.on_bar_rest`); `closed` = kết quả `on_bar_open` cùng nến."""
        # 2-3. Trong nến
        if self.is_open and closed is None:
            self.book.mark(h, l)
            closed = self._intrabar()

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

    def _close_event(self, fill: Fill) -> PositionModel:
        """Fill đóng do venue sinh (SL / TRAIL / LIQ / TP / sàn đã đóng): gắn trạng thái + MAE rồi áp."""
        if fill.kind == "liq":
            status = PositionStatus.LIQ
        elif fill.kind == "tp":
            status = PositionStatus.TP
        elif fill.kind == "sl":
            status = PositionStatus.SL
        else:
            status = self._status_by_pnl(fill.raw_price)   # trailing: lãi hay lỗ theo giá khớp (trước trượt)
        extra = {}
        if not fill.reason:                                # OKX suy kind từ vị thế biến mất: không có nhãn lệnh -> nhãn theo loại
            extra["reason"] = {"sl": _SL_REASON, "tp": _TP_REASON, "trail": _TRAIL_REASON}.get(fill.kind, _EXCHANGE_CLOSE_REASON)
        return self._apply_close(self._enrich(fill, status=int(status), mae_usd=self.mae_usd, **extra))

    def _handle(self, ev) -> Optional[PositionModel]:
        """Một sự kiện của venue khi vị thế đang mở. DCA bị từ chối (ngân sách / vốn / sàn): cắt các tầng còn lại; DCA khớp: áp, tính lại lệnh chờ
        từ avg mới; lệnh bảo vệ bị từ chối: chỉ ghi sổ (bot cảnh báo; nến sau đặt lại); đóng: áp. Trả vị thế vừa đóng, None nếu vẫn mở."""
        if isinstance(ev, OrderRejected):
            self.book.reject(ev.reason, ev.kind, ev.order_id)
            if ev.kind == "dca":
                self.dca_rejected += 1
                self.dca_steps = self.dca_steps[: self.layer_count - 1]   # không nhồi thêm tầng nào nữa
            return None
        if ev.kind == "dca":
            self.book.apply_fill(self._enrich(ev, unit_pct=self.unit_pct, leverage_used=self.pos_leverage, risk_usd=self.planned_risk))
            self.next_margin = ev.margin
            self._place_orders()                            # avg / last_fill đổi: tính lại SL, TRAIL, DCA kế, TP
            return None
        return self._close_event(ev)

    def sync_events(self) -> Optional[PositionModel]:
        """Bot sàn: kéo và áp mọi sự kiện venue đã có (poll: DCA khớp, SL/TP/trailing khớp, sàn đóng vị thế) — DCA khớp thì SL/TP mới đặt ngay từ avg mới.
        Trả vị thế vừa đóng (nếu có). Không làm gì khi slot chưa mở."""
        if not self.is_open:
            return None
        while True:
            ev = self.venue.next_event(self.slot)
            if ev is None:
                return None
            closed = self._handle(ev)
            if closed is not None:
                return closed

    def _intrabar(self) -> Optional[PositionModel]:
        self._place_orders()
        while True:
            ev = self.venue.next_event(self.slot)
            if ev is None:
                break
            closed = self._handle(ev)
            if closed is not None:
                return closed
        end_adverse = getattr(self.venue, "end_adverse", None)
        if end_adverse is not None:
            end_adverse(self.slot)
        ev = self.venue.next_event(self.slot)               # phía có lợi: TP
        if ev is not None:
            return self._close_event(ev)
        return None

    def force_close(self, t: int, raw_price: float, reason: str = "End of Backtest") -> Optional[PositionModel]:
        if not self.is_open:
            return None
        self.pending_entry = False
        quote = getattr(self.venue, "quote", None)
        if quote is not None:
            quote(self.slot, t, raw_price)
        return self._close_market(PositionStatus.CANCEL, reason, "kill" if reason.startswith("Kill") else "end")
