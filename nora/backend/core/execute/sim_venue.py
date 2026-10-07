"""SimVenue (P6.4) — sàn mô phỏng theo nến, cài `Venue` (venue.py) cho backtest-py / paper.

Khớp lệnh theo nến với chính sách đường giá trong nến `intrabar_path` (mỗi slot một giá trị, do manager truyền qua `add_slot`) — tái hiện
NGUYÊN VĂN `PositionTracker._intrabar`:

**"ohlc" (mặc định, = NautilusTrader) / "adaptive"** (`_match_path`): nến là đường O -> H -> L -> C (adaptive: cực gần open trước; `policy.bar_points`).
Mỗi chặng là MỘT tick: venue trả lần lượt (a) các fill DCA mà chặng xuyên qua (từ gần ra xa; sau mỗi fill manager đặt lại lệnh, tầng kế tính từ
giá khớp), (b) chốt lời (limit, khớp ở mức TP), (c) lệnh stop: SL, TRAIL, thanh lý — mức bị xuyên cao nhất trước (long). SL / TP là lệnh đã nằm
trên sàn từ cuối nến trước: venue ĐÓNG BĂNG mức của chúng ở lần `next_event` đầu của nến (manager đặt lại từ avg mới sau fill DCA chỉ có hiệu lực
từ nến sau). Stop-market khớp ở mức kích hoạt; tick mở cửa (gap) thì ở open. TRAIL: venue giữ đỉnh/đáy chạy theo từng chặng (khởi tạo từ `Order.peak`),
kích hoạt theo `activation_pct` và avg hiện tại, mức = `callback_pct`% khỏi đỉnh sau chặng trước (không có `peak` -> dùng `level` tĩnh như cũ).
Cuối nến (`end_adverse` -> `_match_favorable`): nếu nến có fill DCA và TP đặt lại từ avg mới đã "trong giá" ở close -> khớp ngay ở close (taker).

**"adverse_first"** (cũ, giữ nguyên từng bit — slot cũ trong paper.pkl mặc định như vậy):

1. Lệnh market ENTRY / EXIT khớp ở giá open (đã gồm trượt giá taker), theo thứ tự đặt.
2. Phía BẤT LỢI: trong các lệnh chờ DCA (limit), SL, TRAIL và giá thanh lý (sinh từ `position_view`, chỉ perp), lệnh nào ĐÃ CHẠM
   (long: low <= mức; short: high >= mức) thì chọn mức chạm TRƯỚC: long = mức cao nhất, short = thấp nhất; hoà mức -> thoát
   (SL/TRAIL/LIQ, ưu tiên 0) trước DCA (ưu tiên 1); hoà tiếp -> theo thứ tự DCA, SL, TRAIL, LIQ. Giá open đã vượt mức stop-market
   (SL/TRAIL/LIQ) -> khớp ở open (gap).
   `stop_fill="extreme"`: SL/TRAIL khớp ở giá xấu nhất của nến. DCA có `trigger` (limit_through): phải đi QUA mức mới khớp, và luôn
   khớp ở giá đặt (level), kể cả khi open đã gap qua mức (quy tắc bảo thủ 2026-10-06: phần giá tốt hơn thuộc về bên khớp lệnh).
   Sau mỗi fill vị thế đổi (DCA) người đặt lệnh tính lại lệnh chờ rồi gọi `next_event` tiếp, NHƯNG lệnh SL cũ vẫn nằm trên sàn:
   từ sau fill DCA đầu tiên của nến, mức SL dùng trong phần còn lại của nến là mức SL cũ (`_Slot.stale_sl`); SL mới có hiệu lực từ nến sau.
   Giá thanh lý vẫn tính lại ngay từ avg mới.
3. `end_adverse(slot)` chuyển sang phía CÓ LỢI: TP (limit từ giá TB) chỉ xét nếu trong nến KHÔNG có DCA khớp; khớp ở mức TP (level), kể cả khi open đã vượt mức.
4. Peak của trailing do người đặt lệnh giữ và chỉ đổi cuối nến (trailing dùng đỉnh các nến TRƯỚC) — venue chỉ nhận mức TRAIL tĩnh.

Venue không đụng vào sổ vốn: kiểm tra trước giao dịch (ngân sách vị thế, giữ chỗ vốn) là `gate` do người đặt lệnh cấp cho từng slot;
gate từ chối -> `OrderRejected` và KHÔNG tiêu id (id `Fill.order_id` lấy từ `tracker._next_id()` lúc khớp, đúng thứ tự gọi của tracker).
Chưa hỗ trợ móc fill-model của AMM (`limit_taker`, `impact_fn`): DEX nằm ngoài P6 -> raise.
"""
import math
from collections import deque
from dataclasses import dataclass, field
from math import isnan
from typing import Callable, Deque, Dict, List, Optional, Protocol, Union

