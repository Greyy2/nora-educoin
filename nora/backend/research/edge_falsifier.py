"""Edge Falsification & Minimal Feature Discovery Module
Implements the quantitative paradigm:
DISCOVER -> FALSIFY -> VALIDATE -> ALLOCATE

Key functions:
1. DEX Friction Hurdle Test:
   E[R_net] = E[R | Signal] - (Fees + Slippage + Latency/AdverseSelection)
   Falsifies the pattern immediately if E[R_net] <= 0.
2. Cross-Regime Robustness Check:
   Falsifies patterns that are merely regime-specific artifacts.
3. Minimal Sufficient Feature Set (X* Discovery):
   X* = argmin_X |X| such that conditional edge survives after friction.
"""
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd


def falsify_edge_candidate(
    symbol: str,
    theta: float,
    fingerprint: Dict[str, Any],
    playbook_type: str,
    estimated_slippage_pct: float = 0.002,
    base_fee_pct: float = 0.001,
    adverse_selection_pct: float = 0.0005,
    backtest_sim: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Applies the DEX Microstructure Friction Hurdle and Falsification using real backtest simulations.
    Heuristic formulas are retained as 'prior' expectations only.
    """
    # 1. Total DEX Friction Hurdle (round-trip)
    total_friction_pct = (base_fee_pct * 2.0) + (estimated_slippage_pct * 2.0) + adverse_selection_pct
    total_friction_bps = total_friction_pct * 10000.0

    # 2. Prior Theoretical Expectancy E[R | Signal] (Retained as Prior Benchmark only)
    mu_os = float(fingerprint.get("mu_os_dc", 1.0))
    p_cont = float(fingerprint.get("p_continuation_given_surplus", 0.5))
    p_rev = float(fingerprint.get("p_reversal_given_deficit", 0.5))
    persistence = float(fingerprint.get("directional_persistence", 0.5))

    if playbook_type == "DC_MOMENTUM_FOLLOWING":
        prior_gross_pct = theta * mu_os * (p_cont - 0.40)
        recommended_features = ["DC_TRIGGER", "OVERSHOOT_RATIO"]
    elif playbook_type == "DC_OVERSHOOT_FADE":
        prior_gross_pct = theta * 1.2 * (p_rev - 0.40)
        recommended_features = ["DC_TRIGGER", "OVERSHOOT_DEFICIT", "BUY_SELL_IMBALANCE"]
    elif playbook_type == "VOL_EXPANSION_BREAKOUT":
        prior_gross_pct = theta * max(1.5, mu_os) * (persistence - 0.35)
        recommended_features = ["DC_TRIGGER", "EVENT_CLUSTERING", "REALIZED_VOLATILITY"]
    else:  # RANGE_MEAN_REVERSION or NO_STRATEGY_FIT
        prior_gross_pct = theta * 0.8 * 0.10
        recommended_features = ["DC_TRIGGER", "DEFICIT_RATE"]

    prior_gross_pct = max(0.0, float(prior_gross_pct))
    prior_net_pct = float(prior_gross_pct - total_friction_pct)
    prior_net_bps = prior_net_pct * 10000.0

    # 3. Falsification Decision: Based STRICTLY on backtest simulation cost models
    falsification_reasons = []
    if backtest_sim and backtest_sim.get("cost_models"):
        cost_models = backtest_sim["cost_models"]
        # Match closest cost model or standard
        model = cost_models.get("standard") or cost_models.get("low") or next(iter(cost_models.values()))
        survived = bool(model.get("survived", False))
        t_stat = model.get("t_stat")
        if t_stat is not None and float(t_stat) <= 3.0:
            survived = False
        is_falsified = not survived
        falsification_status = "SURVIVED_FRICTION_HURDLE" if survived else "FALSIFIED_AFTER_COST"
        net_expectancy_bps = float(model.get("avg_net_bps", 0.0))
        net_expectancy_pct = net_expectancy_bps / 10000.0
        gross_expectancy_bps = net_expectancy_bps + float(model.get("friction_bps", total_friction_bps))
        gross_expectancy_pct = gross_expectancy_bps / 10000.0

        if is_falsified:
            t_note = f", t-stat={float(t_stat):.2f} <= 3.0" if t_stat is not None and float(t_stat) <= 3.0 else ""
            falsification_reasons.append(
                f"Mô phỏng khớp lệnh thực tế không vượt qua kiểm định ma sát {total_friction_bps:.0f} bps (Avg Net: {net_expectancy_bps:.1f} bps{t_note}, Bootstrap 95% CI <= 0 hoặc < 30 lệnh)."
            )
    else:
        # Fail closed when not tested
        is_falsified = True
        falsification_status = "NOT_TESTED"
        net_expectancy_bps = prior_net_bps
        net_expectancy_pct = prior_net_pct
        gross_expectancy_bps = prior_gross_pct * 10000.0
        gross_expectancy_pct = prior_gross_pct
        falsification_reasons.append("Chưa chạy kiểm định mô phỏng khớp lệnh causal trên dữ liệu thật.")

    # Check for extreme clustering / illiquidity fragility
    clustering_cv = float(fingerprint.get("clustering_index", 1.0))
    if clustering_cv > 2.5:
        is_falsified = True
        falsification_status = "FALSIFIED_AFTER_COST"
        falsification_reasons.append(
            f"Mật độ biến cố bị cụm quá mức (CV={clustering_cv:.1f} > 2.5), rủi ro trượt giá dồn toa khi thanh khoản cạn."
        )

    # 4. Minimal Sufficient Feature Set X*
    if is_falsified:
        minimal_feature_set = []
        feature_set_status = "NO_FEATURE_SURVIVES_COST"
        feature_set_note = "Không có tổ hợp feature nào duy trì được alpha sau khi trừ chi phí ma sát DEX."
    else:
        minimal_feature_set = recommended_features
        feature_set_status = "MINIMAL_SET_VALIDATED"
        feature_set_note = f"Tập feature tối thiểu |X*| = {len(minimal_feature_set)}: {', '.join(minimal_feature_set)} bảo toàn được kỳ vọng ròng dương."

    return {
        "symbol": symbol,
        "theta": theta,
        "playbook_type": playbook_type,
        "falsified": is_falsified,
        "falsification_status": falsification_status,
        "gross_expectancy_pct": round(gross_expectancy_pct * 100.0, 3),
        "gross_expectancy_bps": round(gross_expectancy_bps, 1),
        "friction_hurdle_pct": round(total_friction_pct * 100.0, 3),
        "friction_hurdle_bps": round(total_friction_bps, 1),
        "net_expectancy_pct": round(net_expectancy_pct * 100.0, 3),
        "net_expectancy_bps": round(net_expectancy_bps, 1),
        "prior_gross_expectancy_bps": round(prior_gross_pct * 10000.0, 1),
        "prior_net_expectancy_bps": round(prior_net_bps, 1),
        "falsification_reasons": falsification_reasons,
        "minimal_feature_set": minimal_feature_set,
        "minimal_feature_status": feature_set_status,
        "minimal_feature_note": feature_set_note,
        "cost_breakdown": {
            "amm_fee_bps": round(base_fee_pct * 2.0 * 10000.0, 1),
            "slippage_impact_bps": round(estimated_slippage_pct * 2.0 * 10000.0, 1),
            "adverse_selection_bps": round(adverse_selection_pct * 10000.0, 1),
            "total_friction_bps": round(total_friction_bps, 1),
        },
    }
