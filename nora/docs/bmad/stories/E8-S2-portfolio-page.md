# Story E8-S2: Trang Danh mục

## Status
Done

## Story
Là người theo dõi danh mục, tôi muốn một trang thấy NAV, rủi ro và vị thế trong một nơi, để biết tình trạng danh mục trong vài giây.

## Acceptance Criteria
1. **Given** dữ liệu có sẵn, **When** mở `/portfolio`, **Then** thấy KPI kèm sparkline, NAV so với BTC với dải drawdown, panel rủi ro và ký quỹ, P&L ngày, phân phối lợi suất với VaR, heatmap tháng, rolling Sharpe, bảng chiến lược, sự kiện rủi ro.
2. **Given** rolling Sharpe cần 63 ngày, **When** dữ liệu < 63 ngày, **Then** hiện ghi chú thay vì biểu đồ trống.
3. **Given** kỳ `1M/3M/YTD/1Y/ALL`, **When** đổi kỳ, **Then** KPI và biểu đồ cập nhật theo payload.
4. **Given** lịch sử dưới 3 năm, **When** vẽ heatmap tháng, **Then** hàng xếp đầy chiều ngang, không để trống (`876ce9e`).
5. **Given** `positions[]` rỗng, **When** render, **Then** ẩn bảng "Vị thế đang mở".

## Tasks / Subtasks
- [x] `pages/Portfolio.jsx`, `components/Dashboard.jsx`
- [x] Biểu đồ: AreaLine, Underwater, Histogram, Heatmap, Sparkline, BarsPosNeg
- [x] Nhãn "Tỉ lệ ngày lãi (ngày có giao dịch)"
- [x] Bảng vị thế đang mở

## Dev Notes
- Code: `frontend/src/v2/pages/Portfolio.jsx`, `v2/components/Dashboard.jsx`, `v2/components/charts/*`. Hợp đồng: `docs/ui_contract.md` §3.
- UI đọc payload, không tính lại chỉ số.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commits: `efe4fb2`, `876ce9e` (tỉ lệ ngày lãi, heatmap), `a3202c9` (bảng vị thế, ghi chú rolling Sharpe).
- Xác nhận bằng ảnh chụp headless Chrome ghi trong message commit; chưa có test giao diện tự động.

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
