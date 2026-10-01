# E7-S2: Đối số job kiểm chặt, giới hạn và khôi phục trạng thái

- **Epic:** E7 Studio API
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người vận hành, tôi muốn job chỉ nhận đối số đã kiểm và số job đồng thời có giới hạn, để API không thành đường chạy lệnh tuỳ ý hay làm quá tải máy.

## Acceptance Criteria

1. **Given** loại job và cờ, **When** dựng đối số, **Then** chỉ loại trong danh sách trắng (`book_backtest`, `book_wfa`, `book_build`) và cờ được phép (`test_build_args_and_whitelist`).
2. **Given** ngày sai định dạng, tài sản ngoài vũ trụ, số ngoài khoảng hoặc id ứng viên lạ, **When** gọi, **Then** 422 (`test_backtest_rejects_bad_requests`).
3. **Given** `report_dir`, **When** không nằm trong `data/_cache/book/` hoặc thiếu `stage_a.json`/`report.json`, **Then** bị từ chối (`test_wfa_report_dir_must_be_a_book_run`).
4. **Given** đã có ≥ 8 job chạy/chờ, **When** tạo job mới, **Then** 429 (`test_too_many_active_jobs_is_429`).
5. **Given** job id không đúng `YYYYMMDD_HHMMSS_<6 hex>`, **When** đọc, **Then** 422 (chống path traversal).

## Tasks / Subtasks

- [x] `KINDS` danh sách trắng và `_check_launch_args`
- [x] `MAX_ACTIVE = 8`, `MAX_WFA_STRATEGIES = 16`, `MAX_WFA_CONFIGS = 50`
- [x] `--out` của `book_build` do `launch` tự thêm
- [x] Khôi phục trạng thái từ pid, dòng `exit N`, `result.json`

## Dev Notes

- Code: `backend/api/jobs/batch.py`. Test dùng `run_limited` giả; hành vi thật chạy qua E2E ở E7-S1.
- Xác thực người gọi **chưa có** (E11-S1, E11-S2): ai tới được cổng 18010 đều gọi được.

## Evidence

- Commit: `2d4698f`.
- Tests: `test/test_book_api.py` (15 test, gồm các test trên).

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
