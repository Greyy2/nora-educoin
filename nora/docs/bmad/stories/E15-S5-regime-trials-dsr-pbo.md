# Story E15-S5: Biến thể regime được đếm là lần thử trong DSR/PBO

## Status
Done

## Story
Là nhà nghiên cứu, tôi muốn mọi lựa chọn regime trong mẫu được tính là một lần thử, để DSR/PBO không bị đánh giá lạc quan.

## Acceptance Criteria
1. **Given** phễu `regime=both`, **When** sinh alpha, **Then** mỗi bộ tham số có 2 alpha (off + learn, `alpha_id` khác nhau) và N ở S2 = tổng số biến thể (`test_regime_both_variants_are_separate_trials_and_learn_on_train`).
2. **Given** alpha learn, **When** chạy S3 OOS, **Then** bảng regime học trên train của fold; S6 học trên toàn bộ trước holdout.
3. **Given** ngưỡng classifier, **When** chưa tối ưu, **Then** ghi rõ không tính trial; nếu tối ưu phải đưa vào params.

## Tasks

- [x] `FunnelConfig.regime` off|learn|both, `generate.regime_variants/split_regime`
- [x] `evaluate.learned_regime`, `base_job(learn_window)`
- [x] promote dựng regime từ `regime_blocked` của S6
- [x] API/UI phễu trường regime, ước tính nhân số biến thể

## Tasks / Subtasks
- [x] Hoàn thành triển khai và kiểm thử

## Dev Notes
Chọn `both` để so off/learn công bằng trong cùng lượt; DSR/PBO tự đếm vì mỗi biến thể là một alpha.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `dc08366`.
- Test: `test/test_funnel.py::test_regime_both_variants_are_separate_trials_and_learn_on_train`.
- Số đo: lượt `fr-20261003-4ab03b` (E14-S2).

## Change Log
| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-03 | Tạo | dc08366 |
