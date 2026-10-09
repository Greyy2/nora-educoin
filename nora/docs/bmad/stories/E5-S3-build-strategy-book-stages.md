# Story E5-S3: Dựng sổ chiến lược: giai đoạn A dev1, B dev2, C sổ, D holdout

## Status
Done

## Story
Là người nghiên cứu, tôi muốn một lệnh dựng sổ nhiều chiến lược với tham số chung cho cả vũ trụ và mức rủi ro chốt bằng bootstrap, để có sổ qua gate hoặc biết chắc là không có.

## Acceptance Criteria
1. **Given** các ứng viên, **When** chạy A, **Then** mỗi chiến lược thử `n` cấu hình trên cả 8 perp, điểm = lãi/max(MDD,1), đạt khi ≥ 40 lệnh, ≥ 5/8 tài sản có lãi, lãi > 0, MDD ≤ 30%; giữ top-3 (`test_book_pipeline_runs_all_stages_with_shared_params`).
2. **Given** top-1 của mỗi chiến lược, **When** chạy B, **Then** phải lãi ở cả SL "level" và "extreme", MDD ≤ 30%, ≥ 4/8 tài sản có lãi mới đạt; top-2/3 chỉ để đo `stability`.
3. **Given** bootstrap ngày dev2 (extreme) theo `RISK_SCALES`, **When** chốt rủi ro/lệnh, **Then** dùng hệ số lớn nhất có P(MDD ≥ 30%) ≤ 5%, trần 2,0%/lệnh.
4. **Given** không chiến lược nào đạt, **When** kết thúc, **Then** in "KHÔNG có chiến lược nào đạt — không tạo sổ (không nới gate)" và `report.book = None`.
5. **Given** job chạy không có trần RAM cgroup, **When** khởi động, **Then** từ chối chạy (`require_memory_limit`).
6. **Given** lỗi trong job, **When** pool chạy, **Then** lỗi nổi lên ngay (không che), chỉ khi worker bị kill mới chạy lại phần thiếu với nửa số worker.

## Tasks / Subtasks
- [x] Giai đoạn A-D với pool riêng mỗi chiến lược
- [x] Checkpoint `stage_a.json`, `stage_b.json`, `report.json`
- [x] `result.json` cho job API (có `stage_a` mọi cấu hình)
- [x] `--only`, `--n`, `--workers`, `--per-worker-mb`, `--out`
- [x] Chạy thật 7 ứng viên × 24 cấu hình

## Dev Notes
- Code: `backend/optimize/build_strategy_book.py`, `backend/core/strategy/strategy_book.py`. Đặc tả: `architecture.md` §8.2.
- Chạy: `ops/run_limited.sh -- -m backend.optimize.build_strategy_book --n 24` (từ `nora/`).
- Cửa sổ: `start = max(start_ts) + 20 ngày`, dev1 đến 40%, dev2 đến 80%, holdout 20% cuối.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commits: `f2bfc1a` (pool riêng, checkpoint, memory gate), `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code), `b179f2b` (mmap), `2d4698f` (`result.json`), `876ce9e` (`stage_a` đủ cấu hình).
- Đo (message `06ae13b`): full `build_strategy_book` 7 ứng viên × 24 cấu hình, 10 worker, **487 s, đỉnh 2,5 GB** — lần chạy trước đây làm sập máy.
- Đo (`836103b`): `--workers auto` chọn 5 worker, đỉnh 5657 MB trong ngân sách 12 GB (trước khi có mmap).
- Hiện vật: `data/_cache/book/20261001_115808` (7 ứng viên, có giai đoạn C-D), `..._152813` (chỉ `breakout_4h_long`, qua UI). Tests: `test/test_strategy_book.py`, `test/test_book_ui_backend.py`.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
