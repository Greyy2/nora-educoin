"""Directional Change & Overshoot Deficit Event Engine for Tick Streams.
Based on the empirical scaling laws by Glattfelder-Olsen & Son Do (2026).
"""
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
import pandas as pd

try:
    from numba import njit
except ImportError:
    def njit(*args, **kwargs):
        def decorator(func):
            return func
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator


@njit(cache=True)
def extract_dc_events_numba(
    timestamps: np.ndarray,
    prices: np.ndarray,
    theta: float,
    out_i: np.ndarray,
    out_v: np.ndarray,
    cap: int,
) -> int:
    """
    Extract causal Directional Change events from tick price series.
    
    out_i columns: [i_ext_prev, i_ext, i_conf, direction (1 for up, -1 for down), timestamp_conf]
    out_v columns: [TMV, delta, omega, duration_ticks]
    """
    n = prices.shape[0]
    k = 0
    ext_p = prices[0]
    ext_i = 0
    curr_max = prices[0]
    curr_min = prices[0]
    tp_max = 0
    tp_min = 0
    up = True
    
    for i in range(n):
        p = prices[i]
        t = timestamps[i]
        
        if up:
            if p <= (1.0 - theta) * curr_max:
                # UP trend ended at tp_max (P_ext = curr_max), confirmed at i
                if k < cap:
                    out_i[k, 0] = ext_i
                    out_i[k, 1] = tp_max
                    out_i[k, 2] = i
                    out_i[k, 3] = 1
                    out_i[k, 4] = t
                    
                    delta = theta * ext_p
                    total_move = curr_max - ext_p
                    omega = max(0.0, total_move - delta)
                    tmv = total_move / (ext_p * theta) if ext_p > 0 else 1.0
                    
                    out_v[k, 0] = tmv
                    out_v[k, 1] = delta
                    out_v[k, 2] = omega
                    out_v[k, 3] = float(tp_max - ext_i)
                    k += 1
                    
                ext_p = curr_max
                ext_i = tp_max
                up = False
                curr_min = p
                tp_min = i
            elif p > curr_max:
                curr_max = p
                tp_max = i
        else:
            if p >= (1.0 + theta) * curr_min:
                # DOWN trend ended at tp_min (P_ext = curr_min), confirmed at i
                if k < cap:
                    out_i[k, 0] = ext_i
                    out_i[k, 1] = tp_min
                    out_i[k, 2] = i
                    out_i[k, 3] = -1
                    out_i[k, 4] = t
                    
                    delta = theta * ext_p
                    total_move = ext_p - curr_min
                    omega = max(0.0, total_move - delta)
                    tmv = total_move / (ext_p * theta) if ext_p > 0 else 1.0
                    
                    out_v[k, 0] = tmv
                    out_v[k, 1] = delta
                    out_v[k, 2] = omega
                    out_v[k, 3] = float(tp_min - ext_i)
                    k += 1
                    
                ext_p = curr_min
                ext_i = tp_min
                up = True
                curr_max = p
                tp_max = i
            elif p < curr_min:
                curr_min = p
                tp_min = i
                
    return k


