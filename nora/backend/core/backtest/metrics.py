"""Tính toán các chỉ số hiệu năng (Metrics Calculation)."""
import math
from typing import Dict, List, Optional

from backend.db.models import PositionModel


class MetricsCalculator:
    """Xử lý mảng vị thế (Positions) để xuất ra các chỉ số định lượng."""

    @staticmethod
    def calculate(
        positions: List[PositionModel],
        initial_balance: float = 10000.0,
        equity_curve: Optional[List[Dict[str, float]]] = None,
    ) -> Dict[str, float]:
        start_balance = float(initial_balance or 0.0)
        trades = sorted(
            positions or [],
            key=lambda p: (int(p.close_time or p.enter_time or 0), int(p.result_id or 0)),
        )

        if equity_curve:
            curve = MetricsCalculator._normalize_equity_curve(equity_curve, start_balance)
        else:
            curve = MetricsCalculator._equity_from_positions(trades, start_balance)

        if not curve:
            curve = [{"time": None, "date": "Start", "equity": round(start_balance, 2), "drawdown_pct": 0.0}]

        trade_returns = [MetricsCalculator._trade_return_pct(position) / 100.0 for position in trades]
        winning_trades = sum(1 for position in trades if float(getattr(position, "real_pnl", 0.0) or 0.0) > 0)
        losing_trades = sum(1 for position in trades if float(getattr(position, "real_pnl", 0.0) or 0.0) <= 0)
        gross_profit = sum(max(float(getattr(position, "real_pnl", 0.0) or 0.0), 0.0) for position in trades)
        gross_loss = abs(sum(min(float(getattr(position, "real_pnl", 0.0) or 0.0), 0.0) for position in trades))
        net_pnl_usd = sum(float(getattr(position, "real_pnl", 0.0) or 0.0) for position in trades)

        end_balance = float(curve[-1].get("equity", curve[-1].get("balance", start_balance)))
        total_pnl_pct = ((end_balance - start_balance) / start_balance * 100.0) if start_balance > 0 else 0.0
        max_drawdown_pct = MetricsCalculator._max_drawdown_pct(curve)
        winrate = (winning_trades / len(trades) * 100.0) if trades else 0.0

        sharpe_ratio = MetricsCalculator._sharpe_ratio(curve)
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        return {
            "total_trades": len(trades),
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "winrate": round(winrate, 2),
            "win_rate": round(winrate, 2),
            "total_pnl_pct": round(total_pnl_pct, 4),
            "return_pct": round(total_pnl_pct, 4),
            "max_drawdown": round(max_drawdown_pct, 4),
            "max_drawdown_pct": round(max_drawdown_pct, 4),
            "profit_factor": round(profit_factor, 2),
            "gross_profit": round(gross_profit, 4),
            "gross_loss": round(gross_loss, 4),
            "net_pnl_usd": round(net_pnl_usd, 2),
            "estimated_pnl_usd": round(end_balance - start_balance, 2),
            "start_balance": round(start_balance, 2),
            "end_balance": round(end_balance, 2),
            "sharpe_ratio": round(sharpe_ratio, 4) if sharpe_ratio is not None else 0.0,
            "return_mode": "compounded_equity",
            "equity_curve": curve,
        }

    @staticmethod
    def calculate_all(
        positions: List[PositionModel],
        initial_balance: float = 10000.0,
        equity_curve: Optional[List[Dict[str, float]]] = None,
    ) -> Dict[str, float]:
        return MetricsCalculator.calculate(positions, initial_balance=initial_balance, equity_curve=equity_curve)

    @staticmethod
    def _trade_return_pct(position: PositionModel) -> float:
        pnl_pct = float(getattr(position, "profit_pct", 0.0) or 0.0)
        if pnl_pct != 0.0:
            return pnl_pct
        entry_equity = float(getattr(position, "entry_equity", 0.0) or 0.0)
        if entry_equity > 0:
            return float(getattr(position, "real_pnl", 0.0) or 0.0) / entry_equity * 100.0
        return 0.0

    @staticmethod
    def _equity_from_positions(positions: List[PositionModel], initial_balance: float) -> List[Dict[str, float]]:
        equity = float(initial_balance)
        peak = equity
        curve: List[Dict[str, float]] = [
            {"time": None, "date": "Start", "equity": round(equity, 2), "drawdown_pct": 0.0}
        ]
        for position in positions:
            trade_return = MetricsCalculator._trade_return_pct(position) / 100.0
            equity *= 1.0 + trade_return
            peak = max(peak, equity)
            drawdown_pct = ((peak - equity) / peak * 100.0) if peak > 0 else 0.0
            curve.append({
                "time": int(getattr(position, "close_time", 0) or getattr(position, "enter_time", 0) or 0),
                "date": str(getattr(position, "close_time", None) or getattr(position, "enter_time", None) or ""),
                "equity": round(equity, 2),
                "drawdown_pct": round(drawdown_pct, 4),
            })
        return curve

    @staticmethod
    def _normalize_equity_curve(curve: List[Dict[str, float]], initial_balance: float) -> List[Dict[str, float]]:
        normalized: List[Dict[str, float]] = []
        for row in curve:
            equity = row.get("equity")
            if equity is None:
                equity = row.get("balance")
            if equity is None:
                equity = initial_balance
            normalized.append({
                **row,
                "equity": round(float(equity), 2),
            })
        return normalized

    @staticmethod
    def _max_drawdown_pct(curve: List[Dict[str, float]]) -> float:
        peak = None
        max_dd = 0.0
        for row in curve:
            value = row.get("equity_worst")
            if value is None:
                value = row.get("equity", row.get("balance", 0.0))
            value = float(value or 0.0)
            if peak is None or value > peak:
                peak = value
                continue
            if peak > 0:
                dd = (peak - value) / peak * 100.0
                max_dd = max(max_dd, dd)
        return max_dd

    @staticmethod
    def _sharpe_ratio(curve: List[Dict[str, float]]) -> Optional[float]:
        returns: List[float] = []
        prev = None
        for row in curve:
            value = row.get("equity")
            if value is None:
                value = row.get("balance")
            value = float(value or 0.0)
            if prev is not None and prev > 0:
                returns.append((value - prev) / prev)
            prev = value

        if len(returns) < 2:
            return None

        mean = sum(returns) / len(returns)
        variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
        sd = math.sqrt(variance)
        if sd <= 0:
            return None
        periods_per_year = 365.0
        return (mean / sd) * math.sqrt(periods_per_year)
