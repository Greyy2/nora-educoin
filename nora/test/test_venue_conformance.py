"""P6.6: bộ test CONFORMANCE cho Venue (backend/core/execute/venue.py) — cùng một hợp đồng cho mọi nơi khớp lệnh.

Ba tầng (docs/bmad/p6_execution_design.md §3, roadmap P6.6):
  A  hợp đồng — CÙNG thân test chạy trên SimVenue và OkxVenue (sàn OKX v5 giả lập HTTP, tái dùng `FakeOkx` của test_okx_venue.py); chỉ phần
     dựng (`Driver`) khác nhau. Khác biệt hành vi giữa hai venue chỉ được phép đi qua `venue.caps` (skip theo caps) — KHÔNG kiểm tên venue trong thân test.
  B  kịch bản giá — chỉ SimVenue, chạy qua PositionManager trên nến dựng tay (phản chiếu các test đã ghim:
     test_causal_engine::test_gap_through_sl_fills_at_open, test_signals_strategies::test_no_take_profit_in_same_bar_as_dca_fill,
     ::test_trailing_stop_uses_previous_peak, ::test_perp_liquidation_caps_loss_at_margin, ::test_stop_fill_extreme_*, test_dca_gate::limit_through).
  C  dung sai OKX Demo — bỏ qua trừ khi NORA_OKX_DEMO_LIVE=1 (người dùng chủ động; không có khoá thì không chạy).

Khoảng hở thật giữa hai venue do P6.6 tìm ra đã đóng ở P6.8b (không còn xfail): TRAIL có `activation` / `callback_pct` riêng cho trailing gốc
(`level` luôn là mức stop tĩnh của sim); SimVenue từ chối như OKX: ENTRY thứ hai -> "position_exists", SL/TP/TRAIL/DCA khi chưa có vị thế -> "no_position".
"""
import math
import os
from dataclasses import dataclass
from typing import List, Optional

import pytest

from backend.core.execute.events import Fill, OrderRejected
from backend.core.execute.manager import PositionManager
from backend.core.execute.models import PositionStatus, PositionType
from backend.core.execute.sim_venue import SimVenue
from backend.core.execute.tracker import PositionTracker
from backend.core.execute.venue import NAN, Order, OrderKind, Venue, new_order_id
from backend.core.params.builder import build_params
from backend.live import okx
from backend.live.okx_venue import OkxVenue
from test_okx_venue import INSTR, FakeOkx, T0

REF = 50_000.0       # giá tham chiếu chung của Tier A (sim: quote; okx: set_ref)
SLOT = 0
M = 60_000


# ═══ Tier A: Driver — phần dựng riêng của từng venue ════════════════════════════════════════════════════════════════════════════════════
@dataclass
class _View:
    """PositionView tối thiểu của SimVenue ở Tier A (không có PositionManager): driver cập nhật theo Fill đã kéo ra."""
    avg: float = 0.0
    qty: float = 0.0
    pos_leverage: float = 10.0
    mmr: float = 0.005
    is_long: bool = True
    market: str = "perp"


class Driver:
    """Mặt chung cho thân test: mỗi venue cài `enter / events / position_qty / exchange_order_count / arm_post_only_cross`."""
    qty_step: Optional[float] = None          # bước khối lượng của sàn (None = venue không làm tròn)
    venue: Venue

    @property
    def caps(self):
        return self.venue.caps

    def submit(self, order: Order) -> None:
        self.venue.submit(order)

    def events(self) -> List:
        out = []
        while (e := self.venue.next_event(SLOT)) is not None:
            out.append(e)
            self._observe(e)
        return out

    def enter(self, is_buy: bool = True, notional: float = 1001.0, margin: float = 100.0) -> List:
        self._before_entry(is_buy)
        self.submit(Order(new_order_id(), SLOT, OrderKind.ENTRY, is_buy, notional=notional, margin=margin, reason="start"))
        return self.events()

    def exit(self, is_buy: bool = False) -> List:
        self.submit(Order(new_order_id(), SLOT, OrderKind.EXIT, is_buy, reason="Tín hiệu thoát"))
        return self.events()

    def _before_entry(self, is_buy: bool) -> None: ...
    def _observe(self, ev) -> None: ...
    def position_qty(self) -> float: raise NotImplementedError
    def exchange_order_count(self) -> int: raise NotImplementedError
    def arm_post_only_cross(self) -> None: raise NotImplementedError


