# Story E5-S4: Xuất sổ: trạng thái READY_FOR_TESTNET / HOLDOUT_FAILED và quy tắc không có testnet khi trượt holdout

## Status
Done

## Story
Là người vận hành, tôi muốn một sổ trượt holdout không bao giờ có cấu hình testnet và báo cáo không bị đọc nhầm kiểu boolean, để không ai chạy testnet cho sổ chưa đạt.

## Acceptance Criteria
1. **Given** `holdout_pass=true`, **When** `write_book`, **Then** ghi cả `book.json` và `testnet/book.json` (`test_write_book_holdout_pass_writes_testnet`).
2. **Given** `holdout_pass=false`, **When** `write_book`, **Then** chỉ ghi `book.json` với `status="HOLDOUT_FAILED"` và xoá `testnet/book.json` cũ nếu có (`test_write_book_holdout_fail_no_testnet_and_removes_stale`).
3. **Given** báo cáo cũ có chuỗi `"False"` do `default=str`, **When** đọc `holdout_pass` hoặc `accepted`, **Then** chỉ `True` thật hoặc chuỗi `"True"` được coi là đúng (`_is_true`).
4. **Given** giá trị numpy (bool, số), **When** ghi báo cáo, **Then** `json_default` ghi bool/số thật (`test_json_default_numpy_types`).
5. **Given** `holdout_level.ret_pct > 0`, `holdout_level.mdd_pct ≤ 30` và `holdout_extreme.mdd_pct ≤ 30`, **When** tính `holdout_pass`, **Then** `true`; thiếu một điều kiện thì `false` (lãi của `holdout_extreme` không bắt buộc dương).

## Tasks / Subtasks
- [x] `build_book`, `write_book`, `publish_book`
- [x] `jsonsafe.json_default` thay mọi `default=str`
- [x] `validate_book` đọc báo cáo cũ nghiêm ngặt
- [x] `testnet_book_config`

## Dev Notes
- Code: `backend/optimize/registry.py`, `backend/utils/jsonsafe.py`. Đặc tả: `architecture.md` §8.3.
- Lỗi đã sửa: numpy bool ghi thành chuỗi `'False'` (truthy) khiến `validate_book` coi chiến lược bị loại là đạt, `holdout_pass` không đáng tin.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `935d4d1` (message: bool thật trong báo cáo; sổ trượt holdout không có testnet).
- Tests: `test/test_strategy_book.py` (5), `test/test_portfolio_wfa.py::test_candidates_from_report_old_report_with_string_bools`. Bộ test lúc đó: 323 qua (peak 1,6 GB).

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
