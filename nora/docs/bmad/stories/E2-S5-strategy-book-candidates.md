# Story E2-S5: Bảy ứng viên sổ chiến lược dùng chung tham số toàn vũ trụ

## Status
Done

## Story
Là người nghiên cứu, tôi muốn mỗi chiến lược có một bộ tham số chung cho cả 8 tài sản, thoát lệnh theo ATR và khối lượng theo rủi ro, để một cấu hình không thể thắng chỉ nhờ một tài sản.

## Acceptance Criteria
1. **Given** ứng viên và tham số, **When** `materialize`, **Then** trả `{id, side, tree, position, signal_params}` với `position` = `BASE_POSITION` + tham số riêng (`test_book_pipeline_runs_all_stages_with_shared_params`).
2. **Given** `BASE_POSITION`, **When** kiểm giá trị, **Then** perp, đòn bẩy 10, `exit_unit="atr"`, `sizing="risk"`, `risk_per_trade_pct=0.5`, `max_notional_pct=300`, `stop_fill="level"`, `cooldown=60`.
3. **Given** sổ xuất ra, **When** đọc cấu hình, **Then** mô tả đúng quy tắc đã mô phỏng (`test_book_export_describes_simulated_rules`).

## Tasks / Subtasks
- [x] 7 ứng viên: `trend_long`, `trend_short`, `breakout_4h_long`, `breakout_4h_short`, `momentum_long`, `reversion_long`, `reversion_short`
- [x] Không gian tham số mỗi ứng viên (`space`)
- [x] `materialize`, `perp_symbols`, `UNIVERSE`
- [x] `GATES` và `RISK` tập trung một nơi

## Dev Notes
- Code: `backend/core/strategy/strategy_book.py`. `GATES = {min_trades 40, min_symbols_positive 5, min_symbols_positive_dev2 4, max_mdd_pct 30}`; `RISK = {8 vị thế, 1/tài sản, 3.0x, kill 30%}`.
- `breakout_4h_*` dùng `atr_frame="4h"`; các ứng viên còn lại ATR 1h.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code).
- Tests: `test/test_strategy_book.py` (5).
- Kết quả sử dụng: xem E5-S3 và E5-S5.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
