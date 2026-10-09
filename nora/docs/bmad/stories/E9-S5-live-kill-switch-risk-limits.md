# Story E9-S5: Kill switch và giới hạn rủi ro trên tài khoản thật

## Status
Review

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

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
**06/10/2026 — OKX demo.** Đỉnh vốn chỉ lấy từ vốn sàn đo được (trước đó state mới lấy vốn danh nghĩa 10.000 làm đỉnh -> demo 4.866 USDT
bị kill switch giả ngay bước đầu, `test_fresh_state_peak_comes_from_measured_equity_not_nominal_capital`). Thêm trần rủi ro mở
(`max_open_risk_pct`) và giảm khối lượng theo sụt vốn (`dd_throttle_pct`) như engine. AC3: trang Live hiện "đã dừng mở lệnh (kill switch)"
và các sự kiện `crit` / `warn` của lần chạy hiện tại (`test_live_trades_shows_halted_and_alerts_since_last_start`). Chưa: AC4 (đo độ trễ).

**04/10/2026.** Bot: vốn MTM sụt >= kill_switch_dd_pct (30%) từ đỉnh -> đóng hết MARKET, huỷ lệnh, cờ `halted` tới khi người vận hành
xoá; sự kiện `crit` (`test_kill_switch_closes_all_and_halts`). Giới hạn danh mục: 1 vị thế/tài sản, tối đa max_positions, tổng danh nghĩa <= 3× vốn.
Chưa: AC3 (hiển thị trên trang Danh mục — cần E9-S3) và AC4 (đo độ trễ trên testnet thật).


- Chưa áp dụng: story chưa làm.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
| 2026-10-04 | Bot sổ paper/testnet (backend/live) | 015f06c |
| 2026-10-06 | Sửa kill switch giả (đỉnh vốn từ sàn), hiện trạng thái dừng + cảnh báo trên trang Live. |
