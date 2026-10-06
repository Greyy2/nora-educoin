"""P6.7: OkxVenue (backend/live/okx_venue.py) cài Venue Protocol trên OkxAdapter — contract test KHÔNG cần mạng.
Tầng HTTP của okx.py (urllib.request.urlopen) được thay bằng sàn OKX giả trả JSON đúng hình dạng API v5 -> chạy qua OkxAdapter THẬT
(đổi coin <-> hợp đồng, thân lệnh, reduce-only / post-only / trigger). Lớp TestOkxDemoLive bỏ qua trừ khi NORA_OKX_DEMO_LIVE=1."""
import json
import math
import os
import urllib.parse

import pytest

from backend.core.execute.events import Fill, OrderRejected
from backend.core.execute.venue import Order, OrderKind, Venue, new_order_id
from backend.live import okx
from backend.live.okx_venue import OkxVenue, SlotConflict

NAN = float("nan")
T0 = 1_700_000_000_000
INSTR = {"ctVal": "0.01", "lotSz": "1", "minSz": "1", "tickSz": "0.1"}    # 1 hợp đồng = 0.01 BTC -> bước 0.01, tối thiểu 0.01


class _Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOkx:
    """Sàn OKX giả: sổ lệnh chờ + lệnh điều kiện + vị thế net (đơn vị HỢP ĐỒNG, như API). Ghi mọi POST vào `self.posts`."""

    def __init__(self):
        self.posts = []                    # (path, body)
        self.pos = {}                      # instId -> {"pos": contracts (signed), "avgPx": str}
        self.pending = []                  # lệnh limit chờ: {"ordId", "instId", ...}
        self.algos = []                    # lệnh điều kiện: {"algoId", "instId", "ordType", ...}
        self.history = []                  # positions-history rows
        self.fail = {}                     # (path, ordType) -> (code, data) lỗi theo shape OKX
        self.fill_px = "50010"
        self._n = 0

    def _id(self):
        self._n += 1
        return str(1000 + self._n)

    def __call__(self, req, timeout=0):
        u = urllib.parse.urlparse(req.full_url)
        q = dict(urllib.parse.parse_qsl(u.query))
        body = json.loads(req.data.decode()) if req.data else None
        out = self.handle(req.get_method(), u.path, q, body)
        return _Resp(json.dumps(out).encode())

    @staticmethod
    def ok(data=None):
        return {"code": "0", "msg": "", "data": data or []}

    def handle(self, method, path, q, body):
        if method == "POST":
            self.posts.append((path, body))
        if path.endswith("/public/instruments"):
            return self.ok([{"instId": q["instId"], **INSTR}])
        if path.endswith("/account/set-leverage"):
            return self.ok([{"instId": body["instId"], "lever": body["lever"], "mgnMode": "isolated"}])
        if path.endswith("/account/positions"):
            return self.ok([{"instId": k, "pos": v["pos"], "avgPx": v["avgPx"]} for k, v in self.pos.items() if float(v["pos"])])
        if path.endswith("/account/positions-history"):
            return self.ok([r for r in self.history if r["instId"] == q["instId"]])
        if path.endswith("/trade/order"):
            err = self.fail.get((path, body["ordType"]))
            if err:
                return {"code": err[0], "msg": "All operations failed", "data": err[1]}
            oid = self._id()
            if body["ordType"] == "market":
                sz = float(body["sz"]) * (1 if body["side"] == "buy" else -1)
                self.pos[body["instId"]] = {"pos": f"{sz:g}", "avgPx": self.fill_px}
            else:
                self.pending.append({"ordId": oid, **body})
            return self.ok([{"ordId": oid, "clOrdId": "", "sCode": "0", "sMsg": ""}])
        if path.endswith("/trade/order-algo"):
            err = self.fail.get((path, body["ordType"]))
            if err:
                return {"code": err[0], "msg": "All operations failed", "data": err[1]}
            aid = self._id()
            self.algos.append({"algoId": aid, **body})
            return self.ok([{"algoId": aid, "sCode": "0", "sMsg": ""}])
        if path.endswith("/trade/orders-pending"):
            return self.ok([o for o in self.pending if o["instId"] == q["instId"]])
        if path.endswith("/trade/cancel-batch-orders"):
            ids = {b["ordId"] for b in body}
            self.pending = [o for o in self.pending if o["ordId"] not in ids]
            return self.ok([{"ordId": i, "sCode": "0", "sMsg": ""} for i in ids])
        if path.endswith("/trade/orders-algo-pending"):
            return self.ok([a for a in self.algos if a["instId"] == q["instId"] and a["ordType"] == q["ordType"]])
        if path.endswith("/trade/cancel-algos"):
            ids = {b["algoId"] for b in body}
            self.algos = [a for a in self.algos if a["algoId"] not in ids]
            return self.ok([{"algoId": i, "sCode": "0", "sMsg": ""} for i in ids])
        if path.endswith("/trade/close-position"):
            if body["instId"] not in self.pos or not float(self.pos[body["instId"]]["pos"]):
                return {"code": "1", "msg": "x", "data": [{"sCode": "51023", "sMsg": "Position does not exist"}]}
            self.pos.pop(body["instId"])
            return self.ok([{"instId": body["instId"], "posSide": "net"}])
        raise AssertionError(f"endpoint không giả lập: {method} {path}")

    def add_history(self, sym, close_px, fee, pnl, c_time=T0 - 1000, u_time=T0 + 5000):
        self.history.append({"instId": f"{sym}-USDT-SWAP", "cTime": str(c_time), "uTime": str(u_time), "closeAvgPx": str(close_px),
                             "openAvgPx": "50010", "realizedPnl": str(pnl), "fee": str(fee), "fundingFee": "0"})


