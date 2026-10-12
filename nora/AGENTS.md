<!-- bmad:context -->
<!-- Verified 2026-10-09 against f4864d5. Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## nora

Nora Quantitative Backtesting & Live Execution Engine. Python 3.11+ backend (FastAPI :18010), React/Vite frontend (:18011), Numba JIT accelerated signal kernels. Planning and specifications live in `docs/bmad/`, theory in `docs/knowledge_base/`.

## Policy

- Một engine duy nhất: mọi chế độ backtest, paper, testnet, live đều chạy qua `nautilus/engine.py`. Nhanh hơn thì tối ưu trong `optimize/`, tuyệt đối không dựng engine thứ hai.
- Mỗi logic một định nghĩa: cấm lặp code logic; gate `p9_ledger --dups` phải bằng 0.
- Phân tầng nghiêm ngặt: `models` → `alpha`/`metrics`/`wfa`/`carlo` → `crawl` → `optimize` → `routes`. `models`/`alpha/dsl` không làm I/O; `metrics` chỉ tính toán thuần. Gate `test_layering` strict = 0.
- Chiến lược Python qua Strategy Contract (`alpha/contract.py`) → IR (`alpha/dsl/signal.py`). Xử lý theo 3 trạng thái: RUN | ADAPT | REJECT, không đoán.
- Cây dữ liệu chuẩn: `data/{market/<sàn>/{cex,dex}, alpha, backtest, wfa, carlo, live/{paper,testnet,live}, cache/{process,shared}}`. Dữ liệu thị trường chỉ dùng `.pkl` có metadata trong attrs. Cache chỉ giữ tiến trình đang chạy hoặc dở dang.
- Không mock số liệu trong backtest, WFA, Monte Carlo.
- Golden tests bit-identical: nếu lệch số thì sửa code, không nới ngưỡng test. Khoá API OKX chỉ đọc từ `~/.config/nora/okx.env`. Chế độ live thật bắt buộc có cờ `confirm_live`.

## Where things are

- Engine & dữ liệu: `backend/nautilus/` (engine = NautilusTrader adapter), DSL/IR: `backend/alpha/dsl/`, mô hình & tham số: `backend/models/`
- Thư viện Alpha & Contract: `backend/alpha/` (các chiến lược định lượng, adapter, kiểm duyệt)
- Tối ưu hoá & tìm kiếm: `backend/optimize/` (WFA, Monte Carlo, regime, portfolio funnel)
- Live trading: đã gỡ `backend/live/`; live qua Nautilus TradingNode là việc tương lai (R7)
- API Routes & Services: `backend/routes/` (5 router chính)
- Giao diện người dùng: `frontend/` (React, Vite, giao tiếp API backend qua `/api`)
- Tài liệu BMAD: `docs/bmad/` (kiến trúc `architecture/`, PRD `prd.md`, câu chuyện `stories/`, trạng thái `sprint-status.yaml`)
- Script kiểm tra & nghiên cứu: `test/scripts/`

## Running and verifying

- Mọi tiến trình Python nặng phải chạy qua `ops/run_limited.sh` (cgroup slice 12GB RAM limit).
- Chạy backend FastAPI: `uvicorn backend.routes.app:app --port 18010`
- Chạy frontend: `cd frontend && npm run dev` (cổng 18011) hoặc build production `npm run build`.
- Kiểm tra tính toàn vẹn kiến trúc: `pytest test/test_layering.py` và `python test/scripts/p9_ledger.py --dups`.

## Conventions that differ from defaults

- UI chỉ là lớp trình bày: backend là nguồn sự thật duy nhất (`/api/studio/meta`). Frontend không tự tính toán số liệu tài chính hoặc giữ logic kinh doanh.
- Timeframe và nến: hoàn toàn là nến đã đóng (strictly closed causal bars) để triệt tiêu lookahead bias.
- Phí, trượt giá, funding rate được trừ thực tế theo từng nến và từng lệnh khớp, không ước lượng đơn giản hoá.

## Known pitfalls

- Không bao giờ chạy lệnh `cd` trong các công cụ agent hoặc script con.
- Không gọi lệnh git hoặc python có tương tác không đóng terminal; luôn dùng script có timeout và không phụ thuộc pager.
- Không tự ý thêm file kế hoạch rời `pXX_plan.md`; toàn bộ kế hoạch phải theo cấu trúc BMAD (`stories/` + `sprint-status.yaml`).

<!-- /bmad:context -->
