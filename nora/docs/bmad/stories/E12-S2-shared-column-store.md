# E12-S2: Kho dữ liệu dùng chung mức cột/khung + điền lười trong worker

- **Epic:** E12 Tốc độ
- **Trạng thái:** done
- **Cập nhật:** 2026-10-03

## Story

Là người chạy job nhiều worker, tôi muốn nến, cột chỉ báo và chỉ số căn khung nằm trong kho mmap dùng chung, để mỗi worker không tự tính lại và RAM mỗi worker nằm trong ngân sách.

## Acceptance Criteria

1. **Given** pool nhiều worker, **When** chạy phễu 10k alpha ở 15m, **Then** RAM riêng mỗi worker ≤ 800 MB (đo ≤ 395 MB) và không OOM.
2. **Given** kho thiếu một cột, **When** worker cần cột đó, **Then** worker tự tính đúng phần thiếu và ghi lại cho worker khác (kết quả trùng bit với không dùng kho).

## Tasks

- [x] `core/data/shared.py` FORMAT_VERSION 5 (base/fv/ft/ix)
- [x] `optimize/shared.py` SharedExporter dùng chung cho sổ/WFA/phễu
- [x] Chỉ báo gốc cố định (fixed-origin) để khoá kho không phụ thuộc điểm nạp
- [x] memwatch không tính page cache inactive_file

## Dev Notes

Roadmap P1.8a–P1.8b, P1.11–P1.13. Lỗi 1,3 GB/worker cũ do kho chỉ theo chiến lược đại diện.

## Evidence

- Commit: `2d7eaed`, `2b7c5d8`, `dc8061c`, `8f97e33`, `1b30398`.
- Test: `test/test_shared_data.py`, `test/test_funnel.py::test_pool_mode_matches_serial_with_shared_data`.
- Số đo: roadmap P1.16/P1.17.

## Change Log

| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-03 | Tạo story ghi nhận P1.8–P1.13 | 1b30398 |
