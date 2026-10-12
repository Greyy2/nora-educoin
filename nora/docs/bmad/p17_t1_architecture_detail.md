# P17 · T1 — Dứt kiến trúc backend + crawl → `data.py` (plan chi tiết)

**Chốt 2026-10-12 (anh):** luồng giữ lại = **Backtest → WFA → Monte Carlo**. GIỮ `wfa/`, `carlo/` (thư viện thuần). Xoá phần research còn lại: `optimize/funnel`, `optimize/search/generate`, kho mmap/run_many, registry promote/revalidate/top_agents + UI Funnel/Tune; logic cũ lưu trong git (tag `pre-p17-research`) + `test/backend-no/`. Metrics lấy từ **Nautilus PortfolioAnalyzer**. Cái gì Nautilus có thì dùng thẳng, không viết lại.

### Cây backend đích (cực gọn)
```
backend/
├── main.py
├── data.py            dữ liệu OKX → catalog (đọc/ghi/quality/EngineData)
├── strategies.py      kho chiến lược: hệ thống (BY_ID, validate_params, lift_frames, FieldError, catalog/doc) + user (save/list/version) + sample_cache
├── jobs/              runner.py · tasks.py (run_custom, book_backtest, book_wfa, book_mc, education_warm, data_update) · workers.py
├── routes/            alpha.py · process.py · data.py · live.py · engine.py
├── alpha/             compile.py · contract.py · plan.py
├── signal/            indicator.py · ta.py · nodes.py · compute.py
├── nautilus/          backtest.py · engine.py · strategy.py · portfolio.py · results.py · catalog.py · live.py · version.py
├── metrics/           report.py (payload UI: stats PortfolioAnalyzer + equity/trades/chart cần cho CustomResult)
├── wfa/               wfa.py (giữ nguyên)
├── carlo/             carlo.py (giữ nguyên)
└── models/            models.py · params.py · position_size.py · storage.py · meta.py
```
Mục tiêu: backend ≤ ~15k dòng (hiện 30k).


Người làm: anh. Opus: test cổng. Nhánh `fix/pipeline-audit`. Chạy Python: `ops/run_limited.sh --no-lock -- <args>` (từ `nora/`).
Nguyên tắc: không đổi kết quả. Mỗi bước có lệnh kiểm; bước xong mới sang bước sau; commit mỗi bước.

Lệnh kiểm dùng chung (gọi tắt **[SNAP]**, **[QUICK]**):
```
[SNAP]  ops/run_limited.sh --no-lock -- test/scripts/p16_engine_snapshot.py --check test/fixtures/p16_engine_snapshot.json   # phải IDENTICAL
[QUICK] ops/run_limited.sh --no-lock -- -m pytest -q test/test_nautilus_engine.py test/test_nautilus_native.py test/test_custom_backtest.py \
        test/test_meta.py test/test_no_mock.py test/test_education_cache.py test/test_layering.py
```

---

## Bước 0 — Chốt baseline (10')
- [ ] Trước khi sửa: lưu chữ ký tín hiệu hiện tại (đọc pkl) để so sau D4:
      thêm `--signals` vào `test/scripts/p16_engine_snapshot.py`: với 10 symbol × khung {15m,1h,4h}, 2 mẫu education (KEMA + 1 DCA), hash `entries[*].match/stop/vol/dca` của `PortfolioEngine.load_data()`; lưu `test/fixtures/p17_signal_snapshot.json`.
- [ ] Danh sách test fail sẵn (baseline `dae2e71`): xem mục **Phụ lục A** — sửa ở Bước 6.

---

## Bước 1 — `models/storage.py` (D1, cơ học)
Tách khỏi `backend/crawl/store.py` mọi thứ KHÔNG phải dữ liệu thị trường:

| Nhóm | Hàm / hằng chuyển sang `models/storage.py` |
|---|---|
| Gốc dữ liệu | `NORA_DATA_ROOT`, `DATA_DIR`, `data_home`, `_flat`, `_kind_path`, `_under`, `LEGACY_CACHE_NAMES` |
| Alpha/run/live | `alpha_dir`, `alpha_file`, `alpha_user_dir`, `alpha_education_samples`, `alpha_run_dir`, `run_dir`, `LIVE_MODE_DIR`, `default_engine`, `live_state_key`, `live_dir` |
| Cache | `cache_process_dir`, `cache_quality_gate_dir`, `cache_runs_dir`, `cache_staging_dir`, `cache_dir`, `_ROOT_GROUPS`, `allowed_roots`, `is_within` |
| IO | `plain`, `write_json_atomic`, `write_pickle_atomic`, `write_parquet_atomic`, `json_default`, `read_json`, `write_job_result`, `options`, `as_list`, `env_mb`, `ByteLRU`, `iso_date`, `load_samples`, `load_report` |
| Hằng | `DEFAULT_CAPITAL`, `DEFAULT_TRAIN_RATIO` → `models/params.py` |

