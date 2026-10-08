"""Thư viện tín hiệu + chiến lược mẫu từ nghiên cứu 28 bot top OKX/Binance (okx-report.html, 28–29/09/2026) — CHỈ cho test/script nghiên cứu
(chuyển từ library.py cũ của thư mục strategy trong core ở P9.9: không backend nào dùng; chiến lược hệ thống nay là file DSL trong data/alpha/strategies/).
Mỗi SIGNAL là một cây điều kiện AST trên kernel, kiểm riêng bằng core/signal.check_signals trước khi ghép tham số vị thế thành STRATEGY."""
from typing import Any, Dict, List

from backend.alpha.compile import cond, f


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


# Bot DCA dùng order_size_pct=19 (không phải 20): lệnh đầu + 4 tầng ×1,0 = 5 × 19% + phí ≤ 100% vốn nên tầng 5
# luôn khớp được; ở 20% thì 5 × 20% + phí > 100% và tầng cuối bị bỏ âm thầm (backtest/params_builder.dca_budget_check).
KERNEL_STRATEGIES: List[Dict[str, Any]] = [
    _strategy(
        "okx_dca_reversion_long", "Bắt hồi + DCA vừa (spot)", "dip_5m_rsi_bb_ranging", "Bắt hồi + DCA",
        "Kiểu 'DCA vừa' của bot top OKX: vào khi 5m quá bán trong regime đi ngang, nhồi mỗi 0,75% tối đa "
        "4 tầng cùng size, chốt 0,8% từ giá TB. KHÁC bot OKX: cắt lỗ cứng 6% từ giá TB, timeout 3 ngày.",
        {"market": "spot", "leverage": 1.0, "order_size_pct": 19.0, "dca_step_pct": 0.75, "dca_max_layers": 4,
         "dca_size_multiplier": 1.0, "take_profit_rate": 0.8, "stop_loss_rate": 6.0, "timeout": 4320},
        "okx-report 6.4: DCA vừa — bước 0,74%, 4 tầng, ×1,0, 10x",
    ),
    _strategy(
        "okx_dca_reversion_short_perp", "Bắt hồi + DCA vừa (short perp 5x)", "rip_5m_rsi_bb_ranging",
        "Bắt hồi + DCA",
        "Chiều short của lối bắt hồi (nhiều bot top chạy hai chiều). Perp 5x, ký quỹ isolated, "
        "có thanh lý. Giá spot làm proxy, chưa tính funding.",
        {"market": "perp", "leverage": 5.0, "order_size_pct": 19.0, "dca_step_pct": 0.75, "dca_max_layers": 4,
         "dca_size_multiplier": 1.0, "take_profit_rate": 0.8, "stop_loss_rate": 6.0, "timeout": 4320},
        "okx-report 4.1: cùng người tạo chạy DCA long và DCA short",
    ),
    _strategy(
        "okx_dca_dense_fast", "DCA dày, chốt nhanh (spot)", "dip_1m_deep_zscore", "Bắt hồi + DCA (dày)",
        "Kiểu 'DCA dày' của bot top OKX: bước 0,3%, 4 tầng, chốt 0,4% từ giá TB. Phí spot 0,1%/chiều ăn "
        "gần hết biên lãi — dùng để kiểm chứng lối này có sống được sau phí hay không.",
        {"market": "spot", "leverage": 1.0, "order_size_pct": 19.0, "dca_step_pct": 0.3, "dca_max_layers": 4,
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
