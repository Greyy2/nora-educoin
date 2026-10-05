"""E9: bot theo sổ (backend/live) — tín hiệu trùng engine, khớp/thoát/kill switch của paper, lệnh + đối soát testnet (sàn giả), bộ lọc sàn, khoá."""
import json
import os

import numpy as np
import pytest

from backend.live import bot as lb
from backend.live import signals as ls
from backend.live.exchange import Filters
from backend.live.secrets import load_keys, redact
from test_strategy_book import SYMS, T0, market  # noqa: F401  (market là fixture: 70 ngày, 3 tài sản)

DAY, HOUR = 86_400_000, 3_600_000
F = lambda fr, c: {"frame": fr, "column": c, "index": 0}  # noqa: E731
POS = {"market": "perp", "leverage": 10, "exit_unit": "atr", "atr_frame": "1h", "atr_period": 14, "sizing": "risk",
       "risk_per_trade_pct": 1.0, "max_notional_pct": 300.0, "stop_loss_rate": 2.0, "take_profit_rate": 3.0, "timeout": 600, "cooldown": 60}
RSI = {"id": "rsi_1h", "side": "LONG", "tree": [[[F("1h", "rsi_14"), "<", 45]]], "position": POS}


def test_live_signals_equal_engine_signals(market):
    """E9-S1 AC4: cùng lịch sử nến -> tín hiệu của bot TRÙNG engine (cùng _build_matrix / VectorEvaluator)."""
    from backend.core.backtest.portfolio import PortfolioEngine
    from backend.core.data.loader import CandleLoader
    sym, start, end = "BBB@perp", T0 + 20 * DAY, T0 + 68 * DAY
    sts = [RSI, {**RSI, "id": "rsi_1h_s", "side": "SHORT", "tree": [[[F("4h", "rsi_14"), ">", 55]]]}]
    pe = PortfolioEngine([sym], sts, start, end, trade_start_ts=start, use_cache=False, base_frame="1h")
    pe.load_data()
    bk = pe.books[0]
    frames = {fr: CandleLoader(sym, frame=fr, use_cache=False).load_data(0, end) for fr in ls.required_frames(sym, sts, "1h")}
    assert set(frames) >= {"1h", "4h"}
    out = ls.evaluate(sym, sts, frames, "1h")
    idx = np.searchsorted(out["t"], bk["data"]["t"])
    assert (out["t"][idx] == bk["data"]["t"]).all()
    for e_eng, e_bot in zip(bk["entries"], out["entries"]):
        assert e_eng["match"].sum() > 0
        assert (e_eng["match"] == e_bot["match"][idx]).all() and (e_eng["stop"] == e_bot["stop"][idx]).all()
        assert np.allclose(e_eng["vol"], e_bot["vol"][idx], equal_nan=True)


def test_klines_frame_drops_unclosed_bar():
    rows = [[0, "1", "2", "0.5", "1.5", "10", HOUR - 1], [HOUR, "1.5", "3", "1", "2", "5", 2 * HOUR - 1]]
    df = ls.klines_frame(rows, now_ms=HOUR + 10)
    assert list(df["open_time"]) == [0] and df["close"].iloc[0] == 1.5 and df["is_filled"].iloc[0] == 0


# ── bot trên dữ liệu dựng tay ───────────────────────────────────────────────
def _defaults(cid):
    from backend.core.strategy.book import BY_ID, schema_defaults
    from legacy_candidates import LEGACY_BY_ID
    return schema_defaults({**LEGACY_BY_ID, **BY_ID}[cid])


BOOK = {"status": "READY_FOR_TESTNET", "timeframe": "1h", "universe": ["AAA@perp", "BBB@perp"], "risk_per_trade_pct": 1.0,
        "risk": {"max_positions": 8, "max_per_symbol": 1, "max_gross_exposure": 3.0, "kill_switch_dd_pct": 30.0},
        "strategies": [{"id": "trend_long", "params": _defaults("trend_long")}], "source": "test"}


def _bot(tmp_path, mode="paper", client=None, filters=None, book=None):
    events = []
    b = lb.Bot(book or BOOK, mode, client, lb.State(str(tmp_path / "state.json"), 10_000.0), events.append, filters)
    return b, events


