# E7-S4: Build không ghi đè sổ đang xuất bản; publish có kiểm soát

- **Epic:** E7 Studio API
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người vận hành, tôi muốn việc hiệu chỉnh tham số trên UI không làm đổi sổ đang xuất bản, và chỉ chép sang `data/alphas/` khi tôi xác nhận, để thử nghiệm không phá sổ hiện hành.

## Acceptance Criteria

1. **Given** job `book_build`, **When** chạy, **Then** ghi vào `<job_dir>/alphas`, `data/alphas/` không đổi; client không đặt được `--out`.
2. **Given** job build xong có `alphas/book.json`, **When** `POST /book/publish {job_id}`, **Then** chép `book.json` sang `data/alphas/`, và `testnet/book.json` chỉ khi job có (holdout đạt); nếu không thì xoá testnet cũ (`test_publish_copies_book_and_testnet_and_cleans_stale`).
3. **Given** job không tồn tại, sai loại, chưa xong, hoặc thiếu `alphas/book.json`, **When** publish, **Then** 404, 422, 409, 409 (`test_publish_errors`).
4. **Given** biến `NORA_ALPHAS_DIR`, **When** publish, **Then** ghi vào thư mục đó (dùng cho test).
5. **Given** ghi file, **When** publish, **Then** dùng file tạm + `os.replace` nên người đọc không thấy file dở dang.

## Tasks / Subtasks

- [x] `book_build` luôn ghi vào thư mục job
- [x] `POST /book/publish`
- [x] `publish_book` ghi nguyên tử
- [x] Nút "Xuất bản sổ này" có hộp xác nhận (E8-S4)

## Dev Notes

- Code: `backend/api/routers/book.py`, `backend/optimize/book_export.py`, `backend/api/jobs/batch.py`.
- Rủi ro còn lại: `publish` ghi đè sổ mà không cần xác thực (R-5, E11-S1/S2).

## Evidence

- Commit: `876ce9e` (message: build tách khỏi `alphas/`, publish, `NORA_ALPHAS_DIR`; 430 test qua; vòng thật Alpha build → Backtest → WFA → Monte Carlo → Danh mục kiểm bằng headless Chrome).
- Tests: `test/test_book_api.py` (publish), `test/test_strategy_book.py`.
- Job build thật: `data/_cache/api_jobs/20261001_152812_e10d23` (`--only breakout_4h_long --n 8`, 71,1 s).

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
