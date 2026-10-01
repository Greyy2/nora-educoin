# E2-S1: 23 kernel thuần, causal và bất biến theo tiền tố

- **Epic:** E2 Tín hiệu & chiến lược
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn các chỉ báo chỉ dùng dữ liệu đã đóng tới nến hiện tại, để tín hiệu không nhìn trước tương lai.

## Acceptance Criteria

1. **Given** mọi kernel trong `kernels.py` và một chuỗi giá, **When** cắt chuỗi ở nhiều điểm t, **Then** `kernel(df)[:t] == kernel(df[:t])` (`test_kernel_is_causal_prefix_invariant`).
2. **Given** một kernel cố ý nhìn tương lai, **When** chạy phép kiểm prefix, **Then** bị phát hiện (`test_prefix_check_detects_a_lookahead_kernel`).
3. **Given** chưa đủ nến khởi động, **When** tính kernel, **Then** trả NaN và điều kiện dùng NaN là False (`test_kernel_nan_during_warmup_then_values`).
4. **Given** một vài kernel có giá trị tham chiếu, **When** so với số đã biết, **Then** khớp (`test_kernel_reference_values`, `test_rsi_flat_series_is_50`).
5. **Given** tên cột sai, **When** parse, **Then** bị từ chối (`test_parse_column_rejects_bad_names`).
6. **Given** kernel 1m, **When** có phút điền, **Then** chỉ tính trên phút có giao dịch (`test_one_minute_kernels_ignore_filled_minutes`).

## Tasks / Subtasks

- [x] 23 kernel: `sma ema roc er adx rsi bbz bbm bbu bbl bbw bbwp atr natr rv kcm kcu kcl dch dcl vwap vwapdev volz`
- [x] `dch`/`dcl` không gồm nến hiện tại
- [x] `parse_column`, `warmup_bars`, `catalog()` cho API/UI
- [x] Phép kiểm prefix tổng quát

## Dev Notes

- Code: `backend/core/signals/kernels.py`. Tên cột `<kernel>_<tham số>` (ví dụ `bbu_20_2`).
- RMA/Wilder dùng `ewm(alpha=1/n, adjust=False, min_periods=n)`: đệ quy nên causal.
- Thêm kernel mới bắt buộc qua phép kiểm prefix trước khi dùng.

## Evidence

- Commit: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code).
- Tests: `test/test_signals_strategies.py` (25 test, gồm các test trên).
- Chưa đo hiệu năng kernel riêng; thời gian tổng của engine ở E3-S7.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