- [ ] Tạo file, chuyển nguyên văn (không sửa logic).
- [ ] Sửa import ở mọi nơi dùng các tên trên (danh sách: `grep -rlE "backend\.crawl" backend test`). `store.py` tạm `from backend.models.storage import *` để không gãy giữa chừng.
- **Kiểm**: `grep -rnE "from backend.crawl.store import .*(alpha_|run_dir|live_dir|read_json|json_default|ByteLRU|options|cache_)" backend test` = 0 · [QUICK] xanh.

## Bước 2 — `backend/data.py` phần ĐỌC (D2)
Một file, 5 mục; mỗi logic một định nghĩa:

1. **Universe/symbol**: `UNIVERSE` (10: BTC ETH SOL BNB XRP DOGE ADA AVAX LINK TRX), `normalize_symbol` (chuyển từ `nautilus/catalog.py`; catalog gọi lại data), `base_name`, `parse_symbol`, `split_instrument`, `clean_name`, `data_symbol`, `require_perp`, `classify_symbols`, `resolve_symbols`, `default_universe` (= UNIVERSE ∩ có catalog), `default_window`, `run_defaults`, `check_data`, `data_info`.
2. **Manifest/coverage**: `read_manifest` (đọc `catalog/_manifest/<SYM>.json`), `coverage()` (thay `list_assets` cho routes/data).
3. **Nến** — nguồn DUY NHẤT là catalog:
   - `read_1m(symbol, start, end)` (pyarrow; chuyển `read_catalog_1m` + `_decode_fixed` từ nautilus/catalog.py — chỉ dùng pyarrow, không import nautilus_trader).
   - `aggregate_frame` (chuyển từ catalog.py) → `exec_arrays(symbol, frame, start, end)`.
   - `load_candles(symbol, frame, start, end, columns)` = DataFrame cho tầng tín hiệu, **tái tạo đúng pkl cũ trong bộ nhớ**: 1m catalog → `fill_missing_1m_candles` (chuyển từ store.py, giữ cột `is_filled`) → `resample_from_1m` (chuyển từ store.py) cho khung >1m; cache bằng `ByteLRU` theo (symbol, frame, catalog_digest).
   - `daily_close`, `load_prices`, `benchmark_daily_closes`, `strategy_frames`, `catalog_digest`.
4. **Chất lượng**: `DataQualityStatus`, `evaluate_data_quality`, `require_data_ok`, `require_data_ok_or_exit`, `DataQualityError` — chuyển, đổi nguồn sang `read_1m` (giữ ngưỡng, giữ cache đĩa).
5. **DataSource**: chuyển `EngineData` + `make_engine_data` từ `optimize/search/evaluate.py:1228-1290` vào data.py; `candles()` → `load_candles`, `exec_arrays()` → `exec_arrays`, `funding()` → trả `None` (engine không mô phỏng funding). Phần kho mmap dùng chung (`shared_plan/load/fill`) giữ ở evaluate.py, EngineData gọi sang.
- [ ] `nautilus/catalog.py` chỉ còn: instrument (`build_instrument`, `get_instrument`, `instrument_spec`, `load_instruments_specs`), `get_bar_type`, `bars_from_arrays`, `load_catalog_bars`, ghi catalog (Bước 3). Đọc nến gọi `data.exec_arrays`.
- **Kiểm**:
  - `data.exec_arrays` bit-identical `catalog.exec_arrays` cũ (10 symbol × 1m/15m/1h, 2025-01..2025-03) — test `test/test_data.py::test_exec_arrays_identical`.
  - `data.load_candles` bit-identical pkl cũ (`pd.read_pickle(.../1m.pkl)` và `1h.pkl`) trên cùng khoảng: so `open_time, open, high, low, close, volume, is_filled` — `test_load_candles_matches_pkl`. Lệch → dừng, báo Opus (nghĩa là catalog ≠ nến thật trong pkl).
  - Quality gate cũ vs mới cùng verdict 10 symbol.
  - [SNAP] IDENTICAL.

