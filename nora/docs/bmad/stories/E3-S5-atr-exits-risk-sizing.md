# E3-S5: Thoát theo ATR và khối lượng theo rủi ro, trần đòn bẩy 1,5 × SL

- **Epic:** E3 Engine backtest, vốn & rủi ro
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn SL/TP/trailing tính theo bội số ATR và khối lượng sao cho chạm SL chỉ mất đúng một phần vốn đã định, để một bộ tham số dùng được cho mọi tài sản.

## Acceptance Criteria

1. **Given** `sizing="risk"` và `risk_per_trade_pct=r`, **When** lệnh chạm SL, **Then** lỗ ≈ r% vốn (`test_atr_exits_and_risk_sizing_lose_exactly_risk_at_stop`) và đã gồm phí khứ hồi + trượt (`test_risk_sizing_includes_round_trip_costs`).
2. **Given** perp và SL, **When** chọn đòn bẩy, **Then** giá thanh lý cách giá vào ≥ 1,5 lần khoảng SL (`test_leverage_is_lowered_so_liquidation_stays_beyond_stop`).
3. **Given** `exit_unit="atr"`, **When** có tín hiệu, **Then** ATR lấy từ nến khung `atr_frame` đã đóng tại thời điểm tín hiệu (`test_engine_atr_unit_comes_from_closed_bar_at_signal`).
4. **Given** chưa đủ nến ATR, **When** có tín hiệu, **Then** bỏ tín hiệu và đếm `skipped_no_vol` (`test_atr_entry_skipped_during_warmup`).
5. **Given** `sizing="risk"` mà `stop_loss_rate=0`, **When** dựng tracker, **Then** `ValueError` (`test_risk_sizing_requires_stop_loss`).

## Tasks / Subtasks

- [x] `_apply_exit_unit`, `pending_vol` từ `natr_<period>`
- [x] `_risk_margin` và đòn bẩy thực
- [x] `max_notional_pct` và `max_new_notional` từ danh mục

## Dev Notes

- Code: `backend/core/backtest/execution.py`. Công thức: `architecture.md` §5.3-5.4.
- Đòn bẩy tham số trần 10 (`MAX_LEVERAGE`); đòn bẩy thực thường thấp hơn khi SL rộng.

## Evidence

- Commit: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code).
- Tests: `test/test_portfolio_engine.py` (6 test đầu danh sách trên).

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
