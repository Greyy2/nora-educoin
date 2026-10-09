# Story E21-S6: G6 - stop_fill="extreme" và gap qua mức dừng (S13d)

## Status
Backlog

## Story
Là quant researcher, tôi muốn đối chiếu hành vi trượt giá khi chạm mức Stop-Loss qua các chế độ `stop_fill` ("level" vs "extreme") và nến mở gap qua mức dừng giữa Nora và NautilusTrader, để đánh giá độ bảo thủ và trượt giá thực tế.

## Acceptance Criteria
1. Nora hỗ trợ hai chế độ `stop_fill`: "level" (khớp đúng giá SL) và "extreme" (khớp tại giá bất lợi nhất khi có gap).
2. Nautilus xử lý tick mở gap theo quy tắc khớp tại giá Open (`fill_at_market=true` trên tick mở nến).
3. Đối chiếu cả hai chế độ trên tập dữ liệu thô (raw data) có bước giá nhảy gap qua mức cắt lỗ.
4. Sai số khớp từng lệnh đạt chuẩn: giá rel < 1e-9, vốn < 1e-3.

## Tasks / Subtasks
- [ ] Xây dựng test suite S13d với kịch bản gap xuyên qua mức dừng lỗ (AC: 1, 2)
- [ ] Chạy so sánh giữa Nora (`stop_fill=extreme` và `level`) với Nautilus (AC: 3)
- [ ] Bổ sung biên bản đối chiếu trượt giá cắt lỗ (AC: 4)

## Dev Notes
- Tham chiếu: `nora/docs/bmad/archive/p13_nautilus_gaps_plan.md` mục G6 (S13d).
- Code Nautilus: `crates/execution/.../mod.rs` (tick open gap handling).

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
