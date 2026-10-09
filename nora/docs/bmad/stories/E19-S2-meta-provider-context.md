# Story E19-S2: MetaProvider React Context nạp và phân phối metadata

## Status
Done

## Story
**Là** lập trình viên frontend, **tôi muốn** có một React Context Provider `CatalogProvider / MetaProvider` nạp metadata từ API một lần khi ứng dụng khởi động và cung cấp hook `useCatalog()` cho mọi component, **để** đảm bảo toàn bộ ứng dụng sử dụng dữ liệu thống nhất và mượt mà.

## Acceptance Criteria
1. `CatalogProvider` nạp dữ liệu từ `/api/studio/meta` khi mount và lưu vào React Context.
2. Cung cấp fallback loading state và xử lý lỗi khi backend chưa sẵn sàng.
3. Hook `useCatalog()` cho phép truy cập dễ dàng vào `symbols`, `timeframes`, `strategies`, `metrics`.
4. Kiểm thử frontend build thành công và vượt qua kiểm tra API contract `npm run api:check` (65/65).

## Tasks / Subtasks
- [x] Tạo `frontend/src/meta/MetaProvider.jsx` và custom hook (AC: 1, 2, 3)
- [x] Bọc `AppRoutes` trong `CatalogProvider` tại `frontend/src/App.jsx` (AC: 1)
- [x] Kiểm tra build và API check (AC: 4)

## Dev Notes
- Tài liệu tham chiếu: [ux-design.md](../ux-design.md).
- File triển khai: `frontend/src/meta/MetaProvider.jsx`, `frontend/src/App.jsx`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Hoàn thành MetaProvider và tích hợp vào root app.
- **File List:**
  - `frontend/src/meta/MetaProvider.jsx`
  - `frontend/src/App.jsx`

## QA Results
- **Gate:** PASS
- **Commit:** `f4864d5`
- **Tests:**
  - `cd frontend && npm run build` PASS
  - `cd frontend && npm run api:check` PASS (65/65 checks passed)

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-07 | 1.0.0 | Triển khai MetaProvider Context | BMAD Dev |
| 2026-10-09 | 1.0.1 | Cập nhật QA Results với commit và test thực tế | BMAD Dev |
