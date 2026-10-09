# Story E21-S5: G5 - Sizing theo rủi ro, trần notional và kill switch (S13c)

## Status
Backlog

## Story
Là quant researcher, tôi muốn đối chiếu chính sách định cỡ vị thế theo mức rủi ro (risk sizing), trần danh nghĩa (max notional pct) và cơ chế ngắt mạch khẩn cấp (kill switch) giữa Nora và NautilusTrader, để đảm bảo tính an toàn vốn cấp danh mục.

## Acceptance Criteria
1. Nora áp dụng `sizing="risk"` (khối lượng theo `risk_per_trade_pct * equity / khoảng_SL`), `max_notional_pct`, `max_capital_usage` và kill switch danh mục.
2. Nautilus ánh xạ công thức tính khối lượng từ equity tài khoản Nautilus (`portfolio.account.balance_total`) khớp với equity dùng của Nora (realized hoặc MTM).
3. Kill switch dừng vào lệnh khi mức sụt vốn danh mục chạm ngưỡng quy định, thời điểm dừng giữa hai hệ thống khớp nhau.
4. Sai số khớp từng lệnh đạt chuẩn quy ước: khối lượng rel < 1e-7, vốn < 1e-3.

## Tasks / Subtasks
- [ ] Ánh xạ công thức risk-based sizing từ Nora sang Nautilus strategy (AC: 1, 2)
- [ ] Cài đặt cơ chế kiểm tra kill switch danh mục trong Nautilus (AC: 3)
- [ ] So sánh lịch sử lệnh và thời điểm ngắt giao dịch (AC: 4)

## Dev Notes
- Tham chiếu: `nora/docs/bmad/archive/p13_nautilus_gaps_plan.md` mục G5 (S13c).
- Code Nora: `backend/core/position_size.py` (`admit_entry`, `kill_triggered`, `RiskConfig`).

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
