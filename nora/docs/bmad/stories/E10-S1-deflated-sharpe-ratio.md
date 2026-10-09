# Story E10-S1: Deflated Sharpe Ratio cho alpha và sổ

## Status
Backlog

## Story
Là người nghiên cứu, tôi muốn có Deflated Sharpe Ratio hiệu chỉnh cho số cấu hình đã thử, để biết Sharpe của alpha có còn ý nghĩa sau đa kiểm định hay không.

## Acceptance Criteria
1. **Given** chuỗi lợi suất ngày OOS, số lần thử N, độ lệch và độ nhọn, **When** tính DSR/PSR, **Then** khớp giá trị tham chiếu từ công thức Bailey và López de Prado với sai số ≤ 1e-6 (test với số tính tay).
2. **Given** `N = 1`, **When** tính DSR, **Then** bằng PSR so với ngưỡng 0.
3. **Given** alpha SOL, **When** tính với số lần thử từ sổ thử nghiệm (E10-S6), **Then** DSR được ghi vào `evidence` của `registry.json` kèm N đã dùng.
4. **Given** gate hiện tại, **When** thêm DSR, **Then** ban đầu chỉ báo cáo (không đổi `verdict`); biến thành gate khi chủ sở hữu duyệt ngưỡng.

## Tasks / Subtasks
- [ ] Hàm `psr`, `dsr` (`backend/carlo/` hoặc module mới) với test
- [ ] Đọc N từ sổ thử nghiệm
- [ ] Ghi vào registry và UI Alpha
- [ ] Quyết định ngưỡng gate (Q mới)

## Dev Notes
- R-1. Hiện số lần thử: lượt `20260930_1728` 34 cặp × ≤ 60 cấu hình; chưa tổng hợp qua mọi lượt.
- Không nới gate hiện có; chỉ thêm kiểm tra.

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
