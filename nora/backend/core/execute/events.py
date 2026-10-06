"""Sự kiện thực thi (P6.3): nguồn thay đổi DUY NHẤT của sổ vốn (Account) và vị thế (PositionBook).

Mỗi sự kiện là dữ liệu bất biến; phát lại cùng chuỗi sự kiện vào Account + PositionBook mới cho đúng từng bit
vốn, ký quỹ giữ chỗ và PositionModel/OrderModel của lần chạy gốc (test/test_account_replay.py).
Đặc tả: docs/bmad/p6_execution_design.md §2.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Fill:
    """Một lệnh khớp. kind: "entry" | "dca" (mở/nhồi tầng) hoặc "sl" | "trail" | "tp" | "exit" | "timeout" | "liq" | "kill" | "end" (đóng hết)."""
    slot: int            # chỉ số slot (symbol × chiến lược) trong runner
    order_id: int
    kind: str
    t: int               # open_time của nến (ms)
    price: float         # giá khớp cuối cùng (đã gồm trượt giá với lệnh taker)
    raw_price: float     # giá trước trượt (để tái hiện thứ tự phép toán)
    notional: float      # entry/dca: margin × leverage (qty = notional / price); lệnh đóng: 0 (đóng hết)
    margin: float        # entry/dca: ký quỹ; lệnh đóng: 0
    fee: float
    slip: float
    liquidity: str       # "maker" | "taker" | "liquidation"
    # ── bổ sung ngoài đặc tả §2 (đều có mặc định): thông tin do manager/policy quyết định, book chỉ ghi lại ──
    reason: str = ""             # start_reason (entry) / close_reason (lệnh đóng)
    status: int = 0              # PositionStatus của lệnh đóng (sl/trail/tp không suy ra được chỉ từ kind)
    mae_usd: float = 0.0         # lệnh đóng: lỗ treo tối đa của vị thế (manager theo dõi)
    unit_pct: float = 0.0        # entry: ATR% lúc vào lệnh
    leverage_used: float = 1.0   # entry: đòn bẩy thực dùng
    risk_usd: float = 0.0        # entry: rủi ro dự kiến tới SL


@dataclass(frozen=True)
class FundingApplied:
    slot: int
    t: int
    rate: float
    price: float
    payment: float       # (+) trả, (−) nhận


@dataclass(frozen=True)
class OrderRejected:
    """Lệnh bị từ chối. reason: "budget" (vượt ngân sách vị thế — không đổi sổ vốn), "capital" (không giữ chỗ được
    từ vốn trống) hoặc "no_margin" (khối lượng <= 0 / không còn vốn) — hai loại sau cộng Account.rejected."""
    slot: int
    order_id: int
    kind: str
    reason: str


@dataclass(frozen=True)
class PositionMarked:
    """Nến mới của vị thế đang mở: cập nhật đỉnh/đáy (max_price/min_price) của PositionModel."""
    slot: int
    high: float
    low: float
