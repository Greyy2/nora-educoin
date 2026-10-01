"""Market Health & Tradeability Scoring Module
Computes:
1. Market Health Score (0-100): Measures cleanliness, liquidity continuity, and structural regularity.
2. Tradeability Score (0-100): Measures capital deployment viability.
Classifies markets into 5 states:
- CAN_TRADE: High health, validated edge, strong WFA
- RESEARCH_READY: Clean data, robust DC structure, awaiting strategy/WFA validation
- NARROW_CONDITIONS: Only viable in specific regimes (e.g. Vol Expansion)
- DO_NOT_TRADE: Severely hindered by noise, spread, or liquidity gaps
- NEEDS_MORE_DATA: Insufficient history to draw reliable quantitative conclusions
"""
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd

try:
    from backend.core.data.quality_gate import evaluate_data_quality, DataQualityStatus
    from backend.core.research.regime_classifier import classify_market_regime, RegimeType
except ImportError:
    from nora.backend.core.data.quality_gate import evaluate_data_quality, DataQualityStatus
    from nora.backend.core.research.regime_classifier import classify_market_regime, RegimeType


class TradeabilityClass:
    CAN_TRADE = "CAN_TRADE"
    RESEARCH_READY = "RESEARCH_READY"
    NARROW_CONDITIONS = "NARROW_CONDITIONS"
    DO_NOT_TRADE = "DO_NOT_TRADE"
    NEEDS_MORE_DATA = "NEEDS_MORE_DATA"


TRADEABILITY_META = {
    TradeabilityClass.CAN_TRADE: {
        "title": "Trade Tốt",
        "badge": "success",
        "color": "#10b981",
        "icon": "✅",
        "description": "Thanh khoản dồi dào, cấu trúc sóng DC rõ nét, edge chiến lược kháng phí và sống sót qua kiểm định OOS/WFA.",
    },
    TradeabilityClass.RESEARCH_READY: {
        "title": "Sẵn Sàng Nghiên Cứu",
        "badge": "primary",
        "color": "#3b82f6",
        "icon": "🔬",
        "description": "Dữ liệu sạch, cấu trúc vi mô DC đạt chuẩn, có ngưỡng θ* tối ưu. Sẵn sàng đưa vào sinh Alpha và chạy Backtest.",
    },
    TradeabilityClass.NARROW_CONDITIONS: {
        "title": "Điều Kiện Hẹp",
        "badge": "warning",
        "color": "#f59e0b",
        "icon": "⚠️",
        "description": "Chỉ hiệu quả trong một số Regime nhất định (ví dụ Volatility Expansion), dễ fail khi thị trường đi ngang hoặc thanh khoản mỏng.",
    },
    TradeabilityClass.DO_NOT_TRADE: {
        "title": "Không Nên Trade",
        "badge": "danger",
        "color": "#ef4444",
        "icon": "❌",
        "description": "Expectancy âm sau phí, độ nhiễu lớn, thanh khoản ngắt quãng hoặc không có quy luật sóng rướn.",
    },
    TradeabilityClass.NEEDS_MORE_DATA: {
        "title": "Cần Thêm Data",
        "badge": "neutral",
        "color": "#94a3b8",
        "icon": "🕰️",
        "description": "Dữ liệu lịch sử chưa đủ số lượng giao dịch hoặc chu kỳ biến động để đưa ra kết luận định lượng.",
    },
}


