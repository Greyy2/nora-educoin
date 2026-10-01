# E11-S5: Dọn legacy: route MySQL cũ, trang Legacy, mã nghiên cứu DEX

- **Epic:** E11 Bảo mật & phát hành
- **Trạng thái:** backlog
- **Cập nhật:** 2026-10-01

## Story

Là người phát triển, tôi muốn `main.py` chỉ còn ghép app và các route/trang cũ được cô lập hoặc xoá, để dễ bảo trì và giảm bề mặt tấn công.

## Acceptance Criteria

1. **Given** `backend/main.py` (2261 dòng), **When** dọn, **Then** chỉ còn khởi tạo app, middleware, include router và phục vụ SPA (< 300 dòng).
2. **Given** route MySQL cũ (`/api/runs*`, `/api/miner/*`, `/api/strategies*`...), **When** dọn, **Then** hoặc chuyển vào router riêng bị tắt mặc định, hoặc xoá; chủ sở hữu quyết định từng nhóm.
3. **Given** các trang Legacy, **When** dọn, **Then** các trang không còn dùng bị xoá khỏi `App.jsx` và `Shell.jsx` kèm đường dẫn chuyển hướng.
4. **Given** thay đổi, **When** chạy `pytest` và golden, **Then** toàn bộ qua, golden không đổi; `GET /api/health` và các route `/api/studio/*` vẫn chạy.

## Tasks / Subtasks

- [ ] Liệt kê route/trang còn được dùng (cần xác nhận của chủ sở hữu)
- [ ] Tách hoặc xoá route MySQL
- [ ] Dọn trang Legacy
- [ ] Chạy test và golden

## Dev Notes

- R-9. Cần MySQL của hệ thống cũ để các route này chạy; test cũ có thể phụ thuộc (kiểm trước khi xoá).
- Nhớ giữ nhánh `except ImportError` hoặc dọn import `nora.backend...` trong `core/research`.

## Evidence

- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
