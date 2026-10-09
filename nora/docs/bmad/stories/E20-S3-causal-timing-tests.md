# Story E20-S3: Bộ test kiểm định causal signal timing bit-identical

## Status
Done

## Story
**Là** kỹ sư QA, **tôi muốn** có bộ test tự động chuyên biệt kiểm định tính bất biến và strictly causal của signal timing, **để** ngăn chặn mọi hồi quy tiềm ẩn trong tương lai.

## Acceptance Criteria
1. Bộ test phát hiện được nếu một kernel hoặc chiến lược đọc dữ liệu từ nến tương lai (`check_signal_lookahead.py`).
2. Kiểm tra sự kiện tín hiệu và timing (`test_signal_event.py`).
3. So sánh đối soát Nautilus S9 harness (`s9_compare.py` + `s9_results.json`).
4. Toàn bộ test suite chạy ổn định và đưa vào pipeline kiểm thử liên tục.

## Tasks / Subtasks
- [x] Chạy test kiểm tra lookahead detection (AC: 1)
- [x] Chạy test kiểm tra signal events (AC: 2)
- [x] Đối soát với harness S9 Nautilus (AC: 3, 4)

## Dev Notes
- Tài liệu tham chiếu: [test-strategy.md](../architecture/test-strategy.md), [coding-standards.md](../architecture/coding-standards.md).
- File triển khai: `test/test_signal_event.py`, `test/scripts/check_signal_lookahead.py`.
- Testing: `test/test_signal_event.py`, `test/scripts/nautilus_diff/s9_compare.py`, `test/scripts/check_signal_lookahead.py`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Hoàn tất bộ test kiểm định timing và lookahead. Đã commit test suites.
- **File List:**
  - `test/test_signal_event.py`
  - `test/scripts/check_signal_lookahead.py`
  - `test/scripts/nautilus_diff/s9_compare.py`

## QA Results
- **Gate:** PASS
- **Commit:** `546e475`
- **Tests:**
  - `pytest test/test_signal_event.py` PASS
  - `python -m test.scripts.check_signal_lookahead` PASS
  - `python -m test.scripts.nautilus_diff.s9_compare` đối soát với `s9_results.json` PASS

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-07 | 1.0.0 | Tạo test suite kiểm định causal timing | BMAD Dev |
| 2026-10-09 | 1.0.1 | Chuyển sang Review, cập nhật test thật | BMAD Dev |
| 2026-10-09 | 1.0.2 | Hoàn tất nghiệm thu, chuyển sang Done với commit `546e475` | BMAD Dev |