## Bước 3 — `data.py` phần GHI + job (D3)
- [ ] `fetch_instruments()` (từ `test/scripts/fetch_instruments.py`) → `data/market/okx/instruments.json`.
- [ ] Crawl OKX 1m (chuyển từ `crawl/cex.py`: `inst`, `_day_tag`, `fetch_day_zip`, `parse_candles_csv`, `_okx_get`, `fetch_rest_candles`, `_hk_days`, `_hk_day_range`, `crawl_candles`, `_gaps`, hằng CDN/REST/HK_OFFSET_MS/COLS). **Không** chuyển funding, Binance.
- [ ] `update_catalog(symbol, end=None)`: mốc cuối từ manifest → crawl phần sau → bỏ nến trùng/không hợp lệ → `nautilus.catalog.write_bars(symbol, df)` (thêm hàm này: `df_1m_to_nautilus_bars` + `ParquetDataCatalog.write_data`, thay `write_catalog_bars` mà `build_catalog.py` gọi nhưng không tồn tại) → cập nhật manifest {start_ts, end_ts, rows, digest}.
- [ ] `run_job(params)` = `update_catalog` cho list symbol. `optimize/process/process.py` KINDS: thêm `data_update` (module `backend.data`), xoá `data_crawl`, `data_crawl_okx`, `data_crawl_ticks`, `data_promote`; `routes/data.py` gọi `data_update`; endpoint tick vẫn 501 (không import dex).
- [ ] `test/scripts/build_catalog.py` → gọi `data.update_catalog` (hoặc xoá nếu thừa).
- **Kiểm**: `test_data.py` dùng zip/REST ghi sẵn (fixture, **không mạng**): crawl 2 ngày → catalog tmp + manifest đúng; chạy lại → digest không đổi; nến trùng không ghi đôi.

## Bước 4 — Cắt pkl (D4) + archive (D5, D6)
- [ ] Đổi sang `data.*`: `routes/alpha.py:493-530` (chart đọc pkl) → `data.load_candles`; `routes/data.py:89` → `data.coverage`; `optimize/funnel/storage.py:595` (hash 1m.pkl) → `catalog_digest`; `optimize/search/evaluate.py:968,1122,1252` (fp funding.pkl, 1m.pkl) → digest catalog, bỏ funding; `models/models.py:491`, `alpha/dsl/strategy.py:713` (`_load_funding`) → bỏ funding (trả None).
- [ ] Xoá khỏi backend: `exchange()`, `EXCHANGES`, `exchange_root`, `exchange_of`, `market_dir` theo venue dex, `has_ticks`, `ticks_to_bars`, `save_resampled_dataset`, `generate_manifest` (cũ), staging/promote, `is_dex_symbol` (thay: symbol không thuộc UNIVERSE → lỗi rõ / 501).
- [ ] D5: `git mv backend/crawl test/backend-no/crawl`; test chỉ dành crawl cũ (`test_crawler_and_gate`, `test_okx_data`, `test_pkl_meta`, `test_ticks`, `test_data_layout*`, `test_data_paths_p93b`, `test_resampler_idempotent`, `test_data_quality_gate`) → hoặc viết lại trên `data.py`, hoặc chuyển `test/backend-no/tests/` (ghi lý do đầu file).
- [ ] D6: `mv data/market/okx/cex data/archive/2026-10-p16/okx_cex_pkl` (sau khi mọi kiểm xanh).
- **Kiểm**: `grep -rn "backend.crawl\|read_pickle\|\.pkl\b" backend` = 0 · `p16_engine_snapshot.py --signals --check test/fixtures/p17_signal_snapshot.json` IDENTICAL · [SNAP] · [QUICK].

## Bước 5 — Cây package đích + routes mỏng
**5a. Di chuyển** (git mv + sửa import; không sửa logic):
| Từ | Sang |
|---|---|
| `optimize/process/{process,tasks,workers,sample_cache}.py` | `jobs/{runner,tasks,workers,sample_cache}.py` — sửa `ops/run_limited.sh`, `ops/README.md`, systemd unit, chuỗi `-m backend.optimize.process.process` trong routes/process.py |
| `alpha/dsl/indicator.py`, `ta.py` | `signal/indicator.py`, `signal/ta.py` |
| `alpha/dsl/signal.py` | `signal/nodes.py` |
| `alpha/dsl/strategy.py` | tách: `alpha/plan.py` (Plan, build_plan, _ref, _tree, _leg_signals, leg_level, _check_position, RiskConfig, aggregate_positions, display_name, require_long_legs) + `signal/compute.py` (SignalEngine, SignalPortfolio, matrix_evaluator, entry_event_mask, frame_*, slot_*, _regime_labels/_regime_gate, evaluate_signals, signal_snapshot, check_signals, collect_field_refs, needs_minute_path, data_cache_clear) |
| code chết trong `alpha/dsl/strategy.py` | xoá: `OrderKind`, `Order`, `VenueCaps`, `Venue`, `new_order_id`, `check_amm_pool`, `tick_window`, `klines_frame` (grep xác nhận không ai dùng) |
| `metrics/regime.py` | bỏ `import backend.nautilus`: `series()` nhận nến từ `data.load_candles` |