def _sig(b, sym, ts, match=None, stop=None, close=100.0, low=None, high=None, vol=2.0):
    """Dữ liệu một tài sản trên các nến ts: match/stop = tập open_time có tín hiệu."""
    _, pairs = ls._engine(f"{sym}@perp", b.strategies, "1h", 0, DAY)
    st, tr = pairs[0]
    n = len(ts)
    arr = lambda x: np.full(n, x, dtype=float)  # noqa: E731
    return {"t": np.array(ts, dtype=np.int64), "open": arr(close), "close": arr(close), "high": arr(high or close), "low": arr(low or close),
            "entries": [{"strategy": st["id"], "side": st["side"], "match": np.array([t in (match or ()) for t in ts]),
                         "stop": np.array([t in (stop or ()) for t in ts]), "vol": arr(vol), "tracker": tr}]}


def test_paper_bot_catches_up_missed_bars_with_engine_tracker(tmp_path):
    b, ev = _bot(tmp_path)
    t0 = 100 * HOUR
    b.step(t0 + HOUR, {"AAA": _sig(b, "AAA", [t0 - HOUR, t0], match={t0}), "BBB": _sig(b, "BBB", [t0 - HOUR, t0])}, {})
    assert b.paper.last_t == t0 and not b.state.d["positions"]                  # khởi động: chỉ nến cuối, tín hiệu -> lệnh chờ
    # bot nghỉ 2 nến: chạy bù t0+1h, t0+2h; lệnh vào ở open của t0+1h (đúng engine)
    ts = [t0 - HOUR, t0, t0 + HOUR, t0 + 2 * HOUR]
    r = b.step(t0 + 3 * HOUR, {"AAA": _sig(b, "AAA", ts, match={t0}), "BBB": _sig(b, "BBB", ts)}, {})
    pos = b.state.d["positions"]["AAA"]
    assert b.paper.last_t == t0 + 2 * HOUR and r["positions"] == 1 and pos["entry_time"] == t0 + HOUR
    saved = json.load(open(tmp_path / "state.json"))
    assert saved["last_bar"] == t0 + 3 * HOUR and saved["paper"]["positions"] == 1 and "AAA" in saved["positions"]
    # chạm SL trong nến kế -> đóng bởi tracker của engine
    sl = pos["avg"] * (1 - b.paper.books[0]["entries"][0]["tracker"].sl_pct / 100)
    ts2 = ts + [t0 + 3 * HOUR]
    b.step(t0 + 4 * HOUR, {"AAA": _sig(b, "AAA", ts2, low=sl * 0.98), "BBB": _sig(b, "BBB", ts2)}, {})
    assert not b.state.d["positions"] and b.state.d["trades"][-1]["reason"].startswith("Stop-loss")
    assert any(e["kind"] == "close" for e in ev)


# ── sàn (demo) với adapter giả — cùng giao diện OkxAdapter / BinanceAdapter ─────────────────
class FakeAdapter:
    def __init__(self, live=None):
        self.calls, self.live = [], {k: [q, 100.0] for k, q in (live or {}).items()}

    def prepare(self, sym, lev):
        self.calls.append(("prepare", sym, lev))

    def market_open(self, sym, side, qty):
        self.calls.append(("market", sym, side, qty))
        self.live[sym] = [qty if side == "LONG" else -qty, 100.5]
        return 100.5

    def place_sl(self, sym, side, qty, trigger):
        self.calls.append(("sl", sym, side, qty, trigger))

    def place_tp(self, sym, side, qty, px):
        self.calls.append(("tp", sym, side, qty, px))

    def place_post_only(self, sym, side, qty, px):
        self.calls.append(("post_only", sym, side, qty, px))

    def cancel_all(self, sym):
        self.calls.append(("cancel_all", sym))

    def close_market(self, sym):
        self.calls.append(("close", sym))
        self.live.pop(sym, None)

    def positions(self):
        return {s: (q, px) for s, (q, px) in self.live.items()}

    def equity(self):
        return 10000.0


DCA_BOOK_PARAMS = {**_defaults("trend_long"), "take_profit_rate": 2.0}


def _dca_book():
    """trend_long + thang DCA 3 tầng (bước 1/2/3%, hệ số 1,5/2/2) — kiểm đường DCA của bot."""
    book = {**BOOK, "strategies": [{"id": "trend_long", "params": DCA_BOOK_PARAMS}]}
    return book


