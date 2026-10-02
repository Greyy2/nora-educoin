# E6-S2: Bắt buộc trần RAM cgroup cho script nặng (run_limited)

- **Epic:** E6 Hạ tầng vận hành & bộ nhớ
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người vận hành, tôi muốn script nặng từ chối chạy khi không có trần RAM, để không ai vô tình chạy không giới hạn trên máy không có swap.

## Acceptance Criteria

1. **Given** không có cgroup giới hạn, **When** script nặng gọi `require_memory_limit`, **Then** `SystemExit` hướng dẫn dùng `run_limited.sh` (`test_require_memory_limit_refuses_without_cap`).
2. **Given** `NORA_ALLOW_UNLIMITED=1`, **When** chạy, **Then** được phép và trần là `inf` (`test_require_memory_limit_allows_explicit_unlimited`).
3. **Given** có cgroup, **When** hỏi trần, **Then** trả trần chặt nhất trong chuỗi cgroup (`test_require_memory_limit_returns_the_cap`, `test_effective_available_respects_cgroup_limit`).
4. **Given** OOM, **When** worker bị giết, **Then** worker có `oom_score_adj = 1000` bị giết trước tiến trình điều phối (`test_worker_init_never_raises` chỉ kiểm không ném lỗi; hành vi kernel kiểm bằng tay).
5. **Given** job bị kill (mã 137/9), **When** `run_limited` kết thúc, **Then** in gợi ý giảm worker hoặc tăng `--mem`.

## Tasks / Subtasks

- [x] `run_limited.sh` (systemd-run scope, taskset, nice)
- [x] `require_memory_limit`, `cgroup_limit_mb`, `worker_init`
- [x] Áp cho `build_strategy_book`, `validate_book`, `optimize_alphas`, `robustness_check`, `portfolio_sizing`
- [x] Log RAM mỗi giây và in đỉnh

## Dev Notes

- Code: `backend/utils/memwatch.py`, `backend/utils/ops/run_limited.sh`.
- `conftest.py` đặt `NORA_ALLOW_UNLIMITED=1` cho test nhỏ.

## Evidence

- Commit: `407f51f` (message: 258 test qua dưới trần 4G, peak 868 MB; `PER_WORKER_MB` hiệu chỉnh từ VmHWM đo 1280-1320 MB).
- Tests: `test/test_memory_guards.py` (các test `require_memory_limit_*`, `planning_budget_*`, `check_memory_gate_*`).

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
