# E7-S7: Danh mục chiến lược, kho alpha và tương thích API Studio cũ

- **Epic:** E7 Studio API
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn UI đọc được catalog chiến lược (kèm tham số mặc định), vũ trụ, cửa sổ và kho alpha, và API Studio cũ vẫn chạy, để trang Alpha dựng được và không làm hỏng tích hợp đang có.

## Acceptance Criteria

1. **Given** `GET /api/studio/book/`, **When** đọc, **Then** có `catalog` (= `candidates`), `latest_wfa` (= `wfa`), `universe`, `windows`, và `default_params` bằng mức giữa của mỗi khoá `space` (`test_catalog_default_params_universe_windows`, `test_default_params_match_run_book_backtest_mid_params`).
2. **Given** `GET /api/studio/alphas`, **When** gọi, **Then** `{registry, book}` (null nếu thiếu file) (`test_alphas_endpoint`).
3. **Given** `GET /jobs?kind=...`, **When** lọc, **Then** chỉ trả job đúng loại kèm nhãn (`test_job_labels_and_kind_filter`).
4. **Given** `/api/studio/simulate` và `/wfa/run` trên bố cục venue, **When** dữ liệu qua gate, **Then** chạy được (`test_data_layout.py::test_simulate_and_wfa_work_on_venue_layout`); dữ liệu không qua gate thì bị chặn (E1-S4).
5. **Given** test, **When** chạy, **Then** không chạm DB production (`test_tests_never_touch_prod_db`).

## Tasks / Subtasks

- [x] `GET /book/` mở rộng, `GET /alphas`
- [x] Lọc job theo `kind`, nhãn job
- [x] Giữ `/simulate`, `/scan`, `/wfa/run`, `/monte-carlo/run` và SQLite (`store.py`)
- [>] Route MySQL cũ trong `main.py`: dọn ở E11-S5

## Dev Notes

- Code: `backend/api/routers/book.py`, `studio.py`, `backend/api/jobs/store.py`. Hợp đồng: `docs/ui_contract.md` §1.
- `catalog` và `candidates` cùng nội dung chỉ để tương thích; UI đọc `catalog || candidates`.

## Evidence

- Commit: `efe4fb2`; phần Studio cũ trong `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code).
- Tests: `test/test_book_ui_backend.py` (10), `test/test_round3_completion.py` (17), `test/test_gate_integration.py` (5).

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