**5b. Routes mỏng**:
- `routes/optimize.py:461 post_mc` (gate MC + custom gate) → `carlo/carlo.py` hàm `mc_report(req)`; route chỉ validate + gọi.
- `routes/optimize.py:1145 _nav` → `metrics/metrics.py nav_series`.
- `routes/process.py:851 _build_meta` → `models/meta.py build_meta()`; thêm `engine.default_exec_mode="fast"`, `frames.defaults={"custom_backtest":..., "funnel":"1h"}`.
- `routes/optimize.py:51 BacktestRequest` thêm `run_frame: Optional[str]` (validate theo meta) → truyền xuống job.
**Kiểm**:
- `grep -rln "nautilus_trader" backend | grep -v backend/nautilus/` = 0 (chú ý `main.py`, `routes/process.py`, `alpha/compile.py` đang import → chuyển qua `backend.nautilus.version`/hàm bọc).
- `grep -rn "backend.optimize.process\|backend.alpha.dsl" backend test ops` = 0.
- `test_layering.py` cập nhật luật import: `routes→jobs→{wfa,nautilus}→{alpha,signal}→models`; `strategies, data` → models; `metrics, carlo` không import nautilus/signal.
- [SNAP] · [QUICK] · `p9_ledger.py --dups` sạch.

**5c. Xoá research (giữ Backtest → WFA → MC)** — trước khi xoá: `git tag pre-p17-research`.
| Xoá | Giữ lại (chuyển chỗ) |
|---|---|
| — | `backend/wfa/`, `backend/carlo/` GIỮ NGUYÊN |
| `optimize/funnel/*`, `optimize/search/generate.py` | `split_regime` (nếu alpha/compile còn cần) → `alpha/plan.py` |
| `optimize/search/evaluate.py` (kho mmap dùng chung, run_many, funnel cache) | `execute`, `run_benchmark`, `WARMUP` → `jobs/tasks.py` hoặc `nautilus/engine.py`; `EngineData` → `data.py` (Bước 2) |
| `optimize/book/build.py` phần publish/explore/testnet_config | `BY_ID`, `UNIVERSE`, `perp_symbols`, `lift_frames`, `validate_params`, `FieldError` → `strategies.py`; luồng sổ backtest/WFA/MC (build_book giai đoạn backtest, gọi wfa/carlo) → `jobs/tasks.py` (`run_book_backtest`, `run_book_wfa`, `run_book_mc`) |
| `optimize/book/registry.py` (registry, promote, revalidate, build_report, top_agents, testnet) | user alpha (`save_user_alpha`, `list_user_alphas`, `get_user_alpha`, `*_version*`, `update_user_alpha_status`, `generate_alpha_id`, `evaluate_checklist`) + tài liệu catalog (`catalog`, `leg_doc`, `summarize`, `conditions`, `_exits`, `_sizing`…) → `strategies.py` |
| `PortfolioEngine.run_many`, `_load_shared`, shared_dir/mmap trong `nautilus/engine.py` | `PortfolioEngine.run` |
| routes: endpoint funnel/tune/registry/promote/revalidate/presets/top_agents trong `routes/optimize.py`, `routes/process.py`, `routes/data.py` | endpoint book backtest/WFA/MC (`routes/optimize.py` chỉ còn phần này, đổi tên `routes/book.py`), custom backtest, compile, user alpha, education, meta, jobs, data, live(501), engine |
| job kinds: funnel_*, revalidate*, publish/explore, live_bot… | `custom_backtest`, `book_backtest`, `book_wfa`, `book_mc`, `education_warm`, `data_update` |
| test: funnel/registry/revalidate/top_agents/shared_data/run_many/kernel… → `test/backend-no/tests/` | test custom/compile/nautilus/meta/no_mock/education/user_alphas/data + book/wfa/mc (`test_portfolio_wfa`, `test_book_mc_api`, `test_daily_mc`, `test_run_book_backtest`) |
| **Frontend**: pages `Funnel`, `Tune`, `components/optimize/funnel/*`, `lib/funnel.js`, hàm api tương ứng | Studio, AlphaCatalog, Backtest (backtest → WFA → MC, `McResult`, `WfaResult`), Portfolio, History, Live, Education |