@pytest.fixture
def fake(monkeypatch):
    f = FakeOkx()
    monkeypatch.setattr(okx.urllib.request, "urlopen", f)
    return f


def mk(fake, slots=None, **kw):
    a = okx.OkxAdapter(("K", "S", "P"), demo=True, pause=0)
    v = OkxVenue(a, slots if slots is not None else {0: "BTC"}, clock=lambda: T0, settle_s=0, **kw)
    v.set_ref(0, 50000.0)
    return a, v


def entry(slot=0, notional=1000.0, margin=100.0, is_buy=True, **kw):
    return Order(new_order_id(), slot, OrderKind.ENTRY, is_buy, notional=notional, margin=margin, reason="start", **kw)


def events(v, slot=0):
    out = []
    while (e := v.next_event(slot)) is not None:
        out.append(e)
    return out


def posts(fake, suffix):
    return [b for p, b in fake.posts if p.endswith(suffix)]


def open_long(fake, v, slot=0):
    v.submit(entry(slot))
    return events(v, slot)[0]


def test_implements_venue_protocol_and_caps(fake):
    a, v = mk(fake)
    assert isinstance(v, OkxVenue) and hasattr(v, "caps")
    for name in ("submit", "cancel", "cancel_slot", "open_orders", "next_event"):
        assert callable(getattr(v, name))
    _: Venue = v                                               # kiểm kiểu tĩnh (Protocol)
    c = v.caps
    assert (c.generates_liquidation, c.native_trailing, c.post_only, c.rounds_qty) == (False, True, True, True)
    a.place_trailing = None
    assert OkxVenue(a, {}).caps.native_trailing is False


def test_entry_market_open_fill_rounded_qty_and_price(fake):
    fake.fill_px = "50010"
    a, v = mk(fake)
    v.submit(entry(notional=1001.0, margin=100.0))             # 1001/50000 = 0.02002 coin -> 2 hợp đồng (0.02) sau làm tròn xuống
    ev = events(v)
    assert len(ev) == 1 and isinstance(ev[0], Fill) and ev[0].kind == "entry"
    f = ev[0]
    assert posts(fake, "/account/set-leverage")[0]["lever"] == "10" and posts(fake, "/account/set-leverage")[0]["mgnMode"] == "isolated"
    mo = posts(fake, "/trade/order")[0]
    assert mo == {"instId": "BTC-USDT-SWAP", "tdMode": "isolated", "side": "buy", "ordType": "market", "sz": "2"}
    assert f.price == pytest.approx(50010.0) and f.raw_price == 50000.0
    assert f.notional == pytest.approx(0.02 * 50010.0) and f.margin == pytest.approx(f.notional / 10) and f.leverage_used == 10.0
    assert f.slip == pytest.approx(10 / 50000) and f.liquidity == "taker" and f.fee == 0.0 and f.reason == "start"
    assert f.t == T0 and v.next_event(0) is None


def test_short_entry_side_and_slip_sign(fake):
    fake.fill_px = "49990"
    a, v = mk(fake)
    v.submit(entry(is_buy=False))
    f = events(v)[0]
    assert posts(fake, "/trade/order")[0]["side"] == "sell" and f.slip == pytest.approx(10 / 50000)    # bán thấp hơn tham chiếu = bất lợi


