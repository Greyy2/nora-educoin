# E7-S1: API sổ chiến lược: backtest, WFA, build chạy nền

- **Epic:** E7 Studio API
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn gọi backtest, WFA và build sổ qua API và theo dõi job, để dùng được từ UI mà không chạy nặng trong tiến trình API.

## Acceptance Criteria

1. **Given** `POST /api/studio/book/backtest`, **When** gọi, **Then** trả `{job_id}` và job chạy qua `run_limited.sh` không dùng shell (`test_backtest_launches_via_run_limited_without_shell`).
2. **Given** không có sổ và không truyền `strategies`, **When** `POST /backtest`, **Then** 409 (`test_backtest_without_book_or_strategies_is_409`).
3. **Given** `POST /wfa`, **When** truyền không đúng một nguồn (`report_dir`, `candidates`+`n`, `strategies`), **Then** 422 (`test_wfa_requires_exactly_one_source_and_valid_ids`).
4. **Given** job, **When** poll `GET /jobs/{id}`, **Then** trạng thái đi `queued → running → done|failed` kèm `log_tail` 40 dòng và `result` khi xong (`test_job_status_transitions`, `test_job_status_log_tail_and_bad_ids`).
5. **Given** API khởi động lại, **When** đọc job cũ, **Then** trạng thái khôi phục từ thư mục job (`test_waiter_thread_records_exit_code`).
6. **Given** router, **When** app khởi động, **Then** được nối vào `backend.main` (`test_router_is_wired_into_main`).

## Tasks / Subtasks

- [x] `backend/api/jobs/batch.py` (launch, status, list)
- [x] `backend/api/routers/book.py` (backtest, wfa, build, jobs)
- [x] `backend/cli/run_book_backtest.py` (một lần chạy `PortfolioEngine`)
- [x] `NORA_JOB_DIR/result.json` cho `build_strategy_book`, `validate_book`

## Dev Notes

- Code: `batch.py`, `routers/book.py`, `cli/run_book_backtest.py`. Đặc tả: `architecture.md` §9, §10; hợp đồng: `docs/ui_contract.md` §2, §4, §6.
- Hàng đợi job do `run_limited` (flock); API chỉ khởi chạy và đọc kết quả.

## Evidence

- Commit: `2d4698f` (message: E2E qua nora-api — book backtest BTC/SOL 2 tháng xong ~2 s; WFA danh mục xong 52 s trong scope `run-*.scope` của `nora.slice`, API giữ ~113 MB; 351 test qua).
- Job thật còn lưu: `data/_cache/api_jobs/20261001_123710_64ee1a` (`book_wfa`, 52,4 s), `20261001_164256_3430ce` (`book_backtest`, 2,1 s).
- Tests: `test/test_book_api.py` (15), `test/test_run_book_backtest.py` (8).

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
