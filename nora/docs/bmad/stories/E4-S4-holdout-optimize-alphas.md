# Story E4-S4: Quy trình tối ưu trung thực: dev1, WFA dev2, MC, holdout

## Status
Done

## Story
Là người nghiên cứu, tôi muốn một quy trình cố định chia dữ liệu theo thời gian và chấm holdout một lần, để một alpha chỉ được công nhận khi qua đủ bốn giai đoạn.

## Acceptance Criteria
1. **Given** manifest một tài sản, **When** tính cửa sổ, **Then** `dev1_end = start + 40%`, `holdout = start + 80%` và seed cố định tái lập mẫu cấu hình (`test_optimizer_windows_and_sampling_are_honest`).
2. **Given** không cặp nào qua, **When** kết thúc, **Then** báo "không có" và không nới gate (`verdict` ∈ `KHONG_DAT`, `LOAI_O_SANG_LOC`).
3. **Given** alpha qua WFA, MC ruin ≤ 5%, holdout > 0, MDD ≤ 30%, đủ lệnh và đòn bẩy ≤ 10, **When** gộp, **Then** `verdict="ALPHA"`; thiếu một điều kiện thì không.
4. **Given** một thư mục kết quả tối ưu, **When** chạy `smoke_check optcheck --run <thư mục>`, **Then** kiểm cấu trúc `results.json`, các fold và gate rồi in số FAIL (bước kiểm thủ công; chưa có bản ghi lần chạy gần nhất).

## Tasks / Subtasks
- [x] Sàng lọc dev1 (top-8, MDD ≤ 30%, đủ lệnh)
- [x] WFA dev2 từ đúng cuối dev1
- [x] MC ngày (`run_monte_carlo` trên lợi suất ngày OOS) 2000 mô phỏng, block 5, seed 7, số bước = số ngày OOS
- [x] Holdout với cấu hình WFA chọn nhiều nhất
- [x] Kết quả `results.json` mỗi lượt

## Dev Notes
- Code: `backend/optimize/optimize_alphas.py`. Chạy: `ops/run_limited.sh -- -m backend.optimize.optimize_alphas --n 60 --workers auto`. Đặc tả: `architecture.md` §8.1.
- Hiện chưa hiệu chỉnh đa kiểm định (E10-S1/S2) và holdout đã chấm nhiều lần (R-2).

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commits: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code), `45f734e` (cổng ruin theo MC ngày), `edb26f4`, `030c7f9` (`--workers auto`).
- Kết quả lượt `data/_cache/optimize/20260930_1728`: 34 cặp, 1 `ALPHA`, 23 `KHONG_DAT`, 10 `LOAI_O_SANG_LOC`. Lượt `20261001_1440` (SOL): `ALPHA`.
- Tests: `test/test_optimization_plumbing.py`, `test/test_golden_results.py::test_full_pipeline_stages_contracts_and_reproducibility`.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
