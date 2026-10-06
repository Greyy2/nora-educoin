"""P6.5: Runner + PaperBook trên đường SỰ KIỆN (SimVenue + PositionManager) phải BIT-IDENTICAL với đường tracker cũ (PaperBook(engine="tracker"))
và khớp kernel (PortfolioEngine).

(a) Cùng dữ liệu + tín hiệu + funding phát lại từng nến vào hai PaperBook (event / tracker) trên cấu hình danh mục ngẫu nhiên (đa tài sản, đa
    chiến lược, đủ trần rủi ro / kill switch, cùng bộ sinh với test_kernel_parity / test_risk_engine): so từng bit lệnh đóng, sổ vốn (equity,
    reserved, peak, rejected), rejected_for_risk, halted_at, positions(), mtm(), last_close, peak_mtm; đường event còn so với kernel.
(b) Phủ: có nến vừa đóng vừa mở lệnh (khác slot), kill switch, bị trần rủi ro chặn, DCA nhiều tầng (không "xanh rỗng").
(c) Pickle: PaperBook event pickle giữa chừng rồi chạy tiếp == chạy liền; pickle định dạng CŨ (không có `runner`) nạp lại thành engine="tracker" và chạy tiếp
    bit-identical.
Số cấu hình đổi bằng NORA_RUNNER_CONFIGS (mặc định 40). Lệch -> sửa Runner/manager, KHÔNG nới so sánh."""
import os
import pickle
import random

import pytest

import golden_scenarios as gs
from backend.core.backtest.portfolio import PortfolioEngine
from backend.live.paper import PaperBook
from test_kernel_parity import hexify, market_root, rand_portfolio_config  # noqa: F401  (market_root là fixture)
from test_risk_engine import _pos_key, _risk_cfg, _trade_key

N_CONFIGS = int(os.environ.get("NORA_RUNNER_CONFIGS", "40"))
N_CHUNKS = 4
_COV = {"ran": 0, "rejected": 0, "halted": 0, "dca": 0, "same_bar_close_open": 0, "skipped": 0, "kernel": 0}


def _feed(pe):
    """Từng nến của PortfolioEngine đã chạy -> (t, bars, sig, funding) như bot cấp cho PaperBook."""
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
        yield t, bars, sig, fund


def _run(pb, pe, limit=None):
    for k, (t, bars, sig, fund) in enumerate(_feed(pe)):
        if limit is not None and k >= limit:
            break
        pb.step_bar(t, bars, sig, fund)
    return pb


def _state(pb):
    a = pb.ledger
    return hexify({"trades": pb.trades, "account": [a.initial, a.equity, a.reserved, a.peak, a.rejected, a.usage],
                   "rejected_for_risk": pb.rejected_for_risk, "halted_at": pb.halted_at, "last_t": pb.last_t,
                   "positions": pb.positions(), "mtm": list(pb.mtm()), "peak_mtm": pb.peak_mtm,
                   "last_close": pb.last_close, "last_low": pb.last_low, "last_high": pb.last_high, "last_open": pb.last_open})


def _same_bar_close_open(trades):
    """Có nến mà một slot đóng lệnh còn slot khác mở lệnh (vốn / chỗ vừa nhả được dùng ngay trong nến)."""
    enters = {x["enter_time"] for x in trades}
    return any(x["close_time"] in enters for x in trades if x["reason"] != "Kill switch danh mục")


def _risk_dict(r):
    return {"max_positions": r.max_positions, "max_per_symbol": r.max_per_symbol, "max_gross_exposure": r.max_gross_exposure,
            "kill_switch_dd_pct": r.kill_switch_dd_pct, "max_open_risk_pct": r.max_open_risk_pct, "dd_throttle_pct": r.dd_throttle_pct,
            "dd_throttle_floor": r.dd_throttle_floor}


def _configs(chunk, market_root_):
    per = N_CONFIGS // N_CHUNKS + (1 if chunk < N_CONFIGS % N_CHUNKS else 0)
    for j in range(per):
        seed = 800_000 + chunk * 10_000 + j
        # chẵn: đủ trần rủi ro (kill switch nhạy); lẻ: bộ sinh danh mục gốc (kill switch / trần có thể tắt)
        cfg = _risk_cfg(seed, market_root_) if j % 2 == 0 else {**rand_portfolio_config(seed, market_root_), "close_at_end": False}
        yield seed, cfg


