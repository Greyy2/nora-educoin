"""Bộ số đo chuẩn (core/metrics): mỗi công thức kiểm bằng ví dụ tính tay."""
import math

import numpy as np
import pytest

from backend.metrics import metrics as rt
from backend.metrics.metrics import curve_mdd_pct, series_metrics
from backend.metrics.trades import NOTE_NO_LOSSES, NOTE_NO_PNL, NOTE_NO_TRADES, exposure_metrics, strategy_correlation, trade_metrics, trade_stats

H = 3_600_000
D = 24 * H


def _t(pnl, side="LONG", enter=0, close=H, pct=None, fees=0.0, mae=0.0, margin=0.0, eq=0.0, lev=1.0, status="TP", strategy="a",
       layers=1):
    return {"symbol": "X@perp", "strategy": strategy, "side": side, "enter_time": enter, "close_time": close, "enter_price": 1.0,
            "close_price": 1.0, "qty": 1.0, "pnl_usd": pnl, "pnl_pct": pnl if pct is None else pct, "fees_usd": fees, "funding_usd": 0.0,
            "status": status, "layers": layers, "mae_pct": mae, "margin_usd": margin, "leverage": lev, "entry_equity": eq}


# ─── Chuỗi ngày ─────────────────────────────────────────────────────────────
def test_sharpe_sortino_match_formula_and_none_when_undefined():
    r = np.array([0.01, -0.02, 0.03, 0.0])
    assert rt.sharpe(r) == pytest.approx(r.mean() / r.std(ddof=1) * math.sqrt(365))
    assert rt.sortino(r) == pytest.approx(r.mean() / math.sqrt(np.mean(np.minimum(r, 0) ** 2)) * math.sqrt(365))
    assert rt.sharpe([0.01]) is None and rt.sharpe([0.01, 0.01]) is None          # 1 ngày / độ lệch 0
    assert rt.sortino([0.01, 0.02]) is None                                       # không có ngày lỗ


def test_cagr_total_return_vol():
    r = [0.01] * 365
    assert rt.total_return_pct(r) == pytest.approx((1.01 ** 365 - 1) * 100)
    assert rt.cagr_pct(r) == pytest.approx((1.01 ** 365 - 1) * 100)              # đúng 1 năm: CAGR = lãi kỳ
    assert rt.cagr_pct([0.01] * 730) == pytest.approx((1.01 ** 365 - 1) * 100)   # 2 năm: quy về 1 năm
    assert rt.cagr_pct([-1.0, 0.1]) == -100.0 and rt.cagr_pct([]) is None
    assert rt.vol_ann_pct([0.01, -0.01]) == pytest.approx(np.std([0.01, -0.01], ddof=1) * math.sqrt(365) * 100)


def test_var_cvar_historical():
    r = np.linspace(-0.10, 0.09, 20)                  # 20 ngày, tệ nhất -10%
    var, cvar = rt.var_cvar_pct(r)
    q = np.percentile(r, 5)
    assert var == pytest.approx(-q * 100) and cvar == pytest.approx(-r[r <= q].mean() * 100)
    assert rt.var_cvar_pct([0.01]) == (None, None)
    assert rt.var_cvar_pct([0.01, 0.02])[0] == 0.0    # phân vị không âm -> VaR 0


def test_drawdown_stats_depth_duration_recovery():
    # vốn: 1 -> 1.1 -> 0.99 (−10%) -> 1.045 -> 1.1 (về đỉnh sau 2 ngày từ đáy) -> 1.21
    r = [0.10, -0.10, 1.045 / 0.99 - 1, 1.1 / 1.045 - 1, 0.10]
    d = rt.drawdown_stats(r)
    assert d["mdd_daily_pct"] == pytest.approx(10.0) and d["max_dd_days"] == 2 and d["recovery_days"] == 2
    assert rt.equity_mdd_pct(r) == pytest.approx(d["mdd_daily_pct"])
    assert rt.drawdown_stats([0.1, -0.2])["recovery_days"] is None                 # chưa hồi phục
    assert rt.drawdown_stats([])["mdd_daily_pct"] == 0.0
    flat = rt.drawdown_stats([0.01, 0.01])
    assert flat["mdd_daily_pct"] == 0.0 and flat["recovery_days"] == 0 and flat["ulcer_index"] == 0.0


def test_return_metrics_calmar_and_win_days():
    r = [0.02, -0.01, 0.0, 0.03, -0.02]
    m = rt.return_metrics(r)
    assert m["calmar"] == pytest.approx(m["cagr_pct"] / m["mdd_daily_pct"])
    assert m["win_days_pct"] == pytest.approx(50.0)                               # ngày 0% không tính
    assert m["best_day_pct"] == pytest.approx(3.0) and m["worst_day_pct"] == pytest.approx(-2.0) and m["days"] == 5


