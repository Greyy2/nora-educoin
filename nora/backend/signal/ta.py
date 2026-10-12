"""TradingView Standard & Global TA Mappings (P15 Clean Syntax).

Cung cấp ánh xạ và các alias chuẩn quốc tế (TradingView / Sova style)
cho bộ biên dịch Alpha DSL của Nora, loại bỏ hoàn toàn các tiền tố XNO cũ.
"""
from typing import Dict, Tuple

# Ánh xạ hàm toàn cục và namespace `ta.*` sang bảng FEATURES hoặc OPS của Nora
GLOBAL_TA_FUNCS: Dict[str, Tuple[str, str]] = {
    # ── 1. Tín hiệu giao cắt & quan hệ (TradingView ta.cross*) ──
    "crossover": ("op", "crossed_above"),
    "crossunder": ("op", "crossed_below"),
    "cross": ("op", "crossed"),
    "crossed_above": ("op", "crossed_above"),
    "crossed_below": ("op", "crossed_below"),
    "crossed": ("op", "crossed"),

    # ── 2. Chỉ báo kỹ thuật phổ biến (TradingView ta.*) ──
    "ema": ("feat", "ema"),
    "sma": ("feat", "sma"),
    "rsi": ("feat", "rsi"),
    "atr": ("feat", "atr"),
    "macd": ("feat", "macd"),
    "bbands": ("feat", "bollinger_bands"),
    "bollinger": ("feat", "bollinger_bands"),
    "bollinger_bands": ("feat", "bollinger_bands"),
    "stoch": ("feat", "stochastic"),
    "stochastic": ("feat", "stochastic"),
    "adx": ("feat", "adx"),
    "cci": ("feat", "cci"),
    "vwap": ("feat", "vwap"),
    "williams_r": ("feat", "williams_r"),
    "mfi": ("feat", "mfi"),
    "supertrend": ("feat", "supertrend"),
    "keltner": ("feat", "keltner_channels"),
    "donchian": ("feat", "donchian_channels"),

    # ── 3. Thống kê & Chuỗi thời gian ──
    "highest": ("feat", "rolling_max"),
    "lowest": ("feat", "rolling_min"),
    "rolling_max": ("feat", "rolling_max"),
    "rolling_min": ("feat", "rolling_min"),
    "rolling_mean": ("feat", "rolling_mean"),
    "rolling_std": ("feat", "rolling_std"),
    "rolling_sum": ("feat", "rolling_sum"),
    "stddev": ("feat", "stddev"),
    "returns": ("feat", "returns"),
    "zscore": ("feat", "zscore"),

    # ── 4. Toán tử chuỗi (TradingView ta.change, ta.barssince...) ──
    "change": ("op", "diff"),
    "diff": ("op", "diff"),
    "pct_change": ("op", "pct_change"),
    "previous": ("op", "previous"),
    "shift": ("op", "shift"),
    "bars_since": ("op", "bars_since"),
    "barssince": ("op", "bars_since"),
    "value_when": ("op", "value_when"),
    "valuewhen": ("op", "value_when"),
    "rising": ("op", "rising"),
    "falling": ("op", "falling"),
    "where": ("op", "where"),
    "fillna": ("op", "fillna"),
    "ffill": ("op", "ffill"),
    "clip": ("op", "clip"),
}

# Các cột nến chuẩn thế giới
OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")

# Ánh xạ tên tham số rủi ro chuẩn TradingView / Sova sang engine
RISK_PARAM_MAP = {
    "stop_loss_pct": "stop_loss_rate",
    "stop_loss": "stop_loss_rate",
    "take_profit_pct": "take_profit_rate",
    "take_profit": "take_profit_rate",
    "trailing_stop_pct": "trailing_stop",
    "trailing_pct": "trailing_stop",
    "trailing_activation": "trailing_activation_pct",
    "risk_pct": "risk_per_trade_pct",
    "risk_per_trade": "risk_per_trade_pct",
}