class SimDriver(Driver):
    def __init__(self):
        self.venue = SimVenue()
        self.venue.add_slot(SLOT, fee_rate=0.0005, maker_fee_rate=0.0002, slippage_rate=0.0002)
        self.view = _View()
        # nến phẳng ở REF: không lệnh bảo vệ nào (cách xa 1-2%) bị chạm, nhưng có quote cho lệnh market và view cho lệnh đóng
        self.venue.begin_bar(SLOT, T0, REF, REF, REF, REF, self.view)

    def _observe(self, ev) -> None:
        v = self.view
        if not isinstance(ev, Fill):
            return
        if ev.kind in ("entry", "dca"):
            q = ev.notional / ev.price
            v.avg = (v.avg * v.qty + ev.price * q) / (v.qty + q) if v.qty else ev.price
            v.qty += q
        else:
            v.qty = 0.0

    def _before_entry(self, is_buy: bool) -> None:
        # SimVenue lấy hướng khớp từ position_view.is_long (không phải Order.is_buy): người đặt lệnh (manager) giữ view đúng hướng của slot
        self.view.is_long = is_buy

    def position_qty(self) -> float:
        return self.view.qty

    def exchange_order_count(self) -> int:
        return len(self.venue.open_orders(SLOT))        # sim không có "sàn" ngoài sổ lệnh chờ

    def arm_post_only_cross(self) -> None:
        raise NotImplementedError("SimVenue.caps.post_only = False")


class SimStrictDriver(SimDriver):
    qty_step = 0.01

    def __init__(self):
        self.venue = SimVenue(post_only=True, rounds_qty=True)
        self.venue.add_slot(SLOT, fee_rate=0.0005, maker_fee_rate=0.0002, slippage_rate=0.0002, qty_step=self.qty_step)
        self.view = _View()
        self.venue.begin_bar(SLOT, T0, REF, REF, REF, REF, self.view)

    def arm_post_only_cross(self) -> None:
        pass


class OkxFakeDriver(Driver):
    qty_step = 0.01        # INSTR: 1 hợp đồng = 0.01 BTC

    def __init__(self, fake: FakeOkx):
        self.fake = fake
        self.client = okx.OkxAdapter(("K", "S", "P"), demo=True, pause=0)
        self.venue = OkxVenue(self.client, {SLOT: "BTC"}, clock=lambda: T0, settle_s=0)
        self.venue.set_ref(SLOT, REF)

    def _before_entry(self, is_buy: bool) -> None:
        self.fake.fill_px = "50010" if is_buy else "49990"        # trượt bất lợi 2 bps, cùng độ lớn slippage_rate của SimDriver

    def position_qty(self) -> float:
        p = self.fake.pos.get("BTC-USDT-SWAP")
        return abs(float(p["pos"])) * float(INSTR["ctVal"]) if p else 0.0

    def exchange_order_count(self) -> int:
        return len(self.fake.pending) + len(self.fake.algos)

    def arm_post_only_cross(self) -> None:
        self.fake.fail[("/api/v5/trade/order", "post_only")] = ("1", [{"sCode": "51026", "sMsg": "Post-only order would take liquidity"}])


@pytest.fixture(params=["sim", "sim_strict", "okx_fake"])
def venue(request, monkeypatch) -> Driver:
    if request.param == "sim":
        return SimDriver()
    if request.param == "sim_strict":
        return SimStrictDriver()
    fake = FakeOkx()
    monkeypatch.setattr(okx.urllib.request, "urlopen", fake)
    return OkxFakeDriver(fake)


def _fill_qty(f: Fill) -> float:
    return f.notional / f.price


def _protective(d: Driver, is_long: bool) -> dict:
    """Bộ lệnh bảo vệ + DCA cho vị thế long/short. TRAIL giống nhau cho mọi venue (P6.8b): level = mức stop TĨNH (sim), activation / callback_pct
    cho trailing gốc (OKX)."""
    sgn = 1.0 if is_long else -1.0
    out = {
        "sl": Order(new_order_id(), SLOT, OrderKind.SL, not is_long, level=REF * (1 - 0.02 * sgn), reduce_only=True),
        "tp": Order(new_order_id(), SLOT, OrderKind.TP, not is_long, level=REF * (1 + 0.02 * sgn), reduce_only=True),
        "trail": Order(new_order_id(), SLOT, OrderKind.TRAIL, not is_long, level=REF * (1 - 0.005 * sgn), activation=REF * (1 + 0.01 * sgn),
                       callback_pct=1.5, reduce_only=True),
    }
    lvl = REF * (1 - 0.01 * sgn)
    out["dca"] = Order(new_order_id(), SLOT, OrderKind.DCA, is_long, level=lvl, notional=lvl * 0.02, margin=lvl * 0.002,
                       post_only=d.caps.post_only)
    return out


