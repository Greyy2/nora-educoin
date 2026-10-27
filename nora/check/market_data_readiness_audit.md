# Báo cáo Kiểm toán Dữ liệu Thị trường (GATE 2 - Market Data Readiness)

**Status:** AUDITED & APPROVED FOR BACKTEST RESEARCH  
**Scope:** OKX Crypto Perpetual Parquet Catalog (BTC-USDT-SWAP & ETH-USDT-SWAP)  
**Catalog Digest (BTC):** `cd026438b6a668b1`  
**Catalog Digest (ETH):** `8d62dc2d69c4d5cf`  
**Active Catalog SHA-256 (BTC.json):** `859568c1f656c48e6a8a2dcce37dfb50c04e1fc3e35b8a2fddab307f933c39fa`  
**Active Catalog SHA-256 (ETH.json):** `5fe5356d7662ec737736162ad084c38e996f6346568dab5ff1fee2f154275415`  
**Instruments SHA-256:** `878c18e878cc92dfd4ee8f64cc2ff6ee249092a4ac6eb0fdf4436e1c435ee0be`  

---

## 1. Kết quả Kiểm định Dữ liệu Nến (OHLCV Bars)

| Tiêu chí | BTC-USDT-SWAP | ETH-USDT-SWAP | Trạng thái |
|---|---|---|---|
| **Số lượng nến 1m (`rows_1m`)** | 1,580,149 bars | 1,580,149 bars | PASS (Khớp 100%) |
| **Khoảng thời gian bao phủ** | 1,097.325 ngày (~3 năm) | 1,097.325 ngày (~3 năm) | PASS |
| **Tính hợp lệ OHLC ($L \le O, C \le H$)** | 100% hợp lệ | 100% hợp lệ | PASS |
| **Căn chỉnh UTC (UTC-Aligned)** | Nến 1m, 5m, 15m, 1h, 4h, 24h neo từ 00:00:00 UTC | Neo từ 00:00:00 UTC | PASS |
| **Khoảng hở / Trùng lặp (Gaps / Dupes)** | 0 trùng lặp, tỷ lệ lấp đầy `filled_ratio: 0.0` | 0 trùng lặp, `filled_ratio: 0.0` | PASS |
| **Thước đo khối lượng** | `base_coin` | `base_coin` | PASS |
| **Điểm chất lượng (Quality Score)** | 100.0 / 100.0 | 100.0 / 100.0 | PASS |

---

## 2. Kiểm định Tính Causal của Resampling & Indicator

- Toàn bộ thanh nến resample $5\text{m}, 15\text{m}, 1\text{h}, 4\text{h}, 24\text{h}$ được tổng hợp nhân quả (causal) từ nến 1m đã đóng hoàn toàn.
- Thời gian đóng nến `ts_close` = `ts_open` + timeframe delta.
- Tín hiệu chỉ phát sinh tại `ts_close` của nến hiện tại; không có hiện tượng rò rỉ dữ liệu tương lai (Zero Lookahead Bias).

---

## 3. Giới hạn Phạm vi & Hạng mục UNVERIFIED

1. **Funding Rate:** Dữ liệu funding chỉ có lịch sử công khai từng phần (public funding snapshot); chưa có chuỗi funding liên tục từng 8h (00:00, 08:00, 16:00 UTC) cho toàn bộ 1,097 ngày. Trong giai đoạn kiểm thử, áp dụng quy tắc thận trọng: vị thế qua đêm (qua mốc 00:00 UTC) bị tính phí funding bảo thủ trước khi tất toán (flatten).
2. **Mark Price:** Thanh lý (liquidation) trong live dựa trên Mark Price. Backtest hiện tại dùng Last Trade Price của nến OHLC, không suy diễn thanh lý từ nến hourly mark.
3. **Fee Tier:** Chưa gắn nhãn authoritative; kiểm thử sử dụng mức stress x2 (swing) và x2/x3 (scalp) để đảm bảo biên độ an toàn vốn.
