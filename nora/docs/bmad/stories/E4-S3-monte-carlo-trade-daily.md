# Story E4-S3: Monte Carlo theo lệnh và theo lợi suất ngày MTM

## Status
Done

## Story
Là người nghiên cứu, tôi muốn bootstrap trên lợi suất ngày mark-to-market thay vì chỉ trên lệnh đã đóng, để rủi ro cháy phản ánh cả lỗ chưa chốt.

## Acceptance Criteria
1. **Given** cùng chuỗi ngày, seed, scale, **When** chạy hai lần, **Then** cùng số; `run_monte_carlo_daily_detail.summary` trùng từng bit với `run_monte_carlo_daily` (`test_detail_summary_is_bit_identical_to_run_monte_carlo_daily`).
2. **Given** MC có `source_wfa_id`, **When** client gửi thêm lệnh tự tạo, **Then** bị bỏ qua, chỉ dùng dữ liệu của WFA (`test_mc_uses_wfa_trades_not_fake`, `test_mc_pipeline_never_falls_back_to_client_trades`).
3. **Given** WFA nguồn chưa xong, không tồn tại hoặc trượt gate, **When** MC chạy, **Then** `gate` phản ánh đúng, kể cả sau khi xoá bộ nhớ (`test_gate_true_after_memory_clear`, `test_gate_false_after_memory_clear`, `test_gate_nonexistent_job`, `test_gate_pending_job`).
4. **Given** `basis="daily"` (mặc định), **When** WFA cũ không có chuỗi ngày hoặc < 30 điểm, **Then** rơi về cơ sở lệnh kèm ghi chú (`test_mc_basis_trades_and_fallback_for_old_jobs`).
5. **Given** đường vốn có lỗ treo mà lệnh đã đóng không thấy, **When** so hai cơ sở, **Then** MC ngày cho MDD lớn hơn (`test_mc_daily_sees_unrealized_drawdown_that_trades_miss`).
6. **Given** cổng ruin của `optimize_alphas`, **When** đánh giá, **Then** dùng MC ngày, MC lệnh chỉ lưu tham chiếu (`test_optimize_alphas_gate_reads_daily_mc_and_keeps_trade_mc`).

## Tasks / Subtasks
- [x] `run_monte_carlo` (theo lệnh, block bootstrap)
- [x] `run_monte_carlo_daily` (horizon 365 ngày) giữ nguyên thứ tự gọi RNG của bản cũ
- [x] `run_monte_carlo_daily_detail` (fan, histogram, gate ruin)
- [x] `MonteCarloRunRequest.basis` mặc định `daily`
- [x] Chặn bypass gate bằng lệnh giả

## Dev Notes
- Code: `backend/carlo/monte_carlo.py`, `backend/core/backtest/portfolio_metrics.py` (`daily_returns_from_curve`), `backend/optimize/optimize_alphas.py` (`monte_carlo_gate`).
- Cảnh báo: **đừng vector hoá** vòng bootstrap khi chưa so lại từng bit; số seed/thứ tự RNG là một phần hợp đồng.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commits: `e334716` (MC ngày, trùng bootstrap cũ của sổ), `45f734e` (MC ngày cho WFA đơn tài sản), `efe4fb2` (`detail`).
- Tests: `test/test_daily_mc.py` (7), `test/test_golden_results.py` (8), `test/test_book_mc_api.py` (9), `test/test_round4_venue_and_fills.py::test_mc_robust_requires_wfa_gate_and_low_ruin`.
- SOL: MC ngày ruin 0,80% so với MC lệnh 0,55% (`45f734e`).

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
