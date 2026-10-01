# E4-S1: Walk-forward đơn tài sản: fold, gate, NO_TRADE

- **Epic:** E4 Kiểm chứng WFA / Monte Carlo / holdout
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn chọn tham số trên IS rồi kiểm cố định trên OOS không chồng, với gate rõ ràng, để biết chiến lược có sống sót ngoài mẫu không.

## Acceptance Criteria

1. **Given** `step_days < test_days`, **When** sinh fold, **Then** `ValueError` (OOS không được chồng) (`test_generate_folds_no_overlap`).
2. **Given** một fold không có cấu hình đủ lệnh IS, **When** chạy, **Then** fold có `status="NO_TRADE"`, tính vào mẫu số tỉ lệ fold có lãi (`test_wfa_no_trade_fold_requires_status_field`, `test_wfa_all_no_trade_gate_false`).
3. **Given** lưới tham số, **When** vượt `MAX_GRID_COMBOS = 50`, chứa khoá lạ, rỗng hoặc giá trị chuỗi, **Then** bị từ chối nhanh (`test_param_grid_too_many_combos`, `test_param_grid_bogus_key_rejected`, `test_param_grid_empty_list_rejected`, `test_param_grid_string_value_rejected`).
4. **Given** kết quả WFA, **When** đánh giá gate, **Then** có đủ 6 check `is_return, total_folds, positive_ratio, total_trades, worst_mdd, compounded_return` và `acceptance_gate_passed` là AND của chúng (`test_wfa_gate_has_is_return_check`).
5. **Given** WFA đã xong, **When** đọc `aggregate_oos_daily_returns`, **Then** có chuỗi lợi suất ngày MTM của các fold TRADED theo thời gian (`test_wfa_result_has_oos_daily_returns`).

## Tasks / Subtasks

- [x] `generate_folds` (embargo, anchored, step)
- [x] `_optimize_is` trên `param_candidates`/lưới
- [x] `execute_wfa_pipeline` + gate + `param_stability`
- [x] `WfaFoldConfig` (`extra="forbid"`)
- [x] Gate dữ liệu trước khi chạy WFA (E1-S4)

## Dev Notes

- Code: `backend/wfa/walk_forward.py`, `backend/core/contracts.py` (`WfaFoldConfig`, `MAX_GRID_COMBOS = 50`).
- Cấu hình dùng trong `optimize_alphas`: train/test 120/30 ngày, `min_folds=5`, `min_positive_ratio=0.6`, `min_oos_trades=30`, `max_oos_mdd_pct=30`. Mặc định `WfaFoldConfig` (30/10, `max_oos_mdd_pct=25`) khác; hiểu rõ trước khi so số.

## Evidence

- Commits: `808d7f4` (test `test_wfa_mc`), `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code), `edb26f4` (ngưỡng 0,6 thống nhất với Studio), `06ae13b`, `45f734e` (lợi suất ngày OOS).
- Tests: `test/test_wfa_fold_status.py` (14), `test/test_wfa_mc.py` (3), `test/test_wfa_invalid_combos.py` (3), `test/test_round4_venue_and_fills.py::test_wfa_gate_has_is_return_check`.
- Ví dụ thật: alpha SOL, 14 fold, 9 fold có lãi, OOS +35,97%, 78 lệnh, MDD fold tệ nhất 9,13% (`data/alphas/registry.json`).

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
