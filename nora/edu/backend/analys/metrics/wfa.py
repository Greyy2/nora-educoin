# Nguồn: docs/bmad/p9_review_log.md (mục P9.5, P9.10b). Phần CHẠY engine (run_job, _pool_shared, plan_*_jobs, run_portfolio_wfa) nằm ở jobs/tasks.py (wfa nằm dưới optimize).
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
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from backend.analys.param import config_from_dict
from backend.carlo.carlo import (MC_MAX_RUIN_PCT, MC_MIN_SIMULATIONS, MC_RUIN_THRESHOLD_PCT, STRESS_MAX_MDD_PCT,
                                 evaluate_mc_gate, extra_cost_from_turnover, merge_exposure, merge_turnover,
                                 run_monte_carlo_daily_gate)


# ── Gate chấp nhận (không nới để có kết quả đẹp) ────────────────────────────
MIN_FOLDS = 5                      # tối thiểu số fold
MIN_AVG_IS_RET_PCT = 0.0           # lãi IS trung bình các fold >= 0 (lỗ ngay trên dữ liệu chọn tham số thì OOS dương chỉ là may)
MIN_TRADED_FOLDS = 3               # tối thiểu số fold có lệnh (fold NO_TRADE trung tính)
MIN_FOLD_T = 1.0                   # t-stat lãi TB/fold OOS (extreme, fold có lệnh) >= 1 — thay "tỉ lệ fold lãi >= 60%" (lãi lệch phải;
                                   # wfa/wfa.fold_stats, cùng cổng với phễu S3)
MIN_EX_BEST_FOLD_PCT = -2.0        # bỏ fold OOS tốt nhất, lãi kép (extreme) còn lại >= -2%
MAX_FOLD_MDD_PCT = 30.0            # MDD tệ nhất của một fold OOS (extreme) <= 30%
MIN_COMPOUNDED_OOS_PCT = 0.0       # lãi kép OOS (extreme) >= 0
# Monte Carlo (hằng số gốc ở backend/carlo/carlo.py, dùng chung mọi gate): >= 10.000 bootstrap, P(MDD >= 30% trong 1 năm) <= 5%,
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
        return config_from_dict(cls, d)


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
    turnover = merge_turnover([f.get("turnover") for f in folds])           # vòng quay đo từ lệnh của mọi fold OOS (extreme)
    shock = merge_exposure([f.get("shock") for f in folds])   # vị thế ngược chiều lớn nhất của mọi fold OOS (extreme)
    if len(daily["extreme"]) >= MIN_MC_DAYS:
        mc = run_monte_carlo_daily_gate(daily["extreme"], simulations=cfg.mc_simulations, block_days=cfg.mc_block_days,
                                        horizon_days=cfg.mc_horizon_days, ruin_threshold_pct=MC_RUIN_THRESHOLD_PCT,
                                        seed=cfg.mc_seed, max_ruin_pct=MAX_MC_RUIN_PCT, stress_max_mdd_pct=STRESS_MAX_MDD_PCT, shock=shock,
                                        extra_cost_daily=extra_cost_from_turnover(turnover["turnover_daily"]))
    fs = fold_stats([f["oos_extreme"]["ret_pct"] if f["oos_extreme"] else 0.0 for f in folds],
                    [f["status"] == "TRADED" and (f["oos_extreme"] or {}).get("trades", 0) > 0 for f in folds])
    return {
        "n_folds": n, "n_traded_folds": len(traded), "positive_folds": positive,
        "positive_ratio_pct": round(positive / n * 100, 1) if n else 0.0,
        "fold_t": fs["fold_t"], "oos_ex_best_pct": fs["oos_ex_best_pct"], "n_active_folds": fs["traded_folds"],
        "avg_is_ret_pct": avg_is, "compounded_oos_ret_pct": compounded, "worst_fold_mdd_pct": worst_mdd,
        "oos_days": len(daily["extreme"]), "oos_trades": {sf: sum(f["trades"][sf] for f in folds) for sf in ("level", "extreme")},
        "param_stability": stability, "oos_daily": daily, "mc": mc, "shock": shock,
        "turnover_daily": turnover["turnover_daily"], "turnover_note": turnover["note"],
        **({"oos_daily_dates": dates} if dates is not None else {}),   # song song với oos_daily (UI vẽ đường vốn OOS)
    }


