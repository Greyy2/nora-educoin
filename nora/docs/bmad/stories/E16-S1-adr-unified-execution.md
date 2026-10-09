# Story E16-S1: — ADR kiến trúc thực thi thống nhất (P6.0)

## Status
Done

## Story
**Là** kỹ sư hệ thống, **tôi muốn** hoàn thiện — ADR kiến trúc thực thi thống nhất (P6.0), **để** hệ thống vận hành đúng chuẩn định lượng và kiến trúc Nora.

## Acceptance Criteria
1. Given hiện trạng có 4 bản logic khớp lệnh/rủi ro, When đọc ADR, Then có bảng hiện trạng đã kiểm chứng và mô tả mức parity chính xác (sim bit-identical, sim ↔ sàn trong dung sai).
2. Given ba quyết định đã chốt với người dùng (phạm vi P6.0–P6.9, nghỉ hưu `PositionTracker` ở P6.9, vốn rủi ro là sổ vốn ảo), When đọc ADR, Then cả ba được ghi nguyên văn kèm hệ quả.
3. Given sáu mặc định D1–D6 chưa được người dùng xác nhận riêng, When đọc ADR, Then chúng nằm ở mục "Mặc định chờ duyệt" và roadmap giữ P6.0 ở `doing` cho tới khi được duyệt.
4. Given roadmap, When mở mục P6, Then có P6.0–P6.9 đúng định dạng bảng với "Xong khi" riêng từng dòng.

## Tasks

- [x] Viết `adr-p6-unified-execution.md`
- [x] Thêm mục P6 vào `roadmap.md`; thêm epic E16 vào `epics.md` và `sprint-status.yaml`
- [x] Sửa doc lệch trong `architecture.md` (đường dẫn `core/execute/`, `core/params/builder.py`)
- [x] Người dùng duyệt D1–D6 (đóng P6.0, 2026-10-06)

## Tasks / Subtasks
- [x] Hoàn thành triển khai và kiểm thử

## Dev Notes
Nguồn của kiến trúc đích: NautilusTrader (`ExecutionClient`, `ExecutionEngine`, `RiskEngine`, sandbox dùng chung `OrderMatchingEngine` với backtest). Khác biệt có chủ ý: Nora giữ kernel numba làm backtest sản xuất duy nhất (mục tiêu 500k alpha ≤ 4 h) và chỉ dùng đường event cho paper/demo/live; không có message bus (không cần cho nghiên cứu).

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- **Tests:** `test/test_ops_units.py`, `test/scripts/nautilus_diff/check_baseline.py`
- Commit: `e14ce4a` (ADR, roadmap P6, E16).
- Duyệt D1–D6: người dùng, 2026-10-06.

## Change Log
| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-06 | Tạo | (chưa commit) |
