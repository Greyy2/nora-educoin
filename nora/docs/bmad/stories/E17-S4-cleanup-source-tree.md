# Story E17-S4: Loại bỏ module cũ, dead code và đồng bộ source-tree.md

## Status
Done

## Story
**Là** lập trình viên duy trì dự án, **tôi muốn** dọn dẹp toàn bộ code cũ (MySQL/Mongo legacy, đường dẫn `api/`, `core/execute/`) và đồng bộ cây mã nguồn vào `source-tree.md`, **để** kiến trúc trong tài liệu và code thực tế khớp nhau 100%.

## Acceptance Criteria
1. Xóa bỏ hoặc cô lập toàn bộ các module legacy không còn sử dụng.
2. Không còn bất kỳ tham chiếu nào trong code active tới `api/` cũ hoặc MySQL models.
3. Tài liệu `architecture/source-tree.md` phản ánh chính xác từng file trong `backend/`, `data/`, `frontend/`, `ops/`.
4. Kiểm tra ops units và layering không bị duplicate symbols.

## Tasks / Subtasks
- [x] Rà soát và gỡ bỏ dead code (AC: 1, 2)
- [x] Tạo `architecture/source-tree.md` mô tả 1 dòng/file (AC: 3)
- [x] Kiểm tra chéo giữa filesystem và tài liệu (AC: 4)

## Dev Notes
- Tài liệu tham chiếu: [source-tree.md](../architecture/source-tree.md).
- Testing: `test/test_ops_units.py`, `test/test_layering.py`, `test/scripts/p9_ledger.py`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Hoàn tất dọn dẹp và lập bảng cây mã nguồn chi tiết.
- **File List:**
  - `nora/docs/bmad/architecture/source-tree.md`
  - `backend/`

## QA Results
- **Gate:** PASS
- **Commit:** `4b95028`, `543e7b3`
- **Tests:**
  - `pytest test/test_ops_units.py` PASS
  - `pytest test/test_layering.py` PASS
  - `python -m test.scripts.p9_ledger --dups` = 0 duplicate symbols

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-07 | 1.0.0 | Xóa dead code và cập nhật source-tree | BMAD Dev |
| 2026-10-09 | 1.0.1 | Cập nhật QA Results với commit và test thực tế | BMAD Dev |
