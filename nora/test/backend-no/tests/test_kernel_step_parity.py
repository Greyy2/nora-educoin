"""P9.4b T3: CÙNG kernel bước TỪNG NẾN / TỪNG KHÚC (KernelBook, SlotDriver) phải BIT-IDENTICAL với kernel chạy cả lô và với đường paper cũ.

(a) batch == step: PortfolioEngine(close_at_end=False).run() rồi cùng dữ liệu + tín hiệu + funding phát lại vào KernelBook — từng nến một, khúc
    ngẫu nhiên qua step_bars (có save/load npz+json giữa các khúc), cả hai (kill switch BẬT — ffwd tắt — và kill switch TẮT): so từng bit (float.hex)
    mọi PositionModel đã đóng (mọi trường), lệnh (thứ tự + liên kết vị thế + id tương đối), sổ vốn, rejected_for_risk, risk_blocked_attempts,
    dca_layers_rejected, skipped_no_vol, halted_at, ruined_at, đường vốn, vị thế còn mở (+ lệnh của chúng), last_close.
(b) tam giác: KernelBook == PaperBook(event) == PaperBook(tracker) cùng nguồn nến (live/paper.py).
(c) SlotDriver.on_bar == PositionTracker.on_bar trên các cấu hình tầng 4a–4g của test_event_path_parity (từng nến: toàn bộ trạng thái + sổ vốn,
    vị thế đóng, vị thế / lệnh còn mở, funding, kill, đóng cuối).
(d) hợp đồng: save/load (không pickle), chặn nến lùi, vết admission, sự kiện, nén bộ đệm không đổi kết quả.
Lệch -> sửa kernel / KernelBook, KHÔNG nới so sánh. Số cấu hình: NORA_STEP_CONFIGS (a, mặc định 24), NORA_STEP_TRI (b, 8), NORA_SLOT_CONFIGS (c mỗi tầng, 12)."""
import json
import os
import random

import numpy as np
import pytest

import golden_scenarios as gs
from backend.core import backtest as bt
from backend.core.backtest import KernelBook, PaperBook, PortfolioEngine, SlotDriver, PositionTracker
from backend.core.models import Account, PositionType, next_id
from backend.live.live import load_kernel_book, save_kernel_book
from test_event_path_parity import STAGES, _ATTRS, _canon, _hx, _make_config, _snap
from test_kernel_parity import hexify, market_root, rand_portfolio_config  # noqa: F401  (market_root là fixture)
from test_risk_engine import _risk_cfg
from test_runner_parity import _feed, _risk_dict, _same_bar_close_open, _state

N_CONFIGS = int(os.environ.get("NORA_STEP_CONFIGS", "24"))
N_TRI = int(os.environ.get("NORA_STEP_TRI", "8"))
N_SLOT = int(os.environ.get("NORA_SLOT_CONFIGS", "12"))
N_CHUNKS = 4
_COV = {"ran": 0, "kill_on": 0, "kill_off": 0, "halted": 0, "dca": 0, "risk_block": 0, "risk_attempts": 0, "same_bar_close_open": 0,
        "open_at_end": 0, "ruined": 0, "chunks_saved": 0, "tri": 0, "tri_halted": 0, "tri_dca": 0, "slot_closed": 0, "slot_configs": 0}
_REASONS: dict = {}


def _configs(chunk, market_root_):
    per = N_CONFIGS // N_CHUNKS + (1 if chunk < N_CONFIGS % N_CHUNKS else 0)
    for j in range(per):
        seed = 900_000 + chunk * 10_000 + j
        # chẵn: đủ trần rủi ro + kill switch bật; lẻ: bộ sinh danh mục gốc (kill switch bật/tắt ngẫu nhiên)
        cfg = _risk_cfg(seed, market_root_) if j % 2 == 0 else {**rand_portfolio_config(seed, market_root_), "close_at_end": False}
        yield seed, cfg


def _batch(cfg):
    pe = PortfolioEngine(cfg["symbols"], cfg["strategies"], cfg["start"], cfg["end"], trade_start_ts=cfg["trade_start"],
                         initial_capital=cfg["capital"], risk=cfg["risk"], close_at_end=False)
    pe.run()
    return pe


