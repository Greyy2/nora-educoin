"""P6.8b: bot sàn trên kiến trúc thống nhất (UnifiedBot trong backend/live/live.py, engine="unified") — Runner + PositionManager + OkxVenue + sổ vốn ảo.
Sàn OKX GIẢ (FakeOkx của test_okx_venue.py) chạy qua OkxAdapter THẬT (tầng HTTP thay bằng sàn giả) — không mạng, không khoá.
Tín hiệu dựng tay như test_live_bot (`_sig`); mốc thời gian: nến t0 đóng -> bước `now = t0 + HOUR` (bot vào lệnh ngay ở bước đó)."""
import json
import os
import pickle

import pytest

from backend.routes import live as live_router
from backend.core import backtest as bt
from backend.core import position_size as policy
from backend.live import live as lb
from backend.metrics import trades as C
from backend.crawl.store import live_state_key
from backend.live.live import Filters
from test_live_bot import BOOK, HOUR, _defaults, _sig
from test_okx_venue import FakeOkx

T0B = 50 * HOUR
DCA = {"dca_steps": [1.0, 2.0, 3.0], "dca_multipliers": [1.5, 2.0, 2.0]}
TRAIL = {"trailing_stop": 1.5, "trailing_activation_pct": 1.0}


class Fake(FakeOkx):
    """FakeOkx + ticker (giá last), cấu hình tài khoản và số dư (bot gọi equity() / last_price())."""

    def __init__(self):
        super().__init__()
        self.last = {"AAA": 100.0, "BBB": 100.0}
        self.balance = "10000"

    def handle(self, method, path, q, body):
        if path.endswith("/market/ticker"):
            sym = q["instId"].split("-")[0]
            return self.ok([{"instId": q["instId"], "last": str(self.last[sym])}])
        if path.endswith("/account/config"):
            return self.ok([{"acctLv": "2", "posMode": "net_mode", "perm": "read_only,trade"}])
        if path.endswith("/account/balance"):
            return self.ok([{"details": [{"ccy": "USDT", "eq": self.balance}]}])
        return super().handle(method, path, q, body)


class World:
    """Bot unified + sàn giả + danh sách sự kiện ghi ra (thay events.jsonl)."""

    def __init__(self, tmp_path, monkeypatch, book=None, pos=None, keys=("K", "S", "P"), exec_blob=None, drift=5.0):
        self.fake = Fake()
        monkeypatch.setattr(lb.urllib.request, "urlopen", self.fake)
        self.tmp, self.events = tmp_path, []
        if pos:
            orig = lb.book_strategies

            def patched(bk):
                sts = orig(bk)
                for st in sts:
                    st["position"] = {**st["position"], **pos}
                return sts
            monkeypatch.setattr(lb, "book_strategies", patched)
        self.client = lb.OkxAdapter(keys, demo=True, pause=0)
        self.filters = {s: self.client.filters(s) for s in ("AAA", "BBB")}
        self.book = book or BOOK
        self.state = lb.State(str(tmp_path / "state.json"))
        self.exec_path = str(tmp_path / "unified.pkl")
        self.b = lb.UnifiedBot(self.book, "demo", self.client, self.state, self.events.append, self.filters, None, 10000.0, exec_blob, drift,
                               self.exec_path)
        self.b.wall_ms = lambda: self.b.clock_t + 7_000      # sàn khớp 7 s sau mốc nến (độ trễ D5)
        self.fake.fill_px = "100.05"

    def sig(self, ts, match=None, stop=None, **kw):
        return {"AAA": _sig(self.b, "AAA", ts, match=match, stop=stop, **kw), "BBB": _sig(self.b, "BBB", ts)}

    def step(self, now, ts, **kw):
        return self.b.step(now, self.sig(ts, **kw), {})

    @property
    def mgr(self):
        return self.b.runner.books[0]["entries"][0]["tracker"]

    def rows(self, evt="fill", src=None):
        return [e for e in self.events if e.get("evt") == evt and (src is None or e.get("src") == src)]

    def kinds(self, src):
        return [e["kind"] for e in self.rows(src=src)]

    def kind_events(self, kind):
        return [e for e in self.events if e.get("kind") == kind and "evt" not in e]

    def posts(self, suffix, **where):
        return [b for p, b in self.fake.posts if p.endswith(suffix) and all(b.get(k) == v for k, v in where.items())]

    def algos(self, ord_type):
        return [a for a in self.fake.algos if a["ordType"] == ord_type]

    def limits(self):
        return [o for o in self.fake.pending]

    def enter(self):
        """Tín hiệu ở nến T0B -> bot vào lệnh ngay ở bước T0B + HOUR."""
        self.step(T0B + HOUR, [T0B], match={T0B})
        assert self.mgr.is_open
        return self.mgr


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch, pos={**DCA, **TRAIL, "take_profit_rate": 2.0})


