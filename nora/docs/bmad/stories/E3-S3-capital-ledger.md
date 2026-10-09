# Story E3-S3: Sổ vốn chung (CapitalLedger)

## Status
Done

## Story
Là người nghiên cứu, tôi muốn mọi flow và tầng DCA lấy vốn từ một quỹ chung, để nhiều chiến lược chạy cùng lúc không thể dùng quá vốn.

## Acceptance Criteria
1. **Given** nhiều flow ngẫu nhiên, **When** chạy, **Then** bất biến vốn (`reserved ≤ equity × usage`, `free ≥ 0`) đúng ở mọi nến (`test_ledger_invariants_every_bar_random_multi_flow`).
2. **Given** danh sách lệnh con, **When** tính lại lãi/lỗ độc lập, **Then** khớp kết quả engine (`test_pnl_recomputed_independently_from_orders`).
3. **Given** hai flow cùng đòi vốn, **When** tổng vượt vốn trống, **Then** lệnh sau bị từ chối và đếm ở `rejected_for_capital` (`test_two_flows_cannot_over_allocate_capital`).
4. **Given** spot và vốn giảm, **When** mở lệnh mới, **Then** khối lượng co theo vốn hiện tại và vốn không âm (`test_spot_equity_never_negative_and_size_follows_equity`).

## Tasks / Subtasks
- [x] `reserve`/`release`/`settle`
- [x] PnL % trên vốn lúc mở lệnh
- [x] Đếm lệnh bị từ chối vì thiếu vốn

## Dev Notes
- Code: `backend/core/backtest/execution.py` (`CapitalLedger`). Đặc tả: `architecture.md` §5.6.
- Trước đây mỗi flow tự dùng 100% vốn (lỗi cũ, ghi trong `docs/signals_strategies.md`).

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code).
- Tests: `test/test_capital_ledger.py` (4), `test/test_signals_strategies.py::test_spot_equity_never_negative_and_size_follows_equity`.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
