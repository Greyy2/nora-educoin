# E7-S3: Endpoint Monte Carlo ngày đồng bộ

- **Epic:** E7 Studio API
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn chạy Monte Carlo ngay trong UI sau khi WFA xong và nhận fan chart, histogram và gate, để đánh giá rủi ro cháy mà không chờ job nền.

## Acceptance Criteria

1. **Given** `{wfa_job_id, basis, ...}` hoặc `{daily_returns}`, **When** `POST /api/studio/book/mc`, **Then** trả `summary, fan, mdd_hist, ret_hist, gate, params` và `summary` trùng bit với `run_monte_carlo_daily` cùng seed (`test_endpoint_matches_run_monte_carlo_daily`).
2. **Given** thiếu hoặc thừa nguồn, **When** gọi, **Then** 422 (`test_endpoint_needs_exactly_one_source`).
3. **Given** `simulations > 10000`, `horizon_days > 730` hoặc chuỗi < 20 ngày hay chứa giá trị ≤ −1, **When** gọi, **Then** 422 (`test_endpoint_rejects_bad_limits`).
4. **Given** `wfa_job_id` chưa xong, không phải `book_wfa` hoặc không tồn tại, **When** gọi, **Then** 409, 422 hoặc 404.
5. **Given** kích thước tối đa (10000 mô phỏng, 730 ngày), **When** gọi, **Then** xong < 15 s (`test_endpoint_is_fast_at_max_size`).

## Tasks / Subtasks

- [x] `POST /book/mc` (Pydantic `McRequest`)
- [x] `run_monte_carlo_daily_detail`
- [x] Chọn cơ sở `extreme|level` từ `summary.oos_daily`
- [x] Gate ruin ≤ 5% (`MC_RUIN_MAX_PCT`)

## Dev Notes

- Code: `backend/api/routers/book.py`, `backend/carlo/monte_carlo.py`. Mặc định: 4000 mô phỏng, block 5, horizon 365, ngưỡng 30%, seed 7, scale 1.
- Thời gian thực tế ở kích thước mặc định chưa ghi log; mục tiêu "~10 s" trong vòng UI chưa có bằng chứng trong repo (chưa đo).

## Evidence

- Commit: `efe4fb2`.
- Tests: `test/test_book_mc_api.py` (9).

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
