# Story E16-S10: — Đối chiếu chuẩn NautilusTrader & Nến hai pha (P6.10–P6.12)

## Status
Done

## Story
**Là** kỹ sư hệ thống, **tôi muốn** hoàn thiện — Đối chiếu chuẩn NautilusTrader & Nến hai pha (P6.10–P6.12), **để** hệ thống vận hành đúng chuẩn định lượng và kiến trúc Nora.

## Acceptance Criteria
1. Given bộ test so chéo Nautilus (`REPORT.md`, `EXT_REPORT.md`), When so sánh từng lệnh giữa hai engine, Then đạt 0 lỗi chưa giải thích trên hơn 18.000 lệnh.
2. Given quy tắc khớp bảo thủ, When DCA khớp trong nến, Then SL cũ vẫn có hiệu lực đến hết nến; resting limit gặp gap khớp ở giá limit.
3. Given mô phỏng nến danh mục, When chuyển sang kiến trúc hai pha (pha 1 lúc mở nến, pha 2 trong nến), Then loại bỏ hoàn toàn hiện tượng tài sản sau nhìn trước kết quả của tài sản trước.

## Tasks / Subtasks
- [x] Hoàn thành triển khai và kiểm thử

## Dev Notes
Tham chiếu kiến trúc Nora.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `27e97b8` (conservative fills), `169ddd0` (intrabar_path ohlc), `c9320bf` (two-phase portfolio bar).
- Báo cáo: `test/scripts/nautilus_diff/REPORT.md` và `EXT_REPORT.md` (0 lỗi class e).

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-06 | 1.0.0 | Khởi tạo và ghi nhận trạng thái | BMAD Dev |
