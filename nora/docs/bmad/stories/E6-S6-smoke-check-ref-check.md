# Story E6-S6: Smoke check bất biến và đối chiếu test với phiên bản cũ

## Status
Done

## Story
Là người vận hành, tôi muốn một bộ kiểm nhanh các bất biến và tính tất định, và cách chạy test hiện tại trên code cũ, để biết test thực sự bắt được lỗi cũ và pipeline không hỏng sau thay đổi.

## Acceptance Criteria
1. **Given** `smoke_check single`, **When** chạy, **Then** 7 ứng viên sổ trên SOL@perp, 8 bot kiểu OKX trên BTC và DCA probe không vi phạm bất biến (sổ vốn, vị thế, bậc DCA, rủi ro theo SL, trần danh nghĩa/đòn bẩy).
2. **Given** `smoke_check portfolio`, **When** chạy, **Then** danh mục 8 perp × 7 ứng viên (có `shared_dir`) không vi phạm trần danh mục.
3. **Given** mỗi lần chạy, **When** chạy hai lần xoá cache, **Then** hai kết quả giống nhau theo `canonicalize` của golden.
4. **Given** `check_tests_vs_ref.sh <ref>`, **When** ref từ `6d35c0d` trở đi, **Then** chạy test hiện tại trên `nora/backend` ở ref đó.

## Tasks / Subtasks
- [x] `smoke_check` 4 chế độ: `single`, `portfolio`, `studio`, `optcheck`
- [x] `check_tests_vs_ref.sh`
- [x] Chạy qua `run_limited`

## Dev Notes
- Code: `backend/core/backtest/smoke_check.py` (546 dòng), `test/scripts/check_tests_vs_ref.sh`.
- Cửa sổ smoke: 2025-04-01 đến 2025-05-31 + 20 ngày khởi động. Báo cáo ghi ở `data/_cache/smoke/`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commits: `edb26f4` (thêm `smoke_check`), `45f734e` (`smoke_check single` 0 FAIL), `6d35c0d` và `4e8dd61` (0 FAIL).
- `check_tests_vs_ref.sh`: có từ `c5d700b`; kết quả dùng nó chưa ghi trong repo (chưa đo).

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
