# E8-S4: Trang Alpha: hiệu chỉnh tham số, gửi sang Backtest, xuất bản sổ

- **Epic:** E8 UI v2
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn thử tham số của các chiến lược trong thư viện, thấy bảng xếp hạng mọi cấu hình và gửi cấu hình đã chọn sang Backtest, để tìm tham số tốt mà không sửa sổ đang xuất bản.

## Acceptance Criteria

1. **Given** chọn chiến lược và `n`, **When** build, **Then** job `book_build` chạy và bảng xếp hạng stage A liệt kê mọi cấu hình đã thử (điểm `null` khi không đạt cổng).
2. **Given** một dòng bảng, **When** bấm "Gửi sang Backtest", **Then** form Backtest được điền `strategies[{id, params}]`.
3. **Given** build xong, **When** xem, **Then** hiển thị dev1, dev2 level/extreme, holdout, độ ổn định (`stability`) và trạng thái chấp nhận từ kết quả lồng.
4. **Given** job build có sổ, **When** bấm "Xuất bản sổ này", **Then** có hộp xác nhận rồi gọi `POST /book/publish`.
5. **Given** kho alpha và `status` sổ, **When** mở trang, **Then** hiển thị `registry`, `HOLDOUT_FAILED`/`READY_FOR_TESTNET`.

## Tasks / Subtasks

- [x] `pages/Alpha.jsx`
- [x] Bảng stage A, gửi sang Backtest
- [x] Xuất bản có xác nhận (biểu tượng khoá SVG thay emoji)
- [x] Hiển thị kho alpha và trạng thái sổ

## Dev Notes

- Code: `frontend/src/v2/pages/Alpha.jsx`, `components/StrategyPicker.jsx`, `context/Catalog.jsx`.
- Build trong UI chỉ ghi vào thư mục job; xuất bản là thao tác riêng (E7-S4).

## Evidence

- Commits: `efe4fb2` (trang Alpha), `876ce9e` (publish, hiển thị đủ dev1/dev2/holdout/stability, SVG khoá).
- Job thật: `data/_cache/api_jobs/20261001_152812_e10d23` (build 71,1 s).

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
