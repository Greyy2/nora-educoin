# Story E8-S1: Khung UI v2: thanh bên, định tuyến, chủ đề Sáng/Tối, tương thích trình duyệt

## Status
Done

## Story
Là người dùng UI, tôi muốn khung điều hướng rõ với ba trang chính, nhóm Legacy tách riêng và chuyển Sáng/Tối nhìn thấy được, để dùng được trên trình duyệt công ty và không bị chói.

## Acceptance Criteria
1. **Given** truy cập `/`, **When** tải app, **Then** chuyển tới `/portfolio`; ba trang chính `/portfolio`, `/backtest`, `/alpha` có trên thanh bên.
2. **Given** các đường dẫn cũ (`/scan`, `/wfa`, `/monte-carlo`, `/runs`, `/strategies`, `/miner`...), **When** truy cập, **Then** chuyển hướng tới trang Legacy tương ứng (`frontend/src/App.jsx`).
3. **Given** lần đầu vào, **When** chưa có lựa chọn, **Then** theo `prefers-color-scheme`; chọn Sáng/Tối thì nhớ ở `localStorage` khoá `nora-theme`, lỗi `localStorage` không làm hỏng trang.
4. **Given** trình duyệt chặn đường dẫn chứa "miner", **When** Vite nạp trang, **Then** không có file/route nào có tên đó (`frontend/src/pages/PhienDao.jsx`).
5. **Given** `npm run build`, **When** chạy, **Then** build thành công (kiểm bằng tay).

## Tasks / Subtasks
- [x] `v2/layout/Shell.jsx`, `v2/v2.css`
- [x] Route v2 và nhóm Legacy
- [x] Công tắc Sáng/Tối có nhãn (`aria-pressed`)
- [x] Đổi `Miner.jsx` → `PhienDao.jsx`, favicon inline
- [x] Biểu đồ SVG tự vẽ, không thư viện

## Dev Notes
- Code: `frontend/src/App.jsx`, `v2/layout/Shell.jsx`. Dev: `npm run dev` (cổng 18011, proxy `/api` → 18010).
- Chưa có test tự động cho frontend (E8-S7). Bundle production là một file JS ≈ 583 KB chưa nén (E11-S4).

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commits: `efe4fb2` (khung v2, 162 KB gzip JS lúc đó, build OK), `b0419d5` (công tắc Sáng/Tối có nhãn), `cc68087` (đổi tên file do chính sách chặn "miner").
- Xác nhận bằng tay (headless Chrome, theo message `876ce9e`); không có test tự động.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
