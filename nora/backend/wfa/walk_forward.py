"""Walk-Forward Analysis cho SỔ CHIẾN LƯỢC (danh mục nhiều tài sản, MỘT sổ vốn) + Monte Carlo trên lợi suất ngày MTM.

Khác WFA đơn tài sản (wfa.py): chọn tham số theo CHIẾN LƯỢC (dùng chung cả vũ trụ), OOS chạy CẢ sổ cùng nhau với
giới hạn danh mục (RiskConfig, kill switch BẬT) nên phản ánh đúng cạnh tranh vốn giữa các chiến lược.

Mỗi fold (generate_folds, OOS không chồng lấp, test đầu = start + train):
  IS  — mỗi chiến lược × mỗi cấu hình ứng viên chạy RIÊNG một PortfolioEngine trên cửa sổ train (kill switch tắt, SL "level");
        điểm = lãi / max(MDD, 1), cần >= min_is_trades lệnh; chọn cấu hình điểm cao nhất (hoà -> cấu hình đứng trước).
  OOS — MỘT PortfolioEngine với MỌI chiến lược dùng cấu hình đã chọn, trên cửa sổ test (kill switch BẬT, trade_start = đầu test,
        warmup 20 ngày), chạy với SL "level" VÀ "extreme"; "extreme" (khớp bi quan) là cơ sở kết luận.
KHÔNG nhìn trước: chọn cấu hình chỉ dùng kết quả IS (cửa sổ IS kết thúc <= đầu test); các cửa sổ OOS không chồng nhau.

Sau cùng: nối lợi suất ngày OOS (extreme) của mọi fold -> Monte Carlo block bootstrap 1 năm (đường vốn ngày đã gồm lỗ treo).
Chạy song song: MỌI job IS của MỌI fold trong một pool, rồi MỌI job OOS trong một pool; trước mỗi pool tiến trình cha
dựng dữ liệu dùng chung (mmap) cho từng (cửa sổ, refs) và xoá sau khi pool thành công.
"""
import gc
import json
import os
import shutil
import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.core.metrics.portfolio import portfolio_metrics
from backend.utils.parallel import pool_map_safe

from ..carlo.monte_carlo import (MC_MAX_RUIN_PCT, MC_MIN_SIMULATIONS, MC_RUIN_THRESHOLD_PCT, STRESS_MAX_MDD_PCT,
                                 evaluate_mc_gate, run_monte_carlo_daily_gate)

DAY = 86_400_000
WARMUP = 20 * DAY                  # nạp thêm trước đầu cửa sổ để kernel đủ dữ liệu (như build_strategy_book)

# ── Gate chấp nhận (không nới để có kết quả đẹp) ────────────────────────────
MIN_FOLDS = 5                      # tối thiểu số fold
MIN_AVG_IS_RET_PCT = 0.0           # lãi IS trung bình các fold >= 0 (lỗ ngay trên dữ liệu chọn tham số thì OOS dương chỉ là may)
MIN_POSITIVE_FOLD_RATIO = 0.60     # >= 60% fold OOS có lãi (extreme)
MAX_FOLD_MDD_PCT = 30.0            # MDD tệ nhất của một fold OOS (extreme) <= 30%
MIN_COMPOUNDED_OOS_PCT = 0.0       # lãi kép OOS (extreme) >= 0
# Monte Carlo (hằng số gốc ở backend/carlo/monte_carlo.py, dùng chung mọi gate): >= 10.000 bootstrap, P(MDD >= 30% trong 1 năm) <= 5%,
# và MỌI kịch bản cực xấu tất định (+ đường bootstrap tệ nhất) có MDD < STRESS_MAX_MDD_PCT, không cháy vốn.
MAX_MC_RUIN_PCT = MC_MAX_RUIN_PCT
MIN_MC_DAYS = 20                   # ít hơn ngần này ngày OOS thì không đủ để bootstrap -> check MC trượt


@dataclass
class PortfolioWfaConfig:
    train_days: int = 120
    test_days: int = 30
    step_days: Optional[int] = None    # None = test_days (OOS liền nhau, không chồng)
    min_is_trades: int = 10            # cấu hình có ít lệnh IS hơn bị loại khỏi việc chọn
    mc_simulations: int = MC_MIN_SIMULATIONS   # < MC_MIN_SIMULATIONS: chạy được nhưng gate trượt (check mc_simulations)
    mc_block_days: int = 5
    mc_horizon_days: int = 365
    mc_seed: int = 1

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "PortfolioWfaConfig":
        d = dict(d or {})
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


