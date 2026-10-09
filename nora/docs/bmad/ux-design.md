# UX Design & Frontend Specification: Nora Studio

Phiên bản: 2.0 · Ngày: 09/10/2026 · Hệ thống: Single-Page Application (React 18 + Vite)

Tài liệu này định nghĩa cấu trúc giao diện, trải nghiệm người dùng (UX), luồng điều hướng (flows), và các nguyên tắc thiết kế bất biến của Nora Frontend.

---

## 1. Triết lý Thiết kế & Nguyên tắc Bất biến

1. **UI chỉ là lớp hiển thị và định dạng (UI Only Formats):**
   - Tuyệt đối không nhúng logic tính toán quant (PnL, margin, liquidation, Sharpe ratio) vào code frontend.
   - Toàn bộ kết quả tính toán do backend engine trả về; UI chỉ parse và hiển thị theo locale/format chuẩn.
2. **Một nguồn sự thật duy nhất qua `MetaProvider`:**
   - Khi khởi động, UI gọi `GET /api/studio/meta` để nạp danh mục sàn (`venues`), thị trường (`markets`), tài sản (`symbols`), khung nến (`timeframes`), danh sách chiến lược (`strategies`), và danh mục chỉ số (`metrics_inventory`).
   - Mọi dropdown, autocomplete, và form validation đều sử dụng metadata này; tuyệt đối không hardcode danh sách coin hay timeframe rải rác trong component.
3. **Lazy Loading theo trang (Chunk Isolation):**
   - Mỗi trang là một chunk độc lập (`lazy(() => import(...))`). Thư viện biểu đồ nến nặng chỉ nạp khi người dùng mở trang chứa biểu đồ.
4. **Bảo vệ dữ liệu chưa lưu (`useUnsavedGuard`):**
   - Khi đang chỉnh sửa code chiến lược hoặc có kết quả chạy dở chưa lưu/xuất bản, router sẽ chặn và cảnh báo nếu người dùng chuyển trang.
5. **Dark Mode tinh tế & Responsive:**
   - Giao diện Dark theme tối ưu cho trader/quant làm việc nhiều giờ; responsive mượt mà từ màn hình Desktop siêu rộng tới Laptop và Tablet.

---

## 2. Sơ đồ Điều hướng & Cấu trúc Trang (Site Map)

Toàn bộ ứng dụng được bọc trong layout chung `Shell` (Header, Navigation Bar, Global Job Tracker, Theme Toggle).

```
/
├── /portfolio               ← Tổng quan danh mục, đường vốn NAV MTM, drawdown, vị thế
├── /backtest                ← Chạy mô phỏng chiến lược đơn, xem biểu đồ nến & lệnh vào/ra
├── /alpha/
│   ├── /alpha               ← Alpha Catalog: Danh mục alpha đạt chuẩn, registry.json
│   ├── /alpha/create        ← Studio (mode="create"): Soạn thảo code chiến lược Python
│   ├── /alpha/funnel        ← Funnel Optimization: Quét nhiều tầng (Screening -> WFA -> MC)
│   └── /alpha/tune          ← Tune: Tinh chỉnh tham số và đóng gói sổ chiến lược (book.json)
├── /education               ← Studio (mode="education"): 50+ chiến lược mẫu kèm giải thích logic
├── /live                    ← Giám sát giao dịch tài khoản thật OKX (Paper/Testnet/Live)
└── /history                 ← Lịch sử các lệnh đã đóng, nhật ký kiểm định, audit trail
```

---

## 3. Chi tiết Từng Phân Hệ Giao Diện

### 3.1 Trang Portfolio (`/portfolio`)
- **Mục tiêu:** Giám sát sức khỏe tổng thể của danh mục đa tài sản và sổ chiến lược.
- **Thành phần chính:**
  - **KPI Cards:** NAV Hiện tại, Tổng Realized PnL, Unrealized PnL, Max Drawdown (MTM), Rolling Sharpe 30D.
  - **Equity & Drawdown Chart:** Biểu đồ đường kép (NAV so với BTC Benchmark; vùng Drawdown bên dưới).
  - **Daily P&L Heatmap / Distribution:** Phân phối lợi nhuận ngày kèm ngưỡng VaR 95% và 99%.
  - **Open Positions Table:** Bảng vị thế mở thời gian thực (Ký hiệu, Chiều Long/Short, Đòn bẩy, Ký quỹ, Giá vào, Giá thanh lý, PnL chưa chốt).
  - **Risk Events Feed:** Nhật ký cảnh báo rủi ro (Margin warning, chạm ngưỡng Kill Switch, Funding fee spike).

### 3.2 Trang Backtest (`/backtest`)
- **Mục tiêu:** Chạy thử nghiệm nhanh một chiến lược trên một cặp tài sản với dữ liệu lịch sử nến 1m.
- **Thành phần chính:**
  - **Control Bar:** Chọn Sàn (`venue`), Tài sản (`symbol`), Khung thời gian (`timeframe`), Khoảng thời gian (Start/End date), Chiến lược (`strategy`), và Tham số (`params`).
  - **Candlestick & Trade Overlay Chart:** Biểu đồ nến tương tác hiển thị rõ điểm vào lệnh (mũi tên xanh/đỏ), mức Stop-Loss (đỏ), Take-Profit (xanh), và các tầng DCA.
  - **Performance Summary:** CAGR, Win Rate, Profit Factor, Total Trades, Phí và Trượt giá chịu phạt.
  - **Trade Log Table:** Danh sách chi tiết từng trade (Thời gian mở/đóng, Giá mở/đóng, Khối lượng, Lý do thoát: SL, TP, Timeout, Signal).

