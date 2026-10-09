# Story E15-S1: — Regime thị trường: đặc tả (P2.1–P2.4)

## Status
Done

## Story
**Là** kỹ sư hệ thống, **tôi muốn** hoàn thiện — Regime thị trường: đặc tả (P2.1–P2.4), **để** hệ thống vận hành đúng chuẩn định lượng và kiến trúc Nora.

## Acceptance Criteria
1. Hoàn thành và kiểm thử toàn bộ yêu cầu kỹ thuật của story.

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
- Commit: `aa3823f` (classifier, REGIME_MAP + cầu chì, job báo cáo), `dc08366` (chạy dữ liệu thật, học trên train).
- Test: `test/test_regime.py` (nhân quả, golden khi tắt, lọc vào lệnh, cầu chì).
- Số đo: xem E15-S2 (báo cáo thật) và E15-S3 (WFA học trên train).

## Change Log
| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-02 | Đặc tả + classifier + bảng tĩnh | aa3823f |
| 2026-10-03 | Thêm trạng thái/Evidence; kết quả thật cho thấy bảng tĩnh không khớp dữ liệu (E15-S2) | dc08366 |