def _kb(pe, cfg, **kw):
    return KernelBook(cfg["strategies"], pe.symbols, "1m", pe.initial_capital, _risk_dict(cfg["risk"]), trade_start=cfg["trade_start"],
                      record_full=True, **kw)


def _rel(orders):
    base = min((o.order_id for o in orders), default=0)
    return [o.order_id - base for o in orders]


def _canon_batch(res_positions, res_orders, open_trackers):
    """PositionModel đóng + lệnh (id tương đối, liên kết vị thế theo chỉ số) + vị thế / lệnh còn mở của từng slot."""
    pos_index = {p.result_id: i for i, p in enumerate(res_positions)}
    return {"positions": [hexify(p) for p in res_positions],
            "orders": [{**hexify(o), "pos": pos_index.get(o.position_id, "?")} for o in res_orders], "order_ids": _rel(res_orders),
            "open": [(hexify(tr.position), [hexify(o) for o in tr.orders]) for tr in open_trackers]}


def _scalars(pe_or_kb, curve, books=()):
    if isinstance(pe_or_kb, PortfolioEngine):
        e = pe_or_kb
        led = (e.ledger.equity, e.ledger.reserved, e.ledger.peak, e.ledger.rejected)
        r = {"rejected_for_risk": e.rejected_for_risk, "risk_blocked_attempts": e.risk_blocked_attempts, "halted_at": e.halted_at,
             "ruined_at": e.ruined_at, "skipped_no_vol": sum(x["tracker"].skipped_no_vol for b in e.books for x in b["entries"]),
             "dca_layers_rejected": sum(x["tracker"].dca_rejected for b in e.books for x in b["entries"]),
             "last_close": [e.last_close[bk["symbol"]] for bk in e.books]}
    else:
        k = pe_or_kb
        led = (k.ledger.equity, k.ledger.reserved, k.ledger.peak, k.ledger.rejected)
        r = {"rejected_for_risk": k.rejected_for_risk, "risk_blocked_attempts": k.risk_blocked_attempts, "halted_at": k.halted_at,
             "ruined_at": k.ruined_at, "skipped_no_vol": k.skipped_no_vol, "dca_layers_rejected": k.dca_layers_rejected,
             "last_close": [x for s, x in zip(k.symbols, k.last_close) if s in books]}
    return hexify({**r, "ledger": led, "curve": curve})


def _compare(label, pe, kb):
    kb_pos, kb_orders = kb.full_objects()
    a = {**_canon_batch(pe.closed_positions, pe.orders, [x["tracker"] for b in pe.books for x in b["entries"]]), **_scalars(pe, pe.equity_curve)}
    b = {**_canon_batch(kb_pos, kb_orders, kb.full_views), **_scalars(kb, kb.equity_curve(), {bk["symbol"] for bk in pe.books})}
    for key in a:
        if a[key] != b[key]:
            if isinstance(a[key], list) and isinstance(b[key], list):
                assert len(a[key]) == len(b[key]), f"{label}: {key} khác độ dài batch={len(a[key])} step={len(b[key])}"
                for i, (x, y) in enumerate(zip(a[key], b[key])):
                    if x != y:
                        diff = {q: (x[q], y.get(q)) for q in x if x[q] != y.get(q)} if isinstance(x, dict) else (x, y)
                        pytest.fail(f"{label}: {key}[{i}] khác: {diff}")
            pytest.fail(f"{label}: {key} khác: batch={a[key]!r} step={b[key]!r}")
    # vị thế còn mở: bảng của PortfolioEngine.open_positions() vs KernelBook.positions()
    op = {(x["symbol"], x["strategy"]): x for x in pe.open_positions()}
    for x in kb.positions():
        y = op.get((x["symbol"], x["strategy"]))
        assert y is not None and hexify((y["qty"], y["entry_price"], y["unrealized_pnl"], y["opened"])) == hexify(
            (x["qty"], x["avg"], x["unrealized"], x["entry_time"])), f"{label}: positions() khác open_positions()"
    assert len(op) == len(kb.positions()), f"{label}: số vị thế mở"


