# E12-S1: Kernel numba là vòng lặp trong của engine + tua nhanh phút yên lặng

- **Epic:** E12 Tốc độ
- **Trạng thái:** done
- **Cập nhật:** 2026-10-03

## Story

Là người chạy phễu quy mô lớn, tôi muốn vòng lặp mô phỏng chạy bằng numba và bỏ qua phút không có sự kiện, để 500k alpha chạy được trong vài giờ mà kết quả trùng bit.

## Acceptance Criteria

1. **Given** cùng dữ liệu và chiến lược, **When** chạy kernel numba và engine Python tham chiếu, **Then** vị thế, vốn và số đo trùng từng bit (`test_kernel_parity.py`, golden).
2. **Given** phút không có lệnh mở và không có tín hiệu (kill == 0), **When** chạy, **Then** kernel tua nhanh qua đoạn đó (`_quiet_bar` khớp điều kiện `_intrabar`) và kết quả không đổi.

## Tasks

- [x] Kernel `portfolio_kernel` (core/backtest/kernel.py)
- [x] Tua nhanh phút yên lặng + MTM chỉ ở phút lấy mẫu
- [x] Tái dùng dung lượng `_CAP_HINT`

## Dev Notes

Roadmap P1.2–P1.3, P1.9–P1.10. Engine Python cũ chỉ còn trong test/reference_engine.py để so trùng bit.

## Evidence

- Commit: `f7e9c1b` (kernel), `7f7060f` (tua nhanh).
- Test: `test/test_kernel_parity.py`, `test/test_golden_results.py`.
- Số đo: roadmap P1 (0,03 → 26,9 alpha/s ở 1m).

## Change Log

| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-03 | Tạo story ghi nhận P1.2–P1.10 | f7e9c1b, 7f7060f |
