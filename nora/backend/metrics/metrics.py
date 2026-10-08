"""Bộ chỉ số Nora (P9.5): số đo trên chuỗi lợi suất NGÀY (returns) + bộ số đo chuẩn của MỘT lần chạy (portfolio), một công thức chuẩn, năm = 365 ngày.

Hợp nhất NGUYÊN VĂN từ core/metrics/returns.py + core/metrics/portfolio.py (xem docs/bmad/p9_review_log.md, mục P9.5). Đường dẫn cũ là shim.
Thứ tự trong file: returns, portfolio. Chỉ import `metrics/trades.py` (cùng tầng) — không import ngoài core.
"""
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from backend.metrics.trades import exposure_metrics, strategy_correlation, trade_metrics, trade_rows, trade_stats


# ══════════════════════════════════════════════════════════════════════════
# P9.5 — nguyên văn từ core/metrics/returns.py
#
# Số đo trên chuỗi lợi suất NGÀY (vốn MTM cuối ngày UTC): lợi nhuận, quy năm, biến động, Sharpe/Sortino/Calmar, sụt giảm + thời gian
# hồi phục, VaR/CVaR, thống kê chuỗi (cho DSR).
#
# Quy ước (một nguồn duy nhất cho mọi tầng: backtest, sổ, phễu, WFA, trang Danh mục):
#   - năm = 365 ngày (crypto giao dịch cả tuần); lãi suất phi rủi ro = 0;
#   - Sharpe = mean(r) / std(r, ddof=1) × √365; Sortino = mean(r) / √mean(min(r, 0)²) × √365 (độ lệch xuống so với 0);
#     chuỗi < 2 ngày hoặc độ lệch ≈ 0 -> None (không xác định), KHÔNG phải 0;
#   - CAGR = (Π(1 + r))^(365 / số ngày) − 1; Calmar = CAGR / MDD theo ngày;
#   - MDD theo ngày dùng giá đóng ngày (nhẹ hơn MDD trong nến của engine — xem metrics/portfolio.py);
#   - VaR/CVaR 95% = phân vị 5% lịch sử của r ngày (số dương = mức lỗ 1 ngày) và trung bình phần đuôi tệ hơn nó.
# ══════════════════════════════════════════════════════════════════════════

ANN = 365   # số ngày quy năm (crypto giao dịch cả tuần)


def _arr(r) -> np.ndarray:
    return np.asarray(r, dtype=float)


def curve_frame(curve_rows) -> pd.DataFrame:
    """DataFrame của đường vốn (list dict time/equity/equity_worst) dựng theo CỘT — cùng giá trị/dtype với pd.DataFrame(curve_rows)
    nhưng nhanh hơn nhiều (đường vốn theo giờ có hàng chục nghìn điểm, tính lại cho mọi alpha)."""
    if not curve_rows:
        return pd.DataFrame()
    try:
        return pd.DataFrame({k: [r[k] for r in curve_rows] for k in curve_rows[0]})
    except KeyError:                                  # dòng thiếu khoá -> để pandas tự điền NaN
        return pd.DataFrame(curve_rows)


def daily_returns_from_curve(curve_rows, start_ts, initial_capital):
    """Lợi suất ngày MTM (vốn đóng cửa mỗi ngày UTC) từ đường vốn `curve_rows` (list dict time/equity/...),
    chỉ lấy điểm có time >= start_ts, nối từ vốn ban đầu. Dùng chung cho danh mục, WFA và Monte Carlo ngày."""
    curve = curve_frame(curve_rows)
    if curve.empty:
        return []
    curve = curve[curve["time"] >= start_ts]
    if curve.empty:
        return []
    s = pd.Series(curve["equity"].to_numpy(), index=pd.to_datetime(curve["time"], unit="ms"))
    daily = s.resample("1D").last().ffill()
    daily = pd.concat([pd.Series([initial_capital], index=[daily.index[0] - pd.Timedelta(days=1)]), daily]).pct_change().dropna()
    return [float(x) for x in daily.to_numpy()]


# ─── Rủi ro điều chỉnh lợi nhuận ────────────────────────────────────────────
def sharpe(r) -> Optional[float]:
    r = _arr(r)
    if len(r) < 2:
        return None
    sd = float(np.std(r, ddof=1))
    return float(np.mean(r) / sd * math.sqrt(ANN)) if sd > 1e-12 else None


