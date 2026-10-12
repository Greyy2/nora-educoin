"""Thống kê kết quả = thống kê của NautilusTrader (quyết định chủ dự án): Nora KHÔNG tự cài Sharpe/Sortino/Profit factor/win rate/
expectancy/avg win/avg loss/độ biến động/MDD/CAGR/Calmar — mọi giá trị lấy từ các lớp `nautilus_trader.analysis` (Rust, pyo3).

Đây là file DUY NHẤT trong Nora gọi các lớp thống kê đó (chỉ `backend/nautilus/` được import nautilus_trader).

Nautilus 1.231 (đã kiểm bằng thực nghiệm, test/test_nautilus_stats.py):
  - các thống kê trên LỢI SUẤT (`calculate_from_returns`) nhận dict {timestamp_ns: r}; Sharpe/Sortino/Vol GOM lợi suất theo NGÀY lịch (nên khoá
    phải là thời điểm thật, một ngày một giá trị — chuỗi ngày của Nora thoả điều đó);
  - Sharpe = mean(r) / std(r, ddof=1) × √period; Sortino = mean(r) / √mean(min(r,0)²) × √period; Vol = std(r, ddof=1) × √period;
    CAGR = Π(1+r)^(period/n) − 1; MaxDrawdown = sụt giảm lớn nhất của vốn nối từ r (số ÂM, phân số); Calmar = CAGR / |MDD|;
  - `period` MẶC ĐỊNH của Nautilus là 252 (ngày giao dịch cổ phiếu). Nora giữ năm = 365 ngày (crypto giao dịch cả tuần) bằng cách TRUYỀN
    `period=ANN` vào chính các lớp Nautilus — không đổi công thức;
  - ProfitFactor của Nautilus tính trên LỢI SUẤT: Σ r dương / |Σ r âm| (không phải trên lệnh); không có r âm -> NaN;
  - các thống kê trên PnL đã thực hiện (`calculate_from_realized_pnls`): WinRate = lệnh PnL > 0 / tất cả lệnh (phân số 0-1; hoà làm giảm);
    AvgWinner / AvgLoser = trung bình PnL > 0 / < 0 (AvgLoser ÂM); Expectancy = trung bình PnL khác 0 của các lệnh (BỎ lệnh hoà);
  - NaN = không xác định (<2 ngày, độ lệch 0, không có ngày lỗ...) -> ở đây trả None (không phải 0 giả).
Đầu ra của `compute`: số thô theo đơn vị Nautilus (phân số, không nhân 100) trừ `win_rate` (phần trăm 0-100, theo giao diện).
"""
import math
from typing import Any, Dict, Optional, Sequence

import numpy as np
import pandas as pd
from nautilus_trader.analysis import (
    CAGR, AvgLoser, AvgWinner, CalmarRatio, Expectancy, MaxDrawdown, ProfitFactor, ReturnsVolatility, SharpeRatio, SortinoRatio, WinRate,
)

ANN = 365                                   # số ngày quy năm của Nora (Nautilus mặc định 252)
_EPOCH = pd.Timestamp("2000-01-01")         # mốc cho chuỗi không có chỉ số thời gian (chỉ khoảng cách ngày có ý nghĩa)


def _clean(x) -> Optional[float]:
    """NaN/inf/None -> None, còn lại float."""
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def returns_dict(returns, daily: bool = True) -> Dict[int, float]:
    """Chuỗi lợi suất -> dict {ns: r} cho Nautilus. pd.Series có DatetimeIndex giữ thời điểm; mảng thường -> mỗi phần tử một ngày liên tiếp
    (daily=True, cho Sharpe/Sortino/Vol gom theo ngày) hoặc mỗi phần tử một mili-giây (daily=False, chỉ cho thống kê KHÔNG gom ngày như ProfitFactor)."""
    if isinstance(returns, pd.Series) and isinstance(returns.index, pd.DatetimeIndex):
        return {int(t.value): float(v) for t, v in zip(returns.index, returns.to_numpy(dtype=float))}
    a = np.asarray(returns, dtype=float)
    step = 86_400_000_000_000 if daily else 1_000_000
    base = int(_EPOCH.value)
    return {base + i * step: float(v) for i, v in enumerate(a)}


