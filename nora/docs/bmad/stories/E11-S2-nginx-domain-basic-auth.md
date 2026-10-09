# Story E11-S2: Truy cập từ xa qua nginx: domain, TLS và basic auth

## Status
Backlog

## Story
Là người vận hành, tôi muốn truy cập UI từ xa qua một domain có TLS và basic auth, để chỉ người được cấp mới dùng được API và UI.

## Acceptance Criteria
1. **Given** nginx làm reverse proxy tới `127.0.0.1:18010`, **When** truy cập domain không có thông tin đăng nhập, **Then** nhận 401 cho cả trang và `/api`.
2. **Given** đăng nhập đúng, **When** dùng UI, **Then** vòng Alpha → Backtest → WFA → MC → Danh mục chạy bình thường (poll job không bị chặn).
3. **Given** HTTP, **When** truy cập, **Then** chuyển sang HTTPS.
4. **Given** cấu hình nginx, **When** xem repo, **Then** có mẫu cấu hình trong `ops/` (không chứa mật khẩu).

## Tasks / Subtasks
- [ ] Mẫu cấu hình nginx (TLS, basic auth, proxy, timeout cho job)
- [ ] Hướng dẫn tạo `htpasswd`
- [ ] Kiểm bằng `curl` (401/200)
- [ ] Ghi vào `ops/README.md`

## Dev Notes
- R-5. Cần domain và chứng chỉ do chủ sở hữu cung cấp (chưa có thông tin trong repo). Basic auth là mức tối thiểu; không thay thế xác thực trong ứng dụng nếu sau này có nhiều người dùng.
- Phụ thuộc E11-S1.

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
