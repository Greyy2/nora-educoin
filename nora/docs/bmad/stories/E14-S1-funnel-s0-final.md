# Story E14-S1: Phễu S0 → FINAL: chống ăn may, WFA, MC, sizing, holdout

## Status
Done

## Story
Là nhà nghiên cứu, tôi muốn mọi alpha sinh ra đi qua các tầng ngày càng khắt khe với lý do loại rõ ràng, để chỉ alpha thắng thật và sống sót được vào testnet.

## Acceptance Criteria
1. **Given** một lượt phễu, **When** chạy, **Then** mỗi tầng có thống kê vào/ra, lý do loại (mã + tiếng Việt) và danh sách lệnh.
2. **Given** lượt bị ngắt, **When** resume, **Then** kết quả trùng với chạy liền (`test_resume_after_crash_is_identical`).
3. **Given** DSR/PBO, **When** tính ở S2, **Then** N = số alpha đã thử của chiến lược.

## Tasks

- [x] `optimize/funnel/*`
- [x] API `/api/studio/funnel`
- [x] UI tab Phễu trong `/alpha`

## Tasks / Subtasks
- [x] Hoàn thành triển khai và kiểm thử

## Dev Notes
Roadmap P0.2, P4.2, P4.7; hợp đồng docs/funnel_contract.md.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `197bfc0`, `9bc8a85`, `b42bfc2`.
- Test: `test/test_funnel.py`.
- Số đo: các lượt `data/_cache/funnel/fr-2026100*`.

## Change Log
| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-03 | Tạo story | 197bfc0 |
