# Story E4-S6: Kiểm null và bài học nghiên cứu: edge giả của bộ quét limit

## Status
Done

## Story
Là người nghiên cứu, tôi muốn mọi bộ quét mới phải ra "không có edge" trên random walk trước khi tin kết quả, để không lặp lại edge giả +15 bps từng gặp.

## Acceptance Criteria
1. **Given** random walk, **When** chạy bộ quét limit-scalp, **Then** không có edge (`test_limit_scalp_has_no_edge_on_random_walk`).
2. **Given** nhiều lệnh limit chờ, **When** khớp, **Then** không bỏ lệnh sớm để chọn lệnh sau (không chọn trước lệnh "sẽ khớp") (`test_no_overlap_never_skips_an_earlier_pending_order_for_a_later_one`).
3. **Given** nghiên cứu DC trên 1m close, **When** dữ liệu là random walk, **Then** bị bác bỏ, và t-stat hurdle loại lệnh may mắn (`test_research_random_walk_falsified_on_1m_close`, `test_t_stat_hurdle_rejects_lucky_trades`).
4. **Given** tham số chọn theo dữ liệu, **When** sweep, **Then** có tách train/test mới được chọn theta (`test_sweep_does_not_pick_theta_without_train_test_split`).

## Tasks / Subtasks
- [x] `test_research_null.py`
- [x] Ghi nhận kết quả hướng nghiên cứu (maker scalp, funding carry, trend chung)
- [x] CLI `research_maker_scalp`, `research_trend_portfolio`
- [>] Biến phép kiểm null thành cổng bắt buộc cho mọi bộ quét: chuyển sang E10

## Dev Notes
- Code: `backend/core/research/research_maker_scalp.py`, `backend/core/research/research_trend_portfolio.py`; test `test/test_research_null.py`.
- Hai nguyên nhân edge giả đã xác định (`docs/alpha_pipeline.md` §7): chọn trước lệnh sẽ khớp (nhìn trước) và SL khớp đúng mức khi giá giật xuyên mức.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code).
- Kết quả hướng chiến lược (`docs/alpha_pipeline.md` §7, ngày 30/09/2026): maker scalp 1m-15m không có edge (9.792 cấu hình × 8 tài sản, gần như tất cả lỗ ở dev); trend chung hai chiều cho 8 tài sản thất bại, long trend chỉ có edge trên SOL; funding carry 12-14%/năm năm 2024 còn 1-2%/năm năm 2026 (chưa tính phí 4 chân).
- Báo cáo: `data/_cache/reports/maker_scalp_r2_*.json`, `trend_portfolio_20260930_1829.json` (chưa đọc lại trong đợt này).
- Tests: `test/test_research_null.py` (2), `test/test_round4_venue_and_fills.py` (6), `test/test_signals_strategies.py`.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
