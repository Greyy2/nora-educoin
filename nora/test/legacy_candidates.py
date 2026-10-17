"""9 định nghĩa chiến lược cũ (trước khi gom về 3 chiến lược KEMA / Sideway / DCA) — CHỈ cho test: golden snapshot, kiểm parity kernel,
test cơ chế preset / chế độ chạy viết trên các id này. conftest đăng ký chúng vào optimize.book.build.EXTRA_CANDIDATES cho mọi test."""
from typing import Any, Dict, List

from backend.analys.param import exit_risk_schema as _exit_risk_schema, schema_choice as _choice, schema_flt as _flt, schema_int as _int
from backend.alpha.compile import calc, cond, cross_over, cross_under, f, tree_p

_TF_SLOW = ("15m", "1h", "4h", "24h")     # khung xu hướng / bộ lọc regime
_TF_FAST = ("1m", "5m", "15m", "1h")      # khung điểm vào lệnh

# Lược đồ/cây Keltner + reversion của 3 chiến lược cũ — chuyển từ book.py cũ của thư mục strategy trong core (P9.9: chiến lược hệ thống nay viết bằng DSL trong
# data/alpha/strategies/*.py; các mảnh này chỉ còn phục vụ 9 định nghĩa cũ bên dưới).
def _keltner_schema():
    return {
        "sig.signal_tf": _choice("signal", "Khung tín hiệu", "4h", _TF_SLOW, "Khung nến tính kênh Keltner và xét điểm cắt."),
        "sig.ema_n": _int("signal", "Chu kỳ EMA (đường giữa)", 30, 5, 200, "nến", "EMA đường giữa của kênh Keltner."),
        "sig.atr_n": _int("signal", "Chu kỳ ATR của kênh", 14, 5, 50, "nến", "ATR (Wilder) đo độ rộng kênh."),
        "sig.k_up": _flt("signal", "Hệ số dải trên", 2.0, 0.5, 5.0, 0.1, "× ATR", "Dải trên = EMA + hệ số × ATR."),
        "sig.k_dn": _flt("signal", "Hệ số dải dưới", 2.0, 0.5, 5.0, 0.1, "× ATR", "Dải dưới = EMA − hệ số × ATR."),
        **_exit_risk_schema(3.0, 0.0, 0.0, 0.0, 0, "4h"),
    }


def _keltner_bands():
    """(dải trên, dải dưới) của kênh Keltner trên khung tín hiệu: EMA(ema_n) ± k × ATR(atr_n) — kiểu KEMA."""
    atr = f("{signal_tf}", "atr_{atr_n}")
    up = {**f("{signal_tf}", "ema_{ema_n}"), "add": calc(atr, "*", tree_p("k_up", 2.0))}
    dn = {**f("{signal_tf}", "ema_{ema_n}"), "subtract": calc(atr, "*", tree_p("k_dn", 2.0))}
    return up, dn


_KC_UP, _KC_DN = _keltner_bands()
_KC_CLOSE = f("{signal_tf}", "close")


def _reversion_schema(side_key, side_default, side_lo, side_hi, side_label):
    return {
        "sig.entry_tf": _choice("signal", "Khung điểm vào", "5m", _TF_FAST, "Khung nến tính RSI và dải Bollinger."),
        "sig.rsi_n": _int("signal", "Chu kỳ RSI", 14, 2, 50, "nến", "Chu kỳ RSI (Wilder)."),
        side_key: _flt("signal", side_label, side_default, side_lo, side_hi, 1.0, "", "Ngưỡng RSI kích hoạt bắt hồi."),
        "sig.bb_n": _int("signal", "Chu kỳ Bollinger", 20, 5, 100, "nến", "Chu kỳ đường giữa của dải Bollinger."),
        "sig.bb_k": _flt("signal", "Độ rộng Bollinger (k)", 2.0, 1.0, 4.0, 0.1, "σ", "Dải cách đường giữa k độ lệch chuẩn."),
        "sig.regime_tf": _choice("signal", "Khung regime", "1h", _TF_SLOW, "Khung đo mức đi ngang bằng Efficiency Ratio."),
        "sig.er_n": _int("signal", "Chu kỳ ER", 20, 5, 100, "nến", "Chu kỳ Efficiency Ratio (1 = xu hướng, 0 = đi ngang)."),
        "sig.er_max": _flt("signal", "Ngưỡng ER tối đa", 0.3, 0.1, 0.6, 0.05, "", "Chỉ bắt hồi khi ER thấp hơn mức này (thị trường đi ngang)."),
        **_exit_risk_schema(1.5, 1.5, 0.0, 0.0, 1440, "1h"),
    }





