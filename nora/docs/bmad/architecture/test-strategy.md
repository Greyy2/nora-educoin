# Chiến lược kiểm thử & Đảm bảo chất lượng (Test Strategy)

Chiến lược kiểm thử của Nora hướng đến độ tin cậy tuyệt đối: **Golden bit-identical, đối chiếu chuẩn công nghiệp NautilusTrader và kiểm soát kiến trúc tự động**.

---

## 1. Các cấp độ kiểm thử cốt lõi

### 1.1 Golden Scenarios (Bit-Identical Tests)
- **Mục tiêu**: Đảm bảo engine thực thi ra kết quả giống hệt từng bit qua các lần cập nhật mã nguồn.
- **Quy tắc vàng**: Nếu có sự sai lệch số liệu so với bản chụp chuẩn (Golden Snapshot), phải tìm nguyên nhân và sửa đổi logic code, tuyệt đối không được nới lỏng ngưỡng chấp nhận sai số trong test.
- **Tập test**:
  - `test/test_conservative_fills.py`: Kiểm thử các trường hợp gap xuyên lệnh, stop-market và khớp lệnh bảo thủ.
  - `test/test_intrabar_path.py`: Kiểm thử đường nến nội bar (`ohlc`, `adaptive`, `adverse_first`).
  - `test/test_portfolio_sync_open.py`: Kiểm thử khớp lệnh danh mục hai pha (mở nến & trong nến).

### 1.2 Kernel Parity Tests
- **Mục tiêu**: Đảm bảo các kernel chỉ báo Numba và các hàm thuần Python cho cùng một kết quả với độ chính xác số thực tối đa.
- **Tập test**: `test/test_kernel_parity.py`.

### 1.3 Đối chiếu chuẩn NautilusTrader (Cross-Engine Validation)
- **Mục tiêu**: So khớp toàn bộ các ca kiểm thử với chuẩn engine mã nguồn mở NautilusTrader 2.0.
- **Kết quả nghiệm thu**: Vượt qua 332/332 ca kiểm thử (`test/scripts/nautilus_diff/REPORT.md` và `EXT_REPORT.md`), sai lệch vốn cuối danh mục dưới 0.025%.

### 1.4 Kiểm soát trùng lặp logic (Zero Duplication Gate)
- **Mục tiêu**: Đảm bảo mỗi quy tắc kinh doanh hoặc công thức chỉ có đúng một nơi định nghĩa duy nhất trong mã nguồn.
- **Công cụ kiểm tra**:
  ```bash
  python test/scripts/p9_ledger.py --dups
  ```
  Kết quả trả về bắt buộc: **0 duplicate logic definitions**.

### 1.5 Kiểm soát phân tầng nghiêm ngặt (Strict Layering Gate)
- **Mục tiêu**: Chặn đứng các import ngược dòng vi phạm kiến trúc phân tầng (ví dụ: `core` không được import `optimize` hay `routes`).
- **Công cụ kiểm tra**:
  ```bash
  pytest test/test_layering.py
  ```
  Kết quả bắt buộc: **0 layering violations** ở chế độ strict.

### 1.6 Kiểm thử đầu-cuối giao diện (E2E Tests)
- **Mục tiêu**: Kiểm tra tính toàn vẹn của giao diện web SPA, các biểu đồ số liệu và tương tác người dùng.
- **Công cụ**: Playwright E2E suite (`nora/test/e2e/`).
