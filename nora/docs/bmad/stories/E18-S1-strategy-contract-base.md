# Story E18-S1: Chuẩn hoá Strategy Contract BaseStrategy

## Status
Done

## Story
**Là** quant researcher, **tôi muốn** có một hợp đồng chiến lược thống nhất `BaseStrategy` với phương thức `evaluate(candles) -> signals`, **để** mọi chiến lược đều có thể chạy được trên cùng một Core Engine mà không cần chỉnh sửa engine.

## Acceptance Criteria
1. Lớp trừu tượng `BaseStrategy` được định nghĩa trong `backend.alpha.base`.
2. Phương thức `evaluate(candles: pd.DataFrame) -> pd.Series` nhận DataFrame nến đã đóng và trả về tín hiệu $1$ (Long), $-1$ (Short), hoặc $0$ (Hold).
3. Hỗ trợ khai báo metadata và schema tham số hoá dạng từ điển tĩnh (`parameters`).
4. Đảm bảo tính toán causal, tương thích parity giữa DSL và Python AST.

## Tasks / Subtasks
- [x] Định nghĩa lớp `BaseStrategy` (AC: 1, 2)
- [x] Tạo schema tham số và cấu trúc metadata (AC: 3)
- [x] Viết unit tests kiểm tra contract compliance và DSL parity (AC: 4)

## Dev Notes
- Tài liệu tham chiếu: [ADR-P10-alpha-contract.md](../architecture/decisions/ADR-P10-alpha-contract.md), [coding-standards.md](../architecture/coding-standards.md).
- File triển khai: `backend/alpha/base.py`.
- Testing: `test/test_alpha_contract.py`, `test/test_strategy_dsl_parity.py`, `test/test_pydsl_parity.py`, `test/test_pydsl_dsl.py`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Hoàn tất hợp đồng BaseStrategy.
- **File List:**
  - `backend/alpha/base.py`
  - `test/test_alpha_contract.py`

## QA Results
- **Gate:** PASS
- **Commit:** `3dd61f1`
- **Tests:**
  - `pytest test/test_alpha_contract.py` PASS
  - `pytest test/test_strategy_dsl_parity.py` PASS
  - `pytest test/test_pydsl_parity.py` PASS
  - `pytest test/test_pydsl_dsl.py` PASS

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-07 | 1.0.0 | Tạo và kiểm chứng BaseStrategy contract | BMAD Dev |
| 2026-10-09 | 1.0.1 | Cập nhật QA Results với commit và test thực tế | BMAD Dev |
