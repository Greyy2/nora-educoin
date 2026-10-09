# Story E21-S2: G2 - Khớp limit qua mức limit_through_pct > 0 (S13)

## Status
Backlog

## Story
Là quant researcher, tôi muốn đối chiếu hành vi khớp lệnh Limit khi giá xuyên qua mức một khoảng `limit_through_pct > 0` giữa Nora và NautilusTrader, để đảm bảo tính thực tế của lệnh chờ trong môi trường trượt giá và thanh khoản mỏng.

## Acceptance Criteria
1. Nora kiểm tra đường đi intrabar 1m đi qua mức giới hạn cộng thêm `limit_through_pct` (TP, các tầng DCA).
2. Nautilus ánh xạ tương đương thông qua cấu hình `FillModel(prob_fill_on_limit=...)`, `bar_execution` hoặc chiến lược shadow ledger.
3. Kiểm thử với các mức `limit_through_pct` (0.05%, 0.2%) cho cả chốt lời TP và dồn lệnh DCA.
4. Sai số khớp từng lệnh đạt chuẩn: giá rel < 1e-9, khối lượng rel < 1e-7, vốn < 1e-3.

## Tasks / Subtasks
- [ ] Xác minh cấu hình khớp lệnh limit trong Nautilus rc7 (AC: 1, 2)
- [ ] Xây dựng kịch bản S13 TP limit và DCA qua mức through pct (AC: 3)
- [ ] Chạy kiểm thử đối chiếu và xác nhận sai số (AC: 4)

## Dev Notes
- Tham chiếu: `nora/docs/bmad/archive/p13_nautilus_gaps_plan.md` mục G2 (S13).
- Code Nora: `backend/core/backtest/engine.py` (`_intrabar`, `_layer_cost`, `params.limit_through_pct`).

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
