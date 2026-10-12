# Kiến Trúc Nora Backend (Nautilus Trader Native-First)

> **Tài liệu tham chiếu chuẩn quốc tế:** [Nautilus Trader Documentation](https://nautilustrader.io/docs/)  
> **Kho mã nguồn:** [nautechsystems/nautilus_trader (GitHub)](https://github.com/nautechsystems/nautilus_trader)  
> **Phiên bản cố định:** `1.231.0` (OKX CEX Venue, Margin, Netting, USDT Base)

---

## 1. Phân Tầng Kiến Trúc Backend (Separation of Concerns)

Hệ thống backend của Nora được chuẩn hóa theo mô hình phân tầng chặt chẽ. **Nautilus Trader là engine duy nhất** chịu trách nhiệm mô phỏng sự kiện, khớp lệnh, quản lý tài khoản và giao dịch thực tế. Các module khác đóng vai trò cung cấp dữ liệu, tối ưu hóa và phân tích rủi ro.

```text
                                 [Nora Frontend UI / Studio]
                                              │
                                              ▼
                                 [FastAPI Gateway: routes/]
                                              │
                     ┌────────────────────────┼────────────────────────┐
                     │                        │                        │
                     ▼                        ▼                        ▼
           [backend/optimize/]        [backend/metrics/]       [backend/carlo/]
           • Parameter Search         • Performance Metrics    • Monte Carlo
           • Screening Funnel         • Market Regime          • WFA Analysis
           • Background Workers         (regime.py)
                     │                        │
                     └────────────────────────┼────────────────────────┘
                                              │
                                              ▼
                                    [backend/nautilus/]
                         ★ TRÁI TIM KHỚP LỆNH & THỰC THI DUY NHẤT ★
                         ├── runner.py    (Native Strategy Runner)
                         ├── results.py   (UI Data Contract Formatter)
                         ├── engine.py    (Portfolio / Backtest Engine)
                         ├── strategy.py  (DSL -> Nautilus Adapter)
                         ├── catalog.py   (Parquet Data Catalog)
                         └── live.py      (OKX Live / Paper Connector)
                                     ▲                 ▲
                                     │                 │
                ┌────────────────────┘                 └────────────────────┐
                │                                                           │
       [backend/models/]                                          [backend/crawl/]
       • Domain Models & Data Schemas                             • OKX Market Data Fetcher
       • Parameter & Risk Defaults                                • Parquet Store Sync
       • Position Sizing Rules
                │
                ▼
       [backend/alpha/dsl/]
       • Vectorized Technical Indicators
       • DSL AST Logic & Signal Trees
```

> **Lưu ý:** Thư mục `backend/core/` và `backend/regime/` đã được **XÓA BỎ HOÀN TOÀN** để loại bỏ mọi nhầm lẫn về engine cũ.

---

## 2. Chi Tiết Vai Trò Các Module

### 2.1. `backend/nautilus/` — Execution & Backtest Engine Độc Quyền
Trung tâm tính toán và thực thi toàn bộ chiến lược:
- **`NativeNautilusRunner` (`runner.py`):** Thực thi trực tiếp các chiến lược viết bằng mã Python bản địa kế thừa từ `nautilus_trader.trading.strategy.Strategy`. Tự do sử dụng các chỉ báo, state machine, multi-order, dynamic risk của Nautilus mà không bị giới hạn bởi DSL.
- **`format_nautilus_results` (`results.py`):** Trích xuất lịch sử lệnh, fill, position và equity curve từ `engine.cache` và `reports` của Nautilus, chuyển đổi khớp 100% với hợp đồng dữ liệu hiển thị của Nora UI.
- **`BacktestEngine` / `PortfolioEngine` (`engine.py`):** Điều phối nạp dữ liệu nến, khởi tạo sàn giao dịch ảo OKX, gán phí maker/taker và đòn bẩy.
- **`NautilusStrategy` (`strategy.py`):** Adapter chuyển đổi các chiến lược viết bằng cú pháp DSL cấu hình (AST tree) sang mô hình thực thi của Nautilus.
- **`catalog.py`:** Quản lý kho `ParquetDataCatalog`, đồng bộ nến 1m, 5m, 15m, 1h, 4h, 1d từ kho dữ liệu OKX.

### 2.2. `backend/models/` — Domain Data Models, Parameters & Position Sizing
- `models.py`: Định nghĩa kiểu dữ liệu dùng chung (`PositionModel`, `OrderModel`, `CapitalLedger`, `Fill`).
- `params.py`: Cấu hình tham số chiến lược, chi phí sàn, đòn bẩy và mặc định rủi ro.
- `position_size.py`: Quy tắc phân bổ slot và tính toán quy mô vị thế.

### 2.3. `backend/alpha/dsl/` — Domain-Specific Language (Cho Bộ Tạo Chiến Lược Kéo-Thả)
- `indicator.py`: Bộ tính toán chỉ báo kỹ thuật vector hóa (EMA, RSI, MACD, ATR, Bollinger, SuperTrend...).
- `signal.py` & `strategy.py`: Parser AST cây điều kiện, chuẩn bị kế hoạch tín hiệu (Signal Plan) cho các chiến lược tạo qua giao diện UI kéo thả trước khi chuyển vào Nautilus Adapter.

### 2.4. `backend/optimize/` — Hyperparameter Search & Workflow Management
- `search/`: Thuật toán Grid Search và Bayesian Optimization. Mọi trial đều gọi Nautilus Engine để tính PnL và Sharpe.
- `funnel/`: Phễu sàng lọc Alpha 3 tầng (Fast Screening -> Full Backtest -> Stress Test).
- `book/`: Quản lý sổ đăng ký chiến lược (Strategy Registry) và metadata.
- `process/tasks.py`: Worker xử lý background jobs.

### 2.5. `backend/metrics/` — Chỉ Số Đánh Giá & Phân Loại Regime Thị Trường
- `metrics.py` & `trades.py` & `charts.py`: Thống kê PnL, Drawdown, Profit Factor, Sharpe/Sortino.
- `regime.py`: Phân loại trạng thái thị trường trên từng cây nến (Trend Up/Down, Surge, Crash, Range) để cung cấp báo cáo chẩn đoán đa chế độ trên UI.

### 2.6. `backend/carlo/` & `backend/wfa/` — Phân Tích Rủi Ro & Đánh Giá Độc Lập
- `carlo/`: Mô phỏng Monte Carlo 10,000 kịch bản và stress-test kịch bản xấu (Black Swan).
- `wfa/`: Walk-Forward Analysis kiểm tra tính bền vững out-of-sample của chiến lược.


---

## 3. Quy Trình Thực Thi Chiến Lược Đồng Nhất

Dù người dùng tạo chiến lược bằng **Native Python Code** (Nautilus Trader Strategy) hay qua **Nora DSL / Visual Builder**, luồng thực thi tại backend đều hội tụ về Nautilus:

```text
[Mã Chiến Lược Người Dùng]
        │
        ├─► [Native Nautilus Strategy] ──► NativeNautilusRunner ──┐
        │   (kế thừa nautilus Strategy)                           │
        │                                                         ├──► BacktestEngine (Nautilus)
        └─► [Nora DSL / Builder]        ──► NoraSlotStrategy   ──┘     • Venue OKX Margin/Netting
            (AST Condition Tree)            (Nautilus Adapter)         • Parquet Data Catalog
                                                                       • Ticker/Bar Event Streaming
                                                                                  │
                                                                                  ▼
                                                                     [format_nautilus_results]
                                                                                  │
                                                                                  ▼
                                                                     [Nora UI Standard Contract]
                                                                     (Equity, Trades, Metrics, Regimes)
```

---

## 4. Kiểm Thử Hệ Thống (100% Verification PASS)

- **`test/test_nautilus_native.py`:** Xác minh Native Nautilus Strategy execution, metadata detection, AST bypass và worker task end-to-end (4/4 PASS).
- **`test/test_nautilus_engine.py`:** Xác minh BacktestEngine & PortfolioEngine với dữ liệu OKX thực tế (13/13 PASS).
- **`test/test_all_modes_nautilus.py`:** Xác minh 4 chế độ Backtest, Paper, Testnet, Live.