class DirectionalChangeEngine:
    """High-performance Directional Change & Overshoot Deficit Analyzer."""

    def __init__(self, theta: float = 0.02):
        self.theta = float(theta)

    def process_ticks(self, df_ticks: pd.DataFrame) -> pd.DataFrame:
        if df_ticks.empty or len(df_ticks) < 10:
            return pd.DataFrame()

        prices = np.ascontiguousarray(df_ticks["price"].values, dtype=np.float64)
        timestamps = np.ascontiguousarray(df_ticks["timestamp_ms"].values, dtype=np.int64)
        n = len(prices)
        cap = max(64, n)

        out_i = np.zeros((cap, 5), dtype=np.int64)
        out_v = np.zeros((cap, 4), dtype=np.float64)

        k = extract_dc_events_numba(timestamps, prices, self.theta, out_i, out_v, cap)

        if k == 0:
            return pd.DataFrame()

        oi = out_i[:k]
        ov = out_v[:k]

        events_df = pd.DataFrame({
            "i_ext_prev": oi[:, 0],
            "i_ext": oi[:, 1],
            "i_conf": oi[:, 2],
            "direction": oi[:, 3],
            "timestamp_conf": oi[:, 4],
            "price_ext_prev": prices[oi[:, 0]],
            "price_ext": prices[oi[:, 1]],
            "price_conf": prices[oi[:, 2]],
            "tmv": ov[:, 0],
            "delta": ov[:, 1],
            "omega": ov[:, 2],
            "overshoot_ratio": np.where(ov[:, 1] > 0, ov[:, 2] / ov[:, 1], 0.0),
            "deficit": ov[:, 1] - ov[:, 2],  # (delta - omega)
            "duration_ticks": ov[:, 3],
        })

        # Calculate session/window realized range R
        window_size = min(50, len(events_df))
        min_periods = min(3, window_size)
        events_df["rolling_max_p"] = events_df["price_ext"].rolling(window_size, min_periods=min_periods).max()
        events_df["rolling_min_p"] = events_df["price_ext"].rolling(window_size, min_periods=min_periods).min()
        events_df["realized_range_R"] = events_df["rolling_max_p"] - events_df["rolling_min_p"]
        
        # Scale compression ratio: delta / R
        events_df["delta_over_R"] = np.where(
            events_df["realized_range_R"] > 0,
            events_df["delta"] / events_df["realized_range_R"],
            0.20
        )

        # Signal: Mid-Air Reversal Gate (When delta / R > 0.30 -> Expect sharp Overshoot Deficit)
        events_df["fade_reversal_signal"] = (events_df["delta_over_R"] > 0.25) & (events_df["overshoot_ratio"] < 0.85)

        return events_df


