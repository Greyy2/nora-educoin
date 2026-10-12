# Cây mã nguồn Nora (Source Tree Specification)

Mỗi file đúng một dòng trách nhiệm, phản ánh cấu trúc thực tế của repository sau tái cấu trúc P9–P12.

## 1. Backend (`nora/backend/`)

- `main.py` — Điểm vào ứng dụng FastAPI duy nhất (`uvicorn backend.main:app`).

### `backend/core/` (Lõi logic thuần: 0 I/O, không import ngoài core)
- `core/models.py` — Định nghĩa cấu trúc dữ liệu lệnh (`OrderModel`), khớp lệnh (`Fill`), vị thế (`PositionModel`), tài khoản (`Account`), sự kiện và kế toán (`CapitalLedger`).
- `core/params.py` — Quản lý tham số chiến lược: lược đồ (`StrategyParams`), mẫu thay thế `{param}`, trình dựng tham số (`build_params`) và hiện thực hóa vị thế danh mục.
- `core/indicator.py` — Thư viện chỉ báo định lượng causal tăng tốc Numba JIT; đặc tả chữ ký DSL cho `self.feat.*` và `self.op.*`.
- `core/signal.py` — Biểu diễn trung gian IR của DSL (`Program`, `Node`, `DslError`, `code_hash`), bộ thông dịch AST vector hoá và ảnh chụp tín hiệu.
- `core/position_size.py` — Chính sách quản lý vốn, kích thước vị thế, tính toán các mức SL / TP / DCA / Trailing stop và kiểm duyệt rủi ro danh mục.
- `core/backtest.py` — Engine thực thi duy nhất của Nora (`BacktestEngine`, `PortfolioEngine`), xử lý khớp lệnh nến/tick, CEX/DEX, phí và funding rate.

### `backend/alpha/` (Hợp đồng chiến lược & Bộ chuyển đổi)
- `alpha/contract.py` — Strategy Contract: kiểm tra hợp đồng (`check_contract`), giới hạn mã nguồn, danh mục primitive và trợ lý viết code tất định.
- `alpha/compile.py` — Trình biên dịch chuyển đổi mã người dùng/hệ thống sang IR chuẩn; nạp và lưu trữ file chiến lược.

### `backend/metrics/` (Đo lường & Chỉ số tài chính)
- `metrics/metrics.py` — Bộ chỉ số hiệu suất chuẩn định lượng (Sharpe, Sortino, Calmar, Max Drawdown, CAGR, Win Rate) tính trên chuỗi lợi suất ngày (365 ngày/năm).
- `metrics/trades.py` — Phân tích chi tiết từng lệnh giao dịch đã đóng, lãi/lỗ gộp, profit factor, payoff ratio và đối soát sim ↔ sàn.
- `metrics/charts.py` — Tạo chuỗi dữ liệu trực quan hoá cho frontend: đường vốn (equity), sụt giảm (underwater), phân phối lợi suất và feeds.

### `backend/regime/` (Chế độ thị trường)
- `regime/regime.py` — Nhận diện phân loại chế độ thị trường theo thời gian thực (Bull/Bear/Volatile/Quiet) và học ma trận tương thích chiến lược.

### `backend/wfa/` (Walk-Forward Analysis)
- `wfa/wfa.py` — Phân tích WFA đa khung đa tài sản trên một sổ vốn duy nhất, kiểm tra ổn định tham số (PBO-CSCV, lân cận).

### `backend/carlo/` (Monte Carlo Stress Testing)
- `carlo/carlo.py` — Phân tích Monte Carlo bootstrap khối trên chuỗi MTM và kiểm thử kịch bản rủi ro cực đoan.

### `backend/optimize/` (Tối ưu hóa, Tìm kiếm & Hàng đợi)
- `optimize/search/generate.py` — Sinh lưới tham số alpha, biến thể regime và kiểm tra cổng ban đầu S0.
- `optimize/search/evaluate.py` — Bộ điều phối chạy hàng loạt backtest danh mục và chia sẻ dữ liệu bộ nhớ dùng chung.
- `optimize/funnel/stages.py` — Quản lý các tầng phễu kiểm duyệt alpha (S0 → FINAL), xếp hạng và xuất bản sổ chiến lược.
- `optimize/funnel/storage.py` — Kho lưu trữ kết quả chạy phễu (`RunStore` SQLite + Parquet).
- `optimize/book/build.py` — Thuật toán xây dựng và tối ưu hoá sổ chiến lược danh mục từ các alpha đạt chuẩn.
- `optimize/book/registry.py` — Kho lưu trữ sổ chiến lược đã duyệt, sổ thử nghiệm, phiên bản engine và danh mục Top Agents.
- `optimize/process/process.py` — Quản lý vòng đời job nền (khởi tạo, theo dõi tiến độ, huỷ bỏ, phục hồi sau sự cố).
- `optimize/process/tasks.py` — Triển khai cụ thể các tác vụ nền: backtest sổ, WFA, regime report, custom backtest, edu precompute.
- `optimize/process/workers.py` — Giám sát tài nguyên RAM (`memwatch`) và phân bổ tiến trình worker an toàn.

