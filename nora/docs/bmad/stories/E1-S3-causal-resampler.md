# E1-S3: Resample causal từ 1m, idempotent

- **Epic:** E1 Dữ liệu thị trường
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn mọi khung 5m, 15m, 1h, 4h, 24h được resample từ một nguồn 1m duy nhất theo quy ước UTC cố định, để các khung khớp nhau và không có nến nào dùng dữ liệu tương lai.

## Acceptance Criteria

1. **Given** chuỗi 1m có phút thiếu, **When** điền khoảng trống hai lần liên tiếp, **Then** kết quả giống hệt lần một và `filled_ratio` không đổi (`test_fill_idempotent_filled_ratio`, `test_fill_idempotent_no_extra_filled`).
2. **Given** phút điền (`is_filled=1`) và dữ liệu thật về sau, **When** hợp nhất, **Then** dữ liệu thật thay phút điền (`test_real_data_replaces_filled`).
3. **Given** lưu resample hai lần, **When** so manifest, **Then** hai manifest giống nhau (`test_save_resampled_twice_same_manifest`).
4. **Given** file crawl cũ còn dòng điền, **When** crawler đọc lại, **Then** dòng điền bị loại trước khi ghép (`test_crawler_strips_filled_from_existing`, `test_read_pickle_if_usable_drops_filled_rows`).

## Tasks / Subtasks

- [x] Resample theo UTC, `label=left`, `closed=left`, 4h neo 00:00 UTC
- [x] Điền phút thiếu bằng close trước, volume 0, `is_filled=1`
- [x] Ghi số dòng từng khung và `sha256_1m` vào manifest

## Dev Notes

- Code: `backend/core/data/resampler.py`. Khung cho phép: 5m, 15m, 30m, 1h, 2h, 4h, 24h (1d = 24h); engine dùng 1m, 5m, 15m, 1h, 4h, 24h.
- Engine bỏ qua nến `is_filled=1` khi khớp lệnh; kernel 1m chỉ tính trên phút có giao dịch (xem E2-S1).

## Evidence

- Commit: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code).
- Tests: `test/test_resampler_idempotent.py` (5 test).
- Dữ liệu perp 3 năm: `filled_ratio_1m = 0.0` (SOL perp); DEX chưa đo lại trong đợt này.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
