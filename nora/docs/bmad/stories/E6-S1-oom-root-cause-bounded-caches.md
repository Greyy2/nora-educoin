# Story E6-S1: Nguyên nhân OOM và cache giới hạn theo byte

## Status
Done

## Story
Là người vận hành, tôi muốn mọi cache có trần RAM theo byte và job tự giới hạn worker, để một lần build không còn làm sập cả máy dùng chung.

## Acceptance Criteria
1. **Given** `ByteLRU` với ngân sách byte, **When** thêm mục, **Then** loại mục ít dùng nhất theo byte, sổ byte luôn đúng kể cả khi thay khoá và dưới nhiều luồng (`test_byte_lru_evicts_least_recently_used_by_bytes`, `test_byte_lru_replacing_a_key_keeps_the_byte_ledger_right`, `test_byte_lru_ledger_stays_consistent_under_threads`).
2. **Given** một file nến, **When** đọc nhiều cửa sổ, **Then** chỉ chiếm RAM một lần; file được ghi lại thì cache hết hạn (`test_loader_caches_each_file_once_and_windows_match_fetch`, `test_loader_cache_expires_when_file_is_rewritten`).
3. **Given** nguồn Mongo, **When** nạp, **Then** luôn theo cửa sổ và không cache (`test_mongo_source_is_always_windowed_and_never_cached`).
4. **Given** build trên 8 perp, **When** chạy với cache giới hạn và worker tự chia, **Then** không OOM: 7 ứng viên × 24 cấu hình xong 487 s, đỉnh 2,5 GB.
5. **Given** cache dữ liệu theo tiến trình, **When** chuyển qua chiến lược khác, **Then** `data_cache_clear()` giải phóng; mỗi chiến lược một pool riêng thu hồi RAM khi pool đóng.

## Tasks / Subtasks
- [x] Xác định nguyên nhân: `_CANDLE_CACHE`, `_DATA_CACHE` không giới hạn × 10 worker
- [x] `ByteLRU` có khoá luồng (`backend/utils/lru.py`)
- [x] Cắt cửa sổ trước khi `.copy()` (`local_pkl`)
- [x] Pin BLAS = 1 luồng, checkpoint, memory gate
- [x] Đo VmHWM từng worker và ghi vào kết quả

## Dev Notes
- **Nguyên nhân gốc:** hai cache theo tiến trình (`_CANDLE_CACHE`, `_DATA_CACHE`) không giới hạn theo byte × 10 worker, và `.copy()` toàn lịch sử trước khi cắt cửa sổ làm đỉnh RAM ~3x (message `f2bfc1a`). Sau khi giới hạn cache, mỗi worker đo được 1280-1320 MB VmHWM (`407f51f`).
- Cache: `NORA_CANDLE_CACHE_MB` (1024; script đặt 512), `NORA_DATA_CACHE_MB` (1500; script đặt 1024); API unit đặt 512/512.
- Sau mmap: ~142 MB RAM riêng mỗi worker (E3-S7).

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commits: `f2bfc1a` (cache byte, pool riêng, checkpoint, memory gate), `e36a486` (ngân sách mỗi worker, `pool_map_safe` chỉ retry khi `BrokenProcessPool`, `ByteLRU` có khoá), `06ae13b` (đo 487 s / 2,5 GB).
- Tests: `test/test_memory_guards.py` (25 test); message `e36a486` ghi "not run yet", `407f51f` ghi 258 test qua dưới trần 4G (peak 868 MB).
- Giá trị `PER_WORKER_MB`: 1800 (ước) → 1700 (`407f51f`, đo 1280-1320 MB) → 800 (`b179f2b`, đo 576-587 MB).

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
