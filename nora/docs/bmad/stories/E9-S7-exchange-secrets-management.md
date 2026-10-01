# E9-S7: Quản lý khoá API sàn

- **Epic:** E9 Testnet & Live
- **Trạng thái:** backlog
- **Cập nhật:** 2026-10-01

## Story

Là người vận hành, tôi muốn khoá API được lưu và nạp an toàn, để khoá không lọt vào repo, log hay payload API.

## Acceptance Criteria

1. **Given** khoá, **When** cấu hình, **Then** nằm ngoài repo (ví dụ `~/.config/nora/`, quyền 600) và được nạp qua `EnvironmentFile` của unit systemd.
2. **Given** log, payload API và `result.json`, **When** quét, **Then** không chứa khoá hay chữ ký (test quét mẫu).
3. **Given** khoá có quyền rút tiền, **When** nạp, **Then** từ chối khởi động.
4. **Given** `.gitignore`, **When** thêm file khoá, **Then** git bỏ qua (`.env`, `.env.*` đã có; kiểm đường dẫn mới).

## Tasks / Subtasks

- [ ] Chọn nơi lưu và quyền file
- [ ] Nạp qua unit systemd
- [ ] Test không rò khoá
- [ ] Hướng dẫn xoay khoá

## Dev Notes

- Unit API đã có `EnvironmentFile=-%h/.config/nora/nora.env` (`backend/ops/systemd/nora-api.service.in`).

## Evidence

- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