def _submit_all(d: Driver, orders: dict) -> None:
    for o in orders.values():
        d.submit(o)


# ─── Hợp đồng chung ──────────────────────────────────────────────────────────
def test_implements_venue_protocol(venue):
    v = venue.venue
    assert hasattr(v, "caps") and all(isinstance(getattr(v.caps, f), bool) for f in
                                      ("generates_liquidation", "native_trailing", "post_only", "rounds_qty"))
    for name in ("submit", "cancel", "cancel_slot", "open_orders", "next_event"):
        assert callable(getattr(v, name))
    assert v.next_event(SLOT) is None and v.open_orders(SLOT) == []        # slot mới: không sự kiện, không lệnh chờ


@pytest.mark.parametrize("is_buy", [True, False], ids=["long", "short"])
def test_market_entry_yields_fill(venue, is_buy):
    evs = venue.enter(is_buy=is_buy)
    assert len(evs) == 1 and isinstance(evs[0], Fill)
    f = evs[0]
    assert (f.kind, f.slot, f.liquidity) == ("entry", SLOT, "taker")
    assert f.price > 0 and f.raw_price > 0 and f.notional > 0 and f.margin > 0 and f.fee >= 0
    qty = _fill_qty(f)
    assert qty > 0 and venue.position_qty() == pytest.approx(qty)
    # trượt giá luôn BẤT LỢI cho taker: mua cao hơn / bán thấp hơn giá tham chiếu, slip >= 0
    assert f.slip >= 0
    assert (f.price >= f.raw_price) if is_buy else (f.price <= f.raw_price)
    assert venue.venue.next_event(SLOT) is None


def test_entry_qty_rounded_down_to_exchange_step(venue):
    if not venue.caps.rounds_qty:
        pytest.skip("venue không làm tròn khối lượng (caps.rounds_qty=False)")
    (f,) = venue.enter(notional=1001.0)                        # 1001 / 50000 = 0.02002 coin
    qty = _fill_qty(f)
    assert qty <= 1001.0 / REF + 1e-12                         # làm tròn XUỐNG: không vượt khối lượng đã xin
    steps = qty / venue.qty_step
    assert steps == pytest.approx(round(steps), abs=1e-6) and round(steps) >= 1


@pytest.mark.parametrize("is_long", [True, False], ids=["long", "short"])
def test_protective_orders_appear_in_open_orders(venue, is_long):
    (f,) = venue.enter(is_buy=is_long)
    orders = _protective(venue, is_long)
    _submit_all(venue, orders)
    assert venue.events() == []                                # đặt lệnh chờ hợp lệ: không sự kiện
    got = venue.venue.open_orders(SLOT)
    assert sorted(o.id for o in got) == sorted(o.id for o in orders.values())
    assert {o.kind for o in got} == {OrderKind.SL, OrderKind.TP, OrderKind.TRAIL, OrderKind.DCA}
    side_of = {o.id: o.is_buy for o in got}
    assert all(side_of[orders[k].id] is (not is_long) for k in ("sl", "tp", "trail")) and side_of[orders["dca"].id] is is_long
    assert venue.position_qty() == pytest.approx(_fill_qty(f))  # lệnh chờ không đổi vị thế


def test_cancel_slot_removes_all_and_is_idempotent(venue):
    venue.enter()
    _submit_all(venue, _protective(venue, True))
    qty0 = venue.position_qty()
    assert len(venue.venue.open_orders(SLOT)) == 4
    venue.venue.cancel_slot(SLOT)
    assert venue.venue.open_orders(SLOT) == [] and venue.exchange_order_count() == 0
    venue.venue.cancel_slot(SLOT)                              # lần hai: không lỗi, vẫn rỗng
    assert venue.venue.open_orders(SLOT) == [] and venue.exchange_order_count() == 0
    assert venue.position_qty() == pytest.approx(qty0)         # cancel_slot không đóng vị thế
    assert venue.events() == []


def test_cancel_slot_on_empty_slot_is_noop(venue):
    venue.venue.cancel_slot(SLOT)
    venue.venue.cancel_slot(SLOT)
    assert venue.venue.open_orders(SLOT) == [] and venue.events() == []


def test_cancel_single_order_keeps_the_rest(venue):
    venue.enter()
    orders = _protective(venue, True)
    _submit_all(venue, orders)
    venue.venue.cancel(orders["tp"].id)
    assert sorted(o.id for o in venue.venue.open_orders(SLOT)) == sorted(orders[k].id for k in ("sl", "trail", "dca"))
    venue.venue.cancel(999_999_999)                            # id lạ: bỏ qua
    assert len(venue.venue.open_orders(SLOT)) == 3
    assert venue.events() == []


