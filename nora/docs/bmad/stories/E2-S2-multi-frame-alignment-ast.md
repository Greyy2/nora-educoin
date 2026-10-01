# E2-S2: Căn khung đa khung (avail_time) và bộ đánh giá AST

- **Epic:** E2 Tín hiệu & chiến lược
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn điều kiện chiến lược dùng được nhiều khung thời gian mà nến 1m chỉ thấy nến khung lớn khi nó đã đóng, để không có look-ahead giữa các khung.

## Acceptance Criteria

1. **Given** kernel khung 4h, **When** ở nến 1m trước khi nến 4h đóng, **Then** giá trị 4h chưa hiện; chỉ hiện từ nến 1m đầu tiên sau khi 4h đóng (`test_4h_lookahead_candle_visibility`, `test_higher_frame_kernel_visible_only_after_close`).
2. **Given** dữ liệu tương lai bị sửa, **When** chạy lại engine, **Then** tín hiệu và lệnh trước điểm sửa không đổi (`test_no_lookahead_when_future_modified`).
3. **Given** AST có `"index": 1`, **When** đánh giá, **Then** đọc giá trị của nến liền trước trên cùng khung (`test_index_reads_previous_bar`).
4. **Given** AST ngẫu nhiên, **When** đánh giá bằng bộ vector và bộ từng nến, **Then** hai kết quả giống nhau (`test_vector_evaluator_matches_scalar_on_random_asts`).

## Tasks / Subtasks

- [x] `merge_asof` theo `decision_time = open_1m + 1m` và `avail_time = open_F + độ dài F`
- [x] Cột trễ `index` tới 500 nến
- [x] `VectorEvaluator` (numpy) cùng ngữ nghĩa `LogicEvaluator`
- [x] Gom tham chiếu `(frame, column, lag)` để chỉ tính kernel cần dùng

## Dev Notes

- Code: `backend/core/backtest/engine.py` (căn khung, `FRAME_MS`, `collect_field_refs`), `backend/core/signals/evaluator.py`.
- Khung hỗ trợ: 1m, 5m, 15m, 1h, 4h, 24h; luôn nạp thêm 4h để tương thích.
- Khoá nội bộ `__bar_open_time` tránh trùng cột `open_time` mà AST có thể dùng.

## Evidence

- Commit: `808d7f4` (baseline, thêm `test_causal_engine.py` 294 dòng) và `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code).
- Tests: `test/test_causal_engine.py` (4), `test/test_signals_strategies.py`.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
