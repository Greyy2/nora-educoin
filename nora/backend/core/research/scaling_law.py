"""Scaling Law Analysis Module
Fits empirical log-log scaling laws on Directional Change metrics across theta thresholds:
1. Event Count Law: N(theta) ≈ C * theta^-E
2. Overshoot Law: <omega>(theta) ≈ C_os * theta^E_os
3. Duration Law: <T>(theta) ≈ C_t * theta^E_t
Measures scaling exponents, R^2 goodness of fit, and composite structural regularity score.
"""
from typing import Dict, List, Any
import numpy as np


def compute_r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Computes R-squared coefficient of determination."""
    if len(y_true) < 2:
        return 0.0
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    if ss_tot < 1e-9:
        return 1.0
    ss_res = np.sum((y_true - y_pred) ** 2)
    return float(np.clip(1.0 - ss_res / ss_tot, 0.0, 1.0))


def analyze_scaling_laws(theta_results: List[Dict[str, Any]], symbol: str = "") -> Dict[str, Any]:
    """
    Fits log-log linear regressions across the theta sweep results.
    Returns exponents, R^2 values, cross-theta stability, and scaling law score (0-100).
    """
    # Filter valid theta points with at least 3 events
    valid_pts = [r for r in theta_results if r.get("event_count", 0) >= 3 and r.get("theta", 0) > 0]

    if len(valid_pts) < 3:
        return {
            "symbol": symbol,
            "scaling_law_score": 35.0,
            "has_valid_scaling": False,
            "interpretation": "Không đủ điểm biến cố để xác lập quy luật Scaling Law",
            "event_count_law": {"exponent_E": 0.0, "r2": 0.0, "constant_C": 0.0},
            "overshoot_law": {"exponent": 0.0, "r2": 0.0},
            "duration_law": {"exponent": 0.0, "r2": 0.0},
            "cross_theta_stability": 30.0,
        }

    thetas = np.array([r["theta"] for r in valid_pts], dtype=np.float64)
    log_thetas = np.log(thetas)

    # 1. Event Count Scaling Law: ln(N) = ln(C) - E * ln(theta)
    event_counts = np.array([r["event_count"] for r in valid_pts], dtype=np.float64)
    log_events = np.log(event_counts)

    p_events = np.polyfit(log_thetas, log_events, 1)
    slope_events = float(p_events[0])
    intercept_events = float(p_events[1])
    e_exponent = float(-slope_events)  # Positive scaling exponent
    c_events = float(np.exp(intercept_events))
    pred_log_events = np.polyval(p_events, log_thetas)
    r2_events = compute_r2(log_events, pred_log_events)

    # 2. Overshoot Scaling Law: ln(<omega>) = ln(C_os) + E_os * ln(theta)
    omegas = np.array([max(1e-9, r.get("median_omega", 0.0)) for r in valid_pts], dtype=np.float64)
    log_omegas = np.log(omegas)
    p_os = np.polyfit(log_thetas, log_omegas, 1)
    e_os = float(p_os[0])
    pred_log_os = np.polyval(p_os, log_thetas)
    r2_os = compute_r2(log_omegas, pred_log_os)

    # 3. Duration Scaling Law: ln(duration_ms) = ln(C_t) + E_t * ln(theta)
    durations = np.array([max(100.0, r.get("duration_ms_median", 0.0)) for r in valid_pts], dtype=np.float64)
    log_durations = np.log(durations)
    p_dur = np.polyfit(log_thetas, log_durations, 1)
    e_dur = float(p_dur[0])
    pred_log_dur = np.polyval(p_dur, log_durations)
    r2_dur = compute_r2(log_durations, pred_log_dur)

    # 4. Cross-theta stability of Overshoot Ratio
    os_ratios = np.array([r.get("overshoot_ratio_median", 1.0) for r in valid_pts], dtype=np.float64)
    os_cv = float(np.std(os_ratios) / (np.mean(os_ratios) + 1e-9))
    cross_stability = float(np.clip(100.0 - os_cv * 100.0, 10.0, 95.0))

    # 5. Composite Scaling Law Score (0 - 100)
    # Higher score = robust, scale-invariant market structure
    score = (
        r2_events * 40.0
        + r2_os * 25.0
        + r2_dur * 15.0
        + (cross_stability / 100.0) * 20.0
    ) * 100.0 / 100.0

    score = round(float(np.clip(score, 10.0, 99.0)), 1)

    # Human-readable interpretation
    if r2_events >= 0.88 and score >= 75.0:
        interpretation = f"Cấu trúc vi mô tuân thủ quy luật bất biến hàm mũ vững chắc (E={e_exponent:.2f}, R²={r2_events:.2f})."
    elif r2_events >= 0.70:
        interpretation = f"Thị trường có xu hướng tuân thủ scaling law tương đối rõ (E={e_exponent:.2f}, R²={r2_events:.2f})."
    else:
        interpretation = f"Thị trường phân tán ngẫu nhiên, độ phù hợp scaling law yếu (R²={r2_events:.2f})."

    return {
        "symbol": symbol,
        "scaling_law_score": score,
        "has_valid_scaling": bool(r2_events >= 0.65),
        "interpretation": interpretation,
        "event_count_law": {
            "exponent_E": round(e_exponent, 3),
            "r2": round(r2_events, 3),
            "constant_C": round(c_events, 2),
        },
        "overshoot_law": {
            "exponent": round(e_os, 3),
            "r2": round(r2_os, 3),
        },
        "duration_law": {
            "exponent": round(e_dur, 3),
            "r2": round(r2_dur, 3),
        },
        "cross_theta_stability": round(cross_stability, 1),
    }