def _trend_schema(sl, trail, act, timeout):
    return {
        "sig.trend_tf": _choice("signal", "Khung xu hướng", "1h", _TF_SLOW, "Khung tính EMA và ADX xác nhận xu hướng."),
        "sig.ema_fast": _int("signal", "EMA nhanh", 50, 5, 100, "nến", "Chu kỳ EMA nhanh (phải nhỏ hơn EMA chậm)."),
        "sig.ema_slow": _int("signal", "EMA chậm", 200, 20, 500, "nến", "Chu kỳ EMA chậm; EMA nhanh nằm trên/dưới nó quyết định chiều xu hướng."),
        "sig.adx_n": _int("signal", "Chu kỳ ADX", 14, 5, 50, "nến", "Chu kỳ ADX đo độ mạnh xu hướng."),
        "sig.adx_min": _flt("signal", "Ngưỡng ADX tối thiểu", 20.0, 10.0, 40.0, 1.0, "", "Chỉ vào lệnh khi ADX lớn hơn mức này (xu hướng đủ rõ)."),
        "sig.entry_tf": _choice("signal", "Khung điểm vào", "15m", _TF_FAST, "Khung nến tìm điểm phá đỉnh/đáy để vào lệnh."),
        "sig.dch_n": _int("signal", "Chu kỳ kênh Donchian", 20, 5, 200, "nến", "Vào lệnh khi giá đóng cửa vượt đỉnh/đáy của bấy nhiêu nến trước."),
        **_exit_risk_schema(sl, 0.0, trail, act, timeout, "1h"),
    }


def _breakout_schema():
    return {
        "sig.signal_tf": _choice("signal", "Khung tín hiệu", "4h", _TF_SLOW, "Khung tính EMA và kênh Donchian (cùng một khung)."),
        "sig.ema_fast": _int("signal", "EMA nhanh", 50, 5, 100, "nến", "Chu kỳ EMA nhanh (phải nhỏ hơn EMA chậm)."),
        "sig.ema_slow": _int("signal", "EMA chậm", 200, 20, 500, "nến", "Chu kỳ EMA chậm."),
        "sig.dch_n": _int("signal", "Chu kỳ kênh Donchian", 20, 5, 200, "nến", "Vào lệnh khi giá đóng cửa vượt đỉnh/đáy của bấy nhiêu nến trước."),
        **_exit_risk_schema(2.0, 0.0, 3.0, 1.0, 10080, "4h"),
    }