# Seam cho test: thay bằng bản chạy tuần tự trong tiến trình để ghi lại job.
_pool_map = pool_map_safe


# ── Job & worker ────────────────────────────────────────────────────────────
def _make_engine(job):
    """job = (strategies [(candidate_id, params)], (start, end), stop_fill, risk dict, risk_per_trade, symbols, shared_dir)."""
    from backend.core.strategy.book import CANDIDATES, materialize
    from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
    items, (start, end), stop_fill, risk, rpt, symbols, shared_dir = job
    by_id = {c["id"]: c for c in CANDIDATES}
    strategies = [materialize(by_id[cid], prm, stop_fill=stop_fill, risk_per_trade_pct=rpt) for cid, prm in items]
    return PortfolioEngine(symbols, strategies, start - WARMUP, end, trade_start_ts=start,
                           risk=RiskConfig.from_dict(risk), shared_dir=shared_dir), start


def run_job(job):
    import contextlib
    import io
    from backend.utils.memwatch import peak_rss_mb, rss_anon_mb
    eng, start = _make_engine(job)
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    res = eng.get_results()
    result = portfolio_metrics(res, start)
    # Ngày UTC đầu của chuỗi lợi suất ngày (mẫu vốn đầu tiên >= start) -> dựng nhãn ngày cho đường vốn OOS
    first = next((c["time"] for c in res["equity_curve"] if c["time"] >= start), None)
    result["_daily_start"] = _date(first) if first is not None else None
    result["_peak_rss_mb"] = round(peak_rss_mb(), 1)
    result["_rss_anon_mb"] = round(rss_anon_mb(), 1)
    return result


def _export_shared(jobs, shared_dir, label):
    """Cha dựng MỘT lần dữ liệu cho mọi (tài sản, cửa sổ, refs) của các job vào shared_dir. Trả các khoá đã dùng."""
    import ctypes
    from backend.core.data import shared as shared_data
    from backend.core.backtest.portfolio import data_cache_clear
    from backend.core.data.loader import CandleLoader
    t = time.time()
    keys, written = set(), 0
    for job in jobs:
        eng, _ = _make_engine(job)
        info = shared_data.export(eng, shared_dir)
        keys.update(info["keys"].values())
        written += len(info["written"])
    CandleLoader.clear_cache()
    data_cache_clear()
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:
        pass
    print(f"[shared] {label}: {written} bộ mới, {len(keys)} bộ ({time.time() - t:.0f}s)", flush=True)
    return keys


def _pool_shared(jobs, workers, label, shared_dir, store=None, stage=None, progress=None):
    """Export dữ liệu dùng chung -> pool -> xoá các bộ của pool này (lỗi thì ngoại lệ bay lên, giữ nguyên để gỡ lỗi).
    store (ResultsStore, tuỳ chọn): mỗi kết quả ghi ngay khi xong; job đã có trong kho (cùng job_key) bỏ qua -> `--resume`.
    stage "wfa_is": bỏ chuỗi `daily` (chọn cấu hình IS không cần) để RAM/kho gọn. Kết quả luôn đúng thứ tự jobs."""
    if store is None and progress is None:
        keys = _export_shared(jobs, shared_dir, label)
        res = _pool_map(run_job, jobs, workers, label)
        for k in keys:
            shutil.rmtree(os.path.join(shared_dir, k), ignore_errors=True)
        return res
    from backend.optimize.store import data_fingerprint, make_job_key
    from backend.optimize.store import normalize
    stage = stage or "wfa"
    results: List[Any] = [None] * len(jobs)
    keys_of: List[Optional[str]] = [None] * len(jobs)
    missing = []
    fp = data_fingerprint(jobs[0][5]) if (store is not None and jobs) else None
    for i, job in enumerate(jobs):
        if store is not None:
            items, window, stop_fill, risk, rpt, symbols, _shared = job
            keys_of[i] = make_job_key(stage, "-", [[c, p] for c, p in items], list(window), stop_fill, risk, fp,
                                      extra={"rpt": rpt, "symbols": list(symbols)})
            row = store.get(keys_of[i])
            if row is not None:
                results[i] = row["metrics"]
                if progress is not None:
                    progress.tick(resumed=True)
                continue
        missing.append(i)
    if missing:
        sub = [jobs[i] for i in missing]
        exp_keys = _export_shared(sub, shared_dir, label)

        def _done(j, res):
            i = missing[j]
            m = normalize(res)
            if stage == "wfa_is":
                m.pop("daily", None)
            results[i] = m
            if store is not None:
                store.put(keys_of[i], stage, "-", [[c, p] for c, p in jobs[i][0]], m, ord=i)
            if progress is not None:
                progress.tick(worker_peak_mb=m.get("_peak_rss_mb"))
        _pool_map(run_job, sub, workers, label, on_done=_done)
        for k in exp_keys:
            shutil.rmtree(os.path.join(shared_dir, k), ignore_errors=True)
    return results


