# Story E1-S2: Bố cục dữ liệu theo venue, ký hiệu @perp và manifest

## Status
Done

## Story
Là người nghiên cứu, tôi muốn một nơi duy nhất quyết định đường dẫn dữ liệu và cách đọc ký hiệu, để không bao giờ chạy nhầm spot thay cho perp hay đoán sai tài sản.

## Acceptance Criteria
1. **Given** ký hiệu `BTC@perp`, **When** phân giải, **Then** luôn trỏ tới `cex/BTC/perp`, không bao giờ rơi về thư mục spot (`test_instrument_symbol_never_falls_back_to_spot`).
2. **Given** tên tài sản có ở cả cex và dex, **When** gọi không tiền tố, **Then** báo lỗi yêu cầu `cex:`/`dex:` (`test_ambiguous_symbol_requires_venue`).
3. **Given** thư mục bắt đầu bằng `_` hoặc `.`, **When** liệt kê tài sản, **Then** bị bỏ qua (`test_listing_skips_meta_cache_archive`).
4. **Given** chỉ đọc dữ liệu, **When** gọi hàm đường dẫn, **Then** không tạo thư mục nào (`test_reading_never_creates_directories`).
5. **Given** biến môi trường `NORA_LOCAL_DATA_ROOT`, **When** mọi module tính đường dẫn, **Then** dùng đúng một gốc (`test_data_root_env_is_single_source`).

## Tasks / Subtasks
- [x] Bố cục `data/cex/<SYM>[/perp]`, `data/dex/<SYM>`
- [x] `resolve_asset_dir`, `split_instrument`, `list_assets`, `cache_dir`
- [x] Manifest chuẩn (`venue`, `sha256_1m`, `coverage_days`, `filled_ratio_1m`...)
- [x] Tài liệu `docs/data_layout.md`

## Dev Notes
- Code: `backend/db/data_layout.py` (đường dẫn), `backend/db/local_pkl.py` (đọc pkl, manifest), `backend/db/tick_storage.py`.
- Khi thiếu dữ liệu perp, `params_builder.data_symbol` trả `spot_proxy` và kết quả ghi `price_source`/`funding_modeled=false`; không âm thầm.
- Thư mục dữ liệu và cache không commit, trừ `data/alphas/` (xem `.gitignore`).

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code); chuyển vào `backend/db/` ở `6d35c0d` (`git mv`, không đổi hành vi).
- Tests: `test/test_data_layout.py` (11 test, gồm `test_simulate_and_wfa_work_on_venue_layout`, `test_datasets_endpoint_reports_venue`).
- Dữ liệu hiện có: `data/cex/{ADA,AVAX,BNB,BTC,DOGE,ETH,SOL,XRP}` (spot + perp), `data/dex/{AERO,VVV}`.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
