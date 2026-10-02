# E7-S6: Feed Live/Testnet giả lập thay cho tài khoản chưa nối

- **Epic:** E7 Studio API
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người theo dõi danh mục, tôi muốn trang Danh mục có đủ ba nguồn Live, Testnet, Backtest với dữ liệu giả lập tất định khi chưa có tài khoản thật, để UI và payload hoàn chỉnh trước khi nối sàn.

## Acceptance Criteria

1. **Given** `source=live|testnet`, **When** chưa nối tài khoản, **Then** payload có `mock: true`, `mock_note = "Dữ liệu giả lập — chưa kết nối tài khoản <Live|Testnet>"` và `positions[]` (`test_mock_source_has_flag_note_and_positions`).
2. **Given** chưa có file giả lập, **When** gọi, **Then** HTTP 200 `{available:false, reason}` có hướng dẫn chạy `make_mock_feeds` (`test_live_testnet_without_mock_file_is_unavailable_with_hint`).
3. **Given** file giả lập hỏng, **When** gọi, **Then** `available:false` (`test_mock_feed_corrupt_file_is_unavailable`).
4. **Given** `source=paper` hoặc giá trị lạ, **When** gọi, **Then** 422 (`test_paper_source_is_removed_and_unknown_sources_rejected`).
5. **Given** `LiveFeed`/`TestnetFeed`, **When** `fetch()`, **Then** `NotAvailable` (stub) (`test_real_feeds_are_stubs_that_raise_not_available`).
6. **Given** `make_mock_feeds` chạy hai lần trên cùng dữ liệu, **When** so kết quả, **Then** giống nhau và vị thế cuối dữ liệu được giữ mở (`test_make_mock_feed_keeps_open_positions_and_is_deterministic`).
7. **Given** payload backtest, **When** so với trước khi có feed, **Then** giống hệt (+ `positions: []`) (`test_backtest_feed_payload_identical_to_pre_feed_output`).

## Tasks / Subtasks

- [x] `feeds.py` (BacktestFeed, MockFeed, Live/Testnet stub, `get_snapshot`)
- [x] CLI `make_mock_feeds` (testnet: sổ, 8 perp, 60 ngày, 10.000 USDT; live: alpha SOL + sổ, 120 ngày, 25.000 USDT)
- [x] Bỏ nguồn Paper
- [x] `positions[]` trong mọi payload
- [>] Cài `LiveFeed.fetch()` / `TestnetFeed.fetch()` thật: E9-S3, E9-S4

## Dev Notes

- Code: `backend/core/analytics/feeds.py`, `backend/core/analytics/make_mock_feeds.py`; file `data/_cache/mock_feeds/{live,testnet}.json`.
- Feed giả lập không phải dữ liệu thật; banner và chip MOCK là bắt buộc (R-6). Alpha SOL ở feed live nhân `order_size_pct` với hệ số vốn extreme tối đa (0,5).

## Evidence

- Commit: `a3202c9` (message: 440 test qua, golden không đổi).
- Tests: `test/test_portfolio_dashboard.py`, `test/test_run_book_backtest.py`.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
