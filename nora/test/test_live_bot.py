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
    from backend.core.strategy.book import CANDIDATES, schema_defaults
    return schema_defaults(next(c for c in CANDIDATES if c["id"] == cid))


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


# ── testnet với sàn giả ─────────────────────────────────────────────────────
class FakeClient:
    def __init__(self, live=None):
        self.calls, self.live = [], {k: [q, 100.0] for k, q in (live or {}).items()}

    def set_margin_isolated(self, s):
        self.calls.append(("margin", s))

    def set_leverage(self, s, lev):
        self.calls.append(("leverage", s, lev))

    def order(self, **p):
        self.calls.append(("order", p))
        if p.get("type") == "MARKET" and not p.get("reduceOnly"):
            self.live[p["symbol"]] = [p["quantity"], 100.5]
            return {"avgPrice": "100.5"}
        if p.get("type") == "MARKET" and p.get("reduceOnly"):
            self.live.pop(p["symbol"], None)
        return {}

    def cancel_all(self, s):
        self.calls.append(("cancel_all", s))

    def positions(self):
        return [{"symbol": s, "positionAmt": str(q), "entryPrice": str(px)} for s, (q, px) in self.live.items()]

    def account(self):
        return {"totalMarginBalance": "10000"}


DCA_BOOK_PARAMS = {**_defaults("trend_long"), "take_profit_rate": 2.0}


def _dca_book():
    """trend_long + thang DCA 3 tầng (bước 1/2/3%, hệ số 1,5/2/2) — kiểm đường DCA của bot."""
    book = {**BOOK, "strategies": [{"id": "trend_long", "params": DCA_BOOK_PARAMS}]}
    return book


def test_testnet_orders_dca_ladder_protection_and_reconcile(tmp_path, monkeypatch):
    fake = FakeClient(live={"BBBUSDT": 0.5})                                   # vị thế BBB không do bot mở
    flt = {s: Filters(0.01, 0.001, 0.001, 5.0) for s in ("AAA", "BBB")}
    orig = lb.book_strategies

    def with_dca(book):
        sts = orig(book)
        for st in sts:
            st["position"] = {**st["position"], "dca_steps": [1.0, 2.0, 3.0], "dca_multipliers": [1.5, 2.0, 2.0]}
        return sts
    monkeypatch.setattr(lb, "book_strategies", with_dca)
    b, ev = _bot(tmp_path, "testnet", fake, flt, _dca_book())
    t0 = 50 * HOUR
    sig = lambda **kw: {"AAA": _sig(b, "AAA", [t0], **kw), "BBB": _sig(b, "BBB", [t0], match={t0})}  # noqa: E731
    b.step(t0 + HOUR, sig(match={t0}), {})
    p = b.state.d["positions"]["AAA"]
    assert "BBB" not in b.state.d["positions"] and b.state.d["external"] == ["BBB"]
    orders = [c[1] for c in fake.calls if c[0] == "order"]
    assert ("margin", "AAAUSDT") in fake.calls and any(c[0] == "leverage" for c in fake.calls)
    assert orders[0]["type"] == "MARKET" and orders[0]["side"] == "BUY" and p["avg"] == 100.5
    sl = next(o for o in orders if o["type"] == "STOP_MARKET")
    assert sl["closePosition"] == "true" and sl["stopPrice"] == flt["AAA"].price(100.5 * (1 - p["sl_pct"] / 100))
    tp = next(o for o in orders if o["type"] == "LIMIT" and o.get("reduceOnly"))
    assert tp["price"] == flt["AAA"].price(100.5 * (1 + p["tp_pct"] / 100))
    ladder = [o for o in orders if o.get("timeInForce") == "GTX"]
    assert len(ladder) == 3 and [o["price"] for o in ladder] == [lay["price"] for lay in p["ladder"]]
    # exit_unit "atr": bước DCA tính theo ATR% như engine (vol = 2 -> bước 2%, 4%, 6%)
    assert ladder[0]["price"] == flt["AAA"].price(100.5 * 0.98) and ladder[1]["price"] == flt["AAA"].price(100.5 * 0.98 * 0.96)
    assert ladder[1]["quantity"] > ladder[0]["quantity"] > 0
    # tầng 1 khớp trên sàn -> bước sau: cập nhật giá TB + khối lượng, đặt lại SL/TP từ giá TB mới, còn 2 tầng
    q1 = p["qty"] + p["ladder"][0]["qty"]
    fake.live["AAAUSDT"] = [q1, 100.0]
    n_before = len(fake.calls)
    b.step(t0 + 2 * HOUR, sig(), {})
    p = b.state.d["positions"]["AAA"]
    assert p["filled_layers"] == 1 and p["avg"] == 100.0 and p["qty"] == pytest.approx(q1)
    new = [c[1] for c in fake.calls[n_before:] if c[0] == "order"]
    assert next(o for o in new if o["type"] == "STOP_MARKET")["stopPrice"] == flt["AAA"].price(100.0 * (1 - p["sl_pct"] / 100))
    assert len([o for o in new if o.get("timeInForce") == "GTX"]) == 2 and any(e["kind"] == "dca" for e in ev)
    # sàn đã đóng AAA (SL) -> đối soát: bỏ vị thế, huỷ lệnh treo, không mở trùng
    fake.live.pop("AAAUSDT")
    n_orders = len([c for c in fake.calls if c[0] == "order"])
    b.step(t0 + 3 * HOUR, sig(), {})
    assert "AAA" not in b.state.d["positions"] and b.state.d["trades"][-1]["layers"] == 2
    assert len([c for c in fake.calls if c[0] == "order"]) == n_orders
    assert "paper" in json.load(open(tmp_path / "state.json"))                    # bóng paper chạy cùng nến để đối chiếu


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
    assert batch.job_label("live_bot", {"mode": "paper", "once": True}) == "Bot sổ · paper · một bước"


def test_book_must_be_ready_for_testnet(tmp_path):
    (tmp_path / "book.json").write_text(json.dumps({**BOOK, "status": "HOLDOUT_FAILED"}))
    with pytest.raises(SystemExit):
        lb.load_book(str(tmp_path))


# ── paper = engine (từng nến), gồm cả DCA ───────────────────────────────────
DCA = {"id": "dca_long", "side": "LONG", "tree": [[[F("1h", "rsi_14"), "<", 40]]],
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
            sig[s] = [{"match": e["match"][i], "stop": e["stop"][i], "vol": e["vol"][i] if e["vol"] is not None else None} for e in bk["entries"]]
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
