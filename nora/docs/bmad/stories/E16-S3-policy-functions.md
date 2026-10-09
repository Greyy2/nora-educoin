# Story E16-S3: — Hàm thuần chính sách vị thế (P6.2)

## Status
Done

## Story
**Là** kỹ sư hệ thống, **tôi muốn** hoàn thiện — Hàm thuần chính sách vị thế (P6.2), **để** hệ thống vận hành đúng chuẩn định lượng và kiến trúc Nora.

## Acceptance Criteria
1. Given mức giá và cấu hình vị thế, When tính toán các mốc DCA/SL/TP/trailing/thanh lý, Then `policy.py` trả về kết quả giống hệt `PositionTracker`.
2. Given `PositionTracker`, When chạy các bước intrabar, Then uỷ quyền cho `policy.py` mà không làm thay đổi kết quả số.
3. Given các bài test golden và parity, When chạy lại, Then bảo toàn bit-identical 100%.

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
- Commit: `0aa01e1` (P6.2 policy.py).
- Kiểm chứng: Golden, parity, pack_trackers bit-identical.

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-06 | 1.0.0 | Khởi tạo và ghi nhận trạng thái | BMAD Dev |
