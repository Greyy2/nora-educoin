# Story E21-S8: G8 - Live/paper KernelBook từng bước = batch = Nautilus (S15)

## Status
Backlog

## Story
Là quant researcher, tôi muốn đối chiếu engine thực thi live/paper bar-by-bar (`KernelBook.step_bar`) với chế độ PortfolioEngine batch và NautilusTrader, để chứng minh bot chạy realtime thực tế cho kết quả đồng nhất với kết quả backtest và chuẩn Nautilus.

## Acceptance Criteria
1. Chạy các kịch bản S9 (đa khung) và S11 (DCA đa tầng) qua `KernelBook.step_bar` từng bước một giống như môi trường bot live.
2. Kiểm tra tính tương đương kết quả giữa chế độ step-by-step của KernelBook với chế độ chạy batch của PortfolioEngine.
3. Đối chiếu trực tiếp kết quả chạy step-by-step với NautilusTrader.
4. Sai số khớp từng lệnh đạt chuẩn: giá rel < 1e-9, khối lượng rel < 1e-7, vốn < 1e-3.

## Tasks / Subtasks
- [ ] Thiết lập test harness S15 chạy KernelBook step-by-step (AC: 1)
- [ ] Đối chiếu parity giữa KernelBook step và PortfolioEngine batch (AC: 2)
- [ ] So sánh với kết quả đối chứng của NautilusTrader (AC: 3, 4)

## Dev Notes
- Tham chiếu: `nora/docs/bmad/archive/p13_nautilus_gaps_plan.md` mục G8 (S15).
- Code Nora: `KernelBook.step_bar` (live/paper bot), `test_kernel_step_parity`.

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
