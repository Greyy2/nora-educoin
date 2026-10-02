# E3-S4: Ngân sách DCA, cooldown và loại tổ hợp không hợp lệ

- **Epic:** E3 Engine backtest, vốn & rủi ro
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn cấu hình DCA không vừa vốn bị từ chối rõ ràng và có cooldown sau khi thoát, để tầng DCA không bị bỏ âm thầm và không vào lại ngay trên tín hiệu cũ.

## Acceptance Criteria

1. **Given** `order_size_pct=20`, 5 tầng DCA, **When** dựng tham số, **Then** `ValueError` kèm `order_size_pct` lớn nhất còn vừa; 19% thì qua (`test_budget_20pct_x5_layers_fails_19pct_passes`, `test_build_params_rejects_over_budget_with_clear_message`).
2. **Given** tầng DCA bị từ chối lúc chạy do hết vốn, **When** hoàn tất, **Then** `dca_layers_rejected` ghi số tầng và logic khớp lệnh không đổi (`test_refused_dca_layer_is_counted_and_fill_logic_unchanged`, `test_get_results_exposes_dca_layers_rejected`).
3. **Given** `cooldown=N`, **When** vừa đóng vị thế (kể cả `force_close`/timeout), **Then** tín hiệu trong N phút bị bỏ, sau N phút được nhận (`test_reentry_blocked_within_cooldown_allowed_after`, `test_cooldown_applies_after_force_close_and_timeout`).
4. **Given** `cooldown=0`, **When** chạy, **Then** kết quả giống mặc định cũ (`test_cooldown_zero_is_identical_to_default`) và skip-idle không đổi kết quả (`test_skip_idle_identical_with_cooldown`).
5. **Given** lưới tối ưu có tổ hợp không vừa ngân sách, **When** lấy mẫu hoặc WFA, **Then** loại trước/bỏ qua thay vì làm hỏng job (`test_sample_configs_filters_invalid_before_sampling_and_is_deterministic`, `test_wfa_skips_invalid_dca_combo`, `test_wfa_all_combos_invalid_falls_back_with_note`).

## Tasks / Subtasks

- [x] `dca_budget_check` (`need_pct`, `max_order_size_pct`)
- [x] `cooldown` trong `StrategyParams`, snapshot và sổ
- [x] `optimize_alphas` đếm `configs_invalid`
- [x] `_optimize_is` bỏ qua tổ hợp hỏng

## Dev Notes

- Code: `backend/core/backtest/params_builder.py`, `execution.py`, `backend/wfa/walk_forward.py`, `backend/optimize/optimize_alphas.py`. Đặc tả: `architecture.md` §5.5.
- Chỉ áp cho `sizing="margin_pct"`; `sizing="risk"` chia khối lượng theo tổng hệ số tầng.
- Sổ chiến lược dùng `cooldown=60` (một nến 1h). Golden `portfolio_real` ghim `cooldown=0` để giữ bit-identical.

## Evidence

- Commits: `edb26f4` (ngân sách DCA, cooldown, một ngưỡng WFA 0,6), `06ae13b` (bỏ qua tổ hợp bị từ chối).
- Tests: `test/test_dca_cooldown.py` (15), `test/test_wfa_invalid_combos.py` (3). Commit ghi 313 test qua (`edb26f4`) và 316 (`06ae13b`); golden 4/4.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
