# Story E12-S3: Khung chạy 15m / 1h / 4h chọn trước khi sinh tham số

## Status
Done

## Story
Là người chạy thử nghiệm, tôi muốn chọn khung nến mô phỏng (15m/1h/4h) trước khi sinh tham số, để mỗi lần chạy nhanh hơn 1m hàng chục lần.

## Acceptance Criteria
1. **Given** khung chạy 15m, **When** chạy phễu 10k alpha, **Then** tốc độ ≥ 80 alpha/s (500k ≈ 1,7 h); 1h ≈ 103 alpha/s.
2. **Given** khung tín hiệu nhỏ hơn khung chạy, **When** sinh tham số, **Then** khung được nâng lên (`lift_frames`) hoặc chiến lược bị từ chối với 422 (`generate.incompatible`).
3. **Given** API/UI Backtest, WFA, phễu, preset, **When** tạo job, **Then** đều có trường `timeframe` (mặc định 15m) và resume không trộn kết quả hai khung.

## Tasks

- [x] `base_frame` trong engine/portfolio/BacktestJob
- [x] Trường timeframe ở API + UI
- [x] Preset ghi khung tối ưu, cảnh báo lệch khung (P0.3c)

## Tasks / Subtasks
- [x] Hoàn thành triển khai và kiểm thử

## Dev Notes
Roadmap P1.17–P1.18, P0.3c.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `fa0a93b`, `89f4210`, `1b30398`, `21d8adb`.
- Test: `test/test_run_modes.py::test_timeframe_lifts_frames_and_blocks_incompatible_strategies`, `test_basic_mode_timeframe_mismatch_warning`.
- Số đo: roadmap P1.17.

## Change Log
| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-03 | Tạo story ghi nhận P1.17 + P0.3c | fa0a93b, 21d8adb |
