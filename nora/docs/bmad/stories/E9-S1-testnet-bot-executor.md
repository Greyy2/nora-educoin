# E9-S1: Bot Binance Futures testnet chạy đúng quy tắc đã mô phỏng

- **Epic:** E9 Testnet & Live
- **Trạng thái:** review
- **Cập nhật:** 2026-10-01

## Story

Là người vận hành, tôi muốn một bot đọc cấu hình trong `data/alphas/testnet/` và giao dịch trên Binance Futures testnet theo đúng quy tắc backtest, để so sánh hành vi thật với mô phỏng trước khi dùng tiền thật.

## Acceptance Criteria

1. **Given** `testnet/trend_long_perp__SOL.json`, **When** bot khởi động, **Then** lấy `/fapi/v1/exchangeInfo`, đặt `ISOLATED` và đúng đòn bẩy cho `SOLUSDT`, và từ chối chạy nếu cấu hình không khớp tài khoản.
2. **Given** nến 1m đã đóng làm AST `match` đúng, **When** sang phút kế tiếp, **Then** bot gửi lệnh MARKET ở đầu phút đó (cùng quy tắc `pending_entry`).
3. **Given** vị thế mở, **When** bot đặt bảo vệ, **Then** SL là `STOP_MARKET` reduce-only từ giá trung bình, chốt lời là LIMIT reduce-only (nếu có), tầng DCA là LIMIT `GTX`, trailing và timeout đóng MARKET.
4. **Given** lịch sử nến giống nhau, **When** so tín hiệu của bot với backtest, **Then** hai chuỗi tín hiệu giống nhau (dùng chung `kernels.py` và `evaluator.py`, có test chênh lệch bằng 0).
5. **Given** bot chạy, **When** mất kết nối hoặc khởi động lại, **Then** đối soát vị thế/lệnh mở với sàn trước khi tiếp tục, không mở trùng vị thế.

## Tasks / Subtasks

- [ ] Thiết kế tiến trình bot (systemd user unit trong `nora.slice`, không dùng nhiều RAM)
- [ ] Client REST/WS testnet (ký HMAC, giới hạn tần suất)
- [ ] Dùng chung kernel/AST với backtest, test song song tín hiệu
- [ ] Đặt/huỷ lệnh bảo vệ, đối soát khi khởi động lại
- [ ] Log quyết định có thể phát lại

## Dev Notes

- Phụ thuộc: một alpha hoặc sổ có cấu hình testnet. Hiện chỉ có `trend_long_perp__SOL` (sổ `HOLDOUT_FAILED` không có cấu hình).
- Đặc tả hành vi cần khớp: `architecture.md` §5, §8.3. Phí giả định maker 0,02% / taker 0,05%.
- Quyết định mở: ngôn ngữ/tiến trình của bot (Python trong repo là lựa chọn mặc định); Q-2, Q-3 trong PRD.

## Evidence

**03-04/10/2026.** `backend/live/` (exchange, signals, bot, secrets), job `live_bot` (paper | testnet), API `/api/studio/live/bot`.
Đã đạt: AC1 (exchangeInfo, ISOLATED + đòn bẩy theo `_risk_margin` trước mỗi lệnh; từ chối tài khoản hedge mode), AC2 theo khung của sổ (1h: tín hiệu nến
đóng -> MARKET đầu nến kế), AC3 (SL STOP_MARKET closePosition, TP LIMIT reduce-only; trailing / timeout / tín hiệu thoát MARKET reduce-only ở nến kế),
AC4 (tín hiệu bot = engine từng bit — `test_live_signals_equal_engine_signals`; 1.500 nến sàn so với toàn lịch sử: 0 lệch trên 500 nến cuối × 4 tài sản
× 4 chiến lược), AC5 (đối soát vị thế mỗi bước, vị thế ngoài bot -> không mở trên tài sản đó). Chưa: DCA (sổ có DCA -> từ chối chạy); chạy thật trên
testnet cần khoá API của người vận hành. Paper đã chạy một bước thật trên dữ liệu mainnet (job 20261004_012621_b1fdb6).


- Chưa áp dụng: story chưa làm.

**04/10/2026 (bổ sung).** Paper = `live/paper.py` PaperBook: đúng PositionTracker + vòng danh mục của engine, từng nến; test
`test_paper_book_replays_engine_trades_exactly`: cùng nến + tín hiệu -> CÙNG lệnh (giờ vào/ra, giá, lãi/lỗ, số tầng) với PortfolioEngine/kernel,
gồm DCA nhiều tầng, tín hiệu thoát, trailing, giới hạn danh mục, kill switch. Testnet hỗ trợ DCA: thang LIMIT GTX đặt sẵn đúng bước/hệ số
(bước theo ATR% khi exit_unit = atr, như engine), tầng khớp -> giá TB từ sàn, đặt lại SL/TP từ giá TB; GTX bị từ chối -> bỏ tầng, không chuyển
market. Sửa lỗi engine: `dca_steps` / `dca_multipliers` bị build_params bỏ qua (chỉ dca_budget_check tính) — nay truyền vào tracker.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
| 2026-10-04 | Bot sổ paper/testnet (backend/live) | 015f06c |
