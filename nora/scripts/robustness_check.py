"""Kiểm độ bền của một alpha ứng viên (bước cuối trước testnet).

1. Lân cận tham số: đổi TỪNG tham số sang mức kề bên trong không gian tối ưu; alpha bền khi phần lớn
   lân cận vẫn có lãi ở cả giai đoạn WFA-test (dev2) và holdout. Sụp khi đổi nhẹ = overfit.
2. Chuyển tài sản: chạy nguyên bộ tham số trên các tài sản cùng loại khác (không tối ưu lại).

Dùng:  PYTHONPATH=. python scripts/robustness_check.py <results.json> <space_id> <SYMBOL> [--workers auto|8]
"""
# ── Pin BLAS threads TRƯỚC khi import numpy ───────────────────────────────────
import os
for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    if _blas_env not in os.environ:
        os.environ[_blas_env] = "1"
# ─────────────────────────────────────────────────────────────────────────────

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)

DAY = 86_400_000


def _window_run(args):
    space_id, symbol, params, start, end, trade_start = args
    import contextlib
    import io
    from backend.core.strategy.strategy_library import OPTIMIZATION_SPACES
    from backend.wfa.walk_forward import _run_single_window
    sd = next(s for s in OPTIMIZATION_SPACES if s["id"] == space_id)
    flows = [{"id": space_id, "type": sd["side"],
              "ast": {"type": sd["side"], "match": [{"condition": sd["tree"]}], "stop": []}}]
    with contextlib.redirect_stdout(io.StringIO()):
        s, _ = _run_single_window(symbol=symbol, flows=flows, start_ts=start, end_ts=end, trade_start_ts=trade_start,
                                  initial_capital=10000.0, **params)
    return {"ret": s["return_pct"], "mdd": s["max_drawdown_pct"], "n": s["total_trades"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("space_id")
    ap.add_argument("symbol")
    ap.add_argument("--workers", default="auto",
                    help="số tiến trình song song; 'auto' = tính theo RAM (gồm cgroup) và CPU")
    a = ap.parse_args(argv)
    from backend.utils.memwatch import require_memory_limit, worker_init
    require_memory_limit("robustness_check")
    from backend.utils.parallel import resolve_workers
    # 900 MB/worker: mỗi job là backtest MỘT tài sản (chưa đo thực — hiệu chỉnh khi có số đỉnh RAM)
    workers = resolve_workers(a.workers, 900, "robustness_check")
    from backend.core.strategy.strategy_library import OPTIMIZATION_SPACES
    from backend.db.data_layout import list_assets
    from backend.db.local_pkl import read_manifest
    import pandas as pd

    res = next(r for r in json.load(open(a.results)) if r["space"] == a.space_id and r["symbol"] == a.symbol)
    sd = next(s for s in OPTIMIZATION_SPACES if s["id"] == a.space_id)
    final = dict(res["final_params"])
    w = {k: int(pd.Timestamp(v, tz="UTC").value // 10**6) for k, v in res["windows"].items()}
    end = int((read_manifest(res["data_symbol"]) or {})["end_ts"])
    periods = {"dev2": (w["dev1_end"] - 10 * DAY, w["holdout"], w["dev1_end"]), "holdout": (w["holdout"] - 10 * DAY, end, w["holdout"])}

    variants = [("GỐC", final)]
    for key, values in sd["space"].items():
        if key not in final or final[key] not in values:
            continue
        i = values.index(final[key])
        for j in (i - 1, i + 1):
            if 0 <= j < len(values):
                variants.append((f"{key}={values[j]}", {**final, key: values[j]}))
    others = sorted({x["symbol"] for x in list_assets() if x["venue"] == sd["venue"] and x["instrument"] == "spot"} - {a.symbol})

    jobs = [(a.space_id, a.symbol, p, *periods[per]) for _, p in variants for per in ("dev2", "holdout")]
    jobs += [(a.space_id, sym, final, *periods[per]) for sym in others for per in ("dev2", "holdout")]
    with ProcessPoolExecutor(max_workers=workers, initializer=worker_init) as pool:
        out = list(pool.map(_window_run, jobs))
    k = 0
    report = {"space": a.space_id, "symbol": a.symbol, "neighbors": [], "other_assets": []}
    print(f"== Lân cận tham số ({a.space_id} / {a.symbol}) — lãi% / MDD% / số lệnh ==")
    pos_both = 0
    for name, _ in variants:
        d2, ho = out[k], out[k + 1]
        k += 2
        ok = d2["ret"] > 0 and ho["ret"] > 0
        pos_both += ok and name != "GỐC"
        report["neighbors"].append({"variant": name, "dev2": d2, "holdout": ho, "profitable_both": ok})
        print(f"  {name:32s} dev2 {d2['ret']:7.2f}/{d2['mdd']:5.1f}/{d2['n']:3d}   holdout {ho['ret']:7.2f}/{ho['mdd']:5.1f}/{ho['n']:3d}  {'✓' if ok else '✗'}")
    print(f"  -> {pos_both}/{len(variants) - 1} lân cận có lãi ở cả dev2 và holdout")
    print("== Cùng tham số trên tài sản khác (không tối ưu lại) ==")
    pos_assets = 0
    for sym in others:
        d2, ho = out[k], out[k + 1]
        k += 2
        ok = d2["ret"] > 0 and ho["ret"] > 0
        pos_assets += ok
        report["other_assets"].append({"symbol": sym, "dev2": d2, "holdout": ho, "profitable_both": ok})
        print(f"  {sym:6s} dev2 {d2['ret']:7.2f}/{d2['mdd']:5.1f}/{d2['n']:3d}   holdout {ho['ret']:7.2f}/{ho['mdd']:5.1f}/{ho['n']:3d}  {'✓' if ok else '✗'}")
    print(f"  -> {pos_assets}/{len(others)} tài sản khác có lãi ở cả dev2 và holdout")
    report["neighbors_profitable"] = f"{pos_both}/{len(variants) - 1}"
    report["other_assets_profitable"] = f"{pos_assets}/{len(others)}"
    path = os.path.join(os.path.dirname(os.path.abspath(a.results)), f"robustness_{a.space_id}__{a.symbol}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("lưu:", path)


if __name__ == "__main__":
    main()
