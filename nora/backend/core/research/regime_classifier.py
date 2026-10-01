"""Regime Classifier Module (DEX & Intrinsic Time Native)
Classifies market structure into:
- DC_MOMENTUM_REGIME: High overshoot ratio, sustained direction persistence
- VOL_EXPANSION_REGIME: High realized volatility, ATR & tick surge
- RANGE_CHOP_REGIME: Choppy sideways, low overshoot, frequent reversals
- OVERSHOOT_DEFICIT_REGIME: Scale compression delta/R > 0.25, overshoot deficit exhaustion
- LIQUIDITY_DRY_UP_REGIME: Long inter-trade intervals, drying volume
- NEEDS_MORE_DATA_REGIME: Insufficient tick/candle history
Extracts timeline chunks, regime drivers, and probability distributions.
"""
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd

try:
    from backend.db.tick_storage import load_candle_df, load_ticks_df, default_data_root
except ImportError:
    from nora.backend.db.tick_storage import load_candle_df, load_ticks_df, default_data_root


class RegimeType:
    DC_MOMENTUM_REGIME = "DC_MOMENTUM_REGIME"
    VOL_EXPANSION_REGIME = "VOL_EXPANSION_REGIME"
    RANGE_CHOP_REGIME = "RANGE_CHOP_REGIME"
    OVERSHOOT_DEFICIT_REGIME = "OVERSHOOT_DEFICIT_REGIME"
    LIQUIDITY_DRY_UP_REGIME = "LIQUIDITY_DRY_UP_REGIME"
    NEEDS_MORE_DATA_REGIME = "NEEDS_MORE_DATA_REGIME"

    # Backward-compatible aliases
    TRENDING_UP = "DC_MOMENTUM_REGIME"
    TRENDING_DOWN = "DC_MOMENTUM_REGIME"
    RANGING_SIDEWAYS = "RANGE_CHOP_REGIME"
    HIGH_VOL_EXPANSION = "VOL_EXPANSION_REGIME"
    LOW_VOL_CONTRACTION = "RANGE_CHOP_REGIME"


REGIME_LABELS = {
    RegimeType.DC_MOMENTUM_REGIME: {
        "name": "Sóng Quán Tính DC (Momentum)",
        "color": "#10b981",
        "badge": "success",
        "description": "Quán tính sóng rướn mạnh (OS Ratio > 1.2), thuận lợi cho các chiến lược Trend/Momentum.",
    },
    RegimeType.VOL_EXPANSION_REGIME: {
        "name": "Biến Động Bùng Nổ (Vol Expansion)",
        "color": "#f59e0b",
        "badge": "warning",
        "description": "Biên độ và khối lượng on-chain tăng đột biến, phù hợp cho Breakout có bộ lọc.",
    },
    RegimeType.RANGE_CHOP_REGIME: {
        "name": "Đi Ngang / Nhiễu (Range Chop)",
        "color": "#64748b",
        "badge": "neutral",
        "description": "Đảo chiều liên tục trong biên độ hẹp, phí và trượt giá dễ ăn mòn lợi nhuận.",
    },
    RegimeType.OVERSHOOT_DEFICIT_REGIME: {
        "name": "Sóng Rướn Hụt Hơi (Overshoot Deficit)",
        "color": "#8b5cf6",
        "badge": "info",
        "description": "Sóng rướn hụt hơi ở biên độ nén, xuất hiện cụm tín hiệu đảo chiều Fade Reversal.",
    },
    RegimeType.LIQUIDITY_DRY_UP_REGIME: {
        "name": "Cạn Kiệt Thanh Khoản (Dry-Up)",
        "color": "#ef4444",
        "badge": "danger",
        "description": "Khoảng cách giữa các giao dịch quá dài, rủi ro kẹt lệnh và trượt giá cực lớn.",
    },
    RegimeType.NEEDS_MORE_DATA_REGIME: {
        "name": "Chưa Đủ Dữ Liệu",
        "color": "#94a3b8",
        "badge": "neutral",
        "description": "Chưa đủ số lượng giao dịch để xác lập trạng thái thị trường.",
    },
}


