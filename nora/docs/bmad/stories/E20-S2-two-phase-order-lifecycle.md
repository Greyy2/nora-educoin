# Story E20-S2: Hạch toán vòng đời lệnh hai pha không rò rỉ dữ liệu

## Status
Done

## Story
**Là** quant engineer, **tôi muốn** vòng đời lệnh được hạch toán tách biệt 2 pha rõ ràng: Pha 1 khám phá tín hiệu và cập nhật lệnh chờ; Pha 2 xử lý khớp lệnh nội bar theo trình tự chạm giá bi quan, **để** mô phỏng chính xác hành vi khớp lệnh trên sàn thật.

## Acceptance Criteria
1. Tách biệt hoàn toàn pha sinh tín hiệu (Phase 1) và pha khớp lệnh nội bar (Phase 2).
2. Xử lý chạm giá theo mô hình OHLC bi quan: nếu cả Stop-Loss và Take-Profit đều nằm trong biên độ $[Low, High]$, vị thế luôn bị xử lý chạm Stop-Loss trước.
3. Cập nhật ký quỹ, phí, và funding rate đúng thời điểm diễn ra sự kiện.
4. Đối soát đạt chuẩn 332/332 baseline parity với NautilusTrader.

## Tasks / Subtasks
- [x] Cài đặt state machine quản lý vòng đời lệnh 2 pha (AC: 1)
- [x] Áp dụng quy tắc xử lý chạm giá bi quan cho SL/TP (AC: 2)
- [x] Tích hợp kế toán ký quỹ và phí khứ hồi (AC: 3)
- [x] Chạy kiểm tra Nautilus parity 332/332 (AC: 4)

## Dev Notes
- Tài liệu tham chiếu: [engine-spec.md](../architecture/engine-spec.md).
- File triển khai: `backend/core/engine/`.
- Testing: `test/test_intrabar_path.py`, `test/test_kernel_step_parity.py`, `test/scripts/nautilus_diff/check_baseline.py`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Hoàn tất hạch toán 2 pha. Đã commit mã nguồn engine và test parity.
- **File List:**
  - `backend/core/`
  - `test/test_intrabar_path.py`
  - `test/test_kernel_step_parity.py`

## QA Results
- **Gate:** PASS
- **Commit:** `64a7a43`, `546e475`
- **Tests:**
  - `pytest test/test_intrabar_path.py` PASS
  - `pytest test/test_kernel_step_parity.py` PASS
  - `python -m test.scripts.nautilus_diff.check_baseline` PASS (332/332 cases matching NautilusTrader)

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-07 | 1.0.0 | Triển khai hạch toán 2 pha | BMAD Dev |
| 2026-10-09 | 1.0.1 | Chuyển sang Review, cập nhật test thật | BMAD Dev |
| 2026-10-09 | 1.0.2 | Hoàn tất nghiệm thu, chuyển sang Done với commit `64a7a43`, `546e475` | BMAD Dev |