# ── D1 ────────────────────────────────────────────────────────────────────────
def test_d1_refuses_max_per_symbol_not_one(tmp_path, monkeypatch):
    bad = {**BOOK, "risk": {**BOOK["risk"], "max_per_symbol": 2}}
    with pytest.raises(SystemExit, match="max_per_symbol"):
        World(tmp_path, monkeypatch, book=bad)
    with pytest.raises(SystemExit, match="max_per_symbol"):
        lb.check_book_d1({**BOOK, "risk": {k: v for k, v in BOOK["risk"].items() if k != "max_per_symbol"}})
    with pytest.raises(SystemExit, match="trùng"):
        lb.check_book_d1({**BOOK, "universe": ["AAA@perp", "AAA@perp"]})
    lb.check_book_d1(BOOK)                                         # sổ hợp lệ: không ném


def test_d1_refusal_in_run_job_before_touching_exchange(tmp_path, monkeypatch):
    monkeypatch.setattr(lb, "load_book", lambda *a, **k: {**BOOK, "risk": {**BOOK["risk"], "max_per_symbol": 3}})
    monkeypatch.setattr(lb, "make_adapter", lambda *a, **k: pytest.fail("không được chạm sàn khi D1 từ chối"))
    with pytest.raises(SystemExit, match="max_per_symbol"):
        lb.run_job({"mode": "demo", "engine": "unified", "state_dir": str(tmp_path), "once": True})
    with pytest.raises(SystemExit, match="engine"):
        lb.run_job({"mode": "demo", "engine": "nope"})
    with pytest.raises(SystemExit, match="OKX"):
        lb.run_job({"mode": "demo", "engine": "unified", "venue": "binance"})


