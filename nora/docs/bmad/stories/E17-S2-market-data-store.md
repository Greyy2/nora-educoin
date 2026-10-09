# Story E17-S2: Cấu trúc cây dữ liệu thống nhất và metadata attrs

## Status
Done

## Story
**Là** kỹ sư dữ liệu, **tôi muốn** tổ chức toàn bộ dữ liệu nến vào một cây thư mục thống nhất `data/market/<venue>/<market>/<symbol>/<timeframe>.pkl` kèm metadata (`sha256`, `coverage`, `filled_ratio`, `is_synthetic`) trong DataFrame attrs, **để** loại bỏ sự phân mảnh giữa các nguồn dữ liệu và truy xuất nhanh chóng.

## Acceptance Criteria
1. Dữ liệu nến được lưu dạng pickle nén tại `data/market/<venue>/<market>/<symbol>/<timeframe>.pkl`.
2. Mọi file `.pkl` đều chứa metadata chuẩn trong `df.attrs` (`sha256`, `coverage_days`, `filled_ratio`, `synthetic`).
3. Hỗ trợ đầy đủ các tài sản OKX/Binance perp.
4. Đọc dữ liệu chuẩn qua các helper layout, xác thực với golden results.

## Tasks / Subtasks
- [x] Thiết kế layout cây dữ liệu `data/market/` (AC: 1)
- [x] Tạo script migrate dữ liệu kèm nhúng metadata vào attrs (AC: 2)
- [x] Bổ sung dataset đầy đủ cho các tài sản (AC: 3)
- [x] Viết unit test xác thực định dạng và metadata (AC: 4)

## Dev Notes
- Tài liệu tham chiếu: [data-models.md](../architecture/data-models.md), [source-tree.md](../architecture/source-tree.md).
- File triển khai: `backend/core/data/`, `data/market/`.
- Testing: `test/test_data_layout_helpers.py`, `test/test_data_layout.py`, `test/test_data_paths_p93b.py`, `test/test_pkl_meta.py`, `test/test_golden_results.py`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Dữ liệu đã chuyển đổi sang cấu trúc chuẩn một cây `data/market/`.
- **File List:**
  - `data/market/`
  - `backend/core/data/`
  - `test/test_data_layout_helpers.py`

## QA Results
- **Gate:** PASS
- **Commit:** `3dd61f1`
- **Tests:**
  - `pytest test/test_data_layout_helpers.py` PASS
  - `pytest test/test_data_layout.py` PASS
  - `pytest test/test_data_paths_p93b.py` PASS
  - `pytest test/test_pkl_meta.py` PASS
  - `pytest test/test_golden_results.py` (với `NORA_GOLDEN_DATA_ROOT=data/market/binance`) PASS

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-07 | 1.0.0 | Hoàn tất chuẩn hoá dữ liệu market store một cây | BMAD Dev |
| 2026-10-09 | 1.0.1 | Cập nhật QA Results với commit và test thực tế | BMAD Dev |