### 3.3 Phân hệ Alpha Lab (`/alpha/*`)
Bao gồm thanh tab điều hướng phụ `AlphaTabs`:
- **Alpha Catalog (`/alpha`):**
  - Hiển thị danh sách các Alpha đã được ghi nhận vào `registry.json`.
  - Bảng lọc theo Sharpe, Return, Drawdown, Sàn và Tài sản.
  - Nút "Gửi sang Backtest" và "Tải cấu hình AST".
- **Studio Editor (`/alpha/create`):**
  - Trình soạn thảo mã nguồn Python có tô màu cú pháp (Monaco/CodeMirror).
  - Nút **Validate Contract**: Gọi backend kiểm tra hợp đồng (`BaseStrategy`), trả kết quả `RUN`, `ADAPT`, hoặc `REJECT` kèm lỗi chi tiết.
  - Nút **Run Quick Test**: Chạy thử nghiệm 30 ngày gần nhất để xem tín hiệu sinh ra.
- **Funnel Optimization (`/alpha/funnel`):**
  - Giao diện trực quan hoá 4 giai đoạn sàng lọc:
    - Stage 1: Fast Screening (Grid filter).
    - Stage 2: Walk-Forward Analysis (IS/OOS Folds).
    - Stage 3: Monte Carlo Block Bootstrap.
    - Stage 4: Holdout Verification.
  - Sơ đồ hình phễu hiển thị số lượng ứng viên bị loại qua từng giai đoạn và lý do trượt.
- **Tune (`/alpha/tune`):**
  - Tinh chỉnh trọng số giữa các chiến lược trong sổ vốn chung.
  - Nút "Xuất bản Sổ này" (`publish`) kèm modal xác nhận cảnh báo an toàn.

### 3.4 Trang Education (`/education`)
- **Mục tiêu:** Môi trường học tập và tham khảo cho quant dev.
- **Đặc điểm:**
  - Ẩn bớt các thanh công cụ nặng của Backtest (Job runner nền, data fetcher) để giao diện thoáng đãng.
  - Danh sách 50+ chiến lược mẫu phân theo loại: Trend Following, Mean Reversion, Breakout, Volatility, Martingale/DCA.
  - Code panel hiển thị docstrings chi tiết bằng tiếng Anh giải thích logic toán học, điều kiện vào lệnh, thoát lệnh.
  - Panel bên phải: Chỉ hiển thị bảng tham số mẫu và kết quả chạy nhanh (Metrics & Equity mini chart).

### 3.5 Trang Live Trading (`/live`)
- **Mục tiêu:** Giám sát bot giao dịch thực tế đang chạy trên sàn OKX.
- **Môi trường:** Cho phép chuyển đổi giữa `Paper` (Giả lập khớp lệnh sàn), `Testnet` (OKX Demo), và `Live` (Tài khoản thật).
- **Tính năng:**
  - Trạng thái kết nối WebSocket và độ trễ sàn (ping ms).
  - Vị thế thực tế trên sàn đối chiếu với sổ lệnh nội bộ.
  - Nút khẩn cấp: **Kill Switch** (Đóng toàn bộ vị thế ngay lập tức và dừng bot).

---

## 4. Giao thức Tích hợp Dữ liệu (`MetaProvider`)

Component `CatalogProvider` trong `src/meta/MetaProvider.jsx` đóng vai trò trung tâm phân phối dữ liệu cấu hình:

```javascript
// Cấu trúc state toàn cục do MetaProvider cung cấp
{
  venues: ["binance", "okx"],
  markets: ["perp", "spot"],
  symbols: ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "NEAR", "SUI"],
  timeframes: ["1m", "5m", "15m", "1h", "4h", "1d"],
  strategies: [
    { id: "kema_trend", name: "KEMA Trend Follower", type: "trend", params_schema: {...} },
    ...
  ],
  metrics_inventory: [
    { key: "cagr", label: "CAGR", format: "percent" },
    { key: "sharpe", label: "Sharpe Ratio", format: "number_2dp" },
    { key: "mdd", label: "Max Drawdown", format: "percent" },
    ...
  ]
}
```

Mọi component con truy cập qua hook:
```javascript
const { symbols, timeframes, strategies } = useCatalog();
```

---

## 5. Quy tắc Trình bày & Định dạng (Formatting Standards)

- **Số thập phân:**
  - Tỷ lệ %, Lợi nhuận, Drawdown: `+12.34%`, `-5.67%` (luôn có dấu +/- trừ khi 0, 2 chữ số thập phân, màu xanh lá cây `#10b981` cho dương, đỏ `#ef4444` cho âm).
  - Giá tài sản: Định dạng linh hoạt theo tick size (`$65,420.50` cho BTC, `$0.1234` cho DOGE).
  - Tỷ số (Sharpe, Sortino, Calmar): `1.85`, `-0.42` (2 chữ số thập phân).
- **Thời gian:** Hiển thị theo múi giờ địa phương kèm nhãn múi giờ (hoặc UTC mặc định khi soi nến), chuẩn ISO 8601 trong tooltips.
