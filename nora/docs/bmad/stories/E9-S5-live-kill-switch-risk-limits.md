# E9-S5: Kill switch và giới hạn rủi ro trên tài khoản thật

- **Epic:** E9 Testnet & Live
- **Trạng thái:** review
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

**04/10/2026.** Bot: vốn MTM sụt >= kill_switch_dd_pct (30%) từ đỉnh -> đóng hết MARKET, huỷ lệnh, cờ `halted` tới khi người vận hành
xoá; sự kiện `crit` (`test_kill_switch_closes_all_and_halts`). Giới hạn danh mục: 1 vị thế/tài sản, tối đa max_positions, tổng danh nghĩa <= 3× vốn.
Chưa: AC3 (hiển thị trên trang Danh mục — cần E9-S3) và AC4 (đo độ trễ trên testnet thật).


- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
| 2026-10-04 | Bot sổ paper/testnet (backend/live) | 015f06c |
