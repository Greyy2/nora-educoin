# E5-S1: Kho alpha và cấu hình Binance Futures testnet cho alpha perp

- **Epic:** E5 Alpha & sổ chiến lược
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn alpha đạt gate được ghi vào kho kèm đủ bằng chứng để tái lập và một cấu hình testnet mô tả đúng hành vi đã mô phỏng, để người viết bot không phải đoán quy tắc.

## Acceptance Criteria

1. **Given** các kết quả `optimize_alphas`, **When** dựng kho, **Then** chỉ cặp có `verdict="ALPHA"` vào `registry.json`, `pairs_evaluated` bằng số cặp đã chạy (`test_registry_and_testnet_export`).
2. **Given** một alpha, **When** ghi vào kho, **Then** AST đã thay hết tham số (không còn khoá `param`) và có `data.sha256_1m` (`test_registry_and_testnet_export`).
3. **Given** alpha `market="perp"`, **When** xuất cấu hình, **Then** `margin_type="ISOLATED"`, DCA `time_in_force="GTX"`, SL `STOP_MARKET` reduce-only, `leverage` khớp `position.leverage` (`test_registry_and_testnet_export`).
4. **Given** alpha spot, **When** xuất cấu hình testnet, **Then** `ValueError` (Binance Futures chỉ nhận perp) (`test_registry_and_testnet_export`).
5. **Given** thư mục `robustness_*.json` cạnh `results.json`, **When** dựng kho, **Then** mục `robustness` được gắn vào đúng alpha.

## Tasks / Subtasks

- [x] `build_registry`, `write_registry`, `testnet_config`
- [x] CLI `build_alpha_registry <thư mục> [--out data/alphas]`
- [x] Ghi commit code (`code.commit`, `dirty_backend`) và `data.sha256_1m`
- [x] Tài liệu `alpha_pipeline.md` §4

## Dev Notes

- Code: `backend/optimize/registry.py`, `backend/cli/build_alpha_registry.py`. Đặc tả: `architecture.md` §8.3.
- Cấu hình testnet là **file cấu hình**; chưa có bot đọc nó (E9-S1).

## Evidence

- Commit: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code), làm mới ở `45f734e`.
- Test: `test/test_pipeline_e2e.py` (2 test, tham số hoá theo thị trường).
- Hiện vật: `data/alphas/registry.json` (1 alpha), `data/alphas/testnet/trend_long_perp__SOL.json`.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