def _pnls(values) -> list:
    return [float(v) for v in np.asarray(values, dtype=float)]


_RETURN_KEYS = ("sharpe", "sortino", "profit_factor", "returns_volatility", "max_drawdown", "cagr", "calmar")


def returns_stats(returns, period: int = ANN, keys: Optional[Sequence[str]] = None) -> Dict[str, Optional[float]]:
    """Thống kê Nautilus trên lợi suất NGÀY: sharpe, sortino, profit_factor, returns_volatility (quy năm, phân số), max_drawdown (≤ 0),
    cagr (phân số), calmar. < 2 ngày hoặc rỗng -> mọi giá trị None. `keys`: chỉ tính các khoá này (mặc định tất cả)."""
    keys = tuple(keys) if keys is not None else _RETURN_KEYS
    if len(returns) < 2:
        return {k: None for k in keys}
    d = returns_dict(returns)
    calc = {
        "sharpe": lambda: SharpeRatio(period).calculate_from_returns(d),
        "sortino": lambda: SortinoRatio(period).calculate_from_returns(d),
        "profit_factor": lambda: ProfitFactor().calculate_from_returns(returns_dict(returns, daily=False)),
        "returns_volatility": lambda: ReturnsVolatility(period).calculate_from_returns(d),
        "max_drawdown": lambda: MaxDrawdown().calculate_from_returns(d),
        "cagr": lambda: CAGR(period).calculate_from_returns(d),
        "calmar": lambda: CalmarRatio(period).calculate_from_returns(d),
    }
    return {k: _clean(calc[k]()) for k in keys}


def pnl_stats(realized_pnls: Sequence[float], pnl_pcts: Optional[Sequence[float]] = None) -> Dict[str, Optional[float]]:
    """Thống kê Nautilus trên PnL đã thực hiện của các lệnh đã đóng: win_rate (%, 0-100), expectancy, avg_winner, avg_loser (âm).
    `pnl_pcts` (PnL % mỗi lệnh, tuỳ chọn) -> `expectancy_pct` cũng bằng lớp Expectancy của Nautilus. Không có lệnh -> None."""
    p = _pnls(realized_pnls)
    out: Dict[str, Optional[float]] = {"win_rate": None, "expectancy": None, "avg_winner": None, "avg_loser": None, "expectancy_pct": None}
    if p:
        wr = _clean(WinRate().calculate_from_realized_pnls(p))
        out["win_rate"] = None if wr is None else wr * 100.0
        out["expectancy"] = _clean(Expectancy().calculate_from_realized_pnls(p))
        out["avg_winner"] = _clean(AvgWinner().calculate_from_realized_pnls(p))
        out["avg_loser"] = _clean(AvgLoser().calculate_from_realized_pnls(p))
    if pnl_pcts is not None and len(pnl_pcts):
        out["expectancy_pct"] = _clean(Expectancy().calculate_from_realized_pnls(_pnls(pnl_pcts)))
    return out


def trade_profit_factor(realized_pnls: Sequence[float]) -> Optional[float]:
    """Profit factor của Nautilus (lớp ProfitFactor) áp lên chuỗi PnL từng lệnh: Σ lãi / |Σ lỗ|. Không có lệnh lỗ -> None."""
    p = _pnls(realized_pnls)
    return _clean(ProfitFactor().calculate_from_returns(returns_dict(p, daily=False))) if p else None


def compute(returns, realized_pnls: Sequence[float], pnl_pcts: Optional[Sequence[float]] = None, period: int = ANN) -> Dict[str, Optional[float]]:
    """Bộ thống kê Nautilus cho MỘT đoạn (simulate / train / test): `returns` = lợi suất ngày của đường vốn đoạn đó, `realized_pnls` = PnL các lệnh
    đã đóng trong đoạn. Khoá: sharpe, sortino, profit_factor (trên lợi suất ngày), returns_volatility, max_drawdown, cagr, calmar,
    win_rate (%), expectancy, avg_winner, avg_loser, expectancy_pct."""
    return {**returns_stats(returns, period), **pnl_stats(realized_pnls, pnl_pcts)}
