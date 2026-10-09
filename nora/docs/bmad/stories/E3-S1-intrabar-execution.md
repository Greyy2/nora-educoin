# Story E3-S1: Khớp lệnh trong nến: phía bất lợi trước, gap, TP không cùng nến DCA

## Status
Done

## Story
Là người nghiên cứu, tôi muốn thứ tự khớp lệnh trong một nến luôn bi quan và có quy tắc rõ, để kết quả backtest không lạc quan hơn thị trường thật.

## Acceptance Criteria
1. **Given** tín hiệu vào ở nến t, **When** mô phỏng, **Then** lệnh vào khớp ở open của nến 1m có giao dịch kế tiếp (`test_entry_at_next_candle_open`, `test_pending_entry_waits_for_next_real_minute`).
2. **Given** open đã vượt mức SL, **When** nến mở, **Then** khớp ở open (gap) (`test_gap_through_sl_fills_at_open`).
3. **Given** nến vừa khớp tầng DCA, **When** giá cũng chạm TP, **Then** không chốt lời trong nến đó (`test_no_take_profit_in_same_bar_as_dca_fill`).
4. **Given** SL, trailing và DCA cùng nằm trong nến, **When** xử lý, **Then** theo đúng thứ tự giá chạm; sau fill DCA, SL CŨ còn hiệu lực đến hết nến, SL tính từ giá TB mới có hiệu lực từ nến sau (quy tắc bảo thủ 2026-10-06: `test_stale_stop_loss_after_dca_and_ordering`, `test_conservative_fills.py`).
5. **Given** `stop_fill="extreme"`, **When** SL chạm, **Then** khớp ở giá xấu nhất của nến (`test_stop_fill_extreme_uses_worst_price_of_bar`); giá trị lạ bị từ chối (`test_stop_fill_rejects_unknown_mode`).
6. **Given** trailing đang bật, **When** nến mới, **Then** dùng đỉnh/đáy của các nến trước (`test_trailing_stop_uses_previous_peak`); timeout đóng ở open (`test_timeout_closes_at_open`).

## Tasks / Subtasks
- [x] `PositionTracker.on_bar`/`_intrabar`
- [x] Ưu tiên thoát khi hai mức trùng nhau
- [x] `_gap_fill`
- [x] Đóng cuối dữ liệu ở open nến thật cuối (`test_final_close_uses_last_real_minute`)

## Dev Notes
- Code: `backend/core/backtest/execution.py` (`PositionTracker`), `engine.py`. Đặc tả đầy đủ: `architecture.md` §5.1.
- `stop_fill="level"` là giả định lạc quan; mọi báo cáo phải kèm `extreme` (E4-S5).

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `808d7f4` (test nhân quả), `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code).
- Tests: `test/test_signals_strategies.py`, `test/test_causal_engine.py`, `test/test_round4_venue_and_fills.py`.
- Golden: mọi thay đổi về sau giữ bit-identical (E3-S8).

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
