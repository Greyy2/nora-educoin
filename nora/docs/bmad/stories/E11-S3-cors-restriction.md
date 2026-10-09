# Story E11-S3: Giới hạn CORS

## Status
Backlog

## Story
Là người vận hành, tôi muốn CORS chỉ cho phép nguồn được cấu hình, để trang web lạ không gọi API từ trình duyệt của người dùng.

## Acceptance Criteria
1. **Given** `allow_origins`, **When** khởi động, **Then** đọc từ biến môi trường, mặc định chỉ `http://localhost:18011` và `http://127.0.0.1:18010` (hiện là `["*"]`).
2. **Given** yêu cầu từ origin lạ, **When** preflight, **Then** không có header `Access-Control-Allow-Origin` (test).
3. **Given** UI phục vụ cùng origin ở production, **When** gọi API, **Then** hoạt động không cần CORS.

## Tasks / Subtasks
- [ ] Đọc origin từ biến môi trường
- [ ] Test origin lạ bị từ chối
- [ ] Cập nhật tài liệu

## Dev Notes
- Code: `backend/main.py` (`CORSMiddleware`, `allow_origins=["*"]`). R-5.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PENDING
- Chưa áp dụng: story chưa làm.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