def test_unified_requires_exec_mode(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        w = World(tmp_path, monkeypatch)
        lb.UnifiedBot(BOOK, "paper", w.client, w.state, w.events.append)


# ── vào lệnh: sizing + lệnh bảo vệ ────────────────────────────────────────────
def test_entry_sizing_matches_shadow_and_places_protective_orders(world):
    w = world
    w.enter()
    assert w.kinds("exec") == ["entry"] and w.kinds("sim") == []   # sim vào ở open nến kế (bước sau)
    # nến t0+HOUR đóng, không tín hiệu: bóng sim vào lệnh ở open của nến đó
    w.step(T0B + 2 * HOUR, [T0B, T0B + HOUR])
    ex, sm = w.rows(src="exec")[0], w.rows(src="sim")[0]
    assert (ex["kind"], sm["kind"]) == ("entry", "entry") and ex["symbol"] == sm["symbol"] == "AAA" and ex["side"] == sm["side"] == "LONG"
    assert ex["margin"] == pytest.approx(sm["margin"], rel=0.01)                # cùng sizing (chênh chỉ do làm tròn khối lượng theo bộ lọc sàn)
    assert ex["notional"] == pytest.approx(sm["notional"], rel=0.01) and ex["leverage_used"] == sm["leverage_used"]
    assert w.posts("/account/set-leverage")[0]["mgnMode"] == "isolated"
    assert w.posts("/trade/order", ordType="market")[0]["side"] == "buy"
    # SL / TP / TRAIL / DCA nằm sẵn trên sàn, đúng trường
    mgr = w.mgr
    f = w.filters["AAA"]
    avg = mgr.avg
    assert avg == pytest.approx(100.05)
    (sl,) = w.algos("conditional")
    assert sl["slTriggerPx"] == str(f.price(policy.sl_level(avg, mgr.sl_pct, 1.0))) and sl["reduceOnly"] == "true" and sl["slOrdPx"] == "-1"
    (tr,) = w.algos("move_order_stop")
    assert tr["activePx"] == str(f.price(avg * (1 + mgr.trail_activation_pct / 100))) and tr["callbackRatio"] == f"{mgr.trail_pct / 100:.4f}"
    limits = w.limits()
    tp = [o for o in limits if o["ordType"] == "limit"]
    dca = [o for o in limits if o["ordType"] == "post_only"]
    assert len(tp) == 1 and tp[0]["px"] == str(f.price(policy.tp_level(avg, mgr.tp_pct, 1.0))) and tp[0]["reduceOnly"] == "true"
    assert len(dca) == 1                                                        # thang DCA: mỗi lần một tầng kế tiếp (như sim)
    assert float(dca[0]["px"]) == pytest.approx(f.price(policy.dca_level(avg, mgr.dca_steps[0], 1.0)))
    # không có gì đổi -> nến sau KHÔNG huỷ / đặt lại lệnh bảo vệ (D2: nằm sẵn trên sàn, trailing gốc giữ nguyên đỉnh)
    n_posts = len(w.fake.posts)
    w.step(T0B + 3 * HOUR, [T0B, T0B + HOUR, T0B + 2 * HOUR])
    assert len(w.fake.posts) == n_posts


def test_state_and_virtual_ledger_seeded_with_capital(world):
    w = world
    assert w.b.runner.account.initial == 10000.0 and w.b.runner.account.equity == 10000.0
    w.enter()
    d = w.state.d
    assert d["engine"] == "unified" and d["positions"]["AAA"]["layers"] == 1 and d["exchange_equity"] == 10000.0
    assert d["paper"]["positions"] == 0 and json.load(open(w.tmp / "state.json"))["engine"] == "unified"
    assert os.path.isfile(w.exec_path)


# ── DCA khớp trên sàn -> đặt lại bảo vệ ngay trong watch() ───────────────────────
def test_dca_fill_on_exchange_reprotects_from_new_avg_within_watch(world):
    w = world
    mgr = w.enter()
    f, fake = w.filters["AAA"], w.fake
    avg0, qty0 = mgr.avg, mgr.qty
    (dca,) = [o for o in w.limits() if o["ordType"] == "post_only"]
    q_dca_contracts = float(dca["sz"])
    # sàn khớp tầng DCA: vị thế tăng, giá TB mới
    pos = fake.pos["AAA-USDT-SWAP"]
    add_qty = q_dca_contracts * 0.01
    new_avg = (avg0 * qty0 + float(dca["px"]) * add_qty) / (qty0 + add_qty)
    fake.pos["AAA-USDT-SWAP"] = {"pos": f"{float(pos['pos']) + q_dca_contracts:g}", "avgPx": str(new_avg)}
    n0 = len(fake.posts)
    w.b.watch(T0B + HOUR + 30_000)                                              # trong cùng nến: không cần chờ nến mới
    assert mgr.layer_count == 2 and mgr.qty == pytest.approx(qty0 + add_qty)
    assert w.kinds("exec") == ["entry", "dca"]
    assert len(fake.posts) > n0
    (sl,) = w.algos("conditional")
    assert sl["slTriggerPx"] == str(f.price(policy.sl_level(mgr.avg, mgr.sl_pct, 1.0)))
    assert mgr.avg == pytest.approx(new_avg, rel=1e-4) and sl["sz"] == fake.pos["AAA-USDT-SWAP"]["pos"]
    tp = [o for o in w.limits() if o["ordType"] == "limit"]
    assert tp[0]["px"] == str(f.price(policy.tp_level(mgr.avg, mgr.tp_pct, 1.0)))
    nxt = [o for o in w.limits() if o["ordType"] == "post_only"]
    assert len(nxt) == 1 and float(nxt[0]["px"]) == pytest.approx(f.price(policy.dca_level(mgr.last_fill, mgr.dca_steps[1], 1.0)))
    assert w.b.runner.account.reserved > 0
    assert json.load(open(w.tmp / "state.json"))["positions"]["AAA"]["layers"] == 2


# ── sàn đóng vị thế -> sổ ảo ghi nhận, cooldown áp dụng ─────────────────────────
def test_exchange_close_recorded_and_cooldown_applies(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, pos={**DCA, "take_profit_rate": 2.0, "cooldown": 180})
    mgr = w.enter()
    eq0 = w.b.runner.account.equity
    (sl,) = w.algos("conditional")
    px = float(sl["slTriggerPx"]) - 0.1
    w.fake.pos.pop("AAA-USDT-SWAP")
    w.fake.add_history("AAA", px, fee=-1.5, pnl=-99.0, c_time=T0B + HOUR, u_time=T0B + HOUR + 20_000)
    w.fake.last["AAA"] = px
    c0 = T0B + HOUR
    w.b.watch(c0 + 25_000)
    assert not mgr.is_open and mgr.last_close_time == c0
    acct = w.b.runner.account
    assert acct.equity < eq0 and acct.reserved == pytest.approx(0.0, abs=1e-9)
    close = w.rows(src="exec")[-1]
    assert close["kind"] == "sl" and close["price"] == pytest.approx(px) and close["t"] == T0B + HOUR + 20_000     # giờ sàn thật, không phải mốc nến
    assert close["t_bar"] == c0 and close["fee"] == pytest.approx(1.5)
    assert w.state.d["trades"][-1]["reason"].startswith("Stop-loss") and w.state.d["positions"] == {}
    n_mkt = len(w.posts("/trade/order", ordType="market"))
    # cooldown 180 phút: tín hiệu ngay nến kế bị chặn, sau 3 nến thì vào lại
    w.step(c0 + HOUR, [T0B, c0], match={c0})
    assert not w.mgr.is_open and len(w.posts("/trade/order", ordType="market")) == n_mkt
    w.fake.fill_px = "100.05"
    w.step(c0 + 4 * HOUR, [T0B, c0, c0 + HOUR, c0 + 2 * HOUR, c0 + 3 * HOUR], match={c0 + 3 * HOUR})
    assert w.mgr.is_open and len(w.posts("/trade/order", ordType="market")) == n_mkt + 1


def test_exit_signal_closes_market_on_next_boundary(world):
    w = world
    mgr = w.enter()
    w.step(T0B + 2 * HOUR, [T0B, T0B + HOUR], stop={T0B + HOUR})             # tín hiệu thoát ở nến đóng -> đóng market ngay bước đó
    assert not mgr.is_open and w.posts("/trade/close-position")
    assert w.kinds("exec") == ["entry", "exit"] and w.fake.pos == {}
    assert w.b.runner.trades[-1]["reason"].startswith("Tín hiệu thoát")


# ── kill switch trên sổ ảo ───────────────────────────────────────────────────────
KILL_BOOK = {**BOOK, "risk": {**BOOK["risk"], "kill_switch_dd_pct": 0.5}}


def test_kill_switch_from_price_sample_in_watch_flattens(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, book=KILL_BOOK, pos={**DCA})
    mgr = w.enter()
    assert w.b.runner.halted_at is None
    w.fake.last["AAA"] = 60.0                                                 # mẫu giá giữa nến: lỗ chưa chốt (~0,7% vốn ảo) > ngưỡng 0,5%
    w.b.watch(T0B + HOUR + 40_000)
    assert w.b.runner.halted_at is not None and not mgr.is_open and w.fake.pos == {}
    assert w.b.runner.trades[-1]["reason"] == "Kill switch danh mục"
    crit = w.kind_events("crit")
    assert crit and "kill switch" in crit[-1]["reason"] and w.state.d["halt_reason"] == "kill_switch"
    # đã dừng: tín hiệu mới không mở lệnh
    n_mkt = len(w.posts("/trade/order", ordType="market"))
    w.step(T0B + 2 * HOUR, [T0B, T0B + HOUR], match={T0B + HOUR})
    assert len(w.posts("/trade/order", ordType="market")) == n_mkt and w.state.d["halted"] is True


def test_kill_switch_from_bar_low_at_bar_end(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, book=KILL_BOOK, pos={**DCA})
    mgr = w.enter()
    # nến đóng có đáy 60 (SL trên sàn chưa khớp trong giả lập) -> MTM xấu nhất theo H/L chạm ngưỡng -> đóng hết
    w.step(T0B + 2 * HOUR, [T0B, T0B + HOUR], low=60.0, close=100.0, high=100.0)
    assert w.b.runner.halted_at is not None and not mgr.is_open
    assert w.b.runner.trades[-1]["reason"] == "Kill switch danh mục"
    assert w.kind_events("crit")


# ── cảnh báo lệch vốn sàn ↔ vốn ảo ─────────────────────────────────────────────
def test_drift_alert_halts_new_entries_without_flattening(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, pos={**DCA})
    mgr = w.enter()
    w.fake.balance = "9000"                                                   # sàn thấp hơn vốn ảo 10% > 5%
    w.b.watch(T0B + HOUR + 10_000)
    assert w.b.runner.halted_at is not None and w.state.d["halt_reason"] == "equity_drift" and w.state.d["equity_drift_pct"] > 5
    assert mgr.is_open and "AAA-USDT-SWAP" in w.fake.pos                       # KHÔNG tự đóng
    crit = w.kind_events("crit")
    assert crit and "lệch" in crit[-1]["reason"]
    # vị thế đang mở vẫn được quản lý; nhưng tín hiệu vào lệnh mới bị chặn
    n_mkt = len(w.posts("/trade/order", ordType="market"))
    w.step(T0B + 2 * HOUR, [T0B, T0B + HOUR], match={T0B + HOUR})
    assert len(w.posts("/trade/order", ordType="market")) == n_mkt


def test_drift_within_threshold_does_not_halt_and_zero_disables(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, pos={**DCA})
    w.fake.balance = "9700"                                                   # -3% < 5%
    w.enter()
    assert w.b.runner.halted_at is None and w.state.d["equity_drift_pct"] == pytest.approx(3.0, abs=0.5)
    w2 = World(tmp_path / "x", monkeypatch, drift=0.0) if (tmp_path / "x").mkdir() is None else None
    w2.fake.balance = "1"
    w2.step(T0B + HOUR, [T0B])
    assert w2.b.runner.halted_at is None


def test_run_job_refuses_fresh_start_when_capital_far_from_exchange_equity(tmp_path, monkeypatch):
    fake = Fake()
    fake.balance = "20000"
    monkeypatch.setattr(lb.urllib.request, "urlopen", fake)
    monkeypatch.setattr(lb, "load_book", lambda *a, **k: BOOK)
    monkeypatch.setattr(lb, "make_adapter", lambda *a, **k: (lb.OkxAdapter(("K", "S", "P"), demo=True, pause=0), ("K", "S", "P")))
    with pytest.raises(SystemExit, match="capital"):
        lb.run_job({"mode": "demo", "engine": "unified", "state_dir": str(tmp_path), "once": True, "capital": 10000.0})


# ── events.jsonl: hai phía, compare_events ───────────────────────────────────────
def test_events_log_both_sides_and_compare_events_runs(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, pos={"take_profit_rate": 2.0})              # không DCA / trailing: thoát của sim là SL thuần
    w.enter()
    w.step(T0B + 2 * HOUR, [T0B, T0B + HOUR])
    (sl,) = w.algos("conditional")
    level = float(sl["slTriggerPx"])
    close_px = level - 0.05                                                   # sàn khớp SL kém mức đặt 5 xu (market sau trigger)
    w.fake.pos.pop("AAA-USDT-SWAP")
    w.fake.add_history("AAA", close_px, fee=-1.0, pnl=-90.0, c_time=T0B + HOUR, u_time=T0B + 2 * HOUR + 30_000)
    w.fake.last["AAA"] = close_px
    w.b.watch(T0B + 2 * HOUR + 40_000)                                        # sàn đóng trong nến t0+2h
    # bóng sim: nến t0+2h có đáy xuyên SL -> SL của sim cùng nến
    w.step(T0B + 3 * HOUR, [T0B, T0B + HOUR, T0B + 2 * HOUR], low=level * 0.97, close=100.0, high=100.0)
    # cả hai phía đã ghi Fill với side, symbol, src
    for e in w.rows():
        assert {"src", "symbol", "side", "kind", "price", "t", "order_id"} <= set(e) and e["symbol"] == "AAA" and e["side"] == "LONG"
    assert w.kinds("exec") == ["entry", "sl"] and w.kinds("sim") == ["entry", "sl"]
    sim_sl = w.rows(src="sim")[-1]
    assert sim_sl["level"] == pytest.approx(level, rel=1e-3) and sim_sl["extreme"] == pytest.approx(level * 0.97)
    assert w.rows(src="exec")[0]["t"] - w.rows(src="exec")[0]["t_bar"] == 7_000      # giờ thật vs mốc nến
    # đọc lại như endpoint và đối soát
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in w.events) + "\n{hỏng\n", encoding="utf-8")
    ex, sm, _, _ = live_router.read_event_rows(str(path))
    r = C.compare_events(ex, sm, "1h")
    assert r["positions"]["matched"] == 1 and r["kinds"]["entry"]["matched"] == 1 and r["kinds"]["sl"]["matched"] == 1
    assert r["kinds"]["entry"]["latency_ms"]["mean"] == 7000.0
    assert r["kinds"]["sl"]["bps"]["mean"] is not None and r["sl_band"]["n"] == 1 and r["sl_band"]["n_with_extreme"] == 1
    assert next(x for x in r["pairs"] if x["kind"] == "sl")["sl"] in ("better", "between", "worse")


