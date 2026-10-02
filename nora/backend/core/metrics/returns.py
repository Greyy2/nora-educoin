"""Lợi suất và độ biến động: chuỗi lợi suất ngày MTM, NAV ngày, Sharpe/Sortino quy năm (365), MDD từ chuỗi ngày, thống kê chuỗi (cho DSR).

Hai cách tính Sortino tồn tại có chủ đích: `sortino` (trả None khi không xác định — trang Danh mục) và `sortino_annual`
(trả 0.0 — số đo phễu lưu SQLite). Cùng công thức độ lệch xuống so với 0.
"""
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

ANN = 365   # số ngày quy năm (crypto giao dịch cả tuần)


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


def sharpe(r: np.ndarray) -> Optional[float]:
    if len(r) < 2:
        return None
    sd = float(np.std(r, ddof=1))
    return float(np.mean(r) / sd * math.sqrt(ANN)) if sd > 1e-12 else None


def sortino(r: np.ndarray) -> Optional[float]:
    if len(r) < 2:
        return None
    dd = float(np.sqrt(np.mean(np.minimum(r, 0.0) ** 2)))   # độ lệch xuống so với 0
    return float(np.mean(r) / dd * math.sqrt(ANN)) if dd > 1e-12 else None


# ─── NAV ngày ───────────────────────────────────────────────────────────────
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


# ── Thống kê chuỗi ngày ─────────────────────────────────────────────────────
def daily_stats(daily: Sequence[float]) -> Dict[str, Any]:
    """Sharpe/độ lệch/kurtosis thô theo NGÀY của chuỗi lợi suất ngày (dùng cho DSR). Chuỗi < 3 ngày hoặc std = 0 -> sr = 0."""
    d = np.asarray(daily, dtype=float)
    n = int(d.size)
    if n < 3:
        return {"sr_daily": 0.0, "skew": 0.0, "kurt": 3.0, "n_days": n}
    sd = float(d.std(ddof=1))
    if not sd > 0:
        return {"sr_daily": 0.0, "skew": 0.0, "kurt": 3.0, "n_days": n}
    mu = float(d.mean())
    z = (d - mu) / float(d.std(ddof=0))
    return {"sr_daily": mu / sd, "skew": float((z ** 3).mean()), "kurt": float((z ** 4).mean()), "n_days": n}


def sortino_annual(daily: Sequence[float]) -> float:
    d = np.asarray(daily, dtype=float)
    if d.size < 2:
        return 0.0
    dd = float(np.sqrt(np.mean(np.minimum(d, 0.0) ** 2)))
    return float(d.mean() / dd * math.sqrt(365)) if dd > 0 else 0.0


# ── Chuỗi ngày / số đo ──────────────────────────────────────────────────────
def equity_mdd_pct(daily) -> float:
    d = np.asarray(daily, dtype=float)
    if d.size == 0:
        return 0.0
    eq = np.cumprod(np.maximum(0.0, 1.0 + d))
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return float(((peak - eq) / peak).max() * 100.0)


def nav_from_returns(rets, start_date: str, initial: float = 10_000.0) -> Tuple[List[str], List[float]]:
    d = np.asarray(rets, dtype=float)
    dates = [f"{x:%Y-%m-%d}" for x in pd.date_range(start_date, periods=len(d), freq="D")]
    return dates, [round(float(v), 2) for v in initial * np.cumprod(1.0 + d)]
