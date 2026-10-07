# E16-S6 — Runner điều phối và PaperBook trên SimVenue (P6.5)

- **Epic:** E16 Kiến trúc thực thi thống nhất
- **Trạng thái:** done
- **Cập nhật:** 2026-10-06

**Story.** Là lập trình viên hệ thống, tôi muốn có bộ điều phối `Runner` liên kết Venue, PositionManager, Account và Risk, đồng thời chuyển đổi `PaperBook` sang chạy trên `Runner(SimVenue)` để thống nhất vòng lặp thực thi.

## Acceptance Criteria

1. Given `Runner`, When gọi `step_bar`, Then xử lý funding, admit_entry và phân phối sự kiện cho từng slot theo thứ tự xác định.
2. Given `PaperBook`, When chạy kiểm thử khớp lệnh với kernel, Then kết quả bit-identical 100%.

## Evidence

- Commit: `2a8156d` (P6.5 Runner, PaperBook trên SimVenue event path).
- Kiểm chứng: PaperBook(event) = tracker = kernel bit-for-bit trên 40 cấu hình cơ bản và 100 cấu hình có rủi ro.
