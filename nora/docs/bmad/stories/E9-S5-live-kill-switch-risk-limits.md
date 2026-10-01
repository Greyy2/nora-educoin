# E9-S5: Kill switch và giới hạn rủi ro trên tài khoản thật

- **Epic:** E9 Testnet & Live
- **Trạng thái:** backlog
- **Cập nhật:** 2026-10-01

## Story

Là người vận hành, tôi muốn kill switch 30% và các giới hạn danh mục áp dụng trên tài khoản thật như đã mô phỏng, để thua lỗ thật không vượt ngân sách đã chốt.

## Acceptance Criteria

1. **Given** vốn MTM sụt ≥ 30% từ đỉnh (điểm xấu nhất), **When** bot đang chạy, **Then** đóng mọi vị thế bằng MARKET, huỷ lệnh chờ và ngừng mở lệnh mới tới khi người vận hành bật lại thủ công.
2. **Given** `RiskConfig` (8 vị thế, 1/tài sản, tổng danh nghĩa ≤ 3x vốn), **When** có tín hiệu vượt giới hạn, **Then** lệnh bị chặn hoặc thu nhỏ như `PortfolioEngine`.
3. **Given** kill switch kích hoạt, **When** xem trang Danh mục, **Then** có sự kiện mức `crit` và `halted_at`.
4. **Given** kịch bản giả lập giá giảm mạnh trên testnet, **When** chạy, **Then** kill switch kích hoạt trước khi vốn mất quá ngưỡng cộng độ trễ khớp lệnh (ghi số đo).

## Tasks / Subtasks

- [ ] Bộ theo dõi vốn MTM của tài khoản
- [ ] Đóng khẩn cấp và khoá bot
- [ ] Áp giới hạn danh mục
- [ ] Thử trên testnet trước khi bật live

## Dev Notes

- Logic mẫu: `PortfolioEngine._halt`, `RiskConfig` (`architecture.md` §6.1). Độ trễ thực của kill switch chưa đo (R-8).
- Q-2 (ngân sách rủi ro thật) cần chủ sở hữu quyết trước.

## Evidence

- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
