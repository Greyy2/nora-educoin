# HỆ THỐNG TÀI LIỆU DỰ ÁN NORA (BMAD & KNOWLEDGE BASE)

## Cấu trúc thư mục

```text
nora/
├── backend/                  # CHỈ logic lõi (không script, không lệnh terminal)
│   ├── main.py               # app FastAPI: gắn router + phục vụ frontend/dist
│   ├── api/
│   │   ├── routers/          # book (backtest/WFA/MC, sổ, kho alpha), funnel, strategies, portfolio, data
│   │   ├── jobs/             # batch.py (khởi chạy/theo dõi/huỷ job), runner.py (MỘT cửa chạy mọi job)
│   │   └── modes.py          # chế độ Cơ bản / Nâng cao -> params của job
│   ├── core/
│   │   ├── data/             # loader, resampler, quality_gate, shared (kho chỉ báo + nền mmap dùng chung), crawler (Binance), promote
│   │   ├── signals/          # kernels (chỉ báo causal), evaluator (cây điều kiện), diagnostics
│   │   ├── strategy/         # library (chiến lược lõi + bot), book (7 ứng viên sổ, materialize)
│   │   ├── params/           # schema (StrategyParams), template, builder (chi phí sàn, kiểm DCA), presets, modes
│   │   ├── execute/          # tracker (vào/ra, SL/TP/trailing, DCA, thanh lý, funding), ledger (vốn chung), models
│   │   ├── metrics/          # trades (PnL, win rate, PF), returns (lợi suất ngày, Sharpe, Sortino, MDD), portfolio
│   │   ├── backtest/         # engine (một tài sản), portfolio (nhiều tài sản/chiến lược), run (job backtest)
│   │   └── analytics/        # dashboard (payload trang Danh mục), feeds (nguồn backtest)
│   ├── db/                   # data_layout (đường dẫn), local_pkl (đọc/ghi nến), tick_storage
│   ├── optimize/             # book (dựng sổ A–D), store (kho kết quả SQLite + streaming), registry (kho alpha, sổ, xuất bản), shared (làm nóng/dọn kho dùng chung)
│   │   └── funnel/           # phễu S0–FINAL: gates, generate, evaluate, antiluck, sizing, stats, storage, orchestrator, run
│   ├── wfa/                  # walk_forward (fold + WFA danh mục), run (job WFA)
│   ├── carlo/                # monte_carlo (bootstrap, kịch bản cực xấu, gate)
│   └── utils/                # parallel (worker), memwatch (RAM), lru, jsonsafe, jobs (tham số/tiến độ/kết quả job), ops/ (run_limited.sh, systemd)
├── test/                     # pytest + golden/ + scripts/ (smoke, bench, research, make_golden, check_tests_vs_ref)
├── data/                     # dữ liệu & cache (không commit), TRỪ data/alphas/ (sổ alpha / registry, có commit)
├── frontend/src/             # Vite + React: pages/, components/, lib/, hooks/, api.js
└── docs/                     # tài liệu
```

### Chạy việc gì ở đâu — một cửa: API

Mọi việc nặng là **job** chạy qua cùng một đường: endpoint API → `api/jobs/batch.launch` ghi `params.json` → tiến trình riêng
`ops/run_limited.sh -- -m backend.api.jobs.runner <job_dir>` (trần RAM nora.slice) → `run_job(params)` của module.
UI, terminal (curl) hay script đều gọi **cùng endpoint**; không có lệnh terminal riêng cho từng việc.

| Việc | Endpoint | Loại job → module |
|---|---|---|
| Backtest | `POST /api/studio/book/backtest` | `book_backtest` → `core/backtest/run.py` |
| Walk-forward | `POST /api/studio/book/wfa` | `book_wfa` → `wfa/run.py` |
| Monte Carlo | `POST /api/studio/book/mc` | (nhẹ, chạy ngay trong API) → `carlo/monte_carlo.py` |
| Dựng sổ chiến lược | `POST /api/studio/book/build` | `book_build` → `optimize/book.py` |
| Phễu alpha | `POST /api/studio/funnel/runs` | `funnel_run` → `optimize/funnel/run.py` |
| Dựng preset | `POST /api/studio/strategies/presets` | `presets_build` → `core/params/presets.py` |
| Tải dữ liệu Binance | `POST /api/data/crawl` | `data_crawl` → `core/data/crawler.py` |
| Đưa dữ liệu vào kho | `POST /api/data/promote` | `data_promote` → `core/data/promote.py` |

