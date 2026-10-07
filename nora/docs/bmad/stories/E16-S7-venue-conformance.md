# E16-S7 — Bộ kiểm thử hợp đồng Venue (P6.6)

- **Epic:** E16 Kiến trúc thực thi thống nhất
- **Trạng thái:** done
- **Cập nhật:** 2026-10-06

**Story.** Là lập trình viên hệ thống, tôi muốn bộ kiểm thử hợp đồng chuẩn hoá (`test/test_venue_conformance.py`) kiểm tra tính đúng đắn của bất kỳ cài đặt `Venue` nào (SimVenue, OkxVenue), đảm bảo tuân thủ nghiêm ngặt giao thức.

## Acceptance Criteria

1. Given `SimVenue`, When chạy bộ kiểm thử conformance, Then tất cả các ca kiểm thử hợp đồng (đặt lệnh, huỷ lệnh, khớp lệnh, từ chối lệnh) đều đạt.
2. Given sự khác biệt giữa Sim và OKX, When ghi nhận các ca đặc thù, Then đánh dấu rõ bằng xfail/strict để xử lý ở adapter.

## Evidence

- Commit: `c26e20f` (P6.6 venue conformance suite).
- Kiểm chứng: 56 pass trên SimVenue.
