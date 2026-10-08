"""Số đo lợi suất NGÀY mark-to-market dùng chung: daily_returns_from_curve = đúng chuỗi ngày mà portfolio_metrics từng tự tính (so với bản cũ, từng bit)."""
import os

import numpy as np
import pandas as pd

from backend.metrics.metrics import daily_returns_from_curve
from backend.metrics.metrics import portfolio_metrics
from test_round3_completion import T0, D

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ── 1. Số đo dùng chung ─────────────────────────────────────────────────────
def _old_portfolio_daily(res, start_ts):
    """Bản gốc của portfolio_metrics (trước khi tách daily_returns_from_curve) — giữ nguyên để so từng bit."""
    curve = pd.DataFrame(res["equity_curve"])
    curve = curve[curve["time"] >= start_ts]
    eq = curve["equity"].to_numpy()
    worst = curve["equity_worst"].to_numpy()
    init = res["initial_capital"]
    peak = np.maximum.accumulate(np.r_[init, eq])[1:]
    mdd = float(np.max((peak - np.minimum(eq, worst)) / peak) * 100) if len(eq) else 0.0
    s = pd.Series(eq, index=pd.to_datetime(curve["time"], unit="ms"))
    daily = s.resample("1D").last().ffill()
    daily = pd.concat([pd.Series([init], index=[daily.index[0] - pd.Timedelta(days=1)]), daily]).pct_change().dropna()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(365)) if daily.std() > 0 else 0.0
    return daily, mdd, sharpe


def _synthetic_res(n_days=40, seed=11):
    rng = np.random.default_rng(seed)
    t = T0 + 3_600_000 * 5 + np.arange(n_days * 96, dtype=np.int64) * 900_000     # 15 phút/điểm, lệch ngày
    eq = 10_000 * np.cumprod(1 + rng.normal(0.0002, 0.004, len(t)))
    keep = np.ones(len(t), bool)
    keep[500:700] = False                                                         # khoảng trống -> ffill
    rows = [{"time": int(a), "equity": round(float(b), 4), "equity_worst": round(float(b) * 0.995, 4)}
            for a, b, k in zip(t, eq, keep) if k]
    return {"equity_curve": rows, "initial_capital": 10_000.0}


def test_daily_returns_from_curve_identical_to_old_portfolio_series():
    res = _synthetic_res()
    start = T0 + 3 * D + 7 * 3_600_000                                            # cắt giữa ngày (bỏ warmup)
    old_daily, old_mdd, old_sharpe = _old_portfolio_daily(res, start)
    new = daily_returns_from_curve(res["equity_curve"], start, res["initial_capital"])
    assert new == [float(x) for x in old_daily.to_numpy()]                        # bit-identical, chưa làm tròn
    full = dict(res, final_equity=10_500.0, positions=[], by_symbol={}, by_strategy={},
                rejected_for_risk=0, rejected_for_capital=0, halted_at=None)
    m = portfolio_metrics(full, start)
    assert m["daily"] == [round(float(x), 6) for x in old_daily.to_numpy()]
    assert m["sharpe"] == round(old_sharpe, 2) and m["mdd_pct"] == round(old_mdd, 2)


def test_daily_returns_from_curve_empty_and_before_start():
    assert daily_returns_from_curve([], 0, 1000.0) == []
    rows = [{"time": 1000, "equity": 1000.0, "equity_worst": 1000.0}]
    assert daily_returns_from_curve(rows, 10**13, 1000.0) == []
