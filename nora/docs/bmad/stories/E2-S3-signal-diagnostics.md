# E2-S3: Kiểm tra tín hiệu có mang thông tin trước khi ghép chiến lược

- **Epic:** E2 Tín hiệu & chiến lược
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn biết một tín hiệu có dự báo giá tương lai không trước khi tốn công tối ưu, để loại sớm các tín hiệu vô nghĩa.

## Acceptance Criteria

1. **Given** dữ liệu có edge cài sẵn, **When** chạy diagnostics, **Then** kết luận `CO_THONG_TIN` (`test_diagnostics_detects_planted_edge`, `test_planted_edge_detection`).
2. **Given** random walk, **When** chạy diagnostics, **Then** không bao giờ ra `CO_THONG_TIN` (`test_diagnostics_rejects_random_walk`, `test_random_walk_falsification`).
3. **Given** các mốc 15 phút, 1h, 4h, 24h, **When** thống kê, **Then** chỉ giữ sự kiện cách nhau ≥ h để t-stat không bị thổi phồng; ngưỡng `CO_THONG_TIN` là |t| ≥ 3 cùng dấu ở 60% đầu và 40% sau (theo `docs/signals_strategies.md` §3).

## Tasks / Subtasks

- [x] Vào ở open của phút có giao dịch kế tiếp
- [x] Đối chứng = vào ở mọi phút trong cùng khoảng
- [x] Cột "sau phí" theo chi phí khứ hồi của venue
- [x] CLI `check_signals_strategies` chạy 10 tài sản

## Dev Notes

- Code: `backend/core/signals/diagnostics.py`; CLI `backend/cli/check_signals_strategies.py` (`--workers`, `--assets`); kết quả `data/_cache/reports/step2_<thời điểm>.json`.
- Ngưỡng |t| ≥ 3 vì kiểm nhiều tín hiệu cùng lúc; chưa hiệu chỉnh đa kiểm định chính thức (E10-S1).

## Evidence

- Commit: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code).
- Tests: `test/test_signals_strategies.py`, `test/test_pipeline_regression.py`.
- Báo cáo chạy thật: `data/_cache/reports/step2_20260930_1604.json`, `step2_20260930_1608.json` (nội dung chưa đọc lại trong đợt này).

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
