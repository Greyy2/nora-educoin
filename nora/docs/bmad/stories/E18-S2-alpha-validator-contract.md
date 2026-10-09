# Story E18-S2: Trình xác thực Alpha Validator RUN ADAPT REJECT

## Status
Done

## Story
**Là** kỹ sư kiểm định chất lượng, **tôi muốn** có bộ validator tự động phân loại code chiến lược người dùng nộp vào 3 mức `RUN`, `ADAPT`, hoặc `REJECT`, **để** ngăn chặn lỗi cú pháp, lookahead bias và hỏng runtime trước khi đưa vào engine.

## Acceptance Criteria
1. Module validator phân tích AST của mã nguồn Python chiến lược.
2. Trả về `RUN` nếu chiến lược kế thừa đúng `BaseStrategy` và tuân thủ các quy tắc causal.
3. Trả về `ADAPT` nếu chiến lược viết theo phong cách tự do nhưng có thể bọc qua adapter tiêu chuẩn.
4. Trả về `REJECT` nếu mã nguồn vi phạm bảo mật, có lookahead hoặc sai format không thể khắc phục, kèm thông báo lỗi chi tiết.

## Tasks / Subtasks
- [x] Xây dựng bộ phân tích AST cho code chiến lược (AC: 1)
- [x] Cài đặt logic phân loại 3 trạng thái RUN / ADAPT / REJECT (AC: 2, 3, 4)
- [x] Viết unit tests kiểm thử contract validator (AC: 4)

## Dev Notes
- Tài liệu tham chiếu: [ADR-P10-alpha-contract.md](../architecture/decisions/ADR-P10-alpha-contract.md), [api-spec.md](../architecture/api-spec.md).
- File triển khai: `backend/alpha/validator.py`.
- Testing: `test/test_alpha_contract.py`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Validator hoạt động ổn định và an toàn.
- **File List:**
  - `backend/alpha/validator.py`
  - `test/test_alpha_contract.py`

## QA Results
- **Gate:** PASS
- **Commit:** `3dd61f1`
- **Tests:**
  - `pytest test/test_alpha_contract.py` PASS

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-07 | 1.0.0 | Hoàn tất bộ Alpha Validator | BMAD Dev |
| 2026-10-09 | 1.0.1 | Cập nhật QA Results với commit và test thực tế | BMAD Dev |