def simulate_causal_dc_trades(
    df_ticks: pd.DataFrame,
    theta: float = 0.02,
    friction_bps: float = 65.0,
    tp_overshoot_multiplier: float = 1.25,
    mode: str = "fade",
) -> Dict[str, Any]:
    """
    Simulate causal, 100% zero look-ahead trading execution on raw tick data.
    
    Rules:
    1. Entry is strictly triggered at i_conf (confirmation tick) at price P_conf.
    2. Exit is evaluated tick-by-tick:
       - Take Profit: If price hits target P_tp = P_entry * (1 +/- k * theta)
       - Stop / Reversal: If opposite DC event is confirmed at i_next_conf at price P_next_conf.
    3. Zero look-ahead bias: Never uses unconfirmed peak/trough extrema for execution.
    4. mode: 'fade' (counter-trend fade after DC) or 'momentum' (trend-following after DC).
    """
    if df_ticks.empty or len(df_ticks) < 20:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_net_bps": 0.0,
            "trades": [],
            "cost_models": {},
        }

    prices = np.ascontiguousarray(df_ticks["price"].values, dtype=np.float64)
    timestamps = np.ascontiguousarray(df_ticks["timestamp_ms"].values, dtype=np.int64)
    n = len(prices)

    engine = DirectionalChangeEngine(theta=theta)
    events_df = engine.process_ticks(df_ticks)

    if events_df.empty or len(events_df) < 2:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_net_bps": 0.0,
            "trades": [],
            "cost_models": {},
        }

    trades = []
    k_events = len(events_df)

    for idx in range(k_events):
        ev = events_df.iloc[idx]
        direction = int(ev["direction"])
        i_conf = int(ev["i_conf"])
        p_conf = float(ev["price_conf"])
        t_conf = int(ev["timestamp_conf"])

        if i_conf >= n - 1:
            continue

        # Next event confirmation index (boundary for trailing exit)
        if idx + 1 < k_events:
            i_next_bound = int(events_df.iloc[idx + 1]["i_conf"])
        else:
            i_next_bound = n - 1

        i_next_bound = min(n - 1, max(i_conf + 1, i_next_bound))

        entry_p = p_conf
        entry_t = t_conf
        exit_p = prices[i_next_bound]
        exit_t = timestamps[i_next_bound]
        exit_reason = "DC Reversal Trailing Stop"
        exit_i = i_next_bound

        # Determine trade position type
        if mode == "momentum":
            is_long = (direction == -1)  # Upturn confirmed -> Long momentum
            trade_type = "LONG (Momentum sau upturn)" if is_long else "SHORT (Momentum sau downturn)"
        else:
            is_long = (direction == 1)   # Downturn confirmed -> Long fade
            trade_type = "LONG (Fade sau downturn)" if is_long else "SHORT (Fade sau upturn)"

        # Check tick-by-tick for Overshoot Take-Profit limit order
        if is_long:
            tp_target = entry_p * (1.0 + theta * tp_overshoot_multiplier)
            for tick_i in range(i_conf + 1, i_next_bound + 1):
                p_tick = prices[tick_i]
                if p_tick >= tp_target:
                    exit_p = tp_target  # Limit order fills at target, not overshoot tick price
                    exit_t = timestamps[tick_i]
                    exit_reason = "Take Profit @ Target Overshoot"
                    exit_i = tick_i
                    break

            gross_pct = ((exit_p - entry_p) / entry_p) * 100.0 if entry_p > 0 else 0.0
        else:
            tp_target = entry_p * (1.0 - theta * tp_overshoot_multiplier)
            for tick_i in range(i_conf + 1, i_next_bound + 1):
                p_tick = prices[tick_i]
                if p_tick <= tp_target:
                    exit_p = tp_target  # Limit order fills at target, not overshoot tick price
                    exit_t = timestamps[tick_i]
                    exit_reason = "Take Profit @ Target Overshoot"
                    exit_i = tick_i
                    break

            gross_pct = ((entry_p - exit_p) / entry_p) * 100.0 if entry_p > 0 else 0.0

        gross_b = int(round(gross_pct * 100.0))
        dur_ms = max(1000, abs(exit_t - entry_t))
        dur_min = int(round(dur_ms / 60000.0))
        dur_str = f"{dur_min}m" if dur_min < 60 else f"{dur_min // 60}h {dur_min % 60}m"
        dt_str = pd.to_datetime(entry_t, unit="ms").strftime("%Y-%m-%d %H:%M")

        trades.append({
            "id": int(idx + 1),
            "time": dt_str,
            "timestamp": int(entry_t),
            "exitTimestamp": int(exit_t),
            "entryIndex": int(i_conf),
            "exitIndex": int(exit_i),
            "type": trade_type,
            "direction": int(direction),
            "entryPrice": round(float(entry_p), 6),
            "exitPrice": round(float(exit_p), 6),
            "grossGainPct": round(float(gross_pct), 2),
            "grossBps": int(gross_b),
            "duration": dur_str,
            "durationMin": int(dur_min),
            "reason": exit_reason,
        })

    # Evaluate 5 multi-tier cost scenarios from Zero to Stress
    cost_tiers = [
        {"key": "zero", "label": "Zero Cost (0 bps)", "friction": 0, "desc": "Alpha gộp lý thuyết"},
        {"key": "low", "label": "Low AMM (30 bps)", "friction": 30, "desc": "Pool sâu (Fee 10 + Slip 20)"},
        {"key": "standard", "label": "Standard AMM (65 bps)", "friction": int(round(friction_bps)), "desc": "Pool tiêu chuẩn (Fee 25 + Slip 40)"},
        {"key": "high", "label": "High Slippage (150 bps)", "friction": 150, "desc": "Biến động mạnh (Fee 50 + Slip 100)"},
        {"key": "stress", "label": "Severe Stress (250 bps)", "friction": 250, "desc": "Nghẽn mạng / Sụp đổ thanh khoản"},
    ]

    time_span_ms = float(timestamps[-1] - timestamps[0]) if len(timestamps) > 1 else 0.0
    years = max(1.0 / 365.25, time_span_ms / (86400.0 * 1000.0 * 365.25))

    cost_models = {}
    for tier in cost_tiers:
        f = tier["friction"]
        tier_net_bps = [t["grossBps"] - f for t in trades]
        tier_wins = sum(1 for b in tier_net_bps if b > 0)
        total_t = len(trades)
        wr = round((tier_wins / max(1, total_t)) * 100.0, 1) if total_t else 0.0

        g_gains = [b for b in tier_net_bps if b > 0]
        g_losses = [abs(b) for b in tier_net_bps if b < 0]
        sum_gains = sum(g_gains)
        sum_losses = sum(g_losses)
        if sum_losses > 0:
            pf = round(sum_gains / sum_losses, 2)
        elif sum_gains > 0:
            pf = float("inf")
        else:
            pf = 0.0

        avg_net = round(float(np.mean(tier_net_bps)), 1) if tier_net_bps else 0.0

        # Estimate Sharpe Ratio using actual time span in years
        if len(tier_net_bps) > 2 and years > 0:
            ret_arr = np.array(tier_net_bps) / 10000.0
            std = np.std(ret_arr)
            sharpe = round(float((np.mean(ret_arr) / max(1e-6, std)) * np.sqrt(len(tier_net_bps) / years)), 2) if std > 0 else 0.0
        else:
            sharpe = 0.0

        # Drawdown calculation
        equity = np.cumsum([0] + tier_net_bps)
        peak = np.maximum.accumulate(equity)
        dd = peak - equity
        max_dd_bps = int(np.max(dd)) if len(dd) else 0
        max_dd_pct = round(max_dd_bps / 100.0, 1)

        # Survived criteria: n >= 30, avg_net > 0, 95% bootstrap lower bound of avg_net_bps > 0
        bootstrap_lb = -999.0
        if len(tier_net_bps) >= 30:
            rng = np.random.default_rng(42)
            boot_samples = rng.choice(tier_net_bps, size=(500, len(tier_net_bps)), replace=True)
            boot_means = np.mean(boot_samples, axis=1)
            bootstrap_lb = float(np.percentile(boot_means, 2.5))

        survived = bool((len(tier_net_bps) >= 30) and (avg_net > 0) and (bootstrap_lb > 0))

        cost_models[tier["key"]] = {
            "key": tier["key"],
            "name": tier["label"],
            "label": tier["label"],
            "friction_bps": f,
            "frictionBps": f,
            "desc": tier["desc"],
            "win_rate": wr,
            "winRate": wr,
            "profit_factor": None if pf == float("inf") else pf,
            "profitFactor": None if pf == float("inf") else pf,
            "profit_factor_is_inf": pf == float("inf"),
            "avg_net_bps": avg_net,
            "avgNetBps": avg_net,
            "net_bps": avg_net,
            "sharpe": sharpe,
            "max_drawdown_pct": max_dd_pct,
            "maxDdPct": max_dd_pct,
            "bootstrap_lb_95": round(bootstrap_lb, 1) if bootstrap_lb > -900 else None,
            "survived": survived,
            "verdict": "SURVIVED" if survived else "FALSIFIED",
        }

    # Attach base friction to trades
    base_f = int(round(friction_bps))
    for t in trades:
        t["frictionBps"] = base_f
        t["netBps"] = t["grossBps"] - base_f
        t["netGainPct"] = round(t["netBps"] / 100.0, 2)
        t["win"] = t["netBps"] > 0

    base_model = cost_models.get("standard", cost_models.get("zero", {}))

    return {
        "total_trades": len(trades),
        "win_rate": base_model.get("winRate"),
        "profit_factor": base_model.get("profitFactor"),
        "avg_net_bps": base_model.get("avgNetBps"),
        "sharpe": base_model.get("sharpe"),
        "trades": trades,
        "cost_models": cost_models,
    }

