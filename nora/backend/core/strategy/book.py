"""Sổ chiến lược (strategy book): tham số theo CHIẾN LƯỢC, không theo tài sản; vốn phân bổ theo RỦI RO.

Nguyên tắc:
- Một chiến lược = tín hiệu (AST trên kernel) + quản lý vị thế. Một bộ tham số dùng chung cho cả vũ trụ tài sản.
- Thoát lệnh theo bội số ATR% (exit_unit="atr") để cùng tham số tự co giãn theo biến động từng tài sản:
  stop_loss_rate=2 nghĩa là SL cách giá vào 2 × ATR%(khung atr_frame) đo ở nến đã đóng lúc có tín hiệu.
- Khối lượng theo rủi ro (sizing="risk"): chạm SL mất ~risk_per_trade_pct% vốn; đòn bẩy tự hạ để thanh lý
  cách giá vào >= 1,5 × khoảng SL; trần đòn bẩy 10x (mức rủi ro đã chốt).
- Rủi ro danh mục (RiskConfig): số vị thế đồng thời, mỗi tài sản tối đa 1 vị thế, trần tổng danh nghĩa, kill switch 30%.

Chọn chiến lược (backend/optimize/book.py) chạy trên CẢ vũ trụ cùng lúc (backtest danh mục), nên một
cấu hình chỉ thắng nhờ một tài sản sẽ bị loại bởi điều kiện độ phủ (đa số tài sản phải có lãi).
"""
from typing import Any, Dict, List

from backend.core.strategy.library import calc, cond, cross_over, cross_under, f, p

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

# ─── Lược đồ tham số (params_schema): mọi tham số người dùng chỉnh được ở chế độ Nâng cao ─────────────────────
# Khoá nhóm "signal" mang tiền tố "sig." (cùng quy ước với `space`, book.json, cấu hình WFA); nhóm "exit"/"risk" là khoá vị thế
# (backtest/params_builder.POSITION_KEYS). MẶC ĐỊNH tái lập đúng cây/vị thế cũ: tín hiệu = giá trị literal cũ của cây; thoát lệnh =
# mức GIỮA của `space` (cùng quy tắc run_book_backtest._mid_params / default_params), không có trong space = BASE_POSITION/0.
_FRAME_HELP = "Khung nến dùng để tính chỉ báo (1m, 5m, 15m, 1h, 4h, 24h)."


def _int(group, label, default, lo, hi, unit="", help_vi="", step=1):
    return {"group": group, "type": "int", "min": lo, "max": hi, "step": step, "default": default,
            "label_vi": label, "unit": unit, "help_vi": help_vi}


def _flt(group, label, default, lo, hi, step, unit="", help_vi=""):
    return {"group": group, "type": "float", "min": lo, "max": hi, "step": step, "default": default,
            "label_vi": label, "unit": unit, "help_vi": help_vi}


def _choice(group, label, default, choices, help_vi=_FRAME_HELP):
    return {"group": group, "type": "choice", "choices": list(choices), "default": default,
            "label_vi": label, "unit": "", "help_vi": help_vi}


_TF_SLOW = ("15m", "1h", "4h", "24h")     # khung xu hướng / bộ lọc regime
_TF_FAST = ("1m", "5m", "15m", "1h")      # khung điểm vào lệnh