@pytest.mark.parametrize("is_long", [True, False], ids=["long", "short"])
def test_exit_closes_position_and_leaves_no_protective_orders(venue, is_long):
    venue.enter(is_buy=is_long)
    _submit_all(venue, _protective(venue, is_long))
    assert venue.venue.open_orders(SLOT) != []
    evs = venue.exit(is_buy=not is_long)
    assert len(evs) == 1 and isinstance(evs[0], Fill)
    f = evs[0]
    assert f.kind == "exit" and f.slot == SLOT and f.price > 0 and f.notional == 0.0 and f.margin == 0.0 and f.fee >= 0
    assert f.reason == "Tín hiệu thoát"
    assert venue.position_qty() == 0.0
    assert venue.venue.open_orders(SLOT) == [] and venue.exchange_order_count() == 0
    assert venue.venue.next_event(SLOT) is None


def test_min_size_violation_is_rejected(venue):
    if not venue.caps.rounds_qty:
        pytest.skip("venue không làm tròn/kiểm khối lượng tối thiểu (caps.rounds_qty=False)")
    evs = venue.enter(notional=100.0, margin=10.0)             # 0.002 coin < bước 0.01 -> làm tròn 0
    assert len(evs) == 1 and isinstance(evs[0], OrderRejected)
    assert (evs[0].reason, evs[0].kind, evs[0].slot) == ("min_size", "entry", SLOT)
    assert venue.position_qty() == 0.0 and venue.venue.open_orders(SLOT) == []
    venue.enter()
    dca = Order(new_order_id(), SLOT, OrderKind.DCA, True, level=49500.0, notional=50.0, margin=5.0)
    venue.submit(dca)
    (r,) = venue.events()
    assert isinstance(r, OrderRejected) and (r.reason, r.kind, r.order_id) == ("min_size", "dca", dca.id)
    assert venue.venue.open_orders(SLOT) == []                 # lệnh bị từ chối không nằm lại sổ


def test_post_only_that_would_cross_is_rejected(venue):
    if not venue.caps.post_only:
        pytest.skip("venue không hỗ trợ post_only (caps.post_only=False)")
    venue.enter()
    venue.arm_post_only_cross()
    d = Order(new_order_id(), SLOT, OrderKind.DCA, True, level=REF * 1.01, notional=1010.0, margin=101.0, post_only=True)
    venue.submit(d)
    (r,) = venue.events()
    assert isinstance(r, OrderRejected) and (r.reason, r.kind, r.order_id, r.slot) == ("post_only", "dca", d.id, SLOT)
    assert venue.venue.open_orders(SLOT) == [] and venue.exchange_order_count() == 0


def test_second_entry_on_open_slot_does_not_double_position(venue):
    """Hợp đồng: một slot tối đa MỘT vị thế (venue.py). ENTRY thứ hai phải bị từ chối hoặc không tạo Fill/vị thế thứ hai."""
    (f,) = venue.enter()
    qty0 = venue.position_qty()
    evs = venue.enter()
    assert all(isinstance(e, OrderRejected) for e in evs), f"ENTRY thứ hai sinh sự kiện khớp: {evs}"
    assert venue.position_qty() == pytest.approx(qty0) and qty0 == pytest.approx(_fill_qty(f))
    if evs:
        assert evs[0].reason == "position_exists" and evs[0].kind == "entry"


def test_protective_order_without_position_is_not_left_resting(venue):
    """Hợp đồng: lệnh bảo vệ đóng hết vị thế -> không có vị thế thì bị từ chối (hoặc ít nhất không nằm lại sổ lệnh chờ)."""
    sl = Order(new_order_id(), SLOT, OrderKind.SL, False, level=REF * 0.98, reduce_only=True)
    venue.submit(sl)
    evs = venue.events()
    assert venue.venue.open_orders(SLOT) == []
    assert len(evs) == 1 and isinstance(evs[0], OrderRejected) and (evs[0].reason, evs[0].kind) == ("no_position", "sl")


# ═══ Tier B: kịch bản giá trên SimVenue, qua PositionManager ═════════════════════════════════════════════════════════════════════════════
BASE_POS = {"market": "perp", "leverage": 1, "exit_unit": "pct", "sizing": "margin_pct", "order_size_pct": 10.0, "stop_loss_rate": 0.0,
            "take_profit_rate": 0.0, "trailing_stop": 0.0, "trailing_activation_pct": 0.0, "dca_max_layers": 0, "dca_step_pct": 0.0,
            "dca_size_multiplier": 1.0, "timeout": 0, "fee_rate": 0.0, "maker_fee_rate": 0.0, "slippage_rate": 0.0}
