# E10-S6: Sổ thử nghiệm: đếm mọi cấu hình đã thử

- **Epic:** E10 Nghiên cứu chiến lược mới & phương pháp
- **Trạng thái:** backlog
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn có một sổ ghi mọi cấu hình đã thử qua mọi lượt chạy, để tính đúng N cho hiệu chỉnh đa kiểm định.

## Acceptance Criteria

1. **Given** mỗi lượt `optimize_alphas`, `build_strategy_book`, `validate_book`, **When** chạy xong, **Then** ghi vào sổ thử nghiệm số cấu hình/cặp/ứng viên đã thử và cửa sổ dữ liệu.
2. **Given** sổ thử nghiệm, **When** tổng hợp, **Then** trả N tích luỹ theo chiến lược và theo tài sản.
3. **Given** các lượt đã có trong `data/_cache/{optimize,book,book_wfa}`, **When** nhập lại (backfill), **Then** sổ chứa các lượt đó với ghi chú "nhập lại, có thể thiếu".

## Tasks / Subtasks

- [ ] Định dạng sổ (`data/alphas/trials.json` hoặc tương đương, có commit)
- [ ] Ghi từ ba CLI
- [ ] Backfill từ `data/_cache`
- [ ] Cung cấp N cho E10-S1

## Dev Notes

- R-1. Các lượt hiện có: `optimize/` 5 thư mục, `book/` 13, `book_wfa/` 6; `data/_cache` có thể bị xoá nên sổ phải nằm ngoài cache.

## Evidence

- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
