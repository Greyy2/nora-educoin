# Story E19-S3: Đồng bộ toàn bộ các trang UI với MetaProvider

## Status
Done

## Story
**Là** người dùng, **tôi muốn** danh sách đồng coin, khung thời gian và chiến lược trên các trang Backtest, Funnel, Alpha Lab và Live đều lấy từ cùng một nguồn dữ liệu thật, **để** không còn tình trạng dropdown bị lệch hoặc chọn coin không có dữ liệu.

## Acceptance Criteria
1. Trang `Backtest.jsx` sử dụng danh sách coin và timeframe từ `useCatalog()`.
2. Trang `Funnel.jsx` và `AlphaCatalog.jsx` đọc danh mục chiến lược và metrics trực tiếp từ meta.
3. Không còn danh sách hardcode mảng coin `["BTC", "ETH"]` trong bất kỳ component nào của `frontend/src/pages/`.
4. Hoàn tất các trường động `trades_from`, `meta.stress`, `limits.book_mc`, `metrics.defs`.

## Tasks / Subtasks
- [x] Refactor `Backtest.jsx` chuyển sang dùng `useCatalog()` (AC: 1, 3)
- [x] Refactor `Funnel.jsx`, `AlphaCatalog.jsx` (AC: 2, 3)
- [x] Rà soát và gỡ bỏ toàn bộ hardcoded lists trong `frontend/src/` (AC: 3, 4)

## Dev Notes
- Tài liệu tham chiếu: [ux-design.md](../ux-design.md).
- File triển khai: `frontend/src/pages/Backtest.jsx`, `frontend/src/pages/Funnel.jsx`, `frontend/src/pages/AlphaCatalog.jsx`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Toàn bộ trang đã tiêu thụ metadata động từ MetaProvider. Đã commit toàn bộ trường động (`trades_from`, `meta.stress`, `limits.book_mc`).
- **File List:**
  - `frontend/src/pages/Backtest.jsx`
  - `frontend/src/pages/Funnel.jsx`
  - `frontend/src/pages/AlphaCatalog.jsx`

## QA Results
- **Gate:** PASS
- **Commit:** `f4864d5`, `0c7f22f`
- **Tests:**
  - Grep hằng viết cứng coin/timeframe trong `frontend/src/pages` = rỗng
  - `cd frontend && npm run build` PASS
  - `cd frontend && npm run api:check` PASS
  - Playwright E2E so khớp số liệu UI với payload API

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-07 | 1.0.0 | Đồng bộ UI các trang với MetaProvider | BMAD Dev |
| 2026-10-09 | 1.0.1 | Chuyển sang Review, cập nhật commit và test thực tế | BMAD Dev |
| 2026-10-09 | 1.0.2 | Hoàn tất nghiệm thu, chuyển sang Done với commit `0c7f22f` | BMAD Dev |
