<!-- bmad:context -->
<!-- Verified 2026-10-09 against f4864d5. Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## nora

Nora Quantitative Backtesting & Live Execution Engine. Python 3.11+ backend (FastAPI :18010), React/Vite frontend (:18011), Numba JIT accelerated signal kernels. Planning and specifications live in `docs/bmad/`, theory in `docs/knowledge_base/`.

## Policy

- Một engine duy nhất: mọi chế độ backtest, paper, testnet đều chạy qua `nautilus/engine.py`. Nhanh hơn thì tối ưu trong worker / cache, tuyệt đối không dựng engine thứ hai.
- Mỗi logic một định nghĩa: cấm lặp code logic; gate `p9_ledger --dups` phải bằng 0.
- Phân tầng nghiêm ngặt: `models` → `signal`, `alpha` → `data` → `metrics`, `carlo` → `wfa`, `nautilus` → `strategies` / `alpha/store` → `jobs` → `routes` → `main`. Phân tầng theo `test_layering.py`.
- Chiến lược Python qua Strategy Contract (`alpha/contract.py`) → IR/Plan (`alpha/plan.py`). Xử lý theo 3 trạng thái: RUN | ADAPT | REJECT, không đoán.
- Cây dữ liệu chuẩn: `data/{market/okx/catalog, alpha/{user,education,presets.json}, users, backtest, wfa, carlo}`. Dữ liệu thị trường là ParquetDataCatalog của Nautilus (không còn pkl).
- Không mock số liệu trong backtest, WFA, Monte Carlo.
- Golden tests bit-identical: nếu lệch số thì sửa code, không nới ngưỡng test. Khoá API OKX chỉ đọc từ `~/.config/nora/okx.env`.

## Where things are

- Engine & Adapter: `backend/nautilus/` (engine = NautilusTrader adapter; catalog = nạp/quản lý catalog Parquet)
- Quản lý Dữ liệu: `backend/data/` (`crawl.py` = kéo nến OKX về catalog; `data.py` = đọc catalog cấp cho engine)
- Tín hiệu & Chỉ báo: `backend/signal/` (`compute.py`, `nodes.py`, `indicator.py`)
- Thư viện Alpha & DSL: `backend/alpha/` (`compile.py`, `contract.py`, `plan.py`, `strategies.py`, `store.py`)
- Mô hình & Cấu hình: `backend/models/` (`models.py`, `params.py`, `position_size.py`, `storage.py`, `meta.py`)
- Quản trị Job & Vòng đời: `backend/jobs/` (`runner.py`, `tasks.py`, `evaluate.py`)
- Đo lường & Hiệu suất: `backend/metrics/` (thống kê Nautilus PortfolioAnalyzer, `charts.py`, `trades.py`, `report.py`)
- Walk-Forward & Monte Carlo: `backend/wfa/`, `backend/carlo/`
- Người dùng & Phiên: `backend/users.py`, `backend/routes/users.py`
- API Routes & Services: `backend/routes/` (`alpha.py`, `book.py`, `data.py`, `process.py`, `users.py`, `home.py`)
- Giao diện người dùng: `frontend/` (React, Vite, 2 hệ thống song song Education / Coin qua `EduLayout` & `CoinLayout`)
- Tài liệu BMAD: `docs/bmad/`
- Script kiểm tra & nghiên cứu: `test/scripts/`

## Running and verifying

- Mọi tiến trình Python nặng phải chạy qua `ops/run_limited.sh --no-lock -- <args>` (cgroup slice 12GB RAM limit).
- Chạy backend FastAPI: `uvicorn backend.main:app --port 18010`
- Chạy frontend: `cd frontend && npm run dev` (cổng 18011) hoặc build production `cd frontend && npx vite build`.
- Kiểm tra tính toàn vẹn kiến trúc: `pytest test/test_layering.py` và `python test/scripts/p9_ledger.py --dups`.

## Conventions that differ from defaults

- UI chỉ là lớp trình bày: backend là nguồn sự thật duy nhất (`/api/studio/meta`, `/api/home/summary`). Frontend không tự tính toán số liệu tài chính hoặc giữ logic kinh doanh.
- Timeframe và nến: hoàn toàn là nến đã đóng (strictly closed causal bars) để triệt tiêu lookahead bias.
- Phí, trượt giá, funding rate được trừ thực tế theo từng nến và từng lệnh khớp, không ước lượng đơn giản hoá.

## Known pitfalls

- Không bao giờ chạy lệnh `cd` trong các công cụ agent hoặc script con.
- Không gọi lệnh git hoặc python có tương tác không đóng terminal; luôn dùng script có timeout và không phụ thuộc pager.
- Không tự ý thêm file kế hoạch rời `pXX_plan.md`; toàn bộ kế hoạch phải theo cấu trúc BMAD (`stories/` + `sprint-status.yaml`).

<!-- /bmad:context -->
