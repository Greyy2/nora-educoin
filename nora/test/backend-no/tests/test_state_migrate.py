"""P9.4b T7: paper.pkl CŨ (PaperBook: Runner + PositionTracker / PositionManager) -> KernelBook qua backend/live/live.py (PHẦN B).

(0) an toàn: unpickler hạn chế chỉ nhận lớp cũ (thành _Bag) + collections.deque + getattr; mọi global khác bị từ chối; không import tracker / manager / runner.
(1) với từng pickle của test/fixtures/live_state_p94b (6 file, 5 bot: tracker, event/unified, có / không vị thế mở): nạp vào (a) PaperBook CŨ (còn tới T10) và
    (b) KernelBook đã chuyển, bước N nến giả CÙNG nguồn, so từng bit (float.hex) mọi lệnh đóng, mtm, vị thế mở, sổ vốn, đếm từ chối rủi ro, halted_at.
(2) kết quả đóng băng ở test/fixtures/live_state_p94b/expected/<bot>.json (sinh từ đường CŨ bằng NORA_REGEN_P94B=1): bài (b) so KernelBook với JSON nên còn sống sau T10.
(3) save/load npz + json giữa chừng không đổi kết quả; tham số khác -> ParamsMismatch.
Chuẩn hoá khi nạp đường cũ (pickle cũ hơn mã hiện tại): sổ vốn thiếu `peak` = max(initial, equity); tracker thiếu `intrabar_path` = ohlc; slot SimVenue cũ ở adverse_first -> ohlc
và tắt post_only / rounds_qty (kernel dùng ohlc theo tham số hiện tại, bỏ kiểm post-only — quyết định (b) của P9.4b)."""
import json
from pathlib import Path
import math
import os
import pickle
import random
import sys

from backend.crawl.store import live_dir
import numpy as np
import pytest

from backend.core.backtest import KernelPaperBook, PaperBook
from backend.live import live as sm

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "live_state_p94b")
EXPECTED = os.path.join(FIX, "expected")
BOTS = ["okx_demo", "okx_demo_unified", "okx_paper", "okx_paper_explore", "paper"]
STEP_MS = 900_000
N_BARS = int(os.environ.get("NORA_MIGRATE_BARS", "400"))


