# Đặc tả chi tiết Engine thực thi & Đo lường (Engine Specification)

Tài liệu hợp nhất đặc tả thuật toán lõi của `backend/core/backtest.py` (`PortfolioEngine`), các quy tắc khớp lệnh bảo thủ, mô hình hóa chi phí và danh mục đo lường tài chính chuẩn mực.

---

## 1. Mô hình khớp lệnh nội nến (Intrabar Price Path)

Engine hỗ trợ 3 chế độ quét bước giá trong nến (`StrategyParams.intrabar_path`):

1. **`"ohlc"` (Mặc định chuẩn NautilusTrader)**:
   - Đường giá đi tuần tự 4 chặng: $\text{Open} \to \text{High} \to \text{Low} \to \text{Close}$.
   - Mỗi chặng được coi là một tick giả lập. Trong mỗi tick, thứ tự ưu tiên kiểm tra khớp lệnh tuân theo quy tắc:
     - (a) Các tầng DCA limit bị xuyên qua.
     - (b) Lệnh chốt lời (Take-Profit).
     - (c) Lệnh dừng lỗ (Stop-Loss / Trailing Stop / Thanh lý).
2. **`"adaptive"`**:
   - Tự động đi qua đỉnh/đáy nào gần giá mở cửa hơn trước: Nếu $(\text{High} - \text{Open}) < (\text{Open} - \text{Low})$ thì High đi trước, ngược lại Low đi trước.
3. **`"adverse_first"`**:
   - Đi qua mức giá bất lợi nhất trước (quét Stop-Loss trước khi tới Take-Profit) để kiểm định sức chịu đựng rủi ro tối đa.

---

## 2. Quy trình khớp lệnh danh mục Hai Pha (Two-Phase Portfolio Execution)

Để triệt tiêu hoàn toàn hiện tượng nhìn trước giữa các tài sản trong cùng một nến, `PortfolioEngine` thực hiện theo 2 pha tuần tự cho mọi tài sản trong sổ:

### Pha 1: Mở nến (Bar Open)
- **Áp dụng Funding Rate**: Trừ/cộng phí funding của các vị thế đang mở tại giá `Open`.
- **Thoát lệnh đến hạn**: Kiểm tra các lệnh thoát theo thời gian hoặc lệnh dừng tại mở nến.
- **Duyệt lệnh vào mới**: Đánh giá các lệnh mở vị thế chờ tại `Open`. Hạn mức danh mục (số lượng vị thế mở tối đa, trần gross exposure, trần rủi ro) được tính toán nghiêm ngặt theo trạng thái **ngay tại thời điểm mở nến** (giá `last_close` của nến trước), không nhìn trước các lệnh sẽ đóng trong nến.

### Pha 2: Trong nến (Intrabar Execution)
- Duyệt qua từng tài sản theo thứ tự cấu hình sổ: Quét đường giá nội nến (`ohlc`), kiểm tra khớp các tầng DCA, TP, SL, Trailing stop.
- Cập nhật số dư tiền mặt, vốn MTM, giá vốn bình quân và ghi nhận lịch sử lệnh đã đóng.

---

## 3. Mô hình chi phí thực tế

- **Phí giao dịch (Exchange Fees)**:
  - CEX Taker: $0.05\% - 0.10\%$ mỗi chiều.
  - CEX Maker (DCA limit): $0.02\%$ mỗi chiều.
  - DEX Swap: Phí pool cố định ($0.30\%$) + adverse selection.
- **Trượt giá (Slippage)**:
  - Stop-market: Khớp tại giá mở cửa nếu có gap vượt qua mức dừng.
  - Limit order: Khớp chính xác tại giá đặt giới hạn.
- **Funding Rate**: Áp dụng chu kỳ 8 giờ một lần trên sàn OKX/Binance theo giá trị danh nghĩa vị thế perp.

---

## 4. Bộ số đo định lượng chuẩn (Metrics Inventory)

Tất cả các số đo được tính toán thuần túy bởi `backend/metrics/` trên cơ sở năm 365 ngày:

| Chỉ số | Ký hiệu / Tên | Công thức / Ý nghĩa |
|---|---|---|
| **Lợi nhuận ròng** | `ret_pct` | $(\text{Vốn cuối} / \text{Vốn đầu} - 1) \times 100\%$ |
| **Lợi nhuận kép năm** | `cagr` | $(\text{NAV}_\text{cuối} / \text{NAV}_\text{đầu})^{(365 / n)} - 1$ |
| **Tỷ số Sharpe** | `sharpe` | $\frac{\text{mean}(r_\text{ngày})}{\text{std}(r_\text{ngày})} \times \sqrt{365}$ |
| **Tỷ số Sortino** | `sortino` | $\frac{\text{mean}(r_\text{ngày})}{\text{downside\_std}(r_\text{ngày})} \times \sqrt{365}$ |
| **Sụt giảm tối đa** | `mdd_pct` | $\max_{t} \left( \frac{\text{Peak}_t - \text{Equity}_t}{\text{Peak}_t} \right) \times 100\%$ |
| **Tỷ số Calmar** | `calmar` | $\text{CAGR} / |\text{MDD}|$ |
| **Tỷ lệ thắng theo lệnh**| `win_trades`| Số lệnh lãi / Tổng số lệnh đã đóng |
| **Hệ số lợi nhuận** | `profit_factor` | Tổng lãi gộp / Tổng lỗ gộp |
| **Payoff Ratio** | `payoff` | Lãi trung bình mỗi lệnh thắng / Lỗ trung bình mỗi lệnh thua |
| **Số lệnh giao dịch** | `trades` | Tổng số lượt giao dịch hoàn thành |
