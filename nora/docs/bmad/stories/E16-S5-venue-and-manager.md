# E16-S5 — Giao diện Venue, SimVenue và PositionManager (P6.4)

- **Epic:** E16 Kiến trúc thực thi thống nhất
- **Trạng thái:** done
- **Cập nhật:** 2026-10-06

**Story.** Là lập trình viên hệ thống, tôi muốn định nghĩa giao diện sàn chung `Venue` (Protocol), bộ mô phỏng `SimVenue` và bộ quản lý chiến lược vị thế `PositionManager`, để tách rời logic ra lệnh (manager) khỏi cơ chế khớp lệnh (venue).

## Acceptance Criteria

1. Given `Venue` protocol, When gửi lệnh (`submit`) và lấy sự kiện (`next_event`), Then quy định rõ hợp đồng cho cả sàn thật và sàn ảo.
2. Given 7 tầng tính năng (market, SL, DCA settle, TP, trailing, thanh lý, gap/stop_fill), When chạy kiểm chứng chéo giữa PositionManager+SimVenue và RefPositionTracker, Then khớp từng bit trên mọi trường và mọi sự kiện.

## Evidence

- Commit: `bcf3911`, `dff2201` (P6.4 SimVenue, PositionManager, event path parity harness).
- Kiểm chứng: 7 tầng bit-identical với tracker trên 1.400 cấu hình ngẫu nhiên (200 cấu hình/tầng).
