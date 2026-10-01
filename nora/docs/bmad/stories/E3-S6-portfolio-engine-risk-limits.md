# E3-S6: PortfolioEngine: nhiều tài sản trên một sổ vốn, RiskConfig và kill switch

- **Epic:** E3 Engine backtest, vốn & rủi ro
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn backtest cả sổ chiến lược trên một dòng thời gian và một quỹ vốn với giới hạn danh mục, để phản ánh cạnh tranh vốn và rủi ro như bot thật.

## Acceptance Criteria

1. **Given** một tài sản và một chiến lược, **When** chạy bằng `PortfolioEngine` và `BacktestEngine`, **Then** kết quả giống nhau (`test_portfolio_single_symbol_matches_single_engine`).
2. **Given** `RiskConfig` (8 vị thế, 1/tài sản, 3x), **When** nhiều tín hiệu cùng lúc, **Then** vượt trần bị chặn hoặc thu nhỏ và `rejected_for_risk` tăng (`test_portfolio_risk_caps_and_shared_ledger`).
3. **Given** MDD MTM chạm 30%, **When** kill switch bật, **Then** đóng hết vị thế, đặt `halted_at` và không mở lệnh mới đến hết kỳ (`test_kill_switch_closes_everything_and_stops_trading`).
4. **Given** cùng dữ liệu, **When** chạy hai lần (có/không cache), **Then** kết quả giống nhau (`test_portfolio_is_deterministic_and_cache_safe`).
5. **Given** `close_at_end=False`, **When** hết dữ liệu, **Then** vị thế mở được giữ và báo qua `open_positions()` với vốn cuối là MTM (`test_make_mock_feed_keeps_open_positions_and_is_deterministic`).

## Tasks / Subtasks

- [x] Lưới phút hợp, thứ tự tài sản cố định
- [x] Giới hạn rủi ro lúc vào lệnh
- [x] Kill switch dựa `equity_worst`
- [x] `get_results()` đủ trường (by_symbol, by_strategy, halted_at...)
- [x] `close_at_end` và `open_positions()` (cho feed giả lập)

## Dev Notes

- Code: `backend/core/backtest/portfolio.py`; số đo: `portfolio_metrics.py`. Đặc tả: `architecture.md` §6.
- Cây làm việc hiện có thay đổi CHƯA commit ở `portfolio.py`: thêm `risk_blocked_attempts` (đếm số lần vào lệnh bị chặn, không đổi `rejected_for_risk` mà golden dựa vào). Chưa kiểm trong đợt này; thuộc phạm vi E8-S6.

## Evidence

- Commits: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code) (engine), `a3202c9` (`close_at_end`, `open_positions`).
- Tests: `test/test_portfolio_engine.py` (10), `test/test_run_book_backtest.py`.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
