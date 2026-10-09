# Story E21-S4: G4 - Thanh lý (liquidation) và sụt ký quỹ (S13b)

## Status
Backlog

## Story
Là quant researcher, tôi muốn đối chiếu cơ chế thanh lý bắt buộc (Liquidation) và quản lý ký quỹ duy trì (Maintenance Margin) giữa Nora và NautilusTrader, để kiểm chứng mô hình bảo vệ tài khoản khi đòn bẩy cao.

## Acceptance Criteria
1. Nora tính toán giá thanh lý theo `maintenance_margin_rate`, tỷ lệ đòn bẩy và chế độ Isolated Margin.
2. Nautilus áp dụng `MarginAccount` / `MarginModel` hoặc đặt lệnh STOP_MARKET reduce-only tại giá thanh lý của Nora nếu backtest Nautilus không tự kích hoạt thanh lý.
3. Kịch bản kiểm thử đòn bẩy 10–20x với biến động giá cực đoan kích hoạt thanh lý.
4. Đối chiếu thời điểm, khối lượng, giá và số dư còn lại sau thanh lý giữa hai bên.

## Tasks / Subtasks
- [ ] Rà soát cơ chế thanh lý của NautilusTrader rc7 (AC: 1, 2)
- [ ] Thiết lập test case biến động mạnh gây cháy tài khoản đòn bẩy 10-20x (AC: 3)
- [ ] So sánh đối chiếu số dư và lịch sử lệnh thanh lý (AC: 4)

## Dev Notes
- Tham chiếu: `nora/docs/bmad/archive/p13_nautilus_gaps_plan.md` mục G4 (S13b).
- Code Nora: `backend/core/position_size.py` (`liq_price`, kernel liquidation path).

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story đang ở backlog.
- **File List:** `nora/test/scripts/nautilus_diff/`

## QA Results
- **Gate:** PENDING
- Chưa áp dụng: story chưa làm.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-09 | Tạo story từ kế hoạch P13, trạng thái `backlog`. |
