# E8-S3: Trang Backtest → WFA → Monte Carlo trong một vòng

- **Epic:** E8 UI v2
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn chạy backtest, WFA và Monte Carlo liền mạch trên một trang, có thể chia sẻ bằng đường dẫn, để kiểm chứng một chiến lược không cần CLI.

## Acceptance Criteria

1. **Given** form Backtest, **When** gửi, **Then** nhận `job_id`, panel job hiển thị `queued → running → done` và log, rồi kết quả.
2. **Given** WFA, **When** chọn tham số cố định (một cấu hình mỗi chiến lược) hoặc chọn lại ở IS, **Then** gửi đúng dạng `strategies[{id, configs}]` hoặc `candidates + n`.
3. **Given** WFA xong, **When** chạy Monte Carlo, **Then** hiển thị fan chart, histogram MDD/lãi và gate ruin.
4. **Given** `/backtest?wfa=<job_id>`, **When** mở, **Then** form WFA điền sẵn từ job đó.
5. **Given** job lỗi hoặc 429, **When** hiển thị, **Then** có thông báo lỗi rõ, không trắng trang (`ErrorBoundary`).

## Tasks / Subtasks

- [x] `pages/Backtest.jsx` (stepper)
- [x] `components/{JobPanel,WfaResult,McResult,GateList,StrategyPicker}.jsx`
- [x] `hooks/useJob.js` poll 2 s
- [x] Deep link `?wfa=`
- [x] Vòng thật Alpha build → Backtest → WFA → MC

## Dev Notes

- Code: `frontend/src/v2/pages/Backtest.jsx` và `v2/components/*`, `v2/api.js`. Poll `GET /jobs/{id}` mỗi 2 s.
- Mock chỉ bật khi `npm run dev` với `?mock=1`, không vào bundle production.

## Evidence

- Commits: `efe4fb2`, `876ce9e` (deep link `?wfa=`).
- Đo thật (đọc từ `data/_cache/api_jobs/*/job.json`): build 71,1 s (`--only breakout_4h_long --n 8`), backtest 6,6 s, WFA 53,5 s; Monte Carlo đồng bộ, thời gian chưa ghi log.
- Xác nhận bằng ảnh chụp headless Chrome (message `876ce9e`); không có test giao diện tự động.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