def test_compare_events_endpoint_reads_unified_state_dir(world, tmp_path, monkeypatch):
    w = world
    w.enter()
    w.step(T0B + 2 * HOUR, [T0B, T0B + HOUR])
    d = tmp_path / "okx_demo_unified"
    d.mkdir()
    (d / "events.jsonl").write_text("\n".join(json.dumps(e) for e in w.events) + "\n", encoding="utf-8")
    seen = {}
    monkeypatch.setattr(live_router, "_sdir", lambda venue, mode, book, engine=None: (seen.update(engine=engine), str(d))[1])
    monkeypatch.setattr(lb, "load_book", lambda *a, **k: BOOK)
    r = live_router.bot_compare_events(mode="demo", venue="okx", book="main", engine="unified")
    assert seen["engine"] == "unified" and r["n_exec"] == 1 and r["n_sim"] == 1 and r["timeframe"] == "1h"
    assert r["kinds"]["entry"]["matched"] == 1 and "breaches" in r and "calibrated" in r
    with pytest.raises(Exception, match="events.jsonl"):
        monkeypatch.setattr(live_router, "_sdir", lambda *a, **k: str(tmp_path / "none"))
        live_router.bot_compare_events(mode="demo", venue="okx", book="main", engine="unified")


# ── trạng thái / pickle ────────────────────────────────────────────────────────
def test_exec_state_survives_restart_and_never_pickles_api_keys(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, pos={**DCA, "take_profit_rate": 2.0}, keys=("KEYAAA111", "SECRETBBB222", "PASSCCC333"))
    mgr = w.enter()
    raw = open(w.exec_path, "rb").read()
    for k in (b"KEYAAA111", b"SECRETBBB222", b"PASSCCC333"):
        assert k not in raw
    blob = pickle.loads(raw)
    n_before = len(w.fake.posts)
    w2 = World.__new__(World)
    w2.__dict__.update(w.__dict__)
    w2.events = []
    w2.b = lb.UnifiedBot(w.book, "demo", w.client, w.state, w2.events.append, w.filters, None, 10000.0, blob, 5.0, w.exec_path)
    m2 = w2.b.runner.books[0]["entries"][0]["tracker"]
    assert m2.is_open and m2.qty == pytest.approx(mgr.qty) and w2.b.venue.client is w.client and w2.b.venue._clock is not None
    # sau khởi động lại vẫn xử lý được DCA khớp
    (dca,) = [o for o in w.limits() if o["ordType"] == "post_only"]
    pos = w.fake.pos["AAA-USDT-SWAP"]
    w.fake.pos["AAA-USDT-SWAP"] = {"pos": f"{float(pos['pos']) + float(dca['sz']):g}", "avgPx": "99.9"}
    w2.b.watch(T0B + HOUR + 20_000)
    assert m2.layer_count == 2 and len(w.fake.posts) > n_before
    with pytest.raises(ValueError, match="khác"):
        lb.UnifiedBot({**w.book, "universe": ["AAA@perp"]}, "demo", w.client, w.state, [].append, {}, None, 10000.0, blob, 5.0, "")


