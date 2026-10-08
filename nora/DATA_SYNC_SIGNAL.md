# THÔNG BÁO TÍN HIỆU ĐỒNG NHẤT DỮ LIỆU (DATA CONSOLIDATION SIGNAL)
**Thời gian phát tín hiệu:** 2026-10-07 04:50 UTC  
**Gửi tới:** 3 phiên làm việc hiện tại (`83dcb24e-e65f-4d5a-bd0a-f4074083b518`, `66fbae40-704e-4111-b637-a0e4e798b6ce`, `9bfbe26c-26e4-4453-9d8a-c845ce3b963f`) và toàn bộ hệ thống Nora.

---

### 1. NGUYÊN NHÂN BẤT ĐỒNG NHẤT TRƯỚC ĐÂY (ROOT CAUSE)
1. **Sự tồn tại của 2 folder data:**
   - `nora/data/`: Thư mục dữ liệu chuẩn của hệ thống (chứa `okx`, `binance`, `_cache`, `_meta`, `alphas`). Tuy nhiên, `data/okx/cex/` ban đầu chỉ có **16 mã** (với lịch sử 3 năm, đến ngày 04/10/2026).
   - `nora/data_staging/`: Vốn được thiết kế làm vùng đệm tạm thời cho crawler. Khi cào 10 bot copy-trade OKX, crawler đã tải **79 mã** nến 1m & funding (~110 ngày, đến 06/10/2026) vào `data_staging/cex/` nhưng chưa được promote chính thức vào `data/okx/cex/`.
2. **Sự phân mảnh giữa Core và Test:**
   - Bộ script mô phỏng 10 bot OKX tại `test/scripts/okx_top10/load.py` đã bị hardcode trỏ thẳng vào `data_staging/cex/` (`CANDLE_DIR = "/home/vmc03/norabt/nora/data_staging/cex"`).
   - Trong khi đó, toàn bộ Backend (`backend/db/data_layout.py`, các endpoint API, backtest custom) lại đọc từ `data/okx/cex/`.
   - Điều này khiến 63 mã thị trường (như PUMP, TRUMP, SOXL, NVDA, BSB, CRCL...) chỉ chạy được trên test script cô lập, không thể đồng bộ với Core.

---

### 2. CÁC HÀNH ĐỘNG ĐÃ HOÀN TẤT (ACTIONS COMPLETED)
1. **Hợp nhất dữ liệu vào `nora/data/okx/cex/`:**
   - **63 mã mới** từ `data_staging/cex/` đã được chuyển đầy đủ vào `nora/data/okx/cex/` (gồm toàn bộ `1m.pkl`, `5m.pkl`, `15m.pkl`, `1h.pkl`, `4h.pkl`, `24h.pkl`, `funding.pkl`, `manifest.json`).
   - **16 mã trùng** (BTC, ETH, SOL, BNB, ADA, DOGE, XRP, LINK, LTC, UNI...) đã được hợp nhất hoàn hảo:
     - Giữ nguyên toàn bộ **3 năm dữ liệu lịch sử** (từ 2023).
     - Bổ sung và nối tiếp **2 ngày dữ liệu mới nhất** (từ ngày 04/10 đến 06/10/2026).
     - `funding.pkl` đã được deduplicate và mở rộng chuỗi thời gian.
   - Hiện tại `nora/data/okx/cex/` chứa đầy đủ **79 mã**.
2. **Đồng nhất mã nguồn:**
   - Đã cập nhật `test/scripts/okx_top10/load.py`:
     ```python
     CANDLE_DIR = os.environ.get("NORA_OKX_CEX_DATA", "/home/vmc03/norabt/nora/data/okx/cex")
     ```
   - Giờ đây, cả **Core** lẫn **Test** đều chỉ truy cập duy nhất một nguồn dữ liệu tại `/home/vmc03/norabt/nora/data/`.
3. **Dọn dẹp thư mục dư thừa:**
   - Thư mục `nora/data_staging` đã được di dời vào trong thư mục test:
     `/home/vmc03/norabt/nora/test/data_staging`
   - Tại gốc `nora/` hiện chỉ còn duy nhất một thư mục dữ liệu là `/home/vmc03/norabt/nora/data`.

---

### 3. HƯỚNG DẪN CHO CÁC PHIÊN ĐANG LÀM VIỆC
- **Phiên 83dcb24e** (Chạy OOS / mô phỏng 10 bot OKX): Các script trong `test/scripts/okx_top10/` (`run_oos.py`, `implied.py`, `load.py`, `match.py`) sẽ tự động đọc từ `/home/vmc03/norabt/nora/data/okx/cex`. Bạn có thể chạy ngay với dữ liệu đồng nhất mà không cần sửa path.
- **Phiên 66fbae40** (Core bot / Unified engine / Test runner): Đường dẫn dữ liệu thị trường cho OKX CEX thống nhất tại `DATA_HOME/okx/cex`. Không còn xung đột giữa staging và core.
- **Phiên 9bfbe26c** (Phân tích sự kiện / Tương quan chiến lược): Mọi tính toán correl / beta có thể dựa vào đầy đủ 79 symbols tại `nora/data/okx/cex`.
