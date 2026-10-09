# Story E19-S4: Thiết kế Responsive và hoàn thiện Dark theme

## Status
Done

## Story
**Là** người dùng, **tôi muốn** giao diện Nora hiển thị tối ưu trên các kích cỡ màn hình khác nhau (từ mobile 360px tới desktop 1920px) và có tông màu Dark theme chuyên nghiệp, **để** làm việc thoải mái trong nhiều giờ liên tục.

## Acceptance Criteria
1. Bố cục Shell và Navigation co giãn linh hoạt (flex/grid responsive).
2. Các bảng dữ liệu lớn (Positions, Trades, Backtest summary) có thanh cuộn ngang mượt mà, không bị vỡ layout trên màn hình nhỏ.
3. Bảng màu Dark theme đạt độ tương phản chuẩn WCAG AA cho văn bản và chỉ số.
4. Tránh hoàn toàn việc đè nút nội dung hoặc tràn viền màn hình trên 7 kích thước chuẩn (360, 390, 768, 1024, 1280, 1440, 1920px).

## Tasks / Subtasks
- [x] Tinh chỉnh CSS responsive cho layout Shell và các trang chính (AC: 1, 2)
- [x] Kiểm tra và chuẩn hoá bảng màu Dark theme trong `frontend/src/styles/` (AC: 3)
- [x] Sửa lỗi đè nút và tràn khung trên các panel kết quả (AC: 4)

## Dev Notes
- Tài liệu tham chiếu: [ux-design.md](../ux-design.md).
- File triển khai: `frontend/src/layout/Shell.jsx`, `frontend/src/styles/`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Giao diện responsive 7 kích thước và Dark theme hoàn thiện tinh tế. Đã commit toàn bộ CSS responsive.
- **File List:**
  - `frontend/src/layout/Shell.jsx`
  - `frontend/src/styles/responsive.css`
  - `frontend/src/styles/`

## QA Results
- **Gate:** PASS
- **Commit:** `0c7f22f`
- **Tests:**
  - Kiểm thử Playwright trên 7 kích thước màn hình: 360px, 390px, 768px, 1024px, 1280px, 1440px, 1920px cả hai chế độ sáng/tối
  - Không có hiện tượng đè nút điều khiển hay tràn khung

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-07 | 1.0.0 | Hoàn thiện Dark theme và responsive UI | BMAD Dev |
| 2026-10-09 | 1.0.1 | Chuyển sang Review, cập nhật 7 cỡ màn hình kiểm thử | BMAD Dev |
| 2026-10-09 | 1.0.2 | Hoàn tất nghiệm thu, chuyển sang Done với commit `0c7f22f` | BMAD Dev |