LEGACY: List[Dict[str, Any]] = [
    {
        "id": "trend_long", "family": "Theo xu hướng (trend following)", "variant": "EMA + ADX + phá đỉnh Donchian", "side": "LONG",
        "description": "1h EMA50 > EMA200, ADX14 > ngưỡng, 15m close CẮT LÊN đỉnh 20 nến trước (sự kiện phá đỉnh). Thoát: SL + trailing theo ATR.",
        "tree": cond((f("{trend_tf}", "ema_{ema_fast}"), ">", f("{trend_tf}", "ema_{ema_slow}")),
                     (f("{trend_tf}", "adx_{adx_n}"), ">", tree_p("adx_min", 20)),
                     *cross_over(f("{entry_tf}", "close"), f("{entry_tf}", "dch_{dch_n}"))),
        "position": {},
        "space": {"sig.adx_min": [20, 25, 30], "stop_loss_rate": [1.5, 2.5, 3.5], "trailing_stop": [2.0, 3.0, 4.5],
                  "trailing_activation_pct": [0.0, 1.0], "timeout": [0, 4320]},
        "params_schema": _trend_schema(2.5, 3.0, 1.0, 4320),
    },
    {
        "id": "trend_short", "family": "Theo xu hướng (trend following)", "variant": "EMA + ADX + phá đáy Donchian", "side": "SHORT",
        "description": "Đối xứng trend_long.",
        "tree": cond((f("{trend_tf}", "ema_{ema_fast}"), "<", f("{trend_tf}", "ema_{ema_slow}")),
                     (f("{trend_tf}", "adx_{adx_n}"), ">", tree_p("adx_min", 20)),
                     *cross_under(f("{entry_tf}", "close"), f("{entry_tf}", "dcl_{dch_n}"))),
        "position": {},
        "space": {"sig.adx_min": [20, 25, 30], "stop_loss_rate": [1.5, 2.5, 3.5], "trailing_stop": [2.0, 3.0, 4.5],
                  "trailing_activation_pct": [0.0, 1.0], "timeout": [0, 4320]},
        "params_schema": _trend_schema(2.5, 3.0, 1.0, 4320),
    },
    {
        "id": "breakout_4h_long", "family": "Theo xu hướng (trend following)", "variant": "Phá kênh Donchian kiểu Turtle", "side": "LONG",
        "description": "4h EMA50 > EMA200 và close 4h CẮT LÊN đỉnh 20 nến 4h trước. ATR khung 4h.",
        "tree": cond((f("{signal_tf}", "ema_{ema_fast}"), ">", f("{signal_tf}", "ema_{ema_slow}")),
                     *cross_over(f("{signal_tf}", "close"), f("{signal_tf}", "dch_{dch_n}"))),
        "position": {"atr_frame": "4h"},
        "space": {"stop_loss_rate": [1.5, 2.0, 3.0], "trailing_stop": [2.0, 3.0, 4.0],
                  "trailing_activation_pct": [0.0, 1.0], "timeout": [0, 10080]},
        "params_schema": _breakout_schema(),
    },
    {
        "id": "breakout_4h_short", "family": "Theo xu hướng (trend following)", "variant": "Phá kênh Donchian kiểu Turtle", "side": "SHORT",
        "description": "Đối xứng breakout_4h_long.",
        "tree": cond((f("{signal_tf}", "ema_{ema_fast}"), "<", f("{signal_tf}", "ema_{ema_slow}")),
                     *cross_under(f("{signal_tf}", "close"), f("{signal_tf}", "dcl_{dch_n}"))),
        "position": {"atr_frame": "4h"},
        "space": {"stop_loss_rate": [1.5, 2.0, 3.0], "trailing_stop": [2.0, 3.0, 4.0],
                  "trailing_activation_pct": [0.0, 1.0], "timeout": [0, 10080]},
        "params_schema": _breakout_schema(),
    },
    {
        "id": "keltner_trend_long", "family": "Theo xu hướng (trend following)", "variant": "Kênh Keltner (KEMA)", "side": "LONG",
        "description": "Close cắt LÊN dải trên Keltner (EMA + k×ATR) -> mua; thoát khi close cắt XUỐNG dải dưới (đảo chiều xu hướng) "
                       "hoặc chạm SL theo ATR. Lối đánh trend-following KEMA.",
        "tree": cond(*cross_over(_KC_CLOSE, _KC_UP)),
        "stop": cond(*cross_under(_KC_CLOSE, _KC_DN)),
        "position": {"atr_frame": "4h"},
        "space": {"sig.ema_n": [20, 30, 50], "sig.k_up": [1.5, 2.0, 2.5], "sig.k_dn": [1.5, 2.0, 2.5],
                  "stop_loss_rate": [2.0, 3.0, 4.0]},
        "params_schema": _keltner_schema(),
    },
    {
        "id": "keltner_trend_short", "family": "Theo xu hướng (trend following)", "variant": "Kênh Keltner (KEMA)", "side": "SHORT",
        "description": "Đối xứng keltner_trend_long: close cắt XUỐNG dải dưới -> bán; thoát khi close cắt LÊN dải trên hoặc chạm SL.",
        "tree": cond(*cross_under(_KC_CLOSE, _KC_DN)),
        "stop": cond(*cross_over(_KC_CLOSE, _KC_UP)),
        "position": {"atr_frame": "4h"},
        "space": {"sig.ema_n": [20, 30, 50], "sig.k_up": [1.5, 2.0, 2.5], "sig.k_dn": [1.5, 2.0, 2.5],
                  "stop_loss_rate": [2.0, 3.0, 4.0]},
        "params_schema": _keltner_schema(),
    },
    {
        "id": "momentum_long", "family": "Theo đà", "side": "LONG",
        "description": "1h ROC24 CẮT LÊN ngưỡng % và 15m close > EMA20 15m.",
        "tree": cond(*cross_over(f("{roc_tf}", "roc_{roc_n}"), tree_p("roc_min", 3)), (f("{entry_tf}", "close"), ">", f("{entry_tf}", "ema_{ema_n}"))),
        "position": {},
        "space": {"sig.roc_min": [3, 5, 8], "stop_loss_rate": [1.5, 2.5, 3.5], "trailing_stop": [2.0, 3.0, 4.5],
                  "trailing_activation_pct": [0.0, 1.0], "timeout": [1440, 4320]},
        "params_schema": {
            "sig.roc_tf": _choice("signal", "Khung đo đà", "1h", _TF_SLOW, "Khung tính ROC (% thay đổi giá)."),
            "sig.roc_n": _int("signal", "Chu kỳ ROC", 24, 2, 200, "nến", "Đo % thay đổi giá so với bấy nhiêu nến trước (24 nến 1h = 24 giờ)."),
            "sig.roc_min": _flt("signal", "Ngưỡng đà tối thiểu", 3.0, 1.0, 15.0, 0.5, "%", "Chỉ vào lệnh khi giá đã tăng hơn mức này."),
            "sig.entry_tf": _choice("signal", "Khung điểm vào", "15m", _TF_FAST, "Khung nến xác nhận giá trên EMA."),
            "sig.ema_n": _int("signal", "Chu kỳ EMA vào lệnh", 20, 5, 200, "nến", "Giá đóng cửa phải nằm trên EMA này."),
            **_exit_risk_schema(2.5, 0.0, 3.0, 1.0, 4320, "1h"),
        },
    },
    {
        "id": "reversion_long", "family": "Bắt hồi (có SL)", "side": "LONG",
        "description": "5m RSI14 < ngưỡng, dưới Bollinger dưới, regime đi ngang (1h ER20 < ngưỡng). TP/SL theo ATR.",
        "tree": cond((f("{entry_tf}", "rsi_{rsi_n}"), "<", tree_p("rsi_lo", 25)), (f("{entry_tf}", "close"), "<", f("{entry_tf}", "bbl_{bb_n}_{bb_k}")),
                     (f("{regime_tf}", "er_{er_n}"), "<", tree_p("er_max", 0.3))),
        "position": {},
        "space": {"sig.rsi_lo": [20, 25, 30], "sig.er_max": [0.2, 0.3], "stop_loss_rate": [1.0, 1.5, 2.5],
                  "take_profit_rate": [0.75, 1.0, 1.5, 2.5], "timeout": [240, 1440]},
        "params_schema": _reversion_schema("sig.rsi_lo", 25.0, 10.0, 45.0, "Ngưỡng RSI quá bán"),
    },
    {
        "id": "reversion_short", "family": "Bắt hồi (có SL)", "side": "SHORT",
        "description": "Đối xứng reversion_long.",
        "tree": cond((f("{entry_tf}", "rsi_{rsi_n}"), ">", tree_p("rsi_hi", 75)), (f("{entry_tf}", "close"), ">", f("{entry_tf}", "bbu_{bb_n}_{bb_k}")),
                     (f("{regime_tf}", "er_{er_n}"), "<", tree_p("er_max", 0.3))),
        "position": {},
        "space": {"sig.rsi_hi": [70, 75, 80], "sig.er_max": [0.2, 0.3], "stop_loss_rate": [1.0, 1.5, 2.5],
                  "take_profit_rate": [0.75, 1.0, 1.5, 2.5], "timeout": [240, 1440]},
        "params_schema": _reversion_schema("sig.rsi_hi", 75.0, 55.0, 90.0, "Ngưỡng RSI quá mua"),
    },
]
for _c in LEGACY:
    _c["legacy"] = True
    _c.pop("variant", None)


LEGACY_BY_ID: Dict[str, Dict[str, Any]] = {c["id"]: c for c in LEGACY}