def test_external_position_blocks_symbol_and_warns(world):
    w = world
    w.fake.pos["AAA-USDT-SWAP"] = {"pos": "5", "avgPx": "100"}                 # vị thế không do bot mở
    w.step(T0B + HOUR, [T0B], match={T0B})
    assert not w.mgr.is_open and w.state.d["external"] == ["AAA"] and not w.posts("/trade/order", ordType="market")
    assert any(e["kind"] == "warn" and "không do bot quản lý" in e.get("reason", "") for e in w.events if "evt" not in e)


def test_not_permitted_entry_blocks_symbol(world):
    w = world
    w.fake.fail[("/api/v5/trade/order", "market")] = ("50123", [{"sCode": "50123", "sMsg": "API key doesn't have permission"}])
    w.step(T0B + HOUR, [T0B], match={T0B})
    assert not w.mgr.is_open
    assert "AAA" in w.b.blocked or w.rows("reject", "exec")


# ── nhiều chiến lược trên một symbol (D1) / SHORT ─────────────────────────────────
BOOK2 = {**BOOK, "strategies": [{"id": "trend_long", "params": _defaults("trend_long")}, {"id": "trend_short", "params": _defaults("trend_short")}]}


def _sig2(b, sym, ts, long_match=(), short_match=()):
    """Hai chiến lược (long, short) trên một symbol."""
    import numpy as np
    _, pairs = bt._engine(f"{sym}@perp", b.strategies, "1h", 0, bt.DAY)
    n = len(ts)
    arr = lambda x: np.full(n, x, dtype=float)  # noqa: E731
    ents = [{"strategy": st["id"], "side": st["side"], "match": np.array([t in m for t in ts]), "stop": np.zeros(n, dtype=bool), "vol": arr(2.0),
             "tracker": tr} for (st, tr), m in zip(pairs, (long_match, short_match))]
    return {"t": np.array(ts, dtype=np.int64), "open": arr(100.0), "close": arr(100.0), "high": arr(100.0), "low": arr(100.0), "entries": ents}


