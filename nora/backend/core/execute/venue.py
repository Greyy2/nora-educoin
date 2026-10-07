"""Giao diện sàn (Venue) — P6.4. Đặc tả: docs/bmad/p6_execution_design.md §3.

Một Protocol duy nhất cho mọi nơi khớp lệnh: `SimVenue` (sim_venue.py: backtest-py, paper) và `OkxVenue` (live/okx_venue.py: demo, live).
PositionManager (manager.py) chỉ nói chuyện với giao diện này: đặt LỆNH (`submit`), kéo SỰ KIỆN (`next_event` -> Fill / OrderRejected),
rồi tự áp sự kiện vào Account / PositionBook (account.py) — venue KHÔNG đụng vào sổ vốn.

Quy ước:
- `slot` là chỉ số slot (symbol × chiến lược) trong runner; mỗi slot có tập lệnh chờ riêng và tối đa một vị thế (net).
- `Order.id` là định danh lệnh CHỜ (để `cancel`), do người đặt cấp bằng `new_order_id()`; KHÔNG phải `Fill.order_id`
  (id ghi vào `OrderModel`: sim cấp bằng `tracker._next_id()` lúc khớp, OKX dùng id của sàn).
- Lệnh ENTRY/EXIT là MARKET (level = nan). SL/TRAIL/TP là lệnh bảo vệ đóng hết vị thế; DCA là lệnh limit nhồi tầng.
- Hợp đồng chung (P6.8b): ENTRY thứ hai trên slot đã có vị thế -> OrderRejected("position_exists"); SL/TP/TRAIL/DCA khi slot chưa có vị thế ->
  OrderRejected("no_position") — cả SimVenue lẫn OkxVenue (manager không bao giờ làm vậy, nên đường event vẫn bit-identical).
- `next_event` là kéo (pull): trả sự kiện kế tiếp của slot hoặc None khi hết (sim khớp theo nến hiện tại, OKX đọc hàng đợi poll).
"""
import itertools
from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional, Protocol, Union

from backend.core.models import Fill, OrderRejected

NAN = float("nan")


class OrderKind(IntEnum):
    ENTRY = 1   # market, mở tầng đầu
    EXIT = 2    # market, đóng hết (tín hiệu thoát / hết thời gian / kill)
    DCA = 3     # limit nhồi tầng
    SL = 4      # stop-loss đóng hết (từ giá TB)
    TRAIL = 5   # trailing stop đóng hết
    TP = 6      # limit chốt lời đóng hết (từ giá TB)


@dataclass
class Order:
    id: int
    slot: int
    kind: OrderKind
    is_buy: bool
    level: float = NAN          # DCA/SL/TRAIL/TP: mức giá đặt; ENTRY/EXIT: nan (market ở open)
    trigger: float = NAN        # DCA/TP có limit_through: mức phải đi QUA; mặc định (nan) = level
    notional: float = 0.0       # ENTRY/DCA (sim tính qty = notional / giá khớp); EXIT/SL/TRAIL/TP: đóng hết
    margin: float = 0.0
    reason: str = ""            # nhãn close_reason / start_reason của tracker
    reduce_only: bool = False
    post_only: bool = False
    # TRAIL (P6.8b): `level` luôn là mức stop TĨNH tính từ đỉnh các nến trước (SimVenue đọc mức này). Venue có trailing gốc (OKX) đọc thêm
    # `activation` (giá kích hoạt) và `callback_pct` (% lùi khỏi đỉnh, vd 1.5 = 1.5%); thiếu (nan) thì rơi về level / trigger như quy ước cũ.
    activation: float = NAN
    callback_pct: float = NAN
    # TRAIL cho SimVenue đường ohlc/adaptive: `peak` = đỉnh/đáy có lợi các nến TRƯỚC (venue tự chạy tiếp theo từng chặng của nến) và
    # `activation_pct` = ngưỡng lãi % để bật trailing (so với avg hiện tại); thiếu (nan) thì venue dùng `level` tĩnh như đường cũ.
    peak: float = NAN
    activation_pct: float = NAN


@dataclass(frozen=True)
class VenueCaps:
    generates_liquidation: bool   # venue tự sinh Fill thanh lý (sim); sàn thật chỉ quan sát
    native_trailing: bool         # venue có lệnh trailing gốc (OKX); sim dùng mức tĩnh tính từ đỉnh các nến trước
    post_only: bool               # venue hỗ trợ post_only cho lệnh limit
    rounds_qty: bool              # venue làm tròn qty/giá theo bộ lọc sàn


class Venue(Protocol):
    caps: VenueCaps

    def submit(self, order: Order) -> None: ...
    def cancel(self, order_id: int) -> None: ...
    def cancel_slot(self, slot: int) -> None: ...
    def open_orders(self, slot: int) -> List[Order]: ...
    def next_event(self, slot: int) -> Optional[Union[Fill, OrderRejected]]: ...


_ORDER_ID = itertools.count(1)


def new_order_id() -> int:
    """Cấp `Order.id` mới (toàn cục, tăng dần). Tách khỏi `tracker._ID_SEQ` để việc đặt/huỷ lệnh chờ không tiêu id của OrderModel."""
    return next(_ORDER_ID)
