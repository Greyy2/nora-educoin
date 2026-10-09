# Story E18-S4: Tích hợp Studio Editor và trang Education trên giao diện web

## Status
Done

## Story
**Là** người dùng Nora, **tôi muốn** có giao diện Studio Editor trực tiếp trên web để viết, kiểm tra cú pháp, và trang Education để xem giải thích mã nguồn các chiến lược mẫu, **để** trải nghiệm nghiên cứu liền mạch mà không cần mở IDE bên ngoài.

## Acceptance Criteria
1. Trang `/alpha/create` (Studio Editor) tích hợp trình soạn thảo code, nút Validate gọi API validator và hiển thị trạng thái `RUN / ADAPT / REJECT`.
2. Trang `/education` hiển thị danh mục 50+ chiến lược mẫu, hỗ trợ lọc theo loại chiến lược.
3. Trang Education hiển thị docstrings tiếng Anh giải thích mã nguồn và bảng tham số mẫu bên phải, ẩn bớt thanh công cụ backtest nặng.
4. Tour hướng dẫn 5 bước, chú thích `# ▸`, nút Lưu bản nháp hoạt động ổn định.

## Tasks / Subtasks
- [x] Xây dựng component Code Editor và tích hợp với API Validator (AC: 1)
- [x] Xây dựng trang Education với danh mục chiến lược và docstrings viewer (AC: 2, 3)
- [x] Tinh chỉnh UI Education (tour 5 bước, ẩn các mục backtest nặng) (AC: 4)

## Dev Notes
- Tài liệu tham chiếu: [ux-design.md](../ux-design.md), [api-spec.md](../architecture/api-spec.md).
- File triển khai: `frontend/src/pages/Studio.jsx`, `frontend/src/components/studio/`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Hoàn thành giao diện Studio Editor và Education mode. Đã commit toàn bộ UI tour và chú thích.
- **File List:**
  - `frontend/src/pages/Studio.jsx`
  - `frontend/src/components/studio/`

## QA Results
- **Gate:** PASS
- **Commit:** `543e7b3`, `f4864d5`, `0c7f22f`
- **Tests:**
  - `cd frontend && npm run build` PASS
  - Playwright E2E test trên 11 routes đạt 0 lỗi console

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-07 | 1.0.0 | Hoàn tất tích hợp Studio Editor và Education | BMAD Dev |
| 2026-10-09 | 1.0.1 | Chuyển sang Review, cập nhật commit và test thực tế | BMAD Dev |
| 2026-10-09 | 1.0.2 | Hoàn tất nghiệm thu, chuyển sang Done với commit `0c7f22f` | BMAD Dev |
