"""SimVenue (P6.4) — sàn mô phỏng theo nến, cài `Venue` (venue.py) cho backtest-py / paper.

Khớp lệnh theo nến 1m với chính sách trong nến `intrabar_path="adverse_first"` — tái hiện NGUYÊN VĂN `PositionTracker._intrabar`:

1. Lệnh market ENTRY / EXIT khớp ở giá open (đã gồm trượt giá taker), theo thứ tự đặt.
2. Phía BẤT LỢI: trong các lệnh chờ DCA (limit), SL, TRAIL và giá thanh lý (sinh từ `position_view`, chỉ perp), lệnh nào ĐÃ CHẠM
   (long: low <= mức; short: high >= mức) thì chọn mức chạm TRƯỚC: long = mức cao nhất, short = thấp nhất; hoà mức -> thoát
   (SL/TRAIL/LIQ, ưu tiên 0) trước DCA (ưu tiên 1); hoà tiếp -> theo thứ tự DCA, SL, TRAIL, LIQ. Giá open đã vượt mức -> khớp ở open (gap).
   `stop_fill="extreme"`: SL/TRAIL khớp ở giá xấu nhất của nến. DCA có `trigger` (limit_through): phải đi QUA mức mới khớp, nhưng
   khớp ở giá đặt (level). Sau mỗi fill vị thế đổi (DCA) người đặt lệnh tính lại lệnh chờ rồi gọi `next_event` tiếp.
3. `end_adverse(slot)` chuyển sang phía CÓ LỢI: TP (limit từ giá TB) chỉ xét nếu trong nến KHÔNG có DCA khớp; khớp ở max(level, open) (long).
4. Peak của trailing do người đặt lệnh giữ và chỉ đổi cuối nến (trailing dùng đỉnh các nến TRƯỚC) — venue chỉ nhận mức TRAIL tĩnh.

Venue không đụng vào sổ vốn: kiểm tra trước giao dịch (ngân sách vị thế, giữ chỗ vốn) là `gate` do người đặt lệnh cấp cho từng slot;
gate từ chối -> `OrderRejected` và KHÔNG tiêu id (id `Fill.order_id` lấy từ `tracker._next_id()` lúc khớp, đúng thứ tự gọi của tracker).
Chưa hỗ trợ móc fill-model của AMM (`limit_taker`, `impact_fn`): DEX nằm ngoài P6 -> raise.
"""
from dataclasses import dataclass, field
from math import isnan
from typing import Callable, Dict, List, Optional, Protocol, Union

from backend.core.execute import policy
from backend.core.execute.events import Fill, OrderRejected
from backend.core.execute.tracker import _next_id
from backend.core.execute.venue import Order, OrderKind, VenueCaps

# gate(kind, margin, fee, fill_price) -> None (chấp nhận) | lý do từ chối ("budget" | "capital")
Gate = Callable[[str, float, float, float], Optional[str]]


def _trigger(order: Order) -> float:
    """Mức phải đi tới để lệnh limit khớp: `trigger` (limit_through) nếu có, không thì `level`."""
    return order.level if isnan(order.trigger) else order.trigger


class PositionView(Protocol):
    """Cửa sổ ĐỌC vào vị thế của slot (đối tượng sống: venue đọc lại sau mỗi fill, người đặt lệnh không cần đẩy cập nhật)."""
    avg: float
    qty: float
    pos_leverage: float
    mmr: float
    is_long: bool
    market: str          # "perp" -> venue sinh giá thanh lý; "spot" -> không


@dataclass
class _Slot:
    fee_rate: float
    maker_fee_rate: float
    slippage_rate: float
    stop_fill: str
    gate: Optional[Gate]
    orders: List[Order] = field(default_factory=list)     # lệnh chờ (DCA / SL / TRAIL / TP)
    market: List[Order] = field(default_factory=list)     # lệnh market chờ khớp ở giá quote (ENTRY / EXIT)
    view: Optional[PositionView] = None
    phase: str = "adverse"
    t: int = 0
    o: float = float("nan")
    h: float = float("nan")
    l: float = float("nan")
    c: float = float("nan")
    quoted: bool = False
    dca_filled: bool = False


