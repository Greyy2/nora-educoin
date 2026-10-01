# E8-S5: Nguồn Live | Testnet | Backtest và banner giả lập

- **Epic:** E8 UI v2
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người theo dõi danh mục, tôi muốn chuyển giữa Live, Testnet và Backtest và luôn biết dữ liệu có phải giả lập không, để không nhầm số mô phỏng với số thật.

## Acceptance Criteria

1. **Given** trang Danh mục, **When** mở lần đầu, **Then** nguồn mặc định là Live; có ba lựa chọn Live, Testnet, Backtest (không còn Paper).
2. **Given** payload `mock: true`, **When** render, **Then** có banner với `mock_note` và chip MOCK.
3. **Given** `available:false`, **When** render, **Then** hiển thị `reason` thay vì biểu đồ.
4. **Given** nguồn Backtest, **When** chọn job, **Then** dùng đúng `job_id` hoặc backtest xong gần nhất.

## Tasks / Subtasks

- [x] Bộ chọn nguồn
- [x] Banner và chip MOCK
- [x] Trạng thái rỗng kèm lý do
- [x] Bảng "Vị thế đang mở"

## Dev Notes

- Code: `frontend/src/v2/pages/Portfolio.jsx`, `v2/components/Dashboard.jsx`. Phụ thuộc E7-S6.
- Khi nối tài khoản thật (E9-S3/S4) chỉ banner tự biến mất vì backend không còn gắn `mock`.

## Evidence

- Commit: `a3202c9` (message: UI Live | Testnet | Backtest, Live mặc định, banner mock + chip MOCK, bảng Vị thế đang mở).
- Chưa có test giao diện tự động.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
