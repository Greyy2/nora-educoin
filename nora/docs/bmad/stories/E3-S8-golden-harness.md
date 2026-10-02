# E3-S8: Golden harness: snapshot bit-identical của engine

- **Epic:** E3 Engine backtest, vốn & rủi ro
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người phát triển, tôi muốn một bộ snapshot mã hoá float bằng hex để so sánh chính xác từng bit, để mọi tối ưu hay tái cấu trúc chứng minh không đổi kết quả.

## Acceptance Criteria

1. **Given** ba kịch bản (`portfolio_synthetic`, `single_dca_filled`, `portfolio_real` trên BTC/SOL/DOGE perp), **When** chạy engine, **Then** mọi vị thế, lệnh, hàng đường vốn bằng snapshot `test/golden/*.json` (`test_golden_portfolio_synthetic`, `test_golden_single_dca_filled`, `test_golden_portfolio_real`).
2. **Given** một snapshot bị đổi 1 ulp, **When** so sánh, **Then** bị phát hiện (`test_golden_comparison_detects_one_bit_perturbation`).
3. **Given** chủ đích đổi ngữ nghĩa backtest, **When** cần cập nhật, **Then** chỉ sinh lại bằng `backend/utils/ops/run_limited.sh -- test/scripts/make_golden.py` và ghi lý do trong Change Log.

## Tasks / Subtasks

- [x] `test/golden_scenarios.py` (`hx`, `canonicalize`)
- [x] `test/scripts/make_golden.py`
- [x] 3 snapshot trong `test/golden/`
- [x] Test phát hiện xáo trộn 1 bit

## Dev Notes

- Bỏ qua id (dựa trên thời gian) và mọi thứ không tất định; `portfolio_real` chỉ đọc `data_root`.
- Quy tắc: không sửa snapshot để test qua. Mọi PR đụng engine phải chạy `test_golden_results.py` và `test_skip_idle.py`.

## Evidence

- Commit: `030c7f9` (message: golden 3/3 hai lần), `b179f2b` (golden 4/4 gồm test xáo trộn).
- Giữ bit-identical qua: mmap + skip-idle (`b179f2b`), cooldown (`edb26f4`, `portfolio_real` ghim `cooldown=0`), WFA danh mục (`e334716`), tái cấu trúc package (`6d35c0d`, `4e8dd61`), feed giả lập (`a3202c9`).
- Tests: `test/test_golden_results.py` (4).

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