def _strip(m):
    return {k: v for k, v in m.items() if k not in ("daily", "_peak_rss_mb", "_rss_anon_mb", "_daily_start")}


def _date(ts) -> str:
    return f"{pd.Timestamp(int(ts), unit='ms'):%Y-%m-%d}"


# ── Chọn cấu hình ở IS (thuần, test được) ───────────────────────────────────
def is_score(m: Dict[str, Any], min_trades: int) -> Optional[float]:
    """Điểm IS = lãi / max(MDD, 1); None nếu không đủ lệnh."""
    if m["trades"] < min_trades:
        return None
    return m["ret_pct"] / max(m["mdd_pct"], 1.0)


def select_best(rows: List[Dict[str, Any]], min_trades: int) -> Optional[int]:
    """Chỉ số cấu hình điểm cao nhất (so sánh ngặt '>' nên hoà -> cấu hình đứng trước); None nếu không cấu hình nào đủ lệnh."""
    best_i, best = None, None
    for i, m in enumerate(rows):
        sc = is_score(m, min_trades)
        if sc is not None and (best is None or sc > best):
            best_i, best = i, sc
    return best_i


def plan_is_jobs(candidates, folds, symbols, risk, rpt, shared_dir):
    """Danh sách (khoá, job) IS: khoá = (fold, candidate_id, chỉ số cấu hình). Cửa sổ IS = [train_start, train_end]."""
    is_risk = {**risk, "kill_switch_dd_pct": 0}
    keys, jobs = [], []
    for fi, fold in enumerate(folds):
        for cand in candidates:
            for ci, cfg_params in enumerate(cand["configs"]):
                keys.append((fi, cand["id"], ci))
                jobs.append(([(cand["id"], cfg_params)], (fold["train_start_ts"], fold["train_end_ts"]), "level", is_risk,
                             rpt, symbols, shared_dir))
    return keys, jobs


def plan_oos_jobs(chosen, folds, symbols, risk, rpt, shared_dir):
    """chosen[fold] = [(candidate_id, params)] (rỗng -> fold NO_TRADE, không chạy). Khoá = (fold, stop_fill)."""
    keys, jobs = [], []
    for fi, fold in enumerate(folds):
        if not chosen[fi]:
            continue
        for sf in ("level", "extreme"):
            keys.append((fi, sf))
            jobs.append((chosen[fi], (fold["test_start_ts"], fold["test_end_ts"]), sf, risk, rpt, symbols, shared_dir))
    return keys, jobs


# ── Tổng hợp + gate (thuần, test được) ──────────────────────────────────────
def _check(label, required, actual, passed):
    return {"label": label, "required": required, "actual": actual, "passed": bool(passed)}