def _tally(pe, kb):
    _COV["ran"] += 1
    kill = bool(pe.risk.kill_switch_dd_pct)
    _COV["kill_on" if kill else "kill_off"] += 1
    _COV["halted"] += pe.halted_at is not None
    _COV["dca"] += any(p.layers > 1 for p in pe.closed_positions)
    _COV["risk_block"] += bool(pe.rejected_for_risk)
    _COV["risk_attempts"] += bool(pe.risk_blocked_attempts)
    _COV["same_bar_close_open"] += _same_bar_close_open(kb.trades)
    _COV["open_at_end"] += bool(kb.positions())
    _COV["ruined"] += pe.ruined_at is not None


def _chunks(feed, rng):
    i = 0
    while i < len(feed):
        n = rng.choice([1, 2, 7, 64, 300, 1500])
        yield feed[i:i + n]
        i += n


@pytest.mark.parametrize("chunk", range(N_CHUNKS))
def test_step_equals_batch(market_root, chunk, tmp_path):
    ran = skipped = per = 0
    with gs.data_root_env(market_root):
        for seed, cfg in _configs(chunk, market_root):
            per += 1
            try:
                pe = _batch(cfg)
            except ValueError:
                skipped += 1
                continue
            label = f"step-parity seed={seed}"
            feed = list(_feed(pe))
            # 1) từng nến một
            one = _kb(pe, cfg)
            for t, bars, sig, fund in feed:
                one.step_bar(t, bars, sig, fund)
            _compare(label + " [1 nến/lần]", pe, one)
            # 2) khúc ngẫu nhiên + save/load npz+json giữa các khúc (kb nạp lại không còn tracker -> so bằng trạng thái số: xem dưới)
            rng = random.Random(seed)
            two = _kb(pe, cfg)
            for part in _chunks(feed, rng):
                two.step_bars(part)
            _compare(label + " [khúc]", pe, two)
            three = KernelBook(cfg["strategies"], pe.symbols, "1m", pe.initial_capital, _risk_dict(cfg["risk"]), trade_start=cfg["trade_start"])
            d = str(tmp_path / f"s{seed}")
            for part in _chunks(feed, rng):
                three.step_bars(part)
                save_kernel_book(three, d)
                three = load_kernel_book(d, cls=KernelBook)
                _COV["chunks_saved"] += 1
            assert hexify(three.trades) == hexify(one.trades) and one.trades is not None, f"{label}: trades save/load != 1 nến/lần"
            for name in ("P", "PI", "F", "I", "LG", "PS", "PSI", "LPX"):
                a, b = getattr(one, name), getattr(three, name)
                if name == "I":                                   # I_POS là chỉ số hàng vị thế: bị đánh số lại khi nén
                    a, b = np.delete(a, bt.I_POS, axis=1), np.delete(b, bt.I_POS, axis=1)
                assert a.tobytes() == b.tobytes(), f"{label}: mảng {name} sau save/load khác"
            assert hexify(three.equity_curve()) == hexify(one.equity_curve()), f"{label}: đường vốn sau save/load"
            assert hexify(three.positions()) == hexify(one.positions()) and three.halted_at == one.halted_at
            assert three.rejected_for_risk == one.rejected_for_risk and three.risk_blocked_attempts == one.risk_blocked_attempts
            assert hexify(three.mtm()) == hexify(one.mtm()) and three.last_t == one.last_t
            assert hexify(three.peak_mtm) == hexify(one.peak_mtm)
            _tally(pe, one)
            ran += 1
    assert ran >= per * 0.5, f"quá nhiều cấu hình bị bỏ ({skipped}/{per})"


# ── (b) tam giác ──────────────────────────────────────────────────────────────
def _kb_state(kb):
    a = kb.ledger
    return hexify({"trades": kb.trades, "account": [a.initial, a.equity, a.reserved, a.peak, a.rejected, a.usage],
                   "rejected_for_risk": kb.rejected_for_risk, "halted_at": kb.halted_at, "last_t": kb.last_t, "positions": kb.positions(),
                   "mtm": list(kb.mtm()), "peak_mtm": kb.peak_mtm, "last_close": kb.last_close, "last_low": kb.last_low,
                   "last_high": kb.last_high, "last_open": kb.last_open})


