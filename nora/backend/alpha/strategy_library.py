"""Thư viện tín hiệu + chiến lược dựa trên kernel (bước 2).

Tham khảo lối đánh của 28 bot trade top OKX/Binance (okx-report.html, 28–29/09/2026):
    Bắt hồi + DCA   12/28 bot, thắng 81%, 10x, giữ ~14h — bước DCA 0,25% / 0,74% / 1,72%, 2–4 tầng
    Săn cú lớn       7/28, thắng 53%, lãi dồn vào vài lệnh
    Theo đà          5/28, thắng 86%, vào cùng chiều biến động 24h
    Lướt nhanh       4/28, thắng 97%, giữ ~6h, ít nhồi
Khác biệt có chủ đích so với bot OKX: MỌI chiến lược ở đây có stop-loss cứng và/hoặc timeout.
Báo cáo cho thấy 21/28 bot không cắt lỗ và 17/26 lead OKX đang ôm lỗ treo tổng −1,29M USDT;
số tầng DCA tương quan +0,62 với cú lỗ lớn nhất. Không cắt lỗ = win rate đẹp, đuôi lỗ không giới hạn.

Mỗi SIGNAL là một cây điều kiện AST trên kernel (signals/kernels.py), được kiểm tra riêng
bằng signals/diagnostics.py trước khi ghép với tham số quản lý vị thế thành STRATEGY.
"""
from typing import Any, Dict, List


def f(frame: str, column: str, index: int = 0) -> Dict[str, Any]:
    return {"frame": frame, "column": column, "index": index}


def cond(*triplets) -> List[List[List[Any]]]:
    """Một khối AND gồm các (trái, toán tử, phải)."""
    return [[list(t) for t in triplets]]


# ─── SIGNALS (điều kiện vào lệnh; kiểm tra thông tin trước khi dùng) ─────────
SIGNALS: Dict[str, Dict[str, Any]] = {
    "dip_5m_rsi_bb_ranging": {
        "family": "Bắt hồi + DCA",
        "side": "LONG",
        "description": "5m RSI14 < 30 và close dưới Bollinger dưới 20/2, trong regime đi ngang (1h ER20 < 0,35).",
        "tree": cond((f("5m", "rsi_14"), "<", 30), (f("5m", "close"), "<", f("5m", "bbl_20_2")),
                     (f("1h", "er_20"), "<", 0.35)),
    },
    "rip_5m_rsi_bb_ranging": {
        "family": "Bắt hồi + DCA",
        "side": "SHORT",
        "description": "Đối xứng: 5m RSI14 > 70 và close trên Bollinger trên, regime đi ngang.",
        "tree": cond((f("5m", "rsi_14"), ">", 70), (f("5m", "close"), ">", f("5m", "bbu_20_2")),
                     (f("1h", "er_20"), "<", 0.35)),
    },
    "dip_1m_deep_zscore": {
        "family": "Bắt hồi + DCA (dày)",
        "side": "LONG",
        "description": "1m RSI7 < 20 và z-score 60 phút < −2,5 (rơi gấp trong ngắn hạn).",
        "tree": cond((f("1m", "rsi_7"), "<", 20), (f("1m", "bbz_60"), "<", -2.5)),
    },
    "trend_1h_ema_donchian": {
        "family": "Theo xu hướng",
        "side": "LONG",
        "description": "1h EMA50 > EMA200, ADX14 > 20 và 15m close phá đỉnh 20 nến 15m trước.",
        "tree": cond((f("1h", "ema_50"), ">", f("1h", "ema_200")), (f("1h", "adx_14"), ">", 20),
                     (f("15m", "close"), ">", f("15m", "dch_20"))),
    },
    "trend_1h_ema_donchian_short": {
        "family": "Theo xu hướng",
        "side": "SHORT",
        "description": "1h EMA50 < EMA200, ADX14 > 20 và 15m close thủng đáy 20 nến 15m trước.",
        "tree": cond((f("1h", "ema_50"), "<", f("1h", "ema_200")), (f("1h", "adx_14"), ">", 20),
                     (f("15m", "close"), "<", f("15m", "dcl_20"))),
    },
    "momentum_24h_roc": {
        "family": "Theo đà",
        "side": "LONG",
        "description": "Giá tăng > 3% trong 24h (1h ROC24) và 15m close trên EMA20 — vào cùng chiều đà.",
        "tree": cond((f("1h", "roc_24"), ">", 3), (f("15m", "close"), ">", f("15m", "ema_20"))),
    },
    "scalp_vwap_dip_uptrend": {
        "family": "Lướt nhanh",
        "side": "LONG",
        "description": "1m close thấp hơn VWAP 60 phút > 0,6% và RSI7 < 25, khi 15m EMA20 > EMA50.",
        "tree": cond((f("1m", "vwapdev_60"), "<", -0.6), (f("1m", "rsi_7"), "<", 25),
                     (f("15m", "ema_20"), ">", f("15m", "ema_50"))),
    },
    "squeeze_breakout_1h": {
        "family": "Săn cú lớn",
        "side": "LONG",
        "description": "Bollinger 1h nén (phân vị độ rộng < 15 ở nến trước) rồi close 1h phá đỉnh 20 nến.",
        "tree": cond((f("1h", "bbwp_20_2_120", 1), "<", 15), (f("1h", "close"), ">", f("1h", "dch_20"))),
    },
}


