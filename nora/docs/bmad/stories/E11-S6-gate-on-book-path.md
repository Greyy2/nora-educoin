# E11-S6: Gate dữ liệu trên đường danh mục/sổ

- **Epic:** E11 Bảo mật & phát hành
- **Trạng thái:** backlog
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn `build_strategy_book`, `validate_book` và `run_book_backtest` kiểm chất lượng dữ liệu trước khi chạy, để dữ liệu hỏng sau khi đã promote không tạo ra kết quả sai âm thầm.

## Acceptance Criteria

1. **Given** tài sản `BLOCKED` hoặc `NEEDS_MORE_DATA` trong vũ trụ, **When** chạy một trong ba CLI, **Then** thoát mã khác 0 kèm lý do và không chạy engine.
2. **Given** dữ liệu `APPROVED`/`WARNING`, **When** chạy, **Then** kết quả bit-identical với trước khi thêm gate (golden và `test_run_book_backtest.py` không đổi).
3. **Given** gate trên 8 tài sản, **When** đo thời gian, **Then** tổng chi phí được ghi lại (comment trong code nói ~11 s mỗi tài sản 3 năm chưa cache; cần đo thực) và nằm trong ngân sách chấp nhận do chủ sở hữu đặt.
4. **Given** job API `book_backtest`, **When** gate chặn, **Then** job `failed` và `log_tail` nêu lý do.

## Tasks / Subtasks

- [ ] Gọi `evaluate_data_quality` cho từng tài sản của vũ trụ (có cache)
- [ ] Test với dữ liệu giả `BLOCKED`
- [ ] Đo chi phí gate
- [ ] Cập nhật FR-5, R-7 và `architecture.md` §3.4

## Dev Notes

- Hiện gate chỉ gọi ở Studio `/simulate`, scan, WFA đơn tài sản, research, `promote_staging` (E1-S4). R-7.
- Cẩn thận golden: gate không được đổi dữ liệu hay thứ tự tính.

## Evidence

- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