def test_two_strategies_share_one_symbol_slot_and_take_turns(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, book=BOOK2, pos={**DCA, "take_profit_rate": 2.0})
    sig = lambda ts, **kw: {"AAA": _sig2(w.b, "AAA", ts, **kw), "BBB": _sig2(w.b, "BBB", ts)}  # noqa: E731
    long_m, short_m = (e["tracker"] for e in w.b.runner.books[0]["entries"])
    assert long_m.slot == short_m.slot == 0                                       # cùng slot venue (OKX net mode: một vị thế mỗi symbol)
    w.b.step(T0B + HOUR, sig([T0B], long_match={T0B}, short_match={T0B}), {})
    assert long_m.is_open and not short_m.is_open and len(w.posts("/trade/order", ordType="market")) == 1     # long đứng trước theo thứ tự sổ
    assert w.b.runner.rejected_for_risk >= 1                                      # short bị admit_entry chặn (max_per_symbol = 1)
    # DCA khớp: chỉ manager đang mở nhận sự kiện của slot
    (dca,) = [o for o in w.limits() if o["ordType"] == "post_only"]
    pos = w.fake.pos["AAA-USDT-SWAP"]
    w.fake.pos["AAA-USDT-SWAP"] = {"pos": f"{float(pos['pos']) + float(dca['sz']):g}", "avgPx": "99.5"}
    w.b.watch(T0B + HOUR + 15_000)
    assert long_m.layer_count == 2 and not short_m.is_open and short_m.layer_count == 0
    # sàn đóng long -> nến sau short vào được (sell), SL trên giá vào
    w.fake.pos.pop("AAA-USDT-SWAP")
    w.fake.add_history("AAA", 99.0, fee=-1.0, pnl=-5.0, c_time=T0B + HOUR, u_time=T0B + HOUR + 20_000)
    w.fake.last["AAA"] = 99.0
    w.b.watch(T0B + HOUR + 25_000)
    assert not long_m.is_open
    w.fake.fill_px = "99.95"
    w.b.step(T0B + 2 * HOUR + 3 * HOUR, sig([T0B, T0B + HOUR, T0B + 2 * HOUR, T0B + 3 * HOUR, T0B + 4 * HOUR], short_match={T0B + 4 * HOUR}), {})
    assert short_m.is_open and not long_m.is_open
    assert w.posts("/trade/order", ordType="market")[-1]["side"] == "sell"
    (sl,) = w.algos("conditional")
    assert sl["side"] == "buy" and float(sl["slTriggerPx"]) > short_m.avg