### `backend/crawl/` (Thu thập & Lưu trữ dữ liệu thị trường)
- `crawl/cex.py` — Thu thập nến OHLCV và funding rate từ sàn CEX (OKX, Binance).
- `crawl/dex.py` — Thu thập swap tick on-chain cho các cặp giao dịch DEX.
- `crawl/store.py` — Điểm quản lý dữ liệu thị trường tập trung duy nhất: nạp/ghi `.pkl`, resample khung nến, kiểm định chất lượng (Quality Gate) và bộ đệm LRU.

### `backend/live/` (Thực thi thời gian thực)
- `live/live.py` — Vòng lặp giao dịch live bot thời gian thực, quản lý kết nối API sàn OKX, ký lệnh và kiểm soát an toàn tiền thật (`confirm_live`).
- `live/testnet.py` — Hồ sơ kết nối sàn thử nghiệm OKX Demo Trading.
- `live/paper.py` — Hồ sơ giao dịch mô phỏng Paper Trading (đọc nến thật, khớp qua engine `core/backtest.py`).

### `backend/routes/` (Giao tiếp API FastAPI)
- `routes/alphas.py` — API thư viện alpha, chi tiết công thức và thống kê.
- `routes/book.py` — API quản lý sổ chiến lược và chạy backtest/WFA danh mục.
- `routes/chart.py` — API cung cấp nến và biểu đồ tín hiệu vào/ra chi tiết.
- `routes/custom.py` — API phục vụ backtest chiến lược tự do của người dùng.
- `routes/data.py` — API kiểm soát dữ liệu nến, tải nến và kiểm định chất lượng.
- `routes/education.py` — API phục vụ thư viện giáo trình 50 mẫu chiến lược.
- `routes/funnel.py` — API phễu duyệt alpha và theo dõi tiến trình tối ưu.
- `routes/jobs.py` — API theo dõi trạng thái và kết quả các tác vụ nền.
- `routes/live.py` — API điều khiển và giám sát bot giao dịch live.
- `routes/market.py` — API hiển thị trạng thái tín hiệu thời gian thực của thị trường.
- `routes/modes.py` — API cấu hình chế độ Cơ bản / Nâng cao.
- `routes/portfolio.py` — API bảng điều khiển danh mục và lịch sử lệnh.
- `routes/strategies.py` — API quản lý danh mục chiến lược hệ thống và presets.

---

## 2. Dữ liệu (`nora/data/`)

- `data/market/<exchange>/cex/<symbol>/` — File nến `.pkl` chuẩn hoá và `manifest.json`.
- `data/alpha/strategies/` — Các file định nghĩa chiến lược hệ thống.
- `data/alpha/education/` — File mẫu 50 chiến lược giáo trình (`educationSamples.js` / JSON).
- `data/alpha/user/` — Các chiến lược người dùng đã lưu trữ vĩnh viễn (`<id>.json`).
- `data/backtest/<job_id>/` — Kết quả và tham số các lượt chạy backtest lưu trữ lâu dài.
- `data/wfa/<job_id>/` — Kết quả phân tích Walk-Forward Analysis.
- `data/carlo/<job_id>/` — Kết quả mô phỏng Monte Carlo.
- `data/live/<mode>/` — Trạng thái trạng thái bot và nhật ký lệnh thời gian thực (`state.json`, `events.jsonl`).
- `data/cache/process/<job_id>/` — Thư mục tạm thời của các tiến trình đang thực thi (xoá sau khi hoàn tất).
- `data/cache/shared/` — Bộ nhớ chia sẻ mmap cho các worker tính toán song song.

---

## 3. Frontend (`nora/frontend/`)

- `src/main.jsx` & `src/App.jsx` — Điểm khởi đầu ứng dụng React SPA và định tuyến URL.
- `src/layout/Shell.jsx` — Khung giao diện chính (Header, Sidebar, Navigation).
- `src/pages/Portfolio.jsx` — Màn hình bảng điều khiển danh mục (Dashboard).
- `src/pages/Backtest.jsx` — Màn hình chạy và phân tích backtest sổ chiến lược.
- `src/pages/Funnel.jsx` — Màn hình phễu lọc và tối ưu hoá alpha.
- `src/pages/AlphaCatalog.jsx` — Màn hình thư viện chiến lược hệ thống.
- `src/pages/CreateAlpha.jsx` — Màn hình trình soạn thảo Python Studio.
- `src/pages/Education.jsx` — Màn hình giáo trình định lượng 50 mẫu chiến lược.
- `src/pages/Live.jsx` — Màn hình giám sát và điều khiển bot giao dịch trực tiếp.
- `src/pages/History.jsx` — Màn hình tra cứu lịch sử các lượt chạy.
- `src/components/studio/` — Các thành phần biên dịch, editor Monaco, biểu đồ kết quả backtest.
- `src/components/education/` — Các thành phần giáo trình định lượng, 50 mẫu chiến lược, Spotlight walkthrough.
- `src/api.js` — Thư viện gọi API kết nối backend `:18010`.

---

## 4. Vận hành (`nora/ops/`)

- `ops/run_limited.sh` — Bộ chạy Python giới hạn tài nguyên an toàn (systemd slice 12GB RAM).
- `ops/install_user_units.sh` — Script cài đặt các service nền systemd.
- `ops/deploy_nginx.sh` — Cấu hình Nginx phục vụ web frontend và reverse proxy API.