def test_demo_orders_dca_ladder_protection_and_reconcile(tmp_path, monkeypatch):
    fake = FakeAdapter(live={"BBB": 0.5})                                       # vị thế BBB không do bot mở
    flt = {s: Filters(0.01, 0.001, 0.001, 5.0) for s in ("AAA", "BBB")}
    orig = lb.book_strategies

    def with_dca(book):
        sts = orig(book)
        for st in sts:
            st["position"] = {**st["position"], "dca_steps": [1.0, 2.0, 3.0], "dca_multipliers": [1.5, 2.0, 2.0]}
        return sts
    monkeypatch.setattr(lb, "book_strategies", with_dca)
    b, ev = _bot(tmp_path, "demo", fake, flt, _dca_book())
    t0 = 50 * HOUR
    sig = lambda **kw: {"AAA": _sig(b, "AAA", [t0], **kw), "BBB": _sig(b, "BBB", [t0], match={t0})}  # noqa: E731
    b.step(t0 + HOUR, sig(match={t0}), {})
    p = b.state.d["positions"]["AAA"]
    assert "BBB" not in b.state.d["positions"] and b.state.d["external"] == ["BBB"]
    kinds = [c[0] for c in fake.calls]
    assert kinds[:3] == ["prepare", "market", "cancel_all"] and fake.calls[1][2] == "LONG" and p["avg"] == 100.5
    assert fake.calls[1][3] == flt["AAA"].qty(fake.calls[1][3])
    sl = next(c for c in fake.calls if c[0] == "sl")
    assert sl[4] == flt["AAA"].price(100.5 * (1 - p["sl_pct"] / 100))
    tp = next(c for c in fake.calls if c[0] == "tp")
    assert tp[4] == flt["AAA"].price(100.5 * (1 + p["tp_pct"] / 100))
    ladder = [c for c in fake.calls if c[0] == "post_only"]
    assert len(ladder) == 3 and [c[4] for c in ladder] == [lay["price"] for lay in p["ladder"]]
    # exit_unit "atr": bước DCA tính theo ATR% như engine (vol = 2 -> bước 2%, 4%, 6%)
    assert ladder[0][4] == flt["AAA"].price(100.5 * 0.98) and ladder[1][4] == flt["AAA"].price(100.5 * 0.98 * 0.96)
    assert ladder[1][3] > ladder[0][3] > 0
    # tầng 1 khớp trên sàn -> cập nhật giá TB + khối lượng, đặt lại SL/TP từ giá TB mới, còn 2 tầng
    q1 = p["qty"] + p["ladder"][0]["qty"]
    fake.live["AAA"] = [q1, 100.0]
    n_before = len(fake.calls)
    b.step(t0 + 2 * HOUR, sig(), {})
    p = b.state.d["positions"]["AAA"]
    assert p["filled_layers"] == 1 and p["avg"] == 100.0 and p["qty"] == pytest.approx(q1)
    new = fake.calls[n_before:]
    assert next(c for c in new if c[0] == "sl")[4] == flt["AAA"].price(100.0 * (1 - p["sl_pct"] / 100))
    assert len([c for c in new if c[0] == "post_only"]) == 2 and any(e["kind"] == "dca" for e in ev)
    # sàn đã đóng AAA (SL) -> đối soát: bỏ vị thế, huỷ lệnh treo, không mở trùng
    fake.live.pop("AAA")
    n_market = kinds.count("market")
    b.step(t0 + 3 * HOUR, sig(), {})
    assert "AAA" not in b.state.d["positions"] and b.state.d["trades"][-1]["layers"] == 2
    assert [c[0] for c in fake.calls].count("market") == n_market
    assert "paper" in json.load(open(tmp_path / "state.json"))                    # bóng paper chạy cùng nến để đối chiếu


