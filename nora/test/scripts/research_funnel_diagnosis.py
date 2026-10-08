"""Vì sao phễu gần như không ai qua? Lấy mẫu các alpha ĐÃ QUA S1 của một lượt phễu, chạy WFA (S3) cho từng alpha bằng engine hiện hành
(khớp "extreme" theo nến 1m), BỎ QUA S2 — để biết mỗi cổng loại bao nhiêu và S2 có đang loại cả alpha qua được WFA không.

Thêm WFA kiểu sova (sova/backend/optimize/wfa/wfa_engine.py::_apply_window_pipeline) trên cùng mẫu: mỗi fold lọc alpha có lãi IS
(train) -> lọc tương quan (đường vốn IS, |rho| <= 0.8, tối đa top_n theo lãi IS) -> danh mục chia đều -> lãi OOS của fold.

Dùng (từ nora/): ops/run_limited.sh -- test/scripts/research_funnel_diagnosis.py --run fr-... [--per 30] [--workers 12]
"""
import argparse
import json
import os
import random
import sys
import time
import warnings
from collections import Counter, defaultdict

import numpy as np

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)

CTX = {}


def _one(row):
    from backend.optimize.search import evaluate as bt
    c = CTX
    folds = []
    try:
        for f in c["folds"]:
            is_r = bt.run_backtest(bt.base_job(row["strategy"], row["params"], f["train"], "level", False, c["rpt"], c["symbols"], c["shared"],
                                               c["tf"]))
            oos = bt.run_backtest(bt.base_job(row["strategy"], row["params"], f["test"], "extreme", True, c["rpt"], c["symbols"], c["shared"],
                                              c["tf"], learn_window=f["train"]), want_trades=True)
            folds.append({"fold": f["fold"], "train": f["train_iso"], "test": f["test_iso"], "is_ret_pct": is_r["metrics"]["ret_pct"],
                          "is_trades": is_r["metrics"]["trades"], "is_daily": is_r["daily"], "oos": oos["metrics"], "daily": oos["daily"],
                          "daily_start": oos["daily_start"] or f["test_iso"][0], "trades": oos["trades"]})
    except ValueError as e:
        return {**row, "error": str(e)}
    return {**row, "folds": folds}


