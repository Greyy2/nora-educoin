# E3-S2: Phí taker/maker theo venue, funding và thanh lý perp

- **Epic:** E3 Engine backtest, vốn & rủi ro
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn chi phí và rủi ro thanh lý perp được mô phỏng đúng, để lãi backtest đã trừ phí, funding và có thể mất tới hết ký quỹ.

## Acceptance Criteria

1. **Given** lệnh nhiều tầng, **When** đóng vị thế, **Then** phí tính ở từng tầng và lúc thoát, taker cho market và maker cho limit (`test_fees_charged_on_every_layer_and_exit`).
2. **Given** venue và thị trường, **When** dựng tham số, **Then** mặc định đúng bảng `VENUE_COSTS` (CEX perp 0,05%/0,02% + trượt 0,02%) (`test_friction_model_by_venue`).
3. **Given** funding dương, **When** giữ vị thế qua mốc funding, **Then** long trả và short nhận, hạch toán vào vốn (`test_funding_paid_by_long_received_by_short`).
4. **Given** giá chạm giá thanh lý, **When** mô phỏng perp, **Then** lỗ bị chặn ở ký quỹ + phí (`test_perp_liquidation_caps_loss_at_margin`).
5. **Given** spot, **When** cấu hình SHORT hoặc đòn bẩy > 1, **Then** bị từ chối (`test_spot_rejects_short_and_leverage`).
6. **Given** `market="perp"` và có dữ liệu `@perp`, **When** backtest, **Then** dùng giá perp và funding thật (`test_perp_symbol_uses_perp_prices_and_funding`).

## Tasks / Subtasks

- [x] `VENUE_COSTS`, `resolve_costs`
- [x] `apply_funding` mỗi mốc funding
- [x] `_liq_price` long/short với `mmr = 0,005`
- [x] Phí thanh lý taker, không trượt

## Dev Notes

- Code: `backend/core/backtest/params_builder.py`, `execution.py`. Đặc tả: `architecture.md` §5.2.
- Giả định: phí VIP0 (không BNB), trượt 0,02% mỗi chiều cố định; chưa đối soát với sàn thật (E9-S6).

## Evidence

- Commit: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code).
- Tests: `test/test_signals_strategies.py`, `test/test_capital_ledger.py`, `test/test_round4_venue_and_fills.py`, `test/test_optimization_plumbing.py`.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