def sortino(r) -> Optional[float]:
    r = _arr(r)
    if len(r) < 2:
        return None
    dd = float(np.sqrt(np.mean(np.minimum(r, 0.0) ** 2)))   # độ lệch xuống so với 0
    return float(np.mean(r) / dd * math.sqrt(ANN)) if dd > 1e-12 else None


def total_return_pct(r) -> float:
    r = _arr(r)
    return float((np.prod(1.0 + r) - 1.0) * 100.0) if r.size else 0.0


def cagr_pct(r) -> Optional[float]:
    """Lợi nhuận quy năm. Vốn về 0 hoặc âm -> -100; chuỗi rỗng -> None."""
    r = _arr(r)
    if r.size == 0:
        return None
    growth = float(np.prod(1.0 + r))
    if growth <= 0:
        return -100.0
    return float((growth ** (ANN / r.size) - 1.0) * 100.0)


def vol_ann_pct(r) -> Optional[float]:
    r = _arr(r)
    return float(np.std(r, ddof=1) * math.sqrt(ANN) * 100.0) if r.size >= 2 else None


def var_cvar_pct(r, q: float = 5.0) -> Tuple[Optional[float], Optional[float]]:
    """(VaR, CVaR) lịch sử ở mức (100 − q)%: phần trăm lỗ 1 ngày (số dương; 0 nếu phân vị không âm)."""
    r = _arr(r)
    if r.size < 2:
        return None, None
    cut = float(np.percentile(r, q))
    tail = r[r <= cut]
    return max(0.0, -cut * 100.0), (max(0.0, -float(tail.mean()) * 100.0) if tail.size else None)


# ─── Sụt giảm ───────────────────────────────────────────────────────────────
def equity_mdd_pct(daily) -> float:
    """MDD (%) của vốn nối từ chuỗi r ngày (giá đóng ngày); vốn không xuống dưới 0."""
    d = _arr(daily)
    if d.size == 0:
        return 0.0
    eq = np.cumprod(np.maximum(0.0, 1.0 + d))
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return float(((peak - eq) / peak).max() * 100.0)


def equity_series_summary(values: Sequence[float]) -> Dict[str, Any]:
    """Số đo của một đường vốn theo NẾN (bot live): {bars, start, last, mdd_pct, mdd_note}. MDD = sụt giảm lớn nhất từ đỉnh vốn (đóng nến);
    < 2 điểm hoặc đỉnh <= 0 -> mdd_pct None + lý do (không phải 0 giả)."""
    v = np.asarray([x for x in values if x is not None and math.isfinite(x)], dtype=float)
    out: Dict[str, Any] = {"bars": int(v.size), "start": float(v[0]) if v.size else None, "last": float(v[-1]) if v.size else None,
                           "mdd_pct": None, "mdd_note": None}
    if v.size < 2:
        out["mdd_note"] = "cần ít nhất hai nến để đo MDD"
        return out
    peak = np.maximum.accumulate(v)
    if not peak.max() > 0:
        out["mdd_note"] = "vốn không dương, không tính được MDD"
        return out
    ok = peak > 0
    out["mdd_pct"] = float(((peak[ok] - v[ok]) / peak[ok]).max() * 100.0)
    return out


def pnl_since_start(start: Optional[float], last: Optional[float]) -> Dict[str, Any]:
    """Lãi/lỗ từ đầu: USD và % so với vốn đầu đường vốn. Thiếu đầu/cuối hoặc vốn đầu <= 0 -> None + lý do."""
    if start is None or last is None:
        return {"pnl_usd": None, "pnl_pct": None, "pnl_note": "chưa có điểm vốn nào từ bot"}
    if not start > 0:
        return {"pnl_usd": float(last - start), "pnl_pct": None, "pnl_note": "vốn đầu kỳ <= 0, không tính được %"}
    return {"pnl_usd": float(last - start), "pnl_pct": float((last / start - 1.0) * 100.0), "pnl_note": None}


