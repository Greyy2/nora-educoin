# Story E17-S1: Phân tầng 5 lớp backend alpha -> core -> optimize -> live -> routes

## Status
Done

## Story
**Là** kiến trúc sư hệ thống, **tôi muốn** cấu trúc backend thành 5 phân tầng độc lập với quan hệ phụ thuộc 1 chiều nghiêm ngặt `alpha → core → optimize → live → routes`, **để** đảm bảo code sạch, không import ngược, không vòng lặp, và dễ bảo trì mở rộng.

## Acceptance Criteria
1. Backend phân thành 5 package chính: `backend.alpha`, `backend.core`, `backend.optimize`, `backend.live`, `backend.routes`.
2. `backend.core` hoàn toàn là domain logic thuần túy, không import từ `optimize`, `live`, hay `routes`, và không thực hiện disk/network I/O.
3. Không có circular imports giữa các module (`test_layering.py` với `NORA_LAYERING_STRICT=1` PASS).
4. Entrypoints API và CLI phân rã sạch sẽ, không có file monolith 2000+ dòng.

## Tasks / Subtasks
- [x] Tạo cây thư mục 5 phân tầng trong `backend/` (AC: 1)
- [x] Chuyển đổi và tinh gọn `backend/core/` thành pure logic (AC: 2)
- [x] Chạy kiểm tra layering strict (AC: 3)
- [x] Tách router studio ra khỏi `main.py` vào `backend/routes/` (AC: 4)

## Dev Notes
- Tài liệu tham chiếu: [ADR-P9-backend-layout.md](../architecture/decisions/ADR-P9-backend-layout.md), [components.md](../architecture/components.md), [coding-standards.md](../architecture/coding-standards.md).
- File triển khai: `backend/alpha/`, `backend/core/`, `backend/optimize/`, `backend/live/`, `backend/routes/`.
- Testing: `test/test_layering.py`, `test/test_ops_units.py`, `test/scripts/p9_ledger.py`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Hoàn thành phân tầng P9. Đã cô lập core engine khỏi I/O.
- **File List:**
  - `backend/alpha/`
  - `backend/core/`
  - `backend/optimize/`
  - `backend/live/`
  - `backend/routes/studio_routes.py`
  - `test/test_layering.py`

## QA Results
- **Gate:** PASS
- **Commit:** `3dd61f1`, `4b95028`
- **Tests:**
  - `pytest test/test_layering.py` (với `NORA_LAYERING_STRICT=1`) PASS
  - `pytest test/test_ops_units.py` PASS
  - `python -m test.scripts.p9_ledger --dups` = 0 duplicate symbols

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-07 | 1.0.0 | Tạo story và hoàn tất phân tầng 5 lớp theo P9 | BMAD Dev |
| 2026-10-09 | 1.0.1 | Cập nhật QA Results với commit và test thực tế | BMAD Dev |
