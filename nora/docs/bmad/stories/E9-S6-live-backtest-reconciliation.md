# E9-S6: Đối soát live/testnet với backtest

- **Epic:** E9 Testnet & Live
- **Trạng thái:** backlog
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn so từng lệnh thật với lệnh mô phỏng cùng tín hiệu, để biết trượt giá, phí và khớp SL thực tế so với giả định.

## Acceptance Criteria

1. **Given** giai đoạn testnet đã chạy, **When** chạy lại backtest với đúng cửa sổ và dữ liệu, **Then** báo cáo ghép từng lệnh thật với lệnh mô phỏng (cùng thời điểm tín hiệu).
2. **Given** các cặp lệnh, **When** thống kê, **Then** có sai khác giá vào, giá thoát, phí, funding, và tỉ lệ SL khớp xấu hơn mức (so `level` và `extreme`).
3. **Given** sai khác vượt ngưỡng đặt trước, **When** báo cáo, **Then** đánh dấu cần xem lại giả định phí/trượt (0,02%) hoặc `stop_fill`.

## Tasks / Subtasks

- [ ] Định nghĩa khoá ghép lệnh
- [ ] Báo cáo sai khác
- [ ] Ngưỡng cảnh báo (cần chủ sở hữu duyệt)
- [ ] Cập nhật giả định trong `architecture.md` nếu cần

## Dev Notes

- Phụ thuộc E9-S1 và đủ số lệnh testnet; số lệnh tối thiểu để kết luận chưa xác định.
- Đóng R-8 (giả định khớp lệnh chưa đối soát).

## Evidence

- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
