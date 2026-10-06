"""OkxVenue (P6.7): cài `Venue` Protocol (core/execute/venue.py) trên client `OkxAdapter` — dịch I/O THUẦN, không chứa chính sách.
Đặc tả: docs/bmad/p6_execution_design.md §3 + §6. Sizing, mức SL/TP/DCA, kill switch ở PositionManager/policy; venue chỉ đổi Order <-> lệnh OKX
và đổi trạng thái vị thế OKX <-> Fill / OrderRejected. Không tự HTTP/ký: gọi lại các hàm của `okx.OkxAdapter`.

Ánh xạ lệnh
  ENTRY  prepare(lev) + market_open(sym, side, qty); qty = Filters.qty(notional / giá tham chiếu); Fill("entry") ở GIÁ KHỚP THẬT (vị thế sàn).
  EXIT   cancel_all + close_market; Fill đóng lấy giá/phí từ `closed_since` (lịch sử vị thế), kind = "exit" (hoặc kind của lệnh gọi — xem _exit).
  SL     place_sl (điều kiện, trigger theo giá giao dịch cuối, reduce-only); TP  place_tp (limit reduce-only).
  DCA    place_post_only; qty = Filters.qty(notional / level) (lệnh dưới minQty -> OrderRejected("min_size")).
  TRAIL  place_trailing (sàn bám đỉnh) khi client có hàm này (caps.native_trailing); ngược lại giữ làm lệnh CỤC BỘ (như Bot cũ: không gửi sàn),
         poll(now, bars) kiểm high/low của nến: chạm `level` thì đóng market và phát Fill("trail").
         Quy ước TRAIL gốc (P6.8b): Order.activation = giá KÍCH HOẠT (activePx), Order.callback_pct = callback % (vd 1.5 = 1.5%); Order.level là mức stop TĨNH
         của sim, KHÔNG dùng. Thiếu hai trường mới (nan) -> rơi về quy ước cũ (level = kích hoạt, trigger = callback). Thiếu callback -> OrderRejected.

Sự kiện (kéo): `submit` đẩy Fill/OrderRejected tức thì vào hàng đợi của slot (ENTRY/EXIT đồng bộ); `poll(now[, bars])` đọc positions() một lần cho mọi slot:
  - khối lượng tăng so với đã biết -> Fill("dca") cho từng tầng DCA chờ mà phần tăng phủ được (cùng suy luận Bot.reconcile; giá = mức tầng, maker);
  - vị thế biến mất -> Fill đóng; kind suy từ lệnh bảo vệ GẦN giá đóng nhất (sl / tp, trong dung sai `match_tol`), ngược lại "trail" nếu còn trailing
    chờ, ngược lại "exit". Dọn mọi lệnh còn sót (cancel_all) như Bot.reconcile.

Giới hạn so với SimVenue (cố ý, ghi rõ):
  - OkxAdapter KHÔNG có huỷ từng lệnh: `cancel_slot` = cancel_all(symbol) (không để lại lệnh bảo vệ mồ côi); `cancel(order_id)` = bỏ lệnh khỏi sổ rồi cancel_all +
    đặt lại các lệnh còn lại (SL, TP, TRAIL, DCA) — có khoảng ngắn không có SL giữa hai bước; cancel_all huỷ cả lệnh không do venue đặt trên mã đó.
  - Một slot / symbol (OKX net mode, ADR D1 max_per_symbol = 1): bind slot thứ hai trên cùng symbol -> SlotConflict.
  - Phí: Fill vào lệnh/DCA có fee = 0 (OKX không trả phí trong phản hồi đặt lệnh); Fill đóng mang TỔNG phí cả vòng (|fee| của positions-history) nên tổng phí đúng.
  - Fill.order_id = Order.id của lệnh (adapter không trả ordId của sàn); lãi lỗ thật lưu ở `last_close[slot]` (Fill không có trường pnl).
  - Không sinh Fill thanh lý (caps.generates_liquidation=False): thanh lý chỉ quan sát như vị thế biến mất.
  - Khối lượng giảm một phần (TP khớp một phần...) chỉ cập nhật qty đã biết, không phát sự kiện.
"""
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple, Union