# ─── Theo lệnh ──────────────────────────────────────────────────────────────
def test_trade_metrics_win_loss_breakeven_payoff_expectancy():
    rows = [_t(30, close=1 * H), _t(-10, close=2 * H), _t(0, close=3 * H), _t(20, close=4 * H), _t(-10, close=5 * H)]
    m = trade_metrics(rows)
    assert (m["trades"], m["wins"], m["losses"], m["breakeven"]) == (5, 2, 2, 1)
    assert m["win_rate"] == 40.0 and m["loss_rate"] == 40.0                       # hoà không là thua
    assert m["profit_factor"] == pytest.approx(50 / 20) and m["payoff"] == pytest.approx(25 / 10)
    # Nautilus Expectancy = TB PnL các lệnh KHÁC 0 (bỏ lệnh hoà): 30 / 4 (Nora cũ chia cho cả lệnh hoà: 30 / 5)
    assert m["expectancy_usd"] == pytest.approx(30 / 4) and m["pnl_usd"] == 30
    assert m["best_trade_usd"] == 30 and m["worst_trade_usd"] == -10
    assert m["top5_share_pct"] == pytest.approx(100.0)
    assert trade_stats(rows) == {"win_rate": 40.0, "win_rate_note": None, "profit_factor": 2.5, "profit_factor_note": None}


def test_consecutive_losses_in_close_order_and_pf_undefined_without_losses():
    rows = [_t(-1, close=5 * H), _t(-1, close=1 * H), _t(5, close=3 * H), _t(-1, close=4 * H), _t(-1, close=2 * H)]
    m = trade_metrics(rows)                     # theo thời gian đóng: L L W L L
    assert m["max_consec_losses"] == 2 and m["max_consec_wins"] == 1
    only_wins = trade_metrics([_t(1), _t(2)])
    # P9.11: không có lệnh thua -> PF không xác định (None) + lý do, KHÔNG phải số chặn 99
    assert only_wins["profit_factor"] is None and only_wins["profit_factor_note"] == NOTE_NO_LOSSES
    assert only_wins["win_rate"] == 100.0 and only_wins["losses"] == 0 and only_wins["payoff"] is None
    assert trade_stats([_t(1), _t(2)]) == {"win_rate": 100.0, "win_rate_note": None, "profit_factor": None, "profit_factor_note": NOTE_NO_LOSSES}
    assert trade_stats([_t(0), _t(0)])["profit_factor_note"] == NOTE_NO_PNL and trade_stats([_t(0)])["win_rate"] == 0.0   # chỉ lệnh hoà
    assert trade_metrics([_t(-1), _t(1)])["profit_factor"] == 1.0 and trade_metrics([_t(-1), _t(1)])["profit_factor_note"] is None


def test_zero_trades_give_none_not_zero():
    m = trade_metrics([])
    assert m["trades"] == 0 and m["win_rate"] is None and m["loss_rate"] is None and m["profit_factor"] is None
    assert m["win_rate_note"] == NOTE_NO_TRADES and m["profit_factor_note"] == NOTE_NO_TRADES
    assert trade_stats([]) == {"win_rate": None, "win_rate_note": NOTE_NO_TRADES, "profit_factor": None, "profit_factor_note": NOTE_NO_TRADES}
    # đường phễu: series_metrics không lệnh -> None (không 0 giả), cổng S1 vẫn quyết định theo số lệnh
    from backend.metrics.metrics import series_metrics
    sm = series_metrics([0.001, -0.002], [])
    assert sm["trades"] == 0 and sm["win_rate"] is None and sm["profit_factor"] is None and sm["profit_factor_note"] == NOTE_NO_TRADES


def test_fee_drag_hold_time_long_short():
    rows = [_t(8, fees=2, enter=0, close=2 * H), _t(-3, side="SHORT", fees=1, enter=0, close=4 * H)]
    m = trade_metrics(rows)
    assert m["fee_drag_pct"] == pytest.approx(3 / (5 + 3) * 100)               # phí / lãi trước phí
    assert m["avg_hold_h"] == pytest.approx(3.0) and m["max_hold_h"] == pytest.approx(4.0)
    assert m["long"] == {"trades": 1, "pnl_usd": 8.0, "win_rate": 100.0}
    assert m["short"] == {"trades": 1, "pnl_usd": -3.0, "win_rate": 0.0}
    assert trade_metrics([_t(-5, fees=1)])["fee_drag_pct"] is None              # lãi trước phí <= 0