FLAT = (100.0, 100.0, 100.0, 100.0)


def _manager(side: str = "LONG", **pos):
    params = build_params(f"{side}_f", {"match": [], "stop": []}, side, {**BASE_POS, **pos}, "cex")
    tr = PositionTracker(0, 0, "X", f"{side}_f", params, PositionType.LONG if side == "LONG" else PositionType.SHORT, initial_capital=10_000.0)
    events: List = []
    return PositionManager(tr, SimVenue(), slot=0, events=events), events


def _drive(mgr, bars):
    """bars[i] = (o, h, l, c). Tín hiệu vào ở nến 0 -> vào lệnh ở open nến 1. Trả [(chỉ số nến, vị thế vừa đóng)]."""
    closed = []
    for i, (o, h, l, c) in enumerate(bars):
        pos = mgr.on_bar(i * M, o, h, l, c, entry_signal=(i == 0), stop_signal=False)
        if pos is not None:
            closed.append((i, pos))
    return closed


def _fills(events, kind=None):
    return [e for e in events if isinstance(e, Fill) and (kind is None or e.kind == kind)]


def test_b_gap_through_sl_fills_at_open():
    """Nến gap qua SL (open < mức SL) khớp ở OPEN (bi quan), không ở mức SL; chịu trượt giá taker."""
    mgr, ev = _manager(stop_loss_rate=5.0, slippage_rate=0.0002)
    gap_open = 85.5                                            # SL ~ 95.02; open đã thấp hơn nhiều
    closed = _drive(mgr, [FLAT, FLAT, (gap_open, gap_open * 1.01, gap_open * 0.98, gap_open * 0.99)])
    assert [i for i, _ in closed] == [2]
    pos = closed[0][1]
    (sl,) = _fills(ev, "sl")
    assert pos.status == PositionStatus.SL and sl.raw_price == gap_open and sl.liquidity == "taker"
    assert pos.close_price == pytest.approx(gap_open * (1 - 0.0002)) and sl.price == pytest.approx(gap_open * (1 - 0.0002))
    assert pos.close_price < 100.02 * 0.95                     # tệ hơn mức SL: đúng giả định bi quan


def test_b_dca_fill_then_tp_skipped_in_same_bar():
    """Nến có DCA khớp: TP (tính từ avg mới) KHÔNG được xét dù high vượt; nến kế tiếp mới chốt. Đối chứng: không DCA thì TP khớp ngay."""
    bars = [FLAT, FLAT, (100.0, 100.9, 99.4, 100.8), (100.8, 100.8, 100.8, 100.8)]
    mgr, ev = _manager(order_size_pct=20.0, dca_step_pct=0.5, dca_max_layers=1, take_profit_rate=0.3, intrabar_path="adverse_first")
    closed = _drive(mgr, bars)
    assert [i for i, _ in closed] == [3]                       # đóng ở nến 3, không phải nến 2 (nến DCA)
    pos = closed[0][1]
    assert pos.layers == 2 and pos.status == PositionStatus.TP
    assert [f.kind for f in _fills(ev)] == ["entry", "dca", "tp"]
    assert _fills(ev, "dca")[0].price == pytest.approx(99.5) and _fills(ev, "dca")[0].liquidity == "maker"
    avg = 2 / (1 / 100.0 + 1 / 99.5)                           # hai tầng cùng ký quỹ -> giá TB điều hoà
    assert pos.close_price == pytest.approx(avg * 1.003)       # open nến 3 (100.8) đã vượt mức TP (~100.05) -> limit chờ sẵn khớp ĐÚNG ở mức TP (quy tắc bảo thủ 2026-10-06)
    mgr2, ev2 = _manager(order_size_pct=20.0, take_profit_rate=0.3, intrabar_path="adverse_first")
    closed2 = _drive(mgr2, bars)
    assert [i for i, _ in closed2] == [2] and closed2[0][1].layers == 1 and _fills(ev2, "tp")[0].price == pytest.approx(100.3)