# ── legacy / paper không đổi ─────────────────────────────────────────────────────
def test_state_key_per_mode_dirs_and_engine_suffix_only_when_not_default():
    assert live_state_key("okx", "demo") == "testnet/okx_main" and live_state_key("okx", "demo", "explore") == "testnet/okx_explore"
    assert live_state_key("okx", "demo", "main", "unified") == "testnet/okx_main"                 # unified = mặc định của demo
    assert live_state_key("okx", "demo", "main", "legacy") == "testnet/okx_main_legacy"
    assert live_state_key("okx", "live", "main", "legacy") == "live/okx_main_legacy"
    assert live_state_key("okx", "paper", "main", "unified") == "paper/okx_main"          # paper + unified = PaperBook event, dùng chung thư mục
    assert lb.DEFAULTS["engine"] == ""                                                       # rỗng = mặc định theo chế độ


def test_bot_request_engine_default_legacy_and_passed_to_job(monkeypatch):
    req = live_router.BotRequest()
    assert req.engine is None
    with pytest.raises(Exception):
        live_router.BotRequest(engine="bogus")
    seen = {}
    monkeypatch.setattr(live_router.batch_jobs_routes, "http_launch", lambda kind, params: seen.update(kind=kind, params=params) or {"id": "j1"})
    monkeypatch.setattr(live_router.batch_jobs, "list_jobs", lambda **k: [])
    live_router.start_bot(live_router.BotRequest(mode="demo", engine="unified", equity_drift_halt_pct=2.5))
    assert seen["kind"] == "live_bot" and seen["params"]["engine"] == "unified" and seen["params"]["equity_drift_halt_pct"] == 2.5
    lb.options(lb.DEFAULTS, seen["params"])                                        # tham số hợp lệ với DEFAULTS của job
    live_router.start_bot(live_router.BotRequest(mode="demo"))
    assert seen["params"]["engine"] == ""                                          # bot tự chọn engine mặc định của chế độ


