# Story E21-S3: G3 - Một nến 1m chạm cả tầng DCA lẫn cắt lỗ cũ (S11g)

## Status
Backlog

## Story
Là quant researcher, tôi muốn đối chiếu thứ tự ưu tiên xử lý trong cùng 1 nến khi giá chạm cả tầng DCA mới lẫn mức cắt lỗ Stop-Loss cũ giữa Nora và NautilusTrader, để đảm bảo không có sự mâu thuẫn trong việc cập nhật vị thế và rủi ro.

## Acceptance Criteria
1. Tạo kịch bản dữ liệu kiểm thử (synthetic hoặc mẫu thực tế) có nến 1m quét qua cả tầng DCA và mức SL cũ.
2. So sánh thứ tự xử lý đường đi trong nến giữa Nora (O -> H/L -> C, cập nhật SL sau khi khớp DCA) và Nautilus (mọi lệnh cùng tick khớp cùng lúc, limit trước stop).
3. Đánh giá độ lệch logic giữa hai engine và chuẩn hóa hành vi nếu có sai khác.
4. Ghi nhận kết quả vào báo cáo đối chiếu S11g.

## Tasks / Subtasks
- [ ] Xây dựng tập dữ liệu kiểm thử có va chạm DCA và SL trong cùng nến (AC: 1)
- [ ] Chạy so sánh thứ tự khớp lệnh giữa Nora và Nautilus (AC: 2)
- [ ] Đối chiếu và chốt chuẩn quy ước (AC: 3, 4)

## Dev Notes
- Tham chiếu: `nora/docs/bmad/archive/p13_nautilus_gaps_plan.md` mục G3 (S11g).
- Harness: `nora/test/scripts/nautilus_diff/`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story đang ở backlog.
- **File List:** `nora/test/scripts/nautilus_diff/`

## QA Results
- **Gate:** PENDING
- Chưa áp dụng: story chưa làm.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-09 | Tạo story từ kế hoạch P13, trạng thái `backlog`. |
