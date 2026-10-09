# Story E21-S7: G7 - Engine tick và AMM cho DEX (S14)

## Status
Backlog

## Story
Là quant researcher, tôi muốn đối chiếu engine khớp lệnh mức tick và mô hình AMM DEX (Uniswap v2 constant-product x*y=k, stable-swap Curve) giữa Nora và mô phỏng trên nền NautilusTrader, để kiểm chứng mô hình backtest giao dịch phi tập trung.

## Acceptance Criteria
1. Lớp 1 (Toán AMM): Đối chiếu hàm tính toán `amm_amount_out` và `price_impact` với thư viện tham chiếu độc lập trên lưới đầu vào đa dạng, đạt độ chính xác tới sai số 1e-12.
2. Lớp 2 (Luồng lệnh): Mô phỏng luồng lệnh DEX trên Nautilus sử dụng TradeTick từ swap thực tế; giá khớp lệnh tính theo mô hình AMM sau trượt giá (shadow ledger).
3. Đối chiếu thời điểm, giá khớp, phí swap và chi phí gas giữa Nora `run_tick` và NautilusTrader.
4. Xây dựng bộ test S14a (toán AMM) và S14b (luồng lệnh pool đơn lẻ) đạt chuẩn baseline.

## Tasks / Subtasks
- [ ] Xây dựng bộ so sánh toán AMM độc lập S14a (AC: 1)
- [ ] Thiết lập harness luồng lệnh Nautilus TradeTick S14b (AC: 2)
- [ ] Đối chiếu thời điểm, giá và phí với Nora tick engine (AC: 3, 4)

## Dev Notes
- Tham chiếu: `nora/docs/bmad/archive/p13_nautilus_gaps_plan.md` mục G7 (S14).
- Code Nora: `backend/core/backtest/engine.py` (`_amm_out_raw`, `_amm_price_impact_raw`, `reserve_price`), `backend/optimize/search/evaluate.py` (`run_tick`, `TickBook`).

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
