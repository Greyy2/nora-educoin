"""Bộ số đo chuẩn của MỘT lần chạy — mọi tầng (backtest, dựng sổ, WFA, phễu, trang Danh mục) dùng chung.

portfolio_metrics(res, start_ts)  từ PortfolioEngine.get_results() (bỏ phần warmup trước start_ts):
    khoá phẳng (định dạng cũ, gate/bảng đọc): ret_pct, mdd_pct (= MDD TRONG NẾN, khắt nhất), sharpe, trades, win_pct, symbols_positive,
    by_symbol, by_strategy, fees_usd, funding_usd, rejected_*, halted_at, daily
    + mdd_intrabar_pct, mdd_daily_pct, mdd_basis="intrabar", cagr_pct, calmar
    + stats = {returns: metrics/returns.return_metrics, trades: metrics/trades.trade_metrics, exposure, correlation}
series_metrics(daily, trades)     từ chuỗi ngày nối + lệnh (OOS của WFA/phễu): mdd_pct = MDD THEO NGÀY (mdd_basis="daily").

Hai kiểu MDD: trong nến = đỉnh vốn MTM so với vốn ở giá XẤU NHẤT của nến (engine ghi equity_worst mỗi mẫu) — chỉ có khi có đường vốn engine;
theo ngày = trên vốn đóng ngày. Trong nến >= theo ngày. Gate dùng `mdd_pct` của nguồn tương ứng; UI hiện cả hai.
"""
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from backend.core.metrics.returns import daily_returns_from_curve, return_metrics
from backend.core.metrics.trades import exposure_metrics, strategy_correlation, trade_metrics, trade_rows, trade_stats


def _r(x, nd=2):
    return None if x is None else round(float(x), nd)


def _round_tree(obj, nd=4):
    if isinstance(obj, float):
        return round(obj, nd) if np.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _round_tree(v, nd) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_tree(v, nd) for v in obj]
    return obj


def curve_mdd_pct(curve_rows, start_ts, initial_capital) -> float:
    """MDD TRONG NẾN (%) từ đường vốn engine: đỉnh vốn MTM so với min(vốn MTM, vốn ở giá xấu nhất của nến), từ start_ts."""
    from backend.core.metrics.returns import curve_frame
    curve = curve_frame(curve_rows)
    if curve.empty:
        return 0.0
    curve = curve[curve["time"] >= start_ts]
    eq = curve["equity"].to_numpy()
    worst = curve["equity_worst"].to_numpy() if "equity_worst" in curve else eq
    peak = np.maximum.accumulate(np.r_[initial_capital, eq])[1:]
    return float(np.max((peak - np.minimum(eq, worst)) / peak) * 100) if len(eq) else 0.0


def portfolio_metrics(res, start_ts):
    """Số đo của `res` (PortfolioEngine.get_results()) từ `start_ts` trở đi (bỏ phần warmup).
    `daily` = lợi suất ngày theo vốn MTM (đóng cửa), nối từ vốn ban đầu; ngày lấy theo UTC."""
    init = res["initial_capital"]
    mdd = curve_mdd_pct(res["equity_curve"], start_ts, init)
    daily = pd.Series(daily_returns_from_curve(res["equity_curve"], start_ts, init), dtype=float)
    sharpe = float(daily.mean() / daily.std() * np.sqrt(365)) if daily.std() > 0 else 0.0
    by_sym = {k.split("@")[0]: round(v["pnl_usd"], 2) for k, v in res["by_symbol"].items()}
    rows = trade_rows(res["positions"])
    times = [c["time"] for c in res["equity_curve"] if c["time"] >= start_ts]
    end_ts = int(times[-1]) if times else int(start_ts)
    rm = return_metrics(daily.to_numpy())
    stats = {"returns": rm, "trades": trade_metrics(rows), "exposure": exposure_metrics(rows, start_ts, end_ts, init),
             "correlation": strategy_correlation(rows, start_ts, end_ts)}
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
        "mdd_intrabar_pct": round(mdd, 2), "mdd_daily_pct": _r(rm["mdd_daily_pct"]), "mdd_basis": "intrabar",
        "cagr_pct": _r(rm["cagr_pct"]),
        "calmar": _r(rm["cagr_pct"] / mdd) if rm["cagr_pct"] is not None and mdd > 1e-9 else None,
        "stats": _round_tree(stats),
    }


def flat_extras(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Các số đo phẳng (để lọc / sắp xếp alpha) rút từ `stats` của portfolio_metrics / series_metrics."""
    r, t = stats.get("returns") or {}, stats.get("trades") or {}
    return {"cagr_pct": _r(r.get("cagr_pct")), "calmar": _r(r.get("calmar")), "cvar95_pct": _r(r.get("cvar95_pct"), 3),
            "max_dd_days": r.get("max_dd_days"), "payoff": _r(t.get("payoff"), 3), "expectancy_pct": _r(t.get("expectancy_pct"), 4),
            "max_consec_losses": t.get("max_consec_losses"), "top5_share_pct": _r(t.get("top5_share_pct"), 1),
            "mae_worst_pct": _r(t.get("mae_worst_pct")), "liq_proximity_max_pct": _r(t.get("liq_proximity_max_pct"), 1),
            "liquidations": t.get("liquidations"), "fee_drag_pct": _r(t.get("fee_drag_pct"), 1)}


def series_metrics(daily, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Số đo phẳng từ chuỗi ngày nối + danh sách lệnh (cho S3/S4/S5): lãi kép, MDD ngày, Sharpe/Sortino quy năm, lệnh, win rate, PF
    + số đo mở rộng (CAGR, Calmar, CVaR, payoff, expectancy, chuỗi thua, MAE...)."""
    d = np.asarray(daily, dtype=float)
    rm = return_metrics(d)
    stats = {"returns": rm, "trades": trade_metrics(trades)}
    return {"ret_pct": round(rm["ret_pct"], 2) if d.size else 0.0, "mdd_pct": round(rm["mdd_daily_pct"], 2),
            "sharpe": round(rm["sharpe"], 2) if rm["sharpe"] is not None else 0.0,
            "sortino": round(rm["sortino"], 2) if rm["sortino"] is not None else 0.0,
            "trades": len(trades), **trade_stats(trades), "oos_days": int(d.size),
            "mdd_daily_pct": round(rm["mdd_daily_pct"], 2), "mdd_basis": "daily", **flat_extras(stats)}
