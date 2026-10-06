"""Mô hình vị thế / lệnh của engine (dataclass + enum loại vị thế, loại lệnh, trạng thái)."""
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Optional


class PositionType(IntEnum):
    """Loại vị thế."""
    LONG = 1
    SHORT = 2


class OrderType(IntEnum):
    """Hành động lệnh."""
    BUY = 1
    SELL = 2


class PositionStatus(IntEnum):
    """Trạng thái vị thế."""
    INIT = 0
    OPEN = 1
    TP = 2      # Chốt lãi (Take Profit)
    SL = 3      # Cắt lỗ (Stop Loss / Stop Trend)
    CANCEL = 4  # Huỷ lệnh
    LIQ = 5     # Bị thanh lý (perp, đòn bẩy)
    WAIT = 6    # Đang chờ / Đang mở


@dataclass
class PositionModel:
    """Mô hình vị thế giao dịch (lab_results)."""
    result_id: int = 0
    account_id: int = 0
    campaign_id: int = 0
    symbol: str = ""
    pos_type: PositionType = PositionType.LONG
    phase: int = 0
    enter_time: int = 0       # ms
    enter_price: float = 0.0
    close_time: Optional[int] = None  # ms
    close_price: Optional[float] = None
    status: PositionStatus = PositionStatus.OPEN
    real_pnl: float = 0.0
    profit_pct: float = 0.0
    flow: str = ""
    start_reason: str = ""
    close_reason: str = ""
    max_price: float = 0.0
    min_price: float = 0.0
    qty: float = 0.0
    entry_equity: float = 0.0
    entry_margin_usd: float = 0.0
    entry_notional_usd: float = 0.0
    entry_fee_usd: float = 0.0
    exit_fee_usd: float = 0.0
    layers: int = 1                 # số lần vào lệnh (1 = không DCA)
    avg_price: float = 0.0          # giá trung bình sau các tầng DCA
    total_margin_usd: float = 0.0   # tổng ký quỹ đã dùng
    mae_pct: float = 0.0            # lỗ treo tối đa trong lệnh (% vốn ban đầu, số âm)
    fees_usd: float = 0.0           # tổng phí mọi tầng + thoát
    funding_usd: float = 0.0        # funding đã trả (+) / nhận (−) trong lệnh (perp)
    unit_pct: float = 0.0           # exit_unit="atr": ATR% lúc vào lệnh (SL/TP/trailing = bội số của nó)
    leverage_used: float = 1.0      # đòn bẩy thực dùng cho vị thế (có thể < tham số để thanh lý xa SL)
    risk_usd: float = 0.0           # sizing="risk": số tiền dự kiến mất nếu chạm SL
    strategy_id: str = ""           # backtest danh mục: id chiến lược sinh ra vị thế

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "PositionModel":
        raw_type = row.get("lab_result_type", 1)
        raw_status = row.get("lab_result_status", 1)
        return cls(
            result_id=row.get("lab_result_id") or 0,
            account_id=row.get("lab_result_account") or 0,
            campaign_id=row.get("lab_result_campaign") or 0,
            symbol=row.get("lab_result_symbol") or "",
            pos_type=PositionType(raw_type) if raw_type in (1, 2) else PositionType.LONG,
            phase=int(row.get("lab_result_phase") or 0),
            enter_time=int(row.get("lab_result_chart") or row.get("lab_result_enter_time") or 0),
            enter_price=float(row.get("lab_result_chart_price") or row.get("lab_result_enter_price") or 0.0),
            close_time=int(row.get("lab_result_close_time")) if row.get("lab_result_close_time") else None,
            close_price=float(row.get("lab_result_sell_price")) if row.get("lab_result_sell_price") else None,
            status=PositionStatus(raw_status) if raw_status in [0, 1, 2, 3, 4, 5, 6] else PositionStatus.OPEN,
            real_pnl=float(row.get("lab_result_realpnl") or row.get("lab_result_profit") or 0.0),
            profit_pct=float(row.get("lab_result_realprofit") or row.get("lab_result_eventprofit") or 0.0),
            flow=row.get("lab_result_flow") or "",
            start_reason=row.get("lab_result_start_reason") or "",
            close_reason=row.get("lab_result_close_reason") or "",
            max_price=float(row.get("lab_result_max_price") or 0.0),
            min_price=float(row.get("lab_result_min_price") or 0.0),
        )


@dataclass
class OrderModel:
    """Mô hình lệnh khớp chi tiết (lab_order)."""
    order_id: int = 0
    account_id: int = 0
    position_id: int = 0      # lab_order_action
    order_time: int = 0       # ms
    order_type: OrderType = OrderType.BUY
    order_price: float = 0.0
    qty: float = 0.0
    phase: int = 0
    fee_usd: float = 0.0          # phí của riêng lệnh này
    liquidity: str = ""           # "maker" (limit) | "taker" (market) | "liquidation"
    slippage: float = 0.0         # tỉ lệ trượt giá đã áp lên giá khớp (lệnh taker; không gồm phí)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "OrderModel":
        raw_type = row.get("lab_order_type", 1)
        return cls(
            order_id=row.get("lab_order_id") or 0,
            account_id=row.get("lab_order_account") or 0,
            position_id=row.get("lab_order_action") or 0,
            order_time=int(row.get("lab_order_time") or 0),
            order_type=OrderType(raw_type) if raw_type in (1, 2) else OrderType.BUY,
            order_price=float(row.get("lab_order_price") or 0.0),
            qty=float(row.get("lab_order_qty") or 0.0),
            phase=int(row.get("lab_order_phase") or 0),
        )