def aggregate_folds(folds: List[Dict[str, Any]], cfg: PortfolioWfaConfig) -> Dict[str, Any]:
    """Từ danh sách fold (đã có oos_level/oos_extreme/oos_daily_*/is_ret_pct/chosen_idx) -> số liệu tổng + Monte Carlo."""
    n = len(folds)
    traded = [f for f in folds if f["status"] == "TRADED"]
    daily = {sf: [x for f in folds for x in f[f"oos_daily_{sf}"]] for sf in ("level", "extreme")}
    compounded = {sf: round((float(np.prod(1.0 + np.asarray(daily[sf], dtype=float))) - 1.0) * 100, 2) for sf in daily}
    worst_mdd = {sf: max([f[f"oos_{sf}"]["mdd_pct"] for f in traded], default=0.0) for sf in ("level", "extreme")}
    positive = sum(1 for f in traded if f["oos_extreme"]["ret_pct"] > 0)
    avg_is = round(sum(f["is_ret_pct"] for f in traded) / len(traded), 2) if traded else None
    stability: Dict[str, Any] = {}
    for cid in sorted({c for f in folds for c in f["chosen_idx"]}):
        picks = [json.dumps(f["chosen"][cid], sort_keys=True) for f in folds if f["chosen_idx"].get(cid) is not None]
        if picks:
            top = Counter(picks).most_common(1)[0][1]
            stability[cid] = {"share": round(top / len(picks), 4), "folds_chosen": len(picks), "distinct": len(set(picks))}
    dates = None
    if all(f.get(f"oos_daily_dates_{sf}") is not None for f in folds for sf in ("level", "extreme")):
        dates = {sf: [d for f in folds for d in f[f"oos_daily_dates_{sf}"]] for sf in ("level", "extreme")}
    mc = None
    if len(daily["extreme"]) >= MIN_MC_DAYS:
        mc = run_monte_carlo_daily_gate(daily["extreme"], simulations=cfg.mc_simulations, block_days=cfg.mc_block_days,
                                        horizon_days=cfg.mc_horizon_days, ruin_threshold_pct=MC_RUIN_THRESHOLD_PCT,
                                        seed=cfg.mc_seed, max_ruin_pct=MAX_MC_RUIN_PCT, stress_max_mdd_pct=STRESS_MAX_MDD_PCT)
    return {
        "n_folds": n, "n_traded_folds": len(traded), "positive_folds": positive,
        "positive_ratio_pct": round(positive / n * 100, 1) if n else 0.0,
        "avg_is_ret_pct": avg_is, "compounded_oos_ret_pct": compounded, "worst_fold_mdd_pct": worst_mdd,
        "oos_days": len(daily["extreme"]), "oos_trades": {sf: sum(f["trades"][sf] for f in folds) for sf in ("level", "extreme")},
        "param_stability": stability, "oos_daily": daily, "mc": mc,
        **({"oos_daily_dates": dates} if dates is not None else {}),   # song song với oos_daily (UI vẽ đường vốn OOS)
    }


