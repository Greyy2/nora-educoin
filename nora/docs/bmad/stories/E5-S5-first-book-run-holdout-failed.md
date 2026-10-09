# Story E5-S5: Sổ breakout_4h đầu tiên trên dữ liệu thật: HOLDOUT_FAILED

## Status
Done

## Story
Là người nghiên cứu, tôi muốn ghi nhận trung thực kết quả của sổ đầu tiên chạy trên dữ liệu thật, kể cả khi trượt holdout, để không có cấu hình testnet nào được cấp cho một sổ chưa đạt.

## Acceptance Criteria
1. **Given** sổ `breakout_4h_long + breakout_4h_short`, **When** đọc `data/alphas/book.json`, **Then** `status = "HOLDOUT_FAILED"`, `holdout_pass = false`.
2. **Given** trạng thái đó, **When** liệt kê `data/alphas/testnet/`, **Then** không có `book.json` (chỉ có `trend_long_perp__SOL.json` của alpha đơn tài sản).
3. **Given** bằng chứng trong `evidence.final`, **When** đọc, **Then** dev2 +26,76% (level) / +17,26% (extreme), holdout −4,06% (level) / −7,38% (extreme).
4. **Given** `GET /api/studio/book/`, **When** UI đọc, **Then** trạng thái `HOLDOUT_FAILED` hiển thị trên trang Alpha (E8-S4).

## Tasks / Subtasks
- [x] Chạy `build_strategy_book` đủ 7 ứng viên (`data/_cache/book/20261001_115808`)
- [x] Chạy `validate_book` trên sổ (`data/_cache/book_wfa/20261001_121903`)
- [x] Ghi `data/alphas/book.json` với `HOLDOUT_FAILED`
- [x] Ghi nhận trong PRD (G2, R-4)

## Dev Notes
- Số liệu `data/alphas/book.json`: dev2 level +26,76%, MDD 14,16%, 389 lệnh, 8/8 tài sản có lãi; extreme +17,26%, MDD 15,22%, 7/8; holdout level −4,06%, MDD 17,07%, 186 lệnh; extreme −7,38%, MDD 17,65%. Rủi ro/lệnh 0,5%. Ba ứng viên khác bị loại ở A/B (`rejected_candidates`, ví dụ `trend_long` dev2 level −2,94%).
- WFA danh mục của hai chiến lược này qua 6/6 check (MC ngày P(MDD ≥ 30%) = 3,62%), nhưng holdout trượt: gate WFA không đảm bảo holdout.
- Kết luận vận hành: **không có cấu hình testnet cho sổ**. Hướng đi tiếp: E10-S4.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- **Commit:** `3dd61f1`
- **Tests:** `test/test_golden_results.py`
- Commit: `935d4d1` (message ghi đúng các số trên: dev2 +26,8% / extreme +17,3%, WFA 6/6, MC 3,6%, holdout −4,1% / −7,4%).
- Hiện vật: `data/alphas/book.json` (sinh bởi `20261001_115808`, code `06ae13b`, `dirty_backend=true`); `git show 935d4d1 --stat` có `alphas/book.json`.
- Lưu ý: giai đoạn D của sổ đã chấm ít nhất 2 lần (cũng `20261001_152813`, chỉ `breakout_4h_long`); xem R-2.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