def compute_market_health_score(
    symbol: str,
    timeframe: str = "1h",
    df_candles: Optional[pd.DataFrame] = None,
    df_ticks: Optional[pd.DataFrame] = None,
    dc_data: Optional[Dict[str, Any]] = None,
    scaling_law_data: Optional[Dict[str, Any]] = None,
    backtest_metrics: Optional[Dict[str, Any]] = None,
    data_root: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Computes multidimensional scorecard for an asset without fabricating backtest metrics.
    """
    # 1. Evaluate Data Quality Gate
    dq = evaluate_data_quality(symbol, timeframe, df_candles, df_ticks, data_root)
    quality_score = float(dq.get("quality_score", 50.0))

    if dq.get("status") == DataQualityStatus.NEEDS_MORE_DATA:
        return {
            "symbol": symbol,
            "market_health_score": round(quality_score, 1),
            "tradeability_score": round(quality_score, 1),
            "classification": TradeabilityClass.NEEDS_MORE_DATA,
            "meta": TRADEABILITY_META[TradeabilityClass.NEEDS_MORE_DATA],
            "confidence": 0.50,
            "components": {
                "data_quality": quality_score,
                "liquidity_continuity": 25.0,
                "cost_friction_safety": 30.0,
                "dc_structure_clarity": 20.0,
                "regime_stability": 30.0,
                "strategy_fit": None,
                "oos_robustness": None,
            },
            "top_reasons": ["Lịch sử giao dịch quá mỏng, cần tiếp tục thu thập thêm tick data"],
            "blockers": ["Chưa đủ mẫu giao dịch on-chain tối thiểu"],
            "data_quality_report": dq,
            "regime_report": classify_market_regime(symbol, timeframe, df_candles, dc_data=dc_data, data_quality_data=dq, data_root=data_root),
        }

    # 2. Classify Regime with DC integration
    reg = classify_market_regime(symbol, timeframe, df_candles, dc_data=dc_data, data_quality_data=dq, data_root=data_root)
    reg_metrics = reg.get("metrics", {})
    chopiness = float(reg_metrics.get("chopiness_score", 50.0))

    # 3. Liquidity Continuity Score (0-100)
    dq_m = dq.get("metrics", {})
    total_ticks = dq_m.get("total_ticks", 0)
    zero_vol_pct = float(dq_m.get("zero_volume_pct", 0.0))
    inter_trade_p95 = float(dq_m.get("inter_trade_p95_sec", 0.0))

    liquidity_score = 100.0 - min(50.0, zero_vol_pct * 1.5)
    if inter_trade_p95 > 3600:
        liquidity_score -= min(40.0, (inter_trade_p95 / 3600.0) * 8.0)
    if total_ticks >= 500:
        liquidity_score = max(liquidity_score, 85.0)
    elif total_ticks >= 150:
        liquidity_score = max(liquidity_score, 65.0)
    liquidity_score = float(np.clip(liquidity_score, 10.0, 100.0))

    # 4. Cost / Friction Safety Score (0-100)
    slippage_pct = float(dq_m.get("estimated_slippage_pct", 0.25))
    noise_ratio = float(dq_m.get("noise_ratio", 1.0))
    spread_score = 100.0 - min(50.0, noise_ratio * 12.0) - min(40.0, slippage_pct * 50.0)
    spread_score = float(np.clip(spread_score, 10.0, 100.0))

    # 5. DC Structure Clarity (0-100)
    best_m = dc_data.get("best_metrics", {}) if dc_data else {}
    dc_score = float(best_m.get("dc_structure_score", 60.0)) if best_m else 55.0
    scaling_score = float(scaling_law_data.get("scaling_law_score", 55.0)) if scaling_law_data else 55.0
    dc_structure_clarity = round(dc_score * 0.65 + scaling_score * 0.35, 1)

    # 6. Regime Stability (0-100)
    regime_stability = max(20.0, 100.0 - abs(chopiness - 50.0) * 0.5 if chopiness > 62 else 80.0)

    # 7. Market Health Score (Cleanliness & Structure)
    # 20% Data Quality + 20% Liquidity + 20% Cost Safety + 20% DC Structure + 20% Regime Stability
    market_health_score = (
        quality_score * 0.20
        + liquidity_score * 0.20
        + spread_score * 0.20
        + dc_structure_clarity * 0.20
        + regime_stability * 0.20
    )
    market_health_score = round(float(np.clip(market_health_score, 10.0, 99.0)), 1)

    # 8. Strategy Fit & OOS Robustness (Real vs Not-Evaluated)
    has_real_backtest = backtest_metrics is not None and len(backtest_metrics) > 0
    top_reasons: List[str] = []
    blockers: List[str] = []

    if has_real_backtest:
        bm = backtest_metrics
        sharpe = float(bm.get("sharpe", 1.0))
        winrate = float(bm.get("winrate", 50.0))
        mdd = float(bm.get("mdd", 20.0))
        oos_gap = float(bm.get("oos_gap", 0.25))

        strategy_fit = float(np.clip((sharpe * 30.0) + (winrate * 0.7) - (mdd * 0.4), 10.0, 100.0))
        oos_robustness = float(np.clip(100.0 - (oos_gap * 100.0), 10.0, 100.0))
        cost_resilience = float(np.clip(100.0 - (noise_ratio * 10.0) - (mdd * 0.3), 10.0, 100.0))

        tradeability_score = (
            market_health_score * 0.25
            + dc_structure_clarity * 0.20
            + strategy_fit * 0.20
            + cost_resilience * 0.15
            + oos_robustness * 0.20
        )
    else:
        # Research mode without fabricated backtest numbers
        strategy_fit = None
        oos_robustness = None
        cost_resilience = float(np.clip(100.0 - (noise_ratio * 15.0) - (slippage_pct * 40.0), 15.0, 95.0))

        # Tradeability based purely on structural health & friction tolerance
        tradeability_score = (
            market_health_score * 0.40
            + dc_structure_clarity * 0.35
            + cost_resilience * 0.25
        )

    tradeability_score = round(float(np.clip(tradeability_score, 10.0, 99.0)), 1)

    # 9. Formulate Top Reasons & Blockers
    os_med = float(best_m.get("overshoot_ratio_median", 1.0))
    best_theta_pct = str(dc_data.get("best_theta_pct", "2.0%")) if dc_data else "2.0%"

    if dc_structure_clarity >= 70.0:
        top_reasons.append(f"Cấu trúc DC vững chắc tại ngưỡng tối ưu θ* = {best_theta_pct}")
    if os_med >= 1.2:
        top_reasons.append(f"Sóng rướn có quán tính tốt (Overshoot median: {os_med:.2f})")
    if liquidity_score >= 75.0:
        top_reasons.append(f"Mật độ giao dịch on-chain ổn định ({total_ticks} ticks)")

    if spread_score < 50.0 or noise_ratio > 3.0:
        blockers.append(f"Độ nhiễu bước giá cao (Noise ratio {noise_ratio:.1f}), phí trượt giá ăn mòn lợi thế")
    if liquidity_score < 50.0:
        blockers.append(f"Thanh khoản không liên tục (Khoảng cách lệnh p95: {inter_trade_p95 / 60:.0f} phút)")
    if chopiness > 62.0:
        blockers.append(f"Thị trường dao động Sideways nhiễu (Choppiness {chopiness:.1f})")
    if not has_real_backtest:
        blockers.append("Chưa chạy kiểm định Walk-Forward Analysis (WFA) chính thức")

    # 10. Final Classification
    if dq.get("status") == DataQualityStatus.BLOCKED or market_health_score < 48.0 or spread_score < 30.0:
        classification = TradeabilityClass.DO_NOT_TRADE
    elif chopiness >= 60.0 or liquidity_score < 60.0 or spread_score < 55.0:
        classification = TradeabilityClass.NARROW_CONDITIONS
    elif has_real_backtest and tradeability_score >= 70.0 and oos_robustness is not None and oos_robustness >= 65.0:
        classification = TradeabilityClass.CAN_TRADE
    elif market_health_score >= 68.0 and dc_structure_clarity >= 65.0:
        classification = TradeabilityClass.RESEARCH_READY
    else:
        classification = TradeabilityClass.NARROW_CONDITIONS

    confidence = round(float(np.clip(market_health_score / 100.0, 0.50, 0.95)), 2)

    return {
        "symbol": symbol,
        "market_health_score": market_health_score,
        "tradeability_score": tradeability_score,
        "classification": classification,
        "meta": TRADEABILITY_META[classification],
        "confidence": confidence,
        "components": {
            "data_quality": round(float(quality_score), 1),
            "liquidity_continuity": round(float(liquidity_score), 1),
            "cost_friction_safety": round(float(spread_score), 1),
            "dc_structure_clarity": round(float(dc_structure_clarity), 1),
            "regime_stability": round(float(regime_stability), 1),
            "strategy_fit": round(float(strategy_fit), 1) if strategy_fit is not None else None,
            "oos_robustness": round(float(oos_robustness), 1) if oos_robustness is not None else None,
            "cost_resilience": round(float(cost_resilience), 1),
        },
        "top_reasons": top_reasons if top_reasons else ["Cấu trúc cơ bản ổn định"],
        "blockers": blockers,
        "data_quality_report": dq,
        "regime_report": reg,
    }