def test_kernel_book_equals_paper_book_both_engines(market_root):
    ran = 0
    with gs.data_root_env(market_root):
        for j in range(N_TRI * 3):
            if ran >= N_TRI:
                break
            seed = 950_000 + j
            cfg = _risk_cfg(seed, market_root)
            try:
                pe = _batch(cfg)
            except ValueError:
                continue
            risk = _risk_dict(cfg["risk"])
            feed = list(_feed(pe))
            kb = KernelBook(cfg["strategies"], pe.symbols, "1m", pe.initial_capital, risk, trade_start=cfg["trade_start"])
            ev = PaperBook(cfg["strategies"], pe.symbols, "1m", pe.initial_capital, risk, trade_start=cfg["trade_start"])
            tk = PaperBook(cfg["strategies"], pe.symbols, "1m", pe.initial_capital, risk, trade_start=cfg["trade_start"], engine="tracker")
            for t, bars, sig, fund in feed:
                a = kb.step_bar(t, bars, sig, fund)
                b = ev.step_bar(t, bars, sig, fund)
                c = tk.step_bar(t, bars, sig, fund)
                assert hexify(a) == hexify(b) == hexify(c), f"seed={seed} t={t}: lệnh đóng ở nến này"
            sk, se, st = _kb_state(kb), _state(ev), _state(tk)
            for key in sk:
                assert sk[key] == se[key] == st[key], f"seed={seed}: {key} kernel != event != tracker"
            _COV["tri"] += 1
            _COV["tri_halted"] += kb.halted_at is not None
            _COV["tri_dca"] += any(x["layers"] > 1 for x in kb.trades)
            ran += 1
    assert ran >= max(1, N_TRI // 2)


# ── (c) SlotDriver == PositionTracker ──────────────────────────────────────────
def _run_world_slot(cfg):
    base = next_id()
    acct = Account(cfg["initial"])
    trackers = [PositionTracker(k, 7, f"S{k}", "f", params, PositionType.LONG if side == "LONG" else PositionType.SHORT,
                                initial_capital=cfg["initial"], ledger=acct) for k, (side, params) in enumerate(cfg["slots"])]
    drv = SlotDriver(trackers, meta=[(tr.symbol, "") for tr in trackers])
    acct, actors = drv.ledger, [drv[k] for k in range(len(trackers))]
    trace, closed = [], []
    n_slots = len(actors)
    for i in range(cfg["nbars"]):
        for k, a in enumerate(actors):
            t, o, h, l, c = cfg["bars"][k][i]
            s = cfg["steps"][i][k]
            if i in cfg["funding"]:
                trace.append(("funding", k, i, _hx(a.apply_funding(cfg["funding"][i], o, t))))
            a.max_new_notional, a.max_new_risk, a.risk_scale = s["caps"]
            pos = a.on_bar(t, o, h, l, c, entry_signal=s["entry"], stop_signal=s["stop"], can_open=s["can_open"], vol=s["vol"], dca_gate=s["dca_gate"])
            a.max_new_notional = a.max_new_risk = float("inf")
            a.risk_scale = 1.0
            if pos is not None:
                closed.append((k, i, pos))
            trace.append((k, i, _snap(a, acct), _canon(pos, base) if pos is not None else None,
                          _hx(a.unrealized_pnl_usd(c)) if a.is_open else None))
        if cfg["kill_at"] == i:
            for k, a in enumerate(actors):
                a.pending_entry = False
                pos = a.force_close(cfg["bars"][k][i][0], cfg["bars"][k][i][4], "Kill switch danh mục")
                if pos is not None:
                    closed.append((k, i, pos))
                trace.append(("kill", k, i, _snap(a, acct), _canon(pos, base) if pos is not None else None))
    last = cfg["nbars"] - 1
    if cfg["close_at_end"]:
        for k, a in enumerate(actors[: max(1, n_slots - 1)]):
            pos = a.force_close(cfg["bars"][k][last][0], cfg["bars"][k][last][4])
            if pos is not None:
                closed.append((k, last, pos))
            trace.append(("end", k, _snap(a, acct), _canon(pos, base) if pos is not None else None))
    final = [{"orders": [_canon(o, base) for o in a.orders], "position": _canon(a.position, base) if a.position is not None else None,
              "state": _snap(a, acct)} for a in actors]
    return {"trace": trace, "final": final, "closed": closed}


@pytest.mark.parametrize("stage", list(STAGES))
def test_slot_driver_matches_tracker(stage):
    from test_event_path_parity import _first_diff, _run_world
    from collections import Counter
    n = STAGES.index(stage)
    ran = tries = 0
    first_seed = 700_000 + n * 100_000
    while ran < N_SLOT:
        seed = first_seed + tries
        tries += 1
        assert tries < N_SLOT * 3, "quá nhiều cấu hình bị build_params từ chối"
        try:
            cfg = _make_config(seed, n)
        except ValueError:
            continue
        oracle = _run_world("oracle", cfg, Counter())
        slot = _run_world_slot(cfg)
        label = f"slot-driver stage 4{stage} seed={seed}"
        assert oracle["trace"] == slot["trace"], f"{label}: {_first_diff(oracle['trace'], slot['trace'])}"
        assert oracle["final"] == slot["final"], f"{label}: final khác"
        _COV["slot_closed"] += len(oracle["closed"])
        for _, _, pos in oracle["closed"]:
            _REASONS[pos.close_reason] = _REASONS.get(pos.close_reason, 0) + 1
        _COV["slot_configs"] += 1
        ran += 1


# ── (d) hợp đồng ──────────────────────────────────────────────────────────────
def _small_book(market_root, seed=960_001, **kw):
    cfg = _risk_cfg(seed, market_root)
    pe = _batch(cfg)
    kb = KernelBook(cfg["strategies"], pe.symbols, "1m", pe.initial_capital, _risk_dict(cfg["risk"]), trade_start=cfg["trade_start"], **kw)
    return cfg, pe, kb, list(_feed(pe))


def test_save_load_files_and_validation(market_root, tmp_path):
    with gs.data_root_env(market_root):
        cfg, pe, kb, feed = _small_book(market_root)
        kb.step_bars(feed[:3000])
        save_kernel_book(kb, str(tmp_path))
        assert sorted(os.listdir(tmp_path)) == ["paper.json", "paper_state.npz"]
        meta = json.load(open(tmp_path / "paper.json", encoding="utf-8"))
        assert meta["schema"] == bt.KB_SCHEMA and meta["symbols"] == pe.symbols
        assert [s["strategy"] for s in meta["slots"]] == [s["strategy"] for s in kb.slots] and meta["params_hash"] == kb.params_hash()
        assert len(np.load(tmp_path / "paper_state.npz", allow_pickle=False)["F"]) == kb.nt           # không pickle lớp
        load_kernel_book(str(tmp_path), strategies=cfg["strategies"], cls=KernelBook)                                   # băm khớp
        other = [{**cfg["strategies"][0], "position": {**cfg["strategies"][0]["position"], "leverage": 3.7}}] + cfg["strategies"][1:]
        with pytest.raises(ValueError):
            load_kernel_book(str(tmp_path), strategies=other, cls=KernelBook)
        meta["params_hash"] = "0" * 64
        json.dump(meta, open(tmp_path / "paper.json", "w", encoding="utf-8"))
        with pytest.raises(ValueError):
            load_kernel_book(str(tmp_path), cls=KernelBook)
        meta["schema"] = 99
        json.dump(meta, open(tmp_path / "paper.json", "w", encoding="utf-8"))
        with pytest.raises(ValueError):
            load_kernel_book(str(tmp_path), cls=KernelBook)


def test_time_must_increase_and_compaction_is_transparent(market_root):
    with gs.data_root_env(market_root):
        cfg, pe, a, feed = _small_book(market_root)
        b = KernelBook(cfg["strategies"], pe.symbols, "1m", pe.initial_capital, _risk_dict(cfg["risk"]), trade_start=cfg["trade_start"])
        b._alloc_buffers(8, 16, 8)                            # bộ đệm bé nhất: ép nén + nới liên tục
        feed = feed[:20000]
        for t, bars, sig, fund in feed:
            a.step_bar(t, bars, sig, fund)
            b.step_bar(t, bars, sig, fund)
        assert hexify(a.trades) == hexify(b.trades) and a.trades, "nén / nới bộ đệm đổi kết quả"
        assert a.G[bt.G_NPOS] > b.G[bt.G_NPOS] or b.outF.shape[0] < a.G[bt.G_NPOS], "bộ đệm không được nén"
        assert hexify(a.equity_curve()) == hexify(b.equity_curve()) and hexify(a.mtm()) == hexify(b.mtm())
        with pytest.raises(ValueError):
            b.step_bar(*feed[10])


def test_events_and_admission_trace(market_root):
    with gs.data_root_env(market_root):
        cfg, pe, kb, feed = _small_book(market_root, adm_capacity=4)
        kb.step_bars(feed)
        ev = kb.drain_events()
        assert kb.drain_events() == []
        kinds = {e["kind"] for e in ev}
        assert {"entry", "dca"} & kinds and kinds & {"sl", "tp", "trail", "exit", "timeout", "liq", "kill"}, kinds
        fills = [e for e in ev if e["kind"] != "reject"]
        exits = [e for e in fills if e["kind"] not in ("entry", "dca")]
        assert len(exits) == len(kb.trades) and [e["t"] for e in exits] == sorted(e["t"] for e in exits)
        assert sum(e["n"] for e in ev if e["kind"] == "reject" and e["reason"] == "risk") == kb.rejected_for_risk
        # vết admission: tràn thì bỏ bản ghi, G_NADM vẫn đếm đủ, không bao giờ G_OVF; kết quả không đổi so với tắt vết
        assert kb.G[bt.G_OVF] == 0 and kb.G[bt.G_NADM] > 4 and len(kb.adm) == 4
        _, _, plain, _ = _small_book(market_root)
        plain.step_bars(feed)
        assert hexify(plain.trades) == hexify(kb.trades) and plain.G[bt.G_NADM] == 0
        big = KernelBook(cfg["strategies"], pe.symbols, "1m", pe.initial_capital, _risk_dict(cfg["risk"]), trade_start=cfg["trade_start"],
                         adm_capacity=int(kb.G[bt.G_NADM]) + 10)
        big.step_bars(feed)
        adm = big.adm
        assert len(adm) == kb.G[bt.G_NADM] and (adm[:, bt.AD_CAN] <= 1).all() and (np.diff(adm[:, bt.AD_T]) >= 0).all()
        assert (adm[:, bt.AD_K] < big.nt).all() and (adm[:, bt.AD_EQ] > 0).any()
        blocked = int((adm[:, bt.AD_CAN] == 0).sum())
        assert blocked == big.rejected_for_risk, "số lần chặn trong vết != rejected_for_risk"


def test_close_all_and_batch_adm(market_root):
    with gs.data_root_env(market_root):
        cfg, pe, kb, feed = _small_book(market_root)
        kb.step_bars(feed[:6000])
        n_open = len(kb.positions())
        before = len(kb.trades)
        closed = kb.close_all(feed[5999][0], col=0)
        assert len(closed) == n_open and len(kb.trades) == before + n_open and not kb.positions()
        assert all(x["reason"] == "End of Backtest" for x in closed)
        # PortfolioEngine với vết admission bật: cùng kết quả, vết có dữ liệu
        eng = PortfolioEngine(cfg["symbols"], cfg["strategies"], cfg["start"], cfg["end"], trade_start_ts=cfg["trade_start"],
                              initial_capital=cfg["capital"], risk=cfg["risk"], close_at_end=False)
        eng.adm_capacity = 100000
        eng.run()
        assert hexify(eng.get_results()["positions"]) == hexify(pe.get_results()["positions"]) and eng.adm.shape[1] == bt.NAD


def test_zz_step_parity_coverage():
    if _COV["ran"] < N_CONFIGS * 0.5 or N_CONFIGS < 12:
        pytest.skip("chưa chạy đủ bộ parity")
    print(f"\n[step-parity] {_COV} reasons={_REASONS}")
    for key in ("kill_on", "kill_off", "halted", "dca", "risk_block", "risk_attempts", "same_bar_close_open", "open_at_end", "chunks_saved"):
        assert _COV[key] > 0, (key, _COV)
    if _COV["tri"]:
        assert _COV["tri_halted"] > 0 and _COV["tri_dca"] > 0, _COV
    if _COV["slot_configs"] >= 7 * N_SLOT:
        assert _COV["slot_closed"] > 0
        for r in ("Stop-loss (từ giá TB)", "Take-profit (từ giá TB)", "Trailing stop", "Thanh lý (perp)", "Hết thời gian giữ lệnh", "Tín hiệu thoát (AST stop)"):
            assert _REASONS.get(r), (r, _REASONS)
