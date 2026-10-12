"""P17 — thống kê kết quả lấy từ NautilusTrader (backend/nautilus/stats.py): bằng đúng các lớp Nautilus, khoá payload giữ nguyên."""
import math

import numpy as np
import pandas as pd
import pytest
from nautilus_trader.analysis import (
    CAGR, AvgLoser, AvgWinner, CalmarRatio, Expectancy, MaxDrawdown, ProfitFactor, ReturnsVolatility, SharpeRatio, SortinoRatio, WinRate,
)

from backend.metrics import metrics as mm
from backend.metrics import trades as tr
from backend.nautilus import stats as ns

R = [0.01, -0.02, 0.03, 0.0, -0.01, 0.02, 0.015, -0.005]
PNL = [5.0, -2.0, 3.0, 0.0, -1.0]
IDX = pd.date_range("2025-01-01", periods=len(R))
RD = {t.value: v for t, v in zip(IDX, R)}


def test_returns_stats_equal_nautilus_classes_with_365():
    s = ns.returns_stats(pd.Series(R, index=IDX))
    assert s["sharpe"] == SharpeRatio(365).calculate_from_returns(RD)
    assert s["sortino"] == SortinoRatio(365).calculate_from_returns(RD)
    assert s["returns_volatility"] == ReturnsVolatility(365).calculate_from_returns(RD)
    assert s["cagr"] == CAGR(365).calculate_from_returns(RD)
    assert s["max_drawdown"] == MaxDrawdown().calculate_from_returns(RD)
    assert s["calmar"] == CalmarRatio(365).calculate_from_returns(RD)
    assert s["profit_factor"] == ProfitFactor().calculate_from_returns(RD)
    # công thức Nautilus = công thức chuẩn với năm 365 (Nautilus mặc định 252 — Nora truyền period)
    r = np.asarray(R)
    assert s["sharpe"] == pytest.approx(r.mean() / r.std(ddof=1) * math.sqrt(365))
    assert s["sharpe"] != pytest.approx(SharpeRatio().calculate_from_returns(RD))       # period mặc định 252 cho số khác
    assert s["profit_factor"] == pytest.approx(r[r > 0].sum() / -r[r < 0].sum())


def test_array_input_uses_consecutive_days_same_as_dated_series():
    assert ns.returns_stats(np.asarray(R)) == ns.returns_stats(pd.Series(R, index=IDX))


def test_pnl_stats_equal_nautilus_classes():
    s = ns.pnl_stats(PNL, [1.0, -0.5, 0.6, 0.0, -0.2])
    assert s["win_rate"] == WinRate().calculate_from_realized_pnls(PNL) * 100 == 40.0
    assert s["expectancy"] == Expectancy().calculate_from_realized_pnls(PNL) == 1.25        # bỏ lệnh hoà: (5-2+3-1)/4
    assert s["avg_winner"] == AvgWinner().calculate_from_realized_pnls(PNL) == 4.0
    assert s["avg_loser"] == AvgLoser().calculate_from_realized_pnls(PNL) == -1.5
    assert s["expectancy_pct"] == pytest.approx((1.0 - 0.5 + 0.6 - 0.2) / 4)


def test_undefined_is_none_not_zero():
    assert ns.compute([0.01], []) == {k: None for k in ns.compute([0.01], [])}
    s = ns.compute([0.01, 0.02, 0.01], [1.0, 2.0])
    assert s["sortino"] is None and s["profit_factor"] is None and s["win_rate"] == 100.0       # không có ngày/lệnh lỗ
    assert ns.trade_profit_factor([1.0, -2.0]) == pytest.approx(0.5) and ns.trade_profit_factor([1.0]) is None and ns.trade_profit_factor([]) is None


def test_metrics_module_delegates_to_nautilus():
    r = np.asarray(R)
    assert mm.sharpe(r) == ns.returns_stats(r)["sharpe"] and mm.sortino(r) == ns.returns_stats(r)["sortino"]
    rm = mm.return_metrics(r)
    n = ns.returns_stats(r)
    assert rm["sharpe"] == n["sharpe"] and rm["calmar"] == n["calmar"] and rm["profit_factor"] == n["profit_factor"]
    assert rm["cagr_pct"] == pytest.approx(n["cagr"] * 100) and rm["mdd_daily_pct"] == pytest.approx(-n["max_drawdown"] * 100)
    assert rm["mdd_daily_pct"] == pytest.approx(mm.drawdown_stats(r)["mdd_daily_pct"])    # trùng cách dựng đường sụt giảm


def _row(pnl, t=0):
    return {"pnl_usd": pnl, "pnl_pct": pnl / 10.0, "close_time": t, "enter_time": t - 3_600_000, "fees_usd": 0.0, "funding_usd": 0.0, "symbol": "X",
            "strategy": "s", "side": "LONG", "status": "CLOSED", "layers": 1, "mae_pct": -1.0, "margin_usd": 0.0, "entry_equity": 0.0}


def test_stage_payload_keys_unchanged_and_values_from_nautilus():
    rows = [_row(p, i * 86_400_000) for i, p in enumerate(PNL)]
    blk = mm.series_metrics(np.asarray(R), rows)
    assert {"ret_pct", "mdd_pct", "sharpe", "sortino", "trades", "win_rate", "win_rate_note", "profit_factor", "profit_factor_note", "oos_days",
            "mdd_daily_pct", "mdd_basis", "cagr_pct", "calmar"} <= set(blk)
    n = ns.compute(np.asarray(R), PNL)
    assert blk["sharpe"] == round(n["sharpe"], 2) and blk["sortino"] == round(n["sortino"], 2) and blk["calmar"] == round(n["calmar"], 2)
    assert blk["win_rate"] == round(n["win_rate"], 1) and blk["profit_factor"] == round(ns.trade_profit_factor(PNL), 3)   # PF giai đoạn = Nautilus ProfitFactor trên PnL từng lệnh
    assert blk["mdd_pct"] == round(-n["max_drawdown"] * 100, 2) and blk["cagr_pct"] == round(n["cagr"] * 100, 2)
    stage = tr._metric_block(np.r_[0.0, R], rows, 12.345)
    assert set(stage) == {"ret_pct", "mdd_pct", "sharpe", "sortino", "cagr_pct", "calmar", "trades", "win_rate_trades", "profit_factor_trades", "fees_usd"}
    assert stage["win_rate_trades"] == blk["win_rate"] and stage["profit_factor_trades"] == blk["profit_factor"] and stage["fees_usd"] == 12.35


def test_trade_metrics_use_nautilus_pnl_stats():
    m = tr.trade_metrics([_row(p, i * 86_400_000) for i, p in enumerate(PNL)])
    assert (m["win_rate"], m["avg_win_usd"], m["avg_loss_usd"], m["expectancy_usd"]) == (40.0, 4.0, -1.5, 1.25)
    assert m["profit_factor"] == pytest.approx(8 / 3) and m["payoff"] == pytest.approx(4.0 / 1.5)
