# HỆ THỐNG TÀI LIỆU DỰ ÁN NORA (BMAD & KNOWLEDGE BASE)

## Cấu trúc thư mục

```text
nora/
├── backend/
│   ├── main.py            # App FastAPI (uvicorn backend.main:app)
│   ├── api/               # routers/, schemas.py, control.py (điều khiển node cũ), jobs/ (job nền: store, batch, scan)
│   ├── core/              # Lõi nghiệp vụ
│   │   ├── contracts.py   # Hợp đồng dữ liệu Backtest/WFA/Monte Carlo
│   │   ├── data/          # loader, resampler, quality_gate, crawler/
│   │   ├── signals/       # kernels, diagnostics, evaluator
│   │   ├── strategy/      # params, strategy_book/library, templates, builder/generator/validator, DC
│   │   ├── backtest/      # engine, portfolio, execution, metrics, shared_data
│   │   ├── analytics/     # portfolio_dashboard, stats_metrics, queries
│   │   └── research/      # nghiên cứu thị trường (regime, DC, insight, scan)
│   ├── db/                # data_layout, local_pkl, tick_storage, mysql, mongo, models
│   ├── optimize/          # sinh/chạy alpha, funnel/ (phễu S0–FINAL), build_strategy_book, optimize_alphas, run_funnel, registry, book_export
│   ├── wfa/               # walk_forward (đơn tài sản), portfolio_wfa, validate_book (lệnh WFA sổ)
│   ├── carlo/             # monte_carlo
│   └── utils/             # lru, parallel, memwatch, jsonsafe, jobresult, ops/ (run_limited.sh, systemd)
├── test/                  # pytest + golden/ (snapshot bit-identical) + make_golden.py
├── data/                  # dữ liệu & cache (không commit), TRỪ data/alphas/ (sổ alpha / registry, có commit)
├── requirements.txt
├── frontend/              # Vite SPA
└── docs/                  # tài liệu
```

### Lệnh chạy nằm ở đâu

| Lệnh (`python -m …`) | Nằm ở | Làm gì |
|---|---|---|
| `backend.optimize.run_funnel` | `optimize/` | Phễu lọc alpha: sinh → backtest → chống ăn may → WFA → MC → chốt |
| `backend.optimize.build_strategy_book` | `optimize/` | Dựng sổ chiến lược (tối ưu nhiều giai đoạn A–D) |
| `backend.optimize.optimize_alphas` | `optimize/` | Tối ưu alpha đơn tài sản |
| `backend.optimize.build_presets` | `optimize/` | Ghi `data/alphas/presets.json` (tham số tốt nhất từng chiến lược) |
| `backend.optimize.build_alpha_registry`, `portfolio_sizing`, `robustness_check` | `optimize/` | Kho alpha, chọn cỡ vị thế, kiểm độ bền |
| `backend.wfa.validate_book` | `wfa/` | Walk-forward cho sổ danh mục |
| `backend.core.backtest.run_book_backtest` | `core/backtest/` | Backtest một sổ / danh sách chiến lược |
| `backend.core.backtest.smoke_check`, `check_signals_strategies`, `bench_engine` | `core/backtest/` | Kiểm nhanh bất biến, kiểm tín hiệu, đo tốc độ engine |
| `backend.core.analytics.make_mock_feeds` | `core/analytics/` | Feed giả lập Live/Testnet cho trang Danh mục |
| `backend.core.data.promote_staging` | `core/data/` | Đưa dữ liệu đã kiểm từ staging vào kho |
| `backend.core.research.research_*` | `core/research/` | Nghiên cứu (bot top OKX, maker scalp, trend danh mục) |

Luôn chạy qua `backend/utils/ops/run_limited.sh -- -m <lệnh> …` từ thư mục `nora/`.
Bấm "Chạy" trên UI = API tạo **job** gọi đúng lệnh trên trong tiến trình riêng (`backend/api/jobs/batch.py`, danh sách trắng `KINDS`).


Chạy mọi thứ từ thư mục `nora/` qua `backend/utils/ops/run_limited.sh -- -m backend.<gói>.<lệnh> ...` (PYTHONPATH=nora, cwd=nora); import theo dạng `backend.core.backtest.portfolio`, `backend.api.jobs.batch`, ...

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
- **Chạy job nặng:** luôn qua `backend/utils/ops/run_limited.sh` (nora.slice 12G, hàng đợi); chi tiết ở `bmad/architecture.md` mục 12.
- **Khi xong một story:** cập nhật file story (trạng thái, task, Evidence, Change Log), `bmad/sprint-status.yaml`, `bmad/epics.md`, rồi chạy kiểm tra nhất quán trong `bmad/README.md`.
- **Khi chủ sở hữu đưa ra góp ý hoặc luật mới:** bổ sung vào `knowledge_base/02_boss_mandates_and_rulebase.md`.
- **Không nới gate** để có kết quả đẹp; không có kết quả đạt thì ghi nhận trung thực.
