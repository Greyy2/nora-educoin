"""Số đo kết quả backtest DANH MỤC dùng chung cho build_strategy_book, WFA danh mục và validate_book.

- portfolio_metrics: từ results của PortfolioEngine -> lãi, MDD (điểm xấu nhất trong nến), sharpe, lợi suất ngày MTM...
- bootstrap_daily: block bootstrap 1 năm trên lợi suất ngày (mỏng bọc run_monte_carlo_daily).
Chuyển nguyên văn từ backend/optimize/book.py (metrics/bootstrap) — KHÔNG đổi hành vi, cùng RNG, cùng làm tròn.
"""
import math
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from backend.core.metrics.returns import daily_returns_from_curve, equity_mdd_pct, sortino_annual
from backend.core.metrics.trades import trade_stats


def portfolio_metrics(res, start_ts):
    """Số đo của `res` (PortfolioEngine.get_results()) từ `start_ts` trở đi (bỏ phần warmup).
    `daily` = lợi suất ngày theo vốn MTM (đóng cửa), nối từ vốn ban đầu; ngày lấy theo UTC."""
    curve = pd.DataFrame(res["equity_curve"])
    curve = curve[curve["time"] >= start_ts]
    eq = curve["equity"].to_numpy()
    worst = curve["equity_worst"].to_numpy()
    init = res["initial_capital"]
    peak = np.maximum.accumulate(np.r_[init, eq])[1:]
    mdd = float(np.max((peak - np.minimum(eq, worst)) / peak) * 100) if len(eq) else 0.0
    daily = pd.Series(daily_returns_from_curve(res["equity_curve"], start_ts, init), dtype=float)
    sharpe = float(daily.mean() / daily.std() * np.sqrt(365)) if daily.std() > 0 else 0.0
    by_sym = {k.split("@")[0]: round(v["pnl_usd"], 2) for k, v in res["by_symbol"].items()}
    return {
        "ret_pct": round((res["final_equity"] / init - 1) * 100, 2), "mdd_pct": round(mdd, 2), "sharpe": round(sharpe, 2),
        "trades": len(res["positions"]), "win_pct": round(float(np.mean([p.real_pnl > 0 for p in res["positions"]]) * 100), 1)
        if res["positions"] else 0.0,
        "symbols_positive": sum(v > 0 for v in by_sym.values()), "by_symbol": by_sym,
        "by_strategy": {k: {"pnl_usd": round(v["pnl_usd"], 2), "trades": v["trades"]} for k, v in res["by_strategy"].items()},
        "fees_usd": round(sum(p.fees_usd or 0 for p in res["positions"]), 2),
        "funding_usd": round(sum(p.funding_usd or 0 for p in res["positions"]), 2),
        "rejected_for_risk": res["rejected_for_risk"], "rejected_for_capital": res["rejected_for_capital"],
        "halted_at": res["halted_at"], "daily": [round(float(x), 6) for x in daily.to_numpy()],
    }


def series_metrics(daily, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Số đo phẳng từ chuỗi ngày nối + danh sách lệnh (cho S3/S4/S5): lãi kép, MDD ngày, Sharpe/Sortino quy năm, lệnh, win rate, PF."""
    d = np.asarray(daily, dtype=float)
    sd = float(d.std(ddof=1)) if d.size > 1 else 0.0
    return {"ret_pct": round(float((np.prod(1.0 + d) - 1.0) * 100), 2) if d.size else 0.0, "mdd_pct": round(equity_mdd_pct(d), 2),
            "sharpe": round(float(d.mean() / sd * math.sqrt(365)), 2) if sd > 0 else 0.0, "sortino": round(sortino_annual(d), 2),
            "trades": len(trades), **trade_stats(trades), "oos_days": int(d.size)}
