# E2-S4: Thư viện tín hiệu, chiến lược mẫu, không gian tối ưu và tham số tín hiệu

- **Epic:** E2 Tín hiệu & chiến lược
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn một thư viện tín hiệu và chiến lược có cấu trúc, với ngưỡng tham số hoá, để tối ưu tham số mà không sửa AST bằng tay.

## Acceptance Criteria

1. **Given** AST có `{"param": "adx_min", "default": 20}`, **When** truyền `sig.adx_min=25`, **Then** cây được thay giá trị 25; thiếu giá trị thì dùng `default` và tham số lạ báo lỗi (`test_placeholders_resolve_and_errors`).
2. **Given** `param_candidates` của WFA có khoá tín hiệu, **When** chạy, **Then** ngưỡng tín hiệu đổi theo ứng viên (`test_wfa_param_candidates_with_signal_params`, `test_snapshot_candidates_validation`).
3. **Given** các bot DCA mẫu, **When** dựng tham số, **Then** mọi tầng DCA vừa ngân sách vốn (`test_library_dca_bots_fit_budget`).
4. **Given** scan nhiều tài sản, **When** có tài sản không hợp thị trường, **Then** bị bỏ qua kèm lý do và kết quả tái lập (`test_scan_multi_asset_skips_invalid_and_is_deterministic`).

## Tasks / Subtasks

- [x] `SIGNALS` (8), `KERNEL_STRATEGIES` (8), `OPTIMIZATION_SPACES` (5)
- [x] `params_template.resolve_placeholders`, `split_params`
- [x] Mẫu Studio `templates.py` (`/samples`)
- [x] Scan nhiều tài sản (`/api/studio/scan`)

## Dev Notes

- Code: `backend/core/strategy/strategy_library.py`, `params_template.py`, `templates.py`; scan ở `backend/api/jobs/scan.py`.
- Mọi chiến lược mẫu có SL cứng và/hoặc timeout, khác với bot OKX (21/28 bot không cắt lỗ, theo `docs/signals_strategies.md` §5).

## Evidence

- Commit: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code); `edb26f4` đổi preset DCA 20% → 19% để đủ 5 tầng.
- Tests: `test/test_optimization_plumbing.py` (7), `test/test_dca_cooldown.py::test_library_dca_bots_fit_budget`.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
