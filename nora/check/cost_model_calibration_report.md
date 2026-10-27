# Báo cáo Hiệu chuẩn Mô hình Chi phí (GATE 5B - Cost Model Calibration)

**Status:** INCONCLUSIVE (INSUFFICIENT_OBSERVED_DEMO_FILLS)  
**Date:** 2026-10-25  
**Promotion Flag:** BLOCKED (`promotion_allowed = false`)  
**Parent Contract:** `COIN_EXECUTION_PARITY_CONTRACT_V1` (GATE 0)  

---

## 1. Tuyên bố Trạng thái & Bằng chứng Thực nghiệm

Theo quy định nghiêm ngặt của **GATE 5B**:
> *"Chỉ hiệu chuẩn từ đủ fill Demo/Paper đã ghi nhận sau khi vượt qua fixtures, replay và authoritative risk. Nếu bằng chứng thưa thớt (sparse), bắt buộc báo cáo **INCONCLUSIVE** và chặn promotion; tuyệt đối không được làm khớp (fit) số liệu hoặc tuyên bố alpha từ mẫu fill không đầy đủ."*

Hiện tại, môi trường OKX Demo/Testnet chưa tích luỹ đủ mẫu tối thiểu ($N \ge 100$ fills phân bố qua các dải biến động và khối lượng khác nhau trên BTC và ETH). 
Do đó:
1. **Kết luận kiểm định:** **INCONCLUSIVE** — Chưa đủ điều kiện thống kê để xác nhận độ lệch chi phí $\le 30\%$.
2. **Hành động bảo vệ rủi ro:** Khóa toàn bộ quyền thăng hạng (`promotion_allowed = false`) và vô hiệu hoá xếp hạng chính thức (`official_ranking_allowed = false`).
3. **Mô hình chi phí áp dụng cho nghiên cứu:** Tiếp tục sử dụng **Approved Research Proxy** với hệ số stress bảo thủ để loại bỏ triệt để các alpha phụ thuộc vào chi phí thấp.

---

## 2. Thông số Research Cost Proxy Đã Duyệt (Frozen Proxy)

| Hạng mục | Thông số chuẩn | Mức Stress x2 (Swing) | Mức Stress x3 (Scalp) | Cơ sở kiểm định |
|---|---|---|---|---|
| **Taker Fee** | $0.05\%$ ($5.0\text{ bps}$) | $0.10\%$ ($10.0\text{ bps}$) | $0.15\%$ ($15.0\text{ bps}$) | Mức biểu phí mặc định Taker |
| **Maker Fee** | $0.02\%$ ($2.0\text{ bps}$) | $0.04\%$ ($4.0\text{ bps}$) | $0.06\%$ ($6.0\text{ bps}$) | Mức biểu phí mặc định Maker |
| **Slippage BTC** | $3.0\text{ bps}$ | $6.0\text{ bps}$ | $9.0\text{ bps}$ | Proxy nghiên cứu đã duyệt |
| **Slippage ETH** | $5.0\text{ bps}$ | $10.0\text{ bps}$ | $15.0\text{ bps}$ | Proxy nghiên cứu đã duyệt |
| **Stop Slippage Factor** | **2.0x** | **2.0x** | **2.0x** | Trượt giá nhân đôi cho lệnh cắt lỗ |
| **Funding Qua đêm** | Tính phí tại 00:00 UTC | Tính phí tại 00:00 UTC | N/A (Scalp đóng trong ngày) | Trừ funding trước khi tất toán |

---

## 3. Khung Đo lường Đối soát Record / Replay khi Thu thập Dữ liệu

Khi bot Demo/Paper vận hành để thu thập fills, mỗi lệnh bắt buộc phải ghi nhận đầy đủ 7 mốc dữ liệu để phục vụ đối soát:
1. `ts_signal`: Thời điểm đóng nến phát sinh tín hiệu ($00\text{ ns}$).
2. `ts_send`: Thời điểm Client gửi lệnh vào Nautilus OrderMatchingEngine.
3. `ts_ack`: Thời điểm sàn/mô phỏng xác nhận nhận lệnh (Order Accepted).
4. `ts_fill`: Thời điểm khớp lệnh thực tế (Fill Timestamp).
5. `px_quote_ref`: Giá Quote Bid/Ask tốt nhất tại thời điểm phát sinh tín hiệu.
6. `px_fill_actual`: Giá khớp thực tế nhận về từ Venue.
7. `fee_charged`: Khoản phí chính thức ghi nợ vào tài khoản.

Độ lệch chi phí (Cost Deviation Metric) được định nghĩa:
$$\text{Cost Deviation} = \frac{|\text{Observed Slippage} - \text{Modeled Slippage}|}{\text{Modeled Slippage}}$$
Yêu cầu nghiệm thu chính thức: $\text{Cost Deviation} \le 30\%$ trên mẫu $N \ge 100$ trades.
Cho đến khi đạt điều kiện này, mọi kết quả backtest chỉ có giá trị tham khảo nghiên cứu nội bộ.