from backend.core.execute.events import Fill, OrderRejected
from backend.core.execute.venue import Order, OrderKind, VenueCaps
from backend.live.exchange import ExchangeError, NotPermitted

EPS = 1e-12
MIN_SIZE_CODES = ("51020", "51121")          # OKX: dưới khối lượng tối thiểu / không là bội lotSz
PRIORITY = (OrderKind.SL, OrderKind.TP, OrderKind.TRAIL, OrderKind.DCA)   # thứ tự đặt lại: bảo vệ trước, tầng DCA sau
KIND_NAME = {OrderKind.ENTRY: "entry", OrderKind.EXIT: "exit", OrderKind.DCA: "dca", OrderKind.SL: "sl", OrderKind.TRAIL: "trail",
             OrderKind.TP: "tp"}


class SlotConflict(RuntimeError):
    """Hai slot cùng một symbol: OKX net mode chỉ có một vị thế và một giá TB mỗi symbol (ADR-P6 D1: max_per_symbol = 1)."""


@dataclass
class _Pos:
    side: str                  # "LONG" | "SHORT"
    qty: float                 # khối lượng (coin) đã biết
    avg: float
    leverage: float
    entry_time: int
    order_id: int


@dataclass
class _Slot:
    sym: str
    pos: Optional[_Pos] = None
    orders: Dict[int, Order] = field(default_factory=dict)      # lệnh chờ theo thứ tự đặt (DCA: thứ tự tầng)
    placed: set = field(default_factory=set)                    # id lệnh đã gửi sàn (TRAIL cục bộ thì không)
    dca_qty: Dict[int, float] = field(default_factory=dict)
    events: Deque[Union[Fill, OrderRejected]] = field(default_factory=deque)