def classify_market_regime(
    symbol: str,
    timeframe: str = "1h",
    df: Optional[pd.DataFrame] = None,
    dc_data: Optional[Dict[str, Any]] = None,
    data_quality_data: Optional[Dict[str, Any]] = None,
    data_root: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Classifies the current and historical regime of a DEX asset using
    Directional Change structure, tick activity, and price distributions.
    """
    if df is None or df.empty:
        df = load_candle_df(symbol, timeframe, data_root)

    # Check for empty / insufficient data
    if df.empty or len(df) < 10:
        return {
            "symbol": symbol,
            "current_regime": RegimeType.NEEDS_MORE_DATA_REGIME,
            "regime_info": REGIME_LABELS[RegimeType.NEEDS_MORE_DATA_REGIME],
            "regime_confidence": 0.90,
            "regime_probabilities": {
                RegimeType.DC_MOMENTUM_REGIME: 0.1,
                RegimeType.VOL_EXPANSION_REGIME: 0.1,
                RegimeType.RANGE_CHOP_REGIME: 0.2,
                RegimeType.OVERSHOOT_DEFICIT_REGIME: 0.1,
                RegimeType.LIQUIDITY_DRY_UP_REGIME: 0.1,
                RegimeType.NEEDS_MORE_DATA_REGIME: 0.4,
            },
            "drivers": ["Số lượng nến/ticks quá mỏng, chưa đủ để phân loại"],
            "metrics": {
                "trend_strength": 0.0,
                "realized_volatility_pct": 0.0,
                "chopiness_score": 50.0,
                "overshoot_ratio": 1.0,
                "atr_ratio": 1.0,
            },
            "regime_timeline": [],
        }

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    n = len(close)

    # 1. Realized Volatility
    returns = np.diff(close) / (close[:-1] + 1e-9)
    ann_vol = float(np.std(returns) * np.sqrt(365 * 24) * 100.0) if len(returns) > 1 else 0.0

    # 2. ATR proxy
    tr = np.maximum(np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1])), np.abs(low[1:] - close[:-1]))
    atr_window = min(14, len(tr))
    atr = pd.Series(tr).rolling(atr_window, min_periods=1).mean().values if len(tr) > 0 else np.array([0.0])
    recent_atr = float(atr[-1]) if len(atr) > 0 else 0.0
    mean_atr = float(np.mean(atr)) if len(atr) > 0 else 1.0
    atr_ratio = recent_atr / (mean_atr + 1e-9)

    # 3. Trend slope & Choppiness
    slope_window = min(20, n)
    x = np.arange(slope_window)
    y = close[-slope_window:]
    slope, _ = np.polyfit(x, y / (y[0] + 1e-9) - 1.0, 1)
    trend_pct = float(slope * slope_window * 100.0)

    if n >= 14:
        tr_sum = np.sum(tr[-14:])
        max_high = np.max(high[-14:])
        min_low = np.min(low[-14:])
        hl_range = max_high - min_low
        if hl_range > 1e-9 and tr_sum > 0:
            chop = 100.0 * np.log10(tr_sum / hl_range) / np.log10(14)
            chopiness_score = float(np.clip(chop, 0.0, 100.0))
        else:
            chopiness_score = 50.0
    else:
        chopiness_score = 50.0

    # 4. Integrate DC Metrics if available
    best_m = dc_data.get("best_metrics", {}) if dc_data else {}
    os_ratio = float(best_m.get("overshoot_ratio_median", 1.0))
    deficit_rate = float(best_m.get("deficit_rate", 0.30))
    fade_rate = float(best_m.get("fade_signal_rate", 0.0))
    dir_persist = float(best_m.get("directional_persistence", 0.50))

    # Data quality metrics for dry-up detection
    dq_metrics = data_quality_data.get("metrics", {}) if data_quality_data else {}
    inter_trade_p95 = float(dq_metrics.get("inter_trade_p95_sec", 0.0))
    zero_vol_pct = float(dq_metrics.get("zero_volume_pct", 0.0))

    # 5. Compute Probabilities & Drivers
    probs = {
        RegimeType.DC_MOMENTUM_REGIME: 0.10,
        RegimeType.VOL_EXPANSION_REGIME: 0.10,
        RegimeType.RANGE_CHOP_REGIME: 0.20,
        RegimeType.OVERSHOOT_DEFICIT_REGIME: 0.10,
        RegimeType.LIQUIDITY_DRY_UP_REGIME: 0.05,
    }
    drivers: List[str] = []

    # Dry-up rule
    if inter_trade_p95 > 3600 or zero_vol_pct > 25.0:
        probs[RegimeType.LIQUIDITY_DRY_UP_REGIME] += 0.55
        drivers.append(f"Khoảng cách lệnh p95 đạt {inter_trade_p95 / 60:.0f} phút, thanh khoản ngắt quãng")

    # Overshoot Deficit rule
    if fade_rate > 0.15 or (deficit_rate > 0.45 and chopiness_score > 52.0):
        probs[RegimeType.OVERSHOOT_DEFICIT_REGIME] += 0.45
        drivers.append(f"Tỷ lệ sóng rướn hụt hơi (deficit {deficit_rate * 100:.0f}%) và xuất hiện cụm tín hiệu Fade Reversal")

    # DC Momentum rule
    if os_ratio >= 1.25 and chopiness_score < 55.0 and dir_persist >= 0.52:
        probs[RegimeType.DC_MOMENTUM_REGIME] += 0.50
        drivers.append(f"Quán tính sóng rướn mạnh (OS Ratio: {os_ratio:.2f}) với độ bền xu hướng cao")

    # Vol Expansion rule
    if atr_ratio > 1.35 or ann_vol > 120.0:
        probs[RegimeType.VOL_EXPANSION_REGIME] += 0.45
        drivers.append(f"Biến động thực nhận mở rộng mạnh (ATR ratio: {atr_ratio:.2f}, Vol: {ann_vol:.1f}%)")

    # Range Chop rule
    if chopiness_score >= 60.0 or (os_ratio < 0.95 and abs(trend_pct) < 2.0):
        probs[RegimeType.RANGE_CHOP_REGIME] += 0.45
        drivers.append(f"Chỉ số Choppiness cao ({chopiness_score:.1f}), thị trường đi ngang dao động nhiễu")

    if not drivers:
        drivers.append(f"Cấu trúc cân bằng ổn định quanh mức biến động {ann_vol:.1f}%")

    total_p = sum(probs.values())
    regime_probabilities = {k: round(v / total_p, 3) for k, v in probs.items()}
    current_regime = max(regime_probabilities, key=regime_probabilities.get)
    confidence = float(regime_probabilities[current_regime])

    # 6. Build Timeline
    segment_size = max(5, n // 10)
    regime_timeline: List[Dict[str, Any]] = []

    for i in range(0, n, segment_size):
        sub_df = df.iloc[i : i + segment_size]
        if sub_df.empty:
            continue
        sub_close = sub_df["close"].values
        sub_t_start = int(sub_df["open_time"].iloc[0])
        sub_t_end = int(sub_df["open_time"].iloc[-1])
        sub_ret = (sub_close[-1] / (sub_close[0] + 1e-9) - 1.0) * 100.0

        if abs(sub_ret) > 5.0:
            r_type = RegimeType.DC_MOMENTUM_REGIME
        elif len(sub_close) > 2 and np.std(sub_close) / (np.mean(sub_close) + 1e-9) > 0.05:
            r_type = RegimeType.VOL_EXPANSION_REGIME
        else:
            r_type = RegimeType.RANGE_CHOP_REGIME

        info = REGIME_LABELS.get(r_type, REGIME_LABELS[RegimeType.RANGE_CHOP_REGIME])
        regime_timeline.append({
            "start_time": sub_t_start,
            "end_time": sub_t_end,
            "regime": r_type,
            "regime_name": info["name"],
            "color": info["color"],
            "return_pct": round(float(sub_ret), 2),
        })

    return {
        "symbol": symbol,
        "current_regime": current_regime,
        "regime_info": REGIME_LABELS.get(current_regime, REGIME_LABELS[RegimeType.RANGE_CHOP_REGIME]),
        "regime_confidence": round(confidence, 2),
        "regime_probabilities": regime_probabilities,
        "drivers": drivers,
        "metrics": {
            "trend_strength": round(float(trend_pct), 2),
            "realized_volatility_pct": round(float(ann_vol), 1),
            "chopiness_score": round(float(chopiness_score), 1),
            "overshoot_ratio": round(float(os_ratio), 2),
            "atr_ratio": round(float(atr_ratio), 2),
            "deficit_rate": round(float(deficit_rate), 2),
            "fade_signal_rate": round(float(fade_rate), 3),
        },
        "regime_timeline": regime_timeline,
    }
