# P6 — Đặc tả thiết kế thực thi (P6.3–P6.8)

Bổ sung cho [ADR-P6](adr-p6-unified-execution.md). Đây là hợp đồng giữa các phần; người cài đặt (S) làm theo, đổi chữ ký phải báo O.

## 1. Tách `PositionTracker` thành bốn vai

| Vai | File | Giữ gì | Lấy từ tracker hiện tại |
|---|---|---|---|
| Công thức | `core/execute/policy.py` (P6.2) | Hàm thuần: mức giá, giá khớp, phí, sizing | biểu thức trong `_intrabar`, `_risk_margin`, `_add_layer`, `_close` |
| Kế toán | `core/execute/account.py` (P6.3) | `Account` (sổ vốn: equity, reserved, peak, usage, rejected) + `PositionBook` (một slot: qty, avg, margin_used, fees_paid, layer_count, last_fill, reserved_here, funding_paid, entry_equity, PositionModel/OrderModel) | `CapitalLedger`, `_add_layer` (phần kế toán), `_close` (phần kế toán), `apply_funding` |
| Sàn | `core/execute/venue.py` (Protocol) + `sim_venue.py` (P6.4) | Lệnh đang chờ theo slot; khớp lệnh theo nến | thứ tự sự kiện trong `_intrabar`, gap, `stop_fill`, `limit_through`, thanh lý |
| Policy | `core/execute/manager.py` (P6.4) | Trạng thái chiến lược của slot: pending_entry/exit, cooldown, timeout, peak, mae, dca_ok, next_margin, mức thoát đã quy đổi; ra lệnh | `on_bar` bước 1 và 4, `_open`, đặt lại SL/TP/DCA/trailing |

Ràng buộc chung: mọi biểu thức giữ nguyên thứ tự phép toán float của tracker (sao chép nguyên văn qua `policy.py`). `PositionModel`/`OrderModel` sinh ra phải trùng từng trường, kể cả `order_id` lấy từ `tracker._ID_SEQ` theo đúng thứ tự gọi.

## 2. Sự kiện (`core/execute/events.py`, P6.3)

```python
@dataclass(frozen=True)
class Fill:
    slot: int            # chỉ số slot (symbol × chiến lược) trong runner
    order_id: int
    kind: str            # "entry" | "dca" | "sl" | "trail" | "tp" | "exit" | "timeout" | "liq" | "kill" | "end"
    t: int               # open_time của nến (ms)
    price: float         # giá khớp cuối cùng (đã gồm trượt giá với lệnh taker)
    raw_price: float     # giá trước trượt (để tái hiện thứ tự phép toán)
    notional: float      # lệnh vào/DCA: margin × leverage (qty = notional / price); lệnh đóng: 0 (đóng hết)
    margin: float        # lệnh vào/DCA: ký quỹ; lệnh đóng: 0
    fee: float
    slip: float
    liquidity: str       # "maker" | "taker" | "liquidation"

@dataclass(frozen=True)
class FundingApplied: slot: int; t: int; rate: float; price: float; payment: float

@dataclass(frozen=True)
class OrderRejected: slot: int; order_id: int; kind: str; reason: str   # "budget" | "post_only" | "min_size" | ...
```

`Account.apply(event)` và `PositionBook.apply(event)` là nơi DUY NHẤT thay đổi vốn và vị thế. Kiểm tra trước giao dịch (`margin_used + margin + fees_paid + fee > max_capital`, `ledger.reserve`) là hàm `Account.can_reserve(...)`/`PositionBook.can_add(...)` gọi trước khi chấp nhận Fill; bị từ chối thì sinh `OrderRejected("budget")` (tương đương `dca_rejected += 1` và cắt `dca_steps`).

## 3. Lệnh và giao diện sàn (`core/execute/venue.py`, P6.4)

```python
class OrderKind(IntEnum): ENTRY = 1; EXIT = 2; DCA = 3; SL = 4; TRAIL = 5; TP = 6

@dataclass
class Order:
    id: int; slot: int; kind: OrderKind; is_buy: bool
    level: float = nan          # DCA/SL/TRAIL/TP: mức giá đặt; ENTRY/EXIT: nan (market ở open)
    trigger: float = nan        # DCA/TP có limit_through: mức phải đi QUA; mặc định = level
    notional: float = 0.0       # ENTRY/DCA (sim tính qty = notional / giá khớp); EXIT/SL/TRAIL/TP: đóng hết
    margin: float = 0.0
    reason: str = ""            # nhãn close_reason / start_reason của tracker
    reduce_only: bool = False; post_only: bool = False

@dataclass(frozen=True)
class VenueCaps: generates_liquidation: bool; native_trailing: bool; post_only: bool; rounds_qty: bool

class Venue(Protocol):
    caps: VenueCaps
    def submit(self, order: Order) -> None: ...
    def cancel(self, order_id: int) -> None: ...
    def cancel_slot(self, slot: int) -> None: ...
    def open_orders(self, slot: int) -> List[Order]: ...
    def next_event(self, slot: int) -> Optional[Union[Fill, OrderRejected]]: ...   # kéo: sim khớp theo nến hiện tại; OKX đọc hàng đợi poll
```