def evaluate_gate(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Gate chấp nhận: mọi check phải qua. Trả {"passed", "checks": {tên: {label, required, actual, passed}}}."""
    n, avg_is = summary["n_folds"], summary["avg_is_ret_pct"]
    ft, exb, act = summary.get("fold_t", 0.0), summary.get("oos_ex_best_pct", 0.0), summary.get("n_active_folds", n)
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
        "active_folds": _check("Số fold OOS có lệnh", f">= {MIN_TRADED_FOLDS}", act, act >= MIN_TRADED_FOLDS),
        "fold_t": _check("t-stat lãi theo fold OOS (extreme)", f">= {MIN_FOLD_T}", ft, ft >= MIN_FOLD_T),
        "ex_best_fold": _check("Lãi kép OOS khi bỏ fold tốt nhất (extreme)", f">= {MIN_EX_BEST_FOLD_PCT}%", exb, exb >= MIN_EX_BEST_FOLD_PCT),
        "worst_fold_mdd": _check("MDD tệ nhất một fold OOS (extreme)", f"<= {MAX_FOLD_MDD_PCT}%", worst, worst <= MAX_FOLD_MDD_PCT),
        "compounded_oos": _check("Lãi kép OOS (extreme)", f">= {MIN_COMPOUNDED_OOS_PCT}%", comp, comp >= MIN_COMPOUNDED_OOS_PCT),
        "mc_ruin": _check(f"Monte Carlo P(MDD >= {MC_RUIN_THRESHOLD_PCT:.0f}%) trong 1 năm", f"<= {MAX_MC_RUIN_PCT}%", ruin,
                          ruin is not None and ruin <= MAX_MC_RUIN_PCT),
        # Monte Carlo cực xấu: đủ số kịch bản + kịch bản tất định không vượt MDD cho phép / không cháy vốn (nhãn/required từ evaluate_mc_gate)
        "mc_simulations": mg["simulations"],
        "mc_stress_mdd": mg["stress_mdd"],
        "mc_stress_ruin": mg["stress_ruin"],
        "mc_stress_measured": mg["stress_measured"],
    }
    return {"passed": all(c["passed"] for c in checks.values()), "checks": checks}


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


# ══════════════════════════════════════════════════════════════════════════
# Kiểm chứng chéo / ổn định tham số: PBO-CSCV, căn chuỗi ngày, lân cận.
#
# - PBO: Bailey, Borwein, López de Prado, Zhu (2017) — CSCV: chia T ngày thành S khối liền kề, mọi C(S, S/2) cách chọn nửa IS;
#   alpha tốt nhất IS có hạng OOS tương đối ω; logit = ln(ω / (1 - ω)); PBO = P(logit <= 0).
# - Lân cận: ±1 bước trên lưới của TỪNG khoá của không gian tham số (khoá chỉ có 1 giá trị thì không có lân cận).
# ══════════════════════════════════════════════════════════════════════════
from typing import Sequence


# ══════════════════════════════════════════════════════════════════════════
# fold_stats = thống kê cổng WFA (quy tắc: metrics/ chỉ tính thuần, không cổng/kiểm định)
# ══════════════════════════════════════════════════════════════════════════
import math


def fold_stats(fold_rets_pct: Sequence[float], traded: Sequence[bool]) -> Dict[str, Any]:
    """Thống kê lãi OOS theo fold cho cổng WFA (phễu S3 + WFA danh mục). Không dùng "tỉ lệ fold lãi" làm cổng vì lãi của chiến lược theo xu
    hướng lệch phải (đa số tháng lỗ nhẹ, vài tháng lãi lớn): đo trên 360 alpha, 124/145 alpha có lãi OOS bị loại chỉ vì < 60% fold lãi
    (test/scripts/research_funnel_diagnosis.py). Fold KHÔNG có lệnh là trung tính: không vào tỉ lệ / t-stat.
    -> traded_folds, positive_ratio (trên fold có lệnh), fold_t (t-stat lãi TB/fold trên fold có lệnh; < 2 fold hoặc độ lệch 0 -> 0),
       oos_ex_best_pct (lãi kép OOS sau khi bỏ fold tốt nhất — lãi không được dựa vào một fold may mắn)."""
    x = np.asarray([float(r) for r, t in zip(fold_rets_pct, traded) if t], dtype=float)
    allx = np.asarray([float(r) for r in fold_rets_pct], dtype=float)
    n = len(x)
    sd = float(x.std(ddof=1)) if n > 1 else 0.0
    t = float(x.mean() / (sd / math.sqrt(n))) if n > 1 and sd > 0 else 0.0
    ex = np.delete(allx, int(allx.argmax())) if len(allx) else allx
    return {"traded_folds": n, "positive_ratio": float((x > 0).mean()) if n else 0.0, "fold_t": round(t, 4),
            "oos_ex_best_pct": round(float((np.prod(1.0 + ex / 100.0) - 1.0) * 100.0), 4) if len(allx) else 0.0}
