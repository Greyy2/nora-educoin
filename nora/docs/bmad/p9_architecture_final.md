# P9 — kiến trúc cuối (bàn giao cho phiên LOGIC)

Trạng thái sau lượt ARCHITECTURE cuối của P9 (ADR: `adr-p9-backend-layout.md`). Chỉ di chuyển/đổi đường dẫn; logic không đổi. Không commit trong lượt này.

## 1. Cây backend cuối (một dòng trách nhiệm/file, lấy từ docstring đầu file)

`backend/main.py` là app FastAPI. Script vận hành ở `nora/ops/` (ngoài backend; `backend/utils/` đã xoá). Các `__init__.py` rỗng/gói bỏ qua.

- `alpha/compile.py` — Bộ chuyển đổi alpha -> IR (P9 alpha): biên dịch DSL Python (compile_program/compile_code/explain_*), module chiến lược hệ thống (compile_strategy_module), hàm dựng cây (f, cond, lagged, cross_over, cross_under, calc, tree_p), nạp file data/alpha/strategies (load_system_strategies, strategies_dir, strategy_files; cache theo mtime+size). P10: + bộ chuyển đổi đầu vào (registry style detector -> adapter; RUN native | ADAPT function/json_spec/ai_python | REJECT), sửa chiến lược hệ thống tại chỗ (đọc/ghi có khoá sha256, kiểm hợp đồng, sao lưu, ghi nguyên tử, nạp lại; StrategyEditError) — gộp từ alpha/adapters.py + optimize/book/strategy_files.py.
- `alpha/contract.py` — Strategy Contract (P9 alpha): giới hạn (MAX_CODE_CHARS, MAX_NODES, BASE_CLASS), at/suggest, _position_attr_names. `DslError` ở core/signal (Program ném nó); validate_alpha còn ở optimize/search/generate.py (cần optimize). P10: + catalog primitive (một nguồn cho kiểm hợp đồng và gợi ý code), check_contract, trợ lý viết code tất định complete/hover (không AI) — gộp từ alpha/assist.py.
- `carlo/carlo.py` — Monte Carlo: bootstrap theo khối + kịch bản cực xấu + gate (mọi cổng alpha/sổ đều đọc hằng số ở đây).
- `core/backtest.py` — Engine duy nhất (P9.4): kernel numba (cache=True), BacktestEngine, PortfolioEngine, tài sản DEX.
- `core/indicator.py` — Chỉ báo (P9.4 part 2): kernel numba causal + đặc tả chữ ký DSL (spec) + feature `self.feat.*` + operator `self.op.*`.
- `core/models.py` — Mô hình + sự kiện + kế toán của engine (P9.4): lệnh/vị thế (OrderModel, PositionModel), sự kiện (Fill, FundingApplied, ...), Account/PositionBook, CapitalLedger.
- `core/params.py` — Tham số chiến lược (P9.4): schema (StrategyParams), template (placeholder/sig.*), builder (build_params), materialize + BASE_POSITION của sổ.
- `core/position_size.py` — Chính sách vị thế + khối lượng + kiểm rủi ro (P9.4): hàm THUẦN số học cho mọi mức giá / khối lượng / admit_entry.
- `core/signal.py` — Bộ dịch tín hiệu (P9.4 part 2): IR của DSL (DslError, Node…Program, code_hash) —(trình biên dịch/explain đã sang alpha/compile.py)— + bộ thông dịch AST (evaluator) + ảnh chụp tín hiệu (snapshot)
- `crawl/cex.py` — Nến + funding CEX (Binance data.binance.vision/REST và OKX CDN/REST) -> 1m.pkl + khung resample + manifest.
- `crawl/dex.py` — Tick swap on-chain + lưu tick/nến local DEX.
- `crawl/store.py` — Kho dữ liệu thị trường: layout thư mục (một nơi chọn gốc dữ liệu), đọc/ghi pkl, loader nến, resample, quality gate, promote, LRU, json an toàn.
- `live/live.py` — Bot giao dịch theo sổ đã xuất bản (E9) — job API `live_bot`: bộ chạy THỜI GIAN THỰC dùng chung cho mọi môi trường. Sàn triển khai: OKX (Binance chỉ tham khảo).
- `live/paper.py` — Hồ sơ môi trường PAPER (mode "paper"): chỉ dữ liệu thị trường CÔNG KHAI của sàn (không khoá, không đặt lệnh); khớp lệnh mô phỏng bằng KernelPaperBook (core/backtest.py).
- `live/testnet.py` — Hồ sơ môi trường TESTNET (mode "demo"): OKX Demo Trading (khoá demo bắt buộc, từ chối khoá thật) và Binance testnet (khoá bắt buộc). Vốn ảo, lệnh THẬT trên sàn thử nghiệm.
- `main.py` — Nora API: app FastAPI duy nhất (uvicorn backend.main:app).
- `metrics/charts.py` — Chuỗi cho biểu đồ (P9.5): payload trang Danh mục (dashboard), giải thích tín hiệu một chiến lược trên một mã (signal_explain),
- `metrics/metrics.py` — Bộ chỉ số Nora (P9.5): số đo trên chuỗi lợi suất NGÀY (returns) + bộ số đo chuẩn của MỘT lần chạy (portfolio), một công thức chuẩn, năm = 365 ngày.
- `metrics/trades.py` — Số đo theo LỆNH (đã đóng) và theo phơi nhiễm vốn: bảng lệnh phẳng, thắng/thua, profit factor, payoff, expectancy, chuỗi thua,
- `optimize/book/build.py` — Dựng sổ + presets (P9.6): nhóm kiểm tham số/khung dùng cho engine và phễu (từ core/params/modes), dựng sổ chiến lược (optimize/book), presets (core/params/presets).
- `optimize/book/registry.py` — Kho alpha + sổ (P9.6): phiên bản engine (engine_version), registry/sổ chính/sổ thử nghiệm/xuất bản (registry), kiểm lại alpha (revalidate), alpha người dùng (user_alphas), tài liệu chiến lược (strategy_doc), Top Agents (đọc file n
- `optimize/funnel/stages.py` — Phễu alpha S0 -> FINAL (P9.6): ngưỡng cổng (gates), tìm hệ số khối lượng (sizing), thống kê, ước lượng, bộ điều phối các tầng (orchestrator), promote, xuất bản sổ (publish), tính lại (recompute) và job chạy phễu (run).
- `optimize/funnel/storage.py` — Kho kết quả (P9.6): kho một lần chạy phễu (RunStore: SQLite + parquet) + kho kết quả dùng chung dựng sổ/WFA/phễu (ResultsStore, job_key, code_version).
- `optimize/process/process.py` — Hàng đợi / chạy / huỷ / khôi phục job nền (P9.6 + P9.8): tiện ích job (Progress, graceful_sigterm, ghi result.json — từ utils/jobs.py) và phần tiến trình của api/jobs/batch.py (KINDS, launch, status, huỷ, lưu kết quả lâu dài, dọn)
- `optimize/process/tasks.py` — Các job (P9.6): backtest sổ (run_book_backtest), WFA (run_book_wfa), báo cáo regime (run_regime_report), backtest tạm của người dùng (run_custom_backtest), dựng mẫu Education (run_edu_precompute) + mặc định dùng chung (run_default
- `optimize/process/workers.py` — Đa tiến trình + RAM (P9.6): giám sát/giới hạn RAM (memwatch) và pool worker an toàn (parallel).
- `optimize/search/evaluate.py` — Chạy hàng loạt (P9.6): thư viện backtest danh mục (BacktestJob, make_engine, run, result_payload), phía WORKER của phễu (w_*) và kho dữ liệu dùng chung (SharedExporter).
- `optimize/search/generate.py` — Sinh alpha (P9.6): lưới/mẫu tham số, id alpha, biến thể regime, kiểm S0. Nguồn: docs/bmad/p9_review_log.md (mục P9.6).
- `regime/regime.py` — Regime thị trường (P9.5): nhận diện trạng thái theo phút, causal (classifier) + học bảng regime ↔ chiến lược từ dữ liệu TRAIN (learn).
- `routes/alphas.py` — Thư viện chiến lược (/api/studio/alphas): mỗi chiến lược = ý tưởng + công thức bằng lời + công thức toán (ký hiệu) + thống kê alpha đã đạt, theo NGUỒN.
- `routes/book.py` — API sổ chiến lược (strategy book): xem sổ hiện tại + chạy backtest danh mục / WFA danh mục / dựng sổ như job nền.
- `routes/chart.py` — Biểu đồ tín hiệu (/api/studio/chart): nến + chỉ báo + điểm tín hiệu + từng điều kiện đúng/sai — để hiểu TẠI SAO một lệnh được vào.
- `routes/custom.py` — API backtest chiến lược Python tùy chỉnh (P7): POST /api/studio/custom/backtest -> job `custom_backtest` (optimize/process/tasks.run_custom_backtest); GET /api/studio/custom/defaults = rổ + cửa sổ mặc định từ kho dữ liệu.
- `routes/data.py` — Dữ liệu thị trường (/api/data): tải nến OKX (sàn triển khai, mặc định) / Binance (tham khảo) và đưa dữ liệu đã qua quality gate từ staging vào kho — đều là job nền.
- `routes/education.py` — API Education (B7): kết quả backtest tính trước cho 50 mẫu chiến lược giáo dục (job edu_precompute -> crawl/store.education_results_dir()).
- `routes/funnel.py` — API phễu kiểm duyệt alpha (/api/studio/funnel): tạo lượt chạy (job nền qua run_limited), liệt kê, thống kê từng tầng, bảng alpha, chi tiết alpha,
- `routes/jobs.py` — Kiểm tham số job (P9.8): ngày, tài sản, số, thư mục báo cáo, chiến lược WFA, dựng params cho book_backtest/book_wfa/book_build/custom_backtest/edu_precompute, http_launch.
- `routes/live.py` — Bot giao dịch theo sổ (/api/studio/live): khởi chạy job nền `live_bot` (OKX: paper | demo | live) và xem trạng thái (state.json + sự kiện).
- `routes/market.py` — Tín hiệu thị trường (/api/studio/market): trạng thái tín hiệu từng chiến lược × tài sản tại nến 1m ĐÃ ĐÓNG mới nhất của dữ liệu
- `routes/modes.py` — Chế độ chạy Cơ bản / Nâng cao (P9.8): hằng số + gộp tham số job (core/params/modes, phần chỉ-API) và lớp API (api/modes.py): preset, kiểm params_schema, nhãn custom_gates/promotable.
- `routes/portfolio.py` — API trang Danh mục (docs/ui_contract.md §3): GET /api/studio/portfolio/dashboard và /trades.
- `routes/strategies.py` — API chiến lược lõi + lược đồ tham số + bộ tham số tốt nhất (preset) cho chế độ Cơ bản / Nâng cao (docs/ui_contract.md §"Chế độ chạy").
- `wfa/wfa.py` — Walk-Forward Analysis cho SỔ CHIẾN LƯỢC (danh mục nhiều tài sản, MỘT sổ vốn) + Monte Carlo trên lợi suất ngày MTM.

So với cây đích ADR §2: không thừa, không thiếu file. (`routes/*.py` = alphas, book, chart, custom, data, education, funnel, jobs, live, market, modes, portfolio, strategies.)

## 2. Bản đồ module cũ -> mới

### 2.1 Module cũ bị xoá/gộp (nguồn: `old_modules_p910a.txt`, ADR §3)

```
# P9.10a removed module paths -> new target (for live/state_migrate OLD_MODULES; renames noted)
backend.core.signals.evaluator            -> backend.core.signal
backend.core.signals.snapshot             -> backend.core.signal
backend.core.signals.diagnostics          -> backend.core.signal
backend.core.signals.kernels              -> backend.core.indicator
backend.core.strategy.pydsl               -> backend.core.signal
backend.core.strategy.pydsl.parser        -> backend.core.signal
backend.core.strategy.pydsl.program       -> backend.core.signal
backend.core.strategy.pydsl.errors        -> backend.core.signal
backend.core.strategy.pydsl.explain       -> backend.core.signal
backend.core.strategy.pydsl.spec          -> backend.core.indicator
backend.core.strategy.pydsl.features      -> backend.core.indicator
backend.core.strategy.pydsl.ops           -> backend.core.indicator
backend.core.strategy.pydsl.profiles      -> backend.core.backtest (build_plan, Plan, ...); constants -> backend.core.params
backend.core.metrics.returns              -> backend.metrics.metrics
backend.core.metrics.portfolio            -> backend.metrics.metrics
backend.core.metrics.trades               -> backend.metrics.trades
backend.core.metrics.diagnose             -> backend.metrics.trades
backend.core.metrics.series_stages        -> backend.metrics.charts
backend.core.metrics.diagnose_inputs      -> backend.metrics.trades (market_series); rest -> backend.optimize.process.tasks
backend.core.analytics.dashboard          -> backend.metrics.charts
backend.core.analytics.signal_explain     -> backend.metrics.charts
backend.core.analytics.feeds              -> backend.metrics.charts
backend.core.analytics.insights           -> backend.metrics.charts
backend.core.analytics.user_alphas        -> backend.optimize.book.registry
backend.core.analytics.strategy_doc       -> backend.optimize.book.registry
backend.core.analytics.top_agents         -> backend.optimize.book.registry
backend.optimize.registry                 -> backend.optimize.book.registry
backend.utils.engine_version              -> backend.optimize.book.registry
backend.optimize.funnel.antiluck          -> backend.carlo.carlo (DSR, effective_trials); backend.wfa.wfa (pbo_cscv, align_daily, neighbours)
backend.verdict.verdict                   -> same split as antiluck; diagnostics -> backend.metrics.trades; insights -> backend.metrics.charts
backend.core.regime.classifier            -> backend.regime.regime
backend.core.regime.learn                 -> backend.regime.regime
backend.core.regime.report                -> backend.optimize.process.tasks (run_job -> run_regime_report)
backend.core.data.loader                  -> backend.crawl.store
backend.core.data.resampler               -> backend.crawl.store
backend.core.data.quality_gate            -> backend.crawl.store
backend.core.data.promote                 -> backend.crawl.store
backend.core.data.shared                  -> backend.crawl.store
backend.db.data_layout                    -> backend.crawl.store
backend.db.local_pkl                      -> backend.crawl.store
backend.utils.lru                         -> backend.crawl.store
backend.utils.jsonsafe                    -> backend.crawl.store
backend.core.data.crawler                 -> backend.crawl.cex
backend.core.data.okx_crawler             -> backend.crawl.cex (crawl->okx_crawl, crawl_funding->okx_crawl_funding, run_job->okx_run_job, DEFAULT_CACHE_DIR->OKX_DEFAULT_CACHE_DIR)
backend.core.data.tick_crawler            -> backend.crawl.dex
backend.db.tick_storage                   -> backend.crawl.dex
backend.api.routers.<name>                -> backend.routes.<name>
backend.api.modes                         -> backend.routes.modes
backend.api.jobs.batch                    -> backend.optimize.process.process + backend.routes.jobs
backend.api.jobs.runner                   -> backend.optimize.process.process
backend.utils.jobs                        -> backend.optimize.process.process
backend.utils.memwatch                    -> backend.optimize.process.workers
backend.utils.parallel                    -> backend.optimize.process.workers
backend.optimize.shared                   -> backend.optimize.search.evaluate
backend.optimize.funnel.evaluate          -> backend.optimize.search.evaluate (make_engine -> make_engine_from_dict)
backend.optimize.funnel.generate          -> backend.optimize.search.generate
backend.optimize.funnel.gates             -> backend.optimize.funnel.stages
backend.optimize.funnel.sizing            -> backend.optimize.funnel.stages
backend.optimize.funnel.stats             -> backend.optimize.funnel.stages
backend.optimize.funnel.estimate          -> backend.optimize.funnel.stages
backend.optimize.funnel.orchestrator      -> backend.optimize.funnel.stages
backend.optimize.funnel.promote           -> backend.optimize.funnel.stages
backend.optimize.funnel.publish           -> backend.optimize.funnel.stages (*_DEFAULTS, run_funnel_*)
backend.optimize.funnel.recompute         -> backend.optimize.funnel.stages
backend.optimize.funnel.run               -> backend.optimize.funnel.stages
backend.optimize.store                    -> backend.optimize.funnel.storage (_SCHEMA->_RESULTS_SCHEMA, _dumps->_results_dumps)
backend.optimize.revalidate               -> backend.optimize.book.registry (run_job->run_alpha_revalidate, DEFAULTS->ALPHA_REVALIDATE_DEFAULTS, wfa->wfa_check)
backend.wfa.walk_forward                  -> backend.wfa.wfa
backend.wfa.run                           -> backend.optimize.process.tasks (run_book_wfa, BOOK_WFA_DEFAULTS)
backend.carlo.monte_carlo                 -> backend.carlo.carlo
```

### 2.2 Symbol cũ -> file mới (OLD_HOME của `test/scripts/p9_ledger.py`; gợi ý nơi chốn theo module cũ không .py)

| Module cũ (từ backend/) | File đích (gợi ý) |
|---|---|
| `api/jobs/batch` | `optimize/process/process.py`, `routes/jobs.py` |
| `api/jobs/runner` | `optimize/process/process.py` |
| `api/modes` | `routes/modes.py` |
| `api/routers/alphas` | `routes/alphas.py` |
| `api/routers/book` | `routes/book.py`, `optimize/book/build.py` |
| `api/routers/chart` | `routes/chart.py` |
| `api/routers/custom` | `routes/custom.py` |
| `api/routers/data` | `routes/data.py` |
| `api/routers/education` | `routes/education.py` |
| `api/routers/funnel` | `routes/funnel.py` |
| `api/routers/live` | `routes/live.py` |
| `api/routers/market` | `routes/market.py` |
| `api/routers/portfolio` | `routes/portfolio.py` |
| `api/routers/strategies` | `routes/strategies.py` |
| `carlo/monte_carlo` | `carlo/carlo.py` |
| `core/analytics/dashboard` | `metrics/charts.py` |
| `core/analytics/feeds` | `metrics/charts.py` |
| `core/analytics/insights` | `metrics/charts.py` |
| `core/analytics/signal_explain` | `metrics/charts.py` |
| `core/analytics/strategy_doc` | `optimize/book/registry.py` |
| `core/analytics/top_agents` | `optimize/book/registry.py` |
| `core/analytics/user_alphas` | `optimize/book/registry.py` |
| `core/backtest/custom_run` | `optimize/process/tasks.py` |
| `core/backtest/dex` | `crawl/store.py` |
| `core/backtest/edu_precompute` | `optimize/process/tasks.py` |
| `core/backtest/portfolio` | `core/backtest.py`, `crawl/store.py`, `optimize/search/evaluate.py` |
| `core/backtest/run` | `optimize/search/evaluate.py`, `optimize/process/tasks.py` |
| `core/backtest/run_defaults` | `optimize/process/tasks.py` |
| `core/backtest/tick_run` | `optimize/search/evaluate.py` |
| `core/data/crawler` | `crawl/cex.py` |
| `core/data/loader` | `crawl/store.py` |
| `core/data/okx_crawler` | `crawl/cex.py` |
| `core/data/promote` | `crawl/store.py` |
| `core/data/quality_gate` | `crawl/store.py` |
| `core/data/resampler` | `crawl/store.py` |
| `core/data/shared` | `optimize/search/evaluate.py` |
| `core/data/tick_crawler` | `crawl/dex.py` |
| `core/metrics/diagnose` | `metrics/trades.py` |
| `core/metrics/diagnose_inputs` | `metrics/trades.py`, `optimize/process/tasks.py` |
| `core/metrics/portfolio` | `metrics/metrics.py` |
| `core/metrics/returns` | `metrics/metrics.py` |
| `core/metrics/series_stages` | `metrics/charts.py` |
| `core/metrics/trades` | `metrics/trades.py` |
| `core/params/builder` | `core/params.py`, `crawl/store.py`, `optimize/search/evaluate.py` |
| `core/params/modes` | `routes/modes.py`, `optimize/book/build.py` |
| `core/params/presets` | `crawl/store.py` |
| `core/regime/classifier` | `core/signal.py`, `regime/regime.py` |
| `core/regime/learn` | `regime/regime.py` |
| `core/regime/report` | `optimize/process/tasks.py` |
| `core/signals/diagnostics` | `core/backtest.py`, `core/signal.py` |
| `core/signals/evaluator` | `core/signal.py` |
| `core/signals/kernels` | `core/indicator.py` |
| `core/signals/snapshot` | `core/backtest.py`, `core/signal.py`, `optimize/book/build.py` |
| `core/strategy/book` | `core/params.py`, `optimize/book/build.py`, `alpha/compile.py` |
| `core/strategy/library` | `core/params.py`, `optimize/book/build.py`, `alpha/compile.py` |
| `core/strategy/pydsl` | `core/signal.py`, `alpha/compile.py` |
| `core/strategy/pydsl/errors` | `core/signal.py`, `alpha/contract.py` |
| `core/strategy/pydsl/explain` | `alpha/compile.py` |
| `core/strategy/pydsl/features` | `core/indicator.py` |
| `core/strategy/pydsl/ops` | `core/indicator.py` |
| `core/strategy/pydsl/parser` | `alpha/compile.py`, `alpha/contract.py`, `core/signal.py` |
| `core/strategy/pydsl/profiles` | `core/params.py`, `core/backtest.py` |
| `core/strategy/pydsl/program` | `core/signal.py`, `alpha/compile.py` |
| `core/strategy/pydsl/spec` | `core/indicator.py` |
| `db/data_layout` | `crawl/store.py` |
| `db/local_pkl` | `crawl/store.py` |
| `db/tick_storage` | `crawl/dex.py` |
| `live/bot` | `live/live.py`, `core/backtest.py`, `crawl/store.py` |
| `live/compare` | `metrics/trades.py` |
| `live/exchange` | `live/live.py` |
| `live/okx` | `live/live.py` |
| `live/okx_venue` | `live/live.py` |
| `live/paper` | `core/backtest.py` |
| `live/secrets` | `live/live.py` |
| `live/signals` | `core/backtest.py` |
| `live/state_migrate` | `live/live.py` |
| `live/unified` | `live/live.py` |
| `optimize/book` | `optimize/book/build.py` |
| `optimize/funnel/antiluck` | `carlo/carlo.py`, `wfa/wfa.py` |
| `optimize/funnel/estimate` | `crawl/store.py` |
| `optimize/funnel/evaluate` | `optimize/search/evaluate.py` |
| `optimize/funnel/gates` | `optimize/funnel/stages.py` |
| `optimize/funnel/generate` | `optimize/search/generate.py` |
| `optimize/funnel/orchestrator` | `optimize/funnel/stages.py` |
| `optimize/funnel/promote` | `optimize/funnel/stages.py` |
| `optimize/funnel/publish` | `optimize/funnel/stages.py` |
| `optimize/funnel/recompute` | `optimize/funnel/stages.py` |
| `optimize/funnel/run` | `optimize/funnel/stages.py` |
| `optimize/funnel/sizing` | `optimize/funnel/stages.py` |
| `optimize/funnel/stats` | `optimize/funnel/stages.py` |
| `optimize/registry` | `optimize/book/registry.py` |
| `optimize/revalidate` | `optimize/book/registry.py` |
| `optimize/shared` | `optimize/search/evaluate.py` |
| `optimize/store` | `optimize/funnel/storage.py` |
| `utils/engine_version` | `optimize/book/registry.py` |
| `utils/jobs` | `optimize/process/process.py` |
| `utils/jsonsafe` | `crawl/store.py` |
| `utils/lru` | `crawl/store.py` |
| `utils/memwatch` | `optimize/process/workers.py` |
| `utils/parallel` | `optimize/process/workers.py` |
| `wfa/run` | `optimize/process/tasks.py` |
| `wfa/walk_forward` | `wfa/wfa.py`, `optimize/process/tasks.py` |

### 2.3 Symbol đổi tên (RENAMES của `p9_ledger.py`; `<module cũ>.<tên cũ>` -> tên mới)

| Symbol cũ | Tên mới |
|---|---|
| `api/jobs/runner.run` | `run_job_dir` |
| `api/routers/book._METRIC_KEYS` | `METRIC_KEYS` |
| `api/routers/funnel._Lru` | `LruCache` |
| `core/analytics/dashboard._date` | `iso_date` |
| `core/analytics/signal_explain._num` | `_sx_num` |
| `core/analytics/top_agents._FROZEN_PATH` | `_frozen_path` |
| `core/analytics/user_alphas._write_json` | `atomic_write_json` |
| `core/backtest/custom_run.DEFAULTS` | `CUSTOM_BACKTEST_DEFAULTS` |
| `core/backtest/custom_run.run_job` | `run_custom_backtest` |
| `core/backtest/dex._read_json` | `read_json` |
| `core/backtest/edu_precompute.DEFAULTS` | `EDU_PRECOMPUTE_DEFAULTS` |
| `core/backtest/edu_precompute._atomic_write` | `atomic_write_json` |
| `core/backtest/edu_precompute._json_default` | `json_default` |
| `core/backtest/edu_precompute.run_job` | `run_edu_precompute` |
| `core/backtest/engine.BASE_COLS` | `DATA_COLUMNS` |
| `core/backtest/kernel.pack_trackers` | `pack_slots` |
| `core/backtest/portfolio._DATA_CACHE` | `ENGINE_DATA` |
| `core/backtest/run.DEFAULTS` | `BOOK_BACKTEST_DEFAULTS` |
| `core/backtest/run.run_job` | `run_book_backtest` |
| `core/data/okx_crawler.DEFAULT_CACHE_DIR` | `OKX_DEFAULT_CACHE_DIR` |
| `core/data/okx_crawler.crawl` | `okx_crawl` |
| `core/data/okx_crawler.crawl_funding` | `okx_crawl_funding` |
| `core/data/okx_crawler.run_job` | `okx_run_job` |
| `core/execute/amm.BISECT_MAX_ITER` | `_AMM_BISECT` |
| `core/execute/amm.amount_out` | `amm_amount_out` |
| `core/execute/amm.price_impact` | `amm_price_impact` |
| `core/params/builder.pool_fee_rate` | `manifest_pool_fee` |
| `core/params/builder.venue_of_symbol` | `manifest_venue` |
| `core/params/presets._read_json` | `read_json` |
| `core/params/presets.run_job` | `run_presets_build` |
| `core/regime/classifier.MINUTE` | `MINUTE_MS` |
| `core/regime/report.DEFAULTS` | `REGIME_REPORT_DEFAULTS` |
| `core/regime/report.MINUTE` | `MINUTE_MS` |
| `core/regime/report.run_job` | `run_regime_report` |
| `core/signals/snapshot.MINUTE` | `MINUTE_MS` |
| `core/strategy/book._REGIME_NAMES` | `REGIME_NAMES` |
| `core/strategy/book._choice` | `schema_choice` |
| `core/strategy/book._exit_risk_schema` | `exit_risk_schema` |
| `core/strategy/book._flt` | `schema_flt` |
| `core/strategy/book._int` | `schema_int` |
| `core/strategy/library.p` | `tree_p` |
| `core/strategy/pydsl/features.evaluate` | `evaluate_feature` |
| `core/strategy/pydsl/program.TF_MS` | `FRAME_MS` |
| `live/bot.evaluate` | `evaluate_signals` |
| `live/bot.state_key` | `live_state_key` |
| `live/signals.evaluate` | `evaluate_signals` |
| `optimize/book.DEFAULTS` | `BOOK_BUILD_DEFAULTS` |
| `optimize/book.NORA_ROOT` | `NORA_DIR` |
| `optimize/book.run_job` | `run_book_build` |
| `optimize/funnel/estimate._read_json` | `read_json` |
| `optimize/funnel/evaluate.make_engine` | `make_engine_from_dict` |
| `optimize/funnel/gates.INITIAL_CAPITAL` | `DEFAULT_CAPITAL` |
| `optimize/funnel/promote._atomic_dump` | `atomic_write_json` |
| `optimize/funnel/publish.DEFAULTS` | `FUNNEL_BOOK_DEFAULTS` |
| `optimize/funnel/publish.run_job` | `run_funnel_book` |
| `optimize/funnel/recompute.run_job` | `run_funnel_recompute` |
| `optimize/funnel/run.DEFAULTS` | `FUNNEL_RUN_DEFAULTS` |
| `optimize/funnel/run.run_job` | `run_funnel_run` |
| `optimize/funnel/stats.DIST_KEYS` | `FLAT_KEYS` |
| `optimize/funnel/storage._SCHEMA` | `_RUN_SCHEMA` |
| `optimize/funnel/storage._dumps` | `_run_dumps` |
| `optimize/revalidate.DEFAULTS` | `ALPHA_REVALIDATE_DEFAULTS` |
| `optimize/revalidate.run_job` | `run_alpha_revalidate` |
| `optimize/revalidate.wfa` | `wfa_check` |
| `optimize/store._SCHEMA` | `_RESULTS_SCHEMA` |
| `optimize/store._dumps` | `_results_dumps` |
| `wfa/run.DEFAULTS` | `BOOK_WFA_DEFAULTS` |
| `wfa/run.run_job` | `run_book_wfa` |
| `wfa/walk_forward._date` | `iso_date` |
| `wfa/walk_forward.run_job` | `run_wfa_job` |

Bảng ánh xạ file theo ADR §3 nằm ở `adr-p9-backend-layout.md` §3 (nguồn chuẩn khi ledger không chắc).

## 3. Cây dữ liệu cuối (`nora/data/`) và vòng đời

| Đường dẫn | Chứa gì | Vòng đời |
|---|---|---|
| `market/<okx|binance>/{cex,dex}/<SYM>[/perp]` | nến 1m + resample, funding, ticks.parquet; metadata trong `df.attrs["nora"]` | lâu dài, không commit |
| `alpha/` | `book.json`, `registry.json`, `presets.json`, `strategies/`, `education/`, `explore/`, `testnet/`, `research/`, `universes/` (commit); `user/`, `funnel/<run>/`, `book/<run>/` (không commit) | lâu dài |
| `backtest/<id>/`, `backtest/education/` | kết quả backtest lâu dài; education sinh lại được | lâu dài |
| `wfa/<id>/`, `carlo/<id>/` | kết quả WFA / Monte Carlo (carlo tạo khi có lần chạy đầu) | lâu dài |
| `live/<venue>_<mode>[_explore][_unified]/` | trạng thái bot, sự kiện | lâu dài |
| `cache/process/<job_id>/` (+ `_mem/`, `_staging/`) | params, tiến độ, log, checkpoint, file tạm crawl, log RAM | TẠM: dọn ngay sau khi kết quả được lưu lâu dài; job lỗi/huỷ giữ log 7 ngày; chạy tạm của người dùng 24 h |
| `cache/shared/` (+ `quality_gate/`) | mmap chỉ báo dùng chung, cache quality gate | xoá được bất cứ lúc nào |

Đường dẫn chỉ do `backend/crawl/store.py` quyết định (`_kind_path` = bảng một đường/kind; `market_root`, `alpha_dir`, `run_dir`, `alpha_run_dir`, `live_dir`, `cache_dir`, `cache_process_dir`, `cache_runs_dir`, `cache_staging_dir`, `allowed_roots`, `is_within`). Không còn fallback đường cũ (`_cache/`, `alphas/`, `<home>/<sàn>`, `data_staging`). `LEGACY_CACHE_NAMES` giữ vì `cache_dir(None, "book"|...)` vẫn được gọi (tên -> kind). `layout_version()` đã xoá: lịch sử job luôn ẩn job `done` trong `cache/process` (đọc từ thư mục kết quả).

## 4. File đổi trong lượt này

- Task A: `backend/crawl/store.py` (bỏ `_pick`, `_migrated`, `layout_version`; `_kind_paths` -> `_kind_path`; `_under`, `market_root`, `alpha_education_samples`, `allowed_roots`, `cache_dir` chỉ cây mới; comment), `backend/optimize/process/process.py` (`_history_dirs`, `RUN_LIMITED`, comment), `backend/optimize/book/build.py` (`strategies_dir` chỉ `data/alpha/strategies`), comment đường dẫn ở `backend/routes/{jobs,modes,book,live,funnel,alphas,strategies}.py`, `backend/crawl/cex.py`, `backend/optimize/process/tasks.py`, `backend/optimize/search/evaluate.py`, `backend/optimize/funnel/{stages,storage}.py`, `backend/optimize/book/registry.py`, `backend/live/live.py` (chỉ chuỗi đường dẫn trong comment/docstring); test: `test/test_data_layout_helpers.py` (viết lại, chỉ cây mới), `test/test_data_paths_p93b.py`, `test/test_okx_data.py` và vài chuỗi đường dẫn ở `test/scripts/*`.
- Task B: `backend/utils/ops/` -> `ops/` (git mv), `ops/run_limited.sh` (NORA_DIR = cha của ops, log RAM `data/cache/process/_mem`), `ops/install_user_units.sh`, `ops/deploy_nginx.sh` (độ sâu), `backend/optimize/process/process.py` (RUN_LIMITED), `backend/optimize/process/workers.py`, `backend/routes/{book,funnel}.py`, `backend/optimize/book/build.py` (comment), `ops/{README.md,systemd,nginx}`, `test/test_ops_units.py` (OPS path; target set, legacy rỗng), `test/test_layering.py` (bỏ dòng `utils/ops`), `test/test_book_api.py`, `test/scripts/*`, `docs/**` (sed `backend/utils/ops` -> `ops`).
- Task C: `docs/bmad/adr-p9-backend-layout.md` §2/§3/§4 cập nhật trạng thái cuối.
- Phụ: `test/scripts/migrate_data_tree.py` (báo cáo ghi ở thư mục tạm `data/_migration_tmp_<pid>` rồi chuyển vào `cache/process/_migration` SAU bước process).
- Task D: tài liệu này.

Unit systemd đã cài (`~/.config/systemd/user/nora-api.service`, `nora.slice`) chỉ nhắc `backend/utils/ops/install_user_units.sh` trong DÒNG COMMENT; không có ExecStart nào trỏ vào đường cũ. Chạy lại `ops/install_user_units.sh` khi tiện để làm mới comment (không bắt buộc).

## 5. Checklist cho phiên LOGIC

1. Chạy `ops/run_limited.sh --no-lock -- test/scripts/p9_ledger.py --hide-identical --dups`: mọi CHANGED phải truy được nguồn, MISSING = 0, không còn định nghĩa trùng.
2. Phễu: bước `S2_antiluck` chưa gỡ — quyết định của người dùng: dồn vào S3 (wfa) / S4 (carlo). CHƯA LÀM.
3. `signal_snapshot` chưa gộp (fold) — còn mở.
4. `ENGINE_FILES` / hash `engine_version` / `code_version` đã đổi do dời file -> sổ (book) và run cũ cần dựng lại; khoá `--resume` cũ không còn khớp.
5. Hai bot paper kiểu cũ có khoảng hở ~11,5 giờ (dữ liệu trạng thái); kiểm tra trước khi chạy lại bot.
6. Bảng remap pickle trong `live/live.py` (`backend.utils.*`, `backend.core.*` cũ -> mới) phải đủ cho mọi pickle trạng thái bot cũ.
7. Kiểm tra test cũ có thể mồ côi/thay thế: `test/test_data_layout.py` (còn dùng tên `_meta`, `_cache/research` làm thư mục "không phải tài sản" — hợp lệ), `test/legacy_candidates.py`, `test/reference_engine.py` (oracle giữ lại).
8. Golden: `NORA_GOLDEN_DATA_ROOT=data/market/binance` pytest `test/test_golden_results.py` phải bit-identical; full suite một lần sau khi logic xong.
9. Đã xoá khỏi data: `_meta`, `cex_ref`/`binance_hist` (gộp vào `binance/cex`); xác nhận không code nào còn đọc.
10. `docs/bmad/*` còn nhắc cấu trúc rất cũ (`backend/utils/lru.py`, `backend/db/`) trong tài liệu lịch sử — không sửa, chỉ là lịch sử.


## Chốt kiến trúc (2026-10-08, phiên kiến trúc)
- Cây backend khớp ADR §2: alpha/ = compile + contract; optimize/book = build + registry; không file thừa/thiếu; 57 module import sạch; p9_ledger --dups: DUPS=0.
- Hằng đường dẫn: `NORA_DIR`, `DATA_DIR` định nghĩa DUY NHẤT ở core/models.py; crawl/store (NORA_ROOT, DATA_HOME), alpha/compile (NORA_DIR, _DATA_HOME), optimize/process/process (NORA_DIR) chỉ import. (core/models nằm trong ENGINE_FILES -> hash engine đổi thêm một lần.)
- Cây data: market/{okx/{cex,dex}, binance/cex}, alpha/, backtest/, wfa/, carlo/ (tạo khi cần), live/{paper,testnet,live} (live/ tạo khi cần), cache/{process,shared}; cache chỉ giữ tiến trình đang chạy/dở dang.
- Kiểm tra sau chốt: test_data_layout_helpers, test_ops_units, test_golden_results (data/market/binance), test_strategy_dsl_parity, test_layering — 53 passed.
