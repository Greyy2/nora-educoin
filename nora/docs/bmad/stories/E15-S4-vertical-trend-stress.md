# Story E15-S4: Monte Carlo: kịch bản trend thẳng đứng

## Status
Done

## Story
Là người quản lý rủi ro, tôi muốn MC có kịch bản giá chạy thẳng đứng ngược vị thế lớn nhất từng mở, để bot nhồi lệnh kiểu OKX trượt cổng còn sổ có cắt lỗ thì không bị phạt oan.

## Acceptance Criteria
1. **Given** vị thế (trade list), **When** tính `vertical_exposure`, **Then** cộng đúng các lệnh mở chồng nhau theo thời gian; có cắt lỗ theo rủi ro → lỗ ≤ 2 × rủi ro kế hoạch; không cắt lỗ → lỗ ≤ ký quỹ.
2. **Given** bot DCA LONG không cắt lỗ, danh nghĩa 3 × vốn, lịch sử êm (6 kịch bản cũ đều qua), **When** thêm kịch bản thẳng đứng, **Then** `vertical_crash` −90% và gate trượt; sổ trend 0,5%/lệnh có cắt lỗ thì qua (`test_vertical_scenarios_fail_okx_style_dca_bot_but_not_stopped_trend_book`).
3. **Given** không truyền shock, **When** chạy MC, **Then** kết quả y nguyên bản cũ (6 kịch bản).

## Tasks

- [x] `carlo/monte_carlo.py`: vertical_exposure, merge_exposure, vertical_sequences, stress_scenarios(shock)
- [x] WFA ghi `summary.shock`; API /mc dùng shock của job WFA
- [x] Phễu: S3 `metrics.shock` → S4/S5
- [x] `STRESS_NAMES` 9 tên; bỏ vertical khi nguồn có vị thế → custom_gates

## Tasks / Subtasks
- [x] Hoàn thành triển khai và kiểm thử

## Dev Notes
+40%/3 ngày ngược SHORT, −30%/1 ngày ngược LONG, chuỗi tăng-sập ×2; đặt đầu chuỗi rồi lịch sử. WFA thật (tắt regime): crash_loss = surge_loss = 6% vốn (vị thế LONG tối đa 1,70 × vốn, có cắt lỗ).

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `dc08366`.
- Test: `test/test_mc_stress.py` (3 test mới).
- Số đo: `summary.shock` trong `data/_cache/book_wfa/20261003_120508/report.json`.

## Change Log
| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-03 | Tạo | dc08366 |
