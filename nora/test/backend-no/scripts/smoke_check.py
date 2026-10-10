"""Smoke check NHANH cho pipeline backtest Nora: kiểm bất biến + tất định (KHÔNG phải chạy production).

Chạy qua run_limited (nora.slice 12G, xếp hàng):
  ops/run_limited.sh -- test/scripts/smoke_check.py single    --out DIR   # 7 ứng viên strategy_book (SOL@perp) + 8 bot-style (BTC) + DCA probe
  ops/run_limited.sh -- test/scripts/smoke_check.py portfolio --out DIR   # danh mục 8 tài sản perp x 7 ứng viên (+ shared_dir)
  ops/run_limited.sh -- test/scripts/smoke_check.py studio    --out DIR   # WFA + Monte Carlo (hàm pipeline, không HTTP) cho alpha trong registry
  ops/run_limited.sh -- test/scripts/smoke_check.py optcheck  --run DIR1 [--run DIR2]   # kiểm results.json + fold của optimize_alphas

Bất biến mỗi lần chạy: sổ vốn, vị thế, bậc DCA, rủi ro theo SL, trần danh nghĩa/đòn bẩy, trần danh mục.
Tất định: chạy 2 lần, xoá cache giữa hai lần, so canonical (test/golden_scenarios.canonicalize).
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

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for _p in (NORA_ROOT, os.path.join(NORA_ROOT, "test")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from backend.crawl.store import json_default  # noqa: E402

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
    from backend.core.params import materialize
    from backend.core.backtest import PortfolioEngine
    st = materialize(c, first_config(c["space"]))
    t0 = time.time()
    eng = PortfolioEngine([symbol], [st], start, end, trade_start_ts=trade_start)
    quiet(eng.run)
    return eng, eng.get_results(), time.time() - t0, st


def run_bot(strat, symbol, start, end, trade_start, override=None):
    from backend.core.backtest import BacktestEngine
    from backend.core.params import build_params
    pos = {k: v for k, v in strat["default_params"].items() if k != "initial_capital"}
    pos.update(override or {})
    fl = strat["flows"][0]
    name = f"{fl['type']}_{strat['id']}"
    t0 = time.time()
    eng = BacktestEngine(0, 0, symbol, start, end, trade_start_ts=trade_start, initial_capital=10000.0)
    eng.add_strategy_flow(name, build_params(name, fl["ast"], fl["type"], pos, "cex"))
    quiet(eng.load_data)
    quiet(eng.run)
    return eng, eng.get_results(), time.time() - t0, pos


def dca_unit_probe():
    """Thăm dò tất định (không dữ liệu thị trường): giá rơi xuyên mọi bậc DCA -> số tầng đã khớp theo order_size_pct."""
    from backend.core.backtest import PositionTracker
    from backend.core.params import build_params
    from backend.core.models import PositionType
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
    from backend.optimize.book.build import CANDIDATES
    import os as _os
    import sys as _sys
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
    from backend.core.params import RISK, materialize
    from backend.optimize.book.build import CANDIDATES, perp_symbols
    from backend.core.backtest import PortfolioEngine, RiskConfig
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
    from backend.optimize.search import evaluate as shared_data
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
    print("  by_strategy: " + ", ".join(f"{k}:{int(v['trades'])}/{v['pnl_usd']:.0f}" for k, v in sorted(res['by_strategy'].items())), flush=True)
    print("  by_symbol:   " + ", ".join(f"{k}:{int(v['trades'])}/{v['pnl_usd']:.0f}" for k, v in sorted(res['by_symbol'].items())), flush=True)
    print(f"  shared_dir run: {secs3:.1f}s identical-to-first={'PASS' if det3[0] else 'FAIL ' + det3[1]}", flush=True)
    print("  checks: " + json.dumps(check_table(ck)), flush=True)
    write_json(a.out, "portfolio.json", {"summary": s, "stats": stats, "checks": check_table(ck), "det_rerun": det,
                                          "det_shared": det3, "rejected_for_risk": res["rejected_for_risk"],
                                          "halted_at": res["halted_at"], "secs": [round(secs, 1), round(secs3, 1)]})
    shutil_rm(sd)


def shutil_rm(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def write_json(out, name, obj):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, default=json_default)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["single", "portfolio"])
    ap.add_argument("--out", default=os.path.join(NORA_ROOT, "data", "_cache", "smoke"))
    a = ap.parse_args()
    from backend.optimize.process.workers import require_memory_limit
    require_memory_limit("smoke_check")
    {"single": cmd_single, "portfolio": cmd_portfolio}[a.cmd](a)


if __name__ == "__main__":
    main()
