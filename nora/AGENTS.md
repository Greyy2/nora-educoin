<!-- bmad:context -->
<!-- Verified 2026-10-09 against f4864d5. Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## nora

Nora Quantitative Backtesting & Live Execution Engine. Python 3.11+ backend (FastAPI), React/Vite frontend. Numba JIT accelerated signal kernels. Planning and specifications live in `docs/bmad/`, theory in `docs/knowledge_base/`, full EDU/COIN split blueprint in `docs/architecture-edu-coin-backtest.md`.

**Product split (target):**
- **COIN API** `backend/apps/coin.py` — port 18010, `uvicorn backend.apps.coin:app`; studio, live bot, data, portfolio. Frontend: `frontend/dist-coin` (build: `npm run build:coin`).
- **EDU API** `backend/apps/edu.py` — port 18020, `uvicorn backend.apps.edu:app`; users/auth, edu market, studio (read). Frontend: `frontend/dist-edu` (build: `npm run build:edu`).
- **Legacy monolith** `backend/main.py` — port 18010, `uvicorn backend.main:app`; giữ trong thời gian migration; KHÔNG dùng song song với nora-coin.

## Policy

- Một engine duy nhất: mọi chế độ backtest, paper, testnet đều chạy qua `nautilus/engine.py`. Nhanh hơn thì tối ưu trong worker / cache, tuyệt đối không dựng engine thứ hai.
- Mỗi logic một định nghĩa: cấm lặp code logic; gate `p9_ledger --dups` phải bằng 0.
- Phân tầng nghiêm ngặt: `models` → `signal`, `alpha` → `data` → `metrics`, `carlo` → `wfa`, `nautilus` → `strategies` / `alpha/store` → `jobs` → `routes` → `main`. Phân tầng theo `test_layering.py`.
- Chiến lược Python qua Strategy Contract (`alpha/contract.py`) → IR/Plan (`alpha/plan.py`). Xử lý theo 3 trạng thái: RUN | ADAPT | REJECT, không đoán.
- Cây dữ liệu chuẩn: `data/{market/okx/catalog, alpha/{user,education,presets.json}, users, backtest, wfa, carlo}`. Dữ liệu thị trường là ParquetDataCatalog của Nautilus (không còn pkl).
- Không mock số liệu trong backtest, WFA, Monte Carlo.
- Golden tests bit-identical: nếu lệch số thì sửa code, không nới ngưỡng test. Khoá API OKX chỉ đọc từ `~/.config/nora/okx.env`.
- **EDU app không được có live bot control hoặc exchange credential.** COIN app không được có edu private user/content data.

## Where things are

- Engine & Adapter: `backend/nautilus/` (engine = NautilusTrader adapter; catalog = nạp/quản lý catalog Parquet)
- Quản lý Dữ liệu: `backend/data/` (`crawl.py` = kéo nến OKX về catalog; `data.py` = đọc catalog cấp cho engine)
- Tín hiệu & Chỉ báo: `backend/signal/` (`compute.py`, `nodes.py`, `indicator.py`)
- Thư viện Alpha & DSL: `backend/alpha/` (`compile.py`, `contract.py`, `plan.py`, `strategies.py`, `store.py`)
- Mô hình & Cấu hình: `backend/models/` (`models.py`, `params.py`, `position_size.py`, `storage.py`, `meta.py`)
- Quản trị Job & Vòng đời: `backend/jobs/` (`runner.py`, `tasks.py`, `evaluate.py`)
- Đo lường & Hiệu suất: `backend/metrics/` (thống kê Nautilus PortfolioAnalyzer, `charts.py`, `trades.py`, `report.py`)
- Walk-Forward & Monte Carlo: `backend/wfa/`, `backend/carlo/`
- Người dùng & Phiên: `backend/users.py`, `backend/routes/system.py` (users_router, edu_router)
- **App factories (mới):** `backend/apps/edu.py`, `backend/apps/coin.py`
- API Routes & Services: `backend/routes/` (`studio.py`, `live.py`, `data.py`, `system.py`)
- Giao diện người dùng: `frontend/` (React, Vite); `App.edu.jsx` + `App.coin.jsx` là hai SPA riêng; `App.jsx` là monolith legacy.
- Nginx configs: `ops/nginx/{nora,coin.nora,edu.nora}.expsolution.io.conf`
- Systemd units: `ops/systemd/{nora-api,nora-coin,nora-edu}.service.in`
- Tài liệu BMAD: `docs/bmad/`
- Script kiểm tra & nghiên cứu: `test/scripts/`

## Running and verifying

- Mọi tiến trình Python nặng phải chạy qua `ops/run_limited.sh --no-lock -- <args>` (cgroup slice 12GB RAM limit).
- **COIN API (target):** `./start.sh coin` hoặc `uvicorn backend.apps.coin:app --port 18010`
- **EDU API (target):** `./start.sh edu` hoặc `uvicorn backend.apps.edu:app --host 127.0.0.1 --port 18020`
- **Cả hai:** `./start.sh all`
- Legacy monolith: `./start.sh legacy` hoặc `uvicorn backend.main:app --port 18010`
- Chạy frontend dev: `cd frontend && npm run dev:coin` (:18011) hoặc `npm run dev:edu` (:18021).
- Build production: `cd frontend && npm run build:all` (→ dist-coin + dist-edu).
- Kiểm tra tính toàn vẹn kiến trúc: `pytest test/test_layering.py` và `python test/scripts/p9_ledger.py --dups`.

## Conventions that differ from defaults

- UI chỉ là lớp trình bày: backend là nguồn sự thật duy nhất (`/api/studio/meta`, `/api/home/summary`). Frontend không tự tính toán số liệu tài chính hoặc giữ logic kinh doanh.
- Timeframe và nến: hoàn toàn là nến đã đóng (strictly closed causal bars) để triệt tiêu lookahead bias.
- Phí, trượt giá, funding rate được trừ thực tế theo từng nến và từng lệnh khớp, không ước lượng đơn giản hoá.

## Known pitfalls

- Không bao giờ chạy lệnh `cd` trong các công cụ agent hoặc script con.
- Không gọi lệnh git hoặc python có tương tác không đóng terminal; luôn dùng script có timeout và không phụ thuộc pager.
- Không tự ý thêm file kế hoạch rời `pXX_plan.md`; toàn bộ kế hoạch phải theo cấu trúc BMAD (`stories/` + `sprint-status.yaml`).
- `backend/routes/system.py` dùng pattern ghép nhiều "module" vào 1 file: `ROUTERS` (dòng 345) nằm trước khi `users_router`/`edu_router` được định nghĩa — Pyrefly báo lỗi "uninitialized" nhưng runtime đúng vì Python thực thi tuần tự. Không "sửa" bằng cách di chuyển ROUTERS ra cuối file vì sẽ phá vỡ import order.
- Khi deploy COIN: dùng `nora-coin.service` (port 18010, `backend.apps.coin:app`), KHÔNG chạy song song `nora-api` và `nora-coin` trên cùng port 18010.

<!-- /bmad:context -->
