# E9-S7: Quản lý khoá API sàn

- **Epic:** E9 Testnet & Live
- **Trạng thái:** done
- **Cập nhật:** 2026-10-06

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

- Unit API đã có `EnvironmentFile=-%h/.config/nora/nora.env` (`backend/utils/ops/systemd/nora-api.service.in`).

## Evidence

**06/10/2026 — OKX.** Khoá ở `~/.config/nora/okx.env` quyền 600 (từ chối nếu lỏng hơn); bot chạy như job API nên không dùng
`EnvironmentFile`. AC2: `redact` trên mọi dòng log / lỗi sàn. AC3: `OkxAdapter.check_account` từ chối khởi động khi `perm` của khoá có `withdraw`
(khoá demo hiện tại: `read_only,trade`). AC4: file khoá nằm ngoài repo.

**04/10/2026.** `live.secrets`: khoá từ biến môi trường hoặc `~/.config/nora/binance_testnet.env` (từ chối nếu quyền lỏng hơn 600);
`redact` trên mọi dòng log / lỗi sàn (`test_secrets_file_permissions_and_redaction`). Khoá testnet Binance Futures không có quyền rút tiền nên AC3
không kiểm được qua API testnet; nạp qua EnvironmentFile chưa làm (bot chạy như job API).



## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
| 2026-10-04 | Bot sổ paper/testnet (backend/live) | 015f06c |
| 2026-10-06 | OKX demo: trạng thái `done`. |
