"""Smoke check NHANH cho pipeline backtest Nora: kiểm bất biến + tất định (KHÔNG phải chạy production).

Chạy qua run_limited (nora.slice 12G, xếp hàng):
  scripts/run_limited.sh -- scripts/smoke_check.py single    --out DIR   # 7 ứng viên strategy_book (SOL@perp) + 8 bot-style (BTC) + DCA probe
  scripts/run_limited.sh -- scripts/smoke_check.py portfolio --out DIR   # danh mục 8 tài sản perp x 7 ứng viên (+ shared_dir)
  scripts/run_limited.sh -- scripts/smoke_check.py studio    --out DIR   # WFA + Monte Carlo (hàm pipeline, không HTTP) cho alpha trong registry
  scripts/run_limited.sh -- scripts/smoke_check.py optcheck  --run DIR1 [--run DIR2]   # kiểm results.json + fold của optimize_alphas

Bất biến mỗi lần chạy: sổ vốn, vị thế, bậc DCA, rủi ro theo SL, trần danh nghĩa/đòn bẩy, trần danh mục.
Tất định: chạy 2 lần, xoá cache giữa hai lần, so canonical (tests/golden_scenarios.canonicalize).
"""
import os

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_k, "1")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

import argparse
import contextlib
import io
import json
import sys
import time
from collections import Counter, defaultdict

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (NORA_ROOT, os.path.join(NORA_ROOT, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DAY = 86_400_000
MIN = 60_000
EPS = 1e-9
START, END, WARMUP_D = "2025-04-01", "2025-05-31", 20   # cửa sổ 60 ngày + 20 ngày khởi động
STATUS = {2: "TP", 3: "SL", 4: "CANCEL", 5: "LIQ"}


def ms(date):
    import pandas as pd
    return int(pd.Timestamp(date, tz="UTC").timestamp() * 1000)


def windows():
    return ms(START) - WARMUP_D * DAY, ms(END), ms(START)   # start_ts, end_ts, trade_start_ts


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def clear():
    import golden_scenarios as gs
    gs.clear_caches()


# ─── Bất biến ────────────────────────────────────────────────────────────────

class Checks:
    """Mỗi check: ok + chi tiết (số liệu, vị thế vi phạm đầu tiên)."""

    def __init__(self):
        self.items = {}

    def add(self, name, ok, detail=""):
        old = self.items.get(name)
        if old is None:
            self.items[name] = [bool(ok), detail]
        elif not ok and old[0]:      # giữ vi phạm đầu tiên
            self.items[name] = [False, detail]

    def fails(self):
        return {k: v[1] for k, v in self.items.items() if not v[0]}


def _sweep_max(intervals):
    """Số khoảng mở đồng thời lớn nhất; đóng xử lý TRƯỚC mở khi cùng thời điểm (cận dưới -> không báo oan)."""
    ev = []
    for a, b in intervals:
        if b > a:
            ev += [(a, 1), (b, -1)]
    ev.sort(key=lambda x: (x[0], x[1]))
    cur = best = 0
    for _, d in ev:
        cur += d
        best = max(best, cur)
    return best


def check_invariants(res, initial, cfg_of, risk=None, books=None):
    """res: get_results(); cfg_of(pos)->dict tham số vị thế; risk: RiskConfig (danh mục); books: eng.books để lấy giá mark."""
    ck = Checks()
    pos = res["positions"]
    # 1. Sổ vốn
    diff = initial + sum(p.real_pnl for p in pos) - res["final_equity"]
    ck.add("ledger", abs(diff) < 1e-6, f"initial+sum(pnl)-final = {diff:.3e}")
    by = defaultdict(list)
    for o in res["orders"]:
        by[o.position_id].append(o)
    stats = {"max_risk_ratio": 0.0, "max_risk_ratio_sl_only": 0.0, "max_notional_ratio": 0.0, "max_lev": 0.0,
             "dca_min_step_slack": None}
    for p in pos:
        cfg = cfg_of(p)
        long = p.pos_type.name == "LONG"
        sign = 1.0 if long else -1.0
        tag = f"{p.symbol}/{p.strategy_id or p.flow}@{p.enter_time}"
        ck.add("pos_time", p.close_time is not None and p.close_time >= p.enter_time, f"{tag} close<enter")
        ck.add("pos_layers", p.layers >= 1, f"{tag} layers={p.layers}")
        ck.add("pos_qty", p.qty > 0, f"{tag} qty={p.qty}")
        if p.layers > 1:
            ok = p.avg_price <= p.enter_price * (1 + EPS) if long else p.avg_price >= p.enter_price * (1 - EPS)
            ck.add("pos_avg_vs_enter", ok, f"{tag} avg={p.avg_price} enter={p.enter_price}")
        ods = sorted(by.get(p.result_id, []), key=lambda o: o.phase)
        et = "BUY" if long else "SELL"
        ent = [o for o in ods if o.order_type.name == et]
        ck.add("orders_count", len(ent) == p.layers and len(ods) == p.layers + 1,
               f"{tag} entries={len(ent)} total={len(ods)} layers={p.layers}")
        ck.add("orders_phase", [o.phase for o in ent] == list(range(len(ent))), f"{tag} phases={[o.phase for o in ent]}")
        # 2. Bậc DCA: mỗi tầng thấp hơn (LONG) / cao hơn (SHORT) tầng trước ít nhất một bước cấu hình
        step = float(cfg.get("dca_step_pct") or 0.0)
        if cfg.get("exit_unit") == "atr":
            step *= p.unit_pct
        maxl = int(cfg.get("dca_max_layers") or 0)
        ck.add("dca_layers_cap", p.layers <= maxl + 1, f"{tag} layers={p.layers} > {maxl}+1")
        for k in range(1, len(ent)):
            prev, cur = ent[k - 1].order_price, ent[k].order_price
            need = prev * (1 - sign * step / 100.0)
            ok = (cur <= need * (1 + EPS)) if long else (cur >= need * (1 - EPS))
            ck.add("dca_step", ok, f"{tag} layer{k} fill={cur} prev={prev} need<={need}")
            slack = abs(cur - need) / prev * 100.0
            if stats["dca_min_step_slack"] is None or slack < stats["dca_min_step_slack"]:
                stats["dca_min_step_slack"] = round(slack, 6)
        # 3. Rủi ro theo SL
        notional = sum(o.order_price * o.qty for o in ent)
        if cfg.get("sizing") == "risk":
            rp = float(cfg.get("risk_per_trade_pct") or 0.5)
            if p.real_pnl < 0 and p.entry_equity > 0:
                ratio = -p.real_pnl / (rp / 100.0 * p.entry_equity)
                if p.status.name == "SL":
                    stats["max_risk_ratio"] = max(stats["max_risk_ratio"], ratio)
                    if str(p.close_reason).startswith("Stop-loss"):
                        stats["max_risk_ratio_sl_only"] = max(stats["max_risk_ratio_sl_only"], ratio)
                    ck.add("risk_sl", ratio <= 1.15, f"{tag} loss/risk={ratio:.3f} ({p.close_reason})")
            mx = float(cfg.get("max_notional_pct") or 100.0)
            r = notional / (p.entry_equity * mx / 100.0)
            stats["max_notional_ratio"] = max(stats["max_notional_ratio"], r)
            ck.add("cap_notional", r <= 1 + 1e-6, f"{tag} notional/cap={r:.6f}")
        # 4. Đòn bẩy hiệu dụng
        lev = float(cfg.get("leverage") or 1.0)
        if p.total_margin_usd > 0:
            il = notional / p.total_margin_usd
            stats["max_lev"] = max(stats["max_lev"], il)
            ck.add("cap_leverage", il <= lev * (1 + 1e-6) and p.leverage_used <= lev + 1e-9,
                   f"{tag} implied={il:.4f} used={p.leverage_used} cfg={lev}")
        ck.add("margin_budget", p.total_margin_usd <= p.entry_equity * (1 + 1e-9),
               f"{tag} margin={p.total_margin_usd} entry_equity={p.entry_equity}")
    # 5. Trần danh mục (dựng lại từ sự kiện vào/đóng)
    if risk is not None and pos:
        stats["max_concurrent"] = _sweep_max([(p.enter_time, p.close_time) for p in pos])
        ck.add("cap_max_positions", stats["max_concurrent"] <= risk.max_positions,
               f"concurrent={stats['max_concurrent']} > {risk.max_positions}")
        per = defaultdict(list)
        for p in pos:
            per[p.symbol].append((p.enter_time, p.close_time))
        stats["max_per_symbol"] = max(_sweep_max(v) for v in per.values())
        ck.add("cap_per_symbol", stats["max_per_symbol"] <= risk.max_per_symbol,
               f"per_symbol={stats['max_per_symbol']} > {risk.max_per_symbol}")
        stats.update(_gross_check(ck, pos, risk, books))
    return ck, stats


def _gross_check(ck, pos, risk, books):
    """Σ danh nghĩa các vị thế đang mở (khác vị thế đang xét, vào TRƯỚC) + danh nghĩa mới <= max_gross × vốn lúc vào, dung sai 1%.
    mark = qty × close nến cuối trước lúc vào (đúng cách engine tính, từ eng.books); entry = qty × giá vào (xấp xỉ, thông tin)."""
    import numpy as np
    book = {b["symbol"]: b["data"] for b in (books or [])}

    def mark(p, t):
        d = book.get(p.symbol)
        if d is None:
            return p.qty * p.avg_price
        i = int(np.searchsorted(d["t"], t, side="left")) - 1   # nến cuối có open_time < t
        return p.qty * (float(d["c"][i]) if i >= 0 else p.avg_price)

    best_m = best_e = 0.0
    worst = None
    order = sorted(pos, key=lambda p: p.enter_time)
    for p in order:
        t = p.enter_time
        others = [q for q in order if q is not p and q.enter_time < t < q.close_time]
        own = p.qty * p.enter_price
        gm = (own + sum(mark(q, t) for q in others)) / (risk.max_gross_exposure * p.entry_equity)
        ge = (own + sum(q.qty * q.enter_price for q in others)) / (risk.max_gross_exposure * p.entry_equity)
        if gm > best_m:
            best_m, worst = gm, f"{p.symbol}/{p.strategy_id}@{t}"
        best_e = max(best_e, ge)
    ck.add("cap_gross", best_m <= 1.01, f"gross(mark)/cap={best_m:.4f} at {worst}")
    return {"max_gross_ratio_mark": round(best_m, 4), "max_gross_ratio_entry": round(best_e, 4)}


# ─── Số liệu báo cáo ─────────────────────────────────────────────────────────

def summarize(res, initial):
    pos = res["positions"]
    n = len(pos)
    eq = res["equity_curve"]
    peak, mdd = initial, 0.0
    for r in eq:   # đỉnh theo vốn MTM, đáy xấu nhất trong nến (equity_worst)
        peak = max(peak, r["equity"])
        mdd = max(mdd, (peak - r["equity_worst"]) / peak * 100.0 if peak > 0 else 0.0)
    st = Counter(STATUS.get(int(p.status), str(int(p.status))) for p in pos)
    return {"trades": n, "ret_pct": round((res["final_equity"] / initial - 1) * 100.0, 3), "mdd_pct": round(mdd, 3),
            "win_pct": round(100.0 * sum(p.real_pnl > 0 for p in pos) / n, 1) if n else 0.0, "status": dict(st),
            "layers": dict(sorted(Counter(p.layers for p in pos).items()))}


def canon(res):
    import golden_scenarios as gs
    return gs.canonicalize(res)


def deterministic(first_res, second_res):
    a, b = canon(first_res), canon(second_res)
    if a == b:
        return True, ""
    import golden_scenarios as gs
    return False, "; ".join(gs.diff_canonical(a, b, limit=2))[:300]


def fmt_checks(ck):
    f = ck.fails()
    return "PASS" if not f else "FAIL " + " | ".join(f"{k}: {v}" for k, v in list(f.items())[:3])


def show(label, s, ck, secs, det, extra=""):
    print(f"{label:34s} n={s['trades']:4d} ret={s['ret_pct']:8.2f}% mdd={s['mdd_pct']:6.2f}% win={s['win_pct']:5.1f}% "
          f"{json.dumps(s['status'])} {secs:5.1f}s det={'PASS' if det[0] else 'FAIL ' + det[1]} inv={fmt_checks(ck)} {extra}", flush=True)


def check_table(ck):
    return {k: ("PASS" if v[0] else "FAIL: " + v[1]) for k, v in ck.items.items()}


# ─── single ──────────────────────────────────────────────────────────────────

def first_config(space):
    return {k: space[k][0] for k in sorted(space)}


def run_candidate(c, symbol, start, end, trade_start):
    from backend.alpha.strategy_book import materialize
    from backend.backtest.portfolio import PortfolioEngine
    st = materialize(c, first_config(c["space"]))
    t0 = time.time()
    eng = PortfolioEngine([symbol], [st], start, end, trade_start_ts=trade_start)
    quiet(eng.run)
    return eng, eng.get_results(), time.time() - t0, st


def run_bot(strat, symbol, start, end, trade_start, override=None):
    from backend.backtest.engine import BacktestEngine
    from backend.backtest.params_builder import build_params
    pos = {k: v for k, v in strat["default_params"].items() if k != "initial_capital"}
    pos.update(override or {})
    fl = strat["flows"][0]
    name = f"{fl['type']}_{strat['id']}"
    t0 = time.time()
    eng = BacktestEngine(0, 0, symbol, start, end, trade_start_ts=trade_start, initial_capital=10000.0)
    eng.add_strategy_flow(name, build_params(name, fl["ast"], fl["type"], pos, "cex", symbol=symbol))
    quiet(eng.load_data)
    quiet(eng.run)
    return eng, eng.get_results(), time.time() - t0, pos


def dca_unit_probe():
    """Thăm dò tất định (không dữ liệu thị trường): giá rơi xuyên mọi bậc DCA -> số tầng đã khớp theo order_size_pct."""
    from backend.backtest.execution import PositionTracker
    from backend.backtest.params_builder import build_params
    from backend.db.models import PositionType
    out = {}
    for size in (20.0, 19.0):
        pos = {"market": "spot", "leverage": 1.0, "order_size_pct": size, "dca_step_pct": 0.75, "dca_max_layers": 4,
               "dca_size_multiplier": 1.0, "take_profit_rate": 0.8, "stop_loss_rate": 6.0, "timeout": 4320}
        # build_params giờ TỪ CHỐI cấu hình vượt ngân sách DCA (20%) -> dựng StrategyParams trực tiếp để thăm dò hành vi engine
        p = build_params("LONG_probe", {"match": [], "stop": []}, "LONG", {**pos, "order_size_pct": 19.0}, "cex")
        p.order_size_pct = size
        tr = PositionTracker(0, 0, "X", "LONG_probe", p, PositionType.LONG, 10000.0)
        t = 1_700_000_000_000
        tr.on_bar(t, 100, 100, 100, 100, entry_signal=True, stop_signal=False)             # đặt lệnh chờ
        tr.on_bar(t + MIN, 100, 100, 96.5, 97, entry_signal=False, stop_signal=False)      # mở + giá rơi qua 4 bậc DCA
        out[f"order_size_{int(size)}"] = {"layers_filled": tr.layer_count, "planned": 5, "dca_rejected": tr.dca_rejected,
                                          "margin_used": round(tr.margin_used, 4), "fees": round(tr.fees_paid, 4),
                                          "max_capital": round(tr.max_capital, 4),
                                          "margin+fees": round(tr.margin_used + tr.fees_paid, 4)}
    return out


def cmd_single(a):
    from backend.alpha.strategy_book import CANDIDATES
    from backend.alpha.strategy_library import KERNEL_STRATEGIES
    start, end, ts = windows()
    rows = []
    print(f"== single: cửa sổ {START} -> {END} (+{WARMUP_D}d khởi động)  [cấu hình = khoá sắp xếp, giá trị đầu tiên của mỗi khoá]", flush=True)
    for c in CANDIDATES:
        clear()
        eng, res, secs, st = run_candidate(c, "SOL@perp", start, end, ts)
        ck, stats = check_invariants(res, 10000.0, lambda p, st=st: st["position"])
        s = summarize(res, 10000.0)
        clear()
        _, res2, _, _ = run_candidate(c, "SOL@perp", start, end, ts)
        det = deterministic(res, res2)
        show("cand " + c["id"], s, ck, secs, det, f"riskmax={stats['max_risk_ratio']:.3f}/{stats['max_risk_ratio_sl_only']:.3f} "
             f"notional_max={stats['max_notional_ratio']:.3f} lev_max={stats['max_lev']:.2f}")
        rows.append({"kind": "candidate", "id": c["id"], "config": first_config(c["space"]), "summary": s, "stats": stats,
                     "checks": check_table(ck), "det": det, "secs": round(secs, 1)})
    for strat in KERNEL_STRATEGIES:
        sym = "BTC@perp" if strat["default_params"]["market"] == "perp" else "BTC"
        clear()
        eng, res, secs, pos = run_bot(strat, sym, start, end, ts)
        ck, stats = check_invariants(res, 10000.0, lambda p, pos=pos: pos)
        s = summarize(res, 10000.0)
        clear()
        _, res2, _, _ = run_bot(strat, sym, start, end, ts)
        det = deterministic(res, res2)
        maxl = int(pos.get("dca_max_layers") or 0)
        show("bot  " + strat["id"], s, ck, secs, det, f"layers={s['layers']} cfg_max={maxl + 1 if maxl else 1} "
             f"dca_layers_rejected={res.get('dca_layers_rejected')}")
        row = {"kind": "bot", "id": strat["id"], "symbol": sym, "summary": s, "stats": stats, "checks": check_table(ck),
               "det": det, "secs": round(secs, 1), "cfg_max_layers": maxl + 1 if maxl else 1}
        if maxl:   # DCA: chạy thêm biến thể order_size_pct=19 (5 x 19% = 95% < 100%) để so
            clear()
            _, r19, _, _ = run_bot(strat, sym, start, end, ts, {"order_size_pct": 19.0})
            row["layers_size19"] = summarize(r19, 10000.0)["layers"]
            print(f"     dca probe order_size 19%: layers={row['layers_size19']} (order_size 20%: {s['layers']})", flush=True)
        rows.append(row)
    probe = dca_unit_probe()
    print("DCA unit probe (giá rơi xuyên mọi bậc, bước 0,75%, 4 tầng DCA, spot):", json.dumps(probe), flush=True)
    write_json(a.out, "single.json", {"rows": rows, "dca_unit_probe": probe})
    fails = sum(1 for r in rows if r["checks"] and any(v != "PASS" for v in r["checks"].values()) or not r["det"][0])
    print(f"== single xong: {len(rows)} lần chạy, {fails} có FAIL", flush=True)


# ─── portfolio ───────────────────────────────────────────────────────────────

def mk_portfolio(shared_dir=None):
    from backend.alpha.strategy_book import CANDIDATES, RISK, materialize, perp_symbols
    from backend.backtest.portfolio import PortfolioEngine, RiskConfig
    start, end, ts = windows()
    sts = [materialize(c, first_config(c["space"])) for c in CANDIDATES]
    risk = RiskConfig.from_dict(RISK)
    eng = PortfolioEngine(perp_symbols(), sts, start, end, trade_start_ts=ts, risk=risk, shared_dir=shared_dir)
    return eng, sts, risk


def cmd_portfolio(a):
    start, end, ts = windows()
    clear()
    eng, sts, risk = mk_portfolio()
    t0 = time.time()
    quiet(eng.run)
    secs = time.time() - t0
    res = eng.get_results()
    cfgs = {s["id"]: s["position"] for s in sts}
    ck, stats = check_invariants(res, 10000.0, lambda p: cfgs[p.strategy_id], risk=risk, books=eng.books)
    s = summarize(res, 10000.0)
    clear()
    eng2, _, _ = mk_portfolio()
    quiet(eng2.run)
    det = deterministic(res, eng2.get_results())
    # shared_dir: export mmap rồi chạy lại, phải y hệt
    from backend.backtest import shared_data
    sd = os.path.join(a.out, "_shared")
    clear()
    eng3, _, _ = mk_portfolio(shared_dir=sd)
    quiet(shared_data.export, eng3, sd)
    clear()
    t1 = time.time()
    quiet(eng3.run)
    secs3 = time.time() - t1
    det3 = deterministic(res, eng3.get_results())
    show("portfolio 8 asset x 7 strat", s, ck, secs, det,
         f"rej_risk={res['rejected_for_risk']} rej_cap={res['rejected_for_capital']} halted_at={res['halted_at']} ruined_at={res['ruined_at']}")
    print(f"  stats: {json.dumps(stats)}", flush=True)
    print(f"  by_strategy: " + ", ".join(f"{k}:{int(v['trades'])}/{v['pnl_usd']:.0f}" for k, v in sorted(res['by_strategy'].items())), flush=True)
    print(f"  by_symbol:   " + ", ".join(f"{k}:{int(v['trades'])}/{v['pnl_usd']:.0f}" for k, v in sorted(res['by_symbol'].items())), flush=True)
    print(f"  shared_dir run: {secs3:.1f}s identical-to-first={'PASS' if det3[0] else 'FAIL ' + det3[1]}", flush=True)
    print("  checks: " + json.dumps(check_table(ck)), flush=True)
    write_json(a.out, "portfolio.json", {"summary": s, "stats": stats, "checks": check_table(ck), "det_rerun": det,
                                          "det_shared": det3, "rejected_for_risk": res["rejected_for_risk"],
                                          "halted_at": res["halted_at"], "secs": [round(secs, 1), round(secs3, 1)]})
    shutil_rm(sd)


def shutil_rm(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


# ─── studio (WFA + MC) ───────────────────────────────────────────────────────

def fold_checks(folds, first_test_expected, test_days_ms):
    """Cửa sổ test không chồng lấp, theo thứ tự, test đầu tiên bắt đầu đúng chỗ mong đợi, lệnh OOS nằm trong cửa sổ test."""
    out = {}
    folds = sorted(folds, key=lambda f: f["fold_index"])
    out["first_test_start"] = [folds[0]["test_start_ts"] == first_test_expected,
                               f"{folds[0]['test_start_ts']} vs expected {first_test_expected}"]
    bad = [(f["fold_index"], nx["fold_index"]) for f, nx in zip(folds, folds[1:]) if f["test_end_ts"] > nx["test_start_ts"]]
    out["test_windows_disjoint"] = [not bad, f"overlap {bad}"]
    bad = [f["fold_index"] for f in folds if f["train_end_ts"] > f["test_start_ts"] or f["test_end_ts"] <= f["test_start_ts"]]
    out["train_before_test"] = [not bad, f"folds {bad}"]
    bad = [(f["fold_index"], t["entry_time"]) for f in folds for t in f.get("oos_trades", [])
           if not f["test_start_ts"] <= t["entry_time"] <= f["test_end_ts"]]
    out["oos_trades_in_window"] = [not bad, f"{bad[:3]}"]
    return {k: ("PASS" if v[0] else "FAIL " + v[1]) for k, v in out.items()}


def cmd_studio(a):
    os.makedirs(a.out, exist_ok=True)
    os.environ["NORA_PIPELINE_DB_PATH"] = os.path.join(a.out, "pipeline.db")
    from backend.studio_pipeline.jobs import create_mc_job, create_wfa_job, get_mc_job, get_wfa_job, init_db
    from backend.studio_pipeline.monte_carlo import execute_monte_carlo_pipeline
    from backend.studio_pipeline.schemas import MonteCarloRunRequest, StrategySnapshot, WfaFoldConfig
    from backend.studio_pipeline.wfa import execute_wfa_pipeline
    init_db()
    reg = json.load(open(os.path.join(NORA_ROOT, "alphas", "registry.json"), encoding="utf-8"))
    al = next(x for x in reg["alphas"] if x["alpha_id"] == a.alpha)
    s0, e0 = ms("2025-01-01"), ms("2026-02-01")
    snap = StrategySnapshot(name=al["alpha_id"], symbol=al["symbol"], start_ts=s0, end_ts=e0, flows=al["flows"],
                            signal_params=al["signal_params"], initial_capital=10000.0,
                            param_grid={"stop_loss_rate": [2.5, 4.0], "trailing_stop": [3.0, 5.0]}, **al["position"])
    cfg = WfaFoldConfig(train_days=90, test_days=30, min_folds=3)
    job = create_wfa_job(al["symbol"], al["alpha_id"], 0)
    t0 = time.time()
    quiet(execute_wfa_pipeline, job, snap, cfg, f"smoke_{al['alpha_id']}")
    wj = get_wfa_job(job)
    print(f"WFA status={wj.get('status')} {time.time() - t0:.0f}s error={wj.get('error')}", flush=True)
    if wj.get("status") != "completed":
        return
    r = wj["result"]
    fc = fold_checks(r["folds"], s0 + 90 * DAY, 30 * DAY)
    print(f"  folds={r['total_folds']} positive={r['positive_folds_count']} oos_trades={r['total_oos_trades']} "
          f"oos_return={r['total_oos_return_pct']}% worst_mdd={r['worst_fold_mdd_pct']}% gate={r['acceptance_gate_passed']} "
          f"wfe={r['wfe']} stability={r['param_stability']}", flush=True)
    print("  gate_checks: " + ", ".join(f"{k}={'PASS' if v['passed'] else 'FAIL'}({v['actual']})" for k, v in r["gate_checks"].items()), flush=True)
    print("  fold checks: " + json.dumps(fc), flush=True)
    for f in r["folds"]:
        print(f"   fold{f['fold_index']:2d} {f['status']:8s} test {f['test_start_date']}..{f['test_end_date']} IS={f['is_return_pct']:7.2f}%/{f['is_trades_count']:3d} "
              f"OOS={f['oos_return_pct']:7.2f}%/{f['oos_trades_count']:3d} mdd={f['oos_max_drawdown_pct']:5.2f} {f['chosen_params'].get('stop_loss_rate')}/{f['chosen_params'].get('trailing_stop')}", flush=True)
    outs = []
    for i in (1, 2):
        mj = create_mc_job(al["symbol"], al["alpha_id"], 2000, source_wfa_id=job)
        req = MonteCarloRunRequest(source_wfa_id=job, simulations=2000, block_size=5, seed=7, symbol=al["symbol"],
                                   strategy_name=al["alpha_id"])
        execute_monte_carlo_pipeline(mj, req, [])
        m = get_mc_job(mj)
        if m.get("status") != "completed":
            print(f"MC run{i} status={m.get('status')} error={m.get('error')}", flush=True)
            return
        outs.append({k: v for k, v in m["result"].items() if k not in ("mc_id", "generated_at")})
    same = outs[0] == outs[1]
    m = outs[0]
    print(f"MC trades={m['trades_count']} percentile_mdd={m['percentile_mdd']} risk_of_ruin={m['risk_of_ruin_pct']}% "
          f"terminal={m['terminal_return_pct']} source_gate={m['source_gate_passed']} robust={m['robust_passed']} "
          f"identical-twice={'PASS' if same else 'FAIL'}", flush=True)
    write_json(a.out, "studio.json", {"wfa": {k: v for k, v in r.items() if k not in ("aggregate_oos_trades", "aggregate_oos_equity")},
                                       "fold_checks": fc, "mc": m, "mc_identical": same})


# ─── optcheck: kiểm kết quả scripts/optimize_alphas.py ──────────────────────

STRIP = ("seconds", "peak_rss_mb")


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in STRIP}
    if isinstance(o, list):
        return [_strip(x) for x in o]
    return o


def cmd_optcheck(a):
    import sqlite3
    sys.path.insert(0, os.path.join(NORA_ROOT, "scripts"))
    import optimize_alphas as oa
    from backend.alpha.strategy_library import OPTIMIZATION_SPACES
    from backend.backtest.params_builder import data_symbol
    from backend.db.local_pkl import read_manifest
    loaded = []
    for d in a.run:
        res = json.load(open(os.path.join(d, "results.json"), encoding="utf-8"))
        res = sorted(res, key=lambda r: (r["space"], r["symbol"]))
        print(f"== {d}", flush=True)
        db = sqlite3.connect(os.path.join(d, "pipeline.db"))
        folds_by = {}
        for jid, sym, name, rj in db.execute("SELECT job_id, symbol, strategy_name, result_json FROM wfa_jobs WHERE status='completed'"):
            folds_by[(name, sym)] = json.loads(rj)
        for r in res:
            wf, mc, h, sc = r.get("wfa") or {}, r.get("mc") or {}, r.get("holdout") or {}, r.get("screen") or {}
            line = (f"{r['space']}/{r['symbol']:4s} verdict={r['verdict']:16s} screen={sc.get('passed')}/{r.get('configs_tried')} "
                    f"wfa folds={wf.get('total_folds')} pos={wf.get('positive_folds_count')} oos_trades={wf.get('total_oos_trades')} "
                    f"gate={wf.get('acceptance_gate_passed')} {json.dumps(wf.get('gate_checks'))} "
                    f"mc ruin={mc.get('risk_of_ruin_pct')} mdd_p95={mc.get('mdd_p95')} "
                    f"holdout ret={h.get('return_pct')} mdd={h.get('mdd_pct')} n={h.get('trades')} rss={r.get('peak_rss_mb')}MB {r.get('seconds')}s")
            print(line, flush=True)
            wr = folds_by.get((r["space"], r["symbol"]))
            if wr:
                sd = next(s for s in OPTIMIZATION_SPACES if s["id"] == r["space"])
                dsym, _ = data_symbol(r["symbol"], sd["fixed"].get("market", "spot"))
                w = oa.windows(read_manifest(dsym), sd["venue"])
                fc = fold_checks(wr["folds"], w["dev1_end"], 30 * DAY)
                last_end = max(f["test_end_ts"] for f in wr["folds"])
                fc["last_test_end<=holdout"] = "PASS" if last_end <= w["holdout"] else f"FAIL {last_end} > {w['holdout']}"
                print("   fold checks: " + json.dumps(fc), flush=True)
        loaded.append(_strip(res))
    if len(loaded) >= 2:
        same = loaded[0] == loaded[1]
        print(f"results.json identical (except seconds/peak_rss_mb): {'PASS' if same else 'FAIL'}", flush=True)
        if not same:
            for x, y in zip(loaded[0], loaded[1]):
                if x != y:
                    ks = [k for k in x if x.get(k) != y.get(k)]
                    print(f"   differs {x['space']}/{x['symbol']} keys={ks}", flush=True)


def write_json(out, name, obj):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, default=str)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["single", "portfolio", "studio", "optcheck"])
    ap.add_argument("--out", default=os.path.join(NORA_ROOT, "data", "_cache", "smoke"))
    ap.add_argument("--alpha", default="trend_long_perp__SOL")
    ap.add_argument("--run", action="append", default=[])
    a = ap.parse_args()
    from backend.utils.memwatch import require_memory_limit
    if a.cmd != "optcheck":
        require_memory_limit("smoke_check")
    {"single": cmd_single, "portfolio": cmd_portfolio, "studio": cmd_studio, "optcheck": cmd_optcheck}[a.cmd](a)


if __name__ == "__main__":
    main()
