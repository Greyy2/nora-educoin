"""Analyst Insight Engine Module
Converts quantitative market health, Directional Change (DC) metrics,
scaling laws, and regime diagnostics into professional, analyst-grade
narrative insights (WHAT / WHY / SO-WHAT), reason tags, and why-not-trade diagnostics.
"""
from typing import Dict, Any, List, Optional

try:
    from backend.core.research.market_health import compute_market_health_score, TradeabilityClass
    from backend.core.research.regime_classifier import RegimeType
except ImportError:
    from nora.backend.core.research.market_health import compute_market_health_score, TradeabilityClass
    from nora.backend.core.research.regime_classifier import RegimeType


def generate_market_insights(
    symbol: str,
    health_data: Optional[Dict[str, Any]] = None,
    dc_data: Optional[Dict[str, Any]] = None,
    scaling_law_data: Optional[Dict[str, Any]] = None,
    playbook_data: Optional[Dict[str, Any]] = None,
    timeframe: str = "1h",
    data_root: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generates analyst-grade narrative report (WHAT / WHY / SO-WHAT),
    reason tags, and why-not-trade explanations for a DEX asset.
    """
    if health_data is None:
        health_data = compute_market_health_score(
            symbol,
            timeframe=timeframe,
            dc_data=dc_data,
            scaling_law_data=scaling_law_data,
            data_root=data_root,
        )

    classification = health_data.get("classification", TradeabilityClass.NEEDS_MORE_DATA)
    comp = health_data.get("components", {})
    dq = health_data.get("data_quality_report", {})
    dq_m = dq.get("metrics", {})
    reg = health_data.get("regime_report", {})
    cur_regime = reg.get("current_regime", "RANGE_CHOP_REGIME")
    reg_name = reg.get("regime_info", {}).get("name", "Đi Ngang")
    reg_metrics = reg.get("metrics", {})

    vol_pct = float(reg_metrics.get("realized_volatility_pct", 50.0))
    chopiness = float(reg_metrics.get("chopiness_score", 50.0))

    best_m = dc_data.get("best_metrics", {}) if dc_data else {}
    best_theta_pct = str(dc_data.get("best_theta_pct", "2.0%")) if dc_data else "2.0%"
    os_med = float(best_m.get("overshoot_ratio_median", 1.0))
    deficit_rate = float(best_m.get("deficit_rate", 0.30))
    event_count = int(best_m.get("event_count", 0))

    scaling_score = float(scaling_law_data.get("scaling_law_score", 50.0)) if scaling_law_data else 50.0
    scaling_interp = scaling_law_data.get("interpretation", "") if scaling_law_data else ""

    slippage_pct = float(dq_m.get("estimated_slippage_pct", 0.25))
    noise_ratio = float(dq_m.get("noise_ratio", 1.5))
    inter_trade_p95 = float(dq_m.get("inter_trade_p95_sec", 0.0))
    zero_vol_pct = float(dq_m.get("zero_volume_pct", 0.0))
    total_ticks = int(dq_m.get("total_ticks", 0))

    pb = playbook_data or {}
    pb_name = pb.get("meta", {}).get("name", "Chờ phân tích")
    pb_title = pb.get("meta", {}).get("title", pb_name)

    reason_tags: List[Dict[str, str]] = []
    why_not_trade: List[str] = []

    # 1. Evaluate Reason Tags & Why-Not-Trade Issues
    if zero_vol_pct > 20.0:
        reason_tags.append({"tag": "low liquidity", "type": "danger", "label": "Thanh khoản mỏng"})
        why_not_trade.append(f"Tỷ lệ nến không có volume đạt {zero_vol_pct:.1f}%, nguy cơ trượt giá và kẹt lệnh.")

    if inter_trade_p95 > 3600:
        reason_tags.append({"tag": "trade gap", "type": "warning", "label": "Gap lệnh lớn"})
        why_not_trade.append(f"Khoảng cách giữa các giao dịch p95 lên tới {inter_trade_p95 / 60:.0f} phút, dòng tiền không liên tục.")

    if noise_ratio > 2.8:
        reason_tags.append({"tag": "high spread", "type": "danger", "label": "Spread & nhiễu cao"})
        why_not_trade.append(f"Độ nhiễu bước giá (noise ratio: {noise_ratio:.1f}) cao, trượt giá ước tính {slippage_pct * 100:.2f}% ăn mòn lợi thế.")

    if chopiness > 60.0:
        reason_tags.append({"tag": "unstable regime", "type": "warning", "label": "Chop / Đi ngang"})
        why_not_trade.append(f"Thị trường dao động Sideways nhiễu (Choppiness {chopiness:.1f}), các lệnh Breakout dễ dính False Break.")

    if os_med >= 1.25 and chopiness < 55.0:
        reason_tags.append({"tag": "strong momentum", "type": "success", "label": "Quán tính mạnh"})

    if deficit_rate >= 0.40:
        reason_tags.append({"tag": "overshoot fade", "type": "info", "label": "Sóng rướn hụt hơi"})

    if scaling_score >= 70.0:
        reason_tags.append({"tag": "scaling law fit", "type": "success", "label": "Quy luật DC chuẩn"})

    # 2. Structured Narrative: WHAT / WHY / SO-WHAT
    if classification == TradeabilityClass.CAN_TRADE:
        what_text = f"Thị trường {symbol} đạt Market Health {health_data.get('market_health_score', 0):.1f}/100, dữ liệu sạch ({total_ticks} ticks), hiện đang ở trạng thái {reg_name}."
        why_text = f"Ngưỡng tối ưu θ* = {best_theta_pct} xác lập {event_count} biến cố DC với tỷ lệ sóng rướn vượt trội (Overshoot median: {os_med:.2f}). {scaling_interp} Chi phí trượt giá ước tính {slippage_pct * 100:.2f}% hoàn toàn nằm trong biên độ chịu đựng."
        so_what_text = f"Khuyến nghị CẤP VỐN CHỦ LỰC. Triển khai Playbook '{pb_title}', vào lệnh theo tín hiệu DC tại ngưỡng {best_theta_pct} và bám theo Extreme Price mới."
        recommendation = f"Cấp vốn giao dịch theo Playbook {pb_name}."

    elif classification == TradeabilityClass.RESEARCH_READY:
        what_text = f"Thị trường {symbol} có chất lượng dữ liệu tốt (Health: {health_data.get('market_health_score', 0):.1f}), cấu trúc vi mô vững chắc, hiện ở trạng thái {reg_name}."
        why_text = f"Đã tìm thấy ngưỡng tối ưu θ* = {best_theta_pct} với {event_count} biến cố DC. Quy luật phân phối sóng rướn có độ ổn định cao ({scaling_interp}). Chưa có kết quả Walk-Forward Analysis (WFA) kiểm định chiến lược thực tế."
        so_what_text = f"SẴN SÀNG CHO NGHIÊN CỨU & TEST. Đưa tài sản vào danh mục sinh Alpha tự động và chạy Backtest/WFA theo Playbook '{pb_title}' trước khi cấp vốn thật."
        recommendation = f"Đưa vào pipeline sinh Alpha và chạy Backtest WFA cho Playbook {pb_name}."

    elif classification == TradeabilityClass.NARROW_CONDITIONS:
        what_text = f"Thị trường {symbol} chỉ có lợi thế trong một số điều kiện biên nhất định (Health: {health_data.get('market_health_score', 0):.1f}), hiện ở trạng thái {reg_name}."
        why_text = f"Khi thị trường rơi vào vùng dao động Sideways (Choppiness {chopiness:.1f}) hoặc khoảng cách giao dịch giãn rộng ({inter_trade_p95 / 60:.0f} phút), phí và trượt giá ({slippage_pct * 100:.2f}%) sẽ triệt tiêu lợi nhuận."
        so_what_text = f"CHỈ GIAO DỊCH CÓ ĐIỀU KIỆN. Bắt buộc sử dụng bộ lọc xác nhận Regime, giảm 50% quy mô vốn và ưu tiên Playbook '{pb_title}'."
        recommendation = f"Giao dịch phòng thủ (size 50%) kèm bộ lọc Regime khắt khe."

    elif classification == TradeabilityClass.DO_NOT_TRADE:
        what_text = f"Thị trường {symbol} hiện KHÔNG ĐỦ ĐIỀU KIỆN AN TOÀN để triển khai chiến lược định lượng (Health: {health_data.get('market_health_score', 0):.1f})."
        why_text = f"Độ nhiễu bước giá quá lớn (Noise ratio: {noise_ratio:.1f}), trượt giá dự báo {slippage_pct * 100:.2f}% hoặc thanh khoản mỏng. Lợi thế thống kê (expectancy) bị âm hoàn toàn sau khi trừ chi phí AMM."
        so_what_text = "TUYỆT ĐỐI KHÔNG CẤP VỐN. Đưa tài sản vào danh mục Blacklist theo dõi, chỉ xem xét lại khi volume và mật độ giao dịch tăng trưởng bền vững."
        recommendation = "Dừng giao dịch / Blacklist. Chuyển nguồn vốn sang các cặp tài sản có cấu trúc tốt hơn."

    else:  # NEEDS_MORE_DATA
        what_text = f"Thị trường {symbol} chưa tích lũy đủ chu kỳ dữ liệu lịch sử ({total_ticks} ticks)."
        why_text = "Mẫu dữ liệu quá mỏng để xác lập quy luật Scaling Law hay kiểm định độ bền của sóng rướn DC."
        so_what_text = "TIẾP TỤC THU THẬP DỮ LIỆU. Giữ tài sản trong hàng đợi crawler tự động thêm 1-2 tuần trước khi đưa vào phân tích chuyên sâu."
        recommendation = "Chờ thu thập thêm dữ liệu tick on-chain."

    return {
        "symbol": symbol,
        "classification": classification,
        "narrative": {
            "headline": f"Báo cáo phân tích chuyên sâu {symbol}: {health_data.get('meta', {}).get('title', '')}",
            "what": what_text,
            "why": why_text,
            "so_what": so_what_text,
            "summary_recommendation": recommendation,
        },
        "reason_tags": reason_tags,
        "why_not_trade": why_not_trade if why_not_trade else ["Không phát hiện rủi ro ma sát lớn, thị trường thông thoáng."],
        "playbook": pb,
        "tradeability_score": health_data.get("tradeability_score", 0.0),
        "market_health_score": health_data.get("market_health_score", 0.0),
    }