def drawdown_stats(daily) -> Dict[str, Any]:
    """MDD theo ngày + thời gian: `max_dd_days` = đợt nằm dưới đỉnh dài nhất (ngày), `recovery_days` = số ngày từ đáy của đợt MDD
    tới khi lấy lại đỉnh (None nếu chưa hồi phục), `ulcer_index` = √mean(dd%²) (độ sâu × độ dài sụt giảm)."""
    d = _arr(daily)
    if d.size == 0:
        return {"mdd_daily_pct": 0.0, "max_dd_days": 0, "recovery_days": 0, "ulcer_index": 0.0}
    eq = np.cumprod(np.maximum(0.0, 1.0 + d))
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    dd = (peak - eq) / peak                                  # >= 0
    trough = int(np.argmax(dd))
    longest = cur = 0
    for under in dd > 1e-12:
        cur = cur + 1 if under else 0
        longest = max(longest, cur)
    rec = None
    if dd[trough] <= 1e-12:
        rec = 0
    else:
        after = np.nonzero(eq[trough:] >= peak[trough] - 1e-12)[0]
        rec = int(after[0]) if after.size else None
    return {"mdd_daily_pct": float(dd[trough] * 100.0), "max_dd_days": int(longest), "recovery_days": rec,
            "ulcer_index": float(np.sqrt(np.mean((dd * 100.0) ** 2)))}


# ─── Bộ số đo chuỗi ngày ────────────────────────────────────────────────────
def daily_stats(daily: Sequence[float]) -> Dict[str, Any]:
    """Sharpe/độ lệch/kurtosis thô theo NGÀY của chuỗi lợi suất ngày (dùng cho DSR). Chuỗi < 3 ngày hoặc std = 0 -> sr = 0."""
    d = _arr(daily)
    n = int(d.size)
    if n < 3:
        return {"sr_daily": 0.0, "skew": 0.0, "kurt": 3.0, "n_days": n}
    sd = float(d.std(ddof=1))
    if not sd > 0:
        return {"sr_daily": 0.0, "skew": 0.0, "kurt": 3.0, "n_days": n}
    mu = float(d.mean())
    z = (d - mu) / float(d.std(ddof=0))
    return {"sr_daily": mu / sd, "skew": float((z ** 3).mean()), "kurt": float((z ** 4).mean()), "n_days": n}


def return_metrics(daily) -> Dict[str, Any]:
    """Mọi số đo của chuỗi r ngày (chưa làm tròn trừ khi ghi chú): lợi nhuận, CAGR, biến động, Sharpe, Sortino, Calmar, VaR/CVaR,
    sụt giảm + thời gian, độ lệch/độ nhọn, tỉ lệ ngày lãi, ngày tốt/xấu nhất."""
    d = _arr(daily)
    ddm = drawdown_stats(d)
    cg = cagr_pct(d)
    var, cvar = var_cvar_pct(d)
    st = daily_stats(d)
    active = d[np.abs(d) > 1e-12]
    return {
        "ret_pct": total_return_pct(d), "cagr_pct": cg, "vol_ann_pct": vol_ann_pct(d),
        "sharpe": sharpe(d), "sortino": sortino(d),
        "calmar": (cg / ddm["mdd_daily_pct"]) if cg is not None and ddm["mdd_daily_pct"] > 1e-9 else None,
        **ddm, "var95_pct": var, "cvar95_pct": cvar, "skew": st["skew"], "kurt": st["kurt"],
        "days": int(d.size), "win_days_pct": float((active > 0).mean() * 100.0) if active.size else None,
        "best_day_pct": float(d.max() * 100.0) if d.size else None, "worst_day_pct": float(d.min() * 100.0) if d.size else None,
    }


# ─── NAV ────────────────────────────────────────────────────────────────────
def daily_nav_series(result: Dict[str, Any]) -> pd.Series:
    """NAV cuối mỗi ngày UTC (liên tục theo ngày, ngày thiếu lấy giá trị trước đó). Index = ngày (00:00, không múi giờ)."""
    rows = result.get("daily_nav")
    if rows:
        s = pd.Series([float(r["equity"]) for r in rows], index=pd.to_datetime([r["date"] for r in rows]))
    else:
        curve = result.get("equity_curve") or []
        if not curve:
            return pd.Series(dtype=float)
        end = (result.get("config") or {}).get("end")     # mẫu đúng mốc end (loại trừ) thuộc ngày cuối thật
        t = pd.to_datetime([min(c["time"], end - 1) if end else c["time"] for c in curve], unit="ms")
        s = pd.Series([float(c["equity"]) for c in curve], index=t)
        s = s.groupby(s.index.normalize()).last()
    s = s.sort_index()
    return s.reindex(pd.date_range(s.index[0], s.index[-1], freq="D")).ffill()