def test_protective_and_dca_placement_fields(fake):
    a, v = mk(fake)
    open_long(fake, v)                                         # qty 0.02 coin = 2 hợp đồng
    v.submit(Order(new_order_id(), 0, OrderKind.SL, False, level=49000.04, reduce_only=True))
    v.submit(Order(new_order_id(), 0, OrderKind.TP, False, level=51000.0, reduce_only=True))
    v.submit(Order(new_order_id(), 0, OrderKind.TRAIL, False, level=50500.0, trigger=1.5, reduce_only=True))
    v.submit(Order(new_order_id(), 0, OrderKind.DCA, True, level=49500.0, notional=990.0, margin=99.0, post_only=True))
    assert events(v) == []
    sl = posts(fake, "/trade/order-algo")[0]
    assert sl["ordType"] == "conditional" and sl["side"] == "sell" and sl["reduceOnly"] == "true" and sl["slTriggerPxType"] == "last"
    assert sl["slOrdPx"] == "-1" and sl["slTriggerPx"] == "49000.0" and sl["sz"] == "2" and sl["tdMode"] == "isolated"
    tr = posts(fake, "/trade/order-algo")[1]
    assert tr["ordType"] == "move_order_stop" and tr["callbackRatio"] == "0.0150" and tr["activePx"] == "50500.0" and tr["reduceOnly"] == "true"
    lim = [b for b in posts(fake, "/trade/order") if b["ordType"] != "market"]
    tp, dca = lim
    assert tp["ordType"] == "limit" and tp["reduceOnly"] == "true" and tp["side"] == "sell" and tp["px"] == "51000.0" and tp["sz"] == "2"
    assert dca["ordType"] == "post_only" and dca["side"] == "buy" and dca["px"] == "49500.0" and dca["sz"] == "2" and "reduceOnly" not in dca
    assert [o.kind for o in v.open_orders(0)] == [OrderKind.SL, OrderKind.TP, OrderKind.TRAIL, OrderKind.DCA]


def test_short_protective_sides(fake):
    a, v = mk(fake)
    v.submit(entry(is_buy=False))
    events(v)
    v.submit(Order(new_order_id(), 0, OrderKind.SL, True, level=51000.0, reduce_only=True))
    v.submit(Order(new_order_id(), 0, OrderKind.TP, True, level=49000.0, reduce_only=True))
    assert posts(fake, "/trade/order-algo")[0]["side"] == "buy"
    assert [b for b in posts(fake, "/trade/order") if b["ordType"] == "limit"][0]["side"] == "buy"


def test_dca_fill_inferred_from_position_increase(fake):
    a, v = mk(fake)
    open_long(fake, v)
    d1 = Order(new_order_id(), 0, OrderKind.DCA, True, level=49500.0, notional=990.0, margin=99.0, reason="dca1")     # 0.02 coin
    d2 = Order(new_order_id(), 0, OrderKind.DCA, True, level=49000.0, notional=1960.0, margin=196.0, reason="dca2")   # 0.04 coin
    v.submit(d1)
    v.submit(d2)
    assert v.poll(T0 + 1000) == 0 and events(v) == []                       # chưa đổi -> không có gì
    fake.pos["BTC-USDT-SWAP"] = {"pos": "4", "avgPx": "49755"}              # tầng 1 khớp: 2 -> 4 hợp đồng
    assert v.poll(T0 + 2000) == 1
    (f,) = events(v)
    assert f.kind == "dca" and f.order_id == d1.id and f.price == 49500.0 and f.liquidity == "maker" and f.reason == "dca1" and f.t == T0 + 2000
    assert f.notional == pytest.approx(0.02 * 49500.0) and f.margin == pytest.approx(f.notional / 10)
    assert [o.id for o in v.open_orders(0)] == [d2.id]                      # tầng 2 vẫn chờ
    fake.pos["BTC-USDT-SWAP"] = {"pos": "8", "avgPx": "49400"}              # tầng 2 khớp: 4 -> 8
    v.poll(T0 + 3000)
    (g,) = events(v)
    assert g.kind == "dca" and g.order_id == d2.id and v.open_orders(0) == []
    v.poll(T0 + 4000)
    assert events(v) == []                                                  # không phát lại


