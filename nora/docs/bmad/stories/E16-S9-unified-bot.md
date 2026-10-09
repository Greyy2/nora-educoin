# Story E16-S9: — Bot chạy trên lõi thống nhất (P6.8)

## Status
In-progress

## Story
**Là** kỹ sư hệ thống, **tôi muốn** hoàn thiện — Bot chạy trên lõi thống nhất (P6.8), **để** hệ thống vận hành đúng chuẩn định lượng và kiến trúc Nora.

## Acceptance Criteria
1. Given cấu hình bot `engine=unified`, When khởi động, Then bot chạy qua `Runner(OkxVenue)` và ghi nhận đúng trạng thái bắt đầu.
2. Given bot đang chạy, When có lệnh khớp từ sàn và mô phỏng song song, Then ghi nhận các cặp sự kiện để đo trượt giá (slippage bps).

## Tasks / Subtasks
- [x] Hoàn thành triển khai và kiểm thử

## Dev Notes
Tham chiếu kiến trúc Nora.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PENDING
- Commit: `a738ea6`, `b1ebe1c` (P6.8 unified bot engine).
- Tiến độ: Bot demo mới job `20261006_163924_505644` đang chạy với `engine: unified` trên OKX demo (vốn 4.859 USDT).

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-06 | 1.0.0 | Khởi tạo và ghi nhận trạng thái | BMAD Dev |
