# E8-S6: Cải thiện trải nghiệm UI v2

- **Epic:** E8 UI v2
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người dùng UI v2, tôi muốn tham số, thuật ngữ và trạng thái job được trình bày dễ hiểu, để thao tác vòng Alpha → Backtest → WFA → Monte Carlo → Danh mục mà không phải đoán ý nghĩa con số hay nhớ mã job.

## Acceptance Criteria

1. **Given** các thay đổi UX, **When** chạy `npm run build` (từ `nora/frontend`), **Then** build thành công, không lỗi.
2. **Given** các trang `/portfolio`, `/backtest`, `/alpha`, `/history`, **When** mở với dữ liệu thật, **Then** không có lỗi console, không trắng trang, hiển thị đúng ở chế độ sáng và tối.
3. **Given** một tham số chiến lược (vd. `stop_loss_rate`, `timeout`), **When** hiển thị ở bất kỳ trang nào, **Then** dùng nhãn tiếng Việt có đơn vị từ một nguồn duy nhất (`lib/params.js`); tên gốc nằm trong tooltip.
4. **Given** một thuật ngữ (Sharpe, VaR, MDD, IS/OOS, level/extreme…), **When** người dùng rê chuột hoặc focus bàn phím vào ⓘ, **Then** hiện giải thích một dòng; Esc đóng.
5. **Given** một job đang chạy hoặc đang chờ, **When** người dùng chuyển trang, **Then** khay job trên thanh đầu vẫn hiện trạng thái và dẫn về đúng trang/bước; `/history` liệt kê job, lọc theo loại và trạng thái.
6. **Given** nguồn Live/Testnet, **When** mở trang Danh mục, **Then** dữ liệu tự làm mới mỗi 60 s (tạm dừng khi tab ẩn) và hiện "Cập nhật lúc HH:MM:SS".
7. **Given** sự kiện bị chặn do giới hạn rủi ro, **When** dựng dashboard, **Then** đếm theo số lần vào lệnh bị chặn (`risk_blocked_attempts`), không theo số phút; `rejected_for_risk` giữ nguyên; golden không đổi.

## Tasks / Subtasks

- [x] Nhãn tham số có đơn vị (`frontend/src/v2/lib/params.js`) cho StrategyPicker, thẻ và bảng Alpha, bảng fold WFA.
- [x] Từ điển thuật ngữ + component `Term` (`lib/glossary.js`, `components/Term.jsx`) gắn vào KPI, tiêu đề panel/bảng, dòng cổng, nhãn form.
- [x] Ô ngày dd/mm/yyyy có kiểm hợp lệ + chọn nhanh dev1/dev2/Holdout/Toàn bộ/90 ngày (`lib/dates.js`, `components/DateField.jsx`).
- [x] Thanh điều hướng có nhãn chữ (`layout/Shell.jsx`).
- [x] Khay job (`components/JobTray.jsx`, `hooks/useJobList.js`) và trang `/history` (`pages/History.jsx`); link sâu `/alpha?build=`, `/backtest?wfa=&step=2`.
- [x] Bảng fold WFA chỉ hiện tham số khi đổi so với fold trước ("như fold trước").
- [x] Diễn đạt khớp cắt lỗ: "Đúng mức (lạc quan)" / "Giá xấu nhất của nến (bi quan)" (`lib/stopfill.js`).
- [x] KPI so với BTC: "BTC +x% · chênh y điểm %", có màu theo dấu.
- [x] Backend: `risk_blocked_attempts` trong `core/backtest/portfolio.py`, lưu ở `core/backtest/run_book_backtest.py`, câu sự kiện mới trong `core/analytics/portfolio_dashboard.py`; dựng lại mock feed (Live: 3129 phút → 37 lần).
- [x] Live/Testnet tự làm mới 60 s + nút làm mới.
- [x] Thẻ "Hướng dẫn nhanh" (`components/QuickGuide.jsx`) + nút "?" trên thanh đầu.
- [x] Thanh chạy dính đáy ở bước Backtest kèm tóm tắt cấu hình; khoá nút kèm lý do khi chưa chọn gì.
- [x] Tiêu đề bảng dính, số thập phân thống nhất (2 chữ số cho % và xác suất), trạng thái Loading/Error dùng chung.

## Dev Notes

- Không đổi hợp đồng ngoài phần bổ sung `risk_blocked_attempts` và câu sự kiện; `docs/ui_contract.md` đã cập nhật.
- Số thập phân dùng dấu chấm thống nhất toàn UI.
- Còn lại (chuyển sang story sau): ô ngày chưa cảnh báo khi ngoài khoảng dữ liệu; phụ đề Sortino/Calmar xuống dòng ở độ rộng hiện tại; nút "?" mở popover thay vì hiện lại thẻ trên `/portfolio`; job cũ (trước thay đổi) không có số lần bị chặn nên chỉ hiện câu không kèm số.

## Evidence

- Commit `8a96b4e` feat(ui): usability pass — plain-language params, glossary, dates, job tray, history.
- Test backend: 442 passed (golden không đổi); test mới: `test_risk_block_event_counts_attempts_not_minutes`, kiểm `0 < attempts ≤ minutes` trong `test/test_portfolio_engine.py`, payload kết quả cũ không có khoá mới.
- `npm run build` thành công.
- Ảnh kiểm (headless Chrome, sáng/tối): Danh mục Live có hướng dẫn và tooltip; Backtest bước 1 với ô ngày dd/mm và thanh chạy; bước WFA với "như fold trước"; Alpha qua `?build=`; `/history`; khay job; tooltip Sharpe.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `in-progress`. |
| 2026-10-01 | Hoàn tất 13 mục từ đánh giá UX; chuyển `done` (commit `8a96b4e`). |