class OkxVenue:
    def __init__(self, client, slots: Optional[Dict[int, str]] = None, clock: Optional[Callable[[], int]] = None,
                 match_tol: float = 0.005, close_retries: int = 3, settle_s: float = 0.5):
        self.client = client
        self.caps = VenueCaps(generates_liquidation=False, native_trailing=getattr(client, "place_trailing", None) is not None,
                              post_only=True, rounds_qty=True)
        self._clock = clock or (lambda: int(time.time() * 1000))
        self.match_tol, self.close_retries, self.settle_s = match_tol, max(1, int(close_retries)), settle_s
        self._slots: Dict[int, _Slot] = {}
        self._ref: Dict[int, float] = {}
        self.last_close: Dict[int, Dict[str, Any]] = {}          # dữ liệu closed_since của lần đóng gần nhất của slot (pnl, phí, giá...)
        for s, sym in (slots or {}).items():
            self.bind(s, sym)

    # ── slot <-> symbol ──
    def bind(self, slot: int, sym: str) -> None:
        for s, st in self._slots.items():
            if st.sym == sym and s != slot:
                raise SlotConflict(f"OKX net mode: symbol {sym} đã gắn slot {s}, không thể gắn thêm slot {slot} (max_per_symbol = 1)")
        if slot in self._slots and self._slots[slot].sym != sym:
            raise SlotConflict(f"slot {slot} đã gắn symbol {self._slots[slot].sym}, không đổi sang {sym}")
        self._slots.setdefault(slot, _Slot(sym))

    def release(self, slot: int) -> None:
        st = self._slots.get(slot)
        if st is not None and (st.pos is not None or st.orders):
            raise SlotConflict(f"slot {slot} còn vị thế / lệnh chờ — đóng hoặc cancel_slot trước khi release")
        self._slots.pop(slot, None)

    def set_ref(self, slot: int, price: float) -> None:
        """Giá tham chiếu cho ENTRY (qty = notional / giá, slip so với giá này): thường là close nến cuối. Order.level hữu hạn thì ưu tiên."""
        self._ref[slot] = float(price)

    def _st(self, slot: int) -> _Slot:
        if slot not in self._slots:
            raise KeyError(f"slot {slot} chưa gắn symbol (gọi bind(slot, sym) hoặc truyền slots={{...}})")
        return self._slots[slot]

    # ── Venue ──
    def submit(self, order: Order) -> None:
        st = self._st(order.slot)
        if order.kind == OrderKind.ENTRY:
            return self._entry(st, order)
        if order.kind == OrderKind.EXIT:
            return self._exit(st, order.slot, "exit", order.id, order.reason)
        if st.pos is None:
            return self._reject(st, order, "no_position")
        st.orders[order.id] = order
        why = self._place(order.slot, st, order)
        if why:
            st.orders.pop(order.id, None)
            self._reject(st, order, why)

    def cancel(self, order_id: int) -> None:
        for slot, st in self._slots.items():
            o = st.orders.pop(order_id, None)
            if o is None:
                continue
            if order_id in st.placed:                  # adapter không huỷ từng lệnh: huỷ hết rồi đặt lại phần còn lại
                st.placed.discard(order_id)
                self._resync(slot, st)
            return

    def cancel_slot(self, slot: int) -> None:
        st = self._st(slot)
        if st.placed or st.orders or st.pos is not None:   # có thể còn lệnh sàn dù sổ trống (vừa lỗi giữa chừng): luôn dọn theo symbol
            self.client.cancel_all(st.sym)
        st.orders.clear()
        st.placed.clear()
        st.dca_qty.clear()

    def open_orders(self, slot: int) -> List[Order]:
        return list(self._st(slot).orders.values())

    def next_event(self, slot: int) -> Optional[Union[Fill, OrderRejected]]:
        st = self._st(slot)
        return st.events.popleft() if st.events else None

    # ── poll: đọc vị thế sàn, suy ra Fill ──
    def poll(self, now: int, bars: Optional[Dict[str, Tuple[float, float, float]]] = None) -> int:
        """Đọc positions() một lần cho mọi slot đang có vị thế; trả số sự kiện mới. `bars` = {sym: (high, low, close)} (tuỳ chọn): cập nhật giá tham
        chiếu và kiểm TRAIL cục bộ (client không có trailing gốc)."""
        n0 = sum(len(s.events) for s in self._slots.values())
        live = {s: v for s, v in self.client.positions().items() if abs(v[0]) > EPS}
        for slot, st in self._slots.items():
            if st.pos is None:
                continue
            if bars and st.sym in bars:
                self._ref[slot] = float(bars[st.sym][2])
            cur = live.get(st.sym)
            if cur is None:
                self._on_gone(slot, st, now)
                continue
            amt, entry = abs(cur[0]), cur[1]
            p = st.pos
            if amt > p.qty * (1 + 1e-6):
                self._on_increase(slot, st, amt, entry, now)
            elif amt < p.qty * (1 - 1e-6):
                p.qty = amt                              # đóng một phần: chỉ đồng bộ khối lượng (xem docstring)
            if bars and st.sym in bars:
                self._local_trail(slot, st, bars[st.sym], now)
        return sum(len(s.events) for s in self._slots.values()) - n0

    # ── nội bộ: đặt lệnh ──
    def _entry(self, st: _Slot, o: Order) -> None:
        if st.pos is not None:
            return self._reject(st, o, "position_exists")
        f = self.client.filters(st.sym)
        ref = o.level if math.isfinite(o.level) and o.level > 0 else self._ref.get(o.slot, float("nan"))
        if not (math.isfinite(ref) and ref > 0):
            raise ValueError(f"ENTRY slot {o.slot}: thiếu giá tham chiếu (set_ref hoặc Order.level)")
        qty = f.qty(o.notional / ref)
        if f.check(qty, ref):
            return self._reject(st, o, "min_size")
        lev = max(1, int(round(o.notional / o.margin))) if o.margin > 0 else 1
        side = "LONG" if o.is_buy else "SHORT"
        try:
            self.client.prepare(st.sym, lev)
            px = float(self.client.market_open(st.sym, side, qty) or ref)
        except Exception as e:
            why = self._classify(o, e)
            if why is None:
                raise
            return self._reject(st, o, why)
        notional = qty * px
        slip = (px - ref) / ref * (1 if o.is_buy else -1)
        now = self._clock()
        st.pos = _Pos(side, qty, px, float(lev), now, o.id)
        st.events.append(Fill(slot=o.slot, order_id=o.id, kind="entry", t=now, price=px, raw_price=ref, notional=notional, margin=notional / lev,
                              fee=0.0, slip=slip, liquidity="taker", reason=o.reason, leverage_used=float(lev)))

    def _place(self, slot: int, st: _Slot, o: Order) -> Optional[str]:
        """Gửi một lệnh bảo vệ / DCA lên sàn. None = ổn; chuỗi = lý do từ chối (đã phân loại). Lỗi lạ -> ném lại."""
        f = self.client.filters(st.sym)
        side = st.pos.side
        try:
            if o.kind == OrderKind.SL:
                self.client.place_sl(st.sym, side, f.qty_close(st.pos.qty), f.price(o.level))
            elif o.kind == OrderKind.TP:
                self.client.place_tp(st.sym, side, f.qty_close(st.pos.qty), f.price(o.level))
            elif o.kind == OrderKind.TRAIL:
                if not self.caps.native_trailing:        # cục bộ: không gửi sàn, poll(bars) kiểm
                    return None
                cb = o.callback_pct if math.isfinite(o.callback_pct) else o.trigger      # thiếu trường mới -> quy ước cũ (trigger = callback %)
                act = o.activation if math.isfinite(o.activation) else o.level           # ... (level = giá kích hoạt)
                if not (cb > 0 and math.isfinite(cb)) or not (act > 0 and math.isfinite(act)):
                    return "no_callback"
                self.client.place_trailing(st.sym, side, f.qty_close(st.pos.qty), float(cb), f.price(act))
            elif o.kind == OrderKind.DCA:
                q = st.dca_qty.get(o.id)
                if q is None:
                    q = st.dca_qty[o.id] = f.qty(o.notional / o.level)
                px = f.price(o.level)
                if f.check(q, px):
                    return "min_size"
                self.client.place_post_only(st.sym, side, q, px)
            else:
                raise ValueError(f"loại lệnh không đặt chờ: {o.kind!r}")
        except ValueError:
            raise
        except Exception as e:
            why = self._classify(o, e)
            if why is None:
                raise
            return why
        st.placed.add(o.id)
        return None

    @staticmethod
    def _classify(o: Order, e: Exception) -> Optional[str]:
        """Lỗi sàn -> lý do OrderRejected; None = lỗi không phân loại được (ném lại cho caller)."""
        if isinstance(e, NotPermitted):
            return "not_permitted"
        if not isinstance(e, ExchangeError):
            return None
        msg = str(e)
        if any(c in msg for c in MIN_SIZE_CODES):
            return "min_size"
        if o.kind == OrderKind.DCA or o.post_only:      # như Bot._protect: post-only bị từ chối -> bỏ tầng, không đổi sang market
            return "post_only"
        return None

    def _reject(self, st: _Slot, o: Order, why: str) -> None:
        st.events.append(OrderRejected(slot=o.slot, order_id=o.id, kind=KIND_NAME[o.kind], reason=why))

    def _resync(self, slot: int, st: _Slot) -> None:
        keep = sorted(st.orders.values(), key=lambda x: PRIORITY.index(x.kind))
        self.client.cancel_all(st.sym)
        st.placed.clear()
        for o in keep:
            why = self._place(slot, st, o)
            if why:
                st.orders.pop(o.id, None)
                self._reject(st, o, why)

    # ── nội bộ: đóng ──
    def _close_info(self, sym: str, since: int) -> Dict[str, Any]:
        fetch = getattr(self.client, "closed_since", None)
        if fetch is None:
            return {}
        err = ""
        for k in range(self.close_retries):
            try:
                info = fetch(sym, int(since)) or {}
            except Exception as e:                       # không đọc được: vẫn đóng sổ, thiếu giá/phí thật
                info, err = {}, f"{type(e).__name__}: {e}"
            if info.get("close_price"):
                return info
            if k + 1 < self.close_retries and self.settle_s:
                time.sleep(self.settle_s)
        return {**info, "error": err} if err else info

    def _emit_close(self, slot: int, st: _Slot, kind: str, order_id: int, reason: str, now: int, fallback_px: float,
                    info: Optional[Dict[str, Any]] = None) -> None:
        p = st.pos
        if info is None:
            info = self._close_info(st.sym, p.entry_time)
        self.last_close[slot] = info
        px = float(info.get("close_price") or fallback_px or p.avg)
        lvl = next((o.level for o in st.orders.values() if KIND_NAME[o.kind] == kind and math.isfinite(o.level)), float("nan"))
        raw = lvl if math.isfinite(lvl) and lvl > 0 else px
        slip = (raw - px) / raw * (1 if p.side == "LONG" else -1) if kind in ("sl", "trail") else 0.0   # SL/trailing: market sau trigger
        st.events.append(Fill(slot=slot, order_id=order_id, kind=kind, t=now, price=px, raw_price=raw, notional=0.0, margin=0.0,
                              fee=abs(float(info.get("fee") or 0.0)), slip=slip, liquidity="maker" if kind == "tp" else "taker", reason=reason))
        st.pos = None
        st.orders.clear()
        st.placed.clear()
        st.dca_qty.clear()

    def _exit(self, st: _Slot, slot: int, kind: str, order_id: int, reason: str) -> None:
        self.client.cancel_all(st.sym)
        self.client.close_market(st.sym)
        if st.pos is None:
            return                                       # đã phẳng (close_market bỏ qua 51023): không có gì để ghi
        self._emit_close(slot, st, kind, order_id, reason, self._clock(), self._ref.get(slot, 0.0))

    def _on_gone(self, slot: int, st: _Slot, now: int) -> None:
        """Vị thế sàn biến mất (SL/TP/trailing khớp hoặc thanh lý): suy kind theo lệnh bảo vệ gần giá đóng nhất."""
        p = st.pos
        info = self._close_info(st.sym, p.entry_time)
        px = float(info.get("close_price") or 0.0)
        near = [(abs(o.level - px) / px, o) for o in st.orders.values() if o.kind in (OrderKind.SL, OrderKind.TP) and px > 0 and math.isfinite(o.level)]
        near.sort(key=lambda x: x[0])
        trail = next((o for o in st.orders.values() if o.kind == OrderKind.TRAIL), None)
        guard = [o for o in st.orders.values() if o.kind in (OrderKind.SL, OrderKind.TP, OrderKind.TRAIL)]
        if near and near[0][0] <= self.match_tol:
            o = near[0][1]
        elif trail is not None and (px > 0 or len(guard) == 1):
            o = trail
        elif px <= 0 and len(guard) == 1:
            o = guard[0]
        else:
            o = None
        kind = KIND_NAME[o.kind] if o is not None else "exit"
        self.client.cancel_all(st.sym)                   # dọn lệnh chờ còn sót (tầng DCA, bảo vệ đối ứng)
        self._emit_close(slot, st, kind, o.id if o is not None else p.order_id, "", now, self._ref.get(slot, 0.0), info)

    def _local_trail(self, slot: int, st: _Slot, bar: Tuple[float, float, float], now: int) -> None:
        if st.pos is None:
            return
        o = next((x for x in st.orders.values() if x.kind == OrderKind.TRAIL and x.id not in st.placed and math.isfinite(x.level)), None)
        if o is None:
            return
        hi, lo = float(bar[0]), float(bar[1])
        hit = lo <= o.level if st.pos.side == "LONG" else hi >= o.level
        if hit:
            self._exit(st, slot, "trail", o.id, o.reason)

    def _on_increase(self, slot: int, st: _Slot, amt: float, entry: float, now: int) -> None:
        """Khối lượng tăng: tầng DCA chờ nào phủ được phần tăng -> Fill("dca") (cùng suy luận Bot.reconcile, tolerance 1e-6)."""
        p = st.pos
        cum = p.qty
        for o in [x for x in st.orders.values() if x.kind == OrderKind.DCA]:
            q = st.dca_qty.get(o.id, 0.0)
            if q <= 0 or cum + q > amt * (1 + 1e-6):
                break
            cum += q
            f = self.client.filters(st.sym)
            px = f.price(o.level)
            notional = q * px
            st.events.append(Fill(slot=slot, order_id=o.id, kind="dca", t=now, price=px, raw_price=px, notional=notional,
                                  margin=notional / p.leverage, fee=0.0, slip=0.0, liquidity="maker", reason=o.reason))
            st.orders.pop(o.id, None)
            st.placed.discard(o.id)
            st.dca_qty.pop(o.id, None)
        p.qty, p.avg = amt, entry or p.avg