Theo dõi / huỷ: `GET /api/studio/book/jobs`, `GET /api/studio/book/jobs/{id}`, `POST /api/studio/book/jobs/{id}/cancel`.
Ví dụ terminal: `curl -X POST localhost:18010/api/studio/book/backtest -H 'content-type: application/json' -d '{"mode":"basic","strategies":[{"id":"trend_long"}],"start":"2025-03-01","end":"2025-04-30"}'`.
Script kiểm tra/nghiên cứu (không phải logic sản phẩm) nằm ở `test/scripts/`, chạy bằng `ops/run_limited.sh -- test/scripts/<tên>.py`.

---

## Cấu trúc tài liệu

Tài liệu gồm ba tầng:

1. **`bmad/`: bộ tài liệu hiện hành** (BMAD: yêu cầu, kiến trúc, epic, story, trạng thái). Đây là nơi bắt đầu.
2. **Tài liệu chuyên đề** ở gốc `docs/`: hợp đồng API cho UI, đường ống alpha, tín hiệu và chiến lược, bố cục dữ liệu.
3. **`knowledge_base/`: tri thức và luật thép** (causal, không nới gate, chi phí thật, lý thuyết nền). Còn hiệu lực, không chứa code.

```text
nora/docs/
├── README.md                     # file này
├── bmad/
│   ├── README.md                 # mục lục, quy ước trạng thái, cách cập nhật khi xong một story
│   ├── prd.md                    # yêu cầu sản phẩm: mục tiêu, FR/NFR, ràng buộc, rủi ro
│   ├── architecture.md           # kiến trúc và đặc tả kỹ thuật (khớp code)
│   ├── epics.md                  # 11 epic, 70 story, bảng trạng thái tổng
│   ├── sprint-status.yaml        # trạng thái máy đọc được
│   ├── stories/                  # mỗi story một file E<n>-S<m>-<slug>.md
│   └── legacy/                   # BMAD giai đoạn DEX (chỉ lịch sử, không còn đúng hiện trạng)
├── ui_contract.md                # hợp đồng API cho UI v2
├── alpha_pipeline.md             # từ chiến lược tới alpha sẵn sàng testnet
├── signals_strategies.md         # kernel, tín hiệu, quản lý vị thế, chiến lược
├── data_layout.md                # dữ liệu thị trường, manifest, quality gate
└── knowledge_base/               # tri thức, luật thép (01_ đến 04_)
```

## Hiện trạng (01/10/2026)

- Pipeline `data -> tín hiệu -> backtest -> WFA -> Monte Carlo -> holdout -> alpha/sổ` chạy được đầu-cuối trên 8 perp Binance, kết quả tái lập bit-identical (golden test).
- Alpha `trend_long_perp__SOL` đạt đủ cổng; sổ `breakout_4h_long + breakout_4h_short` trượt holdout (`HOLDOUT_FAILED`), không có cấu hình testnet cho sổ.
- UI v2 (Danh mục, Backtest/WFA/Monte Carlo, Alpha) chạy với job nền; Live/Testnet hiện là dữ liệu giả lập; chưa có bot testnet/live; API chưa xác thực.
- Trạng thái chi tiết: [bmad/epics.md](bmad/epics.md) (7 epic done, 1 in-progress, 3 backlog; 70 story).

## Nguyên tắc vận hành cho developer và AI

- **Bắt đầu phiên mới:** đọc [bmad/README.md](bmad/README.md), [bmad/prd.md](bmad/prd.md) (mục 3, 7, 8), [bmad/epics.md](bmad/epics.md) và `knowledge_base/02_boss_mandates_and_rulebase.md`.
- **Trước khi sửa code:** đọc phần liên quan trong [bmad/architecture.md](bmad/architecture.md). Golden test phải giữ bit-identical trừ khi chủ đích đổi ngữ nghĩa backtest.
- **Chạy job nặng:** luôn qua `ops/run_limited.sh` (nora.slice 12G, hàng đợi); chi tiết ở `bmad/architecture.md` mục 12.
- **Khi xong một story:** cập nhật file story (trạng thái, task, Evidence, Change Log), `bmad/sprint-status.yaml`, `bmad/epics.md`, rồi chạy kiểm tra nhất quán trong `bmad/README.md`.
- **Khi chủ sở hữu đưa ra góp ý hoặc luật mới:** bổ sung vào `knowledge_base/02_boss_mandates_and_rulebase.md`.
- **Không nới gate** để có kết quả đẹp; không có kết quả đạt thì ghi nhận trung thực.
