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
from collections.abc import Mapping
from typing import Any, Dict, List

from backend.core.strategy.library import calc, cond, cross_over, cross_under, f, p
from backend.core.params import (  # noqa: F401  (P9.4: phần tham số vị thế chuyển sang core/params.py; re-export để `book.X` vẫn dùng được)
    BASE_POSITION, BASE_RISK_PER_TRADE_PCT, MAX_LEVERAGE, PESSIMISTIC_LIMIT_THROUGH_PCT, REGIME_DENY, REGIME_MAP, _REGIME_NAMES,
    materialize, regime_for, schema_defaults, signal_defaults,
)

UNIVERSE = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX"]

RISK = {
    "max_positions": 8,          # tối đa số vị thế mở đồng thời (toàn danh mục)
    "max_per_symbol": 1,         # mỗi tài sản tối đa 1 vị thế (mọi chiến lược cộng lại) -> không cộng dồn rủi ro
    "max_gross_exposure": 3.0,   # Σ danh nghĩa / vốn <= 3
    "kill_switch_dd_pct": 30.0,  # sụt 30% từ đỉnh (MTM, điểm xấu nhất) -> đóng hết, dừng
    "max_open_risk_pct": 6.0,    # Σ rủi ro tới SL (cả rổ DCA) của mọi vị thế mở <= 6% vốn: nhiều rổ cùng chạm SL cũng chỉ mất tối đa ~6%
    "dd_throttle_pct": 5.0,      # vốn đã chốt sụt d% so với đỉnh -> lệnh mới rủi ro × max(0,25; 1 − d/5)
    "dd_throttle_floor": 0.25,
}