def _hx(o):
    if isinstance(o, float):
        return "nan" if math.isnan(o) else o.hex()
    if isinstance(o, dict):
        return {k: _hx(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_hx(v) for v in o]
    return o


def _pkl(bot):
    return os.path.join(FIX, bot, "paper.pkl")


def _real(o):
    """_Bag -> đối tượng thật của mã HIỆN TẠI (chỉ dùng trong test để dựng đường cũ): enum theo giá trị, PositionModel / OrderModel / Account theo __dict__."""
    from backend.core import models as m
    if isinstance(o, sm._Bag):
        name = type(o).__name__
        if name in ("PositionType", "PositionStatus", "OrderType"):
            return getattr(m, name)(o._args[0])
        cls = {"PositionModel": m.PositionModel, "OrderModel": m.OrderModel}[name]
        obj = cls.__new__(cls)
        obj.__dict__.update({k: _real(v) for k, v in o.__dict__.items() if k != "_args"})
        return obj
    if isinstance(o, list):
        return [_real(v) for v in o]
    return o


_STATE_ATTRS = ("qty", "avg", "margin_used", "fees_paid", "layer_count", "last_fill", "entry_time", "reserved_here", "funding_paid", "entry_equity", "next_margin",
                "peak", "mae_usd", "is_open", "pending_entry", "pending_exit", "last_close_time", "dca_rejected", "max_capital", "pos_leverage", "planned_risk",
                "unit_pct", "pending_vol", "skipped_no_vol", "sl_pct", "tp_pct", "trail_pct", "trail_activation_pct", "dca_steps", "dca_ok")


def _old_tracker_book(bag):
    """Pickle định dạng tracker là bố cục PHẲNG trước P6.3 (qty / avg... trong tracker, không có `book`) nên PositionTracker hiện tại không nạp được: dựng PaperBook(tracker)
    từ chính các trường đó (tracker mới từ StrategyParams trong pickle, rồi gán trạng thái) — đúng đường cũ của mã hiện tại, đủ làm gốc so sánh."""
    import dataclasses
    from backend.core.models import Account, PositionType
    from backend.core.backtest import PositionTracker
    from backend.core.params import StrategyParams
    port = sm._port(bag)
    lb = bag.ledger.__dict__
    led = Account(lb["initial"], lb.get("usage", 1.0))
    led.equity, led.reserved, led.rejected = lb["equity"], lb["reserved"], lb.get("rejected", 0)
    led.peak = lb.get("peak", max(lb["initial"], lb["equity"]))
    fields = {f.name for f in dataclasses.fields(StrategyParams)}
    books = []
    for bk in port["books"]:
        entries = []
        for e in bk["entries"]:
            f = e["tracker"].__dict__
            sp = StrategyParams(**{k: v for k, v in f["params"].__dict__.items() if k in fields})
            tr = PositionTracker(0, 0, bk["symbol"], f["flow_name"], sp, PositionType.LONG if f["is_long"] else PositionType.SHORT,
                                 initial_capital=lb["initial"], ledger=led)
            for name in _STATE_ATTRS:
                if name in f:
                    setattr(tr, name, f[name])
            tr.position, tr.orders = _real(f.get("position")), _real(f.get("orders") or [])
            entries.append({"strategy": e["strategy"], "side": e["side"], "tracker": tr})
        books.append({"symbol": bk["symbol"], "entries": entries})
    pb = PaperBook.__new__(PaperBook)
    pb.__setstate__({"symbols": bag.symbols, "ledger": led, "risk": dict(port["risk"]), "trade_start": port["trade_start"], "books": books,
                     **{n: list(port[n]) for n in ("last_close", "last_low", "last_high", "last_open")}, "peak_mtm": port["peak_mtm"],
                     "halted_at": port["halted_at"], "last_t": port["last_t"], "trades": [dict(t) for t in port["trades"]],
                     "rejected_for_risk": port["rejected_for_risk"]})
    return pb


def _old_paperbook(bot):
    """Đường CŨ (PaperBook còn tới T10). event: pickle.load thật; tracker: dựng từ trường phẳng (xem _old_tracker_book). Chuẩn hoá: xem docstring."""
    bag = sm.load_old(_pkl(bot))
    if sm.kind(bag) == "tracker":
        return _old_tracker_book(bag)
    pb = sm.load_state(_pkl(bot))
    led = pb.ledger
    if not hasattr(led, "peak"):
        led.peak = max(led.initial, led.equity)
    pb.venue.post_only = False
    pb.venue.rounds_qty = False
    for sl in pb.venue._slots.values():
        sl.intrabar_path = "ohlc"
        sl.pts = ()
        sl.tick_i = 0
    return pb


def _feed(bot, n=N_BARS, drift=0.0, p_match=0.08):
    """Nến + tín hiệu + funding giả tất định, bắt đầu sau last_t của pickle (thứ tự slot theo state_migrate.old_slots)."""
    old = sm.load_old(_pkl(bot))
    port = sm._port(old)
    syms = [bk["symbol"] for bk in port["books"]]
    per_book = [[e["strategy"] for e in bk["entries"]] for bk in port["books"]]
    rng = random.Random(7_000 + BOTS.index(bot))
    px = [float(port["last_close"][b]) for b in range(len(syms))]
    t = int(port["last_t"])
    out = []
    for i in range(n):
        t += STEP_MS
        bars, sig, fund = {}, {}, {}
        for b, sym in enumerate(syms):
            o = px[b]
            c = o * (1.0 + drift + rng.gauss(0.0, 0.006))
            h = max(o, c) * (1.0 + abs(rng.gauss(0.0, 0.003)))
            l = min(o, c) * (1.0 - abs(rng.gauss(0.0, 0.003)))
            bars[sym] = (o, h, l, c)
            px[b] = c
            sig[sym] = [{"match": rng.random() < p_match, "stop": rng.random() < 0.02, "vol": rng.uniform(0.3, 1.2), "dca": rng.random() < 0.9}
                        for _ in per_book[b]]
            fund[sym] = [(t - 1, rng.choice([-1, 1]) * 0.0001)] if i % 32 == 0 else []
        out.append((t, bars, sig, fund))
    return out


def _state(pb):
    mtm, worst = pb.mtm()
    led = pb.ledger
    return {"mtm": mtm, "worst": worst, "positions": pb.positions(), "equity": float(led.equity), "reserved": float(led.reserved), "peak": float(led.peak),
            "peak_mtm": float(pb.peak_mtm), "halted_at": pb.halted_at, "rejected_for_risk": int(pb.rejected_for_risk), "last_t": pb.last_t,
            "last_close": [float(x) for x in pb.last_close], "n_trades": len(pb.trades), "last_trades": list(pb.trades[-5:])}


def _run(pb, feed):
    closed = []
    for t, bars, sig, fund in feed:
        closed.append(pb.step_bar(t, bars, sig, fund))
    return closed, _state(pb)


def _migrated(bot):
    return sm.kernel_book_from_old(sm.load_old(_pkl(bot)), "15m")


def _run_old(bot):
    return _run(_old_paperbook(bot), _feed(bot))


def _frozen_path(bot):
    return os.path.join(EXPECTED, f"{bot}.json")


@pytest.mark.parametrize("bot", BOTS)
def test_migrated_state_equals_old_before_stepping(bot):
    old = _old_paperbook(bot)
    kb = _migrated(bot)
    assert _hx(_state(kb)) == _hx(_state(old))
    assert kb.trades == list(old.trades)


@pytest.mark.parametrize("bot", BOTS)
def test_migrated_matches_old_path(bot):
    old_closed, old_state = _run_old(bot)
    kb = _migrated(bot)
    new_closed, new_state = _run(kb, _feed(bot))
    assert _hx(new_closed) == _hx(old_closed)
    assert _hx(new_state) == _hx(old_state)
    if os.environ.get("NORA_REGEN_P94B"):
        os.makedirs(EXPECTED, exist_ok=True)
        json.dump({"closed": _hx(old_closed), "state": _hx(old_state), "bars": N_BARS}, open(_frozen_path(bot), "w"), indent=0)


@pytest.mark.parametrize("bot", BOTS)
def test_migrated_matches_frozen_output(bot):
    """Sống sau T10: KernelBook đã chuyển == kết quả đường cũ đã đóng băng."""
    path = _frozen_path(bot)
    if not os.path.isfile(path):
        pytest.skip("chưa có fixture đóng băng (NORA_REGEN_P94B=1 pytest test_state_migrate.py)")
    exp = json.load(open(path))
    if exp["bars"] != N_BARS:
        pytest.skip("N_BARS khác lúc đóng băng")
    kb = _migrated(bot)
    closed, state = _run(kb, _feed(bot))
    assert json.loads(json.dumps(_hx(closed))) == exp["closed"]
    assert json.loads(json.dumps(_hx(state))) == exp["state"]


@pytest.mark.parametrize("bot", ["okx_paper", "okx_demo_unified"])
def test_save_load_midway_is_neutral(bot, tmp_path):
    feed = _feed(bot)
    ref = _migrated(bot)
    ref_closed, ref_state = _run(ref, feed)
    kb = _migrated(bot)
    half = len(feed) // 2
    c1, _ = _run(kb, feed[:half])
    sm.save_kernel_book(kb, str(tmp_path))
    kb2 = sm.load_kernel_book(str(tmp_path))
    c2, st = _run(kb2, feed[half:])
    assert _hx(c1 + c2) == _hx(ref_closed)
    assert _hx(st) == _hx(ref_state)


def test_load_paper_state_reads_both_formats(tmp_path, monkeypatch):
    """routes/live.py (bot_trades / bot_compare) đọc sổ paper qua MỘT hàm `load_paper_state`: paper.json + paper_state.npz (KernelPaperBook) hoặc paper.pkl cũ
    (PaperBook định dạng event qua StateUnpickler); không có file nào -> OSError."""
    import shutil
    from backend.routes import live as live_router
    feed = _feed("okx_demo_unified")
    kb = _migrated("okx_demo_unified")
    _run(kb, feed)
    assert kb.trades, "fixture phải có lệnh đóng để so khớp"
    dirs = {}
    for fmt in ("new", "old"):
        monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / fmt))
        d = Path(live_dir("okx", "demo"))
        d.mkdir(parents=True)
        (d / "state.json").write_text("{}", encoding="utf-8")
        dirs[fmt] = d
    sm.save_kernel_book(kb, str(dirs["new"]))
    shutil.copy(_pkl("okx_demo_unified"), dirs["old"] / "paper.pkl")
    new = sm.load_paper_state(str(dirs["new"]))
    assert isinstance(new, KernelPaperBook) and _hx(list(new.trades)) == _hx(list(kb.trades)) and _hx(new.positions()) == _hx(kb.positions())
    old = sm.load_paper_state(str(dirs["old"]))
    ref = sm.load_state(_pkl("okx_demo_unified"))
    assert type(old) is PaperBook and _hx(list(old.trades)) == _hx(list(ref.trades)) and _hx(old.positions()) == _hx(ref.positions())
    with pytest.raises(OSError):
        sm.load_paper_state(str(tmp_path / "none"))
    for fmt, pb in (("new", new), ("old", old)):                      # API: cùng một đường đọc cho cả hai định dạng
        monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / fmt))
        r = live_router.bot_trades(mode="demo", venue="okx", limit=2000, book="main", engine=None)
        assert _hx(r["paper"]["trades"]) == _hx(list(pb.trades)) and _hx(r["paper"]["positions"]) == _hx(pb.positions())
        assert r["engine"] == "unified" and r["dir"] == "live/testnet/okx_main"
        (dirs[fmt] / "events.jsonl").write_text("", encoding="utf-8")          # engine=unified -> /compare dùng đường sự kiện (như /compare_events)
        c = live_router.bot_compare(mode="demo", venue="okx", book="main", engine=None)
        assert c["venue"] == "okx" and c["mode"] == "demo" and c["engine"] == "unified" and c["dir"] == "live/testnet/okx_main" and "n_exec" in c
        assert c == live_router.bot_compare_events(mode="demo", venue="okx", book="main", engine=None)