def test_corrupt_paper_pkl_archived_and_fresh_shadow_started(tmp_path, monkeypatch):
    sdir = tmp_path / "st"
    sdir.mkdir()
    (sdir / "paper.pkl").write_bytes(b"\x80\x04 khong phai pickle hop le")
    monkeypatch.setattr(lb, "load_book", lambda *a, **k: BOOK)

    class Client:
        def filters(self, sym):
            return Filters(0.01, 0.001, 0.001, 5.0)
    monkeypatch.setattr(lb, "make_adapter", lambda *a, **k: (Client(), None))
    monkeypatch.setattr(lb.Bot, "step", lambda self, now, data=None, funding=None: {"equity": 0})
    out = lb.run_job({"mode": "paper", "once": True, "state_dir": str(sdir), "capital": 5000.0})
    assert out["steps"] == 1
    # T7: bot thường (không unified) nạp paper.pkl qua state_migrate; pickle hỏng -> cất vào archive_p94b_*/ (không còn paper.pkl.corrupt_*), bắt đầu sạch, ghi cảnh báo
    arch = [n for n in os.listdir(sdir) if n.startswith("archive_p94b_")]
    assert arch and os.path.isfile(sdir / arch[0] / "paper.pkl") and not os.path.exists(sdir / "paper.pkl")
    ev = [json.loads(x) for x in open(sdir / "events.jsonl", encoding="utf-8")]
    assert any(e["kind"] == "warn" and "paper.pkl cũ không chuyển được" in e.get("msg", "") for e in ev)
    assert os.path.isfile(sdir / "paper.json") and os.path.isfile(sdir / "paper_state.npz")      # bóng KernelBook mới đã được ghi lại hợp lệ
    assert json.load(open(sdir / "paper.json", encoding="utf-8"))["last_t"] is None


def test_load_pickle_helper_handles_missing_and_corrupt(tmp_path):
    logs = []
    assert lb.load_pickle(str(tmp_path / "none.pkl"), logs.append, "x") is None and logs == []
    p = tmp_path / "a.pkl"
    p.write_bytes(b"")
    assert lb.load_pickle(str(p), logs.append, "a.pkl") is None and not p.exists() and logs and "a.pkl hỏng" in logs[0]["msg"]
    p.write_bytes(pickle.dumps({"ok": 1}))
    assert lb.load_pickle(str(p), logs.append, "a.pkl") == {"ok": 1}


def test_sim_venue_old_pickle_without_rejects_loads_and_rejects_like_new():
    """paper.pkl của bot đang chạy (trước P6.8b) không có `_Slot.rejects`: nạp lại vẫn dùng được."""
    from backend.core.models import OrderRejected
    from backend.core.backtest import SimVenue, Order, OrderKind
    v = SimVenue()
    v.add_slot(0, fee_rate=0.0005, maker_fee_rate=0.0002, slippage_rate=0.0002)
    del v._slots[0].__dict__["rejects"]
    v2 = pickle.loads(pickle.dumps(v))
    v2.submit(Order(1, 0, OrderKind.SL, False, level=99.0))
    ev = v2.next_event(0)
    assert isinstance(ev, OrderRejected) and (ev.reason, ev.kind) == ("no_position", "sl") and v2.open_orders(0) == []


def test_live_bot_job_accepts_engine_params():
    """Lỗi thật 2026-10-06: whitelist job live_bot thiếu engine -> API trả 400 và bot unified không bật được qua API."""
    from backend.optimize.process.process import KINDS
    allowed = KINDS["live_bot"]["params"]
    assert {"engine", "equity_drift_halt_pct"} <= allowed
    from backend.live.live import DEFAULTS
    assert set(DEFAULTS) <= allowed | {"state_dir"}


def test_route_engine_resolved_from_latest_job_else_mode_default_and_read_never_creates_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path))
    jobs = []
    monkeypatch.setattr(live_router.batch_jobs, "list_jobs", lambda **k: jobs)
    assert live_router._engine_for("okx", "demo", "main", None) == "unified" and live_router._engine_for("okx", "paper", "main", None) == "legacy"
    jobs.append({"params": {"mode": "demo", "venue": "okx", "book": "main", "engine": "legacy"}})
    assert live_router._engine_for("okx", "demo", "main", None) == "legacy" and live_router._engine_for("okx", "demo", "explore", None) == "unified"
    assert live_router._engine_for("okx", "demo", "main", "unified") == "unified"                 # tham số tường minh thắng
    d = live_router._sdir("okx", "demo", "main")
    assert d.endswith(os.path.join("live", "testnet", "okx_main_legacy")) and not os.path.exists(os.path.join(str(tmp_path), "live"))
    assert live_router.bot_status(mode="demo", venue="okx", events=0, book="main", engine=None)["engine"] == "legacy"
    assert not os.path.exists(os.path.join(str(tmp_path), "live"))
