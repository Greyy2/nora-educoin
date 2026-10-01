# E9-S1: Bot Binance Futures testnet chạy đúng quy tắc đã mô phỏng

- **Epic:** E9 Testnet & Live
- **Trạng thái:** backlog
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

- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
