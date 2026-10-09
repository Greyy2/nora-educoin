# Story E15-S6: Hiển thị regime hiện tại, lịch sử, chiến lược đang bật

## Status
Done

## Story
Là người theo dõi danh mục, tôi muốn thấy regime hiện tại và lịch sử của từng tài sản cùng chiến lược được phép vào lệnh, để hiểu vì sao sổ đang/không giao dịch.

## Acceptance Criteria
1. **Given** `GET /api/studio/market/regime?days=30`, **When** gọi, **Then** mỗi tài sản có `current`, `segments`, `share_pct`, `strategies_on/off`.
2. **Given** trang Danh mục, **When** mở ở chế độ sáng và tối, **Then** bảng Regime thị trường hiển thị đúng màu theo token, không lỗi console.

## Tasks

- [x] Endpoint `/api/studio/market/regime` (cache theo dấu vân tay dữ liệu)
- [x] `RegimePanel` (7/30/90 ngày, thanh lịch sử, chú giải)
- [x] CSS dùng token chủ đề

## Tasks / Subtasks
- [x] Hoàn thành triển khai và kiểm thử

## Dev Notes
Nhãn trên nến 15m (đặc trưng 1h/4h đã đóng) qua `classifier.series` — cùng đường backtest. "Đang bật" theo bảng tĩnh của sổ, có ghi chú kết quả P2.4.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `dc08366`.
- Test: build `npm run build` sạch; ảnh kiểm sáng/tối 5 trang, 0 lỗi console (P4.4).
- Số đo: không áp dụng.

## Change Log
| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-03 | Tạo | dc08366 |
