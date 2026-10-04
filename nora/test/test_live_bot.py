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


# ── bot paper trên dữ liệu dựng tay ─────────────────────────────────────────
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


def _sig(b, sym, match=False, stop=False, close=100.0, high=None, low=None, vol=2.0):
    _, pairs = ls._engine(f"{sym}@perp", b.strategies, "1h", 0, DAY)
    st, tr = pairs[0]
    return {"t": np.array([0, HOUR]), "close": np.array([close, close]), "high": np.array([high or close, high or close]),
            "low": np.array([low or close, low or close]),
            "entries": [{"strategy": st["id"], "side": st["side"], "match": np.array([False, match]), "stop": np.array([False, stop]),
                         "vol": np.array([vol, vol]), "tracker": tr}]}


def test_paper_entry_sizing_matches_tracker_and_sl_close(tmp_path):
    from backend.core.execute.ledger import CapitalLedger
    b, ev = _bot(tmp_path)
    now = 10 * HOUR
    r = b.step(now, {"AAA": _sig(b, "AAA", match=True), "BBB": _sig(b, "BBB")})
    p = b.state.d["positions"]["AAA"]
    assert r["positions"] == 1 and p["strategy"] == "trend_long" and p["entry_time"] == now
    _, pairs = ls._engine("AAA@perp", b.strategies, "1h", 0, DAY)
    tr = pairs[0][1]
    tr.ledger = CapitalLedger(10_000.0)
    tr._apply_exit_unit(2.0)
    want = tr._risk_margin() * tr.pos_leverage / 100.0
    assert p["qty"] == pytest.approx(want) and p["leverage"] == int(tr.pos_leverage)       # đúng công thức khối lượng của engine
    assert p["sl_price"] == pytest.approx(p["entry_price"] * (1 - tr.sl_pct / 100))
    # nến sau chạm SL -> đóng ở mức SL, ghi cooldown, không vào lại ngay
    b.step(now + HOUR, {"AAA": _sig(b, "AAA", match=True, low=p["sl_price"] * 0.99), "BBB": _sig(b, "BBB")})
    assert "AAA" not in b.state.d["positions"]
    tr_ = b.state.d["trades"][-1]
    assert tr_["reason"] == "Stop-loss" and tr_["pnl"] < 0 and b.state.d["last_close"]["trend_long|AAA"] == now + HOUR
    assert any(e["kind"] == "close" for e in ev)
    saved = json.load(open(tmp_path / "state.json"))
    assert saved["last_bar"] == now + HOUR and saved["cash"] < 10_000


def test_paper_timeout_and_exit_signal(tmp_path):
    b, _ = _bot(tmp_path)
    b.step(0, {"AAA": _sig(b, "AAA", match=True), "BBB": _sig(b, "BBB")})
    to = b.state.d["positions"]["AAA"]["timeout_ms"]
    assert to > 0
    b.step(to, {"AAA": _sig(b, "AAA"), "BBB": _sig(b, "BBB")})
    assert b.state.d["trades"][-1]["reason"] == "Hết thời gian giữ lệnh"
    b.step(to + 5 * HOUR, {"AAA": _sig(b, "AAA", match=True), "BBB": _sig(b, "BBB")})
    b.step(to + 6 * HOUR, {"AAA": _sig(b, "AAA", stop=True), "BBB": _sig(b, "BBB")})
    assert b.state.d["trades"][-1]["reason"] == "Tín hiệu thoát"


def test_kill_switch_closes_all_and_halts(tmp_path):
    b, ev = _bot(tmp_path)
    b.step(0, {"AAA": _sig(b, "AAA", match=True), "BBB": _sig(b, "BBB", match=True)})
    assert len(b.state.d["positions"]) == 2
    b.state.d["peak_equity"] = 20_000.0                        # vốn 10.000 = 50% đỉnh -> sụt > 30%
    r = b.step(HOUR, {"AAA": _sig(b, "AAA", match=True), "BBB": _sig(b, "BBB", match=True)})
    assert r["halted"] and not b.state.d["positions"] and any(e["kind"] == "crit" for e in ev)
    b.step(2 * HOUR, {"AAA": _sig(b, "AAA", match=True), "BBB": _sig(b, "BBB", match=True)})
    assert not b.state.d["positions"]                          # dừng mở mới tới khi xoá cờ halted


# ── testnet với sàn giả ─────────────────────────────────────────────────────
class FakeClient:
    def __init__(self, live=None):
        self.calls, self.live = [], dict(live or {})

    def set_margin_isolated(self, s):
        self.calls.append(("margin", s))

    def set_leverage(self, s, lev):
        self.calls.append(("leverage", s, lev))

    def order(self, **p):
        self.calls.append(("order", p))
        if p.get("type") == "MARKET" and not p.get("reduceOnly"):
            self.live[p["symbol"]] = p["quantity"]
            return {"avgPrice": "100.5"}
        return {}

    def cancel_all(self, s):
        self.calls.append(("cancel_all", s))

    def positions(self):
        return [{"symbol": s, "positionAmt": str(q)} for s, q in self.live.items()]

    def account(self):
        return {"totalMarginBalance": "10000"}


def test_testnet_orders_protection_and_reconcile(tmp_path):
    fake = FakeClient(live={"BBBUSDT": 0.5})                   # vị thế BBB không do bot mở
    flt = {s: Filters(0.01, 0.001, 0.001, 5.0) for s in ("AAA", "BBB")}
    book = {**BOOK, "strategies": [{"id": "trend_long", "params": {**_defaults("trend_long"), "take_profit_rate": 2.0}}]}
    b, _ = _bot(tmp_path, "testnet", fake, flt, book)
    b.step(0, {"AAA": _sig(b, "AAA", match=True), "BBB": _sig(b, "BBB", match=True)})
    assert "AAA" in b.state.d["positions"] and "BBB" not in b.state.d["positions"] and b.state.d["external"] == ["BBB"]
    orders = [c[1] for c in fake.calls if c[0] == "order"]
    assert ("margin", "AAAUSDT") in fake.calls and any(c[0] == "leverage" for c in fake.calls)
    assert orders[0]["type"] == "MARKET" and orders[0]["side"] == "BUY" and orders[0]["quantity"] == flt["AAA"].qty(orders[0]["quantity"])
    sl = next(o for o in orders if o["type"] == "STOP_MARKET")
    assert sl["closePosition"] == "true" and sl["side"] == "SELL" and sl["stopPrice"] < 100.5
    tp = next(o for o in orders if o["type"] == "LIMIT")
    assert tp["reduceOnly"] == "true" and tp["price"] > 100.5 and tp["timeInForce"] == "GTC"
    assert b.state.d["positions"]["AAA"]["entry_price"] == 100.5             # giá khớp thật của sàn
    # sàn đã đóng AAA (SL khớp) -> bước sau đối soát: bỏ vị thế, huỷ lệnh treo, không mở trùng
    fake.live.pop("AAAUSDT")
    n_orders = len(orders)
    b.step(HOUR, {"AAA": _sig(b, "AAA"), "BBB": _sig(b, "BBB")})
    assert "AAA" not in b.state.d["positions"] and ("cancel_all", "AAAUSDT") in fake.calls
    assert len([c for c in fake.calls if c[0] == "order"]) == n_orders


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
