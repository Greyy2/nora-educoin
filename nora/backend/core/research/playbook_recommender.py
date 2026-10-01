"""Strategy Playbook Recommender Module
Maps quantitative market health, Directional Change (DC) structure,
scaling regularity, and regime diagnosis into prescriptive trading playbooks:
1. DC_MOMENTUM_FOLLOWING
2. VOL_EXPANSION_BREAKOUT
3. RANGE_MEAN_REVERSION
4. DC_OVERSHOOT_FADE
5. NO_STRATEGY_FIT
"""
from typing import Dict, Any, List, Optional


class PlaybookType:
    DC_MOMENTUM_FOLLOWING = "DC_MOMENTUM_FOLLOWING"
    VOL_EXPANSION_BREAKOUT = "VOL_EXPANSION_BREAKOUT"
    RANGE_MEAN_REVERSION = "RANGE_MEAN_REVERSION"
    DC_OVERSHOOT_FADE = "DC_OVERSHOOT_FADE"
    NO_STRATEGY_FIT = "NO_STRATEGY_FIT"


PLAYBOOK_META = {
    PlaybookType.DC_MOMENTUM_FOLLOWING: {
        "name": "DC Momentum Following",
        "title": "Bám Theo Sóng Quán Tính DC",
        "badge": "success",
        "color": "#10b981",
        "summary": "Khai thác sóng rướn (Overshoot) có quán tính mạnh sau khi xác nhận biến cố DC.",
    },
    PlaybookType.VOL_EXPANSION_BREAKOUT: {
        "name": "Volatility Expansion Breakout",
        "title": "Breakout Biến Động Mở Rộng",
        "badge": "warning",
        "color": "#f59e0b",
        "summary": "Đón đầu nhịp bùng nổ khi biên độ giá và mật độ giao dịch on-chain tăng vọt.",
    },
    PlaybookType.RANGE_MEAN_REVERSION: {
        "name": "Range Mean Reversion",
        "title": "Đánh Đảo Chiều Về Trục Cân Bằng",
        "badge": "info",
        "color": "#06b6d4",
        "summary": "Khai thác các nhịp dao động quanh trục trung tâm trong vùng biên độ rõ ràng.",
    },
    PlaybookType.DC_OVERSHOOT_FADE: {
        "name": "DC Overshoot Fade",
        "title": "Đánh Chặn Sóng Rướn Hụt Hơi",
        "badge": "primary",
        "color": "#8b5cf6",
        "summary": "Bắt đỉnh/đáy đảo chiều khi sóng rướn kiệt sức ở vùng nén biên độ (Overshoot Deficit).",
    },
    PlaybookType.NO_STRATEGY_FIT: {
        "name": "No Strategy Fit",
        "title": "Không Phù Hợp Chiến Lược Nào",
        "badge": "danger",
        "color": "#ef4444",
        "summary": "Độ nhiễu, phí hoặc trượt giá quá cao làm triệt tiêu hoàn toàn lợi thế thống kê.",
    },
}