def test_okx_adapter_signing_contracts_and_candle_paging(monkeypatch):
    import base64, hashlib, hmac  # noqa: E401
    from backend.live import okx
    a = okx.OkxAdapter(("K", "S", "P"), demo=True, pause=0)
    a._inst["BTC"] = {"ctVal": "0.01", "lotSz": "0.01", "minSz": "0.01", "tickSz": "0.1"}
    assert a.contracts("BTC", 0.0567) == "5.67" and a.contracts("BTC", 0.05679) == "5.67"   # coin -> hợp đồng, làm tròn xuống lotSz
    f = a.filters("BTC")
    assert f.step == pytest.approx(0.0001) and f.min_qty == pytest.approx(0.0001) and f.tick == 0.1
    seen = {}

    class R:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        seen["h"] = dict(req.headers)
        seen["url"] = req.full_url
        return R(b'{"code":"0","data":[{"posMode":"net_mode"}]}')
    monkeypatch.setattr(okx.urllib.request, "urlopen", fake_urlopen)
    a.check_account()
    h = {k.lower(): v for k, v in seen["h"].items()}
    assert h["x-simulated-trading"] == "1" and h["ok-access-key"] == "K" and h["ok-access-passphrase"] == "P"
    msg = h["ok-access-timestamp"] + "GET" + "/api/v5/account/config"
    assert h["ok-access-sign"] == base64.b64encode(hmac.new(b"S", msg.encode(), hashlib.sha256).digest()).decode()
    # nến: 300 mới + phân trang history 100/lần tới đủ limit, tăng dần, có close_time
    H = 3_600_000
    calls = []

    def req(method, path, params=None, body=None, signed=False):
        calls.append((path, dict(params or {})))
        if path.endswith("/candles"):
            return [[str(1000 * H - k * H), "1", "2", "0.5", "1.5", "10", "0.1", "15", "1"] for k in range(300)]
        after = int(params["after"])
        return [[str(after - (k + 1) * H), "1", "2", "0.5", "1.5", "10", "0.1", "15", "1"] for k in range(100)]
    a._req = req
    rows = a.klines("BTC", "1h", 450, now=1001 * H)
    assert len(rows) == 450 and rows[-1][0] == 1000 * H and rows[0][0] == 1000 * H - 449 * H and rows[0][6] == rows[0][0] + H - 1
    assert rows[0][5] == "15"                       # volume = volCcyQuote (USDT) như dữ liệu backtest, không phải số hợp đồng
    assert [c[1]["bar"] for c in calls] == ["1H"] * 3 and calls[1][1]["after"] == 1000 * H - 299 * H
    assert a.klines("BTC", "24h", 10, now=1001 * H) and calls[-1][1]["bar"] == "1Dutc"


def test_okx_keys_file_and_mode_guards(tmp_path, monkeypatch):
    from backend.live.secrets import load_okx
    for k in ("NORA_OKX_KEY", "NORA_OKX_SECRET", "NORA_OKX_PASSPHRASE", "NORA_OKX_DEMO"):
        monkeypatch.delenv(k, raising=False)
    p = tmp_path / "okx.env"
    p.write_text("NORA_OKX_KEY=k1\nNORA_OKX_SECRET=s1\nNORA_OKX_PASSPHRASE=p1\n")
    os.chmod(p, 0o600)
    assert load_okx(str(p)) == (("k1", "s1", "p1"), True)                         # mặc định: khoá demo
    p.write_text("NORA_OKX_KEY=k1\nNORA_OKX_SECRET=s1\nNORA_OKX_PASSPHRASE=p1\nNORA_OKX_DEMO=0\n")
    assert load_okx(str(p))[1] is False
    os.chmod(p, 0o644)
    with pytest.raises(PermissionError):
        load_okx(str(p))
    monkeypatch.setenv("NORA_OKX_KEYS_FILE", str(tmp_path / "none.env"))
    with pytest.raises(SystemExit):
        lb.make_adapter("okx", "demo")                                            # thiếu khoá
    adapter, keys = lb.make_adapter("okx", "paper")
    assert adapter.venue == "okx" and keys is None and adapter.demo is False
    with pytest.raises(SystemExit):
        lb.run_job({"mode": "live"})                                              # live cần confirm_live


def test_filters_round_down_and_reject_small():
    f = Filters(tick=0.1, step=0.001, min_qty=0.001, min_notional=5.0)
    assert f.qty(0.12399) == 0.123 and f.price(101.27) == 101.2
    assert f.check(0.0005, 100) and "minQty" in f.check(0.0005, 100)
    assert "minNotional" in f.check(0.01, 100) and f.check(0.1, 100) is None


