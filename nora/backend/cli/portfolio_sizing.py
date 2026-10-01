"""Ghép danh mục từ một alpha (tham số cố định) trên nhiều tài sản và tính mức vốn/đòn bẩy tối đa
theo ngân sách rủi ro đã chốt: P(MDD >= 30% trong 1 năm) <= 5%.

- Chạy engine thật trên các giai đoạn NGOÀI MẪU của tham số (mặc định: WFA-test + holdout của lần tối ưu),
  chỉ chiều của alpha, vốn chia đều giữa các tài sản, đường vốn MTM theo giờ, gồm funding.
- Báo cả hai cách khớp SL: "level" (cận trên) và "extreme" (bi quan, cận dưới).
- Bootstrap khối 5 ngày trên lợi suất ngày của danh mục -> lãi trung vị, MDD p95, P(MDD >= 30%) theo hệ số vốn.

Dùng: PYTHONPATH=. python -m backend.cli.portfolio_sizing --alpha trend_long_perp__SOL --assets SOL,DOGE
"""
import argparse
import json
import os
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)

MDD_LIMIT = 0.30
RUIN_MAX_PCT = 5.0
SCALES = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0)


def _run(args):
    """Một tài sản / một giai đoạn với flow của alpha (AST đã thay tham số trong kho)."""
    import contextlib
    import io
    from backend.core.backtest.engine import BacktestEngine
    from backend.core.backtest.params_builder import build_params
    flows, position, symbol, start, end = args
    eng = BacktestEngine(0, 0, symbol, start - 20 * 86_400_000, end, trade_start_ts=start, initial_capital=10000.0)
    for fl in flows:
        eng.add_strategy_flow(fl["name"], build_params(fl["name"], fl["ast"], fl["type"], position, "cex", symbol=symbol))
    with contextlib.redirect_stdout(io.StringIO()):
        eng.load_data()
        eng.run()
    res = eng.get_results()
    c = pd.DataFrame(res["equity_curve"])
    c = c[c["time"] >= start]
    return {"symbol": symbol, "t": c["time"].tolist(), "eq": (c["equity"] / 1e4).tolist(),
            "eq_worst": (c["equity_worst"] / 1e4).tolist(), "n": len(res["positions"]),
            "ret_pct": (res["final_equity"] / 1e4 - 1) * 100}


def bootstrap(daily: np.ndarray, scale: float, n: int = 4000, block: int = 5, horizon: int = 365, seed: int = 1):
    rng = np.random.default_rng(seed)
    mdds, rets = np.empty(n), np.empty(n)
    for k in range(n):
        starts = rng.integers(0, len(daily), horizon // block + 1)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:horizon] % len(daily)
        eq = np.cumprod(1 + scale * daily[idx])
        peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
        mdds[k] = ((peak - eq) / peak).max()
        rets[k] = eq[-1] - 1
    return {"median_ret_pct": round(float(np.median(rets) * 100), 1), "p05_ret_pct": round(float(np.percentile(rets, 5) * 100), 1),
            "mdd_p95_pct": round(float(np.percentile(mdds, 95) * 100), 1),
            "p_mdd_ge_30_pct": round(float((mdds >= MDD_LIMIT).mean() * 100), 1)}


def main(argv=None):
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--alpha", required=True, help="alpha_id trong data/alphas/registry.json")
    ap.add_argument("--assets", required=True, help="vd. SOL,DOGE (dùng dữ liệu <SYM>@perp)")
    ap.add_argument("--registry", default=os.path.join(NORA_ROOT, "data", "alphas", "registry.json"))
    ap.add_argument("--workers", default="auto",
                    help="số tiến trình song song; 'auto' = tính theo RAM (gồm cgroup) và CPU")
    a = ap.parse_args(argv)
    from backend.utils.memwatch import require_memory_limit, worker_init
    require_memory_limit("portfolio_sizing")
    from backend.utils.parallel import resolve_workers
    # 900 MB/worker: mỗi job là backtest MỘT tài sản (chưa đo thực — hiệu chỉnh khi có số đỉnh RAM)
    workers = resolve_workers(a.workers, 900, "portfolio_sizing")
    from backend.cli.research_trend_portfolio import portfolio

    reg = json.load(open(a.registry, encoding="utf-8"))
    alpha = next(x for x in reg["alphas"] if x["alpha_id"] == a.alpha)
    w = {k: int(pd.Timestamp(v, tz="UTC").value // 10**6) for k, v in alpha["evidence"]["windows"].items()}
    periods = {"wfa_test": (w["dev1_end"], w["holdout"]), "holdout": (w["holdout"], w["end"])}
    base = {**alpha["position"], "order_size_pct": 100.0, "leverage": 1}  # 1x danh nghĩa mỗi phần vốn
    assets = [s if "@" in s else f"{s}@perp" for s in a.assets.split(",")]

    jobs, keys = [], []
    for sf in ("level", "extreme"):
        for per, (s, e) in periods.items():
            for sym in assets:
                jobs.append((alpha["flows"], {**base, "stop_fill": sf}, sym, s, e))
                keys.append((sf, per, sym))
    with ProcessPoolExecutor(max_workers=workers, initializer=worker_init) as pool:
        out = dict(zip(keys, pool.map(_run, jobs)))

    report = {"alpha": a.alpha, "assets": assets, "periods": {k: [str(pd.Timestamp(v[0], unit="ms").date()),
                                                                 str(pd.Timestamp(v[1], unit="ms").date())] for k, v in periods.items()},
              "modes": {}}
    for sf in ("level", "extreme"):
        print(f"\n=== SL khớp '{sf}' — vốn chia đều, mỗi phần 1x danh nghĩa ===")
        mode = {"periods": {}, "sizing": {}}
        daily = []
        for per in periods:
            runs = [out[(sf, per, s)] for s in assets]
            pf = portfolio(runs)
            daily.append(pf["series"].resample("1D").last().pct_change().dropna())
            mode["periods"][per] = {"by_asset": {r["symbol"]: {"ret_pct": round(r["ret_pct"], 1), "trades": r["n"]} for r in runs},
                                    **{k: v for k, v in pf.items() if k != "series"}}
            print(f"{per:9s} " + "  ".join(f"{r['symbol']} {r['ret_pct']:6.1f}% ({r['n']})" for r in runs)
                  + f"  | danh mục {pf['ret_pct']}%  MDD {pf['mdd_pct']}%  sharpe {pf['sharpe']}")
        d = pd.concat(daily).to_numpy()
        best = None
        for sc in SCALES:
            b = bootstrap(d, sc)
            mode["sizing"][str(sc)] = b
            ok = b["p_mdd_ge_30_pct"] <= RUIN_MAX_PCT
            best = sc if ok else best
            print(f"  hệ số {sc:4.2f}x: lãi 1 năm trung vị {b['median_ret_pct']:6.1f}% (p5 {b['p05_ret_pct']:6.1f}%), "
                  f"MDD p95 {b['mdd_p95_pct']:5.1f}%, P(MDD>=30%) {b['p_mdd_ge_30_pct']:4.1f}% {'✓' if ok else '✗'}")
        mode["max_scale_within_budget"] = best
        report["modes"][sf] = mode
        print(f"  -> hệ số vốn tối đa trong ngân sách (P(MDD>=30%) <= {RUIN_MAX_PCT}%): {best}")
    path = os.path.join(NORA_ROOT, "data", "alphas", f"portfolio_{a.alpha}__{'_'.join(s.split('@')[0] for s in assets)}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("\nlưu:", path)


if __name__ == "__main__":
    main()