def _exit_risk_schema(sl, tp, trail, act, timeout, atr_frame):
    """Nhóm thoát lệnh + rủi ro dùng chung (mọi ứng viên có cùng khoá; chỉ mặc định khác nhau)."""
    return {
        "stop_loss_rate": _flt("exit", "Cắt lỗ", sl, 0.5, 10.0, 0.1, "× ATR",
                               "Cắt lỗ cách giá vào bằng số này × ATR% (khung ATR bên dưới). Càng nhỏ càng dễ bị quét."),
        "take_profit_rate": _flt("exit", "Chốt lời", tp, 0.0, 10.0, 0.05, "× ATR", "Chốt lời cố định; 0 = không đặt (thoát bằng trailing/timeout)."),
        "trailing_stop": _flt("exit", "Trailing stop", trail, 0.0, 10.0, 0.1, "× ATR",
                              "Dời lệnh cắt theo đỉnh/đáy có lợi nhất, cách bấy nhiêu × ATR; 0 = tắt."),
        "trailing_activation_pct": _flt("exit", "Bật trailing khi lãi", act, 0.0, 5.0, 0.1, "× ATR",
                                        "Chỉ bật trailing khi đã lãi tối thiểu bấy nhiêu × ATR; 0 = bật ngay."),
        "timeout": _int("exit", "Giữ lệnh tối đa", timeout, 0, 20160, "phút", "Tự đóng lệnh sau bấy nhiêu phút; 0 = không giới hạn.", step=60),
        "cooldown": _int("exit", "Nghỉ sau khi thoát", 60, 0, 1440, "phút", "Chờ bấy nhiêu phút sau khi đóng lệnh mới nhận tín hiệu vào lại.", step=15),
        "atr_frame": _choice("exit", "Khung tính ATR", atr_frame, ("5m", "15m", "1h", "4h", "24h"), "Khung nến đo ATR% để quy đổi cắt lỗ/chốt lời/trailing."),
        "atr_period": _int("exit", "Chu kỳ ATR", 14, 5, 50, "nến", "Số nến của ATR (Wilder)."),
        "risk_per_trade_pct": _flt("risk", "Rủi ro mỗi lệnh", BASE_RISK_PER_TRADE_PCT, 0.05, 5.0, 0.05, "% vốn",
                                   "Chạm cắt lỗ thì mất xấp xỉ bấy nhiêu % vốn; khối lượng lệnh tự tính theo đó. "
                                   "Chế độ Nâng cao: mọi chiến lược trong một lần chạy phải cùng mức này."),
        "max_notional_pct": _flt("risk", "Trần danh nghĩa mỗi lệnh", 300.0, 50.0, 500.0, 10.0, "% vốn",
                                 "Giá trị danh nghĩa tối đa của một lệnh so với vốn."),
        "leverage": _int("risk", "Trần đòn bẩy", MAX_LEVERAGE, 1, MAX_LEVERAGE, "x",
                         "Đòn bẩy tối đa; đòn bẩy thực tự hạ để giá thanh lý xa hơn 1,5 × khoảng cắt lỗ."),
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
    """(dải trên, dải dưới) của kênh Keltner trên khung tín hiệu: EMA(ema_n) ± k × ATR(atr_n) — như KEMA của sova."""
    atr = f("{signal_tf}", "atr_{atr_n}")
    up = {**f("{signal_tf}", "ema_{ema_n}"), "add": calc(atr, "*", p("k_up", 2.0))}
    dn = {**f("{signal_tf}", "ema_{ema_n}"), "subtract": calc(atr, "*", p("k_dn", 2.0))}
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


CANDIDATES: List[Dict[str, Any]] = [
    {
        "id": "trend_long", "family": "Theo xu hướng", "side": "LONG",
        "description": "1h EMA50 > EMA200, ADX14 > ngưỡng, 15m close CẮT LÊN đỉnh 20 nến trước (sự kiện phá đỉnh). Thoát: SL + trailing theo ATR.",
        "tree": cond((f("{trend_tf}", "ema_{ema_fast}"), ">", f("{trend_tf}", "ema_{ema_slow}")),
                     (f("{trend_tf}", "adx_{adx_n}"), ">", p("adx_min", 20)),
                     *cross_over(f("{entry_tf}", "close"), f("{entry_tf}", "dch_{dch_n}"))),
        "position": {},
        "space": {"sig.adx_min": [20, 25, 30], "stop_loss_rate": [1.5, 2.5, 3.5], "trailing_stop": [2.0, 3.0, 4.5],
                  "trailing_activation_pct": [0.0, 1.0], "timeout": [0, 4320]},
        "params_schema": _trend_schema(2.5, 3.0, 1.0, 4320),
    },
    {
        "id": "trend_short", "family": "Theo xu hướng", "side": "SHORT",
        "description": "Đối xứng trend_long.",
        "tree": cond((f("{trend_tf}", "ema_{ema_fast}"), "<", f("{trend_tf}", "ema_{ema_slow}")),
                     (f("{trend_tf}", "adx_{adx_n}"), ">", p("adx_min", 20)),
                     *cross_under(f("{entry_tf}", "close"), f("{entry_tf}", "dcl_{dch_n}"))),
        "position": {},
        "space": {"sig.adx_min": [20, 25, 30], "stop_loss_rate": [1.5, 2.5, 3.5], "trailing_stop": [2.0, 3.0, 4.5],
                  "trailing_activation_pct": [0.0, 1.0], "timeout": [0, 4320]},
        "params_schema": _trend_schema(2.5, 3.0, 1.0, 4320),
    },
    {
        "id": "breakout_4h_long", "family": "Theo xu hướng (Turtle)", "side": "LONG",
        "description": "4h EMA50 > EMA200 và close 4h CẮT LÊN đỉnh 20 nến 4h trước. ATR khung 4h.",
        "tree": cond((f("{signal_tf}", "ema_{ema_fast}"), ">", f("{signal_tf}", "ema_{ema_slow}")),
                     *cross_over(f("{signal_tf}", "close"), f("{signal_tf}", "dch_{dch_n}"))),
        "position": {"atr_frame": "4h"},
        "space": {"stop_loss_rate": [1.5, 2.0, 3.0], "trailing_stop": [2.0, 3.0, 4.0],
                  "trailing_activation_pct": [0.0, 1.0], "timeout": [0, 10080]},
        "params_schema": _breakout_schema(),
    },
    {
        "id": "breakout_4h_short", "family": "Theo xu hướng (Turtle)", "side": "SHORT",
        "description": "Đối xứng breakout_4h_long.",
        "tree": cond((f("{signal_tf}", "ema_{ema_fast}"), "<", f("{signal_tf}", "ema_{ema_slow}")),
                     *cross_under(f("{signal_tf}", "close"), f("{signal_tf}", "dcl_{dch_n}"))),
        "position": {"atr_frame": "4h"},
        "space": {"stop_loss_rate": [1.5, 2.0, 3.0], "trailing_stop": [2.0, 3.0, 4.0],
                  "trailing_activation_pct": [0.0, 1.0], "timeout": [0, 10080]},
        "params_schema": _breakout_schema(),
    },
    {
        "id": "keltner_trend_long", "family": "Theo xu hướng (Keltner)", "side": "LONG",
        "description": "Close cắt LÊN dải trên Keltner (EMA + k×ATR) -> mua; thoát khi close cắt XUỐNG dải dưới (đảo chiều xu hướng) "
                       "hoặc chạm SL theo ATR. Lối đánh trend-following của KEMA (sova).",
        "tree": cond(*cross_over(_KC_CLOSE, _KC_UP)),
        "stop": cond(*cross_under(_KC_CLOSE, _KC_DN)),
        "position": {"atr_frame": "4h"},
        "space": {"sig.ema_n": [20, 30, 50], "sig.k_up": [1.5, 2.0, 2.5], "sig.k_dn": [1.5, 2.0, 2.5],
                  "stop_loss_rate": [2.0, 3.0, 4.0]},
        "params_schema": _keltner_schema(),
    },
    {
        "id": "keltner_trend_short", "family": "Theo xu hướng (Keltner)", "side": "SHORT",
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
        "tree": cond(*cross_over(f("{roc_tf}", "roc_{roc_n}"), p("roc_min", 3)), (f("{entry_tf}", "close"), ">", f("{entry_tf}", "ema_{ema_n}"))),
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
        "tree": cond((f("{entry_tf}", "rsi_{rsi_n}"), "<", p("rsi_lo", 25)), (f("{entry_tf}", "close"), "<", f("{entry_tf}", "bbl_{bb_n}_{bb_k}")),
                     (f("{regime_tf}", "er_{er_n}"), "<", p("er_max", 0.3))),
        "position": {},
        "space": {"sig.rsi_lo": [20, 25, 30], "sig.er_max": [0.2, 0.3], "stop_loss_rate": [1.0, 1.5, 2.5],
                  "take_profit_rate": [0.75, 1.0, 1.5, 2.5], "timeout": [240, 1440]},
        "params_schema": _reversion_schema("sig.rsi_lo", 25.0, 10.0, 45.0, "Ngưỡng RSI quá bán"),
    },
    {
        "id": "reversion_short", "family": "Bắt hồi (có SL)", "side": "SHORT",
        "description": "Đối xứng reversion_long.",
        "tree": cond((f("{entry_tf}", "rsi_{rsi_n}"), ">", p("rsi_hi", 75)), (f("{entry_tf}", "close"), ">", f("{entry_tf}", "bbu_{bb_n}_{bb_k}")),
                     (f("{regime_tf}", "er_{er_n}"), "<", p("er_max", 0.3))),
        "position": {},
        "space": {"sig.rsi_hi": [70, 75, 80], "sig.er_max": [0.2, 0.3], "stop_loss_rate": [1.0, 1.5, 2.5],
                  "take_profit_rate": [0.75, 1.0, 1.5, 2.5], "timeout": [240, 1440]},
        "params_schema": _reversion_schema("sig.rsi_hi", 75.0, 55.0, 90.0, "Ngưỡng RSI quá mua"),
    },
]


# Regime cho phép vào lệnh (core/regime/classifier.py). Chỉ áp khi bật regime (materialize(..., regime=True)); tắt -> chiến lược y như cũ
# (golden bất biến). Dạng "CHẶN NGƯỢC CHIỀU": LONG không vào khi TREND_DOWN / CRASH, SHORT không vào khi TREND_UP / SURGE; mọi regime khác được vào.
# Cầu chì TẮT: chiến lược lõi đều có cắt lỗ theo rủi ro (MC trend thẳng đứng: lỗ tối đa ~6% vốn); sau CRASH giá thường hồi nên cầu chì cắt LONG ở
# đáy. Bảng "chỉ cho vào ở regime X" cũ (+ cầu chì) bị dữ liệu thật bác bỏ: sổ +29,6% -> −26,0%; bảng tĩnh chỉ cho vào 8–12% lệnh lãi của chiến
# lược xu hướng vì nhãn xu hướng 4h đến muộn hơn điểm phá vỡ (test/scripts/research_regime_diagnosis.py, roadmap P2.4).
REGIME_DENY: Dict[str, List[str]] = {"LONG": ["TREND_DOWN", "CRASH"], "SHORT": ["TREND_UP", "SURGE"]}
_REGIME_NAMES = ("UNKNOWN", "RANGE", "TREND_UP", "TREND_DOWN", "VOL_EXPANSION", "SURGE", "CRASH")   # = classifier.NAMES
REGIME_MAP: Dict[str, Dict[str, Any]] = {
    c["id"]: {"allowed": [r for r in _REGIME_NAMES if r not in REGIME_DENY[c["side"]]], "fuse": False} for c in CANDIDATES
}


def schema_defaults(candidate: Dict[str, Any], group: str = None) -> Dict[str, Any]:
    """{khoá: mặc định} của params_schema (lọc theo nhóm nếu có)."""
    return {k: v["default"] for k, v in (candidate.get("params_schema") or {}).items() if group is None or v["group"] == group}


def signal_defaults(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Mặc định tham số tín hiệu KHÔNG tiền tố "sig." (dùng thay các `{tên}` trong cây khi thiếu giá trị)."""
    from backend.core.params.template import SIG_PREFIX
    return {k[len(SIG_PREFIX):]: v for k, v in schema_defaults(candidate, "signal").items()}


def materialize(candidate: Dict[str, Any], params: Dict[str, Any], regime: Any = False, **position_overrides) -> Dict[str, Any]:
    """Chiến lược cụ thể cho PortfolioEngine: thay ngưỡng/chu kỳ/khung tín hiệu, ghép tham số vị thế.
    `signal_params` trả về chỉ gồm tham số tín hiệu được truyền vào (không gồm mặc định) — như trước.
    regime=True: gắn khoá "regime" theo REGIME_MAP (lọc tín hiệu vào + cầu chì trong PortfolioEngine.load_data);
    regime=dict: cấu hình regime riêng của chiến lược này ({"allowed", "fuse"}, vd. bảng học từ train — core/regime/learn.py)."""
    from backend.core.params.template import resolve_placeholders, split_params
    signal, position = split_params(dict(params))
    if isinstance(regime, dict):
        extra = {"regime": regime}
    else:
        extra = {"regime": REGIME_MAP[candidate["id"]]} if regime and candidate["id"] in REGIME_MAP else {}
    if candidate.get("stop"):   # tín hiệu thoát (vd. cắt ngược kênh) -> đóng ở open nến 1m kế tiếp
        extra["stop"] = [{"condition": resolve_placeholders(candidate["stop"], signal, signal_defaults(candidate))}]
    return {**extra,
        "id": candidate["id"], "side": candidate["side"],
        "tree": resolve_placeholders(candidate["tree"], signal, signal_defaults(candidate)),
        "position": {**BASE_POSITION, **candidate.get("position", {}), **position, **position_overrides},
        "signal_params": signal,
    }


def perp_symbols(universe: List[str] = None) -> List[str]:
    return [f"{s}@perp" for s in (universe or UNIVERSE)]