def test_secrets_file_permissions_and_redaction(tmp_path, monkeypatch):
    monkeypatch.delenv("NORA_BINANCE_TESTNET_KEY", raising=False)
    monkeypatch.delenv("NORA_BINANCE_TESTNET_SECRET", raising=False)
    p = tmp_path / "keys.env"
    p.write_text("NORA_BINANCE_TESTNET_KEY=abcKEY123\nNORA_BINANCE_TESTNET_SECRET=sss999\n")
    os.chmod(p, 0o644)
    with pytest.raises(PermissionError):
        load_keys(str(p))
    os.chmod(p, 0o600)
    assert load_keys(str(p)) == ("abcKEY123", "sss999")
    assert load_keys(str(tmp_path / "none.env")) is None
    s = redact("key=abcKEY123 secret=sss999 url?x=1&signature=deadbeef0011 tok=" + "A" * 40, ("abcKEY123", "sss999"))
    assert "abcKEY123" not in s and "sss999" not in s and "deadbeef" not in s and "A" * 40 not in s


def test_live_bot_job_registered_no_lock():
    from backend.api.jobs import batch
    assert "live_bot" in batch.KINDS and "live_bot" in batch.NO_LOCK_KINDS
    assert batch.job_label("live_bot", {"mode": "demo", "venue": "okx", "once": True}) == "Bot sổ · okx demo · một bước"


def test_book_must_be_ready_for_testnet(tmp_path):
    (tmp_path / "book.json").write_text(json.dumps({**BOOK, "status": "HOLDOUT_FAILED"}))
    with pytest.raises(SystemExit):
        lb.load_book(str(tmp_path))


def test_explore_book_only_paper_or_demo(tmp_path):
    (tmp_path / "explore").mkdir()
    (tmp_path / "explore" / "book.json").write_text(json.dumps({**BOOK, "status": "EXPLORE_DEMO"}))
    assert lb.load_book(str(tmp_path), kind="explore", mode="demo")["status"] == "EXPLORE_DEMO"
    with pytest.raises(SystemExit):
        lb.load_book(str(tmp_path), kind="explore", mode="live")              # sổ chưa kiểm định không bao giờ chạy vốn thật
    (tmp_path / "book.json").write_text(json.dumps({**BOOK, "status": "EXPLORE_DEMO"}))
    with pytest.raises(SystemExit):
        lb.load_book(str(tmp_path))                                            # sổ chính không nhận trạng thái thử nghiệm


# ── paper = engine (từng nến), gồm cả DCA ───────────────────────────────────
DCA = {"id": "dca_long", "side": "LONG", "tree": [[[F("1h", "rsi_14"), "<", 40]]],
       "dca": [{"condition": [[[F("1h", "rsi_14"), "<", 32]]]}],   # dồn có điều kiện: chỉ dồn khi RSI còn thấp
       "position": {"market": "perp", "leverage": 5, "exit_unit": "pct", "sizing": "margin_pct", "order_size_pct": 8.0,
                    "take_profit_rate": 2.5, "stop_loss_rate": 6.0, "timeout": 2880, "cooldown": 60,
                    "dca_steps": [0.4, 0.8, 1.2], "dca_multipliers": [1.5, 2.0, 2.0]}}
SHORT = {"id": "trend_s", "side": "SHORT", "tree": [[[F("4h", "rsi_14"), ">", 58]]], "stop": [{"condition": [[[F("1h", "rsi_14"), "<", 40]]]}],
         "position": {**POS, "trailing_stop": 1.5, "trailing_activation_pct": 1.0}}


@pytest.mark.parametrize("risk", [{"max_positions": 8, "max_per_symbol": 1, "max_gross_exposure": 3.0, "kill_switch_dd_pct": 30.0},
                                  {"max_positions": 2, "max_per_symbol": 1, "max_gross_exposure": 0.5, "kill_switch_dd_pct": 2.0}])
