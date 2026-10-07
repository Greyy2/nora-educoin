# E16-S8 — Adapter OkxVenue (P6.7)

- **Epic:** E16 Kiến trúc thực thi thống nhất
- **Trạng thái:** done
- **Cập nhật:** 2026-10-06

**Story.** Là lập trình viên hệ thống, tôi muốn cài đặt `OkxVenue` bọc API sàn OKX v5 để biến sàn thật thành một đối tượng tuân thủ giao thức `Venue`, ánh xạ các loại lệnh và đối soát vị thế qua poll fill.

## Acceptance Criteria

1. Given `OkxVenue`, When gọi `submit`, Then ánh xạ ENTRY thành market_open, EXIT thành close_market, SL/TP thành lệnh điều kiện tương ứng.
2. Given phản hồi từ OKX, When gọi `next_event`, Then sinh ra `Fill`, `OrderRejected`, `FundingApplied` theo đúng định dạng chuẩn.

## Evidence

- Commit: `eb1cab5` (P6.7 OkxVenue implements Venue protocol).
- Kiểm chứng: Conformance test xanh trên mock HTTP OKX v5.
