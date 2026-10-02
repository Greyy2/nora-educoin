"""Số đo trên chuỗi lợi suất NGÀY (vốn MTM cuối ngày UTC): lợi nhuận, quy năm, biến động, Sharpe/Sortino/Calmar, sụt giảm + thời gian
hồi phục, VaR/CVaR, thống kê chuỗi (cho DSR).

Quy ước (một nguồn duy nhất cho mọi tầng: backtest, sổ, phễu, WFA, trang Danh mục):
  - năm = 365 ngày (crypto giao dịch cả tuần); lãi suất phi rủi ro = 0;
  - Sharpe = mean(r) / std(r, ddof=1) × √365; Sortino = mean(r) / √mean(min(r, 0)²) × √365 (độ lệch xuống so với 0);
    chuỗi < 2 ngày hoặc độ lệch ≈ 0 -> None (không xác định), KHÔNG phải 0;
  - CAGR = (Π(1 + r))^(365 / số ngày) − 1; Calmar = CAGR / MDD theo ngày;
  - MDD theo ngày dùng giá đóng ngày (nhẹ hơn MDD trong nến của engine — xem metrics/portfolio.py);
  - VaR/CVaR 95% = phân vị 5% lịch sử của r ngày (số dương = mức lỗ 1 ngày) và trung bình phần đuôi tệ hơn nó.
"""
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

ANN = 365   # số ngày quy năm (crypto giao dịch cả tuần)


def _arr(r) -> np.ndarray:
    return np.asarray(r, dtype=float)


def daily_returns_from_curve(curve_rows, start_ts, initial_capital):
    """Lợi suất ngày MTM (vốn đóng cửa mỗi ngày UTC) từ đường vốn `curve_rows` (list dict time/equity/...),
    chỉ lấy điểm có time >= start_ts, nối từ vốn ban đầu. Dùng chung cho danh mục, WFA và Monte Carlo ngày."""
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


def nav_from_returns(rets, start_date: str, initial: float = 10_000.0) -> Tuple[List[str], List[float]]:
    d = _arr(rets)
    dates = [f"{x:%Y-%m-%d}" for x in pd.date_range(start_date, periods=len(d), freq="D")]
    return dates, [round(float(v), 2) for v in initial * np.cumprod(1.0 + d)]
