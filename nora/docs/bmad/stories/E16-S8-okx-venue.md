# Story E16-S8: — Adapter OkxVenue (P6.7)

## Status
Done

## Story
**Là** kỹ sư hệ thống, **tôi muốn** hoàn thiện — Adapter OkxVenue (P6.7), **để** hệ thống vận hành đúng chuẩn định lượng và kiến trúc Nora.

## Acceptance Criteria
1. Given `OkxVenue`, When gọi `submit`, Then ánh xạ ENTRY thành market_open, EXIT thành close_market, SL/TP thành lệnh điều kiện tương ứng.
2. Given phản hồi từ OKX, When gọi `next_event`, Then sinh ra `Fill`, `OrderRejected`, `FundingApplied` theo đúng định dạng chuẩn.

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
- Commit: `eb1cab5` (P6.7 OkxVenue implements Venue protocol).
- Kiểm chứng: Conformance test xanh trên mock HTTP OKX v5.

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-06 | 1.0.0 | Khởi tạo và ghi nhận trạng thái | BMAD Dev |