def evaluate_gate(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Gate chấp nhận: mọi check phải qua. Trả {"passed", "checks": {tên: {label, required, actual, passed}}}."""
    n, avg_is = summary["n_folds"], summary["avg_is_ret_pct"]
    pos = summary["positive_ratio_pct"]
    worst = summary["worst_fold_mdd_pct"]["extreme"]
    comp = summary["compounded_oos_ret_pct"]["extreme"]
    mc = summary["mc"]
    ruin = mc["p_mdd_ge_ruin_pct"] if mc else None
    mg = evaluate_mc_gate(mc.get("simulations", 0) if mc else 0, ruin, mc.get("stress") if mc else None,
                          max_ruin_pct=MAX_MC_RUIN_PCT, ruin_threshold_pct=MC_RUIN_THRESHOLD_PCT, stress_max_mdd_pct=STRESS_MAX_MDD_PCT)["checks"]
    checks = {
        "folds": _check("Số fold", f">= {MIN_FOLDS}", n, n >= MIN_FOLDS),
        "avg_is_return": _check("Lãi IS trung bình các fold", f">= {MIN_AVG_IS_RET_PCT}%", avg_is,
                                avg_is is not None and avg_is >= MIN_AVG_IS_RET_PCT),
        "positive_folds": _check("Tỉ lệ fold OOS có lãi (extreme)", f">= {MIN_POSITIVE_FOLD_RATIO * 100:.0f}%", pos,
                                 n > 0 and pos >= MIN_POSITIVE_FOLD_RATIO * 100),
        "worst_fold_mdd": _check("MDD tệ nhất một fold OOS (extreme)", f"<= {MAX_FOLD_MDD_PCT}%", worst, worst <= MAX_FOLD_MDD_PCT),
        "compounded_oos": _check("Lãi kép OOS (extreme)", f">= {MIN_COMPOUNDED_OOS_PCT}%", comp, comp >= MIN_COMPOUNDED_OOS_PCT),
        "mc_ruin": _check(f"Monte Carlo P(MDD >= {MC_RUIN_THRESHOLD_PCT:.0f}%) trong 1 năm", f"<= {MAX_MC_RUIN_PCT}%", ruin,
                          ruin is not None and ruin <= MAX_MC_RUIN_PCT),
        # Monte Carlo cực xấu: đủ số kịch bản + kịch bản tất định không vượt MDD cho phép / không cháy vốn (nhãn/required từ evaluate_mc_gate)
        "mc_simulations": mg["simulations"],
        "mc_stress_mdd": mg["stress_mdd"],
        "mc_stress_ruin": mg["stress_ruin"],
    }
    return {"passed": all(c["passed"] for c in checks.values()), "checks": checks}


# ── Chạy ────────────────────────────────────────────────────────────────────
def run_portfolio_wfa(candidates, symbols, start_ts, end_ts, cfg, risk, risk_per_trade_pct, workers, shared_root,
                      store=None, progress=None) -> Dict[str, Any]:
    """candidates = [{"id": candidate_id, "configs": [params...]}]; cfg: PortfolioWfaConfig hoặc dict.
    risk: dict RiskConfig dùng cho OOS (kill switch BẬT); IS tự tắt kill switch. Trả dict kết quả (xem aggregate_folds).
    store/progress (tuỳ chọn, backend/optimize): ghi từng kết quả job vào kho + bỏ qua job đã có (--resume) + tiến độ."""
    cfg = cfg if isinstance(cfg, PortfolioWfaConfig) else PortfolioWfaConfig.from_dict(cfg)
    symbols, rpt = list(symbols), float(risk_per_trade_pct)
    folds = generate_folds(int(start_ts), int(end_ts), cfg.train_days, cfg.test_days, cfg.step_days)
    if not folds:
        raise ValueError("Khoảng thời gian không đủ để tạo ít nhất 1 fold")
    os.makedirs(shared_root, exist_ok=True)
    t0 = time.time()

    # IS: MỌI fold × chiến lược × cấu hình trong MỘT pool
    is_keys, is_jobs = plan_is_jobs(candidates, folds, symbols, risk, rpt, shared_root)
    if progress is not None:
        progress.start_stage("WFA-IS", len(is_jobs))
    is_res = _pool_shared(is_jobs, workers, f"[WFA-IS] {len(folds)} fold × {len(is_jobs) // len(folds)} job", shared_root,
                          store, "wfa_is", progress)
    is_by = {k: m for k, m in zip(is_keys, is_res)}
    print(f"[WFA-IS] {len(is_jobs)} job IS xong ({time.time() - t0:.0f}s)", flush=True)

    # Chọn cấu hình theo IS (chỉ dùng kết quả IS)
    chosen: List[List[Tuple[str, Dict[str, Any]]]] = []
    picks: List[Dict[str, Optional[int]]] = []
    for fi in range(len(folds)):
        pick, items = {}, []
        for cand in candidates:
            rows = [is_by[(fi, cand["id"], ci)] for ci in range(len(cand["configs"]))]
            best = select_best(rows, cfg.min_is_trades)
            pick[cand["id"]] = best
            if best is not None:
                items.append((cand["id"], cand["configs"][best]))
        chosen.append(items)
        picks.append(pick)

    # OOS: MỌI fold × {level, extreme} trong MỘT pool
    oos_keys, oos_jobs = plan_oos_jobs(chosen, folds, symbols, risk, rpt, shared_root)
    if progress is not None:
        progress.start_stage("WFA-OOS", len(oos_jobs))
    oos_res = _pool_shared(oos_jobs, workers, f"[WFA-OOS] {len(oos_jobs)} job", shared_root, store, "wfa_oos", progress) if oos_jobs else []
    oos_by = {k: m for k, m in zip(oos_keys, oos_res)}
    print(f"[WFA-OOS] {len(oos_jobs)} job OOS xong ({time.time() - t0:.0f}s)", flush=True)

    fold_records = []
    for fi, fold in enumerate(folds):
        cids = [c["id"] for c in candidates]
        is_sel = {cid: _strip(is_by[(fi, cid, picks[fi][cid])]) | {"score": round(is_score(is_by[(fi, cid, picks[fi][cid])],
                                                                                          cfg.min_is_trades), 4)}
                  for cid in cids if picks[fi][cid] is not None}
        rec = {
            "fold": fi + 1,
            "train": [_date(fold["train_start_ts"]), _date(fold["train_end_ts"])],
            "test": [_date(fold["test_start_ts"]), _date(fold["test_end_ts"])],
            "train_ts": [fold["train_start_ts"], fold["train_end_ts"]], "test_ts": [fold["test_start_ts"], fold["test_end_ts"]],
            "status": "TRADED" if chosen[fi] else "NO_TRADE",
            "chosen_idx": picks[fi],
            "chosen": {cid: (candidates[i]["configs"][picks[fi][cid]] if picks[fi][cid] is not None else None)
                       for i, cid in enumerate(cids)},
            "is": is_sel,
            "is_ret_pct": round(sum(m["ret_pct"] for m in is_sel.values()) / len(is_sel), 2) if is_sel else 0.0,
            "is_candidates": {cid: [{"ret_pct": m["ret_pct"], "mdd_pct": m["mdd_pct"], "trades": m["trades"],
                                     "score": is_score(m, cfg.min_is_trades)}
                                    for m in (is_by[(fi, cid, ci)] for ci in range(len(candidates[i]["configs"])))]
                              for i, cid in enumerate(cids)},
        }
        for sf in ("level", "extreme"):
            m = oos_by.get((fi, sf))
            rec[f"oos_{sf}"] = _strip(m) if m else None
            rec[f"oos_daily_{sf}"] = list(m["daily"]) if m else [0.0] * cfg.test_days   # NO_TRADE: vốn đứng yên
            first = (m or {}).get("_daily_start") or _date(fold["test_start_ts"])
            rec[f"oos_daily_dates_{sf}"] = [f"{d:%Y-%m-%d}" for d in pd.date_range(first, periods=len(rec[f"oos_daily_{sf}"]), freq="D")]
        rec["trades"] = {sf: (rec[f"oos_{sf}"]["trades"] if rec[f"oos_{sf}"] else 0) for sf in ("level", "extreme")}
        rec["halted_at"] = {sf: (rec[f"oos_{sf}"]["halted_at"] if rec[f"oos_{sf}"] else None) for sf in ("level", "extreme")}
        fold_records.append(rec)

    summary = aggregate_folds(fold_records, cfg)
    gate = evaluate_gate(summary)
    all_res = [m for m in list(is_res) + list(oos_res) if m]
    return {
        "config": asdict(cfg), "risk": risk, "risk_per_trade_pct": rpt, "symbols": symbols,
        "window": [_date(start_ts), _date(end_ts)], "candidates": [{"id": c["id"], "configs": c["configs"]} for c in candidates],
        "folds": fold_records, "summary": summary, "gate": gate,
        "aggregate": summary, "mc": summary["mc"],   # tên theo docs/ui_contract.md §4 (cùng đối tượng với summary / summary.mc)
        "mem": {"peak_rss_mb": max([m["_peak_rss_mb"] for m in all_res], default=0.0),
                "rss_anon_mb": max([m["_rss_anon_mb"] for m in all_res], default=0.0)},
    }


def generate_folds(
    start_ts: int,
    end_ts: int,
    train_days: int = 30,
    test_days: int = 10,
    step_days: Optional[int] = None,
    embargo_days: int = 0,
    anchored: bool = False,
    **kwargs,
) -> List[Dict[str, int]]:
    """
    Sinh các cửa sổ fold theo ngày, đảm bảo OOS không chồng lấp (Phase 3.1).
    Nếu step_days < test_days, raise ValueError để ngăn chặn OOS chồng lấp.
    """
    D = 86_400_000
    step = (step_days or test_days) * D
    if step < test_days * D:
        raise ValueError(f"step ({step // D}d) < test ({test_days}d) -> OOS chồng lấp! Không được phép.")

    folds = []
    test_start = start_ts + (train_days + embargo_days) * D
    while test_start + test_days * D <= end_ts:
        train_end = test_start - embargo_days * D
        train_start = start_ts if anchored else train_end - train_days * D
        folds.append({
            "train_start_ts": int(train_start),
            "train_end_ts": int(train_end),
            "test_start_ts": int(test_start),
            "test_end_ts": int(test_start + test_days * D),
        })
        test_start += step
    return folds
