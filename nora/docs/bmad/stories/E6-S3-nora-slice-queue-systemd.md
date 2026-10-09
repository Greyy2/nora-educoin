# Story E6-S3: nora.slice 12G, hàng đợi flock và unit systemd

## Status
Done

## Story
Là người vận hành, tôi muốn cả dự án Nora nằm trong một ngân sách RAM chung và job nặng xếp hàng từng cái một, để Nora không lấn máy dùng chung.

## Acceptance Criteria
1. **Given** `systemctl --user show nora.slice`, **When** đọc, **Then** `MemoryMax=12G`, `MemoryHigh=10800M`, `MemorySwapMax=0`, `TasksMax=512`.
2. **Given** hai `run_limited.sh` chạy cùng lúc, **When** chạy, **Then** chạy tuần tự bằng `flock`; `--no-wait` thoát mã 75 nếu có job khác.
3. **Given** job vượt trần slice, **When** OOM, **Then** chỉ job đó bị giết (mã 137), API và người khác không bị ảnh hưởng.
4. **Given** `install_user_units.sh` chạy lại, **When** cài, **Then** không lỗi (idempotent) và không enable/start unit.
5. **Given** API trong slice, **When** khởi động, **Then** `MemoryMax=3G`, cổng 18010, cache 512/512 MB.

## Tasks / Subtasks
- [x] `nora.slice`, `nora-api.service.in`
- [x] `install_user_units.sh`, `start_nora.sh`, `stop_nora.sh`
- [x] `planning_budget_mb` với dự phòng `NORA_HOST_RESERVE_MB = 8000`
- [x] Bỏ đường dẫn cứng `/home/ubuntu`, thêm `requirements.txt`

## Dev Notes
- Lý do 12G: máy 67 GB, không swap, ~32 GB trống tại thời điểm cấu hình, 12G ≈ 18% RAM.
- CPU: lõi 0-13, `nice 10` (`CPUAffinity=0-13`, `Nice=5` cho API); controller `cpu` không được uỷ quyền nên không dùng `CPUQuota`.
- Ngân sách hoạch định: `min(85% × trống cgroup, MemAvailable − 8000 MB)`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `836103b` (message: kiểm trên máy này — trần chỉ giết job (exit 137); hai job chạy lần lượt; 265 test qua, peak 877 MB; API khoẻ trong slice ~110 MB; `--workers auto` chọn 5 worker, đỉnh 5657 MB).
- Dời vào `ops/` ở `4e8dd61`. Tests: `test/test_memory_guards.py::test_planning_budget_*`.
- Lưu ý: kiểm bằng tay trên máy này; không có test tự động cho `flock` hay cgroup thật (chưa có).

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