def test_covered_by_fixtures():
    """Các pickle thật có vị thế mở / lệnh đóng / từ chối rủi ro (nếu không, so sánh trên là rỗng)."""
    opens = sum(len(_state(_migrated(b))["positions"]) for b in BOTS)
    assert opens >= 5
    n_closed = sum(len(c) for b in BOTS for c in _run_old(b)[0])
    assert n_closed >= 3


# ── an toàn / tham số ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_restricted_unpickler_rejects_foreign_globals(tmp_path):
    import subprocess
    for payload in (pickle.dumps(os.getcwd), pickle.dumps(subprocess.Popen), pickle.dumps(eval)):
        p = tmp_path / "evil.pkl"
        p.write_bytes(payload)
        with pytest.raises(pickle.UnpicklingError):
            sm.load_old(str(p))


def test_restricted_unpickler_does_not_import_old_engine():
    import sys
    old = sm.load_old(_pkl("okx_paper"))
    assert isinstance(old, sm._Bag) and type(old).__name__ == "PaperBook" and type(old) is not PaperBook
    tr = sm._port(old)["books"][0]["entries"][0]["tracker"]
    assert isinstance(tr, sm._Bag) and type(tr).__name__ == "PositionTracker" and "base_sl" in sm.old_slots(old)[0][4]
    # chạy trong tiến trình con sạch: nạp pickle (cả hai định dạng) không nạp lại module cũ nào (các module trong OLD_MODULES đã xoá) vào sys.modules
    import subprocess
    code = ("import sys; from backend.live import live as sm\n"
            f"sm.load_old({_pkl('okx_paper')!r}); sm.load_old({_pkl('okx_demo_unified')!r})\n"
            "bad = [m for m in sm.OLD_MODULES if m in sys.modules]\n"
            "assert not bad, bad")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert r.returncode == 0, r.stderr[-800:]