def test_dca_two_layers_in_one_poll(fake):
    a, v = mk(fake)
    open_long(fake, v)
    ids = []
    for lvl, nt in ((49500.0, 990.0), (49000.0, 980.0)):
        o = Order(new_order_id(), 0, OrderKind.DCA, True, level=lvl, notional=nt, margin=nt / 10)
        ids.append(o.id)
        v.submit(o)
    fake.pos["BTC-USDT-SWAP"] = {"pos": "6", "avgPx": "49600"}              # 2 + 2 + 2 hợp đồng: cả hai tầng khớp giữa hai lần poll
    v.poll(T0 + 1000)
    assert [(e.kind, e.order_id) for e in events(v)] == [("dca", ids[0]), ("dca", ids[1])]


def test_position_gone_emits_closing_fill_with_closed_since(fake):
    a, v = mk(fake)
    open_long(fake, v)
    sl = Order(new_order_id(), 0, OrderKind.SL, False, level=49000.0, reduce_only=True)
    tp = Order(new_order_id(), 0, OrderKind.TP, False, level=51000.0, reduce_only=True)
    v.submit(sl)
    v.submit(tp)
    fake.pos.clear()                                                        # SL khớp trên sàn
    fake.add_history("BTC", close_px=48985.5, fee=-0.8, pnl=-6.2)           # OKX: fee âm = chi phí
    assert v.poll(T0 + 9000) == 1
    (f,) = events(v)
    assert isinstance(f, Fill) and f.kind == "sl" and f.order_id == sl.id
    assert f.price == 48985.5 and f.raw_price == 49000.0 and f.fee == pytest.approx(0.8) and f.liquidity == "taker"
    assert f.slip == pytest.approx(14.5 / 49000.0) and f.notional == 0.0 and f.t == T0 + 9000
    assert v.last_close[0]["pnl"] == -6.2 and v.open_orders(0) == []
    assert fake.algos == [] and fake.pending == []                             # đã dọn lệnh mồ côi (SL còn trên sàn, TP limit)


def test_position_gone_kind_inference_tp_trail_and_exit(fake):
    for close_px, extra, want in ((51003.0, None, "tp"), (50400.0, "trail", "trail"), (50400.0, None, "exit")):
        fake.__init__()
        a, v = mk(fake)
        open_long(fake, v)
        v.submit(Order(new_order_id(), 0, OrderKind.SL, False, level=49000.0, reduce_only=True))
        v.submit(Order(new_order_id(), 0, OrderKind.TP, False, level=51000.0, reduce_only=True))
        if extra:
            v.submit(Order(new_order_id(), 0, OrderKind.TRAIL, False, level=50300.0, trigger=1.0, reduce_only=True))
        fake.pos.clear()
        fake.add_history("BTC", close_px=close_px, fee=-0.5, pnl=3.0)
        v.poll(T0 + 9000)
        (f,) = events(v)
        assert f.kind == want and f.price == close_px
        assert f.liquidity == ("maker" if want == "tp" else "taker")


def test_exit_cancels_all_and_closes_with_closed_since(fake):
    a, v = mk(fake)
    open_long(fake, v)
    v.submit(Order(new_order_id(), 0, OrderKind.SL, False, level=49000.0, reduce_only=True))
    v.submit(Order(new_order_id(), 0, OrderKind.DCA, True, level=49500.0, notional=990.0, margin=99.0))
    fake.add_history("BTC", close_px=50120.0, fee=-1.1, pnl=2.2)
    v.set_ref(0, 50100.0)
    v.submit(Order(new_order_id(), 0, OrderKind.EXIT, False, reason="Tín hiệu thoát"))
    (f,) = events(v)
    assert f.kind == "exit" and f.price == 50120.0 and f.fee == pytest.approx(1.1) and f.reason == "Tín hiệu thoát"
    assert fake.pending == [] and fake.algos == [] and "BTC-USDT-SWAP" not in fake.pos
    assert posts(fake, "/trade/close-position")[0] == {"instId": "BTC-USDT-SWAP", "mgnMode": "isolated"}
    assert v.last_close[0]["pnl"] == 2.2 and v.open_orders(0) == []
    v.poll(T0 + 1000)
    assert events(v) == []


def test_exit_without_history_falls_back_to_ref_price(fake):
    a, v = mk(fake)
    open_long(fake, v)
    v.set_ref(0, 50123.0)
    v.submit(Order(new_order_id(), 0, OrderKind.EXIT, False))
    (f,) = events(v)
    assert f.price == 50123.0 and f.fee == 0.0


