# E3-S7: Dữ liệu dùng chung qua mmap và bỏ qua phút rảnh (bit-identical)

- **Epic:** E3 Engine backtest, vốn & rủi ro
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người vận hành, tôi muốn giảm RAM và thời gian của job nặng mà không đổi một bit kết quả, để chạy nhiều worker trong ngân sách 12 GB.

## Acceptance Criteria

1. **Given** dữ liệu một tài sản, **When** xuất ra mmap rồi tải lại, **Then** từng mảng bằng từng byte với dữ liệu dựng trực tiếp (`test_mmap_data_equals_built_data_bit_for_bit`).
2. **Given** file nguồn đổi (mtime/size), **When** tính khoá, **Then** khoá đổi, dữ liệu cũ không bao giờ được dùng (`test_key_changes_when_source_file_changes`).
3. **Given** engine có/không `shared_dir`, **When** chạy, **Then** kết quả giống nhau (`test_run_with_shared_dir_matches_run_without`, `test_golden_real_through_shared_mmap`).
4. **Given** bật/tắt bỏ qua phút rảnh, **When** chạy dữ liệu tổng hợp, thưa tín hiệu, có kill switch, có phút điền, dữ liệu thật, **Then** kết quả giống nhau từng bit (5 test `*_skip_equals_full_loop`).
5. **Given** `bar_hook` đặt, **When** chạy, **Then** skip-idle bị tắt (`test_skip_is_disabled_when_bar_hook_set`).

## Tasks / Subtasks

- [x] `shared_data.export/load`, khoá sha1, ghi nguyên tử
- [x] `_skip_idle` tái hiện funding, giá cuối và mẫu vốn theo giờ
- [x] Các CLI xuất mmap trước mỗi pool và dọn sau
- [x] `PER_WORKER_MB` 1700 → 800

## Dev Notes

- Code: `backend/core/backtest/shared_data.py`, `portfolio.py` (`_skip_idle`), `backend/cli/build_strategy_book.py`, `backend/wfa/portfolio_wfa.py`. Đặc tả: `architecture.md` §6.2-6.3.
- Khoá `None` khi nguồn là Mongo hoặc thiếu `1m.pkl`: không chia sẻ, rơi về đường dựng cũ.

## Evidence

- Commit: `b179f2b`.
- Đo (message commit): benchmark `trend_long`, 8 perp, n=14: 5 → 12 worker, RAM riêng 1315 → 142 MB mỗi worker, đỉnh slice 5950 → 2045 MB, thời gian 115 → 78 s; VmHWM 576-587 MB gồm mmap dùng chung (~440 MB mỗi giai đoạn).
- Cũ so mới cho `stage_b.json`/`report.json` giống từng byte với 14 cấu hình `trend_long`; bộ test đầy đủ 285 qua, golden 4/4.
- Tests: `test/test_shared_data.py` (4), `test/test_skip_idle.py` (6).

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
