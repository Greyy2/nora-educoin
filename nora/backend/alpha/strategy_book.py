"""Sổ chiến lược (strategy book): tham số theo CHIẾN LƯỢC, không theo tài sản; vốn phân bổ theo RỦI RO.

Nguyên tắc:
- Một chiến lược = tín hiệu (AST trên kernel) + quản lý vị thế. Một bộ tham số dùng chung cho cả vũ trụ tài sản.
- Thoát lệnh theo bội số ATR% (exit_unit="atr") để cùng tham số tự co giãn theo biến động từng tài sản:
  stop_loss_rate=2 nghĩa là SL cách giá vào 2 × ATR%(khung atr_frame) đo ở nến đã đóng lúc có tín hiệu.
- Khối lượng theo rủi ro (sizing="risk"): chạm SL mất ~risk_per_trade_pct% vốn; đòn bẩy tự hạ để thanh lý
  cách giá vào >= 1,5 × khoảng SL; trần đòn bẩy 10x (mức rủi ro đã chốt).
- Rủi ro danh mục (RiskConfig): số vị thế đồng thời, mỗi tài sản tối đa 1 vị thế, trần tổng danh nghĩa, kill switch 30%.

Chọn chiến lược (scripts/build_strategy_book.py) chạy trên CẢ vũ trụ cùng lúc (backtest danh mục), nên một
cấu hình chỉ thắng nhờ một tài sản sẽ bị loại bởi điều kiện độ phủ (đa số tài sản phải có lãi).
"""
from typing import Any, Dict, List

from backend.alpha.strategy_library import cond, f, p

UNIVERSE = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX"]
MAX_LEVERAGE = 10
BASE_RISK_PER_TRADE_PCT = 0.5   # mức chuẩn khi chọn chiến lược; mức cuối do bootstrap ngân sách MDD quyết định

RISK = {
    "max_positions": 8,          # tối đa số vị thế mở đồng thời (toàn danh mục)
    "max_per_symbol": 1,         # mỗi tài sản tối đa 1 vị thế (mọi chiến lược cộng lại) -> không cộng dồn rủi ro
    "max_gross_exposure": 3.0,   # Σ danh nghĩa / vốn <= 3
    "kill_switch_dd_pct": 30.0,  # sụt 30% từ đỉnh (MTM, điểm xấu nhất) -> đóng hết, dừng
}

GATES = {
    "min_trades": 40,             # trên cả danh mục, mỗi giai đoạn
    "min_symbols_positive": 5,    # dev1: >= 5/8 tài sản có lãi (độ phủ)
    "min_symbols_positive_dev2": 4,
    "max_mdd_pct": 30.0,
}

BASE_POSITION = {
    "market": "perp", "leverage": MAX_LEVERAGE, "exit_unit": "atr", "atr_frame": "1h", "atr_period": 14,
    "sizing": "risk", "risk_per_trade_pct": BASE_RISK_PER_TRADE_PCT, "max_notional_pct": 300.0,
    "stop_fill": "level",
    "cooldown": 60,   # phút: một nến 1h — tránh vào lại ngay trên cùng trạng thái tín hiệu cũ sau khi vừa thoát (SL/trailing)
}

_UP_1H = (f("1h", "ema_50"), ">", f("1h", "ema_200"))
_DN_1H = (f("1h", "ema_50"), "<", f("1h", "ema_200"))

