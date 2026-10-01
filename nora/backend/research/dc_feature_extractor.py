"""Directional Change Feature Extractor Module
Extracts intrinsic time Directional Change (DC) metrics across multiple theta thresholds.
Discovers optimal theta (theta*) based on structural quality and cost resilience,
without fabricating backtest PnL.
"""
from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd

try:
    from backend.alpha.directional_change import DirectionalChangeEngine
except ImportError:
    from nora.backend.alpha.directional_change import DirectionalChangeEngine


DEFAULT_THETA_GRID = [0.005, 0.01, 0.015, 0.02, 0.03, 0.05]


def sweep_directional_change(
    df_ticks: pd.DataFrame,
    symbol: str,
    theta_grid: Optional[List[float]] = None,
    estimated_cost_pct: float = 0.003,  # 0.3% default DEX cost
) -> Dict[str, Any]:
    """
    Executes a multi-theta sweep over tick stream data.
    Computes intrinsic time metrics, scaling indicators, and selects the optimal theta*.
    """
    if df_ticks.empty or len(df_ticks) < 30:
        return {
            "symbol": symbol,
            "best_theta": None,
            "best_theta_pct": None,
            "best_metrics": {},
            "theta_results": [],
            "total_ticks": len(df_ticks),
            "time_span_days": 0.0,
            "has_sufficient_events": False,
            "split_ts": None,
        }

    thetas = theta_grid or DEFAULT_THETA_GRID
    total_ticks = len(df_ticks)

    # Time span in days
    t_min = float(df_ticks["timestamp_ms"].min())
    t_max = float(df_ticks["timestamp_ms"].max())
    time_span_days = max(0.01, (t_max - t_min) / (1000.0 * 86400.0))

    # Phase 5.2: 60/40 train/test split to prevent selection bias
    split_ts = None
    if total_ticks >= 100:
        split_idx = int(total_ticks * 0.6)
        df_train = df_ticks.iloc[:split_idx].reset_index(drop=True)
        df_test = df_ticks.iloc[split_idx:].reset_index(drop=True)
        if "timestamp_ms" in df_test.columns and not df_test.empty:
            split_ts = int(df_test["timestamp_ms"].iloc[0])
    else:
        # Quá ít điểm để tách train/test độc lập -> không được chọn theta (tránh
        # chọn và đánh giá trên cùng một dữ liệu). Vẫn tính theta_results để hiển thị.
        df_train = df_ticks
        df_test = df_ticks

    # Step 1: Select best theta on 60% IS train data
    train_scores = {}
    for theta in thetas:
        engine_train = DirectionalChangeEngine(theta=theta)
        ev_train = engine_train.process_ticks(df_train)
        if len(ev_train) < 5:
            train_scores[theta] = -1.0
            continue
        os_train = ev_train["overshoot_ratio"].dropna().values
        med_os_tr = float(np.median(os_train)) if len(os_train) else 0.0
        cost_adj_os_tr = max(0.0, med_os_tr - (estimated_cost_pct / max(1e-5, theta)))
        train_scores[theta] = cost_adj_os_tr * min(1.0, len(ev_train) / 20.0)

    theta_results: List[Dict[str, Any]] = []

    # Step 2: Evaluate candidates on 40% OOS test data (or full data for reporting)
    for theta in thetas:
        dc_engine = DirectionalChangeEngine(theta=theta)
        events_df = dc_engine.process_ticks(df_test)
        n_events = len(events_df)

        if n_events < 5:
            theta_results.append({
                "theta": float(theta),
                "theta_pct": f"{theta * 100:.1f}%",
                "event_count": n_events,
                "event_rate_per_day": round(n_events / time_span_days, 2),
                "up_event_count": 0,
                "down_event_count": 0,
                "avg_delta": 0.0,
                "avg_omega": 0.0,
                "median_omega": 0.0,
                "overshoot_ratio_mean": 0.0,
                "overshoot_ratio_median": 0.0,
                "overshoot_ratio_p75": 0.0,
                "deficit_rate": 0.0,
                "fade_signal_count": 0,
                "fade_signal_rate": 0.0,
                "duration_ticks_median": 0.0,
                "duration_ms_median": 0.0,
                "duration_ms_p95": 0.0,
                "tmv_mean": 1.0,
                "tmv_std": 0.0,
                "directional_persistence": 0.5,
                "cost_adjusted_os_ratio": 0.0,
                "dc_structure_score": 10.0,
            })
            continue

        directions = events_df["direction"].values
        up_count = int(np.sum(directions == 1))
        down_count = int(np.sum(directions == -1))

        omegas = events_df["omega"].values
        deltas = events_df["delta"].values
        os_ratios = events_df["overshoot_ratio"].values
        tmvs = events_df["tmv"].values
        dur_ticks = events_df["duration_ticks"].values

        # Duration in ms between confirmation timestamps
        timestamps = events_df["timestamp_conf"].values
        diff_ms = np.diff(timestamps)
        duration_ms_median = float(np.median(diff_ms)) if len(diff_ms) > 0 else 0.0
        duration_ms_p95 = float(np.percentile(diff_ms, 95)) if len(diff_ms) > 0 else 0.0

        # Overshoot and Deficit
        deficit_count = int(np.sum(events_df["deficit"] > 0))
        deficit_rate = float(deficit_count / n_events)

        fade_signals = events_df.get("fade_reversal_signal", pd.Series(dtype=bool))
        fade_count = int(fade_signals.sum()) if not fade_signals.empty else 0
        fade_rate = float(fade_count / n_events)

        # Directional persistence (autocorrelation of direction changes)
        if len(directions) > 1:
            same_dir = np.sum(directions[1:] == directions[:-1])
            persistence = float(same_dir / (len(directions) - 1))
        else:
            persistence = 0.5

        # Cost-adjusted overshoot ratio
        # Subtract round-trip fee + slippage impact from relative wave movement
        eff_cost_over_delta = float(estimated_cost_pct / max(1e-5, theta))
        cost_adj_os_ratio = float(max(0.0, np.median(os_ratios) - eff_cost_over_delta))

        # Structural Quality Score (0-100)
        # 1. Event sufficiency: ideally 25 to 500 events
        if n_events >= 30:
            s_events = min(100.0, 50.0 + (n_events - 30) * 0.25)
        else:
            s_events = (n_events / 30.0) * 50.0

        # 2. Overshoot persistence: median OS ratio between 1.0 and 2.5 is healthy
        med_os = float(np.median(os_ratios))
        if med_os >= 1.0:
            s_os = min(100.0, 60.0 + min(40.0, (med_os - 1.0) * 35.0))
        else:
            s_os = max(10.0, med_os * 60.0)

        # 3. Deficit clarity (20% to 50% deficit rate allows strong fade edge)
        s_deficit = 85.0 if 0.15 <= deficit_rate <= 0.60 else 50.0

        # 4. Cost-adjusted movement
        if cost_adj_os_ratio >= 1.0:
            s_cost = 95.0
        elif cost_adj_os_ratio >= 0.5:
            s_cost = 70.0
        elif cost_adj_os_ratio > 0.0:
            s_cost = 45.0
        else:
            s_cost = 15.0

        # 5. Stability & TMV variance
        tmv_std_val = float(np.std(tmvs))
        s_stability = max(20.0, 100.0 - min(80.0, tmv_std_val * 20.0))

        structure_score = round(
            s_events * 0.20
            + s_os * 0.25
            + s_deficit * 0.15
            + s_cost * 0.20
            + s_stability * 0.20,
            1,
        )

        theta_results.append({
            "theta": float(theta),
            "theta_pct": f"{theta * 100:.1f}%",
            "event_count": n_events,
            "event_rate_per_day": round(n_events / time_span_days, 2),
            "up_event_count": up_count,
            "down_event_count": down_count,
            "avg_delta": round(float(np.mean(deltas)), 6),
            "avg_omega": round(float(np.mean(omegas)), 6),
            "median_omega": round(float(np.median(omegas)), 6),
            "overshoot_ratio_mean": round(float(np.mean(os_ratios)), 3),
            "overshoot_ratio_median": round(med_os, 3),
            "overshoot_ratio_p75": round(float(np.percentile(os_ratios, 75)), 3),
            "deficit_rate": round(deficit_rate, 3),
            "fade_signal_count": fade_count,
            "fade_signal_rate": round(fade_rate, 3),
            "duration_ticks_median": round(float(np.median(dur_ticks)), 1),
            "duration_ms_median": round(duration_ms_median, 0),
            "duration_ms_p95": round(duration_ms_p95, 0),
            "tmv_mean": round(float(np.mean(tmvs)), 3),
            "tmv_std": round(tmv_std_val, 3),
            "directional_persistence": round(persistence, 3),
            "cost_adjusted_os_ratio": round(cost_adj_os_ratio, 3),
            "dc_structure_score": structure_score,
        })

    # Select Best Theta (Optimal theta*) using 60% IS train scores
    best_candidate_thetas = sorted(train_scores.keys(), key=lambda t: train_scores[t], reverse=True)
    if split_ts is not None and best_candidate_thetas and train_scores[best_candidate_thetas[0]] > 0:
        best_theta = best_candidate_thetas[0]
        matching = [r for r in theta_results if r["theta"] == best_theta]
        best_item = matching[0] if matching else (theta_results[0] if theta_results else None)
    else:
        best_theta = None
        best_item = None

    return {
        "symbol": symbol,
        "best_theta": best_theta,
        "best_theta_pct": best_item["theta_pct"] if best_item else None,
        "best_metrics": best_item,
        "theta_results": theta_results,
        "total_ticks": total_ticks,
        "time_span_days": round(time_span_days, 1),
        "has_sufficient_events": best_item["event_count"] >= 20 if best_item else False,
        "split_ts": split_ts,
    }