def test_params_mismatch_is_rejected():
    old = sm.load_old(_pkl("okx_paper"))
    fresh = _migrated("okx_paper")
    sm.check_params(old, fresh)                                   # cùng tham số: qua
    fresh.P[0, 0] += 1e-4                                         # đổi phí taker của slot 0
    with pytest.raises(sm.ParamsMismatch):
        sm.check_params(old, fresh)
    other = _migrated("okx_paper")
    other.risk = dict(other.risk)
    other.cfg_f[2] = 0.5                                          # kill switch khác
    with pytest.raises(sm.ParamsMismatch):
        sm.check_params(old, other)


def test_read_summary_matches_old_positions():
    for bot in BOTS:
        s = sm.read_summary(_pkl(bot))
        old = _old_paperbook(bot)
        assert [p["symbol"] + p["strategy"] for p in s["positions"]] == [p["symbol"] + p["strategy"] for p in old.positions()]
        assert s["trades"] == list(old.trades)
        for a, b in zip(s["positions"], old.positions()):
            assert a["unrealized"] == pytest.approx(b["unrealized"], rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("bot", ["okx_paper", "okx_demo_unified"])
def test_migrated_kill_switch_matches_old(bot):
    """Thị trường sập (long-only nên thua) -> kill switch danh mục: đường cũ và KernelBook đã chuyển dừng cùng nến, cùng lệnh Kill switch."""
    feed = _feed(bot, 120, drift=-0.012, p_match=0.5)
    old, kb = _old_paperbook(bot), _migrated(bot)
    old.risk["kill_switch_dd_pct"] = 1.5                      # hạ ngưỡng ở CẢ HAI phía để chắc chắn kích hoạt (cfg_f[2] = tỉ lệ)
    kb.cfg_f[2] = 0.015
    old_closed, old_state = _run(old, feed)
    new_closed, new_state = _run(kb, feed)
    assert _hx(new_closed) == _hx(old_closed) and _hx(new_state) == _hx(old_state)
    assert old_state["halted_at"] is not None
    assert any("Kill switch" in x["reason"] for c in old_closed for x in c)
