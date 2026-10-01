"""Bước B: tối ưu chiến lược một cách TRUNG THỰC -> alpha (bộ tham số) dùng được cho testnet.

Chia dữ liệu mỗi tài sản theo thời gian (không giai đoạn nào nhìn thấy dữ liệu của giai đoạn sau):

    |──────────── dev 80% ─────────────|── holdout 20% ──|
    |── dev1 (sàng lọc) ──|─ dev2 (WFA) ─|  (chấm cuối)    |

1. Sàng lọc (dev1): thử N cấu hình lấy mẫu ngẫu nhiên (seed cố định) trong không gian tối ưu.
   Giữ cấu hình có lãi, MDD mark-to-market <= 30%, đủ số lệnh; lấy top-K theo lãi/MDD.
2. WFA (dev2): mỗi fold chọn cấu hình tốt nhất trong top-K trên IS, kiểm trên OOS kế tiếp.
3. Monte Carlo trên lợi suất NGÀY mark-to-market của OOS (block 5, 2000 mô phỏng): xác suất cháy (MDD >= 30%) <= 5%.
   (kết quả theo lệnh đã đóng chỉ ghi lại làm tham chiếu: mc_trades)
4. Holdout (20% cuối, chưa ai chạm): chạy cấu hình được WFA chọn nhiều nhất.
ALPHA = qua gate WFA + MC + holdout có lãi và MDD <= 30%. Không có thì báo thẳng là không có.

Dùng:  PYTHONPATH=. python scripts/optimize_alphas.py [--spaces id1,id2] [--assets BTC,ETH] [--n 60] [--workers auto|8]
"""
# ── Pin BLAS threads TRƯỚC khi import numpy ───────────────────────────────────
import os
for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    if _blas_env not in os.environ:
        os.environ[_blas_env] = "1"
# ─────────────────────────────────────────────────────────────────────────────

import argparse
import itertools
import json
import random
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)
from backend.utils.jsonsafe import json_default  # noqa: E402

DAY = 86_400_000
MAX_MDD = 30.0
MAX_RUIN = 5.0
TOP_K = 8
# RAM ước tính mỗi worker (MB) để chia số worker: WFA đơn tài sản cho MỘT cặp, CHƯA đo thực —
# hiệu chỉnh từ "peak_rss_mb" mới ghi trong results.json của mỗi cặp.
PER_PAIR_MB = 900


def _quiet(fn, *a, **k):
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


# Khoá không gian ảnh hưởng ngân sách DCA (params_builder.dca_budget_check)
_DCA_KEYS = ("leverage", "order_size_pct", "dca_step_pct", "dca_max_layers", "dca_size_multiplier")


