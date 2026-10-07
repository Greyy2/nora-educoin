# E16-S10 — Đối chiếu chuẩn NautilusTrader & Nến hai pha (P6.10–P6.12)

- **Epic:** E16 Kiến trúc thực thi thống nhất
- **Trạng thái:** done
- **Cập nhật:** 2026-10-06

**Story.** Là kiểm thử viên và nghiên cứu định lượng, tôi muốn Nora đạt chuẩn đối chiếu với NautilusTrader (khớp nến O-H-L-C, quy tắc khớp bảo thủ, xử lý nến danh mục hai pha loại bỏ nhìn trước) để đảm bảo kết quả backtest trung thực tuyệt đối.

## Acceptance Criteria

1. Given bộ test so chéo Nautilus (`REPORT.md`, `EXT_REPORT.md`), When so sánh từng lệnh giữa hai engine, Then đạt 0 lỗi chưa giải thích trên hơn 18.000 lệnh.
2. Given quy tắc khớp bảo thủ, When DCA khớp trong nến, Then SL cũ vẫn có hiệu lực đến hết nến; resting limit gặp gap khớp ở giá limit.
3. Given mô phỏng nến danh mục, When chuyển sang kiến trúc hai pha (pha 1 lúc mở nến, pha 2 trong nến), Then loại bỏ hoàn toàn hiện tượng tài sản sau nhìn trước kết quả của tài sản trước.

## Evidence

- Commit: `27e97b8` (conservative fills), `169ddd0` (intrabar_path ohlc), `c9320bf` (two-phase portfolio bar).
- Báo cáo: `test/scripts/nautilus_diff/REPORT.md` và `EXT_REPORT.md` (0 lỗi class e).