def test_paper_book_replays_engine_trades_exactly(market, risk):
    """PaperBook từng nến (PositionTracker + vòng danh mục) == PortfolioEngine (kernel): cùng lệnh, cùng giá, cùng lãi/lỗ — với trend, DCA,
    tín hiệu thoát, trailing, giới hạn danh mục và kill switch (bộ risk thứ 2 chặt để kích hoạt chặn + kill switch)."""
    from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
    from backend.live.paper import PaperBook
    syms = [f"{s}@perp" for s in SYMS]
    sts = [DCA, RSI, SHORT]
    start, end = T0 + 15 * DAY, T0 + 68 * DAY
    pe = PortfolioEngine(syms, sts, start - 10 * DAY, end, trade_start_ts=start, risk=RiskConfig.from_dict(risk), use_cache=False,
                         base_frame="1h", close_at_end=False)
    pe.run()
    res = pe.get_results()
    want = sorted((p.symbol, p.strategy_id, int(p.enter_time), int(p.close_time), round(p.close_price, 6), round(p.real_pnl, 6), p.layers)
                  for p in res["positions"])
    assert want
    if risk["kill_switch_dd_pct"] >= 30:
        assert any(w[6] > 1 for w in want)                                         # có lệnh DCA nhiều tầng
    else:
        assert res.get("halted_at") is not None                                    # bộ risk chặt: kill switch kích hoạt
    pb = PaperBook(sts, syms, "1h", pe.initial_capital, risk, trade_start=start)
    grid = sorted({int(t) for bk in pe.books for t in bk["data"]["t"]})
    pos = {bk["symbol"]: {int(t): i for i, t in enumerate(bk["data"]["t"])} for bk in pe.books}
    fptr = {bk["symbol"]: 0 for bk in pe.books}
    for t in grid:
        bars, sig, fund = {}, {}, {}
        for bk in pe.books:
            s, d = bk["symbol"], bk["data"]
            i = pos[s].get(t)
            if i is None:
                continue
            bars[s] = (d["o"][i], d["h"][i], d["l"][i], d["c"][i])
            sig[s] = [{"match": e["match"][i], "stop": e["stop"][i], "vol": e["vol"][i] if e["vol"] is not None else None,
                       "dca": bool(e["dca"][i]) if e.get("dca") is not None else True} for e in bk["entries"]]
            fl = []
            while fptr[s] < len(d["f_t"]) and d["f_t"][fptr[s]] <= t:
                fl.append((int(d["f_t"][fptr[s]]), float(d["f_r"][fptr[s]])))
                fptr[s] += 1
            fund[s] = fl
        pb.step_bar(t, bars, sig, fund)
    got = sorted((x["symbol"], x["strategy"], x["enter_time"], x["close_time"], round(x["close_price"], 6), round(x["pnl"], 6), x["layers"])
                 for x in pb.trades)
    assert got == want
    assert (pb.halted_at is not None) == (res.get("halted_at") is not None)


def test_stale_state_of_other_book_is_archived(tmp_path):
    from backend.live import bot as lb
    sdir, spath = str(tmp_path), str(tmp_path / "state.json")
    lb._archive_stale_state(sdir, spath, {"generated_at": 1})          # chưa có gì: không làm gì
    assert os.listdir(sdir) == []
    with open(spath, "w") as fh:
        json.dump({"book": 1}, fh)
    (tmp_path / "paper.pkl").write_bytes(b"x")
    lb._archive_stale_state(sdir, spath, {"generated_at": 1})          # cùng sổ: giữ nguyên
    assert sorted(os.listdir(sdir)) == ["paper.pkl", "state.json"]
    lb._archive_stale_state(sdir, spath, {"generated_at": 2})          # sổ mới: cất trạng thái cũ
    left = os.listdir(sdir)
    assert len(left) == 1 and left[0].startswith("archive_") and sorted(os.listdir(tmp_path / left[0])) == ["paper.pkl", "state.json"]


def test_symbol_without_api_permission_is_skipped(tmp_path):
    """Khoá API không được giao dịch AAA (OKX 50123) -> cảnh báo, không vị thế, các nến sau không thử lại AAA; mã khác vẫn đánh."""
    from backend.live.exchange import NotPermitted

    class Denied(FakeAdapter):
        def market_open(self, sym, side, qty):
            if sym == "AAA":
                self.calls.append(("denied", sym))
                raise NotPermitted('OKX POST /api/v5/trade/order -> 401: {"code":"50123"}')
            return super().market_open(sym, side, qty)
    fake = Denied()
    flt = {s: Filters(0.01, 0.001, 0.001, 5.0) for s in ("AAA", "BBB")}
    b, ev = _bot(tmp_path, "demo", fake, flt, BOOK)
    t0 = 50 * HOUR
    sig = lambda: {"AAA": _sig(b, "AAA", [t0], match={t0}), "BBB": _sig(b, "BBB", [t0], match={t0})}  # noqa: E731
    b.step(t0 + HOUR, sig(), {})
    assert "AAA" not in b.state.d["positions"] and "BBB" in b.state.d["positions"] and b.state.d["blocked"] == ["AAA"]
    assert any(e["kind"] == "warn" and e.get("symbol") == "AAA" for e in ev)
    b.step(t0 + 2 * HOUR, sig(), {})
    assert [c[0] for c in fake.calls].count("denied") == 1


