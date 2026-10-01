# E11-S4: Tách bundle frontend (lazy route)

- **Epic:** E11 Bảo mật & phát hành
- **Trạng thái:** backlog
- **Cập nhật:** 2026-10-01

## Story

Là người dùng, tôi muốn trang đầu tải nhanh vì bundle được tách theo route, để không tải cả nhóm Legacy khi chỉ dùng ba trang v2.

## Acceptance Criteria

1. **Given** `npm run build`, **When** xem `dist/assets`, **Then** nhóm Legacy và mỗi trang v2 nằm trong chunk riêng nạp lười (`React.lazy`).
2. **Given** chunk đầu (shell + trang đầu), **When** đo, **Then** nhỏ hơn bundle hiện tại (≈ 583 KB chưa nén) và nhỏ hơn mục tiêu do chủ sở hữu đặt (đề xuất < 250 KB chưa nén).
3. **Given** điều hướng giữa các trang, **When** chuyển route, **Then** có trạng thái chờ rõ ràng, không trắng trang.
4. **Given** build, **When** chạy, **Then** không còn cảnh báo chunk lớn của Vite.

## Tasks / Subtasks

- [ ] Chuyển route sang `React.lazy`
- [ ] Đo kích thước trước/sau (ghi vào Evidence)
- [ ] Kiểm điều hướng

## Dev Notes

- R-9. Hiện một file `index-*.js` ≈ 583 KB và CSS 90 KB. Số gzip chưa đo lại.
- Phụ thuộc E8-S6 xong để tránh xung đột.

## Evidence

- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
