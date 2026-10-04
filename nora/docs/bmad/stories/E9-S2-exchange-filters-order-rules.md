# E9-S2: Bộ lọc sàn: tickSize, stepSize, minNotional và quy tắc lệnh

- **Epic:** E9 Testnet & Live
- **Trạng thái:** review
- **Cập nhật:** 2026-10-01

## Story

Là người vận hành, tôi muốn bot làm tròn giá/khối lượng theo bộ lọc của sàn và xử lý lệnh bị từ chối, để lệnh không bị sàn trả lỗi âm thầm.

## Acceptance Criteria

1. **Given** giá/khối lượng tính từ sizing, **When** gửi lệnh, **Then** làm tròn xuống theo `stepSize`/`tickSize` và bỏ lệnh nếu dưới `minNotional`, ghi lý do vào log.
2. **Given** lệnh LIMIT `GTX` có thể khớp ngay (sẽ là taker), **When** sàn từ chối, **Then** bot ghi nhận tầng DCA bị bỏ và không chuyển thành lệnh market.
3. **Given** khối lượng sau làm tròn khác mô phỏng, **When** vào lệnh, **Then** sai khác được ghi nhận để đối soát (E9-S6).

## Tasks / Subtasks

- [ ] Đọc và cache `exchangeInfo`
- [ ] Hàm làm tròn và kiểm `minNotional`
- [ ] Xử lý mã lỗi từ chối lệnh
- [ ] Test với bộ lọc giả

## Dev Notes

- Phụ thuộc E9-S1. Cấu hình hiện ghi `exchange_filters: lấy tickSize / stepSize / minNotional từ /fapi/v1/exchangeInfo khi khởi động`.

## Evidence

**04/10/2026.** `live.exchange.Filters`: làm tròn xuống theo stepSize/tickSize, bỏ lệnh dưới minQty/minNotional và ghi sự kiện `skip`
(`test_filters_round_down_and_reject_small`). DCA GTX chưa áp dụng (bot chưa hỗ trợ DCA). Sai khác khối lượng so với mô phỏng ghi trong events.jsonl.


- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
| 2026-10-04 | Bot sổ paper/testnet (backend/live) | 015f06c |