def _dca_filter(space, fixed=None, venue="cex", symbol=None):
    """-> (valid(cfg) -> bool, số tổ hợp không hợp lệ trong toàn không gian). Hợp lệ = qua dca_budget_check."""
    from backend.backtest.params_builder import dca_budget_check, pool_fee_rate, resolve_costs
    keys = sorted(space)
    total = 1
    for k in keys:
        total *= len(space[k])
    fixed = dict(fixed or {})
    market = str(fixed.get("market") or "spot").lower()
    pool = pool_fee_rate(symbol) if venue == "dex" else None   # DEX: phí pool thật như build_params
    costs = resolve_costs(venue, market, pool, None, pool)

    def valid(c):
        return dca_budget_check({**fixed, **{k: v for k, v in c.items() if not k.startswith("sig.")}}, costs)["ok"]

    # Hợp lệ chỉ phụ thuộc vài khoá -> đếm trên không gian con, nhân với phần còn lại
    rel = [k for k in keys if k in _DCA_KEYS]
    rel_total = 1
    for k in rel:
        rel_total *= len(space[k])
    rel_valid = sum(valid(dict(zip(rel, c))) for c in itertools.product(*[space[k] for k in rel]))
    return valid, (rel_total - rel_valid) * (total // rel_total)


def configs_invalid(space, fixed=None, venue="cex", symbol=None):
    """Số tổ hợp trong TOÀN không gian vi phạm ngân sách DCA (ghi vào kết quả mỗi cặp)."""
    return _dca_filter(space, fixed, venue, symbol)[1]


def sample_configs(space, n, seed, fixed=None, venue="cex", symbol=None):
    """Lấy mẫu n cấu hình HỢP LỆ (seed cố định -> tái lập). Tổ hợp vi phạm ngân sách DCA (tầng cuối không bao giờ khớp,
    vd. order_size 20% × 5 tầng) bị loại TRƯỚC khi lấy mẫu để đủ n cấu hình dùng được. -> (configs, tổng số tổ hợp)."""
    keys = sorted(space)
    total = 1
    for k in keys:
        total *= len(space[k])
    valid, invalid = _dca_filter(space, fixed, venue, symbol)
    rng = random.Random(seed)
    if total - invalid <= n:
        combos = [dict(zip(keys, c)) for c in itertools.product(*[space[k] for k in keys])]
        combos = [c for c in combos if valid(c)]
    else:
        seen, combos = set(), []
        while len(combos) < n:
            c = tuple(rng.choice(space[k]) for k in keys)
            if c not in seen:
                seen.add(c)
                cfg = dict(zip(keys, c))
                if valid(cfg):
                    combos.append(cfg)
    return combos, total


def windows(manifest, venue):
    start, end = int(manifest["start_ts"]), int(manifest["end_ts"])
    start = (start // DAY + 1) * DAY  # bỏ ngày đầu chưa đủ
    span = end - start
    holdout = start + int(span * 0.8)
    dev1_end = start + int(span * 0.4)
    return {"start": start, "dev1_end": dev1_end, "holdout": holdout, "end": end}


def monte_carlo_gate(wfa_result, sims=2000, block=5, seed=7):
    """-> (mc, mc_trades) từ kết quả WFA. `mc` (cổng ruin) = bootstrap lợi suất ngày MTM OOS, basis="daily";
    `mc_trades` = bootstrap lệnh đã đóng (tham chiếu, không dùng làm cổng). Ít hơn 30 điểm -> ruin None."""
    from backend.studio_pipeline.monte_carlo import run_monte_carlo

    def pack(mc, basis):
        return {"basis": basis, "risk_of_ruin_pct": mc["risk_of_ruin_pct"], "mdd_p95": mc["percentile_mdd"].get("p95"),
                "terminal_p50": mc["terminal_return_pct"]["p50"], "terminal_p10": mc["terminal_return_pct"]["p10"],
                "n": mc["trades_count"]}

    def run(rows, basis):
        if len(rows) < 30:
            return {"basis": basis, "risk_of_ruin_pct": None, "n": len(rows), "note": "ít hơn 30 điểm"}
        return pack(run_monte_carlo(rows, simulations=sims, initial_capital=10000.0, ruin_threshold_pct=MAX_MDD,
                                    block_size=block, seed=seed), basis)

    daily = [{"pnl_pct": float(r) * 100.0} for r in wfa_result.get("aggregate_oos_daily_returns") or []]
    return run(daily, "daily"), run(wfa_result.get("aggregate_oos_trades") or [], "trades")


def _run_pair(space_id, symbol, n, seed, db_path):
    os.environ["NORA_PIPELINE_DB_PATH"] = db_path
    from backend.alpha.strategy_library import OPTIMIZATION_SPACES
    from backend.backtest.params_builder import data_symbol
    from backend.db.local_pkl import read_manifest
    from backend.studio_pipeline.jobs import create_wfa_job, get_wfa_job, init_db
    from backend.studio_pipeline.schemas import StrategySnapshot, WfaFoldConfig
    from backend.studio_pipeline.wfa import _run_single_window, execute_wfa_pipeline

    init_db()
    sd = next(s for s in OPTIMIZATION_SPACES if s["id"] == space_id)
    fixed = dict(sd["fixed"])
    data_sym, price_source = data_symbol(symbol, fixed.get("market", "spot"))
    manifest = read_manifest(data_sym)
    w = windows(manifest, sd["venue"])
    flows = [{"id": space_id, "name": f"{sd['side']} {space_id}", "type": sd["side"],
              "ast": {"type": sd["side"], "match": [{"condition": sd["tree"]}], "stop": []}}]
    is_dex = sd["venue"] == "dex"
    min_trades = 15 if is_dex else 30
    out = {"space": space_id, "symbol": symbol, "data_symbol": data_sym, "price_source": price_source,
           "windows": {k: datetime.fromtimestamp(v / 1000, timezone.utc).strftime("%Y-%m-%d") for k, v in w.items()},
           "configs_tried": 0, "space_size": 0, "configs_invalid": 0}
    t0 = time.time()

    # 1. Sàng lọc trên dev1
    configs, total = sample_configs(sd["space"], n, seed, fixed=fixed, venue=sd["venue"], symbol=symbol)
    out["configs_tried"], out["space_size"] = len(configs), total
    out["configs_invalid"] = configs_invalid(sd["space"], fixed, sd["venue"], symbol)
    screened = []
    for cfg in configs:
        try:
            s, _ = _quiet(_run_single_window, symbol=symbol, flows=flows, start_ts=w["start"],
                          end_ts=w["dev1_end"], initial_capital=10000.0, **fixed, **cfg)
        except ValueError:
            continue
        ok = s["total_trades"] >= min_trades and s["max_drawdown_pct"] <= MAX_MDD and s["return_pct"] > 0
        screened.append({"cfg": cfg, "ret": s["return_pct"], "mdd": s["max_drawdown_pct"], "n": s["total_trades"],
                         "score": s["return_pct"] / max(s["max_drawdown_pct"], 5.0), "ok": ok})
    passing = sorted([x for x in screened if x["ok"]], key=lambda x: -x["score"])
    out["screen"] = {"passed": len(passing), "best": passing[:3],
                     "median_return": sorted(x["ret"] for x in screened)[len(screened) // 2] if screened else None}
    if not passing:
        out["verdict"] = "LOAI_O_SANG_LOC"
        out["seconds"] = round(time.time() - t0)
        return out
    top = [x["cfg"] for x in passing[:TOP_K]]

    # 2. WFA trên dev2 (fold test bắt đầu đúng từ dev1_end)
    train, test = (30, 10) if is_dex else (120, 30)
    snap = StrategySnapshot(name=space_id, symbol=symbol, flows=flows, start_ts=w["dev1_end"] - train * DAY,
                            end_ts=w["holdout"], initial_capital=10000.0, param_candidates=top,
                            **{k: v for k, v in fixed.items()})
    # min_positive_ratio=0.6: thống nhất với Studio (WfaFoldConfig mặc định)
    cfgw = WfaFoldConfig(train_days=train, test_days=test, min_folds=3 if is_dex else 5, min_positive_ratio=0.6,
                         min_oos_trades=min_trades, max_oos_mdd_pct=MAX_MDD, min_total_oos_profit_pct=0.0,
                         min_is_trades=10, min_is_profit_pct=0.0)
    job = create_wfa_job(symbol, space_id, 0)
    _quiet(execute_wfa_pipeline, job, snap, cfgw, f"opt_{space_id}_{symbol}")
    wj = get_wfa_job(job)
    if wj.get("status") != "completed":
        out["verdict"] = "LOI_WFA"
        out["error"] = wj.get("error")
        return out
    res = wj["result"]
    out["wfa"] = {k: res[k] for k in ("total_folds", "positive_folds_count", "total_oos_return_pct", "total_oos_trades",
                                        "worst_fold_mdd_pct", "acceptance_gate_passed", "param_stability", "wfe")}
    out["wfa"]["gate_checks"] = {k: v["passed"] for k, v in res["gate_checks"].items()}

    # 3. Monte Carlo: cổng chính trên lợi suất NGÀY MTM của OOS (gồm lỗ treo); kết quả theo lệnh đã đóng giữ để tham chiếu
    out["mc"], out["mc_trades"] = monte_carlo_gate(res)

    # 4. Holdout với cấu hình WFA chọn nhiều nhất
    keys = sorted(top[0])
    chosen = [tuple(f["chosen_params"].get(k) for k in keys) for f in res["folds"] if f.get("status") == "TRADED"]
    final = dict(zip(keys, Counter(chosen).most_common(1)[0][0])) if chosen else top[0]
    hs, _ = _quiet(_run_single_window, symbol=symbol, flows=flows, start_ts=w["holdout"] - 10 * DAY, end_ts=w["end"],
                   trade_start_ts=w["holdout"], initial_capital=10000.0, **fixed, **final)
    out["final_params"] = {**fixed, **final}
    out["holdout"] = {"return_pct": hs["return_pct"], "mdd_pct": hs["max_drawdown_pct"], "trades": hs["total_trades"],
                      "win_rate": hs["win_rate"], "profit_factor": hs["profit_factor"]}

    checks = {
        "wfa_gate": bool(res["acceptance_gate_passed"]),
        "mc_ruin_le_5": out["mc"].get("risk_of_ruin_pct") is not None and out["mc"]["risk_of_ruin_pct"] <= MAX_RUIN,
        "holdout_profit": hs["return_pct"] > 0,
        "holdout_mdd_le_30": hs["max_drawdown_pct"] <= MAX_MDD,
        "holdout_trades": hs["total_trades"] >= (5 if is_dex else 10),
        "leverage_le_10": float(out["final_params"].get("leverage", 1)) <= 10,
    }
    out["checks"] = checks
    out["verdict"] = "ALPHA" if all(checks.values()) else "KHONG_DAT"
    out["seconds"] = round(time.time() - t0)
    return out


def run_pair(space_id, symbol, n, seed, db_path):
    """Chạy một cặp, ghi đỉnh RAM của worker, rồi xả cache để cặp kế tiếp trong cùng tiến trình không cộng dồn RAM."""
    try:
        out = _run_pair(space_id, symbol, n, seed, db_path)
        from backend.utils.memwatch import peak_rss_mb
        out["peak_rss_mb"] = round(peak_rss_mb(), 1)
        return out
    finally:
        try:
            from backend.core.loader import CandleLoader
            CandleLoader.clear_cache()
        except Exception:
            pass
        try:
            from backend.backtest.portfolio import data_cache_clear
            data_cache_clear()
        except Exception:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spaces", default=None)
    ap.add_argument("--assets", default=None)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=20260930)
    ap.add_argument("--workers", default="auto",
                    help="số tiến trình song song; 'auto' = tính theo RAM (gồm cgroup) và CPU")
    args = ap.parse_args(argv)
    from backend.utils.memwatch import require_memory_limit, worker_init
    from backend.utils.parallel import resolve_workers
    require_memory_limit("optimize_alphas")
    workers = resolve_workers(args.workers, PER_PAIR_MB, "optimize_alphas")
    from backend.alpha.strategy_library import OPTIMIZATION_SPACES
    from backend.db.data_layout import cache_dir, list_assets

    spaces = [s for s in OPTIMIZATION_SPACES if not args.spaces or s["id"] in args.spaces.split(",")]
    assets = {v: sorted({a["symbol"] for a in list_assets() if a["venue"] == v and a["instrument"] == "spot"})
              for v in ("cex", "dex")}
    wanted = {x.strip().upper() for x in args.assets.split(",")} if args.assets else None
    pairs = [(s["id"], sym) for s in spaces for sym in assets[s["venue"]] if not wanted or sym in wanted]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    out_dir = cache_dir(None, "optimize", stamp)
    db_path = os.path.join(out_dir, "pipeline.db")
    print(f"{len(pairs)} cặp (chiến lược × tài sản), {args.n} cấu hình/cặp, {workers} tiến trình -> {out_dir}", flush=True)

    results = []
    with ProcessPoolExecutor(max_workers=workers, initializer=worker_init) as pool:
        futs = {pool.submit(run_pair, sid, sym, args.n, args.seed, db_path): (sid, sym) for sid, sym in pairs}
        for fut in as_completed(futs):
            sid, sym = futs[fut]
            try:
                r = fut.result()
            except Exception as exc:  # một cặp lỗi không làm hỏng cả lượt
                r = {"space": sid, "symbol": sym, "verdict": "LOI", "error": repr(exc)}
            results.append(r)
            print(f"[{len(results)}/{len(pairs)}] {sid:26s} {sym:5s} -> {r['verdict']}", flush=True)
            with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as fh:
                json.dump(results, fh, ensure_ascii=False, indent=1, default=json_default)
    alphas = [r for r in results if r.get("verdict") == "ALPHA"]
    print(f"\nALPHA đạt mọi gate: {len(alphas)}/{len(results)}  (kết quả: {out_dir}/results.json)")
    for r in sorted(results, key=lambda r: (r["space"], r["symbol"])):
        h, wf, mc = r.get("holdout", {}), r.get("wfa", {}), r.get("mc", {})
        print(f"{r['space']:26s} {r['symbol']:5s} {r['verdict']:16s} sàng={r.get('screen', {}).get('passed')}/{r.get('configs_tried')} "
              f"WFA_oos={wf.get('total_oos_return_pct')}% gate={wf.get('acceptance_gate_passed')} "
              f"ruin={mc.get('risk_of_ruin_pct')}% holdout={h.get('return_pct')}% mdd={h.get('mdd_pct')}%")


if __name__ == "__main__":
    main()
