"""Mô phỏng khớp lệnh và quản lý vị thế (Execution & Position Tracker)."""
import time
from typing import Any, Dict, List, Optional

from backend.core.evaluator import LogicEvaluator
from backend.core.params import StrategyParams
from backend.db.models import OrderModel, OrderType, PositionModel, PositionStatus, PositionType


class PositionTracker:
    """Theo dõi vòng đời của một vị thế giao dịch (Entry -> DCA -> TP/SL/Exit)."""

    def __init__(
        self,
        account_id: int,
        campaign_id: int,
        symbol: str,
        flow_name: str,
        params: StrategyParams,
        pos_type: PositionType,
    ):
        self.account_id = account_id
        self.campaign_id = campaign_id
        self.symbol = symbol
        self.flow_name = flow_name
        self.params = params
        self.pos_type = pos_type

        self.position: Optional[PositionModel] = None
        self.orders: List[OrderModel] = []
        self.is_open = False

        self.volume_rate = max(0.0, float(getattr(params, "volume_rate", 1.0) or 0.0))
        self.leverage = max(1.0, float(getattr(params, "leverage", 1.0) or 1.0))
        self.max_capital_usage = max(0.0, float(getattr(params, "max_capital_usage", 1.0) or 0.0))
        self.fee_rate = max(0.0, float(getattr(params, "fee_rate", 0.0005) or 0.0))
        self.slippage_rate = max(0.0, float(getattr(params, "slippage_rate", 0.0002) or 0.0))

        ast_dict = self.params.extra.get("ast", {})
        self.compiled_match = LogicEvaluator.compile_ast(self._combine_conditions(ast_dict.get("match", [])))
        self.compiled_stop = LogicEvaluator.compile_ast(self._combine_conditions(ast_dict.get("stop", [])))

        self.pending_entry = False
        self.pending_exit = False

    @property
    def avg_entry_price(self) -> float:
        if self.position and self.position.enter_price:
            return float(self.position.enter_price)
        return 0.0

    def _check_hard_exits(self, o: float, h: float, l: float):
        if not self.position or self.position.enter_price <= 0:
            return None
        e = self.position.enter_price
        sl_r = self.params.stop_loss_rate
        tp_r = self.params.take_profit_rate
        if self.pos_type == PositionType.LONG:
            sl = e * (1.0 - sl_r / 100.0) if sl_r > 0 else None
            tp = e * (1.0 + tp_r / 100.0) if tp_r > 0 else None
            if sl is not None and l <= sl:
                return (o if o < sl else sl), PositionStatus.SL  # SL ưu tiên nếu cùng nến
            if tp is not None and h >= tp:
                return (o if o > tp else tp), PositionStatus.TP
        else:  # SHORT
            sl = e * (1.0 + sl_r / 100.0) if sl_r > 0 else None
            tp = e * (1.0 - tp_r / 100.0) if tp_r > 0 else None
            if sl is not None and h >= sl:
                return (o if o > sl else sl), PositionStatus.SL
            if tp is not None and l <= tp:
                return (o if o < tp else tp), PositionStatus.TP
        return None

    def update_candle(
        self,
        row_1m: Dict[str, Any],
        row_4h: Dict[str, Any],
        available_equity: float = 10000.0,
        free_cash: float = 10000.0,
        open_positions: int = 0,
        max_open_trades: int = 45,
        can_trade: bool = True,
    ) -> Dict[str, Any]:
        """Cập nhật vị thế theo nến hiện tại và trả về sự kiện vừa phát sinh."""
        event = {
            "opened": False,
            "closed": False,
            "position": None,
            "entry_margin_usd": 0.0,
            "entry_fee_usd": 0.0,
            "real_pnl_usd": 0.0,
            "gross_pnl_usd": 0.0,
            "unrealized_pnl_usd": 0.0,
        }
        if not row_1m:
            return event

        current_time = int(row_1m.get("open_time", 0) or 0)
        o = float(row_1m.get("open", 0.0) or 0.0)
        h = float(row_1m.get("high", 0.0) or 0.0)
        l = float(row_1m.get("low", 0.0) or 0.0)
        c = float(row_1m.get("close", 0.0) or 0.0)

        # 1. Khớp pending entry nếu có từ nến trước ở giá open nến kế tiếp
        if self.pending_entry and not self.is_open:
            self.pending_entry = False
            if open_positions < max_open_trades and o > 0 and available_equity > 0 and free_cash > 0:
                self._open_position(current_time, o, available_equity, free_cash)
                event.update({
                    "opened": True,
                    "position": self.position,
                    "entry_margin_usd": float(self.position.entry_margin_usd if self.position else 0.0),
                    "entry_fee_usd": float(self.position.entry_fee_usd if self.position else 0.0),
                })

        # 2. Khớp pending exit nếu có từ nến trước ở giá open nến kế tiếp
        if self.pending_exit and self.is_open:
            self.pending_exit = False
            status = PositionStatus.TP if self._asset_return_pct(o) > 0 else PositionStatus.SL
            self._close_position(current_time, o, status, "Stop Condition Triggered")
            event.update(self._closed_event_payload())
            return event

        # 3. Kiểm tra hard exits (SL/TP) trong nến hiện tại (kiểm cả nến vừa vào lệnh)
        if self.is_open:
            self.position.max_price = max(self.position.max_price, h)
            self.position.min_price = min(self.position.min_price, l)
            event["unrealized_pnl_usd"] = self.unrealized_pnl_usd(c)

            hit = self._check_hard_exits(o, h, l)
            if hit:
                exit_price, exit_status = hit
                self._close_position(current_time, exit_price, exit_status, f"{exit_status.name} Triggered")
                event.update(self._closed_event_payload())
                return event

        # 4. Đánh giá AST trên nến đã đóng -> chỉ đặt cờ pending cho nến sau
        if can_trade:
            if not self.is_open and not self.pending_entry:
                if self.compiled_match(row_1m, row_4h):
                    self.pending_entry = True
            elif self.is_open and not self.pending_exit:
                if self.compiled_stop(row_1m, row_4h):
                    self.pending_exit = True

        return event

    def unrealized_pnl_usd(self, price: float) -> float:
        if not self.position:
            return 0.0
        qty = float(self.position.qty or 0.0)
        if qty <= 0:
            return 0.0
        if self.pos_type == PositionType.LONG:
            return qty * (price - self.position.enter_price)
        return qty * (self.position.enter_price - price)

    def force_close(self, current_time: int, raw_close_price: float, reason: str = "End of Backtest") -> Dict[str, Any]:
        """Đóng vị thế đang mở ở cuối backtest."""
        if not self.is_open or not self.position:
            return {
                "closed": False,
                "position": None,
                "entry_margin_usd": 0.0,
                "entry_fee_usd": 0.0,
                "real_pnl_usd": 0.0,
                "gross_pnl_usd": 0.0,
            }

        self.pending_entry = False
        self.pending_exit = False
        self._close_position(current_time, raw_close_price, PositionStatus.CANCEL, reason)
        return self._closed_event_payload()

    def _open_position(
        self,
        current_time: int,
        raw_entry_price: float,
        available_equity: float,
        free_cash: float,
    ) -> None:
        self.is_open = True
        allocation = max(0.0, min(self.volume_rate, self.max_capital_usage, 1.0))
        cash_cap = free_cash / (1.0 + self.fee_rate) if self.fee_rate > 0 else free_cash
        entry_margin = max(0.0, min(available_equity * allocation, cash_cap))
        entry_price = self._entry_fill_price(raw_entry_price)
        entry_notional = entry_margin * self.leverage
        entry_fee = entry_notional * self.fee_rate
        qty = entry_notional / entry_price if entry_price > 0 else 0.0
        pos_id = int(time.time() * 1000)

        self.position = PositionModel(
            result_id=pos_id,
            account_id=self.account_id,
            campaign_id=self.campaign_id,
            symbol=self.symbol,
            pos_type=self.pos_type,
            phase=0,
            enter_time=current_time,
            enter_price=entry_price,
            close_time=None,
            close_price=None,
            status=PositionStatus.OPEN,
            real_pnl=0.0,
            profit_pct=0.0,
            flow=self.flow_name,
            start_reason="Match Condition AST",
            close_reason="",
            max_price=entry_price,
            min_price=entry_price,
            qty=qty,
            entry_equity=available_equity,
            entry_margin_usd=entry_margin,
            entry_notional_usd=entry_notional,
            entry_fee_usd=entry_fee,
            exit_fee_usd=0.0,
        )

        order = OrderModel(
            order_id=pos_id + 1,
            account_id=self.account_id,
            position_id=pos_id,
            order_time=current_time,
            order_type=OrderType.BUY if self.pos_type == PositionType.LONG else OrderType.SELL,
            order_price=entry_price,
            qty=qty,
            phase=0,
        )
        self.orders.append(order)

    def _close_position(self, current_time: int, raw_close_price: float, status: PositionStatus, reason: str, *args, **kwargs) -> None:
        self.is_open = False
        if not self.position:
            return

        close_price = self._exit_fill_price(raw_close_price)
        qty = float(self.position.qty or 0.0)
        gross_pnl = qty * (close_price - self.position.enter_price)
        if self.pos_type == PositionType.SHORT:
            gross_pnl = -gross_pnl
        exit_fee = qty * close_price * self.fee_rate
        net_pnl = gross_pnl - float(self.position.entry_fee_usd or 0.0) - exit_fee
        entry_equity = float(self.position.entry_equity or 0.0)
        profit_pct = (net_pnl / entry_equity * 100.0) if entry_equity > 0 else 0.0

        self.position.close_time = current_time
        self.position.close_price = close_price
        self.position.status = status
        self.position.close_reason = reason
        self.position.exit_fee_usd = exit_fee
        self.position.real_pnl = net_pnl
        self.position.profit_pct = profit_pct

        order = OrderModel(
            order_id=int(time.time() * 1000) + 2,
            account_id=self.account_id,
            position_id=self.position.result_id,
            order_time=current_time,
            order_type=OrderType.SELL if self.pos_type == PositionType.LONG else OrderType.BUY,
            order_price=close_price,
            qty=qty,
            phase=0,
        )
        self.orders.append(order)

    def _closed_event_payload(self) -> Dict[str, Any]:
        if not self.position:
            return {
                "closed": False,
                "position": None,
                "entry_margin_usd": 0.0,
                "entry_fee_usd": 0.0,
                "real_pnl_usd": 0.0,
                "gross_pnl_usd": 0.0,
            }
        return {
            "closed": True,
            "position": self.position,
            "entry_margin_usd": float(self.position.entry_margin_usd or 0.0),
            "entry_fee_usd": float(self.position.entry_fee_usd or 0.0),
            "real_pnl_usd": float(self.position.real_pnl or 0.0),
            "gross_pnl_usd": float((self.position.real_pnl or 0.0) + float(self.position.entry_fee_usd or 0.0) + float(self.position.exit_fee_usd or 0.0)),
        }

    def _entry_fill_price(self, raw_price: float) -> float:
        if self.pos_type == PositionType.LONG:
            return raw_price * (1.0 + self.slippage_rate)
        return raw_price * (1.0 - self.slippage_rate)

    def _exit_fill_price(self, raw_price: float) -> float:
        if self.pos_type == PositionType.LONG:
            return raw_price * (1.0 - self.slippage_rate)
        return raw_price * (1.0 + self.slippage_rate)

    def _asset_return_pct(self, raw_price: float) -> float:
        if not self.position or self.position.enter_price <= 0:
            return 0.0
        fill_price = self._exit_fill_price(raw_price)
        if self.pos_type == PositionType.LONG:
            return (fill_price - self.position.enter_price) * 100.0 / self.position.enter_price
        return (self.position.enter_price - fill_price) * 100.0 / self.position.enter_price

    @staticmethod
    def _combine_conditions(blocks: List[Dict[str, Any]]) -> List[Any]:
        combined: List[Any] = []
        if not isinstance(blocks, list):
            return combined
        for block in blocks:
            if not isinstance(block, dict):
                continue
            condition = block.get("condition", [])
            if isinstance(condition, list):
                combined.extend(condition)
        return combined