def test_b_ohlc_dca_then_replaced_tp_in_the_money_at_close_fills_taker_at_close():
    """Đường "ohlc": nến (100, 100.2, 99.4, 100.2): DCA @99.5 ở chặng L; TP mới (avg x 1.003 ~ 100.05) đã trong giá ở close 100.2 -> khớp
    ngay ở close như lệnh taker (Nautilus: lệnh đặt lại thấy sổ lệnh lúc close); TP cũ 100.3 chưa chạm."""
    mgr, ev = _manager(order_size_pct=20.0, dca_step_pct=0.5, dca_max_layers=1, take_profit_rate=0.3)
    closed = _drive(mgr, [FLAT, FLAT, (100.0, 100.2, 99.4, 100.2)])
    assert [i for i, _ in closed] == [2] and closed[0][1].layers == 2 and closed[0][1].status == PositionStatus.TP
    assert [f.kind for f in _fills(ev)] == ["entry", "dca", "tp"]
    (tp,) = _fills(ev, "tp")
    assert tp.raw_price == pytest.approx(100.2) and tp.liquidity == "taker"
    mgr2, ev2 = _manager(order_size_pct=20.0, dca_step_pct=0.5, dca_max_layers=1, take_profit_rate=0.3)
    closed2 = _drive(mgr2, [FLAT, FLAT, (100.0, 100.9, 99.4, 100.8)])     # H trước: TP cũ 100.3 khớp ở chặng H, chưa có DCA
    assert [i for i, _ in closed2] == [2] and closed2[0][1].layers == 1 and _fills(ev2, "tp")[0].price == pytest.approx(100.3)
    assert _fills(ev2, "tp")[0].liquidity == "maker"


def test_b_tie_sl_vs_dca_exits_first():
    """SL và DCA cùng mức trong một nến (hoà) -> thoát trước: không nhồi tầng. Đối chứng: DCA cao hơn SL thì nhồi trước rồi vẫn sống."""
    mgr, ev = _manager(order_size_pct=20.0, stop_loss_rate=1.0, dca_step_pct=1.0, dca_max_layers=1, intrabar_path="adverse_first")     # DCA 99.0 == SL 99.0
    closed = _drive(mgr, [FLAT, FLAT, (100.0, 100.0, 98.5, 99.0)])
    assert [i for i, _ in closed] == [2]
    assert [f.kind for f in _fills(ev)] == ["entry", "sl"] and closed[0][1].layers == 1
    assert _fills(ev, "sl")[0].price == pytest.approx(99.0)
    mgr2, ev2 = _manager(order_size_pct=20.0, stop_loss_rate=2.0, dca_step_pct=1.0, dca_max_layers=1, intrabar_path="adverse_first")  # DCA 99.0 trước, SL ~97.6 chưa chạm
    assert _drive(mgr2, [FLAT, FLAT, (100.0, 100.0, 98.5, 99.0)]) == [] and mgr2.is_open and mgr2.layer_count == 2
    assert [f.kind for f in _fills(ev2)] == ["entry", "dca"]


def test_b_ohlc_tie_sl_and_dca_same_level_dca_first_then_sl():
    """Đường "ohlc" (Nautilus): trong một tick nhóm DCA khớp TRƯỚC stop — hoà mức 99.0 thì nhồi tầng rồi SL cố định 99.0 đóng cả vị thế."""
    mgr, ev = _manager(order_size_pct=20.0, stop_loss_rate=1.0, dca_step_pct=1.0, dca_max_layers=1)
    closed = _drive(mgr, [FLAT, FLAT, (100.0, 100.0, 98.5, 99.0)])
    assert [i for i, _ in closed] == [2] and closed[0][1].layers == 2
    assert [f.kind for f in _fills(ev)] == ["entry", "dca", "sl"]
    assert _fills(ev, "sl")[0].price == pytest.approx(99.0) and _fills(ev, "dca")[0].price == pytest.approx(99.0)


@pytest.mark.parametrize("spike_bar", [False, True], ids=["pinned_path", "same_bar_spike"])
def test_b_trailing_uses_previous_bars_peak(spike_bar):
    """Trailing bám đỉnh các nến TRƯỚC (đỉnh chỉ đổi cuối nến): mức = 105 × 0,99 = 103,95. Nến có high vọt 110 cùng low 103,5 vẫn khớp ở 103,95
    (nếu dùng đỉnh nến hiện tại mức sẽ là 108,9 -> khớp ở 105)."""
    path = [FLAT, FLAT, (100, 101, 100, 101), (101, 103, 101, 103), (103, 105, 103, 105)]
    path += [(105.0, 110.0, 103.5, 104.0)] if spike_bar else [(105, 105, 104, 104), (104, 104, 103.9, 103.9)]
    mgr, ev = _manager(trailing_stop=1.0, intrabar_path="adverse_first")
    closed = _drive(mgr, path)
    assert [i for i, _ in closed] == [len(path) - 1]
    pos = closed[0][1]
    assert pos.close_price == pytest.approx(105 * 0.99) and pos.status == PositionStatus.TP
    (tr,) = _fills(ev, "trail")
    assert tr.raw_price == pytest.approx(103.95) and tr.liquidity == "taker"


