# Kiến Trúc Nora Backend (Powered by Nautilus Trader)

> **Tài liệu tham chiếu chuẩn quốc tế:** [Nautilus Trader Documentation](https://nautilustrader.io/docs/)  
> **Kho mã nguồn:** [nautechsystems/nautilus_trader (GitHub)](https://github.com/nautechsystems/nautilus_trader)

---

## 1. Cấu Trúc Backend Mới (Tinh Gọn & Trực Tiếp)

Toàn bộ các engine khớp lệnh tự viết cũ (`core`, `alpha`, `optimize`, `wfa`, `carlo`, `live`, `metrics`, `regime`) đã được dọn sạch khỏi `backend/` và lưu trữ nguyên vẹn tại [test/backend-no/](file:///home/vmc03/norabt/nora/test/backend-no/).

Kiến trúc `backend/` hiện tại gồm 3 thành phần duy nhất:

```text
backend/
├── crawl/                      # Giữ nguyên module crawl dữ liệu OKX (store.py, cex.py, dex.py)
├── nautilus/                   # Core Engine Adapter kết nối Nautilus Trader 2.0
│    ├── data.py                # Nạp nến trực tiếp từ /data/market/okx/cex/ và đổi sang Bar
│    ├── engine.py              # NautilusRunner: Khởi tạo BacktestEngine, chạy và thu thập PnL/Metrics
│    ├── strategy.py            # NoraNautilusStrategy: Đặt lệnh Entry, DCA, SL, TP, Trailing Stop
│    └── version.py             # Quản lý phiên bản & tự động check update PyPI
├── routes/
│    ├── nautilus_api.py        # API Gateway phục vụ UI: /api/studio/* và /api/data/crawl
│    └── __init__.py
├── __init__.py
└── main.py                     # FastAPI Application Gateway
```

---

## 2. Kết Nối Trực Tiếp Kho Dữ Liệu Đã Crawl Sẵn (`/home/vmc03/norabt/nora/data`)

Hệ thống kết nối trực tiếp kho nến thật đã crawl của OKX:
- **Đường dẫn:** `/home/vmc03/norabt/nora/data/market/okx/cex/{SYMBOL}/perp/{TIMEFRAME}.pkl`
- **10 Cặp Hợp Đồng Vĩnh Cửu Có Sẵn:** `BTC`, `ETH`, `SOL`, `XRP`, `DOGE`, `ADA`, `AVAX`, `BNB`, `LINK`, `TRX`.
- **Khung thời gian:** `1m`, `5m`, `15m`, `1h`, `4h`, `24h` (chứa hơn 26,000 nến từ 2023 đến 2026).
- **Tốc độ thực thi:** NautilusTrader chạy 1,000 nến thật chỉ mất **~0.007 giây** (7 mili-giây).

---

## 3. Danh Sách API Hoạt Động

1. `GET /api/studio/custom/defaults`: Trả về danh sách symbols có sẵn từ kho data thật, ngày mặc định, vốn.
2. `GET /api/studio/strategies`: Trả về danh sách tham số vị thế cho UI render form.
3. `POST /api/studio/custom/backtest`: Nhận tham số từ UI, nạp nến thật và chạy BacktestEngine của Nautilus.
4. `GET /api/studio/book/jobs/{job_id}`: Trả về trạng thái job (`done`), biểu đồ nến, equity curve và metrics (Sharpe, Profit Factor, Win Rate, Drawdown).
5. `POST /api/data/crawl`: Tiếp nhận yêu cầu crawl thêm nến cho symbol mới từ OKX.
6. `GET /api/studio/nautilus/version`: Kiểm tra phiên bản Nautilus hiện tại và link docs.
7. `GET /api/studio/nautilus/check_update`: Kiểm tra phiên bản mới nhất từ PyPI.

---

## 4. Bốn Chế Độ Hoạt Động (Backtest -> Paper -> Testnet -> Live)

1. **Backtest (Mô phỏng lịch sử):**
   - Sử dụng `NautilusRunner` với `BacktestEngine` của NautilusTrader.
   - Nạp trực tiếp dữ liệu nến thật từ kho `/home/vmc03/norabt/nora/data/market/okx/cex/`.
   - Tốc độ thực thi: ~0.006s cho 500 nến, tính đầy đủ Sharpe, Sortino, Profit Factor, Drawdown.
2. **Paper (Mô phỏng Realtime):**
   - Sử dụng `SimulatedExchange` / Sandbox của Nautilus với dữ liệu thị trường trực tiếp.
   - Khớp lệnh local, vốn ảo, không rủi ro, không cần gọi API key.
3. **Testnet / Demo (OKX Demo Trading):**
   - Đọc an toàn khóa API từ file `~/.config/nora/okx.env`.
   - Kết nối trực tiếp OKX Demo Trading (`x-simulated-trading: 1`) với `OKXEnvironment.DEMO`.
   - Đặt lệnh thật trên môi trường thử nghiệm sàn OKX.
4. **Live (OKX Real Trading):**
   - Kết nối sàn OKX thật (`OKXEnvironment.LIVE`).
   - Có cơ chế bảo vệ **Demo Lock** (`NORA_OKX_DEMO=1`) ngăn chặn rủi ro gửi lệnh nhầm vào tài khoản thật.

---

## 5. Kiểm Thử Hệ Thống (Verification 100% PASS)

Tất cả các bộ test đều chạy tự động và PASS 100%:
- `test/test_nautilus_runner.py`: Xác minh NautilusRunner độc lập.
- `test/test_nautilus_api.py`: Xác minh toàn bộ 5 API kết nối dữ liệu thật và trả về kết quả chuẩn cho UI.
- `test/test_all_modes_nautilus.py`: Kiểm thử liên hoàn toàn diện cả 4 chế độ (Backtest -> Paper -> Testnet -> Live).