def _strategy(sid, name, signal, family, description, params, tags) -> Dict[str, Any]:
    sig = SIGNALS[signal]
    side = sig["side"]
    return {
        "id": sid,
        "name": name,
        "category": family,
        "family": family,
        "signal": signal,
        "market": "CEX/DEX",
        "universe": "data/cex + data/dex",
        "execution_frame": "1m",
        "indicator_frame": "multi",
        "description": description,
        "tags": ["Kernel", side, family],
        "default_params": {"initial_capital": 10000.0, **params},
        "flows": [{
            "id": f"{sid}_flow",
            "name": f"{side} {name}",
            "type": side,
            "enabled": True,
            "ast": {"type": side, "match": [{"condition": sig["tree"]}], "stop": []},
        }],
        "reference": tags,
    }


KERNEL_STRATEGIES: List[Dict[str, Any]] = [
    _strategy(
        "okx_dca_reversion_long", "Bắt hồi + DCA vừa (spot)", "dip_5m_rsi_bb_ranging", "Bắt hồi + DCA",
        "Kiểu 'DCA vừa' của bot top OKX: vào khi 5m quá bán trong regime đi ngang, nhồi mỗi 0,75% tối đa "
        "4 tầng cùng size, chốt 0,8% từ giá TB. KHÁC bot OKX: cắt lỗ cứng 6% từ giá TB, timeout 3 ngày.",
        {"market": "spot", "leverage": 1.0, "order_size_pct": 20.0, "dca_step_pct": 0.75, "dca_max_layers": 4,
         "dca_size_multiplier": 1.0, "take_profit_rate": 0.8, "stop_loss_rate": 6.0, "timeout": 4320},
        "okx-report 6.4: DCA vừa — bước 0,74%, 4 tầng, ×1,0, 10x",
    ),
    _strategy(
        "okx_dca_reversion_short_perp", "Bắt hồi + DCA vừa (short perp 5x)", "rip_5m_rsi_bb_ranging",
        "Bắt hồi + DCA",
        "Chiều short của lối bắt hồi (nhiều bot top chạy hai chiều). Perp 5x, ký quỹ isolated, "
        "có thanh lý. Giá spot làm proxy, chưa tính funding.",
        {"market": "perp", "leverage": 5.0, "order_size_pct": 20.0, "dca_step_pct": 0.75, "dca_max_layers": 4,
         "dca_size_multiplier": 1.0, "take_profit_rate": 0.8, "stop_loss_rate": 6.0, "timeout": 4320},
        "okx-report 4.1: cùng người tạo chạy DCA long và DCA short",
    ),
    _strategy(
        "okx_dca_dense_fast", "DCA dày, chốt nhanh (spot)", "dip_1m_deep_zscore", "Bắt hồi + DCA (dày)",
        "Kiểu 'DCA dày' của bot top OKX: bước 0,3%, 4 tầng, chốt 0,4% từ giá TB. Phí spot 0,1%/chiều ăn "
        "gần hết biên lãi — dùng để kiểm chứng lối này có sống được sau phí hay không.",
        {"market": "spot", "leverage": 1.0, "order_size_pct": 20.0, "dca_step_pct": 0.3, "dca_max_layers": 4,
         "dca_size_multiplier": 1.0, "take_profit_rate": 0.4, "stop_loss_rate": 3.0, "timeout": 720},
        "okx-report 6.4: DCA dày — bước 0,25%, 4 tầng, chốt nhanh, 20x",
    ),
    _strategy(
        "trend_ema_donchian_long", "Theo xu hướng EMA + Donchian", "trend_1h_ema_donchian", "Theo xu hướng",
        "Chỉ mua khi 1h có xu hướng tăng rõ (EMA50>EMA200, ADX>20) và giá phá đỉnh 15m. Không DCA; "
        "trailing 2,5% (bật khi lãi ≥1%), cắt lỗ 3%.",
        {"market": "spot", "leverage": 1.0, "order_size_pct": 100.0, "stop_loss_rate": 3.0,
         "trailing_stop": 2.5, "trailing_activation_pct": 1.0},
        "okx-report 6.4: Theo đà — 5/28 bot",
    ),
    _strategy(
        "trend_ema_donchian_short_perp", "Theo xu hướng giảm (short perp 2x)", "trend_1h_ema_donchian_short",
        "Theo xu hướng",
        "Đối xứng chiều giảm trên perp 2x.",
        {"market": "perp", "leverage": 2.0, "order_size_pct": 50.0, "stop_loss_rate": 3.0,
         "trailing_stop": 2.5, "trailing_activation_pct": 1.0},
        "okx-report 4.3: regime đổi sang giảm",
    ),
    _strategy(
        "momentum_24h_follow", "Theo đà 24h", "momentum_24h_roc", "Theo đà",
        "Vào cùng chiều khi giá đã tăng > 3% trong 24h. Trailing 1,5% (bật khi lãi ≥0,5%), cắt lỗ 2%, "
        "tối đa 1 ngày.",
        {"market": "spot", "leverage": 1.0, "order_size_pct": 100.0, "stop_loss_rate": 2.0,
         "trailing_stop": 1.5, "trailing_activation_pct": 0.5, "timeout": 1440},
        "okx-report 6.4: Theo đà — ≥58% lệnh cùng chiều biến động 24h",
    ),
    _strategy(
        "scalp_vwap_fast", "Lướt nhanh VWAP", "scalp_vwap_dip_uptrend", "Lướt nhanh",
        "Bắt nhịp chệch khỏi VWAP 60 phút trong xu hướng 15m tăng; chốt 0,35%, cắt 0,5%, tối đa 60 phút.",
        {"market": "spot", "leverage": 1.0, "order_size_pct": 100.0, "take_profit_rate": 0.35,
         "stop_loss_rate": 0.5, "timeout": 60},
        "okx-report 6.4: Lướt ngắn, chốt nhanh — 4/28 bot, giữ ~6h",
    ),
    _strategy(
        "squeeze_breakout_hunt", "Săn cú lớn sau nén biến động", "squeeze_breakout_1h", "Săn cú lớn",
        "Chờ Bollinger 1h nén rồi phá đỉnh 20 nến: R:R 3 (chốt 6%, cắt 2%), giữ tối đa 5 ngày. "
        "Win rate thấp là bình thường với lối này.",
        {"market": "spot", "leverage": 1.0, "order_size_pct": 100.0, "take_profit_rate": 6.0,
         "stop_loss_rate": 2.0, "timeout": 7200},
        "okx-report 6.4: Săn cú lớn — 7/28 bot, thắng 53%",
    ),
]


