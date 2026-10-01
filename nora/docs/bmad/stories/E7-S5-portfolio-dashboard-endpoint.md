# E7-S5: Endpoint dashboard Danh mục

- **Epic:** E7 Studio API
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người theo dõi danh mục, tôi muốn một payload duy nhất đủ KPI, đường vốn, rủi ro và vị thế từ một job backtest, để vẽ trang Danh mục mà không tính lại ở client.

## Acceptance Criteria

1. **Given** một job `book_backtest` xong, **When** `GET /dashboard?source=backtest&job_id=...&period=3M`, **Then** payload có đủ khoá của hợp đồng và mọi chuỗi trong `series` cùng độ dài `dates` (`test_payload_has_every_key_and_aligned_series`).
2. **Given** số liệu đã biết, **When** tính, **Then** NAV, drawdown, VaR/CVaR 95%, Sharpe, bảng tháng đúng (`test_drawdown_and_nav_known_values`, `test_var_cvar_sharpe_known_values`, `test_monthly_table_known_values`).
3. **Given** các kỳ `1M/3M/YTD/1Y/ALL`, **When** cắt, **Then** đúng cutoff (YTD dùng cuối năm trước) (`test_period_slicing`, `test_period_ending_year_start_uses_previous_year_end_for_ytd`).
4. **Given** ngày không có P&L, **When** tính tỉ lệ ngày lãi, **Then** chỉ tính ngày có P&L khác 0 (`test_win_days_counts_only_days_with_pnl`).
5. **Given** không truyền `job_id`, **When** `source=backtest`, **Then** dùng backtest xong gần nhất, hoặc `available:false` kèm lý do nếu chưa có.
6. **Given** gọi lặp cùng khoá, **When** file kết quả không đổi, **Then** trả từ cache LRU (`test_dashboard_endpoint_caches_and_rebases_benchmark`); 1 năm dữ liệu tính nhanh (`test_dashboard_is_fast_for_one_year`).

## Tasks / Subtasks

- [x] `portfolio_dashboard.build_dashboard`
- [x] Router `portfolio.py` + cache LRU 32 mục
- [x] Bảng chiến lược realised, sự kiện rủi ro, exposure
- [x] Benchmark BTC buy & hold quy cùng NAV đầu kỳ

## Dev Notes

- Code: `backend/core/analytics/portfolio_dashboard.py`, `backend/api/routers/portfolio.py`. Hợp đồng: `docs/ui_contract.md` §3.
- Ngày UTC; Sharpe/Sortino quy năm bằng √365. `strategies[].pnl` là realised, nên tổng không khớp từng đồng với NAV MTM.
- Cây làm việc có thay đổi chưa commit ở `portfolio_dashboard.py` và `test_portfolio_dashboard.py` (sự kiện chặn rủi ro đếm số lần vào lệnh thay vì số phút; `test_risk_block_event_counts_attempts_not_minutes`). Chưa tính vào story này.

## Evidence

- Commits: `efe4fb2` (endpoint), `876ce9e` (tỉ lệ ngày lãi, `active_days`).
- Tests: `test/test_portfolio_dashboard.py` (26 test tại HEAD, gồm các test trên).

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