from backend.core import position_size as policy
from backend.core.models import Fill, OrderRejected
from backend.core.execute.tracker import _next_id
from backend.core.execute.venue import Order, OrderKind, VenueCaps

_KIND_NAME = {OrderKind.ENTRY: "entry", OrderKind.EXIT: "exit", OrderKind.DCA: "dca", OrderKind.SL: "sl", OrderKind.TRAIL: "trail", OrderKind.TP: "tp"}

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
    qty_step: float = 0.0
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
    stale_sl: Optional[float] = None    # mức SL cũ còn hiệu lực sau fill DCA đầu tiên của nến (None = chưa có DCA khớp / không có SL)
    # ── đường ohlc / adaptive ──
    intrabar_path: str = "ohlc"
    pts: tuple = ()                     # bốn điểm giá của nến theo thứ tự đi qua
    tick_i: int = 0                     # chặng đang xử lý (0 = tick mở cửa)
    prev: float = float("nan")          # giá chặng trước (chặng không đổi giá bị bỏ qua)
    frozen: bool = False                # đã đóng băng SL / TP của nến chưa
    sl_lv: Optional[float] = None       # mức SL cố định cả nến (None = không có SL)
    sl_reason: str = ""
    tp_lv: Optional[float] = None       # mức TP cố định cả nến (None = không có TP)
    tp_need: float = float("nan")
    tp_reason: str = ""
    peak: float = float("nan")          # đỉnh/đáy có lợi chạy theo chặng (trailing); nan = không có TRAIL
    rejects: Deque[OrderRejected] = field(default_factory=deque)   # lệnh bị từ chối ngay lúc đặt (hợp đồng venue.py): trả ở next_event trước mọi khớp

    def __setstate__(self, state) -> None:
        """Pickle cũ (paper.pkl của bot đang chạy, trước P6.8b) chưa có `rejects`."""
        self.__dict__.update(state)
        self.__dict__.setdefault("rejects", deque())
        self.__dict__.setdefault("stale_sl", None)
        self.__dict__.setdefault("qty_step", 0.0)
        for k, v in (("intrabar_path", "adverse_first"), ("pts", ()), ("tick_i", 0), ("prev", float("nan")), ("frozen", False),
                     ("sl_lv", None), ("sl_reason", ""), ("tp_lv", None), ("tp_need", float("nan")), ("tp_reason", ""), ("peak", float("nan"))):
            self.__dict__.setdefault(k, v)     # slot cũ (trước intrabar_path) giữ chính sách cũ để vị thế đang mở không đổi ngữ nghĩa giữa chừng