def test_post_only_rejection_is_order_rejected(fake):
    a, v = mk(fake)
    open_long(fake, v)
    fake.fail[("/api/v5/trade/order", "post_only")] = ("1", [{"sCode": "51026", "sMsg": "Post-only order would take liquidity"}])
    d = Order(new_order_id(), 0, OrderKind.DCA, True, level=50500.0, notional=1010.0, margin=101.0, post_only=True)
    v.submit(d)
    (r,) = events(v)
    assert isinstance(r, OrderRejected) and (r.reason, r.kind, r.order_id, r.slot) == ("post_only", "dca", d.id, 0)
    assert v.open_orders(0) == []


def test_min_size_rejections(fake):
    a, v = mk(fake)
    v.submit(entry(notional=100.0, margin=10.0))                            # 0.002 coin < bước 0.01 -> làm tròn 0 -> dưới minQty
    (r,) = events(v)
    assert isinstance(r, OrderRejected) and r.reason == "min_size" and r.kind == "entry" and not posts(fake, "/trade/order")
    open_long(fake, v)
    d = Order(new_order_id(), 0, OrderKind.DCA, True, level=49500.0, notional=50.0, margin=5.0)
    v.submit(d)
    (r2,) = events(v)
    assert r2.reason == "min_size" and r2.kind == "dca" and [b["ordType"] for b in posts(fake, "/trade/order")] == ["market"]
    fake.fail[("/api/v5/trade/order", "limit")] = ("1", [{"sCode": "51020", "sMsg": "Order amount should be more than the min available amount"}])
    v.submit(Order(new_order_id(), 0, OrderKind.TP, False, level=51000.0))
    assert events(v)[0].reason == "min_size"                                # lỗi 51020 của sàn cũng quy về min_size


def test_not_permitted_is_order_rejected(fake, monkeypatch):
    a, v = mk(fake)
    a.filters("BTC")                                                            # nạp bộ lọc trước khi khoá bị từ chối

    def deny(req, timeout=0):
        return _Resp(json.dumps({"code": "50123", "msg": "API key doesn't have permission", "data": []}).encode())
    monkeypatch.setattr(okx.urllib.request, "urlopen", deny)
    v.submit(entry())
    (r,) = events(v)
    assert isinstance(r, OrderRejected) and r.reason == "not_permitted"
    assert v.open_orders(0) == []


def test_unclassified_exchange_error_is_raised(fake):
    a, v = mk(fake)
    open_long(fake, v)
    fake.fail[("/api/v5/trade/order-algo", "conditional")] = ("1", [{"sCode": "51000", "sMsg": "Parameter error"}])
    with pytest.raises(okx.ExchangeError):
        v.submit(Order(new_order_id(), 0, OrderKind.SL, False, level=49000.0))


def test_cancel_slot_cancels_pending_and_algo_orders(fake):
    a, v = mk(fake)
    open_long(fake, v)
    v.submit(Order(new_order_id(), 0, OrderKind.SL, False, level=49000.0))
    v.submit(Order(new_order_id(), 0, OrderKind.TP, False, level=51000.0))
    v.submit(Order(new_order_id(), 0, OrderKind.TRAIL, False, level=50500.0, trigger=1.0))
    v.submit(Order(new_order_id(), 0, OrderKind.DCA, True, level=49500.0, notional=990.0, margin=99.0))
    assert len(fake.pending) == 2 and len(fake.algos) == 2
    v.cancel_slot(0)
    assert fake.pending == [] and fake.algos == [] and v.open_orders(0) == []   # không còn lệnh bảo vệ mồ côi
    assert "BTC-USDT-SWAP" in fake.pos                                          # vị thế giữ nguyên (cancel_slot không đóng)


def test_cancel_single_order_resyncs_the_rest(fake):
    a, v = mk(fake)
    open_long(fake, v)
    sl = Order(new_order_id(), 0, OrderKind.SL, False, level=49000.0)
    tp = Order(new_order_id(), 0, OrderKind.TP, False, level=51000.0)
    d = Order(new_order_id(), 0, OrderKind.DCA, True, level=49500.0, notional=990.0, margin=99.0)
    for o in (d, tp, sl):
        v.submit(o)
    v.cancel(tp.id)
    assert [o.id for o in v.open_orders(0)] == [d.id, sl.id]
    assert [a["slTriggerPx"] for a in fake.algos] == ["49000.0"] and [p["ordType"] for p in fake.pending] == ["post_only"]   # TP biến mất, SL + DCA đặt lại
    v.cancel(999999)                                                           # id lạ: bỏ qua


