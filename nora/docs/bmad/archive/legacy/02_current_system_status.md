# 02. HIỆN TRẠNG HỆ THỐNG NORA (CURRENT SYSTEM STATUS)

**Cập nhật lần cuối:** 08/09/2026  
**Trạng thái tổng thể:** `STABLE - OPERATIONAL`

---

## 1. Trạng Thái Vận Hành & Mạng Lưới (Services & Endpoints)

| Thành Phần | Cổng / URL | Trạng Thái | Ghi Chú |
| :--- | :--- | :--- | :--- |
| **Backend Core** | `http://127.0.0.1:18010` | **ONLINE** | Uvicorn FastAPI daemon, Python 3.11 (UV) |
| **Health Check API** | `http://127.0.0.1:18010/api/health` | **200 OK** | Phản hồi JSON `{"status": "ok"}` < 2ms |
| **DEX Universe API** | `http://127.0.0.1:18010/api/research/markets/scan` | **200 OK** | Trả về 50 assets theo timeframe (15m, 1h, 4h) |
| **Asset Detail API** | `http://127.0.0.1:18010/api/research/markets/{sym}/analysis` | **200 OK** | Trả về bóc tách DC, OD, Falsification, Tick Trajectory |
| **List Trade Ticks** | `http://127.0.0.1:18010/api/research/markets/{sym}/trades` | **200 OK** | Trả về chuỗi tick liên tục (Zero candle) |
| **Command Center UI** | `http://127.0.0.1:18010/research/analysis` | **READY** | Dashboard phân tích tổng quan toàn thị trường |
| **Asset Drilldown UI**| `http://127.0.0.1:18010/research/analysis/asset/ZEN` | **READY** | Giao diện soi vi cấu trúc & bước sóng tick |

---

## 2. Dữ Liệu & Bộ Đệm Cache (Data Coverage & Pre-built Caches)

- **Quy mô Universe**: 50 cặp tài sản on-chain (Base & Ethereum).
- **Bộ nhớ đệm Universe (Disk Caches)**:
  - `universe_15m.json` (751 KB) - Quét độc lập khung 15 phút.
  - `universe_1h.json` (735 KB) - Quét độc lập khung 1 giờ.
  - `universe_4h.json` (697 KB) - Quét độc lập khung 4 giờ.
- **Tốc độ phản hồi khi đổi Timeframe trên UI**:
  - Thời gian phản hồi: **< 15 mili-giây** (trước đây mất ~25s do quét tuần tự không cache).
  - Trải nghiệm người dùng: Chuyển đổi dropdown 15m ➔ 1h ➔ 4h mượt mà tức thì.

---

## 3. Các Module Đã Hoàn Thiện (Completed Modules)

1. ✅ **Lõi Causal Tick Processing**: Loại bỏ toàn bộ look-ahead bias, tính toán DC $\theta^*$ chuẩn xác theo Intrinsic Time.
2. ✅ **List Trade Tick Trajectory**: Biểu diễn biến động giá liên tục theo từng tick, loại bỏ nến giả lập ở vùng kiểm tra lệnh.
3. ✅ **Mô hình Chi phí 4 Tầng**: Kiểm định từ Zero Cost (0 bps) đến Stress Hurdle (150 bps), cấp nhãn `SURVIVED_FRICTION_HURDLE` hoặc `FALSIFIED_AFTER_COST`.
4. ✅ **Quản lý Tiến trình Sạch**: Rút gọn chỉ còn 2 script `start_nora.sh` và `stop_nora.sh`, xử lý dọn dẹp port 18010 triệt để.
5. ✅ **Độc lập hóa Timeframe 15m / 1h / 4h**: Mỗi timeframe phản ánh đúng Regime, Playbook và độ biến động thực tế mà không làm biến dạng cấu trúc DC tick.

---

## 4. Kế Hoạch Đợt Sóng Tiếp Theo (Backlog / Next Wave)

1. ⏳ **Wave 4: Walk-Forward Analysis (WFA) Integration**:
   - Triển khai kiểm định ngoài mẫu (Out-of-Sample) lăn bánh theo từng cửa sổ thời gian.
   - Bổ sung chỉ số Overfitting Degradation Ratio vào thẻ kiểm duyệt.
2. ⏳ **Wave 5: Real-Time Mempool & Execution Gateway**:
   - Kết nối trực tiếp websocket RPC node để nhận swap event theo mili-giây.
