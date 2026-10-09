# Story E16-S5: — Giao diện Venue, SimVenue và PositionManager (P6.4)

## Status
Done

## Story
**Là** kỹ sư hệ thống, **tôi muốn** hoàn thiện — Giao diện Venue, SimVenue và PositionManager (P6.4), **để** hệ thống vận hành đúng chuẩn định lượng và kiến trúc Nora.

## Acceptance Criteria
1. Given `Venue` protocol, When gửi lệnh (`submit`) và lấy sự kiện (`next_event`), Then quy định rõ hợp đồng cho cả sàn thật và sàn ảo.
2. Given 7 tầng tính năng (market, SL, DCA settle, TP, trailing, thanh lý, gap/stop_fill), When chạy kiểm chứng chéo giữa PositionManager+SimVenue và RefPositionTracker, Then khớp từng bit trên mọi trường và mọi sự kiện.

## Tasks / Subtasks
- [x] Hoàn thành triển khai và kiểm thử

## Dev Notes
Tham chiếu kiến trúc Nora.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- **Tests:** `test/test_ops_units.py`, `test/scripts/nautilus_diff/check_baseline.py`
- Commit: `bcf3911`, `dff2201` (P6.4 SimVenue, PositionManager, event path parity harness).
- Kiểm chứng: 7 tầng bit-identical với tracker trên 1.400 cấu hình ngẫu nhiên (200 cấu hình/tầng).

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-06 | 1.0.0 | Khởi tạo và ghi nhận trạng thái | BMAD Dev |
