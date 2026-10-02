# E11-S1: API chỉ nghe localhost theo mặc định

- **Epic:** E11 Bảo mật & phát hành
- **Trạng thái:** backlog
- **Cập nhật:** 2026-10-01

## Story

Là người vận hành, tôi muốn API mặc định chỉ nghe `127.0.0.1`, để không ai trong mạng gọi được job nặng hay `publish` khi chưa có lớp bảo vệ.

## Acceptance Criteria

1. **Given** unit `nora-api.service`, **When** cài mới, **Then** `NORA_API_HOST=127.0.0.1` (hiện là `0.0.0.0`).
2. **Given** API đang chạy, **When** chạy `ss -ltn` trên máy, **Then** cổng 18010 chỉ gắn `127.0.0.1`.
3. **Given** máy khác trong mạng, **When** truy cập `http://<ip>:18010/api/health`, **Then** bị từ chối kết nối.
4. **Given** cần mở rộng, **When** đặt `NORA_API_HOST` khác, **Then** vẫn nghe theo biến (không khoá cứng).

## Tasks / Subtasks

- [ ] Đổi mặc định trong `nora-api.service.in`
- [ ] Cập nhật `nora/start.sh` và tài liệu (`backend/utils/ops/README.md`)
- [ ] Cập nhật `vite.config.js` nếu cần (dev đang `host: 0.0.0.0`)
- [ ] Kiểm bằng `ss -ltn`

## Dev Notes

- R-5, NFR-9. Hiện `NORA_API_HOST=0.0.0.0` trong unit; CORS `*` (E11-S3).
- Phải xong trước hoặc cùng E11-S2 nếu muốn truy cập từ xa.

## Evidence

- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