def test_b_ohlc_trailing_peak_runs_per_leg():
    """Đường "ohlc": đỉnh chạy theo chặng. Đỉnh trước nến = 105; nến (105, 110, 103.5, 104): H lên 110 rồi L 103.5 xuyên mức 110 x 0.99 = 108.9
    -> khớp ở 108.9 NGAY trong nến (đường cũ khớp ở 103.95). Kích hoạt kiểm theo từng chặng."""
    path = [FLAT, FLAT, (100, 101, 100, 101), (105, 105, 104.5, 105), (105.0, 110.0, 103.5, 104.0)]
    mgr, ev = _manager(trailing_stop=1.0)
    closed = _drive(mgr, path)
    (tr,) = _fills(ev, "trail")
    assert closed[-1][0] == len(path) - 1 and tr.raw_price == pytest.approx(110 * 0.99) and tr.liquidity == "taker"
    mgr2, ev2 = _manager(trailing_stop=1.0, trailing_activation_pct=12.0)    # lãi tại đỉnh 110 là 10% < 12%: chưa bật -> không khớp
    assert _drive(mgr2, path) == [] and not _fills(ev2, "trail")


def test_b_liquidation_fill_on_perp_only():
    """Perp: venue tự sinh Fill thanh lý ở giá thanh lý (avg × (1 − 1/L + mmr)), tách khỏi taker; spot không bị thanh lý."""
    mgr, ev = _manager(leverage=20, order_size_pct=10.0)
    assert mgr.venue.caps.generates_liquidation
    closed = _drive(mgr, [FLAT, FLAT, (100.0, 100.0, 94.0, 94.0)])
    assert [i for i, _ in closed] == [2]
    pos = closed[0][1]
    (liq,) = _fills(ev, "liq")
    assert pos.status == PositionStatus.LIQ and liq.liquidity == "liquidation"
    assert liq.price == pytest.approx(100 * (1 - 1 / 20 + 0.005)) == pytest.approx(pos.close_price)
    assert pos.real_pnl == pytest.approx(-1000.0 * (1 - 0.005 * 20), rel=1e-6)
    spot, ev2 = _manager(market="spot", leverage=1, order_size_pct=10.0)
    assert _drive(spot, [FLAT, FLAT, (100.0, 100.0, 1.0, 1.0)]) == [] and spot.is_open and not _fills(ev2, "liq")


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_b_stop_fill_extreme_fills_at_bar_extreme(side):
    """stop_fill='level' khớp đúng mức SL (98 / 102); 'extreme' khớp ở đáy / đỉnh nến (95 / 105)."""
    lg = side == "LONG"
    bar = (100.0, 100.0, 95.0, 97.0) if lg else (100.0, 105.0, 100.0, 103.0)
    got = {}
    for mode in ("level", "extreme"):
        mgr, ev = _manager(side, market="perp", stop_loss_rate=2.0, stop_fill=mode)
        closed = _drive(mgr, [FLAT, FLAT, bar])
        assert closed[0][1].status == PositionStatus.SL
        got[mode] = _fills(ev, "sl")[0].price
    assert got["level"] == pytest.approx(98.0 if lg else 102.0)
    assert got["extreme"] == pytest.approx(95.0 if lg else 105.0)


def test_b_limit_through_dca_requires_price_to_go_through():
    """limit_through_pct=0,2: DCA chỉ khớp khi giá đi QUA mức 99 × (1 − 0,2%) = 98,802; khớp ở GIÁ ĐẶT 99 (không lấy giá tốt hơn)."""
    pos = {"leverage": 3, "stop_loss_rate": 20.0, "dca_step_pct": 1.0, "dca_max_layers": 3, "limit_through_pct": 0.2}

    def run(low):
        mgr, ev = _manager(**pos)
        _drive(mgr, [FLAT, FLAT, (100.0, 100.0, low, low)])
        return mgr, ev

    assert run(99.0)[0].layer_count == 1                       # chỉ chạm mức: chưa khớp
    assert run(98.85)[0].layer_count == 1                      # qua mức nhưng chưa qua ngưỡng 98,802
    mgr, ev = run(98.7)
    assert mgr.layer_count == 2
    assert _fills(ev, "dca")[0].price == pytest.approx(99.0)   # khớp ở giá đặt