def main():
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--per", type=int, default=30, help="số alpha mỗi (chiến lược, biến thể regime)")
    ap.add_argument("--workers", type=int, default=6)   # 12 worker từng lên ~10 GB RAM (mỗi worker đọc 1m.pkl cho khớp extreme)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    from backend.optimize.search import evaluate as bt
    from backend.optimize.funnel import stages as gates
    from backend.optimize.funnel.storage import RunStore
    run_dir = os.path.join(NORA_ROOT, "data", "_cache", "funnel", a.run)
    st = RunStore(run_dir, read_only=True)
    run = st.read_run()
    cfg, w = run["config"], run["windows_ms"]
    groups = defaultdict(list)
    for aid, strat, m1, _ in st.iter_stage_metrics("S1_backtest"):
        al = st.get_alpha(aid)
        if al["rejected_stage"] == "S1_backtest":
            continue
        groups[(strat, "learn" if al["params"].get("regime") == "learn" else "off")].append(aid)
    rng = random.Random(a.seed)
    rows = []
    for key in sorted(groups):
        ids = groups[key]
        pick = rng.sample(ids, min(a.per, len(ids)))
        m2 = st.metrics_of(pick, "S2_antiluck")
        for aid in pick:
            al = st.get_alpha(aid)
            rows.append({"alpha_id": aid, "strategy": key[0], "variant": key[1], "params": al["params"],
                         "s2_code": al["reject_code"] if al["rejected_stage"] == "S2_antiluck" else None,
                         "dsr": (m2.get(aid) or {}).get("dsr"), "pbo_flag": (m2.get(aid) or {}).get("pbo_flag")})
    st.close()
    shared = os.path.join(NORA_ROOT, "data", "_cache", "research", "funnel_diag_shared")
    CTX.update(folds=bt.fold_job_plan(gates.wfa_folds(w, cfg.get("train_days"), cfg.get("test_days"))), symbols=cfg["symbols"],
               rpt=gates.BASE_RISK_PER_TRADE_PCT, tf=cfg.get("timeframe", "1m"), shared=shared)
    print(f"{len(rows)} alpha (đã qua S1) × {len(CTX['folds'])} fold, khung {CTX['tf']}, {a.workers} worker", flush=True)
    t0 = time.time()
    from backend.crawl.store import require_data_ok
    require_data_ok(cfg["symbols"])
    from multiprocessing import get_context
    with get_context("fork").Pool(a.workers) as pool:
        res = []
        for i, r in enumerate(pool.imap_unordered(_one, rows, chunksize=2)):
            res.append(r)
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(rows)} ({time.time() - t0:.0f}s)", flush=True)
    # ── từng alpha: cổng S3 ──
    out = []
    for r in res:
        if "error" in r:
            out.append({**r, "s3_pass": False, "s3_code": "error"})
            continue
        agg = bt.aggregate_wfa(r["folds"], gates.BASE_RISK_PER_TRADE_PCT)
        ok, code, _ = gates.evaluate_s3(agg["summary"])
        s = agg["summary"]
        out.append({**{k: r[k] for k in ("alpha_id", "strategy", "variant", "s2_code", "dsr", "pbo_flag")}, "s3_pass": ok, "s3_code": code,
                    "folds": s["folds"], "positive_ratio": round(s["positive_ratio"], 2), "oos_pct": s["compounded_oos_ret_pct"],
                    "worst_mdd": s["worst_fold_mdd"], "is_avg": s["is_ret_avg"],
                    "fold_is": [f["is_ret_pct"] for f in r["folds"]], "fold_oos": [f["oos"]["ret_pct"] for f in r["folds"]],
                    "fold_trades": [f["oos"]["trades"] for f in r["folds"]],
                    "_is_daily": [f["is_daily"] for f in r["folds"]], "_oos_daily": [f["daily"] for f in r["folds"]]})
    n = len(out)
    print("\n== S3 (WFA từng alpha, bỏ qua S2) ==", flush=True)
    print(f"qua S3: {sum(o['s3_pass'] for o in out)}/{n} = {100 * sum(o['s3_pass'] for o in out) / max(1, n):.1f}%")
    print("lý do trượt:", Counter(o["s3_code"] for o in out if not o["s3_pass"]).most_common())
    print("lãi kép OOS > 0:", sum(1 for o in out if o.get("oos_pct", -1) > 0), "| fold dương >= 50%:", sum(1 for o in out if o.get("positive_ratio", 0) >= 0.5))
    tr = [t for o in out for t in o.get("fold_trades", [])]
    print(f"lệnh OOS mỗi fold: trung vị {np.median(tr) if tr else 0}, fold 0 lệnh: {sum(1 for t in tr if t == 0)}/{len(tr)}")
    by = defaultdict(list)
    for o in out:
        by[(o["strategy"], o["variant"])].append(o)
    for k, v in sorted(by.items()):
        print(f"  {k[0]:20s} {k[1]:5s}: qua S3 {sum(x['s3_pass'] for x in v):2d}/{len(v)} | OOS>0 {sum(1 for x in v if x.get('oos_pct', -1) > 0):2d} | "
              f"OOS TB {np.mean([x.get('oos_pct', 0) for x in v]):6.2f}% | fold+ TB {np.mean([x.get('positive_ratio', 0) for x in v]):.2f}")
    s2_rej = [o for o in out if o["s2_code"]]
    print(f"S2 loại {len(s2_rej)}/{n}; trong số đó qua S3: {sum(o['s3_pass'] for o in s2_rej)}")
    # ── WFA kiểu sova: danh mục chọn theo IS mỗi fold ──
    print("\n== WFA kiểu sova (IS>0 -> tương quan <= 0.8, top 20 -> chia đều -> OOS) ==", flush=True)
    ok_rows = [o for o in out if "_is_daily" in o]
    nf = len(CTX["folds"])
    fold_res = []
    for fi in range(nf):
        cand = sorted([o for o in ok_rows if o["fold_is"][fi] > 0], key=lambda o: -o["fold_is"][fi])
        sel = []
        for o in cand:
            x = np.asarray(o["_is_daily"][fi], dtype=float)
            if len(x) < 5 or np.std(x) == 0:
                continue
            if all(abs(np.corrcoef(x[:m], np.asarray(s["_is_daily"][fi], dtype=float)[:m])[0, 1]) <= 0.8
                   for s in sel for m in [min(len(x), len(s["_is_daily"][fi]))]):
                sel.append(o)
            if len(sel) >= 20:
                break
        if not sel:
            fold_res.append({"fold": fi + 1, "is_pos": len(cand), "selected": 0, "oos_pct": 0.0})
            continue
        L = min(len(s["_oos_daily"][fi]) for s in sel)
        port = np.mean([np.asarray(s["_oos_daily"][fi][:L], dtype=float) for s in sel], axis=0)
        fold_res.append({"fold": fi + 1, "is_pos": len(cand), "selected": len(sel), "oos_pct": round(float((np.prod(1 + port) - 1) * 100), 2),
                         "strategies": dict(Counter(s["strategy"] for s in sel))})
    for fr in fold_res:
        print(f"  fold {fr['fold']:2d}: IS>0 {fr['is_pos']:3d} chọn {fr['selected']:2d} -> OOS {fr['oos_pct']:6.2f}% {fr.get('strategies', '')}")
    pos = sum(1 for fr in fold_res if fr["oos_pct"] > 0)
    comp = (np.prod([1 + fr["oos_pct"] / 100 for fr in fold_res]) - 1) * 100
    print(f"  fold dương {pos}/{nf}; lãi kép OOS {comp:.2f}%")
    path = os.path.join(NORA_ROOT, "data", "_cache", "research", f"funnel_diag_{a.run}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"alphas": [{k: v for k, v in o.items() if not k.startswith("_")} for o in out], "sova_folds": fold_res,
                   "wall_s": round(time.time() - t0, 1)}, fh, ensure_ascii=False, indent=1, default=str)
    print(f"ghi {path} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