def fold_stats(fold_rets_pct: Sequence[float], traded: Sequence[bool]) -> Dict[str, Any]:
    """Thống kê lãi OOS theo fold cho cổng WFA (phễu S3 + WFA danh mục). Không dùng "tỉ lệ fold lãi" làm cổng vì lãi của chiến lược theo xu
    hướng lệch phải (đa số tháng lỗ nhẹ, vài tháng lãi lớn): đo trên 360 alpha, 124/145 alpha có lãi OOS bị loại chỉ vì < 60% fold lãi
    (test/scripts/research_funnel_diagnosis.py). Fold KHÔNG có lệnh là trung tính: không vào tỉ lệ / t-stat.
    -> traded_folds, positive_ratio (trên fold có lệnh), fold_t (t-stat lãi TB/fold trên fold có lệnh; < 2 fold hoặc độ lệch 0 -> 0),
       oos_ex_best_pct (lãi kép OOS sau khi bỏ fold tốt nhất — lãi không được dựa vào một fold may mắn)."""
    x = np.asarray([float(r) for r, t in zip(fold_rets_pct, traded) if t], dtype=float)
    allx = np.asarray([float(r) for r in fold_rets_pct], dtype=float)
    n = len(x)
    sd = float(x.std(ddof=1)) if n > 1 else 0.0
    t = float(x.mean() / (sd / math.sqrt(n))) if n > 1 and sd > 0 else 0.0
    ex = np.delete(allx, int(allx.argmax())) if len(allx) else allx
    return {"traded_folds": n, "positive_ratio": float((x > 0).mean()) if n else 0.0, "fold_t": round(t, 4),
            "oos_ex_best_pct": round(float((np.prod(1.0 + ex / 100.0) - 1.0) * 100.0), 4) if len(allx) else 0.0}


# ══════════════════════════════════════════════════════════════════════════
# P9.5 — nguyên văn từ core/metrics/portfolio.py
#
# Bộ số đo chuẩn của MỘT lần chạy — mọi tầng (backtest, dựng sổ, WFA, phễu, trang Danh mục) dùng chung.
#
# portfolio_metrics(res, start_ts)  từ PortfolioEngine.get_results() (bỏ phần warmup trước start_ts):
#     khoá phẳng (định dạng cũ, gate/bảng đọc): ret_pct, mdd_pct (= MDD TRONG NẾN, khắt nhất), sharpe, trades, win_pct, symbols_positive,
#     by_symbol, by_strategy, fees_usd, funding_usd, rejected_*, halted_at, daily
#     + mdd_intrabar_pct, mdd_daily_pct, mdd_basis="intrabar", cagr_pct, calmar
#     + stats = {returns: metrics/returns.return_metrics, trades: metrics/trades.trade_metrics, exposure, correlation}
# series_metrics(daily, trades)     từ chuỗi ngày nối + lệnh (OOS của WFA/phễu): mdd_pct = MDD THEO NGÀY (mdd_basis="daily").
#
# Hai kiểu MDD: trong nến = đỉnh vốn MTM so với vốn ở giá XẤU NHẤT của nến (engine ghi equity_worst mỗi mẫu) — chỉ có khi có đường vốn engine;
# theo ngày = trên vốn đóng ngày. Trong nến >= theo ngày. Gate dùng `mdd_pct` của nguồn tương ứng; UI hiện cả hai.
# ══════════════════════════════════════════════════════════════════════════

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
    by_sym = {k.split("@")[0].split(":")[-1]: round(v["pnl_usd"], 2) for k, v in res["by_symbol"].items()}
    rows = trade_rows(res["positions"])
    times = [c["time"] for c in res["equity_curve"] if c["time"] >= start_ts]
    end_ts = int(times[-1]) if times else int(start_ts)
    rm = return_metrics(daily.to_numpy())
    stats = {"returns": rm, "trades": trade_metrics(rows), "exposure": exposure_metrics(rows, start_ts, end_ts, init),
             "correlation": strategy_correlation(rows, start_ts, end_ts)}
    return {
        "ret_pct": round((res["final_equity"] / init - 1) * 100, 2), "mdd_pct": round(mdd, 2), "sharpe": round(sharpe, 2),
        "trades": len(res["positions"]), "win_pct": round(float(np.mean([p.real_pnl > 0 for p in res["positions"]]) * 100), 1)
        if res["positions"] else None,   # 0 lệnh -> None (không phải 0% giả)
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
