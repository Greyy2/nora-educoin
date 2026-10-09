# Story E6-S4: Module song song dùng chung: auto workers và pool chịu OOM

## Status
Done

## Story
Là người phát triển, tôi muốn mọi đường nặng dùng cùng một cách chia worker theo RAM và CPU, để không đường nào tự nghĩ ra số worker riêng.

## Acceptance Criteria
1. **Given** `--workers auto`, **When** tính, **Then** `min(CPU dùng được, ngân sách RAM / RAM mỗi worker)` (`test_auto_workers_limited_by_cpu_then_ram`, `test_auto_workers_max_workers_cap`).
2. **Given** không đọc được RAM, **When** tính, **Then** tối đa 2 worker (`test_auto_workers_conservative_when_budget_unreadable`).
3. **Given** máy đang bận, **When** tính ngân sách, **Then** Nora lùi theo dự phòng host (`test_planning_budget_backs_off_when_host_busy`, `test_auto_workers_backs_off_when_host_busy`).
4. **Given** job trong pool lỗi thật, **When** chạy, **Then** lỗi nổi lên ngay, không retry (`test_pool_map_safe_surfaces_job_errors_without_retrying`).
5. **Given** worker bị kill, **When** chạy, **Then** chỉ job còn thiếu chạy lại với nửa worker, giữ đúng thứ tự (`test_pool_map_safe_reruns_only_missing_jobs_after_worker_kill`, `test_pool_map_safe_keeps_job_order`).

## Tasks / Subtasks
- [x] `backend/utils/parallel.py` (`pool_map_safe`, `auto_workers`, `resolve_workers`)
- [x] Áp cho optimize, robustness, sizing, check_signals, research
- [x] `/api/v2/optimize/run` dùng ngân sách cgroup của API (tối đa 4 worker, endpoint đồng bộ)
- [x] Giữ alias cũ trong `build_strategy_book`

## Dev Notes
- `memwatch` import lúc gọi để test monkeypatch được.
- CPU Nora được dùng: 0-13 thay vì 0-5 (`030c7f9`).

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `030c7f9` (271 test qua, peak 788 MB).
- Tests: `test/test_parallel.py` (6), `test/test_memory_guards.py` (các test pool và budget).

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