# ─── KHÔNG GIAN TỐI ƯU (bước B) ─────────────────────────────────────────────
# Ngưỡng tín hiệu là node {"param": ...} (tối ưu được, khoá "sig.<tên>"); tham số vị thế theo
# backtest/params_builder.POSITION_KEYS. Rủi ro đã chốt: đòn bẩy <= 10x, MDD <= 30%, cháy <= 5%.

def p(name: str, default: float) -> dict:
    return {"param": name, "default": default}


OPTIMIZATION_SPACES = [
    {
        "id": "dca_reversion_long_perp", "family": "Bắt hồi + DCA", "side": "LONG", "venue": "cex",
        "fixed": {"market": "perp"},
        "tree": cond((f("5m", "rsi_14"), "<", p("rsi_lo", 30)), (f("5m", "close"), "<", f("5m", "bbl_20_2")),
                     (f("1h", "er_20"), "<", p("er_max", 0.35))),
        "space": {
            "leverage": [2, 3, 5, 10], "order_size_pct": [10, 20, 30], "dca_step_pct": [0.5, 0.8, 1.2, 2.0],
            "dca_max_layers": [2, 3, 4], "dca_size_multiplier": [1.0, 1.5], "take_profit_rate": [0.4, 0.8, 1.5, 3.0],
            "stop_loss_rate": [3, 5, 8], "timeout": [720, 2880, 10080], "sig.rsi_lo": [20, 25, 30],
            "sig.er_max": [0.2, 0.3, 0.45],
        },
    },
    {
        "id": "dca_reversion_short_perp", "family": "Bắt hồi + DCA", "side": "SHORT", "venue": "cex",
        "fixed": {"market": "perp"},
        "tree": cond((f("5m", "rsi_14"), ">", p("rsi_hi", 70)), (f("5m", "close"), ">", f("5m", "bbu_20_2")),
                     (f("1h", "er_20"), "<", p("er_max", 0.35))),
        "space": {
            "leverage": [2, 3, 5, 10], "order_size_pct": [10, 20, 30], "dca_step_pct": [0.5, 0.8, 1.2, 2.0],
            "dca_max_layers": [2, 3, 4], "dca_size_multiplier": [1.0, 1.5], "take_profit_rate": [0.4, 0.8, 1.5, 3.0],
            "stop_loss_rate": [3, 5, 8], "timeout": [720, 2880, 10080], "sig.rsi_hi": [70, 75, 80],
            "sig.er_max": [0.2, 0.3, 0.45],
        },
    },
    {
        "id": "trend_long_perp", "family": "Theo xu hướng", "side": "LONG", "venue": "cex",
        "fixed": {"market": "perp"},
        "tree": cond((f("1h", "ema_50"), ">", f("1h", "ema_200")), (f("1h", "adx_14"), ">", p("adx_min", 20)),
                     (f("15m", "close"), ">", f("15m", "dch_20"))),
        "space": {
            "leverage": [1, 2, 3, 5], "order_size_pct": [30, 50, 100], "stop_loss_rate": [1.5, 2.5, 4.0],
            "trailing_stop": [1.0, 2.0, 3.0, 5.0], "trailing_activation_pct": [0.0, 0.5, 1.5],
            "timeout": [0, 1440, 4320], "sig.adx_min": [15, 20, 25, 30],
        },
    },
    {
        "id": "trend_short_perp", "family": "Theo xu hướng", "side": "SHORT", "venue": "cex",
        "fixed": {"market": "perp"},
        "tree": cond((f("1h", "ema_50"), "<", f("1h", "ema_200")), (f("1h", "adx_14"), ">", p("adx_min", 20)),
                     (f("15m", "close"), "<", f("15m", "dcl_20"))),
        "space": {
            "leverage": [1, 2, 3, 5], "order_size_pct": [30, 50, 100], "stop_loss_rate": [1.5, 2.5, 4.0],
            "trailing_stop": [1.0, 2.0, 3.0, 5.0], "trailing_activation_pct": [0.0, 0.5, 1.5],
            "timeout": [0, 1440, 4320], "sig.adx_min": [15, 20, 25, 30],
        },
    },
    {
        "id": "dex_dip_reversion_spot", "family": "Bắt hồi (DEX)", "side": "LONG", "venue": "dex",
        "fixed": {"market": "spot"},
        "tree": cond((f("1m", "rsi_7"), "<", p("rsi_lo", 20)), (f("1m", "bbz_60"), "<", p("z_lo", -2.5))),
        "space": {
            "order_size_pct": [20, 50, 100], "take_profit_rate": [1.0, 1.5, 2.5, 4.0], "stop_loss_rate": [2, 3, 5],
            "timeout": [120, 480, 1440], "dca_step_pct": [0, 1.5], "dca_max_layers": [0, 2],
            "sig.rsi_lo": [10, 15, 20], "sig.z_lo": [-2.0, -2.5, -3.0, -3.5],
        },
    },
]
