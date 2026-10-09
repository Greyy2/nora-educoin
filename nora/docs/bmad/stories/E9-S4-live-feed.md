# Story E9-S4: LiveFeed thật cho tài khoản Binance Futures

## Status
Backlog

## Story
Là người theo dõi danh mục, tôi muốn nguồn Live đọc từ tài khoản thật chỉ-đọc, để theo dõi tiền thật bằng cùng một trang.

## Acceptance Criteria
1. **Given** khoá chỉ-đọc, **When** `LiveFeed.fetch()`, **Then** trả `FeedSnapshot` đúng dạng như E9-S3 cho tài khoản live.
2. **Given** khoá có quyền giao dịch/rút, **When** nạp cấu hình, **Then** từ chối khởi động (chỉ chấp nhận quyền đọc cho feed).
3. **Given** feed live bật, **When** mở trang Danh mục, **Then** không còn banner MOCK ở nguồn Live.

## Tasks / Subtasks
- [ ] Cài `LiveFeed.fetch()`
- [ ] Kiểm quyền khoá khi nạp
- [ ] Test với phản hồi giả
- [ ] Tài liệu cấu hình

## Dev Notes
- Phụ thuộc E9-S3, E9-S7. Chỉ làm sau khi testnet chạy ổn định ít nhất một giai đoạn (tiêu chí do chủ sở hữu quyết, Q-2).

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PENDING
**06/10/2026.** Chưa chạy vốn thật. Khi bật live, trang Live dùng cùng đường với demo (`mode=live`, bắt buộc `confirm_live`);
yêu cầu khoá không có quyền rút do E9-S7 AC3 đảm nhận.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
| 2026-10-06 | OKX demo: ghi chú. |
