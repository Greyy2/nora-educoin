"""Bước B: tối ưu chiến lược một cách TRUNG THỰC -> alpha (bộ tham số) dùng được cho testnet.

Chia dữ liệu mỗi tài sản theo thời gian (không giai đoạn nào nhìn thấy dữ liệu của giai đoạn sau):

    |──────────── dev 80% ─────────────|── holdout 20% ──|
    |── dev1 (sàng lọc) ──|─ dev2 (WFA) ─|  (chấm cuối)    |

1. Sàng lọc (dev1): thử N cấu hình lấy mẫu ngẫu nhiên (seed cố định) trong không gian tối ưu.
   Giữ cấu hình có lãi, MDD mark-to-market <= 30%, đủ số lệnh; lấy top-K theo lãi/MDD.
2. WFA (dev2): mỗi fold chọn cấu hình tốt nhất trong top-K trên IS, kiểm trên OOS kế tiếp.
3. Monte Carlo trên lợi suất NGÀY mark-to-market của OOS (block 5, >= 10.000 mô phỏng): xác suất cháy (MDD >= 30%) <= 5% VÀ
   mọi kịch bản cực xấu tất định (backend/carlo: stress_scenarios) có MDD < 50%, không cháy vốn.
   (kết quả theo lệnh đã đóng chỉ ghi lại làm tham chiếu: mc_trades)
4. Holdout (20% cuối, chưa ai chạm): chạy cấu hình được WFA chọn nhiều nhất.
ALPHA = qua gate WFA + MC + holdout có lãi và MDD <= 30%. Không có thì báo thẳng là không có.

Dùng:  PYTHONPATH=. python -m backend.cli.optimize_alphas [--spaces id1,id2] [--assets BTC,ETH] [--n 60] [--workers auto|8]
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

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
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
    from backend.core.backtest.params_builder import dca_budget_check, pool_fee_rate, resolve_costs
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


def _space_total(space):
    total = 1
    for k in space:
        total *= len(space[k])
    return total


def count_configs(space, n, fixed=None, venue="cex", symbol=None):
    """Số cấu hình HỢP LỆ sẽ thử = min(n, tổng - số vi phạm ngân sách DCA) — không dựng/duyệt lưới."""
    _, invalid = _dca_filter(space, fixed, venue, symbol)
    return min(int(n), _space_total(space) - invalid)


def iter_sample_configs(space, n, seed, fixed=None, venue="cex", symbol=None):
    """Sinh LƯỜI đúng dãy của `sample_configs` (cùng RNG, cùng thứ tự) — không giữ danh sách n cấu hình trong RAM.
    Vùng đã bốc được nhớ bằng một số nguyên (chỉ số trộn cơ số) thay cho tuple giá trị: RAM ~60 B/cấu hình thay vì vài trăm."""
    keys = sorted(space)
    total = _space_total(space)
    valid, invalid = _dca_filter(space, fixed, venue, symbol)
    rng = random.Random(seed)
    if total - invalid <= n:
        for c in itertools.product(*[space[k] for k in keys]):
            cfg = dict(zip(keys, c))
            if valid(cfg):
                yield cfg
    else:
        ranges = [range(len(space[k])) for k in keys]
        seen, count = set(), 0
        while count < n:
            idx = tuple(rng.choice(r) for r in ranges)   # rng.choice(range) = cùng lượng RNG như rng.choice(list)
            code = 0
            for r, i in zip(ranges, idx):
                code = code * len(r) + i
            if code not in seen:
                seen.add(code)
                cfg = {k: space[k][i] for k, i in zip(keys, idx)}
                if valid(cfg):
                    count += 1
                    yield cfg


def sample_configs(space, n, seed, fixed=None, venue="cex", symbol=None):
    """Lấy mẫu n cấu hình HỢP LỆ (seed cố định -> tái lập). Tổ hợp vi phạm ngân sách DCA (tầng cuối không bao giờ khớp,
    vd. order_size 20% × 5 tầng) bị loại TRƯỚC khi lấy mẫu để đủ n cấu hình dùng được. -> (configs, tổng số tổ hợp)."""
    return list(iter_sample_configs(space, n, seed, fixed, venue, symbol)), _space_total(space)


def windows(manifest, venue):
    start, end = int(manifest["start_ts"]), int(manifest["end_ts"])
    start = (start // DAY + 1) * DAY  # bỏ ngày đầu chưa đủ
    span = end - start
    holdout = start + int(span * 0.8)
    dev1_end = start + int(span * 0.4)
    return {"start": start, "dev1_end": dev1_end, "holdout": holdout, "end": end}


def _extra_cost_daily(wfa_result, n_trades, n_days):
    """Phí/ngày bổ sung cho kịch bản cost_x2 từ dữ liệu của chính alpha: (taker+trượt giá của sàn) x 2 x vòng quay vốn/ngày,
    vòng quay/ngày = số lệnh OOS x (order_size_pct x đòn bẩy trung bình các fold TRADED) / số ngày OOS. Thiếu thông tin -> None
    (monte_carlo dùng hằng số bảo thủ STRESS_COST_FALLBACK_DAILY)."""
    from backend.carlo.monte_carlo import STRESS_COST_SLIPPAGE, STRESS_COST_TAKER, estimate_extra_daily_cost
    prm = [f["chosen_params"] for f in wfa_result.get("folds") or [] if f.get("status") == "TRADED" and f.get("chosen_params")]
    fr = [float(p["order_size_pct"]) / 100.0 * float(p.get("leverage", 1)) for p in prm if p.get("order_size_pct") is not None]
    if not fr or n_days <= 0:
        return None
    taker, slip = STRESS_COST_TAKER, STRESS_COST_SLIPPAGE
    try:   # phí thật của sàn/thị trường nếu tra được (DEX đắt hơn nhiều)
        from backend.core.backtest.params_builder import resolve_costs, venue_of_symbol
        sym = wfa_result.get("symbol")
        market = str(prm[0].get("market") or wfa_result.get("market") or "perp").lower()
        if sym:
            taker, _, slip = resolve_costs(venue_of_symbol(sym), market, None, None, None)
    except Exception:
        pass
    return estimate_extra_daily_cost(n_trades, n_days, sum(fr) / len(fr), taker, slip)


def monte_carlo_gate(wfa_result, sims=None, block=5, seed=7):
    """-> (mc, mc_trades) từ kết quả WFA. `mc` (cổng) = bootstrap lợi suất ngày MTM OOS, basis="daily", >= MC_MIN_SIMULATIONS (10.000)
    kịch bản, CỘNG kịch bản cực xấu tất định (worst_days_first, reversed_order, crash_day, cost_x2, longest_losing_streak_x2) và đường
    bootstrap tệ nhất: `mc.stress` (bảng) và `mc.gate` (evaluate_mc_gate: sims >= 10.000, P(MDD>=30%) <= 5%, MDD mọi kịch bản < 50%, không cháy).
    `mc_trades` = bootstrap lệnh đã đóng (tham chiếu, không dùng làm cổng). Ít hơn 30 điểm -> ruin None, gate trượt."""
    from backend.carlo.monte_carlo import (MC_MIN_SIMULATIONS, evaluate_mc_gate, run_monte_carlo, strip_paths,
                                           stress_scenarios)
    sims = MC_MIN_SIMULATIONS if sims is None else int(sims)

    def run(rows, basis):
        if len(rows) < 30:
            out = {"basis": basis, "risk_of_ruin_pct": None, "n": len(rows), "note": "ít hơn 30 điểm", "simulations": sims}
            if basis == "daily":
                out["stress"], out["gate"] = None, evaluate_mc_gate(sims, None, None)
            return out
        mc = run_monte_carlo(rows, simulations=sims, initial_capital=10000.0, ruin_threshold_pct=MAX_MDD, block_size=block, seed=seed)
        out = {"basis": basis, "risk_of_ruin_pct": mc["risk_of_ruin_pct"], "mdd_p95": mc["percentile_mdd"].get("p95"),
               "terminal_p50": mc["terminal_return_pct"]["p50"], "terminal_p10": mc["terminal_return_pct"]["p10"],
               "n": mc["trades_count"], "simulations": sims}
        if basis == "daily":
            series = [float(r) for r in wfa_result.get("aggregate_oos_daily_returns") or []]
            cost = _extra_cost_daily(wfa_result, len(wfa_result.get("aggregate_oos_trades") or []), len(series))
            stress = strip_paths(stress_scenarios(series, extra_cost_daily=cost) + [mc["worst_bootstrap"]])
            out["stress"], out["extra_cost_daily"] = stress, cost
            out["gate"] = evaluate_mc_gate(sims, mc["risk_of_ruin_pct"], stress, ruin_threshold_pct=MAX_MDD, max_ruin_pct=MAX_RUIN)
        return out

    daily = [{"pnl_pct": float(r) * 100.0} for r in wfa_result.get("aggregate_oos_daily_returns") or []]
    return run(daily, "daily"), run(wfa_result.get("aggregate_oos_trades") or [], "trades")


def _screen_pair(space_id, symbol, n, seed, sd, fixed, flows, w, min_trades, data_sym, store_path):
    """Sàng lọc dev1 của một cặp theo kiểu STREAMING: cấu hình sinh lười, mỗi kết quả ghi ngay vào kho (nếu có) và job đã có trong kho
    được bỏ qua (--resume); chỉ giữ top-TOP_K đạt cổng + bộ đếm + danh sách `ret` (để lấy trung vị) -> RAM không phụ thuộc n.
    -> (số cấu hình thử, đạt, best, median_return, top_cfgs). Kết quả y hệt bản cũ (cùng dãy cấu hình, cùng xếp hạng ổn định)."""
    import heapq
    from array import array
    from backend.optimize.results_store import ResultsStore, canonical, data_fingerprint, make_job_key
    from backend.wfa.walk_forward import _run_single_window
    store = ResultsStore(store_path) if store_path else None
    cand = f"{space_id}:{symbol}"
    sd_sig = canonical([sd["venue"], sd["side"], sd["tree"], fixed, min_trades])
    fp = data_fingerprint([data_sym])
    window = [w["start"], w["dev1_end"]]
    heap, rets, passed = [], array("d"), 0   # heap: min-heap (score, -ord, dict) giữ TOP_K tốt nhất
    try:
        for ord_, cfg in enumerate(iter_sample_configs(sd["space"], n, seed, fixed=fixed, venue=sd["venue"], symbol=symbol)):
            key = make_job_key("screen", cand, cfg, window, None, None, fp, extra=sd_sig) if store else None
            row = store.get(key) if store else None
            if row is not None:
                m = row["metrics"]
            else:
                try:
                    s, _ = _quiet(_run_single_window, symbol=symbol, flows=flows, start_ts=w["start"],
                                  end_ts=w["dev1_end"], initial_capital=10000.0, **fixed, **cfg)
                except ValueError:
                    if store:
                        store.put(key, "screen", cand, cfg, {"skip": True}, ord=ord_)
                    continue
                ok = s["total_trades"] >= min_trades and s["max_drawdown_pct"] <= MAX_MDD and s["return_pct"] > 0
                m = {"ret": s["return_pct"], "mdd": s["max_drawdown_pct"], "n": s["total_trades"],
                     "score": s["return_pct"] / max(s["max_drawdown_pct"], 5.0), "ok": bool(ok)}
                if store:
                    store.put(key, "screen", cand, cfg, m, ord=ord_, score=m["score"] if ok else None)
            if m.get("skip"):
                continue
            rets.append(m["ret"])
            if m["ok"]:
                passed += 1
                item = (m["score"], -ord_, {"cfg": cfg, "ret": m["ret"], "mdd": m["mdd"], "n": m["n"], "score": m["score"], "ok": True})
                if len(heap) < TOP_K:
                    heapq.heappush(heap, item)
                elif item[:2] > heap[0][:2]:
                    heapq.heapreplace(heap, item)
    finally:
        if store:
            store.close()
    best = [t[2] for t in sorted(heap, key=lambda t: (-t[0], -t[1]))]
    median = sorted(rets)[len(rets) // 2] if len(rets) else None
    return len(rets), passed, best, median


def _run_pair(space_id, symbol, n, seed, db_path, store_path=None):
    os.environ["NORA_PIPELINE_DB_PATH"] = db_path
    from backend.core.strategy.strategy_library import OPTIMIZATION_SPACES
    from backend.core.backtest.params_builder import data_symbol
    from backend.db.local_pkl import read_manifest
    from backend.api.jobs.store import create_wfa_job, get_wfa_job, init_db
    from backend.core.contracts import StrategySnapshot, WfaFoldConfig
    from backend.wfa.walk_forward import _run_single_window, execute_wfa_pipeline

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

    # 0. Cổng chất lượng dữ liệu tường minh cho giai đoạn sàng lọc (WFA bên dưới cũng kiểm lại; có cache nên rẻ)
    from backend.core.data.quality_gate import require_data_ok
    require_data_ok([data_sym])

    # 1. Sàng lọc trên dev1 (streaming: không giữ danh sách n cấu hình / n kết quả)
    out["configs_tried"] = count_configs(sd["space"], n, fixed, sd["venue"], symbol)
    out["space_size"] = _space_total(sd["space"])
    out["configs_invalid"] = configs_invalid(sd["space"], fixed, sd["venue"], symbol)
    n_screened, n_passed, passing, median_ret = _screen_pair(space_id, symbol, n, seed, sd, fixed, flows, w, min_trades,
                                                             data_sym, store_path)
    out["screen"] = {"passed": n_passed, "best": passing[:3], "median_return": median_ret}
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
        "mc_stress_gate": bool(out["mc"]["gate"]["passed"]),   # >= 10.000 kịch bản + kịch bản cực xấu (MDD < 50%, không cháy)
        "holdout_profit": hs["return_pct"] > 0,
        "holdout_mdd_le_30": hs["max_drawdown_pct"] <= MAX_MDD,
        "holdout_trades": hs["total_trades"] >= (5 if is_dex else 10),
        "leverage_le_10": float(out["final_params"].get("leverage", 1)) <= 10,
    }
    out["checks"] = checks
    out["verdict"] = "ALPHA" if all(checks.values()) else "KHONG_DAT"
    out["seconds"] = round(time.time() - t0)
    return out


def run_pair(space_id, symbol, n, seed, db_path, store_path=None):
    """Chạy một cặp, ghi đỉnh RAM của worker, rồi xả cache để cặp kế tiếp trong cùng tiến trình không cộng dồn RAM.
    store_path: kho kết quả của lần chạy (sàng lọc ghi từng cấu hình; chạy lại bỏ qua cấu hình đã có)."""
    import multiprocessing
    import signal
    if multiprocessing.parent_process() is not None:   # chỉ trong worker của pool (không đổi handler của tiến trình gọi trực tiếp, vd. test)
        try:   # SIGTERM (huỷ job) -> thoát có trật tự để finally flush kho
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
        except ValueError:
            pass
    try:
        out = _run_pair(space_id, symbol, n, seed, db_path, store_path)
        from backend.utils.memwatch import peak_rss_mb
        out["peak_rss_mb"] = round(peak_rss_mb(), 1)
        return out
    finally:
        try:
            from backend.core.data.loader import CandleLoader
            CandleLoader.clear_cache()
        except Exception:
            pass
        try:
            from backend.core.backtest.portfolio import data_cache_clear
            data_cache_clear()
        except Exception:
            pass


def _pair_job(job):
    """Worker của pool: một cặp lỗi không làm hỏng cả lượt (ghi verdict LOI, không lưu vào kho -> --resume chạy lại)."""
    sid, sym, n, seed, db_path, store_path = job
    try:
        return run_pair(sid, sym, n, seed, db_path, store_path)
    except Exception as exc:
        return {"space": sid, "symbol": sym, "verdict": "LOI", "error": repr(exc)}


def _calibrate(job):
    """Đo giây/cấu hình: chạy MỘT cấu hình sàng lọc đầu của (space, symbol) trong worker (không ghi kho)."""
    sid, sym = job
    from backend.core.backtest.params_builder import data_symbol
    from backend.core.strategy.strategy_library import OPTIMIZATION_SPACES
    from backend.db.local_pkl import read_manifest
    from backend.wfa.walk_forward import _run_single_window
    sd = next(x for x in OPTIMIZATION_SPACES if x["id"] == sid)
    fixed = dict(sd["fixed"])
    data_sym, _ = data_symbol(sym, fixed.get("market", "spot"))
    w = windows(read_manifest(data_sym), sd["venue"])
    flows = [{"id": sid, "name": f"{sd['side']} {sid}", "type": sd["side"],
              "ast": {"type": sd["side"], "match": [{"condition": sd["tree"]}], "stop": []}}]
    cfg = next(iter_sample_configs(sd["space"], 1, 0, fixed=fixed, venue=sd["venue"], symbol=sym))
    t = time.time()
    _quiet(_run_single_window, symbol=sym, flows=flows, start_ts=w["start"], end_ts=w["dev1_end"], initial_capital=10000.0,
           **fixed, **cfg)
    return time.time() - t


def _new_out_dir(cache_dir):
    base = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    for k in itertools.count(1):
        path = cache_dir(None, "optimize", base if k == 1 else f"{base}_{k}")
        if not os.path.exists(os.path.join(path, "results.sqlite")):
            return path


def _fmt_duration(sec):
    sec = float(sec)
    return f"{sec:.0f} giây" if sec < 90 else f"{sec / 60:.1f} phút" if sec < 5400 else f"{sec / 3600:.1f} giờ" if sec < 172800 else f"{sec / 86400:.1f} ngày"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spaces", default=None)
    ap.add_argument("--assets", default=None)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=20260930)
    ap.add_argument("--workers", default="auto",
                    help="số tiến trình song song; 'auto' = tính theo RAM (gồm cgroup) và CPU")
    ap.add_argument("--resume", default="", help="thư mục lần chạy bị ngắt (data/_cache/optimize/<...>): bỏ qua cặp/cấu hình đã có trong results.sqlite")
    ap.add_argument("--max-configs", type=int, default=200_000,
                    help="từ chối khi tổng số cấu hình sàng lọc (cặp × n) vượt ngưỡng này (trừ --force-large)")
    ap.add_argument("--force-large", action="store_true", help="cho phép vượt --max-configs")
    args = ap.parse_args(argv)
    from backend.utils.memwatch import require_memory_limit
    from backend.utils.parallel import pool_imap_bounded, pool_map_safe, resolve_workers
    require_memory_limit("optimize_alphas")
    from backend.core.backtest.params_builder import data_symbol
    from backend.core.data.quality_gate import require_data_ok_or_exit
    from backend.core.strategy.strategy_library import OPTIMIZATION_SPACES
    from backend.db.data_layout import cache_dir, list_assets
    from backend.optimize.progress import Progress, graceful_sigterm
    from backend.optimize.results_store import ResultsStore, canonical, code_version, data_fingerprint, make_job_key

    spaces = [s for s in OPTIMIZATION_SPACES if not args.spaces or s["id"] in args.spaces.split(",")]
    assets = {v: sorted({a["symbol"] for a in list_assets() if a["venue"] == v and a["instrument"] == "spot"})
              for v in ("cex", "dex")}
    wanted = {x.strip().upper() for x in args.assets.split(",")} if args.assets else None
    pairs = [(s["id"], sym) for s in spaces for sym in assets[s["venue"]] if not wanted or sym in wanted]
    by_space = {s["id"]: s for s in spaces}

    # Ước lượng + trần số cấu hình TRƯỚC khi làm gì nặng
    per_pair = {}
    for sid, sym in pairs:
        sd = by_space[sid]
        per_pair[(sid, sym)] = count_configs(sd["space"], args.n, dict(sd["fixed"]), sd["venue"], sym)
    total_configs = sum(per_pair.values())
    if total_configs > args.max_configs and not args.force_large:
        raise SystemExit(f"Từ chối: {total_configs:,} cấu hình sàng lọc ({len(pairs)} cặp × --n {args.n}) vượt --max-configs "
                         f"{args.max_configs:,}. Giảm --n / --spaces / --assets hoặc thêm --force-large.")

    # Cổng chất lượng dữ liệu BẮT BUỘC (tường minh, trước khi fork pool để worker thừa kế cache gate)
    data_syms = {}
    for sid, sym in pairs:
        data_syms[(sid, sym)] = data_symbol(sym, dict(by_space[sid]["fixed"]).get("market", "spot"))[0]
    require_data_ok_or_exit(sorted(set(data_syms.values())))

    workers = resolve_workers(args.workers, PER_PAIR_MB, "optimize_alphas")
    if args.resume:
        out_dir = os.path.abspath(args.resume if os.path.isabs(args.resume) or os.path.isdir(args.resume)
                                  else os.path.join(cache_dir(None, "optimize"), args.resume))
        if not os.path.isfile(os.path.join(out_dir, "results.sqlite")):
            raise SystemExit(f"--resume: {out_dir} không có results.sqlite")
    else:
        out_dir = _new_out_dir(cache_dir)
    db_path = os.path.join(out_dir, "pipeline.db")
    store_path = os.path.join(out_dir, "results.sqlite")
    store = ResultsStore(out_dir)
    progress = Progress(out_dir)
    print(f"{len(pairs)} cặp (chiến lược × tài sản), {args.n} cấu hình/cặp, {workers} tiến trình -> {out_dir}", flush=True)

    code = code_version()
    extra_code = _file_sig("backend/cli/optimize_alphas.py", "backend/carlo/monte_carlo.py", "backend/wfa/walk_forward.py")
    pair_keys = {}
    for sid, sym in pairs:
        sd = by_space[sid]
        sig = canonical([sd["venue"], sd["side"], sd["tree"], dict(sd["fixed"]), sd["space"], extra_code])
        pair_keys[(sid, sym)] = make_job_key("pair", f"{sid}:{sym}", {"n": args.n, "seed": args.seed}, None, None, None,
                                             data_fingerprint([data_syms[(sid, sym)]]), code=code, extra=sig)
    results = [None] * len(pairs)
    pending = []
    for i, pr in enumerate(pairs):
        row = store.get(pair_keys[pr])
        if row is not None:
            results[i] = row["metrics"]
        else:
            pending.append(i)
    if args.resume:
        print(f"[resume] {len(pairs) - len(pending)}/{len(pairs)} cặp đã xong trong kho; còn {len(pending)} cặp "
              f"(+ cấu hình sàng lọc đã ghi: {store.count('screen'):,})", flush=True)

    def write_results():
        done = [r for r in results if r is not None]
        tmp = os.path.join(out_dir, "results.json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(done, fh, ensure_ascii=False, indent=1, default=json_default)
        os.replace(tmp, os.path.join(out_dir, "results.json"))

    t0 = time.time()
    try:
        with graceful_sigterm(progress):
            progress.start_stage("sàng lọc + WFA", total_configs, done=store.count("screen"))
            progress.start_poller(lambda: store.count("screen"))
            if pending:
                # Hiệu chỉnh: đo 1 cấu hình sàng lọc của cặp đầu mỗi chiến lược (1 worker) -> ước lượng thời gian sàng lọc
                est = {"configs": total_configs, "workers": workers, "per_space": {}}
                firsts = {}
                for i in pending:
                    firsts.setdefault(pairs[i][0], pairs[i])
                secs = []
                for sid, (_, sym) in ((k, v) for k, v in firsts.items()):
                    sec = pool_map_safe(_calibrate, [(sid, sym)], 1, f"hiệu chỉnh {sid}")[0]
                    est["per_space"][sid] = round(sec, 3)
                    secs.append(sec)
                avg = sum(secs) / len(secs)
                est.update(sec_per_config=round(avg, 3), eta_s=round(total_configs * avg / workers, 1))
                print(f"[estimate] {total_configs:,} cấu hình sàng lọc × {avg:.2f} s/cấu hình / {workers} tiến trình "
                      f"≈ {_fmt_duration(total_configs * avg / workers)} (chưa gồm WFA/MC/holdout)", flush=True)
                with open(os.path.join(out_dir, "estimate.json"), "w", encoding="utf-8") as fh:
                    json.dump(est, fh, ensure_ascii=False, indent=1)
                progress.set_estimate(est)
                jobs = [(*pairs[i], args.n, args.seed, db_path, store_path) for i in pending]
                for k, r in pool_imap_bounded(_pair_job, iter(jobs), workers, "optimize_alphas", max_inflight=max(workers * 4, len(jobs))):
                    i = pending[k]
                    results[i] = r
                    if r.get("verdict") not in ("LOI", "LOI_WFA"):   # lỗi hạ tầng: không lưu -> --resume thử lại
                        store.put(pair_keys[pairs[i]], "pair", f"{pairs[i][0]}:{pairs[i][1]}", {"n": args.n, "seed": args.seed}, r, ord=i)
                        store.flush()   # nhả khoá ghi ngay: worker còn đang sàng lọc cùng ghi vào kho này (WAL, một người ghi mỗi lúc)
                    print(f"[{sum(x is not None for x in results)}/{len(pairs)}] {pairs[i][0]:26s} {pairs[i][1]:5s} -> {r['verdict']}", flush=True)
                    write_results()
            write_results()
            store.flush()
            progress.finish("done")
    finally:
        store.close()
    results = [r for r in results if r is not None]
    alphas = [r for r in results if r.get("verdict") == "ALPHA"]
    print(f"\nALPHA đạt mọi gate: {len(alphas)}/{len(results)}  (kết quả: {out_dir}/results.json)")
    for r in sorted(results, key=lambda r: (r["space"], r["symbol"])):
        h, wf, mc = r.get("holdout", {}), r.get("wfa", {}), r.get("mc", {})
        print(f"{r['space']:26s} {r['symbol']:5s} {r['verdict']:16s} sàng={r.get('screen', {}).get('passed')}/{r.get('configs_tried')} "
              f"WFA_oos={wf.get('total_oos_return_pct')}% gate={wf.get('acceptance_gate_passed')} "
              f"ruin={mc.get('risk_of_ruin_pct')}% holdout={h.get('return_pct')}% mdd={h.get('mdd_pct')}%")


def _file_sig(*rel_paths):
    """sha1 ngắn nội dung các file mã (thành phần của job_key cặp: đổi gate/MC/WFA thì kết quả cũ không dùng lại)."""
    import hashlib
    h = hashlib.sha1()
    for rel in rel_paths:
        try:
            with open(os.path.join(NORA_ROOT, rel), "rb") as fh:
                h.update(rel.encode() + b"\0" + fh.read())
        except OSError:
            h.update(rel.encode() + b"\0missing")
    return h.hexdigest()[:16]


if __name__ == "__main__":
    main()