GATES = {
    "min_trades": 40,             # trên cả danh mục, mỗi giai đoạn
    "min_symbols_positive": 5,    # dev1: >= 5/8 tài sản có lãi (độ phủ)
    "min_symbols_positive_dev2": 4,
    "max_mdd_pct": 30.0,
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


def _dca_schema(side_key, side_default, side_lo, side_hi, side_label, gate_rsi):
    """DCA = bắt hồi ở vùng quá bán/quá mua khi thị trường đi ngang, dồn thêm tầng khi giá đi ngược NHƯNG chỉ khi điều kiện còn đúng
    (ER thấp + ADX thấp = chưa thành xu hướng ngược); cắt lỗ cứng cho cả rổ, tính từ giá trung bình."""
    return {
        "sig.entry_tf": _choice("signal", "Khung điểm vào", "1h", _TF_FAST, "Khung nến tính RSI và dải Bollinger."),
        "sig.rsi_n": _int("signal", "Chu kỳ RSI", 14, 2, 50, "nến", "Chu kỳ RSI (Wilder)."),
        side_key: _flt("signal", side_label, side_default, side_lo, side_hi, 1.0, "", "Ngưỡng RSI kích hoạt lệnh đầu."),
        "sig.bb_n": _int("signal", "Chu kỳ Bollinger", 20, 5, 100, "nến", "Chu kỳ đường giữa của dải Bollinger."),
        "sig.bb_k": _flt("signal", "Độ rộng Bollinger (k)", 2.0, 1.0, 4.0, 0.1, "σ", "Dải cách đường giữa k độ lệch chuẩn."),
        "sig.regime_tf": _choice("signal", "Khung chế độ thị trường", "4h", _TF_SLOW, "Khung đo đi ngang (ER) và độ mạnh xu hướng (ADX)."),
        "sig.er_n": _int("signal", "Chu kỳ ER", 20, 5, 100, "nến", "Chu kỳ Efficiency Ratio (1 = xu hướng, 0 = đi ngang)."),
        "sig.er_max": _flt("signal", "Vào lệnh khi ER dưới", 0.35, 0.1, 0.7, 0.05, "", "Chỉ mở lệnh đầu khi thị trường đi ngang."),
        "sig.adx_n": _int("signal", "Chu kỳ ADX", 14, 5, 50, "nến", "Chu kỳ ADX đo độ mạnh xu hướng."),
        "sig.gate_er_max": _flt("signal", "Chỉ dồn khi ER dưới", 0.4, 0.1, 0.8, 0.05, "",
                                "Tầng DCA chỉ khớp khi ER còn thấp; ER tăng (bắt đầu có xu hướng) thì ngừng dồn."),
        "sig.gate_adx_max": _flt("signal", "Chỉ dồn khi ADX dưới", 25.0, 10.0, 50.0, 1.0, "",
                                 "Tầng DCA chỉ khớp khi chưa có xu hướng mạnh."),
        "sig.gate_rsi": _flt("signal", gate_rsi[0], gate_rsi[1], gate_rsi[2], gate_rsi[3], 1.0, "", gate_rsi[4]),
        "dca_step_pct": _flt("dca", "Bước dồn lệnh", 1.0, 0.25, 4.0, 0.25, "× ATR",
                             "Giá đi ngược bấy nhiêu × ATR so với lần khớp trước thì dồn thêm một tầng."),
        "dca_max_layers": _int("dca", "Số tầng dồn tối đa", 3, 1, 6, "tầng", "Số lần dồn thêm sau lệnh đầu."),
        "dca_size_multiplier": _flt("dca", "Hệ số khối lượng tầng sau", 1.5, 1.0, 2.5, 0.1, "×", "Mỗi tầng sau lớn gấp bấy nhiêu lần tầng trước."),
        **_exit_risk_schema(6.0, 1.5, 0.0, 0.0, 4320, "1h"),
    }


def _dca_leg(side: str) -> Dict[str, Any]:
    long_ = side == "LONG"
    rsi = (f("{entry_tf}", "rsi_{rsi_n}"), "<", p("rsi_lo", 30)) if long_ else (f("{entry_tf}", "rsi_{rsi_n}"), ">", p("rsi_hi", 70))
    band = ((f("{entry_tf}", "close"), "<", f("{entry_tf}", "bbl_{bb_n}_{bb_k}")) if long_
            else (f("{entry_tf}", "close"), ">", f("{entry_tf}", "bbu_{bb_n}_{bb_k}")))
    schema = (_dca_schema("sig.rsi_lo", 30.0, 10.0, 45.0, "RSI quá bán",
                          ("Chỉ dồn khi RSI còn dưới", 101.0, 10.0, 101.0, "Tầng DCA chỉ khớp khi RSI vẫn quá bán (giá còn bị bán quá đà, chưa đảo "
                           "chiều thành xu hướng giảm); 101 = không lọc.")) if long_ else
              _dca_schema("sig.rsi_hi", 70.0, 55.0, 90.0, "RSI quá mua",
                          ("Chỉ dồn khi RSI còn trên", -1.0, -1.0, 90.0, "Tầng DCA chỉ khớp khi RSI vẫn quá mua; −1 = không lọc.")))
    gate_rsi = (f("{entry_tf}", "rsi_{rsi_n}"), "<", p("gate_rsi", 101.0)) if long_ else (f("{entry_tf}", "rsi_{rsi_n}"), ">", p("gate_rsi", -1.0))
    return {
        "id": "dca_long" if long_ else "dca_short", "strategy": "dca", "family": "DCA (bắt hồi + dồn có điều kiện)", "side": side,
        "legacy": False,
        "description": (("RSI quá bán và giá dưới dải Bollinger dưới khi thị trường đi ngang → mua; giá giảm tiếp thì dồn thêm tầng theo bước ATR "
                         if long_ else
                         "RSI quá mua và giá trên dải Bollinger trên khi thị trường đi ngang → bán; giá tăng tiếp thì dồn thêm tầng theo bước ATR ")
                        + "CHỈ khi vẫn đi ngang (ER, ADX thấp). Chốt lời và cắt lỗ cả rổ tính từ giá trung bình."),
        "tree": cond(rsi, band, (f("{regime_tf}", "er_{er_n}"), "<", p("er_max", 0.35))),
        "dca_gate": cond((f("{regime_tf}", "er_{er_n}"), "<", p("gate_er_max", 0.4)),
                         (f("{regime_tf}", "adx_{adx_n}"), "<", p("gate_adx_max", 25.0)), gate_rsi),
        "position": {"exit_unit": "atr"},
        "space": {("sig.rsi_lo" if long_ else "sig.rsi_hi"): [25, 30, 35] if long_ else [65, 70, 75],
                  "dca_step_pct": [0.5, 1.0, 1.5], "dca_max_layers": [2, 3, 4], "dca_size_multiplier": [1.0, 1.5, 2.0],
                  "stop_loss_rate": [4.0, 6.0, 8.0], "take_profit_rate": [1.0, 1.5, 2.5], "sig.gate_er_max": [0.3, 0.4, 0.5]},
        "params_schema": schema,
    }


# ─── 3 chiến lược; mỗi chiến lược có chân LONG / SHORT (mỗi bộ tham số của một chân = một alpha; "Cả hai" = chạy cả hai chân) ───
_KEMA_SPACE = {"sig.ema_n": [20, 30, 50], "sig.k_up": [1.5, 2.0, 2.5], "sig.k_dn": [1.5, 2.0, 2.5], "stop_loss_rate": [2.0, 3.0, 4.0]}
CANDIDATES: List[Dict[str, Any]] = [
    {"id": "kema_long", "strategy": "kema", "family": "KEMA (theo xu hướng)", "side": "LONG",
     "description": "Giá đóng cửa cắt LÊN dải trên kênh Keltner (EMA + k × ATR) → mua. Thoát khi giá cắt XUỐNG dải dưới (đảo chiều) hoặc chạm SL.",
     "tree": cond(*cross_over(_KC_CLOSE, _KC_UP)), "stop": cond(*cross_under(_KC_CLOSE, _KC_DN)),
     "position": {"atr_frame": "4h"}, "space": dict(_KEMA_SPACE), "params_schema": _keltner_schema()},
    {"id": "kema_short", "strategy": "kema", "family": "KEMA (theo xu hướng)", "side": "SHORT",
     "description": "Giá đóng cửa cắt XUỐNG dải dưới kênh Keltner (EMA − k × ATR) → bán. Thoát khi giá cắt LÊN dải trên (đảo chiều) hoặc chạm SL.",
     "tree": cond(*cross_under(_KC_CLOSE, _KC_DN)), "stop": cond(*cross_over(_KC_CLOSE, _KC_UP)),
     "position": {"atr_frame": "4h"}, "space": dict(_KEMA_SPACE), "params_schema": _keltner_schema()},
    {"id": "sideway_long", "strategy": "sideway", "family": "Sideway (đi ngang)", "side": "LONG",
     "description": "Chỉ đánh khi thị trường đi ngang (ER thấp): RSI quá bán và giá dưới dải Bollinger dưới → mua. Chốt lời / cắt lỗ theo ATR.",
     "tree": cond((f("{entry_tf}", "rsi_{rsi_n}"), "<", p("rsi_lo", 25)), (f("{entry_tf}", "close"), "<", f("{entry_tf}", "bbl_{bb_n}_{bb_k}")),
                  (f("{regime_tf}", "er_{er_n}"), "<", p("er_max", 0.3))),
     "position": {},
     "space": {"sig.rsi_lo": [20, 25, 30], "sig.er_max": [0.2, 0.3], "stop_loss_rate": [1.0, 1.5, 2.5],
               "take_profit_rate": [0.75, 1.0, 1.5, 2.5], "timeout": [240, 1440]},
     "params_schema": _reversion_schema("sig.rsi_lo", 25.0, 10.0, 45.0, "Ngưỡng RSI quá bán")},
    {"id": "sideway_short", "strategy": "sideway", "family": "Sideway (đi ngang)", "side": "SHORT",
     "description": "Chỉ đánh khi thị trường đi ngang (ER thấp): RSI quá mua và giá trên dải Bollinger trên → bán. Chốt lời / cắt lỗ theo ATR.",
     "tree": cond((f("{entry_tf}", "rsi_{rsi_n}"), ">", p("rsi_hi", 75)), (f("{entry_tf}", "close"), ">", f("{entry_tf}", "bbu_{bb_n}_{bb_k}")),
                  (f("{regime_tf}", "er_{er_n}"), "<", p("er_max", 0.3))),
     "position": {},
     "space": {"sig.rsi_hi": [70, 75, 80], "sig.er_max": [0.2, 0.3], "stop_loss_rate": [1.0, 1.5, 2.5],
               "take_profit_rate": [0.75, 1.0, 1.5, 2.5], "timeout": [240, 1440]},
     "params_schema": _reversion_schema("sig.rsi_hi", 75.0, 55.0, 90.0, "Ngưỡng RSI quá mua")},
    _dca_leg("LONG"),
    _dca_leg("SHORT"),
]
# Định nghĩa đăng ký thêm ngoài danh mục (test: chiến lược cũ của golden / kiểm parity). Không hiện ở API danh mục, không sinh alpha.
EXTRA_CANDIDATES: List[Dict[str, Any]] = []


def all_candidates() -> List[Dict[str, Any]]:
    """Danh mục + định nghĩa đăng ký thêm (đọc tại lúc gọi: test thay CANDIDATES / EXTRA_CANDIDATES vẫn có hiệu lực)."""
    return CANDIDATES + EXTRA_CANDIDATES


class _ById(Mapping):
    """{id: định nghĩa} của all_candidates(), tính tại lúc tra."""
    def _m(self) -> Dict[str, Dict[str, Any]]:
        return {c["id"]: c for c in all_candidates()}

    def __getitem__(self, key: str) -> Dict[str, Any]:
        return self._m()[key]

    def __iter__(self):
        return iter(self._m())

    def __len__(self) -> int:
        return len(self._m())


BY_ID: Mapping = _ById()

STRATEGIES: List[Dict[str, Any]] = [
    {"id": "kema", "name": "KEMA", "kind": "Theo xu hướng", "legs": {"LONG": "kema_long", "SHORT": "kema_short"},
     "description": "Theo xu hướng bằng kênh Keltner: vào khi giá phá kênh, thoát khi giá cắt ngược kênh. Cả hai chiều = đảo chiều liên tục.",
     "idea": "Theo xu hướng: giá đóng cửa phá ra ngoài kênh EMA ± k·ATR báo hiệu xu hướng mới có quán tính; đi theo hướng phá kênh, thoát khi giá cắt ngược kênh. Lãi đến từ ít lệnh thắng lớn khi xu hướng chạy dài."},
    {"id": "sideway", "name": "Sideway", "kind": "Đi ngang", "doc": "combined", "legs": {"LONG": "sideway_long", "SHORT": "sideway_short"},
     "description": "Đánh biên khi thị trường đi ngang: mua vùng quá bán, bán vùng quá mua; đứng ngoài khi có xu hướng.",
     "idea": "Hồi quy về trung bình khi thị trường đi ngang: giá chạm cực trị dải Bollinger lúc xu hướng yếu thường là phản ứng thái quá, kỳ vọng quay về đường giữa."},
    {"id": "dca", "name": "DCA", "kind": "Bắt hồi + dồn lệnh có điều kiện", "legs": {"LONG": "dca_long", "SHORT": "dca_short"},
     "description": "Bắt hồi ở vùng quá bán/quá mua khi đi ngang; chỉ dồn thêm tầng khi thị trường vẫn đi ngang (ER, ADX thấp), "
                    "ngừng dồn khi bắt đầu có xu hướng. Cắt lỗ cứng cho cả rổ.",
     "idea": "Bắt hồi ở vùng quá bán/quá mua khi đi ngang, dồn thêm tầng theo bước ATR chỉ khi thị trường vẫn đi ngang; rủi ro cả rổ cố định bằng cắt lỗ từ giá trung bình."},
]



REGIME_MAP.update({c["id"]: regime_for(c["side"]) for c in CANDIDATES})   # P9.4: REGIME_MAP (dict) do core/params.py giữ; điền ở đây


def perp_symbols(universe: List[str] = None) -> List[str]:
    return [f"{s}@perp" for s in (universe or UNIVERSE)]
