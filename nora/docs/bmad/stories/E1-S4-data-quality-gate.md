# Story E1-S4: Quality gate dữ liệu và nơi gate được gọi

## Status
Done

## Story
Là người nghiên cứu, tôi muốn dữ liệu hỏng, tổng hợp hoặc thiếu bị chặn trước khi backtest/WFA, để kết quả không dựa trên dữ liệu không đáng tin.

## Acceptance Criteria
1. **Given** tài sản không có manifest, **When** gọi `/simulate` hoặc WFA, **Then** bị chặn/thất bại kèm lý do (`test_simulate_blocked_without_manifest`, `test_wfa_fails_without_manifest`).
2. **Given** manifest `synthetic=true`, **When** gọi `/simulate` hoặc WFA, **Then** bị chặn (`test_simulate_blocked_synthetic`, `test_wfa_fails_synthetic`).
3. **Given** `crawl_ok=false`, `sha256_1m` lệch, độ phủ < 30 ngày hoặc `filled_ratio > 0,60`, **When** đánh giá, **Then** trạng thái lần lượt `BLOCKED`, `BLOCKED`, `NEEDS_MORE_DATA`, `BLOCKED` (`test_gate_crawl_ok_false_is_blocked`, `test_gate_sha256_mismatch_blocked`, `test_gate_coverage_days_low_needs_more_data`, `test_gate_filled_ratio_threshold`).
4. **Given** thiếu khung 4h, **When** đánh giá, **Then** `BLOCKED` (`test_gate_blocks_when_4h_missing`).
5. **Given** bất kỳ file nào trong thư mục tài sản đổi, **When** gọi gate lại, **Then** cache hết hạn và đánh giá lại (`test_gate_cache_invalidates_on_file_change`).

## Tasks / Subtasks
- [x] `evaluate_data_quality` với 4 trạng thái và điểm 0-100
- [x] Chính sách bước nhảy lớn theo nguồn: WARNING cho CEX đã kiểm checksum, BLOCKED cho DEX (`test_extreme_move_policy_by_source`)
- [x] Gọi gate ở Studio `/simulate`, scan, WFA đơn tài sản, research, `promote_staging`
- [>] Gọi gate ở đường danh mục/sổ: chuyển sang E11-S6

## Dev Notes
- Code: `backend/core/data/quality_gate.py`; ngưỡng `MAX_FILLED_RATIO_1M = 0.60`.
- **Khoảng trống đã biết:** `PortfolioEngine`, `build_strategy_book`, `validate_book`, `run_book_backtest` không gọi gate (`grep evaluate_data_quality` chỉ thấy `studio.py`, `scan.py`, `walk_forward.py`, research, `promote_staging`). Đường danh mục dựa vào `promote_staging`. Story này đóng ở phạm vi đang có; phần còn thiếu là E11-S6.
- Gate trên 3 năm 1m mất khoảng 11 s (comment trong code); cache trong tiến trình tránh lặp lại.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo); `808d7f4` thêm gate checks (`test_data_quality_gate_checks`).
- Tests: `test/test_crawler_and_gate.py` (6), `test/test_round3_completion.py`, `test/test_round4_venue_and_fills.py`, `test/test_signals_strategies.py`.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
