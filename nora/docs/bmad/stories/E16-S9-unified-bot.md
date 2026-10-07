# E16-S9 — Bot chạy trên lõi thống nhất (P6.8)

- **Epic:** E16 Kiến trúc thực thi thống nhất
- **Trạng thái:** in-progress
- **Cập nhật:** 2026-10-06

**Story.** Là vận hành viên, tôi muốn bot giao dịch demo/live chạy trên chính Runner + OkxVenue + PositionManager + Account ảo với cờ `engine=unified`, và có bộ so sánh mức sự kiện `compare_events` để đo lường trượt giá và độ lệch với mô phỏng.

## Acceptance Criteria

1. Given cấu hình bot `engine=unified`, When khởi động, Then bot chạy qua `Runner(OkxVenue)` và ghi nhận đúng trạng thái bắt đầu.
2. Given bot đang chạy, When có lệnh khớp từ sàn và mô phỏng song song, Then ghi nhận các cặp sự kiện để đo trượt giá (slippage bps).

## Evidence

- Commit: `a738ea6`, `b1ebe1c` (P6.8 unified bot engine).
- Tiến độ: Bot demo mới job `20261006_163924_505644` đang chạy với `engine: unified` trên OKX demo (vốn 4.859 USDT).
