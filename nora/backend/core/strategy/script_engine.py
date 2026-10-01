"""Engine thực thi Chiến lược bằng Python Script / DSL động cho Alpha Studio.

Tối ưu hóa vector tốc độ cao:
- Khởi tạo và tính toán chỉ báo toàn diện trên DataFrame trong 1ms
- Mô phỏng thanh nến tuần tự theo microsecond
- Tính toán PnL, Drawdown, Sharpe, Sortino, Winrate và trả về báo cáo chuẩn Quant
"""
import math
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ─── Indicators & Feature Calculators ──────────────────────────────────────────
class Indicators:
    """Tập hợp các hàm tính toán chỉ báo kỹ thuật trên chuỗi Pandas Series."""

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(window=period, min_periods=1).mean()

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi.fillna(50.0)

    @staticmethod
    def macd(
        series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        hist = macd_line - signal_line
        return macd_line, signal_line, hist

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period, min_periods=1).mean()

    @staticmethod
    def bollinger_bands(
        series: pd.Series, period: int = 20, num_std: float = 2.0
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        mid = series.rolling(window=period, min_periods=1).mean()
        std = series.rolling(window=period, min_periods=1).std().fillna(0)
        upper = mid + (std * num_std)
        lower = mid - (std * num_std)
        return upper, mid, lower

    @staticmethod
    def keltner_channels(
        high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20, multiplier: float = 1.5
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        mid = close.ewm(span=period, adjust=False).mean()
        atr_val = Indicators.atr(high, low, close, period=period)
        upper = mid + (atr_val * multiplier)
        lower = mid - (atr_val * multiplier)
        return upper, mid, lower


# ─── Order & Position Data Structures ──────────────────────────────────────────
@dataclass
class TradeRecord:
    trade_id: int
    pos_type: str  # 'LONG' or 'SHORT'
    entry_time: int
    entry_price: float
    close_time: int
    close_price: float
    qty: float
    margin: float
    pnl_usd: float
    pnl_pct: float
    reason: str
    dca_orders: int = 1


@dataclass
class ActivePosition:
    pos_type: str
    entry_time: int
    entry_price: float
    qty: float
    margin: float
    total_cost: float
    dca_count: int = 1
    max_price: float = 0.0
    min_price: float = 0.0


# ─── Base Strategy Class for User Scripts ──────────────────────────────────────
class Strategy:
    """Class cơ sở cho các kịch bản chiến lược Python."""

    def __init__(self):
        self.context: Dict[str, Any] = {}
        self.active_position: Optional[ActivePosition] = None
        self.trade_history: List[TradeRecord] = []
        self.current_capital: float = 10000.0
        self.initial_capital: float = 10000.0
        self.leverage: float = 1.0
        self.maker_fee: float = 0.0005
        self.taker_fee: float = 0.0005
        self.slippage: float = 0.0002
        self.trade_seq: int = 0
        self._curr_candle: Optional[Dict[str, Any]] = None
        self._curr_index: int = 0

    def initialize(self, df: pd.DataFrame) -> None:
        """Được gọi một lần khi nạp dữ liệu. Dùng để pre-calculate chỉ báo siêu tốc."""
        pass

    def on_candle(self, i: int, candle: Dict[str, Any]) -> None:
        """Hàm chính được gọi trên mỗi cây nến mới."""
        pass

    # Helper Methods cho người viết chiến lược
    def has_position(self) -> bool:
        return self.active_position is not None

    def position_type(self) -> Optional[str]:
        return self.active_position.pos_type if self.active_position else None

    def open_long(self, capital_pct: float = 100.0, margin: float = 1.0) -> bool:
        if self.has_position() or not self._curr_candle:
            return False
        price = float(self._curr_candle["close"]) * (1.0 + self.slippage)
        invest_usd = self.current_capital * (capital_pct / 100.0)
        effective_margin = max(1.0, margin or self.leverage)
        notional_usd = invest_usd * effective_margin
        fee = notional_usd * self.taker_fee
        if self.current_capital < invest_usd + fee:
            invest_usd = max(0.0, (self.current_capital) / (1.0 + effective_margin * self.taker_fee))
            notional_usd = invest_usd * effective_margin
            fee = notional_usd * self.taker_fee
        if invest_usd <= 0:
            return False
        qty = notional_usd / price
        self.current_capital -= fee
        self.active_position = ActivePosition(
            pos_type="LONG",
            entry_time=int(self._curr_candle["open_time"]),
            entry_price=price,
            qty=qty,
            margin=effective_margin,
            total_cost=invest_usd,
            dca_count=1,
            max_price=price,
            min_price=price,
        )
        return True

    def open_short(self, capital_pct: float = 100.0, margin: float = 1.0) -> bool:
        if self.has_position() or not self._curr_candle:
            return False
        price = float(self._curr_candle["close"]) * (1.0 - self.slippage)
        invest_usd = self.current_capital * (capital_pct / 100.0)
        effective_margin = max(1.0, margin or self.leverage)
        notional_usd = invest_usd * effective_margin
        fee = notional_usd * self.taker_fee
        if self.current_capital < invest_usd + fee:
            invest_usd = max(0.0, (self.current_capital) / (1.0 + effective_margin * self.taker_fee))
            notional_usd = invest_usd * effective_margin
            fee = notional_usd * self.taker_fee
        if invest_usd <= 0:
            return False
        qty = notional_usd / price
        self.current_capital -= fee
        self.active_position = ActivePosition(
            pos_type="SHORT",
            entry_time=int(self._curr_candle["open_time"]),
            entry_price=price,
            qty=qty,
            margin=effective_margin,
            total_cost=invest_usd,
            dca_count=1,
            max_price=price,
            min_price=price,
        )
        return True

    def dca(self, add_capital_pct: float = 50.0) -> bool:
        """Nhồi thêm vị thế trung bình giá (DCA)."""
        if not self.has_position() or not self._curr_candle:
            return False
        pos = self.active_position
        price = float(self._curr_candle["close"])
        if pos.pos_type == "LONG":
            price *= 1.0 + self.slippage
        else:
            price *= 1.0 - self.slippage

        add_usd = self.current_capital * (add_capital_pct / 100.0)
        fee = add_usd * self.taker_fee
        if self.current_capital < add_usd + fee:
            add_usd = max(0.0, self.current_capital - fee)
        if add_usd <= 0:
            return False

        add_qty = (add_usd * pos.margin) / price
        self.current_capital -= fee

        total_qty = pos.qty + add_qty
        pos.entry_price = (pos.entry_price * pos.qty + price * add_qty) / total_qty
        pos.qty = total_qty
        pos.total_cost += add_usd
        pos.dca_count += 1
        return True

    def close_position(self, reason: str = "Signal Close") -> bool:
        if not self.has_position() or not self._curr_candle:
            return False
        pos = self.active_position
        curr_price = float(self._curr_candle["close"])
        if pos.pos_type == "LONG":
            exit_price = curr_price * (1.0 - self.slippage)
            pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100.0 * pos.margin
            pnl_usd = (exit_price - pos.entry_price) * pos.qty
        else:
            exit_price = curr_price * (1.0 + self.slippage)
            pnl_pct = (pos.entry_price - exit_price) / pos.entry_price * 100.0 * pos.margin
            pnl_usd = (pos.entry_price - exit_price) * pos.qty

        exit_fee = (pos.qty * exit_price) * self.taker_fee
        net_pnl_usd = pnl_usd - exit_fee
        self.current_capital += net_pnl_usd

        self.trade_seq += 1
        record = TradeRecord(
            trade_id=self.trade_seq,
            pos_type=pos.pos_type,
            entry_time=pos.entry_time,
            entry_price=round(pos.entry_price, 6),
            close_time=int(self._curr_candle["open_time"]),
            close_price=round(exit_price, 6),
            qty=round(pos.qty, 6),
            margin=pos.margin,
            pnl_usd=round(net_pnl_usd, 2),
            pnl_pct=round(pnl_pct, 2),
            reason=reason,
            dca_orders=pos.dca_count,
        )
        self.trade_history.append(record)
        self.active_position = None
        return True


# ─── Script Strategy Runner & Simulation ──────────────────────────────────────
class ScriptStrategyRunner:
    """Thực thi script chiến lược do người dùng viết và trả về báo cáo kết quả."""

    @staticmethod
    def compile_and_run(
        code: str,
        df: pd.DataFrame,
        initial_capital: float = 10000.0,
        leverage: float = 1.0,
        fee_rate: float = 0.0005,
        slippage: float = 0.0002,
        stop_loss_pct: float = 0.0,
        take_profit_pct: float = 0.0,
    ) -> Dict[str, Any]:
        if df.empty or len(df) < 5:
            raise ValueError("Dữ liệu nến không đủ để chạy mô phỏng (cần tối thiểu 5 nến).")

        global_scope = {
            "Strategy": Strategy,
            "Indicators": Indicators,
            "np": np,
            "pd": pd,
            "math": math,
        }
        local_scope: Dict[str, Any] = {}

        try:
            exec(code, global_scope, local_scope)
        except Exception as e:
            tb = traceback.format_exc()
            raise RuntimeError(f"Lỗi cú pháp trong Strategy Code:\n{tb}")

        # Tìm class kế thừa từ Strategy
        strat_class = None
        for obj in local_scope.values():
            if isinstance(obj, type) and issubclass(obj, Strategy) and obj is not Strategy:
                strat_class = obj
                break

        if strat_class is None:
            raise ValueError("Không tìm thấy class chiến lược kế thừa từ `Strategy` trong đoạn code.")

        # Khởi tạo chiến lược
        strategy_instance: Strategy = strat_class()
        strategy_instance.initial_capital = initial_capital
        strategy_instance.current_capital = initial_capital
        strategy_instance.leverage = leverage
        strategy_instance.maker_fee = fee_rate
        strategy_instance.taker_fee = fee_rate
        strategy_instance.slippage = slippage

        # CẢNH BÁO CAUSAL: initialize(df) nhận toàn bộ DataFrame để tính toán indicators vector siêu tốc.
        # Script tự viết TUYỆT ĐỐI KHÔNG ĐƯỢC sử dụng shift âm (df.shift(-1)) hoặc truy cập dữ liệu tương lai!
        try:
            strategy_instance.initialize(df)
        except Exception as e:
            raise RuntimeError(f"Lỗi trong hàm initialize(df): {e}")

        # Kiểm tra signature của on_candle: on_candle(self, i, candle) hoặc on_candle(self, candle, history)
        import inspect
        sig = inspect.signature(strategy_instance.on_candle)
        param_count = len(sig.parameters)

        equity_curve: List[Dict[str, Any]] = []
        candles_list = df.to_dict("records")
        peak_capital = initial_capital
        max_drawdown_pct = 0.0
        daily_returns: List[float] = []
        prev_day_capital = initial_capital
        current_day_bucket: Optional[int] = None

        # Vòng lặp mô phỏng siêu tốc
        for i, candle in enumerate(candles_list):
            strategy_instance._curr_candle = candle
            strategy_instance._curr_index = i
            curr_close = float(candle["close"])
            open_time = int(candle["open_time"])

            # Cập nhật vị thế đang mở và kiểm tra SL/TP cứng
            pos = strategy_instance.active_position
            if pos:
                pos.max_price = max(pos.max_price, float(candle["high"]))
                pos.min_price = min(pos.min_price, float(candle["low"]))
                if pos.pos_type == "LONG":
                    curr_pnl_pct = (curr_close - pos.entry_price) / pos.entry_price * 100.0 * pos.margin
                else:
                    curr_pnl_pct = (pos.entry_price - curr_close) / pos.entry_price * 100.0 * pos.margin

                # Hard Stop Loss
                if stop_loss_pct > 0 and curr_pnl_pct <= -stop_loss_pct:
                    strategy_instance.close_position(f"StopLoss (-{stop_loss_pct:.1f}%)")
                # Hard Take Profit
                elif take_profit_pct > 0 and curr_pnl_pct >= take_profit_pct:
                    strategy_instance.close_position(f"TakeProfit (+{take_profit_pct:.1f}%)")

            # Gọi hook on_candle
            try:
                if param_count == 2:
                    strategy_instance.on_candle(i, candle)
                else:
                    # Rolling window nhỏ 100 bar để không lag nếu dùng param kiểu cũ
                    history_slice = df.iloc[max(0, i - 100) : i + 1]
                    strategy_instance.on_candle(candle, history_slice)
            except Exception as e:
                raise RuntimeError(f"Lỗi khi chạy on_candle tại nến {i} (time={open_time}): {e}")

            # Tính toán vốn tạm tính (Equity)
            unrealized_pnl = 0.0
            if strategy_instance.active_position:
                pos = strategy_instance.active_position
                if pos.pos_type == "LONG":
                    unrealized_pnl = (curr_close - pos.entry_price) * pos.qty
                else:
                    unrealized_pnl = (pos.entry_price - curr_close) * pos.qty

            equity = strategy_instance.current_capital + unrealized_pnl
            peak_capital = max(peak_capital, equity)
            drawdown_pct = (peak_capital - equity) / peak_capital * 100.0 if peak_capital > 0 else 0.0
            max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

            # Lấy mẫu equity curve (mỗi 10 nến hoặc nến cuối)
            if i % 10 == 0 or i == len(candles_list) - 1:
                equity_curve.append({
                    "time": open_time,
                    "equity": round(equity, 2),
                    "drawdown": round(drawdown_pct, 2),
                    "price": curr_close,
                })

            # 2.5: Sharpe theo ngày thật. Nhóm equity theo open_time // 86_400_000, không dùng i % 1440
            day_bucket = open_time // 86_400_000
            if current_day_bucket is None:
                current_day_bucket = day_bucket
            elif day_bucket != current_day_bucket:
                ret = (equity - prev_day_capital) / prev_day_capital if prev_day_capital > 0 else 0.0
                daily_returns.append(ret)
                prev_day_capital = equity
                current_day_bucket = day_bucket

        # Đóng vị thế còn mở ở cây nến cuối
        if strategy_instance.has_position():
            strategy_instance.close_position("End of Simulation")

        # ─── Thống kê chỉ số định lượng (Metrics) ──────────────────────────────
        trades = strategy_instance.trade_history
        total_trades = len(trades)
        winning_trades = [t for t in trades if t.pnl_usd > 0]
        losing_trades = [t for t in trades if t.pnl_usd <= 0]
        win_rate = (len(winning_trades) / total_trades * 100.0) if total_trades > 0 else 0.0

        gross_profit = sum(t.pnl_usd for t in winning_trades)
        gross_loss = abs(sum(t.pnl_usd for t in losing_trades))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        final_capital = strategy_instance.current_capital
        net_profit = final_capital - initial_capital
        return_pct = (net_profit / initial_capital) * 100.0

        # Sharpe & Sortino Ratio
        if len(daily_returns) > 1 and np.std(daily_returns) > 0:
            sharpe_ratio = float((np.mean(daily_returns) / np.std(daily_returns)) * math.sqrt(365))
            downside_returns = [r for r in daily_returns if r < 0]
            downside_std = np.std(downside_returns) if downside_returns else 0.0001
            sortino_ratio = float((np.mean(daily_returns) / downside_std) * math.sqrt(365))
        else:
            sharpe_ratio = 0.0
            sortino_ratio = 0.0

        trades_data = [
            {
                "trade_id": t.trade_id,
                "pos_type": t.pos_type,
                "entry_time": t.entry_time,
                "entry_date": datetime.fromtimestamp(t.entry_time / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "entry_price": t.entry_price,
                "close_time": t.close_time,
                "close_date": datetime.fromtimestamp(t.close_time / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "close_price": t.close_price,
                "qty": t.qty,
                "margin": t.margin,
                "pnl_usd": t.pnl_usd,
                "pnl_pct": t.pnl_pct,
                "reason": t.reason,
                "dca_orders": t.dca_orders,
            }
            for t in reversed(trades)
        ]

        return {
            "success": True,
            "metrics": {
                "initial_capital": round(initial_capital, 2),
                "final_capital": round(final_capital, 2),
                "net_profit": round(net_profit, 2),
                "return_pct": round(return_pct, 2),
                "max_drawdown_pct": round(max_drawdown_pct, 2),
                "sharpe_ratio": round(sharpe_ratio, 2),
                "sortino_ratio": round(sortino_ratio, 2),
                "profit_factor": round(profit_factor, 2),
                "total_trades": total_trades,
                "winning_trades": len(winning_trades),
                "losing_trades": len(losing_trades),
                "win_rate": round(win_rate, 1),
                "total_candles": len(df),
            },
            "equity_curve": equity_curve,
            "trades": trades_data,
        }