def test_dca_metrics_mae_layers_liquidation_proximity():
    # lệnh 1: vốn lúc mở 1000, lỗ treo tối đa −5% vốn = −50 USD, ký quỹ 100 -> đã ăn 50% ký quỹ; lệnh 2: bị thanh lý (mất 100% ký quỹ)
    rows = [_t(10, mae=-5.0, margin=100, eq=1000, layers=3), _t(-100, mae=-10.0, margin=100, eq=1000, status="LIQ", layers=5)]
    m = trade_metrics(rows)
    assert m["liq_proximity_max_pct"] == pytest.approx(100.0) and m["liquidations"] == 1
    assert m["layers_max"] == 5 and m["layers_avg"] == 4.0
    assert m["mae_worst_pct"] == -10.0 and m["mae_avg_pct"] == -7.5
    assert trade_metrics([_t(1, mae=-5.0, margin=100, eq=1000)])["liq_proximity_max_pct"] == pytest.approx(50.0)


def test_exposure_time_in_market_and_peaks():
    cap = 1000.0
    rows = [_t(1, enter=0, close=4 * H, margin=100, lev=2),                      # danh nghĩa 200 long
            _t(1, side="SHORT", enter=2 * H, close=6 * H, margin=50, lev=4)]     # danh nghĩa 200 short
    e = exposure_metrics(rows, 0, 8 * H, cap)
    assert e["time_in_market_pct"] == pytest.approx(6 / 8 * 100)
    assert e["peak_margin_pct"] == pytest.approx(15.0) and e["max_concurrent"] == 2
    assert e["exposure_gross_max_pct"] == pytest.approx(40.0)
    assert e["exposure_gross_avg_pct"] == pytest.approx((200 * 4 + 200 * 4) / 8 / cap * 100)
    assert e["exposure_net_max_pct"] == pytest.approx(20.0)                      # 0 khi cả hai mở, 20% khi một bên
    assert exposure_metrics([], 0, 8 * H, cap)["time_in_market_pct"] == 0.0


def test_strategy_correlation():
    rows = [_t(1, strategy="a", close=0 * D + H), _t(2, strategy="a", close=1 * D + H), _t(-1, strategy="a", close=2 * D + H),
            _t(2, strategy="b", close=0 * D + H), _t(4, strategy="b", close=1 * D + H), _t(-2, strategy="b", close=2 * D + H)]
    c = strategy_correlation(rows, 0, 2 * D + H)
    assert c["pairs"]["a|b"] == pytest.approx(1.0) and c["avg"] == pytest.approx(1.0)
    assert strategy_correlation(rows[:3], 0, 3 * D) is None


# ─── Tổng hợp ───────────────────────────────────────────────────────────────
def test_curve_mdd_uses_worst_price_of_bar():
    curve = [{"time": 1, "equity": 100.0, "equity_worst": 100.0}, {"time": 2, "equity": 110.0, "equity_worst": 99.0},
             {"time": 3, "equity": 105.0, "equity_worst": 104.0}]
    assert curve_mdd_pct(curve, 0, 100.0) == pytest.approx((110 - 99) / 110 * 100)   # đỉnh 110 cùng nến với giá xấu 99
    assert curve_mdd_pct(curve, 3, 100.0) == pytest.approx((105 - 104) / 105 * 100)   # chỉ từ start_ts; giá xấu trong nến vẫn tính


def test_series_metrics_keeps_old_values_and_adds_extras():
    d = np.array([0.01, -0.02, 0.015, 0.0, -0.005, 0.02])
    trades = [_t(5, pct=0.5), _t(-2, pct=-0.2)]
    m = series_metrics(d, trades)
    sd = d.std(ddof=1)
    assert m["ret_pct"] == round((np.prod(1 + d) - 1) * 100, 2) and m["sharpe"] == round(d.mean() / sd * math.sqrt(365), 2)
    assert m["mdd_pct"] == m["mdd_daily_pct"] == round(rt.equity_mdd_pct(d), 2) and m["mdd_basis"] == "daily"
    assert m["win_rate"] == 50.0 and m["payoff"] == 2.5 and m["max_consec_losses"] == 1
    assert m["cagr_pct"] == round(rt.cagr_pct(d), 2) and m["calmar"] == round(rt.return_metrics(d)["calmar"], 2)


def test_equity_series_summary_and_pnl_since_start():
    s = rt.equity_series_summary([100.0, 120.0, 90.0, 110.0])
    assert s["bars"] == 4 and s["start"] == 100.0 and s["last"] == 110.0 and s["mdd_pct"] == pytest.approx(25.0) and s["mdd_note"] is None
    one = rt.equity_series_summary([100.0])
    assert one["mdd_pct"] is None and one["mdd_note"] and rt.equity_series_summary([])["start"] is None
    assert rt.pnl_since_start(100.0, 110.0) == {"pnl_usd": 10.0, "pnl_pct": pytest.approx(10.0), "pnl_note": None}
    assert rt.pnl_since_start(None, 5.0)["pnl_pct"] is None and rt.pnl_since_start(0.0, 5.0)["pnl_note"]
