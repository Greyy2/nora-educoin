# Story E16-S7: — Bộ kiểm thử hợp đồng Venue (P6.6)

## Status
Done

## Story
**Là** kỹ sư hệ thống, **tôi muốn** hoàn thiện — Bộ kiểm thử hợp đồng Venue (P6.6), **để** hệ thống vận hành đúng chuẩn định lượng và kiến trúc Nora.

## Acceptance Criteria
1. Given `SimVenue`, When chạy bộ kiểm thử conformance, Then tất cả các ca kiểm thử hợp đồng (đặt lệnh, huỷ lệnh, khớp lệnh, từ chối lệnh) đều đạt.
2. Given sự khác biệt giữa Sim và OKX, When ghi nhận các ca đặc thù, Then đánh dấu rõ bằng xfail/strict để xử lý ở adapter.

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
- Commit: `c26e20f` (P6.6 venue conformance suite).
- Kiểm chứng: 56 pass trên SimVenue.

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-06 | 1.0.0 | Khởi tạo và ghi nhận trạng thái | BMAD Dev |