class SimVenue:
    caps = VenueCaps(generates_liquidation=True, native_trailing=False, post_only=False, rounds_qty=False)
    intrabar_path = "adverse_first"

    def __init__(self) -> None:
        self._slots: Dict[int, _Slot] = {}

    # ─── cấu hình ───────────────────────────────────────────────────────────
    def add_slot(self, slot: int, *, fee_rate: float, maker_fee_rate: float, slippage_rate: float, stop_fill: str = "level",
                 gate: Optional[Gate] = None, limit_taker: bool = False, impact_fn=None) -> None:
        """Đăng ký slot với chi phí khớp của nó. gate = kiểm tra trước giao dịch cho lệnh vào / DCA (None = luôn chấp nhận)."""
        if limit_taker or impact_fn is not None:
            raise NotImplementedError("SimVenue chưa hỗ trợ limit_taker / impact_fn (AMM/DEX nằm ngoài P6)")
        if stop_fill not in ("level", "extreme"):
            raise ValueError(f"stop_fill phải là 'level' hoặc 'extreme', nhận '{stop_fill}'")
        self._slots[slot] = _Slot(float(fee_rate), float(maker_fee_rate), float(slippage_rate), stop_fill, gate)

    # ─── Venue ──────────────────────────────────────────────────────────────
    def submit(self, order: Order) -> None:
        st = self._slots[order.slot]
        if order.kind in (OrderKind.ENTRY, OrderKind.EXIT):
            if not st.quoted:
                raise RuntimeError("SimVenue: lệnh market cần giá quote (gọi begin_bar hoặc quote trước)")
            st.market.append(order)
        else:
            st.orders.append(order)

    def cancel(self, order_id: int) -> None:
        for st in self._slots.values():
            st.orders = [o for o in st.orders if o.id != order_id]
            st.market = [o for o in st.market if o.id != order_id]

    def cancel_slot(self, slot: int) -> None:
        st = self._slots[slot]
        st.orders.clear()
        st.market.clear()

    def open_orders(self, slot: int) -> List[Order]:
        st = self._slots[slot]
        return list(st.market) + list(st.orders)

    def next_event(self, slot: int) -> Optional[Union[Fill, OrderRejected]]:
        st = self._slots[slot]
        if st.market:
            return self._match_market(slot, st, st.market.pop(0))
        if st.view is None:
            return None
        if st.phase == "adverse":
            return self._match_adverse(slot, st)
        if st.phase == "favorable":
            return self._match_favorable(slot, st)
        return None

    # ─── theo nến ───────────────────────────────────────────────────────────
    def quote(self, slot: int, t: int, price: float) -> None:
        """Giá tham chiếu cho lệnh market ngoài vòng nến (ví dụ đóng cuối kỳ / kill switch)."""
        st = self._slots[slot]
        st.t, st.o, st.quoted = int(t), float(price), True

    def begin_bar(self, slot: int, t: int, o: float, h: float, l: float, c: float, position_view: PositionView) -> None:
        """Bắt đầu nến của slot: đặt quote = open, phía bất lợi mở. position_view (đối tượng sống) cho qty / avg / thanh lý."""
        st = self._slots[slot]
        st.t, st.o, st.h, st.l, st.c, st.quoted = int(t), o, h, l, c, True
        st.view = position_view
        st.phase = "adverse"
        st.dca_filled = False

    def end_adverse(self, slot: int) -> None:
        """Chuyển sang phía CÓ LỢI của nến (TP)."""
        self._slots[slot].phase = "favorable"

    # ─── khớp lệnh ──────────────────────────────────────────────────────────
    def _match_market(self, slot: int, st: _Slot, order: Order) -> Union[Fill, OrderRejected]:
        is_long = st.view.is_long if st.view is not None else order.is_buy
        raw = st.o
        if order.kind == OrderKind.ENTRY:
            slip = st.slippage_rate
            price = policy.entry_fill_price(raw, slip, is_long)
            fee = policy.entry_fee(order.notional, st.fee_rate)
            reason = st.gate("entry", order.margin, fee, price) if st.gate is not None else None
            if reason is not None:
                return OrderRejected(slot, order.id, "entry", reason)
            return Fill(slot=slot, order_id=_next_id(), kind="entry", t=st.t, price=price, raw_price=raw, notional=order.notional,
                        margin=order.margin, fee=fee, slip=slip, liquidity="taker", reason=order.reason)
        return self._close_fill(slot, st, "exit", raw, order.reason, taker=True)

    def _close_fill(self, slot: int, st: _Slot, kind: str, raw: float, reason: str, taker: bool, liq: bool = False) -> Fill:
        """Fill đóng hết vị thế (thứ tự phép toán y `PositionTracker._close`). Xoá mọi lệnh chờ của slot."""
        is_long, qty = st.view.is_long, st.view.qty
        slip = 0.0
        if taker and not liq:
            slip = st.slippage_rate
            price = policy.exit_fill_price(raw, slip, is_long)
        else:
            price = raw
        fee = policy.exit_fee(qty, price, st.fee_rate if taker or liq else st.maker_fee_rate)
        st.orders.clear()
        st.market.clear()
        return Fill(slot=slot, order_id=_next_id(), kind=kind, t=st.t, price=price, raw_price=raw, notional=0.0, margin=0.0,
                    fee=fee, slip=slip, liquidity="liquidation" if liq else ("taker" if taker else "maker"), reason=reason)

    def _first(self, st: _Slot, kind: OrderKind) -> Optional[Order]:
        for o in st.orders:
            if o.kind == kind:
                return o
        return None

    def _match_adverse(self, slot: int, st: _Slot) -> Optional[Union[Fill, OrderRejected]]:
        view = st.view
        is_long = view.is_long
        adverse = st.l if is_long else st.h
        by_kind: Dict[str, Order] = {}
        events = []   # (mức, ưu tiên khi hoà: thoát trước, loại) — thứ tự DCA, SL, TRAIL, LIQ như tracker
        for kind, name, prio in ((OrderKind.DCA, "dca", 1), (OrderKind.SL, "sl", 0), (OrderKind.TRAIL, "trail", 0)):
            od = self._first(st, kind)
            if od is not None:
                by_kind[name] = od
                events.append((_trigger(od), prio, name))
        liq = None
        if view.market == "perp" and view.qty > 0:
            liq = policy.liq_price(view.avg, view.pos_leverage, view.mmr, is_long)
            if liq > 0:
                events.append((liq, 0, "liq"))
        reached = [e for e in events if policy.reached(e[0], adverse, is_long)]
        if not reached:
            return None
        level, _, kind = policy.pick_first_touched(reached, is_long)
        if kind == "dca":
            od = by_kind["dca"]
            price = policy.gap_fill(od.level, st.o, is_long)        # limit khớp ở giá đặt (hoặc open nếu gap qua mức)
            fee = policy.entry_fee(od.notional, st.maker_fee_rate)
            st.orders.remove(od)
            reason = st.gate("dca", od.margin, fee, price) if st.gate is not None else None
            if reason is not None:
                return OrderRejected(slot, od.id, "dca", reason)
            st.dca_filled = True
            return Fill(slot=slot, order_id=_next_id(), kind="dca", t=st.t, price=price, raw_price=price, notional=od.notional,
                        margin=od.margin, fee=fee, slip=0.0, liquidity="maker", reason=od.reason)
        price = policy.gap_fill(level, st.o, is_long)
        if kind == "liq":
            return self._close_fill(slot, st, "liq", price, "Thanh lý (perp)", taker=False, liq=True)
        if st.stop_fill == "extreme":
            price = policy.stop_extreme_fill(price, adverse, is_long)   # bi quan: stop-market khớp ở giá xấu nhất của nến
        return self._close_fill(slot, st, kind, price, by_kind[kind].reason, taker=True)

    def _match_favorable(self, slot: int, st: _Slot) -> Optional[Fill]:
        tp = self._first(st, OrderKind.TP)
        if tp is None or st.dca_filled:     # không giả định "vừa nhồi ở đáy vừa chốt ở đỉnh" trong cùng một nến
            return None
        is_long = st.view.is_long
        need = _trigger(tp)
        favorable = st.h if is_long else st.l
        if not policy.tp_hit(favorable, need, is_long):
            return None
        raw = policy.tp_fill_price(tp.level, st.o, is_long)
        return self._close_fill(slot, st, "tp", raw, tp.reason, taker=False)