def test_okx_permission_error_maps_to_not_permitted(monkeypatch):
    import io
    import urllib.error
    from backend.live import okx
    from backend.live.exchange import NotPermitted
    a = okx.OkxAdapter(("K", "S", "P"), demo=True, pause=0)

    def deny(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 401, "x", {}, io.BytesIO(b'{"msg":"no permission for the Crypto","code":"50123"}'))
    monkeypatch.setattr(okx.urllib.request, "urlopen", deny)
    with pytest.raises(NotPermitted):
        a._req("POST", "/api/v5/trade/order", body={}, signed=True)


def test_live_trades_equity_series_from_events(tmp_path, monkeypatch):
    """Đường vốn trên trang Live: sự kiện "step" khử trùng theo nến (giữ bản cuối), sắp theo thời gian, tối đa 2000 điểm; started = "start" đầu tiên."""
    from backend.api.routers import live as live_router
    d = tmp_path / "_cache" / "live" / "okx_demo"
    d.mkdir(parents=True)
    H = 3_600_000
    evs = [{"t": 5, "kind": "start", "venue": "okx"}, {"t": 99, "kind": "start", "venue": "okx"},
           {"t": 10, "kind": "step", "bar": 2 * H, "equity": 101.0},
           {"t": 11, "kind": "step", "bar": 1 * H, "equity": 100.0},
           {"t": 12, "kind": "step", "bar": 2 * H, "equity": 102.5},       # cùng nến -> giữ bản cuối
           {"t": 13, "kind": "order", "bar": 3 * H, "equity": 999.0},       # không phải step
           {"t": 14, "kind": "step", "bar": 3 * H}]                         # thiếu equity
    (d / "events.jsonl").write_text("\n".join(json.dumps(e) for e in evs) + "\n{hỏng\n", encoding="utf-8")
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path))
    r = live_router.bot_trades(mode="demo", venue="okx", limit=10)
    assert r["equity_series"] == [{"t": H, "equity": 100.0}, {"t": 2 * H, "equity": 102.5}] and r["started"] == 5
    series, _ = live_router._equity_series(str(d), cap=1)
    assert series == [{"t": 2 * H, "equity": 102.5}]
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / "none"))
    r = live_router.bot_trades(mode="demo", venue="okx", limit=10)
    assert r["equity_series"] == [] and r["started"] is None


def test_compare_exec_with_paper_and_state_dirs_per_book():
    from backend.live.compare import compare_trades
    H = 3_600_000
    ex = [{"symbol": "BTC", "strategy": "dca_long", "side": "LONG", "qty": 0.1, "avg": 101.0, "entry_time": 10 * H + 5_000,
           "open_price": 101.0, "close_price": 103.0, "pnl": 0.19, "layers": 2, "reason": "Sàn đã đóng (SL/TP)"},
          {"symbol": "ETH", "strategy": "dca_long", "side": "LONG", "qty": 1.0, "avg": 10.0, "entry_time": 30 * H, "layers": 1}]
    pa = [{"symbol": "BTC@perp", "strategy": "dca_long", "enter_time": 10 * H, "enter_price": 100.0, "avg_price": 100.5, "close_price": 103.5,
           "qty": 0.2, "pnl": 0.6, "layers": 2, "reason": "TP"},
          {"symbol": "SOL@perp", "strategy": "dca_long", "enter_time": 12 * H, "enter_price": 5.0, "avg_price": 5.0, "close_price": 5.1,
           "qty": 1, "pnl": 0.1, "layers": 1, "reason": "TP"}]
    out = compare_trades(ex, pa, "1h")
    s = out["summary"]
    assert s["matched"] == 1 and s["only_exec"] == 1 and s["only_paper"] == 1
    q = out["pairs"][0]
    assert q["entry_bps"] == 100.0 and q["close_bps"] == round((103.5 - 103.0) / 103.5 * 10_000, 2)     # sàn mua đắt hơn, bán rẻ hơn: dương
    assert q["ret_pct"][0] == round(0.19 / (0.1 * 101.0) * 100, 4)
    assert lb.state_key("okx", "paper") == "okx_paper" and lb.state_key("okx", "paper", "explore") == "okx_paper_explore"


