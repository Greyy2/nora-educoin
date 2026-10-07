"""Bộ chỉ số kiểu xnoquant (đo ngược 06/10/2026 trên 3 kết quả mẫu: test/fixtures/xno/*.json) từ chuỗi lợi suất NGÀY.

Đã khớp (sai số < 1e-9 với fixture): volatility, annual_return, cumulative_return, max_drawdown, calmar, sortino, omega = profit_factor =
gain_to_pain, win_rate, win_loss_ratio, kelly, recovery_factor, tail_ratio, cvar, ulcer_index, var (tham số: TB + z·σ). Xấp xỉ: avg_return
(fixture chia cho n-1 vì lợi suất đầu = 0; ở đây là trung bình thường). CHƯA xác định: sharpe (không khớp TB/σ·√252) — dùng
công thức chuẩn TB/σ·√252 và liệt kê trong UNVERIFIED (custom_run ghi vào metrics.notes).
Quy ước: 252 kỳ/năm; chỉ số không xác định (chuỗi quá ngắn / mẫu số 0) = None (JSON null), không NaN.
"""
import math
from typing import Any, Dict, List, Optional

import numpy as np

ANN = 252
Z05 = -1.6448536269514722   # norm.ppf(0.05)


def _div(a: float, b: float) -> Optional[float]:
    return float(a / b) if b and math.isfinite(a) and math.isfinite(b) and abs(b) > 1e-15 else None


def equity_from_returns(r: np.ndarray) -> np.ndarray:
    return np.cumprod(1.0 + r)


def drawdown_series(r: np.ndarray) -> np.ndarray:
    eq = equity_from_returns(r)
    return eq / np.maximum.accumulate(eq) - 1.0


def xno_metrics(returns) -> Dict[str, Any]:
    r = np.asarray(returns, dtype="float64")
    r = r[np.isfinite(r)]
    n = int(r.size)
    keys = ["sharpe", "sortino", "calmar", "omega", "profit_factor", "recovery_factor", "kelly_criterion", "win_rate", "win_loss_ratio",
            "avg_return", "annual_return", "cumulative_return", "max_drawdown", "volatility", "var", "cvar", "tail_ratio",
            "gain_to_pain_ratio", "ulcer_index"]
    if n < 2:
        return {**{k: None for k in keys}, "days": n}
    dd = drawdown_series(r)
    mdd = float(dd.min())
    cum = float(np.prod(1.0 + r) - 1.0)
    annual = float((1.0 + cum) ** (ANN / n) - 1.0) if cum > -1.0 else -1.0
    sd = float(r.std(ddof=1))
    mean = float(r.mean())
    pos, neg = r[r > 0], r[r < 0]
    gp, gl = float(pos.sum()), float(-neg.sum())
    pf = _div(gp, gl)
    nz = int((r != 0).sum())
    win = _div(float((r > 0).sum()), nz)
    wlr = _div(float(pos.mean()), float(-neg.mean())) if pos.size and neg.size else None
    down = float(np.sqrt(np.mean(np.minimum(r, 0.0) ** 2)))
    p5, p95 = float(np.percentile(r, 5)), float(np.percentile(r, 95))
    tail = r[r <= p5]
    return {
        "sharpe": None if sd <= 1e-15 else float(mean / sd * math.sqrt(ANN)),
        "sortino": None if down <= 1e-15 else float(mean / down * math.sqrt(ANN)),
        "calmar": _div(annual, abs(mdd)), "omega": pf, "profit_factor": pf,
        "recovery_factor": _div(cum, abs(mdd)),
        "kelly_criterion": None if win is None or wlr is None else float(win - (1.0 - win) / wlr),
        "win_rate": win, "win_loss_ratio": wlr, "avg_return": mean, "annual_return": annual, "cumulative_return": cum,
        "max_drawdown": mdd, "volatility": float(sd * math.sqrt(ANN)), "var": float(mean + Z05 * sd),
        "cvar": float(tail.mean()) if tail.size else None, "tail_ratio": _div(abs(p95), abs(p5)),
        "gain_to_pain_ratio": pf, "ulcer_index": float(np.sqrt(np.mean(dd ** 2))), "days": n,
    }


UNVERIFIED = ("sharpe",)   # chỉ số xnoquant chưa đo được công thức (xem docstring)


def stage_summary(returns) -> Dict[str, Any]:
    """Bảng giai đoạn / năm của xnoquant: cagr (= annual_return), sharpe, max_drawdown, profit_factor, calmar + số ngày."""
    m = xno_metrics(returns)
    return {"cagr": m["annual_return"], "sharpe": m["sharpe"], "max_drawdown": m["max_drawdown"], "profit_factor": m["profit_factor"],
            "calmar": m["calmar"], "days": m["days"]}