CANDIDATES: List[Dict[str, Any]] = [
    {
        "id": "trend_long", "family": "Theo xu hướng", "side": "LONG",
        "description": "1h EMA50 > EMA200, ADX14 > ngưỡng, 15m phá đỉnh 20 nến trước. Thoát: SL + trailing theo ATR.",
        "tree": cond(_UP_1H, (f("1h", "adx_14"), ">", p("adx_min", 20)), (f("15m", "close"), ">", f("15m", "dch_20"))),
        "position": {},
        "space": {"sig.adx_min": [20, 25, 30], "stop_loss_rate": [1.5, 2.5, 3.5], "trailing_stop": [2.0, 3.0, 4.5],
                  "trailing_activation_pct": [0.0, 1.0], "timeout": [0, 4320]},
    },
    {
        "id": "trend_short", "family": "Theo xu hướng", "side": "SHORT",
        "description": "Đối xứng trend_long.",
        "tree": cond(_DN_1H, (f("1h", "adx_14"), ">", p("adx_min", 20)), (f("15m", "close"), "<", f("15m", "dcl_20"))),
        "position": {},
        "space": {"sig.adx_min": [20, 25, 30], "stop_loss_rate": [1.5, 2.5, 3.5], "trailing_stop": [2.0, 3.0, 4.5],
                  "trailing_activation_pct": [0.0, 1.0], "timeout": [0, 4320]},
    },
    {
        "id": "breakout_4h_long", "family": "Theo xu hướng (Turtle)", "side": "LONG",
        "description": "4h EMA50 > EMA200 và close 4h phá đỉnh 20 nến 4h trước. ATR khung 4h.",
        "tree": cond((f("4h", "ema_50"), ">", f("4h", "ema_200")), (f("4h", "close"), ">", f("4h", "dch_20"))),
        "position": {"atr_frame": "4h"},
        "space": {"stop_loss_rate": [1.5, 2.0, 3.0], "trailing_stop": [2.0, 3.0, 4.0],
                  "trailing_activation_pct": [0.0, 1.0], "timeout": [0, 10080]},
    },
    {
        "id": "breakout_4h_short", "family": "Theo xu hướng (Turtle)", "side": "SHORT",
        "description": "Đối xứng breakout_4h_long.",
        "tree": cond((f("4h", "ema_50"), "<", f("4h", "ema_200")), (f("4h", "close"), "<", f("4h", "dcl_20"))),
        "position": {"atr_frame": "4h"},
        "space": {"stop_loss_rate": [1.5, 2.0, 3.0], "trailing_stop": [2.0, 3.0, 4.0],
                  "trailing_activation_pct": [0.0, 1.0], "timeout": [0, 10080]},
    },
    {
        "id": "momentum_long", "family": "Theo đà", "side": "LONG",
        "description": "1h ROC24 > ngưỡng % và 15m close > EMA20 15m.",
        "tree": cond((f("1h", "roc_24"), ">", p("roc_min", 3)), (f("15m", "close"), ">", f("15m", "ema_20"))),
        "position": {},
        "space": {"sig.roc_min": [3, 5, 8], "stop_loss_rate": [1.5, 2.5, 3.5], "trailing_stop": [2.0, 3.0, 4.5],
                  "trailing_activation_pct": [0.0, 1.0], "timeout": [1440, 4320]},
    },
    {
        "id": "reversion_long", "family": "Bắt hồi (có SL)", "side": "LONG",
        "description": "5m RSI14 < ngưỡng, dưới Bollinger dưới, regime đi ngang (1h ER20 < ngưỡng). TP/SL theo ATR.",
        "tree": cond((f("5m", "rsi_14"), "<", p("rsi_lo", 25)), (f("5m", "close"), "<", f("5m", "bbl_20_2")),
                     (f("1h", "er_20"), "<", p("er_max", 0.3))),
        "position": {},
        "space": {"sig.rsi_lo": [20, 25, 30], "sig.er_max": [0.2, 0.3], "stop_loss_rate": [1.0, 1.5, 2.5],
                  "take_profit_rate": [0.75, 1.0, 1.5, 2.5], "timeout": [240, 1440]},
    },
    {
        "id": "reversion_short", "family": "Bắt hồi (có SL)", "side": "SHORT",
        "description": "Đối xứng reversion_long.",
        "tree": cond((f("5m", "rsi_14"), ">", p("rsi_hi", 75)), (f("5m", "close"), ">", f("5m", "bbu_20_2")),
                     (f("1h", "er_20"), "<", p("er_max", 0.3))),
        "position": {},
        "space": {"sig.rsi_hi": [70, 75, 80], "sig.er_max": [0.2, 0.3], "stop_loss_rate": [1.0, 1.5, 2.5],
                  "take_profit_rate": [0.75, 1.0, 1.5, 2.5], "timeout": [240, 1440]},
    },
]


def materialize(candidate: Dict[str, Any], params: Dict[str, Any], **position_overrides) -> Dict[str, Any]:
    """Chiến lược cụ thể cho PortfolioEngine: thay ngưỡng tín hiệu, ghép tham số vị thế."""
    from backend.alpha.params_template import resolve_placeholders, split_params
    signal, position = split_params(dict(params))
    return {
        "id": candidate["id"], "side": candidate["side"],
        "tree": resolve_placeholders(candidate["tree"], signal),
        "position": {**BASE_POSITION, **candidate.get("position", {}), **position, **position_overrides},
        "signal_params": signal,
    }


def perp_symbols(universe: List[str] = None) -> List[str]:
    return [f"{s}@perp" for s in (universe or UNIVERSE)]