def test_okx_closed_since_parses_positions_history(monkeypatch):
    from backend.live import okx
    a = okx.OkxAdapter(("K", "S", "P"), demo=True, pause=0)
    rows = [{"cTime": "1000000", "uTime": "2000000", "closeAvgPx": "103.2", "openAvgPx": "101", "realizedPnl": "0.21", "fee": "-0.01",
             "fundingFee": "0"},
            {"cTime": "1", "uTime": "5", "closeAvgPx": "1", "openAvgPx": "1", "realizedPnl": "9", "fee": "0", "fundingFee": "0"}]
    monkeypatch.setattr(a, "_req", lambda *x, **k: rows)
    got = a.closed_since("BTC", 1_000_000)
    assert got["close_price"] == 103.2 and got["open_price"] == 101.0 and got["pnl"] == 0.21 and got["exchange_close_time"] == 2_000_000


def test_okx_equity_is_usdt_in_single_currency_margin(monkeypatch):
    """Lỗi đã gặp trên demo: totalEq gồm cả BTC/OKB trong ví -> khối lượng gấp 20 lần số USDT ký quỹ được, tầng DCA bị từ chối 51008."""
    from backend.live import okx
    a = okx.OkxAdapter(("K", "S", "P"), demo=True, pause=0)
    bal = [{"totalEq": "106651.4", "adjEq": "", "details": [{"ccy": "BTC", "eq": "1"}, {"ccy": "USDT", "eq": "4865.7"}]}]

    def req(method, path, params=None, body=None, signed=False):
        return [{"acctLv": "2"}] if path.endswith("/config") else bal
    monkeypatch.setattr(a, "_req", req)
    assert a.equity() == 4865.7
    a._acct_lv = 3
    bal[0]["adjEq"] = "100000"
    assert a.equity() == 100000.0


def test_close_qty_rounding_and_okx_contracts_no_dust():
    """Lỗi tìm ra bằng phát lại: làm tròn XUỐNG khối lượng lệnh đóng để lại một bước lẻ -> vị thế sót không bao giờ đóng hết."""
    f = Filters(0.01, 0.01, 0.01, 0.0)
    assert f.qty(5.67 * (1 - 1e-8)) == 5.66 and f.qty_close(5.67 * (1 - 1e-8)) == 5.67
    from backend.live import okx
    a = okx.OkxAdapter(None, demo=True, pause=0)
    a._inst["BTC"] = {"ctVal": "0.01", "lotSz": "0.01", "minSz": "0.01", "tickSz": "0.1"}
    assert a.contracts("BTC", 0.0567 * (1 - 1e-12)) == "5.67" and a.contracts("BTC", 0.05669) == "5.66"


def test_watch_reprotects_immediately_after_dca_fill(tmp_path, monkeypatch):
    """Giữa hai nến: tầng DCA khớp trên sàn -> bot.watch đặt lại SL/TP từ giá TB mới ngay (không đợi nến sau)."""
    fake = FakeAdapter()
    flt = {s: Filters(0.01, 0.001, 0.001, 5.0) for s in ("AAA", "BBB")}
    orig = lb.book_strategies

    def with_dca(book):
        sts = orig(book)
        for st in sts:
            st["position"] = {**st["position"], "dca_steps": [1.0, 2.0], "dca_multipliers": [1.5, 2.0]}
        return sts
    monkeypatch.setattr(lb, "book_strategies", with_dca)
    b, ev = _bot(tmp_path, "demo", fake, flt, _dca_book())
    t0 = 50 * HOUR
    b.step(t0 + HOUR, {"AAA": _sig(b, "AAA", [t0], match={t0}), "BBB": _sig(b, "BBB", [t0])}, {})
    p = b.state.d["positions"]["AAA"]
    fake.live["AAA"] = [p["qty"] + p["ladder"][0]["qty"], 99.0]                 # tầng 1 khớp giữa nến
    n = len(fake.calls)
    b.watch(t0 + HOUR + 60_000)
    new = fake.calls[n:]
    assert b.state.d["positions"]["AAA"]["filled_layers"] == 1
    assert any(c[0] == "sl" and c[4] == flt["AAA"].price(99.0 * (1 - p["sl_pct"] / 100)) for c in new)