`SimVenue` thêm `begin_bar(slot, t, o, h, l, c, position_view)` (position_view = avg, qty, pos_leverage, mmr, is_long để tính giá thanh lý) và `end_adverse(slot)` (chuyển sang phía có lợi: TP).

## 4. Một nến của một slot (thay `on_bar`)

```
manager.begin(t, o):                          # bước 1 của tracker
    pending_exit / timeout  -> submit(EXIT market) ; ev = venue.next_event -> account/book.apply -> đóng
    pending_entry & can_open -> sizing (policy + risk.Admission) -> submit(ENTRY market) -> apply
                                -> đặt SL, TRAIL (nếu đã kích hoạt), DCA kế tiếp (nếu dca_ok), TP
venue.begin_bar(slot, t, o, h, l, c, book.view())
loop:                                          # bước 2-3: phía bất lợi, hoà thì thoát trước
    ev = venue.next_event(slot)                # chọn mức cao nhất bị chạm (long) / thấp nhất (short), prio thoát=0 < DCA=1, gồm thanh lý
    None -> break
    Fill(dca)  -> apply; manager đặt lại SL/TRAIL/DCA kế tiếp từ avg mới; venue cập nhật position_view; continue
    Rejected(budget) -> manager cắt các tầng DCA còn lại; continue
    Fill(sl|trail|liq) -> apply; đóng; return
venue.end_adverse(slot); nếu chưa có DCA khớp trong nến: ev = next_event -> TP
manager.end(h, l, c, signals):                 # bước 4: peak, mae, pending flags, dca_ok, cooldown
```

Quy tắc theo độ phân giải nến (chính sách `intrabar_path="adverse_first"` của SimVenue, ghi docstring + test): trailing dùng peak của các nến trước (manager chỉ cập nhật peak ở `end`); TP không xét trong nến có DCA khớp.

## 5. Runner (`core/execute/runner.py`, P6.5)

`Runner(venue, account, slots, risk_cfg)`; `step_bar(t, bars, signals, funding)` chạy HAI PHA mỗi nến (P6.12, ADR mục 10): pha 1 (mở nến) funding theo symbol → từng slot theo thứ tự sổ: `risk.admit_entry` theo trạng thái lúc mở nến (`_gross()` định giá theo `last_close` = đóng nến trước) → `on_bar_open`; pha 2 (trong nến) từng slot `on_bar_rest` rồi cập nhật `last_*`; pha 3 MTM, `risk.kill_triggered` → đóng hết ("Kill switch danh mục"). Lệnh của tài sản đứng sau không thấy SL/TP trong nến hay giá đóng nến của tài sản đứng trước. `PaperBook` giữ API cũ, bên trong là `Runner(SimVenue(...))`.

## 6. OKX (`live/okx_venue.py`, P6.7) và Bot (P6.8)

`OkxVenue` cài `Venue`: `submit` ánh xạ ENTRY→`market_open`, EXIT→`close_market`, SL→`place_sl`, TP→`place_tp`, DCA→`place_post_only`, TRAIL→`place_trailing` (nếu `caps.native_trailing`); `next_event` sinh `Fill` từ chênh lệch vị thế khi poll (`positions()` + `closed_since`), `OrderRejected` từ lỗi post-only/min-size. Bot dùng cùng `Runner` + `manager` + `risk` + `Account` (sổ vốn ảo, ADR quyết định 3); vốn sàn đo được chỉ dùng cảnh báo lệch.

## 7. Harness kiểm chứng (P6.4)

`test/test_event_path_parity.py`: với mỗi tầng (4a market/timeout/funding, 4b SL, 4c DCA settle, 4d TP, 4e trailing, 4f liq, 4g limit_through/stop_fill/gap) sinh cấu hình ngẫu nhiên chỉ bật tính năng của tầng đó (và các tầng trước), chạy song song `RefPositionTracker` (oracle, `test/reference_engine.py`) và đường event trên cùng nến + tín hiệu, so từng bit mọi trường `PositionModel`, chuỗi `OrderModel`, ledger (equity, reserved, peak), bộ đếm (`dca_rejected`, `skipped_no_vol`, `ledger.rejected`). Tái dùng bộ sinh cấu hình và hàm so trường của `test/test_kernel_parity.py`.