def test_second_slot_on_same_symbol_rejected(fake):
    a, v = mk(fake)
    with pytest.raises(SlotConflict, match="BTC"):
        v.bind(1, "BTC")
    with pytest.raises(SlotConflict):
        OkxVenue(a, {0: "ETH", 1: "ETH"})
    v.bind(1, "ETH")                                                           # symbol khác thì được
    with pytest.raises(KeyError):
        v.submit(Order(new_order_id(), 7, OrderKind.EXIT, False))


def test_entry_when_position_exists_is_rejected(fake):
    a, v = mk(fake)
    open_long(fake, v)
    v.submit(entry())
    (r,) = events(v)
    assert r.reason == "position_exists" and len(posts(fake, "/trade/order")) == 1


def test_local_trail_when_client_has_no_native_trailing(fake):
    a, v = mk(fake)
    a.place_trailing = None
    v = OkxVenue(a, {0: "BTC"}, clock=lambda: T0, settle_s=0)
    v.set_ref(0, 50000.0)
    assert not v.caps.native_trailing
    open_long(fake, v)
    t = Order(new_order_id(), 0, OrderKind.TRAIL, False, level=50400.0, reason="Trailing stop")
    v.submit(t)
    assert fake.algos == [] and v.open_orders(0) == [t]                        # giữ cục bộ, không gửi sàn
    v.poll(T0 + 1000, bars={"BTC": (50900.0, 50450.0, 50600.0)})               # chưa chạm
    assert events(v) == []
    fake.add_history("BTC", close_px=50395.0, fee=-0.4, pnl=1.0)
    v.poll(T0 + 2000, bars={"BTC": (50700.0, 50390.0, 50400.0)})               # low <= level -> đóng market
    (f,) = events(v)
    assert f.kind == "trail" and f.price == 50395.0 and f.reason == "Trailing stop" and "BTC-USDT-SWAP" not in fake.pos


def test_native_trail_without_callback_rejected(fake):
    a, v = mk(fake)
    open_long(fake, v)
    v.submit(Order(new_order_id(), 0, OrderKind.TRAIL, False, level=50500.0))
    assert events(v)[0].reason == "no_callback" and fake.algos == []


@pytest.mark.skipif(os.environ.get("NORA_OKX_DEMO_LIVE") != "1", reason="chạm OKX Demo thật: đặt NORA_OKX_DEMO_LIVE=1 để chạy (người dùng chủ động)")
class TestOkxDemoLive:
    """Chạy THẬT trên OKX Demo Trading (khoá demo từ môi trường / ~/.config/nora/okx.env qua make_adapter). Chỉ lệnh nhỏ nhất, luôn dọn.
    NORA_OKX_DEMO_SYM (mặc định ETH) chọn mã."""

    def test_entry_protect_cancel_exit_roundtrip(self):
        from backend.live.bot import make_adapter
        client, _ = make_adapter("okx", "demo")
        client.check_account()
        sym = os.environ.get("NORA_OKX_DEMO_SYM", "ETH")
        if client.positions().get(sym):
            pytest.skip(f"đã có vị thế {sym} trên demo — không động vào")
        f = client.filters(sym)
        ref = float(client.klines(sym, "1h", 5, int(__import__("time").time() * 1000))[-1][4])
        v = OkxVenue(client, {0: sym})
        v.set_ref(0, ref)
        notional = f.min_qty * ref * 1.5
        try:
            v.submit(Order(new_order_id(), 0, OrderKind.ENTRY, True, notional=notional, margin=notional / 2, reason="demo_live"))
            fill = events(v)[0]
            assert isinstance(fill, Fill) and fill.kind == "entry" and fill.price > 0 and fill.notional > 0
            v.submit(Order(new_order_id(), 0, OrderKind.SL, False, level=ref * 0.8, reduce_only=True))
            v.submit(Order(new_order_id(), 0, OrderKind.TP, False, level=ref * 1.3, reduce_only=True))
            assert client.positions().get(sym) is not None
            v.cancel_slot(0)
            assert client._req("GET", "/api/v5/trade/orders-pending", {"instId": okx.inst(sym)}, signed=True) == []
            v.submit(Order(new_order_id(), 0, OrderKind.EXIT, False, reason="demo_live_exit"))
            assert [e.kind for e in events(v)] == ["exit"] and sym not in client.positions()
        finally:                                                                # luôn dọn: không để lại vị thế / lệnh trên demo
            client.cancel_all(sym)
            client.close_market(sym)