def test_b_limit_through_tp_requires_price_to_go_through():
    """TP 1% (mức 101) với limit_through 0,2%: cần high >= 101 × 1,002 = 101,202; khớp ở mức TP (open 100 chưa vượt)."""
    pos = {"take_profit_rate": 1.0, "limit_through_pct": 0.2}
    mgr, ev = _manager(**pos)
    assert _drive(mgr, [FLAT, FLAT, (100.0, 101.1, 100.0, 101.0)]) == [] and mgr.is_open       # chạm 101 nhưng chưa qua 101,202
    mgr, ev = _manager(**pos)
    closed = _drive(mgr, [FLAT, FLAT, (100.0, 101.3, 100.0, 101.0)])
    assert [i for i, _ in closed] == [2]
    (tp,) = _fills(ev, "tp")
    assert tp.price == pytest.approx(101.0) and tp.liquidity == "maker" and closed[0][1].status == PositionStatus.TP


# ═══ Tier C: dung sai trên OKX Demo THẬT (người dùng chủ động) ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(os.environ.get("NORA_OKX_DEMO_LIVE") != "1",
                    reason="chạm OKX Demo thật: đặt NORA_OKX_DEMO_LIVE=1 để chạy (người dùng chủ động)")
class TestOkxDemoTolerance:
    """Lệnh nhỏ nhất, vài bps quanh giá thị trường, luôn dọn. Khoá demo lấy qua make_adapter (môi trường / ~/.config/nora/okx.env).
    NORA_OKX_DEMO_SYM (mặc định ETH) chọn mã; NORA_OKX_DEMO_BAND_BPS (mặc định 30) là dải dung sai trượt giá."""

    def _setup(self):
        from backend.live.bot import make_adapter
        client, _ = make_adapter("okx", "demo")
        client.check_account()
        sym = os.environ.get("NORA_OKX_DEMO_SYM", "ETH")
        if client.positions().get(sym):
            pytest.skip(f"đã có vị thế {sym} trên demo — không động vào")
        rows = client._req("GET", "/api/v5/market/ticker", {"instId": okx.inst(sym)})
        ref = float(rows[0]["last"])
        return client, sym, ref

    def test_fills_within_slippage_band_and_cleanup(self):
        client, sym, ref = self._setup()
        band = float(os.environ.get("NORA_OKX_DEMO_BAND_BPS", "30")) / 1e4
        f = client.filters(sym)
        v = OkxVenue(client, {SLOT: sym})
        v.set_ref(SLOT, ref)
        notional = f.min_qty * ref * 1.5
        got: List = []

        def drain():
            while (e := v.next_event(SLOT)) is not None:
                got.append(e)
        try:
            v.submit(Order(new_order_id(), SLOT, OrderKind.ENTRY, True, notional=notional, margin=notional / 2, reason="demo_tol"))
            drain()
            fill = got[-1]
            assert isinstance(fill, Fill) and fill.kind == "entry" and fill.price > 0 and fill.notional > 0
            assert abs(fill.price - ref) / ref <= band, f"trượt giá vào lệnh {fill.slip:.5f} vượt dải {band:.5f}"
            # lệnh chờ cách thị trường vài bps (không chéo): DCA post-only dưới giá, TP trên giá; SL xa để không bị kích hoạt
            dca_lvl, tp_lvl = fill.price * (1 - 0.0005), fill.price * (1 + 0.0005)
            v.submit(Order(new_order_id(), SLOT, OrderKind.SL, False, level=fill.price * 0.8, reduce_only=True))
            v.submit(Order(new_order_id(), SLOT, OrderKind.TP, False, level=tp_lvl, reduce_only=True))
            v.submit(Order(new_order_id(), SLOT, OrderKind.DCA, True, level=dca_lvl, notional=notional, margin=notional / 2, post_only=True))
            drain()
            assert not [e for e in got if isinstance(e, OrderRejected)], f"lệnh chờ bị từ chối: {got}"
            assert {o.kind for o in v.open_orders(SLOT)} >= {OrderKind.SL, OrderKind.DCA}   # TP có thể đã khớp nếu giá nhích đúng 5 bps
            v.cancel_slot(SLOT)
            assert client._req("GET", "/api/v5/trade/orders-pending", {"instId": okx.inst(sym)}, signed=True) == []
            if sym in client.positions():
                v.set_ref(SLOT, float(client._req("GET", "/api/v5/market/ticker", {"instId": okx.inst(sym)})[0]["last"]))
                v.submit(Order(new_order_id(), SLOT, OrderKind.EXIT, False, reason="demo_tol_exit"))
                drain()
                assert got[-1].kind == "exit" and abs(got[-1].price - v._ref[SLOT]) / v._ref[SLOT] <= band
            assert sym not in client.positions()
        finally:                                                # luôn dọn: không để lại vị thế / lệnh trên demo
            client.cancel_all(sym)
            client.close_market(sym)