def recommend_strategy_playbook(
    symbol: str,
    market_classification: str,
    market_health_score: float,
    dc_data: Optional[Dict[str, Any]] = None,
    regime_data: Optional[Dict[str, Any]] = None,
    data_quality_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Recommends optimal quantitative playbook for a given asset based on
    microstructure quality, DC metrics, and regime structure.
    """
    best_m = dc_data.get("best_metrics", {}) if dc_data else {}
    best_theta = float(dc_data.get("best_theta", 0.02)) if dc_data else 0.02
    best_theta_pct = str(dc_data.get("best_theta_pct", f"{best_theta * 100:.1f}%")) if dc_data else "2.0%"

    os_ratio = float(best_m.get("overshoot_ratio_median", 1.0))
    deficit_rate = float(best_m.get("deficit_rate", 0.30))
    fade_rate = float(best_m.get("fade_signal_rate", 0.0))
    cost_adj_os = float(best_m.get("cost_adjusted_os_ratio", 0.8))
    dir_persist = float(best_m.get("directional_persistence", 0.50))

    cur_regime = regime_data.get("current_regime", "RANGE_CHOP_REGIME") if regime_data else "RANGE_CHOP_REGIME"
    reg_metrics = regime_data.get("metrics", {}) if regime_data else {}
    chopiness = float(reg_metrics.get("chopiness_score", 50.0))
    vol_pct = float(reg_metrics.get("realized_volatility_pct", 50.0))
    atr_ratio = float(reg_metrics.get("atr_ratio", 1.0))

    dq_metrics = data_quality_data.get("metrics", {}) if data_quality_data else {}
    slippage_pct = float(dq_metrics.get("estimated_slippage_pct", 0.25))
    noise_ratio = float(dq_metrics.get("noise_ratio", 1.5))
    inter_trade_p95 = float(dq_metrics.get("inter_trade_p95_sec", 0.0))

    # 1. Rule out: Blacklist / Needs More Data
    if market_classification == "DO_NOT_TRADE" or market_health_score < 45.0:
        return {
            "symbol": symbol,
            "playbook_type": PlaybookType.NO_STRATEGY_FIT,
            "meta": PLAYBOOK_META[PlaybookType.NO_STRATEGY_FIT],
            "confidence": 0.88,
            "recommended_theta": best_theta,
            "recommended_theta_pct": best_theta_pct,
            "allowed_regimes": [],
            "blocked_regimes": ["ALL"],
            "entry_conditions": ["KHÔNG VÀO LỆNH: Thị trường không có edge sau phí và trượt giá"],
            "risk_notes": [
                f"Độ nhiễu giá (noise ratio {noise_ratio:.1f}) và trượt giá ước tính ({slippage_pct * 100:.2f}%) quá cao",
                "Chi phí giao dịch và false break ăn mòn toàn bộ lợi nhuận kỳ vọng",
            ],
            "why_fit": "Không có chiến lược nào khả thi trên thị trường có thanh khoản ngắt quãng hoặc nhiễu lớn.",
        }

    if market_classification == "NEEDS_MORE_DATA":
        return {
            "symbol": symbol,
            "playbook_type": PlaybookType.NO_STRATEGY_FIT,
            "meta": PLAYBOOK_META[PlaybookType.NO_STRATEGY_FIT],
            "confidence": 0.60,
            "recommended_theta": best_theta,
            "recommended_theta_pct": best_theta_pct,
            "allowed_regimes": [],
            "blocked_regimes": ["ALL"],
            "entry_conditions": ["Tạm thời quan sát thêm: Tiếp tục thu thập dữ liệu on-chain"],
            "risk_notes": ["Dữ liệu lịch sử chưa đủ để kiểm định độ bền của chiến lược"],
            "why_fit": "Chưa đủ số lượng giao dịch để đưa ra khuyến nghị chiến lược đáng tin cậy.",
        }

    # 2. Evaluate Playbook 4: DC Overshoot Fade
    # Triggered when scale compression and overshoot deficit clustering are prominent
    if (fade_rate >= 0.12 or (deficit_rate >= 0.40 and chopiness >= 52.0)) and cost_adj_os >= 0.2:
        return {
            "symbol": symbol,
            "playbook_type": PlaybookType.DC_OVERSHOOT_FADE,
            "meta": PLAYBOOK_META[PlaybookType.DC_OVERSHOOT_FADE],
            "confidence": round(min(0.85, 0.60 + fade_rate * 1.5), 2),
            "recommended_theta": best_theta,
            "recommended_theta_pct": best_theta_pct,
            "allowed_regimes": ["OVERSHOOT_DEFICIT_REGIME", "RANGE_CHOP_REGIME"],
            "blocked_regimes": ["DC_MOMENTUM_REGIME", "LIQUIDITY_DRY_UP_REGIME"],
            "entry_conditions": [
                f"Xác nhận biến cố DC tại ngưỡng tối ưu θ* = {best_theta_pct}",
                "Tỷ lệ nén biên độ δ / R > 0.25 kết hợp tỷ lệ sóng rướn OS < 0.85 (Overshoot Deficit)",
                "Đặt stop-loss ngay sát điểm cực trị (Extreme Price) vừa tạo lập",
                "Chốt lời từng phần tại mốc hồi quy 50% của con sóng",
            ],
            "risk_notes": [
                "Tuyệt đối không fade khi thị trường đang có dòng tiền mua gom liên tục (Volume Spike > 3x)",
                f"Đảm bảo lệnh trượt giá không vượt quá {slippage_pct * 100:.2f}%",
            ],
            "why_fit": f"Tỷ lệ sóng rướn hụt hơi đạt {deficit_rate * 100:.0f}%, xuất hiện tín hiệu đảo chiều kiệt sức rõ ràng.",
        }

    # 3. Evaluate Playbook 1: DC Momentum Following
    # Strong momentum with persistent overshoot and clean trend
    if os_ratio >= 1.20 and chopiness < 56.0 and dir_persist >= 0.50 and cost_adj_os >= 0.5:
        return {
            "symbol": symbol,
            "playbook_type": PlaybookType.DC_MOMENTUM_FOLLOWING,
            "meta": PLAYBOOK_META[PlaybookType.DC_MOMENTUM_FOLLOWING],
            "confidence": round(min(0.90, 0.65 + (os_ratio - 1.2) * 0.25), 2),
            "recommended_theta": best_theta,
            "recommended_theta_pct": best_theta_pct,
            "allowed_regimes": ["DC_MOMENTUM_REGIME", "VOL_EXPANSION_REGIME"],
            "blocked_regimes": ["RANGE_CHOP_REGIME", "LIQUIDITY_DRY_UP_REGIME"],
            "entry_conditions": [
                f"Khớp lệnh thuận xu hướng ngay khi biến cố DC hoàn thành tại ngưỡng θ* = {best_theta_pct}",
                "Đặt trailing-stop bám theo Extreme Price mới",
                "Duy trì vị thế khi tỷ lệ Overshoot tiếp tục mở rộng",
            ],
            "risk_notes": [
                "Hủy vị thế ngay nếu tỷ lệ nén δ / R tiệm cận kháng cự/hỗ trợ lớn của Range",
                "Không giữ lệnh qua các giai đoạn thanh khoản ngắt quãng (inter-trade gap > 1h)",
            ],
            "why_fit": f"Quán tính sóng rướn mạnh (OS Ratio: {os_ratio:.2f}), quán tính vượt trội so với chi phí giao dịch.",
        }

    # 4. Evaluate Playbook 2: Volatility Expansion Breakout
    if cur_regime == "VOL_EXPANSION_REGIME" or (atr_ratio >= 1.30 and vol_pct >= 100.0):
        return {
            "symbol": symbol,
            "playbook_type": PlaybookType.VOL_EXPANSION_BREAKOUT,
            "meta": PLAYBOOK_META[PlaybookType.VOL_EXPANSION_BREAKOUT],
            "confidence": round(min(0.82, 0.55 + (atr_ratio - 1.0) * 0.25), 2),
            "recommended_theta": best_theta,
            "recommended_theta_pct": best_theta_pct,
            "allowed_regimes": ["VOL_EXPANSION_REGIME"],
            "blocked_regimes": ["LIQUIDITY_DRY_UP_REGIME", "RANGE_CHOP_REGIME"],
            "entry_conditions": [
                "Vào lệnh Breakout khi giá phá vỡ vùng tích lũy với volume on-chain tăng gấp 2 lần mức bình quân",
                "Yêu cầu xác nhận bằng tối thiểu 3 biến cố DC liên tiếp cùng chiều",
            ],
            "risk_notes": [
                "Cần stop-loss chặt để phòng ngừa False Breakout trong pool AMM",
                "Hạn chế kích thước lệnh để tránh trượt giá khi bùng nổ biến động",
            ],
            "why_fit": f"Biên độ giá đang trong pha bùng nổ mạnh mẽ (ATR ratio: {atr_ratio:.2f}, Vol: {vol_pct:.1f}%).",
        }

    # 5. Evaluate Playbook 3: Range Mean Reversion
    if chopiness >= 58.0 and slippage_pct <= 0.40:
        return {
            "symbol": symbol,
            "playbook_type": PlaybookType.RANGE_MEAN_REVERSION,
            "meta": PLAYBOOK_META[PlaybookType.RANGE_MEAN_REVERSION],
            "confidence": 0.65,
            "recommended_theta": best_theta,
            "recommended_theta_pct": best_theta_pct,
            "allowed_regimes": ["RANGE_CHOP_REGIME"],
            "blocked_regimes": ["DC_MOMENTUM_REGIME", "VOL_EXPANSION_REGIME", "LIQUIDITY_DRY_UP_REGIME"],
            "entry_conditions": [
                "Vào lệnh đảo chiều tại các biên ngoài (Extreme Bands) của Range hộp dao động",
                "Chốt lời nhanh chóng tại trục giá trung tâm (Mean), không gồng lãi dài",
            ],
            "risk_notes": [
                "Chỉ trade khi trượt giá AMM duy trì mức thấp",
                "Cắt lỗ ngay khi giá bứt phá dứt khoát ra khỏi Range hộp",
            ],
            "why_fit": f"Chỉ số Choppiness cao ({chopiness:.1f}), biên độ dao động nén quanh trục cân bằng.",
        }

    # Fallback to Momentum or Reversal depending on OS ratio
    default_pb = PlaybookType.DC_MOMENTUM_FOLLOWING if os_ratio >= 1.05 else PlaybookType.DC_OVERSHOOT_FADE
    return {
        "symbol": symbol,
        "playbook_type": default_pb,
        "meta": PLAYBOOK_META[default_pb],
        "confidence": 0.60,
        "recommended_theta": best_theta,
        "recommended_theta_pct": best_theta_pct,
        "allowed_regimes": [cur_regime],
        "blocked_regimes": ["LIQUIDITY_DRY_UP_REGIME"],
        "entry_conditions": [f"Vào lệnh có chọn lọc theo tín hiệu DC tại ngưỡng θ* = {best_theta_pct}"],
        "risk_notes": ["Áp dụng quản trị rủi ro nghiêm ngặt, giảm 50% quy mô vị thế"],
        "why_fit": f"Đặc tính thị trường phù hợp mức trung bình với {PLAYBOOK_META[default_pb]['name']}.",
    }