**5d. Metrics = Nautilus PortfolioAnalyzer**
- `nautilus/backtest.py`: bật `run_analysis=True`; sau run lấy `eng.portfolio.analyzer` → `get_performance_stats_pnls()`, `get_performance_stats_returns()`, `get_performance_stats_general()` (Sharpe, Sortino, Profit Factor, Win Rate, Expectancy, Avg Winner/Loser, Returns Volatility…) → đưa vào `results["stats"]` (giữ nguyên tên Nautilus).
- `metrics/report.py` (thay `metrics/{metrics,trades,charts,regime}.py`): ghép payload UI = stats Nautilus (ánh xạ sang khoá UI `sharpe, sortino, pf, win, trades, fees`) + chỉ tính phần Nautilus KHÔNG có, mỗi cái một hàm: `mdd_pct`, `cagr`, `calmar` từ equity curve; equity/drawdown series, trades list, by_symbol, yearly. Bỏ: diagnostics/insights/regime/compare/exposure/correlation… nếu `CustomResult.jsx` không hiển thị (grep frontend trước khi xoá).
- train/test/simulate: mỗi giai đoạn một lần chạy (đã có) → stats Nautilus từng lần.
- **Kiểm**: 3 mẫu (KEMA, DCA, 1 native) — bảng so sánh chỉ số cũ (Nora) vs mới (Nautilus) lưu `test/fixtures/p17_metrics_compare.json`; khác biệt phải giải thích được bằng định nghĩa (ví dụ Sharpe năm hoá 252 vs 365); UI CustomResult hiển thị đủ.

## Bước 6 — Suite xanh + restart
- [ ] Sửa từng test trong Phụ lục A (test cũ sai theo code mới → sửa test, ghi lý do; bug thật → sửa code).
- [ ] Full suite: `ops/run_limited.sh -- -m pytest -q test` → 0 failed.
- [ ] Restart `nora-api` (`stop_nora.sh && start_nora.sh`), chạy `test/scripts/e2e_api.py` exit 0.
- [ ] Job `education_warm` chạy 1 lần (50 mẫu) → cache thật cho Education (T2/T3 cần).

## Cổng T1 (Opus chạy, tất cả phải đạt)
1. [SNAP] IDENTICAL + signal snapshot IDENTICAL.
2. Grep: `backend.crawl`, `read_pickle`, `.pkl`, `backend.optimize.process`, `backend.alpha.dsl` = 0; nautilus_trader chỉ trong `backend/nautilus/`.
3. Full suite 0 failed; `p9_ledger --dups` sạch; e2e exit 0.
4. Cây `backend/` đúng mục *Cây backend đích* ở đầu file; không còn `optimize/ crawl/`; `wfa/ carlo/` còn và test WFA/MC xanh; `vite build` sạch, UI không còn link tới trang đã xoá.
5. Backend ≤ ~15k dòng (`find backend -name '*.py' | xargs cat | wc -l`).

## Phụ lục A — test fail sẵn ở baseline `dae2e71`
Full suite tại `dae2e71`: **15 failed, 979 passed, 6 skipped** (54'51").
| Test | Ghi chú hướng xử lý |
|---|---|
| `test_alpha_contract.py::test_run_all_education_samples_identical_ir`, `test_adapt_function_style`, `test_adapt_json_spec[dict]`, `[text]`, `test_annotate_all_education_samples` | compile/contract sau refactor alpha/dsl — kiểm lỗi thật trước |
| `test_book_ui_backend.py::test_engine_version_is_stable_and_detects_engine_source_change`, `test_engine_hash_tracks_strategy_ir_not_comments` | danh sách file engine (registry `_engine_files`) còn trỏ path cũ — xử lý trong B5c (registry bỏ) |
| `test_edu_samples_lint.py::test_lint_risk_params_must_match` | mẫu education vs tham số rủi ro |
| `test_okx_data.py::test_exchange_root` | thuộc crawl cũ → B4/D5 |
| `test_ops_units.py::test_backend_has_only_planned_packages`, `test_resume_code_fingerprint_files_exist` | cập nhật theo cây đích ở B5 |
| `test_run_book_backtest.py::test_main_writes_result_json_with_expected_keys`, `test_deterministic`, `test_trade_list_has_notional_and_daily_nav` | luồng sổ backtest (giữ) — lỗi thật, sửa ở B5c khi chuyển vào jobs/tasks |
| `test_strategy_signal_parity.py::test_evaluate_signals_bit_identical_to_old` | so với engine cũ trong test/backend-no (mẫu mới không chạy trên code cũ) → chuyển test sang backend-no hoặc so với snapshot B0 |

