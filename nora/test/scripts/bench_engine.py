"""Đo tốc độ engine backtest danh mục trên dữ liệu thật: profile phân rã thời gian + so sánh engine cũ (Python, đóng băng) và kernel.

Một alpha thật (mặc định breakout_4h_long, tham số mặc định) chạy trên 8 tài sản perp, cửa sổ dev1 của phễu, dữ liệu mmap dùng chung.

  backend/utils/ops/run_limited.sh -- test/scripts/bench_engine.py profile            # Bước 0: phân rã thời gian + hot-spot (engine cũ)
  backend/utils/ops/run_limited.sh -- test/scripts/bench_engine.py compare --n 3 --batch 100   # cũ vs kernel (+ kiểm bằng nhau từng bit)
  Tuỳ chọn chung: --strategy breakout_4h_long  --symbols BTC,ETH,...  --shared-dir DIR  --keep-shared

Engine cũ = test/reference_engine.py (bản chụp đóng băng của vòng lặp Python); engine mới = PortfolioEngine (kernel numba).
"""
import os
for _e in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_e, "1")

import argparse
import cProfile
import contextlib
import io
import pstats
import random
import resource
import shutil
import sys
import time

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (NORA_ROOT, os.path.join(NORA_ROOT, "test")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DAY = 86_400_000
WARMUP_DAYS = 20


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def build_setup(strategy_id, symbols, shared_dir, params=None):
    """-> (symbols, windows, start, strategy dict, shared_dir)."""
    from backend.core.strategy import book as sb
    from backend.optimize.funnel.gates import compute_windows
    syms = [f"{s}@perp" for s in symbols] if symbols else sb.perp_symbols()
    w = compute_windows(syms)
    cand = {c["id"]: c for c in sb.CANDIDATES}[strategy_id]
    p = dict(sb.schema_defaults(cand)) if params is None else dict(params)
    st = sb.materialize(cand, p, stop_fill="level", risk_per_trade_pct=sb.BASE_RISK_PER_TRADE_PCT)
    return syms, w, st


def make_engine(cls, syms, w, st, shared_dir, position=None, kill=False):
    from backend.core.backtest.portfolio import RiskConfig
    from backend.core.strategy import book as sb
    risk = {**sb.RISK, "kill_switch_dd_pct": sb.RISK["kill_switch_dd_pct"] if kill else 0}
    if position:
        st = {**st, "position": {**st["position"], **position}}
    return cls(syms, [st], w["start"] - WARMUP_DAYS * DAY, w["dev1_end"], trade_start_ts=w["start"],
               risk=RiskConfig.from_dict(risk), shared_dir=shared_dir)


def export_shared(syms, w, st, shared_dir):
    from backend.core.data import shared as shared_data
    from backend.core.backtest.portfolio import PortfolioEngine
    eng = make_engine(PortfolioEngine, syms, w, st, shared_dir)
    t0 = time.perf_counter()
    info = shared_data.export(eng, shared_dir)
    return time.perf_counter() - t0, info


def _fmt(sec):
    return f"{sec:8.3f} s"


def cmd_profile(a):
    """Phân rã thời gian của MỘT alpha trên engine cũ: nạp/xuất dữ liệu, tín hiệu, vòng lặp chính, lấy mẫu vốn, số đo."""
    from backend.core.data import shared as shared_data
    from backend.core.metrics.portfolio import portfolio_metrics
    from backend.core.data import quality_gate
    from backend.core.signals import evaluator
    import reference_engine as ref

    syms, w, st = build_setup(a.strategy, a.symbols, a.shared_dir)
    t_exp, info = export_shared(syms, w, st, a.shared_dir)
    print(f"[export] dữ liệu mmap dùng chung: {_fmt(t_exp)}  ({info['bytes'] / 1e6:.0f} MB, ghi {len(info['written'])} / bỏ qua {len(info['skipped'])} tài sản)")

    acc = {"signal": 0.0, "mmap_load": 0.0, "gate": 0.0}

    def timed(obj, name, key):
        orig = getattr(obj, name)

        def wrapper(*args, **kw):
            t = time.perf_counter()
            try:
                return orig(*args, **kw)
            finally:
                acc[key] += time.perf_counter() - t
        setattr(obj, name, wrapper)
        return lambda: setattr(obj, name, orig)

    undo = [timed(evaluator.VectorEvaluator, "tree", "signal"), timed(shared_data, "load", "mmap_load"),
            timed(quality_gate, "require_data_ok", "gate")]
    eng = make_engine(ref.RefPortfolioEngine, syms, w, st, a.shared_dir)
    t0 = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        eng.load_data()
    t_load = time.perf_counter() - t0
    for u in undo:
        u()

    prof = cProfile.Profile()
    t0 = time.perf_counter()
    prof.enable()
    eng.run()
    prof.disable()
    t_run_prof = time.perf_counter() - t0

    eng2 = make_engine(ref.RefPortfolioEngine, syms, w, st, a.shared_dir)
    with contextlib.redirect_stdout(io.StringIO()):
        eng2.load_data()
    t0 = time.perf_counter()
    eng2.run()
    t_run = time.perf_counter() - t0

    t0 = time.perf_counter()
    res = eng.get_results()
    t_res = time.perf_counter() - t0
    t0 = time.perf_counter()
    portfolio_metrics(res, w["start"])
    t_met = time.perf_counter() - t0

    stats = pstats.Stats(prof)
    cum = {}
    for (_fn, _line, name), (_cc, _nc, _tt, ct, _callers) in stats.stats.items():
        if name in ("_sample", "_mtm", "_gross_notional", "on_bar", "_intrabar", "_skip_idle", "apply_funding", "_collect", "_open_counts"):
            cum[name] = cum.get(name, 0.0) + ct
    total_alpha = t_load + t_run + t_res + t_met
    print(f"\n=== Một alpha {a.strategy} · {len(syms)} perp · dev1 {w['start']} .. {w['dev1_end']} ===")
    print(f"  bars/symbol ~ {len(eng.books[0]['data']['t']):,}")
    print(f"  load_data (cổng dữ liệu + mmap + dựng tracker + tín hiệu): {_fmt(t_load)}")
    print(f"      · cổng chất lượng dữ liệu (cache)   : {_fmt(acc['gate'])}")
    print(f"      · mmap load (np.load ×cột)          : {_fmt(acc['mmap_load'])}")
    print(f"      · tín hiệu VectorEvaluator.tree     : {_fmt(acc['signal'])}")
    print(f"  vòng lặp chính run() (không profiler)    : {_fmt(t_run)}   (có cProfile: {t_run_prof:.2f} s)")
    for name in ("on_bar", "_intrabar", "_gross_notional", "_open_counts", "apply_funding", "_mtm", "_sample", "_skip_idle", "_collect"):
        if name in cum:
            print(f"      · cum {name:<16} (profiler) : {cum[name]:8.3f} s")
    print(f"  get_results                               : {_fmt(t_res)}")
    print(f"  portfolio_metrics                         : {_fmt(t_met)}")
    print(f"  TỔNG 1 alpha (đã có dữ liệu mmap)         : {_fmt(total_alpha)}")
    print(f"  số lệnh {len(res['positions'])}, mẫu vốn {len(res['equity_curve'])}, RSS đỉnh {rss_mb():.0f} MB")
    print("\n--- top hot-spot theo tottime (run) ---")
    s = io.StringIO()
    pstats.Stats(prof, stream=s).sort_stats("tottime").print_stats(14)
    print("\n".join(l for l in s.getvalue().splitlines() if l.strip())[:3500])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("profile", "compare"):
        sp = sub.add_parser(name)
        sp.add_argument("--strategy", default="breakout_4h_long")
        sp.add_argument("--symbols", type=lambda s: [x for x in s.split(",") if x], default=None, help="vd BTC,ETH (mặc định 8 perp của sổ)")
        sp.add_argument("--shared-dir", default=os.path.join(NORA_ROOT, "data", "_cache", "bench_shared"))
        sp.add_argument("--keep-shared", action="store_true")
        if name == "compare":
            sp.add_argument("--n", type=int, default=3, help="số lần lặp mỗi phép đo (lấy nhỏ nhất)")
            sp.add_argument("--batch", type=int, default=100, help="số cấu hình vị thế trong lô")
            sp.add_argument("--old-batch", type=int, default=3, help="số cấu hình chạy engine cũ để đối chiếu/đo")
            sp.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    try:
        {"profile": cmd_profile, "compare": cmd_compare}[a.cmd](a)
    finally:
        if not a.keep_shared:
            shutil.rmtree(a.shared_dir, ignore_errors=True)


def _status_mem():
    """RssAnon (riêng của tiến trình) và RssFile (trang file mmap — chia sẻ giữa worker qua page cache), MB."""
    out = {}
    with open("/proc/self/status", encoding="ascii") as fh:
        for line in fh:
            if line.startswith(("RssAnon", "RssFile", "VmHWM")):
                k, v = line.split(":")
                out[k] = int(v.split()[0]) / 1024.0
    return out


def _rand_override(rng):
    """Bộ tham số vị thế/thoát lệnh hợp lý cho breakout (không đổi tín hiệu / cột ATR)."""
    return {"stop_loss_rate": round(rng.uniform(1.0, 4.0), 2), "take_profit_rate": rng.choice([0.0, round(rng.uniform(1.0, 4.0), 2)]),
            "trailing_stop": round(rng.uniform(1.0, 5.0), 2), "trailing_activation_pct": rng.choice([0.0, 1.0, 2.0]),
            "timeout": rng.choice([0, 1440, 4320, 10080]), "cooldown": rng.choice([0, 60, 240]),
            "risk_per_trade_pct": round(rng.uniform(0.2, 1.0), 2), "leverage": rng.choice([5, 10]),
            "stop_fill": rng.choice(["level", "extreme"])}


def cmd_compare(a):
    """Engine cũ (Python, đóng băng) vs kernel: 1 alpha, lô nhiều cấu hình dùng chung tín hiệu, kiểm bằng nhau từng bit, RAM, ngoại suy."""
    import contextlib
    from backend.core.backtest import kernel as _kernel_io
    from backend.core.backtest.portfolio import PortfolioEngine
    from backend.core.metrics.portfolio import portfolio_metrics
    import golden_scenarios as gs
    import reference_engine as ref

    syms, w, st = build_setup(a.strategy, a.symbols, a.shared_dir)
    t_exp, info = export_shared(syms, w, st, a.shared_dir)
    print(f"[export] dữ liệu mmap dùng chung: {_fmt(t_exp)} ({info['bytes'] / 1e6:.0f} MB)")
    rng = random.Random(a.seed)
    overrides = [{}] + [_rand_override(rng) for _ in range(max(a.batch, a.old_batch) - 1)]

    def load(cls, ov):
        eng = make_engine(cls, syms, w, st, a.shared_dir, position=ov or None)
        with contextlib.redirect_stdout(io.StringIO()):
            eng.load_data()
        return eng

    # warm-up (biên dịch numba lần đầu + đọc page cache); không tính vào số đo
    t0 = time.perf_counter()
    e0 = load(PortfolioEngine, None)
    _kernel_io.run_portfolio(e0)
    print(f"[warm-up] lần đầu (numba nạp/biên dịch + page cache): {_fmt(time.perf_counter() - t0)}")

    # ── engine cũ: --old-batch cấu hình (mỗi cái ~20+ s) ──
    old_res, old_t = [], []
    for ov in overrides[:a.old_batch]:
        eng = load(ref.RefPortfolioEngine, ov)
        t0 = time.perf_counter()
        eng.run()
        res = eng.get_results()
        old_t.append(time.perf_counter() - t0)
        old_res.append(res)
        print(f"[cũ] cấu hình {len(old_t)}/{a.old_batch}: run {old_t[-1]:.2f} s, {len(res['positions'])} lệnh")

    # ── kernel, 1 alpha: tách load_data / kernel / get_results / metrics ──
    best = None
    for _ in range(a.n):
        t0 = time.perf_counter()
        eng = load(PortfolioEngine, None)
        t_load = time.perf_counter() - t0
        t0 = time.perf_counter()
        _kernel_io.run_portfolio(eng)
        t_run = time.perf_counter() - t0
        t0 = time.perf_counter()
        res = eng.get_results()
        t_res = time.perf_counter() - t0
        t0 = time.perf_counter()
        portfolio_metrics(res, w["start"])
        t_met = time.perf_counter() - t0
        cur = (t_load + t_run + t_res + t_met, t_load, t_run, t_res, t_met)
        best = cur if best is None or cur[0] < best[0] else best
    print(f"[kernel · 1 alpha] tổng {best[0]:.3f} s = load_data(mmap+tín hiệu) {best[1]:.3f} + kernel+dựng đối tượng {best[2]:.3f} + get_results {best[3]:.3f} + metrics {best[4]:.3f}")

    # ── kiểm bằng nhau từng bit: kernel vs engine cũ ──
    ok = True
    for ov, r_old in zip(overrides[:a.old_batch], old_res):
        eng = load(PortfolioEngine, ov)
        _kernel_io.run_portfolio(eng)
        same = gs.canonicalize(r_old) == gs.canonicalize(eng.get_results())
        ok &= same
    print(f"[bit-identical] kernel == engine cũ trên {a.old_batch} cấu hình thật: {'ĐÚNG' if ok else 'SAI !!!'}")

    # ── lô: dữ liệu + tín hiệu nạp/tính MỘT lần, B cấu hình vị thế ──
    base = load(PortfolioEngine, None)
    t_batch = None
    for _ in range(max(1, a.n - 1)):
        t0 = time.perf_counter()
        results = _kernel_io.run_many(base, overrides[:a.batch])
        dt = time.perf_counter() - t0
        t_batch = dt if t_batch is None else min(t_batch, dt)
    per_batch = t_batch / a.batch
    t0 = time.perf_counter()
    for r in results[:20]:
        pass
    print(f"[kernel · lô {a.batch}] {t_batch:.2f} s tổng = {per_batch * 1000:.0f} ms/alpha (gồm dựng tracker + kernel + dựng đối tượng + get_results; chưa gồm metrics)")
    mem = _status_mem()
    print(f"[RAM] RssAnon {mem.get('RssAnon', 0):.0f} MB (riêng worker) + RssFile {mem.get('RssFile', 0):.0f} MB (mmap chia sẻ qua page cache), đỉnh {mem.get('VmHWM', 0):.0f} MB")

    t_old = sum(old_t) / len(old_t)
    print("\n=== Bảng (1 alpha = 8 perp, dev1) ===")
    print(f"  engine cũ (Python)          : {t_old:8.2f} s/alpha  (+ load_data ~0,3 s)")
    print(f"  kernel, từng alpha riêng    : {best[0]:8.3f} s/alpha  (load_data {best[1]:.3f} + kernel {best[2]:.3f})")
    print(f"  kernel, lô {a.batch:<4} chung tín hiệu : {per_batch:8.3f} s/alpha  (+ metrics ~{best[4]:.3f})")
    print(f"  tăng tốc: {t_old / best[0]:.0f}x (riêng) · {t_old / (per_batch + best[4]):.0f}x (lô)")
    workers = 14
    print(f"\n=== Ngoại suy {workers} worker (lý tưởng, không tính điều phối) ===")
    for n in (10_000, 100_000, 500_000):
        print(f"  {n:>7,} alpha: cũ {n * t_old / workers / 3600:7.1f} h · kernel riêng {n * best[0] / workers / 3600:6.2f} h · kernel lô {n * (per_batch + best[4]) / workers / 3600:6.2f} h")


if __name__ == "__main__":
    main()
