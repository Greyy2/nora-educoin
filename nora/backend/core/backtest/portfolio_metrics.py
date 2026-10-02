"""Số đo kết quả backtest DANH MỤC dùng chung cho build_strategy_book, WFA danh mục và validate_book.

- portfolio_metrics: từ results của PortfolioEngine -> lãi, MDD (điểm xấu nhất trong nến), sharpe, lợi suất ngày MTM...
- bootstrap_daily: block bootstrap 1 năm trên lợi suất ngày (mỏng bọc run_monte_carlo_daily).
Chuyển nguyên văn từ backend/optimize/build_strategy_book.py (metrics/bootstrap) — KHÔNG đổi hành vi, cùng RNG, cùng làm tròn.
"""
import numpy as np
import pandas as pd

MDD_LIMIT = 30.0


def daily_returns_from_curve(curve_rows, start_ts, initial_capital):
    """Lợi suất ngày MTM (vốn đóng cửa mỗi ngày UTC) từ đường vốn `curve_rows` (list dict time/equity/...),
    chỉ lấy điểm có time >= start_ts, nối từ vốn ban đầu. Dùng chung cho danh mục, WFA đơn tài sản và Monte Carlo ngày."""
    curve = pd.DataFrame(curve_rows)
    if curve.empty:
        return []
    curve = curve[curve["time"] >= start_ts]
    if curve.empty:
        return []
    s = pd.Series(curve["equity"].to_numpy(), index=pd.to_datetime(curve["time"], unit="ms"))
    daily = s.resample("1D").last().ffill()
    daily = pd.concat([pd.Series([initial_capital], index=[daily.index[0] - pd.Timedelta(days=1)]), daily]).pct_change().dropna()
    return [float(x) for x in daily.to_numpy()]


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


def bootstrap_daily(daily, scale, n=10_000, block=5, horizon=365, seed=1):  # n = carlo.MC_MIN_SIMULATIONS
    """Block bootstrap lợi suất ngày (nhân `scale` = hệ số rủi ro). Giữ khoá kết quả cũ của build_strategy_book."""
    from backend.carlo.monte_carlo import run_monte_carlo_daily  # import muộn: tránh kéo pydantic vào worker
    r = run_monte_carlo_daily(daily, simulations=n, block_days=block, horizon_days=horizon,
                              ruin_threshold_pct=MDD_LIMIT, seed=seed, scale=scale)
    return {"median_ret_pct": r["median_ret_pct"], "p05_ret_pct": r["p05_ret_pct"], "mdd_p95_pct": r["mdd_p95_pct"],
            "p_mdd_ge_30_pct": r["p_mdd_ge_ruin_pct"]}
