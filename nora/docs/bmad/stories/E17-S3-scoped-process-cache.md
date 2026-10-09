# Story E17-S3: Cơ chế cache tiến trình scoped và dọn dẹp bộ nhớ tạm

## Status
Done

## Story
**Là** kỹ sư vận hành hệ thống, **tôi muốn** các tiến trình chạy nặng chỉ lưu cache trong thời gian chạy (scoped process cache) và tự động dọn dẹp khi kết thúc, **để** ngăn chặn tình trạng tràn đĩa và tràn RAM máy chủ dùng chung.

## Acceptance Criteria
1. Không ghi cache disk vĩnh viễn không kiểm soát vào thư mục gốc `_cache/` hay `data/_cache/`.
2. Cache trung gian chỉ lưu trong scoped temp directory gắn với `job_id` hoặc in-memory LRU có giới hạn dung lượng.
3. Khi job kết thúc (thành công hoặc thất bại), các file tạm được dọn dẹp tự động, trả mã 410 `EPHEMERAL_GONE` nếu truy cập cache đã dọn.
4. Tổng dung lượng đĩa của cache không bao giờ vượt quá ngưỡng an toàn.

## Tasks / Subtasks
- [x] Thay thế cơ chế cache disk cũ bằng scoped temp cache (AC: 1, 2)
- [x] Thêm hook cleanup tự động khi job hoàn tất (AC: 3)
- [x] Kiểm tra rà soát không còn cache rác tồn đọng (AC: 4)

## Dev Notes
- Tài liệu tham chiếu: [ADR-P9-backend-layout.md](../architecture/decisions/ADR-P9-backend-layout.md), [coding-standards.md](../architecture/coding-standards.md).
- File triển khai: `backend/optimize/`, `backend/routes/studio_routes.py`.
- Testing: `test/test_job_lifecycle.py`, `test/test_data_paths_p93b.py`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Đã xóa bỏ các disk cache không kiểm soát, cô lập theo lifecycle của worker.
- **File List:**
  - `backend/optimize/`
  - `backend/routes/studio_routes.py`
  - `test/test_job_lifecycle.py`

## QA Results
- **Gate:** PASS
- **Commit:** `3dd61f1`, `5f2a97e` (hỗ trợ 410 `EPHEMERAL_GONE`)
- **Tests:**
  - `pytest test/test_job_lifecycle.py` PASS
  - `pytest test/test_data_paths_p93b.py` PASS

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-07 | 1.0.0 | Triển khai scoped cache lifecycle | BMAD Dev |
| 2026-10-09 | 1.0.1 | Cập nhật QA Results với commit và test thực tế | BMAD Dev |
