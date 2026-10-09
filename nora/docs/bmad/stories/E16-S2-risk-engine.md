# Story E16-S2: — Risk engine độc lập (P6.1)

## Status
Done

## Story
**Là** kỹ sư hệ thống, **tôi muốn** hoàn thiện — Risk engine độc lập (P6.1), **để** hệ thống vận hành đúng chuẩn định lượng và kiến trúc Nora.

## Acceptance Criteria
1. Given các giới hạn danh mục (max_positions, max_per_symbol, max_gross_exposure, max_open_risk_pct, dd_throttle), When gọi `admit_entry`, Then trả về kết quả cho phép/từ chối kèm khối lượng tối đa được phép mở.
2. Given sụt giảm vốn MTM từ đỉnh, When vượt quá `kill_switch_dd_pct`, Then `kill_check` trả về cờ kích hoạt dừng khẩn cấp.
3. Given `PaperBook`, When nạp nến mới, Then uỷ quyền cho `risk.py` thay vì giữ code rủi ro nội tuyến.

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
- Commit: `8b553b2` (P6.1 risk engine).
- Kiểm chứng: PaperBook = kernel trên 100 cấu hình ngẫu nhiên đủ 7 trần rủi ro.

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-06 | 1.0.0 | Khởi tạo và ghi nhận trạng thái | BMAD Dev |
