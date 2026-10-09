# Story E16-S4: — Kế toán vị thế theo sự kiện (P6.3)

## Status
Done

## Story
**Là** kỹ sư hệ thống, **tôi muốn** hoàn thiện — Kế toán vị thế theo sự kiện (P6.3), **để** hệ thống vận hành đúng chuẩn định lượng và kiến trúc Nora.

## Acceptance Criteria
1. Given chuỗi lệnh thực hiện, When phát lại qua `Account` và `PositionBook`, Then equity, reserved margin, peak vốn và PnL khớp từng bit với `CapitalLedger`.
2. Given `PositionTracker`, When ghi nhận lệnh và funding, Then uỷ quyền phần kế toán cho `PositionBook`.

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
- Commit: `bf0906f` (P6.3 events.py, account.py).
- Kiểm chứng: Replay sự kiện bit-for-bit trên 14 seed × 4 slot.

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-06 | 1.0.0 | Khởi tạo và ghi nhận trạng thái | BMAD Dev |
