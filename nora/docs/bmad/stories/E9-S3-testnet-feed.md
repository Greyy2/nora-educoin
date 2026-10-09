# Story E9-S3: TestnetFeed thật thay feed giả lập

## Status
Done

## Story
Là người theo dõi danh mục, tôi muốn nguồn Testnet đọc từ tài khoản testnet thật, để trang Danh mục hiển thị số thật mà không đổi payload.

## Acceptance Criteria
1. **Given** khoá testnet hợp lệ, **When** `TestnetFeed.fetch()`, **Then** trả `FeedSnapshot` có `equity_curve`/`daily_nav` từ số dư, `trade_list` từ lịch sử khớp lệnh, `positions` từ vị thế mở, `config` (vốn đầu, chiến lược, tài sản).
2. **Given** feed thật kết nối được, **When** `GET /dashboard?source=testnet`, **Then** payload không có `mock`/`mock_note` và `source.mock` là `false` hoặc vắng mặt.
3. **Given** không kết nối được, **When** gọi, **Then** rơi về feed giả lập có banner (hành vi hiện có), không lỗi 500.
4. **Given** payload, **When** so với hợp đồng `docs/ui_contract.md` §3, **Then** `test_portfolio_dashboard.py` hiện có vẫn qua (không đổi hợp đồng).

## Tasks / Subtasks
- [ ] Client lịch sử lệnh, số dư, vị thế (testnet)
- [ ] Chuyển lịch sử thành `trade_list` và `daily_nav` đúng quy ước
- [ ] Cài `TestnetFeed.fetch()` và test với phản hồi giả
- [ ] Cập nhật `docs/ui_contract.md` nếu cần

## Dev Notes
- Code: `backend/core/analytics/feeds.py` (lớp `TestnetFeed`, hiện luôn `NotAvailable`). Phụ thuộc E9-S1 (có giao dịch để hiển thị), E9-S7 (khoá).
- NAV theo ngày UTC; funding đã nằm trong NAV (xem `ui_contract.md` §3).

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- **Commit:** `5f2a97e`
- **Tests:** `test/scripts/check_bot_exec_replay.py`
**06/10/2026 — thay thế.** Feed giả lập đã bỏ; trang Danh mục chỉ còn kết quả backtest. Tài khoản demo xem ở trang **Live**
(`/api/studio/live/trades`): vốn sàn mỗi bước, lệnh khớp thật (giá đóng, lãi lỗ, phí, funding từ lịch sử vị thế OKX), vị thế mở, bóng paper.
Hợp đồng `FeedSnapshot` không còn dùng.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
| 2026-10-06 | OKX demo: trạng thái `done`. |