@pytest.mark.parametrize("chunk", range(N_CHUNKS))
def test_event_paper_book_equals_tracker_and_kernel(market_root, chunk):
    ran = skipped = 0
    per = 0
    with gs.data_root_env(market_root):
        for seed, cfg in _configs(chunk, market_root):
            per += 1
            pe = PortfolioEngine(cfg["symbols"], cfg["strategies"], cfg["start"], cfg["end"], trade_start_ts=cfg["trade_start"],
                                 initial_capital=cfg["capital"], risk=cfg["risk"], close_at_end=False)
            try:
                pe.run()
            except ValueError:
                skipped += 1
                continue
            res = pe.get_results()
            label = f"runner-parity seed={seed}"
            risk = _risk_dict(cfg["risk"])
            syms = pe.symbols
            ev = _run(PaperBook(cfg["strategies"], syms, "1m", pe.initial_capital, risk, trade_start=cfg["trade_start"]), pe)
            tk = _run(PaperBook(cfg["strategies"], syms, "1m", pe.initial_capital, risk, trade_start=cfg["trade_start"], engine="tracker"), pe)
            assert ev.engine == "event" and tk.engine == "tracker" and ev.venue is not None and tk.venue is None
            se, st = _state(ev), _state(tk)
            for k in st:
                assert se[k] == st[k], f"{label}: {k} event != tracker"
            if not res.get("ruined_at"):                                  # cháy tài khoản: kernel dừng, PaperBook không mô hình hoá
                want = sorted(_pos_key(p) for p in res["positions"])
                got = sorted(_trade_key(x) for x in ev.trades)
                assert got == want, f"{label}: event != kernel"
                assert ev.rejected_for_risk == res["rejected_for_risk"] and ev.halted_at == res.get("halted_at"), f"{label}: risk vs kernel"
                _COV["kernel"] += 1
            _COV["ran"] += 1
            _COV["rejected"] += bool(ev.rejected_for_risk)
            _COV["halted"] += ev.halted_at is not None
            _COV["dca"] += any(x["layers"] > 1 for x in ev.trades)
            _COV["same_bar_close_open"] += _same_bar_close_open(ev.trades)
            ran += 1
    _COV["skipped"] += skipped
    assert ran >= per * 0.5, f"quá nhiều cấu hình bị bỏ ({skipped}/{per})"


def _spec_book(market_root_, seed=800_001):
    cfg = _risk_cfg(seed, market_root_)
    pe = PortfolioEngine(cfg["symbols"], cfg["strategies"], cfg["start"], cfg["end"], trade_start_ts=cfg["trade_start"],
                         initial_capital=cfg["capital"], risk=cfg["risk"], close_at_end=False)
    pe.run()
    mk = lambda engine="event": PaperBook(cfg["strategies"], pe.symbols, "1m", pe.initial_capital, _risk_dict(cfg["risk"]),  # noqa: E731
                                          trade_start=cfg["trade_start"], engine=engine)
    return pe, mk


def test_pickle_roundtrip_midrun_continues_identically(market_root):
    with gs.data_root_env(market_root):
        pe, mk = _spec_book(market_root)
        feed = list(_feed(pe))
        cut = len(feed) // 2
        whole = mk()
        for t, bars, sig, fund in feed:
            whole.step_bar(t, bars, sig, fund)
        half = mk()
        for t, bars, sig, fund in feed[:cut]:
            half.step_bar(t, bars, sig, fund)
        half = pickle.loads(pickle.dumps(half))
        assert half.engine == "event" and half.runner.collect is not None and half.books[0]["entries"][0]["tracker"].venue is half.venue
        for t, bars, sig, fund in feed[cut:]:
            half.step_bar(t, bars, sig, fund)
        assert _state(half) == _state(whole)


def test_old_format_pickle_is_adopted_as_tracker_engine(market_root):
    """PaperBook của code CŨ (thuộc tính phẳng: books/ledger/trades/..., không có `runner`) nạp lại -> engine="tracker", chạy tiếp bit-identical."""
    with gs.data_root_env(market_root):
        pe, mk = _spec_book(market_root)
        feed = list(_feed(pe))
        cut = len(feed) // 2
        whole = mk("tracker")
        for t, bars, sig, fund in feed:
            whole.step_bar(t, bars, sig, fund)
        part = mk("tracker")
        for t, bars, sig, fund in feed[:cut]:
            part.step_bar(t, bars, sig, fund)
        old = PaperBook.__new__(PaperBook)                      # dựng đúng bố cục __dict__ của lớp cũ
        old.__dict__.update(symbols=part.symbols, ledger=part.ledger, risk=part.risk, trade_start=part.trade_start, books=part.books,
                            last_close=part.last_close, last_low=part.last_low, last_high=part.last_high, last_open=part.last_open,
                            peak_mtm=part.peak_mtm, halted_at=part.halted_at, last_t=part.last_t, trades=part.trades,
                            rejected_for_risk=part.rejected_for_risk)
        assert "runner" not in old.__dict__
        loaded = pickle.loads(pickle.dumps(old))
        assert loaded.engine == "tracker" and loaded.venue is None and loaded.ledger is loaded.books[0]["entries"][0]["tracker"].ledger
        for t, bars, sig, fund in feed[cut:]:
            loaded.step_bar(t, bars, sig, fund)
        assert _state(loaded) == _state(whole)


def test_engine_validation_and_slot_ids(market_root):
    with gs.data_root_env(market_root):
        pe, mk = _spec_book(market_root)
        with pytest.raises(ValueError):
            PaperBook([], [], "1m", 1000.0, {}, engine="nope")
        pb = mk()
        slots = [e["tracker"].slot for bk in pb.books for e in bk["entries"]]
        assert slots == list(range(len(slots))) and len({id(e["tracker"].venue) for bk in pb.books for e in bk["entries"]}) == 1
        assert all(e["tracker"].ledger is pb.ledger for bk in pb.books for e in bk["entries"])


def test_zz_runner_parity_coverage():
    if _COV["ran"] < N_CONFIGS * 0.5 or N_CONFIGS < 20:
        pytest.skip("chưa chạy đủ bộ parity")
    print(f"\n[runner-parity] {_COV}")
    assert _COV["rejected"] > 0 and _COV["halted"] > 0 and _COV["dca"] > 0, _COV
    assert _COV["same_bar_close_open"] > 0, _COV