class SimVenue:
    caps = VenueCaps(generates_liquidation=True, native_trailing=False, post_only=False, rounds_qty=False)

    def __init__(self, post_only: bool = False, rounds_qty: bool = False) -> None:
        if post_only or rounds_qty:
            self.caps = VenueCaps(generates_liquidation=True, native_trailing=False, post_only=post_only, rounds_qty=rounds_qty)
        self._slots: Dict[int, _Slot] = {}

    # ─── cấu hình ───────────────────────────────────────────────────────────
    def add_slot(self, slot: int, *, fee_rate: float, maker_fee_rate: float, slippage_rate: float, stop_fill: str = "level",
                 gate: Optional[Gate] = None, limit_taker: bool = False, impact_fn=None, intrabar_path: str = "ohlc",
                 qty_step: float = 0.0) -> None:
        """Đăng ký slot với chi phí khớp của nó. gate = kiểm tra trước giao dịch cho lệnh vào / DCA (None = luôn chấp nhận).
        intrabar_path = "ohlc" | "adaptive" | "adverse_first" (xem docstring module)."""
        if limit_taker or impact_fn is not None:
            raise NotImplementedError("SimVenue chưa hỗ trợ limit_taker / impact_fn (AMM/DEX nằm ngoài P6)")
        if stop_fill not in ("level", "extreme"):
            raise ValueError(f"stop_fill phải là 'level' hoặc 'extreme', nhận '{stop_fill}'")
        if intrabar_path not in policy.INTRABAR_PATHS:
            raise ValueError(f"intrabar_path phải là một trong {policy.INTRABAR_PATHS}, nhận '{intrabar_path}'")
        self._slots[slot] = _Slot(float(fee_rate), float(maker_fee_rate), float(slippage_rate), stop_fill, gate,
                                  qty_step=float(qty_step), intrabar_path=intrabar_path)

    # ─── Venue ──────────────────────────────────────────────────────────────
    def submit(self, order: Order) -> None:
        st = self._slots[order.slot]
        has_pos = st.view is not None and st.view.qty > 0
        if order.kind == OrderKind.ENTRY and (has_pos or any(o.kind == OrderKind.ENTRY for o in st.market)):
            st.rejects.append(OrderRejected(order.slot, order.id, "entry", "position_exists"))     # như OkxVenue: tối đa một vị thế mỗi slot
            return
        if order.kind in (OrderKind.DCA, OrderKind.SL, OrderKind.TRAIL, OrderKind.TP) and not has_pos:
            st.rejects.append(OrderRejected(order.slot, order.id, _KIND_NAME[order.kind], "no_position"))
            return
        if self.caps.post_only and getattr(order, "post_only", False):
            ref_px = st.prev if (not isnan(st.prev) and st.prev > 0) else (st.o if st.quoted else float("nan"))
            if not isnan(ref_px) and ref_px > 0 and not isnan(order.level):
                if (order.is_buy and order.level >= ref_px) or (not order.is_buy and order.level <= ref_px):
                    st.rejects.append(OrderRejected(order.slot, order.id, _KIND_NAME.get(order.kind, "order"), "post_only"))
                    return
        if self.caps.rounds_qty and st.qty_step > 0 and order.kind in (OrderKind.ENTRY, OrderKind.DCA):
            px = st.o if (order.kind == OrderKind.ENTRY and st.quoted) else order.level
            if px > 0 and order.notional > 0:
                raw_qty = order.notional / px
                rounded_steps = math.floor(raw_qty / st.qty_step + 1e-12)
                if rounded_steps <= 0:
                    st.rejects.append(OrderRejected(order.slot, order.id, _KIND_NAME.get(order.kind, "order"), "min_size"))
                    return
                order.notional = rounded_steps * st.qty_step * px
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
        if st.rejects:
            return st.rejects.popleft()
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
        st.stale_sl = None
        st.frozen = False
        st.tick_i = 0
        st.prev = o
        st.peak = float("nan")
        st.pts = () if st.intrabar_path == "adverse_first" else policy.bar_points(st.intrabar_path, o, h, l, c)

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
            notional = order.notional
            if self.caps.rounds_qty and st.qty_step > 0 and raw > 0:
                steps = math.floor(notional / raw / st.qty_step + 1e-12)
                notional = steps * st.qty_step * price
            fee = policy.entry_fee(notional, st.fee_rate)
            reason = st.gate("entry", order.margin, fee, price) if st.gate is not None else None
            if reason is not None:
                return OrderRejected(slot, order.id, "entry", reason)
            return Fill(slot=slot, order_id=_next_id(), kind="entry", t=st.t, price=price, raw_price=raw, notional=notional,
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

    def _match_path(self, slot: int, st: _Slot) -> Optional[Union[Fill, OrderRejected]]:
        """Đường ohlc / adaptive: kéo fill kế tiếp của tick hiện tại; hết tick thì sang chặng sau (xem docstring module)."""
        view = st.view
        is_long = view.is_long
        if not st.frozen:                   # SL / TP đã nằm trên sàn từ cuối nến trước (manager vừa đặt): mức cố định cả nến
            st.frozen = True
            sl, tp, tr = self._first(st, OrderKind.SL), self._first(st, OrderKind.TP), self._first(st, OrderKind.TRAIL)
            if sl is not None:
                st.sl_lv, st.sl_reason = sl.level, sl.reason
            else:
                st.sl_lv = None
            if tp is not None:
                st.tp_lv, st.tp_need, st.tp_reason = tp.level, _trigger(tp), tp.reason
            else:
                st.tp_lv = None
            st.peak = tr.peak if tr is not None else float("nan")
        while st.tick_i < 4:
            p = st.pts[st.tick_i]
            if st.tick_i and p == st.prev:
                st.tick_i += 1
                continue
            ev = self._match_tick(slot, st, p, st.tick_i == 0)
            if ev is not None:
                return ev
            st.peak = policy.peak_step(st.peak, p, is_long)
            st.prev = p
            st.tick_i += 1
        return None

    def _match_tick(self, slot: int, st: _Slot, p: float, at_open: bool) -> Optional[Union[Fill, OrderRejected]]:
        """Fill kế tiếp mà tick giá `p` kích hoạt: (a) DCA, (b) TP, (c) stop (SL / TRAIL / thanh lý). None = tick hết việc."""
        view = st.view
        is_long = view.is_long
        sign = policy.sign_of(is_long)
        od = self._first(st, OrderKind.DCA)
        if od is not None and policy.reached(_trigger(od), p, is_long):
            price = od.level        # limit chờ sẵn khớp ĐÚNG ở giá đặt, kể cả khi gap qua mức
            fee = policy.entry_fee(od.notional, st.maker_fee_rate)
            st.orders.remove(od)
            reason = st.gate("dca", od.margin, fee, price) if st.gate is not None else None
            if reason is not None:
                return OrderRejected(slot, od.id, "dca", reason)
            st.dca_filled = True
            return Fill(slot=slot, order_id=_next_id(), kind="dca", t=st.t, price=price, raw_price=price, notional=od.notional,
                        margin=od.margin, fee=fee, slip=0.0, liquidity="maker", reason=od.reason)
        if st.tp_lv is not None and policy.tp_hit(p, st.tp_need, is_long):
            return self._close_fill(slot, st, "tp", st.tp_lv, st.tp_reason, taker=False)     # limit khớp ĐÚNG ở mức TP
        events = []     # (mức, ưu tiên, loại) — thứ tự SL, TRAIL, LIQ như tracker
        reasons = {"sl": st.sl_reason}
        if st.sl_lv is not None:
            events.append((st.sl_lv, 0, "sl"))
        tr = self._first(st, OrderKind.TRAIL)
        if tr is not None:
            if isnan(tr.peak):              # lệnh TRAIL không kèm đỉnh: mức tĩnh như đường cũ
                events.append((tr.level, 0, "trail"))
                reasons["trail"] = tr.reason
            elif policy.trail_active(st.peak, view.avg, tr.activation_pct, sign):
                events.append((policy.trail_level(st.peak, tr.callback_pct, sign), 0, "trail"))
                reasons["trail"] = tr.reason
        if view.market == "perp" and view.qty > 0:
            liq = policy.liq_price(view.avg, view.pos_leverage, view.mmr, is_long)
            if liq > 0:
                events.append((liq, 0, "liq"))
        reached = [e for e in events if policy.reached(e[0], p, is_long)]
        if not reached:
            return None
        level, _, kind = policy.pick_first_touched(reached, is_long)
        price = policy.tick_stop_price(level, st.o, is_long, at_open)
        if kind == "liq":
            return self._close_fill(slot, st, "liq", price, "Thanh lý (perp)", taker=False, liq=True)
        if st.stop_fill == "extreme":
            price = policy.stop_extreme_fill(price, st.l if is_long else st.h, is_long)
        return self._close_fill(slot, st, kind, price, reasons[kind], taker=True)

    def _match_adverse(self, slot: int, st: _Slot) -> Optional[Union[Fill, OrderRejected]]:
        if st.intrabar_path != "adverse_first":
            return self._match_path(slot, st)
        view = st.view
        is_long = view.is_long
        adverse = st.l if is_long else st.h
        by_kind: Dict[str, Order] = {}
        events = []   # (mức, ưu tiên khi hoà: thoát trước, loại) — thứ tự DCA, SL, TRAIL, LIQ như tracker
        for kind, name, prio in ((OrderKind.DCA, "dca", 1), (OrderKind.SL, "sl", 0), (OrderKind.TRAIL, "trail", 0)):
            od = self._first(st, kind)
            if od is not None:
                by_kind[name] = od
                lv = st.stale_sl if (name == "sl" and st.stale_sl is not None) else _trigger(od)   # SL cũ chưa dời kịp sau fill DCA
                events.append((lv, prio, name))
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
            price = od.level        # limit chờ sẵn khớp ĐÚNG ở giá đặt, kể cả khi gap qua mức
            fee = policy.entry_fee(od.notional, st.maker_fee_rate)
            st.orders.remove(od)
            reason = st.gate("dca", od.margin, fee, price) if st.gate is not None else None
            if reason is not None:
                return OrderRejected(slot, od.id, "dca", reason)
            if not st.dca_filled:
                sl_od = self._first(st, OrderKind.SL)
                st.stale_sl = sl_od.level if sl_od is not None else None   # SL đang nằm trên sàn trước fill (manager sắp đặt lại từ avg mới)
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
        if st.intrabar_path != "adverse_first":
            # TP đặt lại từ avg mới (sau fill DCA trong nến) thấy sổ lệnh ở close: đã "trong giá" -> khớp ngay ở close như lệnh taker
            if tp is None or not st.dca_filled or not policy.tp_hit(st.c, tp.level, st.view.is_long):
                return None
            return self._close_fill(slot, st, "tp", st.c, tp.reason, taker=True)
        if tp is None or st.dca_filled:     # không giả định "vừa nhồi ở đáy vừa chốt ở đỉnh" trong cùng một nến
            return None
        is_long = st.view.is_long
        need = _trigger(tp)
        favorable = st.h if is_long else st.l
        if not policy.tp_hit(favorable, need, is_long):
            return None
        raw = tp.level      # limit chờ sẵn khớp ĐÚNG ở mức TP, kể cả khi open đã vượt mức
        return self._close_fill(slot, st, "tp", raw, tp.reason, taker=False)
