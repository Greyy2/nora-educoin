# Story E8-S7: Kiểm thử tự động cho frontend

## Status
Backlog

## Story
Là người phát triển, tôi muốn test tự động cho ba trang v2 và lớp gọi API, để thay đổi UI không làm hỏng vòng Alpha → Backtest → WFA → MC → Danh mục mà không ai biết.

## Acceptance Criteria
1. **Given** `package.json`, **When** chạy `npm test`, **Then** chạy bộ test đơn vị (hàm `lib/format.js`, `lib/jobs.js`, `hooks/useJob.js`) và qua.
2. **Given** dữ liệu mock trong `v2/mock/*.sample.json`, **When** render từng trang bằng test, **Then** các khối chính xuất hiện (KPI, bảng stage A, kết quả WFA/MC).
3. **Given** API trả 429, 409, 422, **When** trang gọi, **Then** hiển thị thông báo đúng.
4. **Given** CI hoặc lệnh chạy tay, **When** chạy toàn bộ, **Then** thời gian < 2 phút và không cần backend thật.

## Tasks / Subtasks
- [ ] Chọn công cụ (ví dụ Vitest + Testing Library, quyết định ghi vào story)
- [ ] Test `lib/` và `hooks/`
- [ ] Test render ba trang với mock
- [ ] Test hiển thị lỗi API

## Dev Notes
- Hiện không có test frontend nào (`package.json` chỉ có `dev`, `build`, `preview`).
- Phụ thuộc E8-S6 xong để tránh xung đột với thay đổi đang làm.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PENDING
- Chưa áp dụng: story chưa làm.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
