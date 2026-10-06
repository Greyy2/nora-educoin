# E9-S6: Đối soát live/testnet với backtest

- **Epic:** E9 Testnet & Live
- **Trạng thái:** review
- **Cập nhật:** 2026-10-06

## Story

Là người nghiên cứu, tôi muốn so từng lệnh thật với lệnh mô phỏng cùng tín hiệu, để biết trượt giá, phí và khớp SL thực tế so với giả định.

## Acceptance Criteria

1. **Given** giai đoạn testnet đã chạy, **When** chạy lại backtest với đúng cửa sổ và dữ liệu, **Then** báo cáo ghép từng lệnh thật với lệnh mô phỏng (cùng thời điểm tín hiệu).
2. **Given** các cặp lệnh, **When** thống kê, **Then** có sai khác giá vào, giá thoát, phí, funding, và tỉ lệ SL khớp xấu hơn mức (so `level` và `extreme`).
3. **Given** sai khác vượt ngưỡng đặt trước, **When** báo cáo, **Then** đánh dấu cần xem lại giả định phí/trượt (0,02%) hoặc `stop_fill`.

## Tasks / Subtasks

- [x] Định nghĩa khoá ghép lệnh
- [x] Báo cáo sai khác
- [x] Ngưỡng cảnh báo (mặc định đề xuất, cần chủ sở hữu duyệt)
- [ ] Cập nhật giả định trong `architecture.md` nếu cần

## Dev Notes

- Phụ thuộc E9-S1 và đủ số lệnh testnet; số lệnh tối thiểu để kết luận chưa xác định.
- Đóng R-8 (giả định khớp lệnh chưa đối soát).

## Evidence

**06/10/2026 — OKX demo.** Thay cho "chạy lại backtest cùng cửa sổ": bot chạy kèm một **bóng paper** (`backend/live/paper.py`, đúng
PositionTracker + vòng danh mục của engine) trên cùng nến, cùng tín hiệu; `test_paper_book_replays_engine_trades_exactly` chứng minh paper = engine.
`backend/live/compare.py` (`GET /api/studio/live/compare`, khối "Sàn thật so với paper" trên trang Live):
AC1: ghép theo mã + chiến lược + giờ vào lệch ≤ 1 nến; lệnh chỉ có ở một bên tách riêng (`only_exec` / `only_paper`).
AC2: mỗi cặp — chênh giá vào (lệnh đầu), giá TB sau DCA, giá đóng (bps, + = sàn kém), phí và funding (% danh nghĩa, sàn lấy từ lịch sử vị thế
OKX, paper từ engine), số tầng DCA, lãi lỗ % danh nghĩa; lệnh SL của paper phân loại giá đóng thật: tốt hơn mức SL (`level`) / giữa mức SL và
đáy/đỉnh nến / xấu hơn kịch bản bi quan (`extreme`).
AC3: `THRESHOLDS` đề xuất — giá vào/đóng/TB > 5 bps, phí lệch > 0,02 điểm %, > 20% lệnh chỉ paper khớp, > 10% SL xấu hơn `extreme` ->
cờ cảnh báo kèm giả định cần xem lại; dưới 30 cặp hiện "chưa đủ mẫu".
Test: `test_compare_*` trong `test/test_live_bot.py`. Chưa: đủ ≥ 30 cặp lệnh demo để kết luận (cần 2–4 tuần) và chủ sở hữu duyệt ngưỡng.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
| 2026-10-06 | Đối soát sàn OKX demo ↔ bóng paper (giá, phí, funding, SL level/extreme, cờ ngưỡng); trạng thái `review`. |
