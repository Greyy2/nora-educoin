"""Data Schemas & Models for Nora Backtest.

Định nghĩa các cấu trúc dữ liệu chuẩn hóa (Dataclasses / Enums)
đại diện cho các thực thể cốt lõi trong toàn bộ hệ thống backend.
"""
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional


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
class AccountModel:
    """Mô hình tài khoản backtest (lab_account)."""
    account_id: int
    name: str
    db_name: str = "backtest_data_1m_strategy810"
    created_at: Optional[int] = None
    status: int = 1
    description: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "AccountModel":
        return cls(
            account_id=row.get("lab_account_id") or 0,
            name=row.get("lab_account_name") or "",
            db_name=row.get("lab_account_db") or "backtest_data_1m_strategy810",
            created_at=row.get("lab_account_created"),
            status=row.get("lab_account_status", 1),
            description=row.get("lab_account_description") or "",
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CampaignModel:
    """Mô hình chiến dịch chạy backtest (lab_campaigns)."""
    campaign_id: int
    account_id: int
    symbol: str
    start_time: int
    end_time: int
    initial_balance: float = 10000.0
    current_balance: float = 10000.0
    total_profit: float = 0.0
    status: int = 1

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "CampaignModel":
        return cls(
            campaign_id=row.get("lab_campaign_id") or 0,
            account_id=row.get("lab_campaign_account") or 0,
            symbol=row.get("lab_campaign_symbol") or "",
            start_time=row.get("lab_campaign_start_time") or 0,
            end_time=row.get("lab_campaign_end_time") or 0,
            initial_balance=float(row.get("lab_campaign_balance") or 10000.0),
            current_balance=float(row.get("lab_campaign_current_balance") or 10000.0),
            total_profit=float(row.get("lab_campaign_profit") or 0.0),
            status=row.get("lab_campaign_status", 1),
        )


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


@dataclass
class OptimizationModel:
    """Mô hình tác vụ tối ưu hóa (lab_optimization)."""
    opt_id: int
    name: str
    account_id: int
    params_json: str
    status: int = 0
    created_at: Optional[int] = None

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "OptimizationModel":
        return cls(
            opt_id=row.get("lab_opt_id") or 0,
            name=row.get("lab_opt_name") or "",
            account_id=row.get("lab_opt_account") or 0,
            params_json=row.get("lab_opt_params") or "[]",
            status=row.get("lab_opt_status", 0),
            created_at=row.get("lab_opt_created"),
        )
