# P9 — nhật ký review chéo

## P9.0 + P9.2

Ngày: 2026-10-07 · Người làm: norabt-99 (kiến trúc, chỉ di chuyển) · Trạng thái: **CHƯA commit, chờ review chéo**.

### Task A — P9.0 test luật phụ thuộc (chế độ báo cáo)

- `nora/test/test_layering.py`: ast-parse mọi module `backend/` (gồm import cục bộ trong hàm), ánh xạ đường dẫn HIỆN TẠI -> tầng đích bằng bảng `LAYER_RULES` (ADR §3), kiểm luật ADR §2 (core chỉ import core; thứ tự models<params<indicator<signal<position_size<backtest; crawl chỉ được gọi từ optimize/live/routes; tầng giữa không import optimize/live/routes).
- Chế độ mặc định = BÁO CÁO: test xanh, ghi `docs/bmad/p9_layering_report.md` (tự sinh, xác định, không dấu thời gian). Bắt buộc ở P9.10: `NORA_LAYERING_STRICT=1`. `NORA_LAYERING_WRITE=0` tắt ghi file.
- Shim = file có `# P9-SHIM` trong 5 dòng đầu (bỏ qua khi làm bên import).
- Kết quả hiện tại: 145 module, 12 shim, 0 chưa ánh xạ, **62 vi phạm** (trước P9.2: 66). Giảm `crawl -> optimize` 7 -> 3 (còn `utils/jobs`, sẽ hết khi jobs chuyển sang optimize/process) — các vi phạm còn lại của `crawl -> core` là `core/data/shared.py` (phiên kia, chưa chuyển).
- Diễn giải cần OK của reviewer: tầng giữa {metrics, regime, wfa, carlo, verdict} được import lẫn nhau; crawl chỉ được import crawl; `core/data/promote` map vào crawl (theo chỉ đạo P9.2) dù ADR §3 xếp `optimize/process/tasks.py`.

### Task B — P9.2 `backend/crawl/` (chuyển nguyên văn)

Phương pháp: script tái tạo (nối nguyên văn thân module; chỉ gỡ import nội bộ nhóm/trỏ lại sang `backend.crawl.*`; docstring module -> comment banner). Kiểm AST từng hàm/lớp/hằng so với `git HEAD`: 140/155 định danh top-level giống hệt; 15 khác biệt đều giải thích bên dưới.

#### Bảng ánh xạ cũ -> mới (mọi hàm/lớp/hằng cấp module; `=` nghĩa là cùng tên, giống hệt AST)

**core/data/crawler.py** -> `crawl/cex.py`

`NORA_DIR *`, `VISION_BASE`, `REST_BASE`, `MARKETS`, `MINUTE_MS`, `DEFAULT_CACHE_DIR`, `KLINE_COLUMNS`, `log`, `ChecksumMismatch`, `normalize_ts_ms`, `parse_kline_csv`, `_http_get`, `fetch_vision_zip`, `fetch_rest_klines`, `_month_iter`, `parse_funding_csv`, `crawl_funding`, `crawl_symbol`, `crawl *`, `run_job`

**core/data/okx_crawler.py** -> `crawl/cex.py`

`NORA_DIR *`, `CDN`, `REST`, `MINUTE_MS *`, `HOUR_MS`, `DAY_MS`, `HK_OFFSET_MS`, `FUNDING_GAP_MS`, `DEFAULT_CACHE_DIR -> OKX_DEFAULT_CACHE_DIR *`, `COLS`, `inst`, `_day_tag`, `fetch_day_zip`, `parse_candles_csv`, `parse_swaprate_csv`, `_okx_get`, `fetch_rest_candles`, `_hk_days`, `_hk_day_range`, `crawl_candles`, `_gaps`, `crawl_funding -> okx_crawl_funding *`, `crawl -> okx_crawl *`, `run_job -> okx_run_job *`

**db/tick_storage.py** -> `crawl/dex.py`

`TICK_COLUMNS`, `REQUIRED_TICK_COLUMNS`, `DEFAULT_TICK_DAYS`, `MAX_TICK_DAYS`, `DAY_MS`, `PKL_COLUMNS`, `STANDARD_MINUTE_FRAMES`, `STANDARD_HOUR_FRAMES`, `symbol_dir`, `resolve_tick_file`, `_write_json_atomic`, `save_ticks`, `tick_coverage`, `load_ticks_df`, `load_candle_df`

**core/data/tick_crawler.py** -> `crawl/dex.py`

`MINUTE_MS`, `RPC_RETRIES`, `TS_SAMPLES`, `SWAP_V2_TOPICS`, `SWAP_V3_TOPIC`, `SYNC_TOPICS`, `USD_QUOTES`, `ETH_QUOTES`, `FEE_UNIT`, `clamp_days`, `network_config`, `_session`, `RpcRange`, `Rpc`, `eth_call`, `_block`, `block_at_or_after`, `_abi_str`, `_addr`, `read_pool_onchain`, `pool_onchain`, `_words`, `swap_flows`, `decode_swaps`, `reserve_price`, `attach_timestamps`, `reserve_deviation_bps`, `quote_to_usd`, `fetch_logs`, `eth_usd_candles`, `crawl_dex_ticks`, `dex_name`, `run_job`

**db/data_layout.py** -> `crawl/store.py`

`VENUES`, `INSTRUMENTS`, `_PREFIX_RE`, `_INSTRUMENT_RE`, `AmbiguousSymbolError`, `DATA_HOME`, `EXCHANGES`, `DEFAULT_EXCHANGE`, `exchange`, `exchange_root`, `default_data_root`, `exchange_of`, `cache_dir`, `clean_name`, `split_instrument`, `parse_symbol`, `is_asset_dir`, `list_assets`, `resolve_asset_dir`

**db/local_pkl.py** -> `crawl/store.py`

`BASE_COLUMNS`, `_COMPAT_COLUMNS`, `_frame_ms`, `_symbol_candidates`, `resolve_symbol_dir *`, `has_frame`, `read_manifest`, `has_ticks`, `list_asset_dirs`, `fetch_candles_df`

**utils/lru.py** -> `crawl/store.py`

`env_mb`, `ByteLRU`

**utils/jsonsafe.py** -> `crawl/store.py`

`json_default`

**core/data/loader.py** -> `crawl/store.py`

`_CANDLE_CACHE`, `_file_fingerprint`, `_index_by_open_time`, `CandleLoader`

**core/data/resampler.py** -> `crawl/store.py`

`PKL_COLUMNS`, `TIMEFRAME_MAP`, `_fill_missing_1m_candles_with_ratio`, `fill_missing_1m_candles`, `ticks_to_bars`, `ticks_to_1m`, `resample_from_1m`, `compute_df_sha256`, `generate_manifest`, `save_resampled_dataset`

**core/data/quality_gate.py** -> `crawl/store.py`

`MAX_FILLED_RATIO_1M`, `DataQualityStatus`, `_GATE_CACHE_MAX`, `_gate_cache_key *`, `_code_sig`, `_disk_cache_path *`, `_disk_get`, `_disk_put *`, `evaluate_data_quality`, `_evaluate_data_quality_uncached *`, `DataQualityError`, `require_data_ok`, `require_data_ok_or_exit`

**core/data/promote.py** -> `crawl/store.py`

`NORA_ROOT *`, `DEFAULTS`, `BLOCKING`, `run_job *`

`*` = khác AST so với bản gốc (xem mục sửa cơ học).

#### Sửa cơ học (không đổi hành vi) — danh sách đầy đủ

1. `NORA_DIR` (cex.py, 2 chỗ) và `NORA_ROOT` (store.py/promote): `..` x3 -> `..` x2 vì file nay ở `backend/crawl/` (nông hơn `backend/core/data/` một cấp) — cùng kết quả đường dẫn `nora/`. `DATA_HOME` (data_layout) giữ nguyên (db/ và crawl/ cùng độ sâu).
2. cex.py: tên trùng giữa Binance và OKX (OKX bị đổi tên): `crawl->okx_crawl`, `crawl_funding->okx_crawl_funding`, `run_job->okx_run_job`, `DEFAULT_CACHE_DIR->OKX_DEFAULT_CACHE_DIR`; trong `okx_crawl_funding`, nhánh proxy Binance (từng là import cục bộ `from crawler import DEFAULT_CACHE_DIR, crawl_funding as binance_funding_hist`) gọi thẳng `crawl_funding`/`DEFAULT_CACHE_DIR` của Binance cùng file. `NORA_DIR`/`MINUTE_MS` trùng giá trị, để nguyên cả hai.
3. Import cục bộ trong thân hàm trỏ sang module khác của nhóm: cùng file -> xoá (tên đã là global): `local_pkl.resolve_symbol_dir`, `quality_gate` (`cache_dir`, `json_default`, `compute_df_sha256`, `resample_from_1m`); khác file -> trỏ `backend.crawl.store` (cex: `exchange_root`, `DATA_HOME`).
4. Import có alias trong loader (`fetch_candles_df as fetch_local_candles_df`, `has_frame as has_local_frame`) -> hai dòng gán alias ở đầu section loader.
5. **Chu trình import store <-> dex**: `quality_gate` (store) dùng `symbol_dir/load_candle_df/load_ticks_df` của tick_storage (dex), mà dex nạp store ở đầu file -> 6 import CỤC BỘ (lazy) trong các hàm của quality_gate (comment `# lazy: dex <-> store`). Gợi ý cho ADR: về lâu dài tick_storage thuộc store (đọc/ghi) thì chu trình mất.
6. **Chu trình utils.jobs -> jsonsafe(shim) -> store -> utils.jobs**: import `options, write_job_result` của promote.run_job thành import cục bộ (lazy).
7. `quality_gate._code_sig()` băm `__file__`: nay là `crawl/store.py` (cả kho) -> chữ ký đổi một lần, cache gate TRÊN ĐĨA (`data/**/quality_gate/*.json`) tự hết hạn một lần rồi tính lại (~10 s/tài sản). Không ảnh hưởng kết quả. Khoá mmap dùng chung (`shared.py`, `_file_fingerprint` của loader) KHÔNG đổi.

#### Shim (tất cả có `# P9-SHIM`, gỡ ở P9.10)

Alias module (`sys.modules[__name__] = backend.crawl.<x>`): cùng MỘT đối tượng module -> cache (`_CANDLE_CACHE`, `_GATE_CACHE`), `DATA_HOME`, mọi tên riêng (`_frame_ms`, `_file_fingerprint`...) có sẵn; `monkeypatch.setattr` qua đường cũ có hiệu lực (test_custom_backtest, test_data_quality_gate cần điều này — `from x import *` sẽ phá vì mỗi bản copy tên một nơi).

- `core/data/crawler.py` -> cex · `core/data/tick_crawler.py` -> dex · `db/tick_storage.py` -> dex
- `db/data_layout.py`, `db/local_pkl.py`, `utils/lru.py`, `utils/jsonsafe.py`, `core/data/{loader,resampler,quality_gate,promote}.py` -> store
- `core/data/okx_crawler.py` -> VIEW module (lớp `ModuleType` dịch 4 tên đổi + chuyển tiếp đọc/ghi/xoá sang cex): `oc.run_job/crawl/crawl_funding/DEFAULT_CACHE_DIR` vẫn là bản OKX; `monkeypatch.setattr(oc, 'fetch_day_zip', ...)` ghi vào cex. Job `data_crawl*`/`data_promote` trong `batch.KINDS` giải đúng `run_job` qua đường cũ.
- Chưa chuyển (ngoài phạm vi): `core/data/shared.py` (phiên alpha đang sửa) — nó vẫn import `core.data.loader`, `db.*` qua shim, chạy bình thường.

#### File chạm/tạo

- Tạo: `backend/crawl/{__init__,cex,dex,store}.py`, `test/test_layering.py`, `docs/bmad/p9_layering_report.md`, mục này.
- Thay bằng shim (12): `backend/core/data/{crawler,okx_crawler,tick_crawler,loader,resampler,quality_gate,promote}.py`, `backend/db/{data_layout,local_pkl,tick_storage}.py`, `backend/utils/{lru,jsonsafe}.py`.
- KHÔNG đụng: `backend/api/*`, `main.py`, `core/signals/kernels.py`, `core/data/shared.py`, `core/analytics/*`, `core/metrics/*`, pydsl, `optimize/{registry,book}.py`, `carlo/*`, manifest dữ liệu. Không cần sửa file nào của phiên kia (danh sách cần sửa: không có).

#### Cổng test

Baseline (trước khi sửa, 14 file cổng, không có test_layering): **192 passed, 4 skipped** (13m23s).

Sau: test_layering + 14 file cổng: **194 passed, 4 skipped** (13m40s; +2 = test_layering). Không test nào đỏ trước hay sau.

Chạy thêm (gần phạm vi, không có baseline riêng nhưng toàn xanh): test_custom_backtest, memory_guards, round3_completion, daily_mc, optimization_plumbing, funnel, strategy_book, portfolio_sync_open, signals_strategies, run_book_backtest, research_topbots, diagnostics_real, xno_parity, signal_explain, pydsl_dsl, bot_unified, web_perf_cache, edu_precompute: **282 passed, 4 skipped, 1 xfailed**.

Chưa chạy: full suite (để dành cuối phase), nautilus_diff S1–S8, test_okx_venue/venue_conformance (không import crawl).

## P9.3 (prep) — chuẩn bị chuyển cây `data/`

Ngày: 2026-10-07 · Người làm: norabt-99 (kiến trúc) · Trạng thái: **CHỈ CHUẨN BỊ — không di chuyển dữ liệu, không commit.** Chạy thật cần: (1) bàn giao alpha ở §3 xong, (2) quyết định ở §1.B, (3) người dùng duyệt.
Tạo: `test/scripts/migrate_data_tree.py` (đã chạy `--dry-run`; đã thử `--apply` trên cây giả trong scratchpad: rename, symlink, gộp quality_gate, idempotent, từ chối khi có live_bot). Vũ trụ OKX CEX cố định 10 tài sản (BTC ETH SOL BNB XRP DOGE ADA AVAX TRX LINK): `data/okx/cex` đúng 10 mã, chỉ có `perp/`.

### 1. Kiểm kê `nora/data` (7.7 GB, 7.584 file; ánh xạ phủ 100 %, 0 mục chưa ánh xạ)

#### A. Đã được ADR §4 xếp chỗ (24 mục, 7.432 file, 7.4 GB)

| Đường cũ | Dung lượng / file | Đích (ADR §4) | Ghi chú |
|---|---|---|---|
| `okx/cex` | 1.0 GB / 80 | `market/okx/cex` | 10 mã × (`perp/{1m..24h}.pkl, funding.pkl, manifest.json`) |
| `okx/dex` | 39 MB / 18 | `market/okx/dex` | AERO, VVV (ticks.parquet, dex_pool.json) |
| `binance/cex` | 1.6 GB / 120 | `market/binance/cex` | 8 mã (không TRX, LINK); chỉ tham khảo |
| `binance_hist/cex` | 1.8 GB / 70 | `market/binance/cex_ref` | TOP10 spot 2019-10→2025-01 + **BCH** (ngoài 10 mã, vẫn giữ: rổ xno). Còn lại `binance_hist/cex` = symlink |
| `_meta` | 184 KB / 6 | `market/_meta` | |
| `_cache/quality_gate` (100) + `okx/_cache/quality_gate` (7) + `binance_hist/_cache/quality_gate` (20) + `binance/_cache/quality_gate` (0) | ~57 KB / 127 | `cache/quality_gate` | gộp theo tên (sha1 khoá); trùng tên khác nội dung → giữ bản mới (cache thuần) |
| `_cache/api_jobs` | 25 MB / 859 | `cache/process/<id>` | 211 job, **3 live_bot đang chạy** |
| `_cache/runs` | 14 MB / 1.332 | `cache/process/_mem/` | log RAM `*_mem.csv` của run_limited.sh (đề xuất; ADR chỉ ghi "← runs"). Tiền tố `_` để không khớp `_JOB_ID_RE` |
| `alphas/{book,registry,presets}.json`, `alphas/explore`, `alphas/testnet` | ~150 KB / 8 | `alpha/…` | đang git-tracked |
| `alphas/user` | rỗng | `alpha/user` | không commit |
| `alphas/research` (okx_top10_agents.json, chưa tracked) | 52 KB / 1 | `alpha/research` | ADR chưa nêu; `core/analytics/top_agents.py` đọc, docstring ghi "git-tracked" |
| `education/samples.json` | 65 KB / 1 | `alpha/education/samples.json` | tracked theo ADR (hiện `.gitignore` chặn) |
| `education/results` | 9.7 MB / 51 | `backtest/education` | sinh lại được |
| `_cache/funnel` | 2.8 GB / 4.480 | `alpha/funnel/<run>` | 22 lượt, results.sqlite(+wal/shm) |
| `_cache/book` | 10.5 MB / 59 | `alpha/book/<run>` | |
| `_cache/book_wfa` | 20 MB / 182 | `wfa/<id>` | |
| `_cache/live` | 1 MB / 36 | `live/<venue_mode>` | okx_demo, okx_demo_unified, okx_paper, okx_paper_explore, paper, paper_v1_20261004; **bot đang ghi** |

Chưa có trong `data/` hiện nay (tạo ở bước sau): `alpha/strategies` + `alpha/universes` (P9.9; universe 10 mã → `alpha/universes/okx_cex10.json`), `backtest/<id>`, `carlo/<id>`, `cache/shared` (hiện mmap dùng chung nằm trong `<run_dir>/_shared`, không có thư mục toàn cục).

#### B. DECISIONS NEEDED (ADR không xếp chỗ) — mặc định script BỎ QUA; `--include-decisions` mới chuyển; "trash" = `data/cache/_trash_p93/`, không xoá

| # | Mục | Cỡ | Đề xuất | Lý do |
|---|---|---|---|---|
| D1 | `_cache/optimize` (6 lượt) | 4 MB / 17 | → `backtest/legacy_optimize` | `alpha/registry.json:3 source_optimization` trỏ `…/20261001_1440` (bằng chứng). Symlink cũ giữ đường tuyệt đối đọc được. Sau này xoá 5 lượt còn lại |
| D2 | `_cache/research` (topbots, market_analysis, funnel_diag, regime) | 3 MB / 8 | → `cache/research` | đầu ra tạm của `test/scripts/research_*.py`, sinh lại được |
| D3 | `_cache/reports` | 58 MB / 8 | → `cache/research/reports` | đầu ra check_signals_strategies/research_maker_scalp/research_trend_portfolio |
| D4 | `_cache/smoke` | 14 KB | → `cache/research/smoke` | smoke_check.py |
| D5 | `_cache/studio_pipeline.db` | 52 KB | **trash** | không code nào đọc/ghi (chỉ architecture.md nhắc) |
| D6 | `_cache/manifest_backup_20261007_162718` | 167 MB / 119 | → `market/_backup/manifest_20261007_162718`, xoá khi P9.1 duyệt xong | sao lưu của P9.1 (manifest 79 mã + khung cũ) — người dùng/norabt-e2 quyết giữ bao lâu |
| D7 | `alphas/custom_strategies.json` (untracked) | 3 KB | **trash** | `api/routers/strategies.py:7`: "bỏ không dùng" |
| D8 | `alphas/portfolio_trend_long_perp__SOL__SOL{,_DOGE}.json` (tracked) | 7 KB | → `alpha/research/` | mồ côi: chỉ docs E4-S5/E5-S2/roadmap nhắc (bằng chứng); cần sửa đường trong docs |
| D9 | `<repo>/data/cache/{binance,okx}` — **ngoài** `nora/data` | 1.0 GB / 976 + 0.8 GB / 49.118 | → `cache/crawl/{binance,okx}` | zip thô của crawler (`crawl/cex.py:57,412`), tải lại được. Cần đổi 2 hằng số ở cex.py |
| D10 | `nora/data_staging` (không tồn tại lúc này; `api/routers/data.py:12`, `store.py:1480`) | — | → `cache/staging` | vùng đệm crawl→promote |
| D11 | `nora/test/data_staging` (85 MB, untracked, không code nào tham chiếu) | 85 MB | xoá | DATA_SYNC_SIGNAL: đã hợp nhất vào `data/okx/cex` |
| D12 | `nora/test/data_legacy` (119 MB, ignored) | — | không đụng | ngoài phạm vi `data/` |
| D13 | `.gitignore`: nay `nora/data/alphas/` tracked, `education/` bị chặn | — | thay khối `nora/data` (xem `--print-gitignore`) | ADR §4.7; symlink cũ nằm dưới `nora/data/*` nên không bị commit; `alphas/` cũ phải `git rm -r --cached` (`--git-stage`) |

Ngoài ra (cần chốt, không ảnh hưởng dữ liệu): quyền sở hữu `alpha/research` (alpha hay kiến trúc), và hạn dọn `cache/process/_mem` (đề xuất 7 ngày).

### 2. Kiểm toán mã: ai dựng đường dẫn dữ liệu

Phân loại: **(a)** đi qua `cache_dir()/default_data_root()/exchange_root()/DATA_HOME` của `crawl/store.py` (qua shim `db.data_layout`); **(b)** viết cứng.

**Nhận xét then chốt.** Mọi người gọi `cache_dir(None, "<tên cũ>")` (api_jobs, book, book_wfa, funnel, live, quality_gate) đều thuộc (a), nhưng tên thư mục cũ là chuỗi ở phía gọi. Cách rẻ nhất: `cache_dir()` GIỮ chữ ký và có bảng ánh xạ tên cũ → vị trí mới (§4). Khi đó các người gọi (a) KHÔNG phải sửa, chỉ (b) mới cần sửa.

**(a) — không cần sửa nếu `cache_dir` có ánh xạ:** `api/jobs/batch.py:89,193` (jobs_root, check_report_dir) · `api/routers/book.py:172,444*` · `api/routers/funnel.py:50` · `api/routers/live.py:41` · `live/bot.py:477-492` · `wfa/run.py:142-191` · `optimize/funnel/orchestrator.py:58` · `optimize/book.py:267,274` · `core/params/presets.py:242` · `core/backtest/dex.py:23,74` · `core/data/shared.py:57` · `crawl/store.py` (quality_gate `_disk_cache_path`).
(*) `book.py:444` dùng `cache_dir(None)` làm GỐC chống truy cập ngoài thư mục: **sẽ hỏng ngay sau khi chuyển** vì `realpath(run_dir)` thành `data/alpha/book|funnel/…`, không còn dưới `data/_cache` → `/jobs/{id}/stage_a…` trả 404. Phải đổi trước khi chạy script (ở §3, mục 1).

**(b) — viết cứng, cần helper:**

| Chủ | Vị trí | Việc |
|---|---|---|
| kiến trúc (tôi) | `crawl/store.py:69-102` DATA_HOME, EXCHANGES, exchange_root, cache_dir; `:1479-1480` DEFAULTS staging/data | helper mới §4 |
| kiến trúc | `crawl/cex.py:57,412` (zip thô ở `<repo>/data/cache`), `:615-628` (`DATA_HOME/binance/cex/<b>/perp/funding.pkl`) | `cache_crawl_dir()`, `market_dir()` |
| kiến trúc | `crawl/dex.py:255` (`_meta/dex_networks.json`, file không tồn tại) | `meta_dir()` |
| kiến trúc | `core/params/presets.py:25-37` (`NORA_DIR/data/alphas`, book/presets path) | uỷ quyền `store.alpha_dir()`; giữ `NORA_ALPHAS_DIR`, `NORA_BOOK_PATH`, `NORA_PRESETS_PATH` |
| kiến trúc | `core/backtest/run.py:35,71` (`data/alphas/book.json`) | dùng `presets.book_path()` |
| kiến trúc | `utils/ops/run_limited.sh:18,66-69` (`data/_cache/runs`) | `cache/process/_mem` |
| kiến trúc | `test/scripts`: `nautilus_diff/export_data.py:23`, `ext_export_data.py:22,51` (`data/okx/cex/…`), `research_regime_diagnosis.py:57`, `research_funnel_diagnosis.py:56,78,151`, `research_topbots.py:45`, `smoke_check.py:409`, `bench_engine.py:170`, `research_maker_scalp.py:265`, `research_trend_portfolio.py:128`, `check_book_perturbation.py:11`, `check_book_out_of_universe.py:11,13`, `okx_top10/load.py:17` | `_cache/…`/`alphas/…` → helper; (bench_engine, check_signals_strategies, okx_top10/* đang dirty: phối hợp) |
| kiến trúc | `test/`: `test_book_api.py:126,280,147`, `test_book_ui_backend.py:65,177,220,267`, `test_strategy_book.py:93`, `test_scale_pipeline.py:322,443`, `test_portfolio_wfa.py:267`, `test_live_bot.py:421,612`, `test_okx_data.py:33`, `test_data_layout.py:103` (`NORA_DATA_ROOT` làm gốc sàn), `test_xno_parity.py:17,41`, `test_diagnostics_real.py:13`, `test_edu_precompute.py:15` (`data/binance_hist`), `test_pydsl_parity.py:64` | dựng cây tạm `alpha/book`, `wfa`, `live`… hoặc dùng helper; `binance_hist` → `resolve_source` |
| vận hành | `systemd/nora-api.service.in`, `nginx/*.conf`, `start.sh`, `stop.sh` | **không** có đường dữ liệu (nginx: "data không phơi") |
| frontend | không file nào dựng đường dẫn; chỉ chuỗi hiển thị | xem §3 mục 18 |

### 3. Bàn giao cho phiên alpha (các file thuộc làn alpha, KHÔNG sửa ở đây)

Quy tắc: file nằm trong làn alpha hoặc đang `M`/`??` trong working tree (dirty) chỉ phiên alpha được sửa. Thứ tự: giao 1-3 TRƯỚC khi chạy script.

1. **`api/routers/book.py`** — (CHẶN) `:444` đổi gốc kiểm tra thành tập {`alpha_run_dir("book")`, `alpha_run_dir("funnel")`, `cache_process_dir()`} (so `realpath`); `:136-142` bỏ bản sao `alphas_dir()/book_path()` → `store.alpha_dir()`; `:313-325` đọc `explore/book.json`, `registry.json` qua helper.
2. **`api/routers/funnel.py`** `:53-54` bỏ bản sao `alphas_dir()`; `:50` (a). **`optimize/revalidate.py:24`** và **`optimize/funnel/{publish,promote,orchestrator}.py`** (dirty): bản sao `alphas_dir()`; `publish.py:115` suy `repo` bằng `alphas_dir()/../..` — vẫn đúng với `data/alpha` (cùng độ sâu).
3. **`api/routers/data.py:12`** `STAGING = NORA_DIR/data_staging` → `store.cache_staging_dir()` (D10); **`api/routers/chart.py:115`** `default_data_root()/"cex"/sym/"perp"` → `market_dir(venue="cex", symbol=…, instrument="perp")`; **`api/routers/live.py:159-160`**.
4. **`core/backtest/edu_precompute.py:26-29,33`** `EDU_DIR/SAMPLES_FILE/RESULTS_DIR` → `alpha_education_samples()`, `education_results_dir()`; `api/routers/education.py:16,42,52` đọc `RESULTS_DIR` (đi theo).
5. **`core/backtest/custom_run.py:57,73,405`** `XNO_DEFAULT_DATA="binance_hist"`, `DATA_HOME/<name>/cex` → `resolve_source(name)` (bí danh `binance_hist` → `market/binance/cex_ref`; bản ghi cũ có `config.exchange/data.source="binance_hist"` vẫn đọc được).
6. **`core/analytics/user_alphas.py:21-25`** `DATA_HOME/"alphas"/"user"` → `alpha_user_dir()`; docstring `:3,:345`.
7. **`core/analytics/top_agents.py:26`** `…/data/alphas/research/okx_top10_agents.json` → `alpha_dir("research", "okx_top10_agents.json")`.
8. **`core/analytics/strategy_doc.py:278-284`** `alphas_dir` mặc định → helper.
9. **`optimize/book.py:292`** `DEFAULTS["out"]=NORA_ROOT/data/alphas` → `alpha_dir()`; docstring `:24,557`. **`optimize/registry.py:16`** docstring.
10. **`core/data/shared.py:57-68`**: khoá mmap băm cả chuỗi `root` → đổi gốc làm đổi khoá một lần (mmap dựng lại, không ảnh hưởng kết quả). Tuỳ chọn: băm `exchange` + tên nguồn thay vì đường tuyệt đối để khoá bền qua mọi lần chuyển.
11. **`api/jobs/batch.py:13,158,196`** chỉ docstring/thông báo lỗi (chữ `data/alphas`, `data/_cache/book/`); `:89,193` (a). **`api/modes.py`**, **`api/routers/{alphas,strategies,book}.py`**: docstring/mô tả field.
12. **`test/scripts/export_edu_samples.py:16`** (`??`, của phiên alpha) → `alpha_education_samples()`.
13. **`test_user_alphas.py:24,251`**, **`test_funnel.py`**, **`test_revalidate.py`**, **`test_top_agents.py`**, **`test_edu_precompute.py`**, **`test_custom_backtest.py`**: dùng `tmp_path/"_cache"/…`/`alphas` — cập nhật theo tên mới khi helper bật.
14. **Frontend (chỉ chuỗi hiển thị, không dựng đường dẫn)**: `AlphaDrawer.jsx:154` ("data/alphas/registry.json"), `lib/funnelMock.js:87`, `lib/eduDefaults.js:5`, `education/usePrecomputed.js:5`, `mock/wfa.sample.json:3336` → "data/alpha/…".

### 4. Thiết kế helper `crawl/store.py` (VIẾT, CHƯA ÁP DỤNG)

Gốc chọn MỘT chỗ. `data_home()` = `NORA_LOCAL_DATA_ROOT` (test; thư mục phẳng, vừa là home vừa là gốc sàn — giữ nguyên hành vi hiện nay) → `NORA_DATA_ROOT` (home, mặc định `nora/data`; **đổi nghĩa**: hiện là bí danh cũ của gốc sàn — `test_data_layout.py:103` cần cập nhật; nếu giá trị có `cex/` hoặc `dex/` ngay dưới thì coi là gốc sàn phẳng) → `<nora>/data`. `NORA_EXCHANGE` chọn sàn (`okx|binance`) như cũ.

**FALLBACK** (trong lúc chuyển): mỗi helper có cặp (mới, cũ); `_pick(new, old)` = `new` nếu tồn tại, rồi `old` nếu tồn tại, nếu không `new` (để tạo mới). Không dùng cờ toàn cục, nên chuyển dở dang (script dừng ở mục lỗi) vẫn chạy được; thêm `layout_version()` = 2 nếu `isdir(home/"market")` (chỉ để báo cáo/log).

```python
# ── Layout (P9.3) ────────────────────────────────────────────────────────────────────────────────────────────
data_home() -> str                                   # xem trên
resolve_source(name=None) -> Source(exchange, root, cex_dir, alias)   # None = NORA_EXCHANGE; "okx"|"binance"|"binance_hist"
#   "binance_hist" -> Source("binance", market/binance, cex_dir="cex_ref", alias="binance_hist")   # v1: root=home/binance_hist, cex_dir="cex"
market_root(exchange=None) -> str                    # = exchange_root() hiện nay; v2: market/<ex>; v1: home/<ex>; test: LOCAL (phẳng)
market_dir(exchange=None, venue="cex", symbol=None, instrument=None) -> str
#   v2: market/<ex>/<venue>[/<SYM>[/perp]]  venue ∈ {cex, dex, cex_ref(chỉ binance)};  v1: home/<ex>/<venue>/…
meta_dir() -> str                                    # market/_meta | home/_meta
alpha_dir(*parts) -> str                             # home/alpha | home/alphas;  NORA_ALPHAS_DIR vẫn ghi đè (1 chỗ thay 4 bản sao)
alpha_file(name) -> str                              # book.json | registry.json | presets.json (NORA_BOOK_PATH / NORA_PRESETS_PATH ghi đè)
alpha_user_dir() -> str                              # alpha/user
alpha_education_samples() -> str                     # alpha/education/samples.json | education/samples.json
alpha_run_dir(kind, run_id=None) -> str              # kind ∈ {funnel, book}: alpha/<kind>/<id> | _cache/<kind>/<id>
run_dir(kind, run_id=None) -> str                    # kind ∈ {backtest, wfa, carlo}: home/<kind>/<id>  (wfa v1: _cache/book_wfa)
education_results_dir() -> str                       # backtest/education | education/results
live_dir(venue, mode, book="main", engine="legacy") -> str   # live/<state_key>  (state_key chuyển từ live/bot.py: giữ nguyên chuỗi)
cache_process_dir(job_id=None) -> str                # cache/process/<id> | _cache/api_jobs/<id>
cache_shared_dir(name=None) -> str                   # cache/shared/<name>  (mmap dùng chung; hiện mỗi run có <run_dir>/_shared)
cache_quality_gate_dir() -> str                      # cache/quality_gate | _cache/quality_gate
cache_runs_dir() -> str                              # cache/process/_mem | _cache/runs
cache_staging_dir() / cache_crawl_dir(exchange) -> str   # cache/staging, cache/crawl/<ex>  (quyết định D9/D10)
cache_dir(data_root=None, *parts) -> str             # GIỮ chữ ký. Phần đầu thuộc bảng LEGACY được định tuyến:
LEGACY_CACHE_NAMES = {"api_jobs": cache_process_dir, "book": alpha_run_dir("book"), "funnel": alpha_run_dir("funnel"),
                      "book_wfa": run_dir("wfa"), "live": home/"live", "quality_gate": cache_quality_gate_dir, "runs": cache_runs_dir}
#   tên khác ("research","reports",…) -> cache/<tên> (v2) | _cache/<tên> (v1). `data_root` tường minh (quality gate theo sàn) vẫn được tôn trọng.
```

Điểm cần lưu ý khi áp dụng:
- Khoá cache (mmap `shared.plan`, `_file_fingerprint`, cổng chất lượng) băm chuỗi gốc. Giữ `market_root()` trả đường **cũ** (`data/okx`, đi qua symlink) cho tới bước cắt (sau script), rồi chuyển sang `market/okx` — khi đó khoá đổi đúng MỘT lần (mmap dựng lại, cổng ~10 s/tài sản), không ảnh hưởng kết quả/golden.
- `binance_hist` không phải một sàn: là `Source` có `cex_dir="cex_ref"`. `local_pkl.resolve_symbol_dir/list_assets` hiện ghép cứng `"cex"` → đổi thành `src.cex_dir`. Symlink tạm `data/binance_hist/cex → ../market/binance/cex_ref` giữ code cũ chạy. Alias nằm trong danh sách shim, không gỡ ở P9.10.
- Quality gate: cache theo sàn (`okx/_cache/...`) gộp vào `cache/quality_gate`; khoá đã chứa `data_root` nên không va chạm.
- Mọi đường tuyệt đối đã ghi trong job.json/state/registry (`…/data/_cache/...`, `…/data/okx/cex/…`) vẫn đọc được nhờ symlink tương đối tại đường cũ — giữ tới P9.10.

### 5. Script `test/scripts/migrate_data_tree.py`

- `--dry-run` (mặc định) / `--apply`; `--allow-live`, `--allow-jobs`, `--include-decisions`, `--only K1,K2`, `--full-hash`, `--workers N`, `--git-stage`, `--print-gitignore`, `--report PATH`, `--data-root` (thử trên cây giả).
- Chuyển: rename nguyên tử cùng ổ đĩa (giữ inode, vài giây cho 7.4 GB); khác ổ → sao chép sang `.p93part`, kiểm, đổi tên. Symlink tương đối thế chỗ: tạo symlink tạm cạnh nguồn → rename nguồn → rename symlink thành đường cũ (cửa sổ hở vài micro giây, kể cả `live/` và `cache/process`).
- Kiểm: manifest TRƯỚC (số file, size, mtime_ns, sha256 mỗi file ≤ 100 MB; file lớn hơn: size+mtime_ns, `--full-hash` để băm hết) và SAU, so khớp; cùng inode mà nội dung đổi (bot đang ghi `events.jsonl`/`out.log`) chỉ ghi `mutated_live`, mất/khác file → LỖI, hoàn tác (rename ngược) và dừng.
- Idempotent: trạng thái từng mục `todo | done | needs_link | merge_todo | conflict | foreign_link | src_missing`; chạy lại bình thường sau gián đoạn. Dừng ở mục lỗi đầu tiên (mã thoát 1); `--apply` bị từ chối (mã 3) khi có `live_bot` đang chạy mà thiếu `--allow-live` (hoặc job khác thiếu `--allow-jobs`).
- Báo cáo JSON `data/_migration/p9_3_<UTC>.json` (từng mục: trạng thái, số file, byte, phương pháp, verify, thời gian, lỗi) + mục chưa ánh xạ + mục DECISION bị bỏ qua.
- Thử trên cây giả (35 mục, gồm gộp va chạm quality_gate, trash, live giả): 35/35 ok, chạy lại 0 việc, `--apply` không có `--allow-live` → từ chối, mã 3.
- Quy trình chạy thật đề xuất: (0) helper `store.py` + bàn giao §3 mục 1-3 + test cập nhật, một suite đầy đủ; (1) không có pytest/job nặng khác đang chạy; bot demo KHÔNG cần dừng (`--allow-live`, ghi qua symlink); (2) `--apply --allow-live` (core), kiểm báo cáo; (3) `--include-decisions` theo quyết định §1.B; (4) `.gitignore` + `--git-stage` (không commit); (5) bật helper sang đường mới (khoá cache đổi một lần); (6) P9.10 gỡ symlink.

### 6. Kết quả `--dry-run` (từ `nora/`, qua `run_limited.sh --no-lock`)

```
guard: live_bot đang chạy=3 [20261006_042423_d4ada8, 20261007_063510_901b8a, 20261005_071648_4bb4df]; job khác=0 -> --apply SẼ TỪ CHỐI nếu thiếu --allow-live
24 mục (ADR §4): 7.432 file, 7.4 GB; xung đột=0; chưa ánh xạ=0
  okx_cex 80f 1.0GB · okx_dex 18f 39MB · binance_cex 120f 1.6GB · binance_hist 70f 1.8GB · meta 6f · qg_* 127f · process 859f 25MB · mem_csv 1.332f 14MB
  alpha_* 8f · edu_samples 1f · edu_results 51f 9.7MB · funnel 4.480f 2.8GB · book_runs 59f · wfa 182f 20MB · live 36f 1MB
+ 11 mục DECISION (--include-decisions): thêm 157 file trong nora/data (~234 MB) + 49.118+976 file / 1.8 GB ngoài nora/data (<repo>/data/cache) => 57.680 file, 9.3 GB tổng
```

## P9.3a — helper đường dẫn dữ liệu trong `crawl/store.py`

Ngày: 2026-10-07 · Người làm: norabt-99 (kiến trúc) · Trạng thái: **xong, chưa commit; KHÔNG di chuyển dữ liệu, KHÔNG sửa người gọi** (bước b là của phiên alpha).

**Luật.** Mọi helper tính ở THỜI ĐIỂM GỌI từ env (`NORA_LOCAL_DATA_ROOT` > `NORA_DATA_ROOT` > `nora/data`; `NORA_EXCHANGE`) — không cache lúc import. Chỉ trả đường (không tạo, trừ `cache_dir()` vẫn makedirs như cũ).
**Fallback** (`_pick`): đường MỚI nếu tồn tại → đường CŨ nếu tồn tại → không có gì: gốc mới là thư mục thì mới, gốc cũ là thư mục thì cũ, còn lại mới nếu `<home>/market` đã có, nếu không CŨ (cây chưa chuyển hành xử như trước P9.3, kể cả `cache_dir(None,"x")` → `_cache/x`). Sau chuyển, symlink ở đường cũ trỏ về mới nên hai cách gọi cùng đúng.
**Chế độ phẳng**: `NORA_LOCAL_DATA_ROOT` đặt (test), hoặc `NORA_DATA_ROOT` có `cex/`/`dex/` ngay dưới (bí danh cũ của gốc sàn) → thư mục đó vừa là home vừa là gốc sàn (`market_root()==home`, không kiểm `NORA_EXCHANGE`) — đúng hành vi cũ. `NORA_DATA_ROOT` khác thì là HOME (đổi nghĩa so với trước; chỉ `test_data_layout.py:103` đụng tới và vẫn xanh vì LOCAL thắng).

| Helper | Mới (cũ) |
|---|---|
| `data_home()`, `layout_version()` (1/2) | home theo env; 2 nếu có `<home>/market` |
| `resolve_source(name=None) -> Source(exchange, root, cex_dir, alias)` + `.cex_path` | None=sàn đang dùng; `okx`/`binance`; **`binance_hist` → `market/binance/cex_ref`** (cũ `<home>/binance_hist/cex`; Source.root/cex_dir đổi theo trạng thái); tên thư mục `<home>/<tên>/cex`; lạ → ValueError |
| `market_root(exchange=None)` (= `exchange_root` = `default_data_root`) | `market/<ex>` (`<home>/<ex>`) |
| `market_dir(exchange=None, venue="cex", symbol=None, instrument=None)` | `market_root/<venue>[/<SYM>[/perp]]`; venue `cex\|dex\|cex_ref` (cex_ref chỉ binance); `symbol` nhận `BTC@perp` |
| `meta_dir()` | `market/_meta` (`_meta`) |
| `alpha_dir(*parts)`, `alpha_file(name)`, `alpha_user_dir()` | `alpha/…` (`alphas/…`), fallback theo từng LÁ; `NORA_ALPHAS_DIR`, `NORA_BOOK_PATH`, `NORA_PRESETS_PATH` vẫn ghi đè; `name` nhận `book` hoặc `book.json` |
| `alpha_education_samples()` | `alpha/education/samples.json` (`education/samples.json`); KHÔNG theo `NORA_ALPHAS_DIR` |
| `education_results_dir()` | `backtest/education` (`education/results`) |
| `alpha_run_dir(kind∈funnel\|book, run_id=None)` | `alpha/<kind>[/<id>]` (`_cache/<kind>`) |
| `run_dir(kind∈backtest\|wfa\|carlo, run_id=None)` | `<kind>[/<id>]` (`_cache/<kind>`; wfa cũ `_cache/book_wfa`) |
| `live_dir(venue, mode, book="main", engine="legacy")`, `live_state_key(...)` | `live/<key>` (`_cache/live/<key>`); `live_state_key` là bản sao nguyên văn `live.bot.state_key` (crawl không import live; có test so khớp) |
| `cache_process_dir(job_id=None)` | `cache/process[/<id>]` (`_cache/api_jobs`) |
| `cache_shared_dir(name=None)` | `cache/shared[/<n>]` (`_cache/shared`) |
| `cache_quality_gate_dir()`, `cache_runs_dir()` | `cache/quality_gate`, `cache/process/_mem` (`_cache/quality_gate`, `_cache/runs`) |
| `cache_staging_dir()` | `cache/staging` (`nora/data_staging`) |
| `cache_crawl_dir(exchange=None)` | `cache/crawl/<ex>` (`<repo>/data/cache/<ex>`, ngoài nora/data; `NORA_OKX_CACHE_DIR` vẫn do cex.py xử lý) |
| `cache_dir(data_root=None, *parts)` | GIỮ chữ ký + makedirs. `parts[0]` ∈ `LEGACY_CACHE_NAMES` (`api_jobs→process, book, funnel, book_wfa→wfa, live, quality_gate, runs→mem`) định tuyến sang vị trí mới có fallback; tên khác/không tên → `cache/<tên>` (`_cache/<tên>`). `data_root` tường minh = home cho định tuyến (khoá quality-gate theo sàn vẫn tạo `…/_cache/quality_gate` khi cây chưa chuyển) |
| `allowed_roots(kind) -> list[str]`, `is_within(path, kind) -> bool` | realpath của CẢ gốc mới lẫn cũ (khử trùng khi symlink cũ→mới; gốc chưa tồn tại vẫn liệt kê). kind: `alpha funnel book backtest wfa carlo live process mem shared quality_gate staging cache education_results meta` hoặc nhóm **`runs`** = book+funnel+wfa+backtest+carlo+process (thay `cache_dir(None)` làm gốc chặn traversal ở `book.py:444`). `is_within` so realpath + ranh giới thư mục (không khớp tiền tố chuỗi; symlink thoát gốc bị chặn) |

**Chưa làm (cố ý, bước sau):** `list_assets/resolve_asset_dir/resolve_symbol_dir` vẫn ghép cứng `"cex"` → cần `Source.cex_dir` khi bật `binance_hist` mới (tới đó dùng symlink `binance_hist/cex → market/binance/cex_ref` như kế hoạch §4); `DEFAULTS` của promote (`staging`, `data`) và `_disk_cache_path` chưa đổi sang `cache_staging_dir()/cache_quality_gate_dir()`; `crawl/cex.py` còn viết cứng đường zip; khoá mmap `shared.plan` băm `market_root()` nên đổi MỘT lần khi `market/<ex>` xuất hiện. `test_okx_data.py:33` kỳ vọng `cache_dir(None,"x")` dưới `DATA_HOME/_cache` — đúng cho tới khi `nora/data/cache` hoặc `market` tồn tại thật, lúc đó cập nhật.

**File chạm:** `backend/crawl/store.py` (thay `exchange_root`, `cache_dir`; thêm khối P9.3a + ghi chú đầu mục layout), `test/test_data_layout_helpers.py` (mới, 74 test: 3 trạng thái old/new/migrated cho từng helper, env tại lúc gọi, chế độ phẳng, alias binance_hist, định tuyến `cache_dir` cho cả 7 tên cũ, allowed_roots/is_within với symlink thoát gốc, khớp `live.bot.state_key`), `docs/bmad/p9_review_log.md`. `docs/bmad/p9_layering_report.md` tự sinh lại bởi test_layering. Không sửa file làn alpha.

**Cổng** (`run_limited.sh --no-lock`, `PYTHONDONTWRITEBYTECODE=1`): baseline (9 file, trước khi sửa) **87 passed, 2 skipped**; sau: +test mới = **161 passed, 2 skipped** (101 s) — test_data_layout_helpers, test_data_layout, test_data_quality_gate, test_okx_data, test_crawler_and_gate, test_shared_data, test_live_bot, test_bot_unified, test_golden_results, test_layering. Không test nào đỏ trước hay sau. Chưa commit.


## P9.4 part 1 — `core/{models, position_size, params, backtest}.py` (gộp nguyên văn + shim)

Ngày: 2026-10-07 · Người làm: norabt-99 (kiến trúc, chỉ di chuyển) · Trạng thái: **xong, CHƯA commit, chờ review chéo**. Không đổi logic.

**Phương pháp.** Script tái tạo (nối nguyên văn thân module theo thứ tự; chỉ gỡ import nội bộ nhóm — kể cả import cục bộ trong hàm — và trỏ import ngoài nhóm sang module mới; docstring module -> comment banner). Kiểm AST từng hàm/lớp/hằng cấp module so với `git HEAD`: **280 giống hệt + 3 hàm chuyển chỗ giống hệt (policy -> models) + 7 khác đúng bằng dòng import/gọi bên dưới + 26 định danh dữ liệu ở lại book.py** (tổng 316). Thứ tự trong file backtest.py: kernel, engine, portfolio, dex (engine/portfolio dùng kernel qua tên cấp module thay vì import cục bộ).

### Bảng ánh xạ cũ -> mới (mọi hàm/lớp/hằng cấp module)

**core/models.py**

- `core/execute/models.py`: `PositionType`, `OrderType`, `PositionStatus`, `PositionModel`, `OrderModel`
- `core/execute/events.py`: `Fill`, `FundingApplied`, `OrderRejected`, `PositionMarked`
- `core/execute/account.py`: `Event`, `Account`, `PositionBook`
- `core/execute/ledger.py`: `CapitalLedger`

**core/position_size.py**

- `core/execute/policy.py`: `ImpactFn`, `INTRABAR_PATHS`, `sign_of`, `bar_points`, `peak_step`, `tick_stop_price`, `dca_level`, `dca_trigger`, `sl_level`, `trail_active`, `trail_level`, `tp_level`, `tp_need`, `tp_hit`, `tp_fill_price`, `liq_price`, `reached`, `gap_fill`, `stop_extreme_fill`, `pick_first_touched`, `slip_rate`, `round_trip_cost`, `entry_fill_price`, `exit_fill_price`, `entry_fee`, `exit_fee`, `in_profit`, `funding_payment`, `layer_mult_total`, `exit_params_scaled`, `flat_margin`, `risk_margin`, `clamp_margin`, `planned_risk_cap`, `apply_risk_ceiling`; `pnl_move`, `gross_pnl`, `unrealized_pnl` -> `core/models.py` (position_size import lại)
- `core/execute/risk.py`: `INF`, `Admission`, `admit_entry`, `kill_triggered`

**core/params.py**

- `core/params/schema.py`: `StrategyParams`
- `core/params/template.py`: `SIG_PREFIX`, `FRAMES`, `FRAME_MINUTES`, `MIN_PERIOD`, `MAX_PERIOD`, `_STR_PLACEHOLDER`, `_STR_FIELDS`, `collect_placeholders`, `collect_string_placeholders`, `_fmt_number`, `_placeholder_text`, `_resolve_string`, `resolve_placeholders`, `split_params`
- `core/params/builder.py`: `POSITION_KEYS`, `VENUE_COSTS`, `venue_of_symbol`, `resolve_costs`, `data_symbol`, `pool_fee_rate`, `dca_budget_check`, `build_params`
- `core/strategy/book.py` (phần materialize/BASE_POSITION): `MAX_LEVERAGE`, `BASE_RISK_PER_TRADE_PCT`, `PESSIMISTIC_LIMIT_THROUGH_PCT`, `BASE_POSITION`, `REGIME_DENY`, `_REGIME_NAMES`, `regime_for`, `REGIME_MAP`, `schema_defaults`, `signal_defaults`, `materialize` (REGIME_MAP: xem bên dưới; còn lại ở book.py)

**core/backtest.py**

- `core/backtest/kernel.py`: `NONE_I`, `F_QTY`, `F_AVG`, `F_MU`, `F_FP`, `F_LAST_FILL`, `F_NEXT`, `F_PEAK`, `F_MAE`, `F_RES_HERE`, `F_FUND`, `F_ENTRY_EQ`, `F_MAXCAP`, `F_POS_LEV`, `F_PLANNED`, `F_PVOL`, `F_SL`, `F_TP`, `F_TRAIL`, `F_TACT`, `F_DS0`, `F_FIXED`, `P_FEE`, `P_MAKER`, `P_SLIP`, `P_MMR`, `P_MAXLEV`, `P_CAPUSE`, `P_BSL`, `P_BTP`, `P_BTR`, `P_BTA`, `P_RISK`, `P_MAXNOT`, `P_OSP`, `P_LTHRU`, `P_BS0`, `P_FIXED`, `PI_LONG`, `PI_PERP`, `PI_TIMEOUT`, `PI_COOL`, `PI_EXTREME`, `PI_ATR`, `PI_RISKSZ`, `PI_NBASE`, `PI_MAXOPEN`, `PI_PATH`, `NPI`, `I_OPEN`, `I_PE`, `I_PX`, `I_LAYERS`, `I_ENTRY_T`, `I_LASTCLOSE`, `I_HASLC`, `I_DCAREJ`, `I_SKIP`, `I_POS`, `I_NST`, `I_BLK`, `I_DCAOK`, `NI`, `G_REJ`, `G_NPOS`, `G_NORD`, `G_NCL`, `G_OVF`, `G_RISKMIN`, `G_ATT`, `G_HALT`, `G_RUIN`, `G_NSMP`, `NG`, `LG_EQ`, `LG_RES`, `LG_PEAK`, `O_ENTER_PRICE`, `O_CLOSE_PRICE`, `O_PNL`, `O_PCT`, `O_QTY`, `O_AVG`, `O_ENTRY_EQ`, `O_ENTRY_MARGIN`, `O_ENTRY_NOTIONAL`, `O_ENTRY_FEE`, `O_EXIT_FEE`, `O_TOTAL_MARGIN`, `O_FEES`, `O_FUNDING`, `O_MAE`, `O_MAXP`, `O_MINP`, `O_UNIT`, `O_LEVUSED`, `O_RISK`, `NOF`, `OI_TR`, `OI_ENTER_T`, `OI_CLOSE_T`, `OI_STATUS`, `OI_LAYERS`, `OI_REASON`, `OI_FIRST_ORD`, `OI_START`, `NOI`, `OR_PRICE`, `OR_QTY`, `OR_FEE`, `ORI_POS`, `ORI_TIME`, `ORI_PHASE`, `ORI_EXIT`, `ORI_LIQ`, `R_ENTRY`, `R_STOP`, `R_TIMEOUT`, `R_LIQ`, `R_SL`, `R_TRAIL`, `R_TP`, `R_END`, `R_KILL`, `R_DCA`, `S_TP`, `S_SL`, `S_CANCEL`, `S_LIQ`, `_JIT`, `_ptr`, `_pmax`, `_pmin`, `_unreal`, `_apply_funding`, `_log_order`, `_add_layer`, `_apply_exit_unit`, `_layer_mult_total`, `_risk_margin`, `_close`, `_status_by_pnl`, `_open`, `_better`, `_intrabar`, `_extreme_price`, `_intrabar_path`, `_intrabar_adverse`, `_on_bar_open`, `_on_bar_rest`, `_on_bar`, `_quiet_bar`, `_lower`, `_upper_abs`, `_any_active`, `_sample`, `portfolio_kernel`, `single_kernel`, `REASONS`, `LIQUIDITY`, `_RETRY_FACTOR`, `_INIT_CAP_POS`, `_INIT_CAP_ORD`, `_MAX_TRIES`, `_CAP_HINT`, `pack_trackers`, `_Tables`, `_alloc`, `_build_objects`, `_writeback`, `_round_curve`, `run_portfolio`, `run_many`, `run_backtest`, `run_single`
- `core/backtest/engine.py`: `FRAME_MS`, `LEGACY_4H_COLUMNS`, `BASE_COLS`, `KEY`, `collect_field_refs`, `frame_features`, `HISTORY_START`, `BacktestEngine`, `needs_minute_path`
- `core/backtest/portfolio.py`: `RiskConfig`, `_DATA_CACHE`, `data_cache_clear`, `aggregate_positions`, `_strategy_flow`, `PortfolioEngine`
- `core/backtest/dex.py`: `SPOT_POSITION`, `POOL_TYPES`, `is_dex_symbol`, `classify_symbols`, `require_perp`, `display_name`, `require_long_legs`, `_read_json`, `pool_info`, `check_amm_pool`, `tick_window`


### Shim (13 alias `sys.modules` + 2 stub gói)

Alias (cùng một đối tượng module — cache/trạng thái module-level chỉ có một bản, monkeypatch qua đường cũ có hiệu lực, pickle tên lớp/hàm cũ vẫn nạp được): `core/execute/{models,events,account,ledger}` -> `core.models`; `core/execute/{policy,risk}` -> `core.position_size`; `core/params/{schema,template,builder}` -> `core.params`; `core/backtest/{engine,portfolio,dex,kernel}` -> `core.backtest`. `CapitalLedger` (tên cũ trong `execute/ledger`) là một tên trong `core.models`.
Stub gói: `core/params/__init__.py` và `core/backtest/__init__.py` (đánh dấu `# P9-SHIM`). **Lý do:** `core/backtest.py` và thư mục gói `core/backtest/` (còn `run, custom_run, tick_run, edu_precompute`; cùng `run_defaults` của phiên kia) cùng tên module — Python luôn chọn gói trước, file bị che. Stub nạp `core/backtest.py` bằng `spec_from_file_location(..., submodule_search_locations=[thư mục gói])` và đặt vào `sys.modules`: module `backend.core.backtest` là FILE (đúng cây đích ADR), có `__path__` nên `backend.core.backtest.run` / `python -m backend.core.backtest.run` / `batch.KINDS` vẫn chạy. Tương tự `core/params.py` với `presets, modes`. Xoá stub + thư mục gói khi các module còn lại chuyển (P9.10). `__module__` của mọi lớp/hàm engine nay là `backend.core.backtest` / `backend.core.models` (đúng tên cuối).
Importer trong `core/execute` còn giữ (chỉ sửa dòng import, không đụng thân): `tracker`, `manager`, `sim_venue`, `runner`, `venue` -> import từ `core.models`, `core.params`, `core.position_size` (`from backend.core import position_size as policy` nên thân `policy.xxx` không đổi). `amm` không import module nào của nhóm.

### Đổi tên
**Không có.** Không định danh nào trùng tên trong 4 nhóm (kiểm bằng AST); chỉ các tên module `engine/portfolio/dex/kernel/schema/template/builder/...` bị gán làm thuộc tính tự trỏ lên module gộp khi nhập đường cũ — đã kiểm không có biến cấp module trùng các tên đó.

### Chu trình / vi phạm thứ tự đã xử lý (cách nhẹ nhất, cơ học)
1. **models -> position_size** (`account.py` gọi `policy.gross_pnl`, `policy.unrealized_pnl`; models đứng TRƯỚC position_size): chuyển 3 hàm nhỏ `pnl_move`, `gross_pnl`, `unrealized_pnl` từ policy sang `core/models.py` (một bản duy nhất, có banner); `position_size` import lại đúng ba tên đó từ models nên `position_size.gross_pnl is models.gross_pnl`; hai chỗ gọi trong PositionBook đổi `policy.gross_pnl(...)` -> `gross_pnl(...)`, `policy.unrealized_pnl(...)` -> `unrealized_pnl(...)`. (Vi phạm `core order models -> position_size` 1 -> 0.)
2. **params <- book (dữ liệu)**: `materialize` tra `REGIME_MAP` build từ `CANDIDATES` (ở lại book.py). `core/params.py` giữ `REGIME_MAP: dict = {}`; `book.py` điền `REGIME_MAP.update({id: regime_for(side) ...})` ngay sau `CANDIDATES` và re-export (`book.REGIME_MAP is params.REGIME_MAP`, 6 mục). Thiếu mục -> `materialize` vẫn rơi về `regime_for(side)` (cùng giá trị). `book.py` import ngược `BASE_POSITION, MAX_LEVERAGE, BASE_RISK_PER_TRADE_PCT, PESSIMISTIC_LIMIT_THROUGH_PCT, REGIME_DENY, _REGIME_NAMES, regime_for, schema_defaults, signal_defaults, materialize` từ params (mọi `book.X` cũ vẫn dùng được).
3. **engine <-> kernel <-> portfolio** (import cục bộ vòng `engine.run -> kernel.run_backtest`, `kernel.run_many -> engine.BacktestEngine`, `portfolio.run -> kernel.run_*`) và `book -> params.template`: gỡ import cục bộ, dùng tên cấp module cùng file. Một import cục bộ `portfolio -> params.builder.build_params` thành `from backend.core.params import build_params` (backtest -> params hợp lệ).
4. **Hệ quả monkeypatch**: vì engine/portfolio/kernel nay chung một namespace, `monkeypatch.setattr(engine_mod, "BacktestEngine", Ref...)` cũng đổi tên đó cho `PortfolioEngine` thật trong cùng module (trước đây `portfolio` giữ bản import riêng). Các test dùng cách này (test_skip_idle, test_dca_cooldown, test_portfolio_engine, test_capital_ledger) đều xanh.
**Còn lại, có từ trước (không thuộc bước này):** `core order params -> indicator` (import cục bộ `signals.kernels` trong `template`) hết khi indicator chuyển; `core -> crawl/regime` (loader, data_layout, local_pkl, shared, quality_gate, classifier) của engine/builder/dex hết ở các bước core-không-đọc-file / P9.7.

### Numba cache
`cache=True` giữ nguyên. Cache nằm cạnh file nguồn: trước `core/backtest/__pycache__/kernel.*.nbi`, nay `core/__pycache__/backtest.*.nbi` (65 file). Lần chạy đầu biên dịch lại một lần (warm-up bench 92 s khi cache cũ nguội; về sau 3,7 s nạp từ cache mới). File `.nbi/.nbc` cũ ở `core/backtest/__pycache__` mồ côi (an toàn xoá).

### Pickle
Bản SAO (không đụng file thật) của 6 file `data/_cache/live/*/{paper,unified}.pkl` (okx_demo, okx_demo_unified paper+unified, okx_paper, okx_paper_explore, paper) nạp bằng Unpickler có ghi `find_class`: **TRƯỚC 6/6 nạp được, SAU 6/6 nạp được**, cùng tập tên cũ được tra (`core.execute.ledger.CapitalLedger`, `...account.{Account,PositionBook}`, `...models.*`, `...params.schema.StrategyParams`, `...tracker/manager/runner/sim_venue/venue.*`). Sau nạp, `Account` có `__module__ = backend.core.models`. Pickle MỚI sẽ ghi tên mới -> không quay lui code sau khi bot đã ghi pickle mới. Worker pool pickle tên hàm: `pickle.loads(pickle.dumps(run_backtest)) is run_backtest` (module `backend.core.backtest`); `batch.KINDS` 16/16 module resolve được.

### Cổng (`NORA_GOLDEN_DATA_ROOT=data/binance`, `run_limited.sh --no-lock`, 24 file)
| | Kết quả |
|---|---|
| BASELINE (trước, đo lúc 17:38) | 397 passed, 9 failed, 5 skipped (968 s). 9 đỏ KHÔNG do bước này: 8 ở test_custom_backtest (`ModuleNotFoundError backend.core.metrics.xno` — phiên alpha đang gộp xno giữa chừng) + test_layering (`IndentationError` ở file alpha đang sửa dở). Chạy lại test_layering lúc đó đã xanh. |
| SAU | **404 passed, 5 skipped, 0 failed** (1034 s). Số test khác baseline vì phiên alpha đổi test/mã song song. test_golden_results, test_kernel_parity, test_portfolio_engine, test_event_path_parity, test_runner_parity, test_account_replay, test_venue_conformance, test_live_bot, test_bot_unified, test_tick_backtest... đều xanh. |
| nautilus_diff S1-S3 aligned | `run_nora.py ohlc` + `adaptive` rồi `compare.py fine` / `fine _adaptive`: 36 file `out/nora_*.json` + `results_fine.json` + `results_fine_adaptive.json` **giống từng byte** trước/sau; bảng markdown giống hệt; JSON đã commit không đổi (`git status` sạch); tracker==manager bit-identical 18/18 mỗi lượt. |
| Tốc độ (`bench_engine.py compare --n 3 --batch 100 --old-batch 0`, cache nóng) | trước 1,077-1,137 s/alpha riêng, 159-162 ms/alpha lô; sau 1,097-1,113 s, 159-162 ms. Không chậm. |
| test_layering | trước 61 vi phạm (143 module, 12 shim); sau **62** (146 module, 25 shim). Phần của bước này: **-1** (`models -> position_size`); +2 `core -> crawl` là file mới `core/backtest/run_defaults.py` của phiên alpha; mọi cạnh của 4 module gộp giống hệt trước (so theo từng cạnh). Bảng `LAYER_RULES` thêm `core/models`, `core/position_size`; `_all_modules` ưu tiên file thật khi trùng tên với stub. |

### Việc phải làm tiếp (ngoài làn kiến trúc — phiên alpha)
- **`utils/engine_version.py` `ENGINE_DIRS` và `optimize/store.py` `_CODE_FILES`** vẫn trỏ file cũ (nay là shim vài dòng) -> hash engine / `code_version` (khoá `--resume`) KHÔNG còn thấy thay đổi mã engine. Cần thêm `core/{backtest,models,params,position_size}.py`. Hash vốn đã đổi vì lần chuyển này (sổ sẽ báo "cần dựng lại" một lần). Chưa sửa vì thuộc làn alpha.
- **Khởi động lại bot live** (okx_demo, okx_paper...) sau khi commit: tiến trình đang chạy giữ lớp cũ trong bộ nhớ; import lười sau này sẽ nạp lớp ở module mới (trộn hai bản Enum/lớp).
- P9.4b (gỡ tracker/manager/sim_venue/runner + venue/amm vào backtest.py) và P9.10 (gỡ shim + stub gói).

## P9.3c plan — chuyển cây `data/` theo quyết định CUỐI (CHỈ KẾ HOẠCH + dry-run; chưa áp dụng, chưa commit)

Ngày: 2026-10-07 · Người làm: norabt-99 (kiến trúc) · Script: `test/scripts/migrate_data_tree.py` (viết lại theo quyết định cuối; chưa tracked). Không sửa file làn alpha.
Thử trên cây giả (bản sao nhỏ của `_cache/{api_jobs,backtest,book,book_wfa,live,quality_gate,runs}`, `alphas`, `education`, stub market): `--apply --allow-live --remove-stale-registry`
chạy được 29/29 bước, chạy lại idempotent, `persist_finished_jobs(apply=True)` gọi thật (95 job chép + 24 dọn trong cây giả), bot "live" cũ/mới cùng một thư mục, `out.log` cùng inode.

### 1. Bản đồ cũ -> mới (thứ tự thực hiện)

| # | Khoá | Cũ (dưới `nora/data/`) | Mới | Ghi chú |
|---|---|---|---|---|
| 1 | okx_cex / okx_dex | `okx/{cex,dex}` | `market/okx/{cex,dex}` | rename cùng ổ đĩa + symlink tương đối |
| 2 | binance_cex | `binance/cex` | `market/binance/cex` | |
| 3 | binance_hist | `binance_hist/cex` | `market/binance/cex_ref` | bí danh giữ bằng symlink `binance_hist/cex` |
| 4 | meta | `_meta` | `market/_meta` | |
| 5 | alpha_book/registry/presets | `alphas/{book,registry,presets}.json` | `alpha/…` | đang tracked -> `--git-stage` |
| 6 | alpha_explore / testnet / user / research | `alphas/{explore,testnet,user,research}` | `alpha/…` | `research` = `okx_top10_agents.json` (đã tracked) |
| 7 | edu_samples | `education/samples.json` | `alpha/education/samples.json` | sẽ tracked (hiện bị .gitignore chặn) |
| 8 | **registry_fix** | `alpha/registry.json` | (sửa tại chỗ) | BƯỚC RIÊNG, cần `--remove-stale-registry`; sao lưu `registry.json.bak` vào thư mục báo cáo |
| 9 | backtest_runs | `_cache/backtest` | `backtest` | MỚI so với P9.3 prep: bộ ghi kết quả của phiên alpha đã tạo 2 run ở đây (fallback `_cache/backtest`); đi TRƯỚC edu_results |
| 10 | edu_results | `education/results` | `backtest/education` | |
| 11 | wfa | `_cache/book_wfa` | `wfa` | |
| 12 | funnel / book_runs | `_cache/funnel` , `_cache/book` | `alpha/funnel` , `alpha/book` | funnel 2,8 GB |
| 13 | live | `_cache/live` | `live` | bot đang ghi: rename nguyên tử + symlink `_cache/live -> ../live` |
| 14 | shared_mmap | `_cache/shared` | `cache/shared` | hiện KHÔNG tồn tại -> bỏ qua |
| 15 | qg_* (4 nguồn) | `_cache/quality_gate` + `{okx,binance,binance_hist}/_cache/quality_gate` | `cache/shared/quality_gate` | gộp theo tên sha1; trùng khác nội dung giữ bản mới |
| 16 | **persist_finished** | `_cache/api_jobs/<id>` (đã xong) | `backtest|wfa|alpha/{book,funnel}/<id>` | GỌI `batch.persist_finished_jobs(apply=True)`; xem §3 |
| 17 | process | `_cache/api_jobs` (phần còn lại) | `cache/process` | + symlink `_cache/api_jobs -> ../cache/process` |
| 18 | mem_csv | `_cache/runs` | `cache/process/_mem` | `_mem` không khớp `_JOB_ID_RE` -> prune/persist không đụng (không dùng thư mục theo job: `NORA_MEM_LOG_PATH` do run_limited.sh đặt, không tầm thường) |
| 19 | staging | `nora/data_staging` | `cache/process/_staging` | hiện không tồn tại -> bỏ qua |

Đã loại khỏi kế hoạch (đã xoá 2026-10-07, script không còn mục DECISION / `--include-decisions`): `_cache/{optimize,research,reports,smoke}`, `studio_pipeline.db`, `manifest_backup_*`, `alphas/custom_strategies.json`,
`alphas/portfolio_*`, zip crawler `<repo>/data/cache` (thư mục `<repo>/data/` hiện rỗng). Nếu xuất hiện lại sẽ báo ở "CHƯA ÁNH XẠ". Symlink tương đối ở mọi đường cũ giữ tới P9.10.

### 2. Kết quả `--dry-run --allow-live` (từ `nora/`, qua `run_limited.sh --no-lock`, 1 s, KHÔNG đổi gì)

```
[migrate_data_tree] DRY-RUN  data=/home/vmc03/norabt/nora/data
  guard: live_bot đang chạy=3 ['20261007_185311_92e91d', '20261007_185311_e7db58', '20261007_185311_5387d0']  job khác=0  -> cho phép
key                 state            files       size  src                                          -> dst
okx_cex             todo                80     1.0 GB  nora/data/okx/cex                            -> nora/data/market/okx/cex
okx_dex             todo                18    39.3 MB  nora/data/okx/dex                            -> nora/data/market/okx/dex
binance_cex         todo               120     1.6 GB  nora/data/binance/cex                        -> nora/data/market/binance/cex
binance_hist        todo                70     1.8 GB  nora/data/binance_hist/cex                   -> nora/data/market/binance/cex_ref
meta                todo                 6   184.1 KB  nora/data/_meta                              -> nora/data/market/_meta
alpha_book          todo                 1    65.6 KB  nora/data/alphas/book.json                   -> nora/data/alpha/book.json
alpha_registry      todo                 1    12.7 KB  nora/data/alphas/registry.json               -> nora/data/alpha/registry.json
alpha_presets       todo                 1     8.7 KB  nora/data/alphas/presets.json                -> nora/data/alpha/presets.json
alpha_explore       todo                 1    39.1 KB  nora/data/alphas/explore                     -> nora/data/alpha/explore
alpha_testnet       todo                 2    19.0 KB  nora/data/alphas/testnet                     -> nora/data/alpha/testnet
alpha_user          todo                 0        0 B  nora/data/alphas/user                        -> nora/data/alpha/user
alpha_research      todo                 1    52.2 KB  nora/data/alphas/research                    -> nora/data/alpha/research
edu_samples         todo                 1    64.1 KB  nora/data/education/samples.json             -> nora/data/alpha/education/samples.json
registry_fix        todo                 0        0 B                                               -> 
    registry: nora/data/alphas/registry.json alphas ['trend_long_perp__SOL'] -> []; khoá giữ nguyên=['code', 'gates', 'generated_at', 'pairs_evaluated', 'source_optimization']; source_optimization tồn tại=False; giữ định dạng=True
backtest_runs       todo                 8   112.6 KB  nora/data/_cache/backtest                    -> nora/data/backtest
edu_results         todo                51     8.5 MB  nora/data/education/results                  -> nora/data/backtest/education
wfa                 todo               182    19.9 MB  nora/data/_cache/book_wfa                    -> nora/data/wfa
funnel              todo              4490     2.8 GB  nora/data/_cache/funnel                      -> nora/data/alpha/funnel
book_runs           todo                59    10.5 MB  nora/data/_cache/book                        -> nora/data/alpha/book
live                todo                36     1.0 MB  nora/data/_cache/live                        -> nora/data/live
shared_mmap         src_missing          0        0 B  nora/data/_cache/shared                      -> nora/data/cache/shared
qg_root             todo               110    49.0 KB  nora/data/_cache/quality_gate                -> nora/data/cache/shared/quality_gate
qg_okx              merge_todo          21     9.8 KB  nora/data/okx/_cache/quality_gate            -> nora/data/cache/shared/quality_gate
qg_binance          merge_todo           6     2.8 KB  nora/data/binance/_cache/quality_gate        -> nora/data/cache/shared/quality_gate
qg_binance_hist     merge_todo          30    14.1 KB  nora/data/binance_hist/_cache/quality_gate   -> nora/data/cache/shared/quality_gate
persist_finished    todo                 0        0 B                                               -> 
    persist: root=_cache/api_jobs thư mục process=215 chạm=125
      alpha_revalidate  {'would_clean': 1}  -> ['(dọn, không chép)']
      book_backtest     {'would_persist': 29}  -> ['backtest']
      book_build        {'would_persist': 2}  -> ['alpha/book']
      book_wfa          {'would_persist': 45}  -> ['wfa']
      data_crawl_okx    {'would_clean': 7}  -> ['(dọn, không chép)']
      data_crawl_ticks  {'would_clean': 1}  -> ['(dọn, không chép)']
      data_promote      {'would_clean': 4}  -> ['(dọn, không chép)']
      edu_precompute    {'would_clean': 4}  -> ['(dọn, không chép)']
      funnel_book       {'would_clean': 6}  -> ['(dọn, không chép)']
      funnel_run        {'would_persist': 19}  -> ['alpha/funnel']
      mock_feeds        {'would_clean': 2}  -> ['(dọn, không chép)']
      presets_build     {'would_clean': 4}  -> ['(dọn, không chép)']
      regime_report     {'would_clean': 1}  -> ['(dọn, không chép)']
process             todo               875    25.5 MB  nora/data/_cache/api_jobs                    -> nora/data/cache/process
mem_csv             todo               116     6.6 MB  nora/data/_cache/runs                        -> nora/data/cache/process/_mem
staging             src_missing          0        0 B  nora/data_staging                            -> nora/data/cache/process/_staging
  CHƯA ÁNH XẠ (0): không
  TỔNG cần chuyển: 6286 file, 7.4 GB trong 29 bước; xung đột=0; 0.7s
```
Tổng: 6.286 file / 7,4 GB trong 29 bước, 0 xung đột, 0 chưa ánh xạ. Cùng ổ đĩa (`/dev/mapper/ubuntu--vg-ubuntu--lv`) -> mọi bước là rename nguyên tử. Va chạm tên quality_gate chỉ đo được khi chạy (đích chưa có; cây giả: 16 trùng ở qg_okx).

### 3. `persist_finished_jobs(apply=False)` — 215 thư mục trong `_cache/api_jobs`, chạm 125

| Loại | Hành động | Đích |
|---|---|---|
| book_backtest | persist 29 | `backtest/<id>` |
| book_wfa | persist 45 | `wfa/<id>` |
| funnel_run | persist 19 | `alpha/funnel/<id>` |
| book_build | persist 2 | `alpha/book/<id>` |
| alpha_revalidate 1, data_crawl_okx 7, data_crawl_ticks 1, data_promote 4, edu_precompute 4, funnel_book 6, mock_feeds 2, presets_build 4, regime_report 1 | dọn 30 (rmtree, KHÔNG chép: kết quả bền do chính job ghi) | — |

Còn lại ở `cache/process` (~90): live_bot 31 (3 đang chạy; ADR/`KEEP_KINDS` không đụng), custom_backtest 46 (TTL 24 h riêng), job lỗi/huỷ (log 7 ngày), 1 thư mục không có job.json. Khi chạy thật con số "dọn" nhỏ hơn: `data_promote` gọi `clean_unstaged_crawl_jobs()` xoá trước 6/7 job crawl (cây giả: 119 chạm = 95 chép + 24 dọn). Việc dọn là KHÔNG hoàn tác (đúng luật vòng đời ADR §4.2-3).

### 4. Bước `registry_fix` (tách riêng, cần `--remove-stale-registry`)

`alpha/registry.json` hiện có đúng 1 mục: `alphas = [trend_long_perp__SOL]` -> `alphas = []`. Giữ nguyên khoá `code, gates, generated_at, pairs_evaluated, source_optimization`. Sao lưu byte-nguyên `registry.json.bak` (kèm sha256 trong báo cáo) vào `data/_migration/p9_3c_<UTC>/`. Ghi lại giữ định dạng (`indent=2`, kiểm `json.dumps(load) == nội dung cũ` trước khi ghi; sai định dạng thì dừng, không ghi). Ghi tạm + `os.replace`.
Còn dư sau bước này (cần người quyết, script KHÔNG tự làm): `pairs_evaluated: 1` và `source_optimization` trỏ `…/_cache/optimize/20261001_1440` (đã xoá). `alpha/testnet/_retired/trend_long_perp__SOL.json` (tracked) không đụng. Không code nào đọc `alphas[0]` (chỉ `test_revalidate` trên cây tạm).

### 5. `.gitignore` đề xuất (KHÔNG ghi; `migrate_data_tree.py --print-gitignore` in diff, `--write-gitignore` cùng `--apply` mới ghi)

```diff
--- a/.gitignore
+++ b/.gitignore
@@ -2,10 +2,21 @@
 coins/node_modules
 .idea
 data/
-# Ngoại lệ: nora/data/alphas/ (sổ alpha, registry, testnet) được commit; phần còn lại của nora/data/ vẫn bị bỏ qua
+# Ngoại lệ: nora/data/ chỉ theo dõi phần định nghĩa/cấu hình của nora/data/alpha/ (ADR-P9 §4.7). Không commit: alpha/{user,funnel,book}/, market/, backtest/,
+# wfa/, carlo/, live/, cache/ và symlink tạm ở đường cũ (alphas, _cache, okx, binance, ... nằm dưới nora/data/* nên đã bị chặn)
 !nora/data/
 nora/data/*
-!nora/data/alphas/
+!nora/data/alpha/
+nora/data/alpha/*
+!nora/data/alpha/strategies/
+!nora/data/alpha/education/
+!nora/data/alpha/universes/
+!nora/data/alpha/research/
+!nora/data/alpha/explore/
+!nora/data/alpha/testnet/
+!nora/data/alpha/presets.json
+!nora/data/alpha/registry.json
+!nora/data/alpha/book.json
 # mã nguồn tên "data" (package Python) không phải dữ liệu: luôn theo dõi
 !nora/backend/core/data/
 # Dữ liệu thị trường Nora (hàng trăm MB): staging crawl và bộ dữ liệu cũ dùng làm tham chiếu test
```
Kiểm bằng repo git tạm (`git check-ignore`): TRACKED `alpha/{strategies,education,research,explore,testnet,universes}/…`, `alpha/{presets,registry,book}.json`; IGNORED `alpha/{user,funnel,book}/`, `market/`, `backtest/`, `wfa/`, `carlo/`, `live/`, `cache/`, symlink `alphas`/`_cache`, `_migration/`; `nora/backend/core/data/` vẫn tracked. `alpha/research/` giữ tracked (`top_agents.py` đọc, file hiện đã tracked) — CẦN người dùng xác nhận (dấu "?" trong yêu cầu). Ghi `.gitignore` + `--git-stage` (rm --cached `alphas/*` cũ, add -f `alpha/*`) là một bước sau chuyển, không commit.

### 6. Tiến trình đang giữ file dưới `data/` (quét `/proc/<pid>/{fd,cwd,maps,cmdline,environ}`, chỉ đọc)

| Ai | Giữ | Đường CŨ cần symlink phủ |
|---|---|---|
| 3 bot `live_bot` (`20261007_185311_92e91d` paper/explore/legacy; `…_5387d0` paper/main/legacy; `…_e7db58` demo/main/unified) — mỗi bot 5 pid (run_limited.sh, 2 `bash -c` giám sát RAM, `python -m backend.api.jobs.runner`, `sleep 1`) | fd mở `out.log` (inode giữ nguyên khi rename); `cmdline` + `NORA_JOB_DIR` = `_cache/api_jobs/<id>` | `_cache/api_jobs -> ../cache/process` |
| cùng các pid trên + 1 pytest của phiên khác (pid 3164417, `test_bot_unified …`) | `NORA_MEM_LOG_PATH=_cache/runs/<ts>_mem.csv` (shell giám sát `>>` mỗi giây theo ĐƯỜNG DẪN) | `_cache/runs -> ../cache/process/_mem` |
| bot (trong tiến trình) | `live_dir()` tính theo đường dẫn mỗi lần ghi: `_cache/live/okx_{paper,paper_explore,demo_unified}/{events.jsonl,state.json,paper.pkl,unified.pkl}` | `_cache/live -> ../live` |
| API `uvicorn backend.main:app :18010` (pid 3149672) | không giữ fd/mmap dưới `data/` (đọc theo yêu cầu, cache theo mtime) | — |

Chưa có tiến trình nào mmap file dưới `data/`. Cửa sổ hở của `link_swap` (tạo symlink tạm -> rename thư mục -> rename symlink vào đường cũ) chỉ vài µs; nếu bot gọi `makedirs`/`open` đúng lúc đó, tệ nhất là mất một mẫu RAM hoặc một lần ghi bị lỗi và thử lại ở nhịp sau — script dừng và báo nếu `os.replace` thất bại. Sau khi chuyển, script chụp ảnh trước/sau và kiểm từng bot: còn sống, đường cũ và mới cùng `realpath`, `out.log` cùng inode, có file nào đổi mtime trong `--verify-wait` (mặc định 90 s); mã thoát 1 nếu bot nào không ok. Lưu ý: guard của script chỉ thấy job API đang chạy, KHÔNG thấy pytest của phiên khác (có 1 cái đang chạy lúc dry-run) — chỉ chạy `--apply` khi không có pytest/công cụ nào đang đọc `data/`.

### 7. Việc kiến trúc còn lại TRƯỚC khi chạy thật (store.py / người gọi) — chưa làm

`crawl/store.py` (làn kiến trúc) còn ánh xạ theo kế hoạch cũ; cần đổi cho khớp "cache chỉ có `process/` và `shared/`":
- `_kind_paths["quality_gate"]` -> mới `cache/shared/quality_gate` (đang `cache/quality_gate`); `"staging"` -> `cache/process/_staging` (đang `cache/staging`); `cache_dir(None, <tên lạ>)` / `"cache"` -> không còn `cache/<tên>` (chỉ `process`, `shared`); `cache_crawl_dir()` -> bỏ hoặc `cache/process/_crawl/<sàn>` (zip crawler không thuộc cây; `crawl/cex.py:57,412` vẫn ghi `<repo>/data/cache`); `allowed_roots("quality_gate"|"staging")`; cập nhật `test_data_layout_helpers.py` (74 test).
- Trước khi bật: `book.py:444` dùng `store.is_within(..., "runs")` (bàn giao §3.1) và sửa `api/jobs/batch.py` docstring `data/alphas` (chỉ chữ) — làn alpha.
- `run_limited.sh:18,66-69` ghi `_cache/runs` -> `cache_runs_dir()`/`cache/process/_mem` (symlink đủ dùng cho tới P9.10).
- Dọn `cache/process/_mem` sau 7 ngày: P9.6 (hiện không ai dọn).
- Khoá cache mmap + quality gate băm đường gốc -> đổi MỘT lần khi `market/<sàn>` thành đường chính (dựng lại, không đổi kết quả).

Lệnh chạy thật (chờ duyệt): `PYTHONDONTWRITEBYTECODE=1 ops/run_limited.sh --no-lock -- test/scripts/migrate_data_tree.py --apply --allow-live --remove-stale-registry [--git-stage --write-gitignore]` từ `nora/`.


## P9.3c store fix

`backend/crawl/store.py` khớp ADR-P9 §4 (cache chỉ có `process/` và `shared/`); đã đối chiếu mục "7" của "P9.3c plan" ở trên.

| Helper / kind | Trước | Sau (cũ giữ làm fallback) |
|---|---|---|
| `quality_gate` / `cache_quality_gate_dir()` | `cache/quality_gate` | `cache/shared/quality_gate` (cũ `_cache/quality_gate`) |
| `staging` / `cache_staging_dir()` | `cache/staging` | `cache/process/_staging` (cũ `nora/data_staging`) |
| `mem` / `cache_runs_dir()` | `cache/process/_mem` | không đổi |
| kind `"cache"` | `cache/` | bỏ (`allowed_roots("cache")` -> ValueError) |
| `cache_dir(None, <tên lạ>)`, `cache_dir(None)` | `cache/<tên>` | `cache/process[/<tên>]` (cũ `_cache[/<tên>]`); chữ ký không đổi |
| `cache_crawl_dir()` | `cache/crawl/<sàn>` | BỎ HẲN |
| `binance_hist` (`HISTORICAL_ALIASES`, venue `cex_ref`) | `market/binance/cex_ref` | BỎ (dữ liệu bị xoá, không còn dùng sau khi bỏ xno); `resolve_source("binance_hist")` -> ValueError; `Source.alias` luôn `None` (giữ trường) |

Test: `test_data_layout_helpers.py` đổi đích, thêm `test_cache_has_only_process_and_shared`, `test_binance_hist_alias_removed`; `test_okx_data.py:33` chấp nhận `cache/process` (cây đã chuyển).

**Người gọi `crawl/cex.py`:** KHÔNG dùng `cache_crawl_dir`; `DEFAULT_CACHE_DIR` (`:56`, env `NORA_BINANCE_CACHE_DIR`) và `OKX_DEFAULT_CACHE_DIR` (`:412`, env `NORA_OKX_CACHE_DIR`) vẫn trỏ `<repo>/data/cache/<sàn>` (ngoài `nora/data`) và `fetch_vision_zip`/`fetch_day_zip` makedirs ở đó mỗi lần crawl -> thư mục `data/cache` cấp repo sẽ mọc lại. Đề xuất (chưa làm): mặc định `os.path.join(cache_process_dir(<job_id>), "_crawl", <sàn>)` tính lúc gọi (hoặc `tempfile.mkdtemp`), vì zip tải lại được và job xong thì thư mục process bị dọn.

**Còn lại (làn alpha / script, chưa sửa):** `api/routers/data.py:12` `STAGING` -> `cache_staging_dir()`; `core/backtest/custom_run.py:57,73,405` `XNO_DEFAULT_DATA="binance_hist"` + `DATA_HOME/<name>/cex` phải bỏ; docstring `api/jobs/batch.py` còn chữ `data/alphas`; `run_limited.sh:18,66-69` ghi `_cache/runs`; ADR §4 dòng `cex_ref (← binance_hist)` và đoạn "Bí danh nguồn dữ liệu cũ" cần xoá.

**Script `test/scripts/migrate_data_tree.py` (chưa sửa được, xem tin nhắn bàn giao):** đích đã khớp (`qg_* -> cache/shared/quality_gate`, `staging -> cache/process/_staging`, `mem_csv -> cache/process/_mem`). Cần: bỏ Move `binance_hist` và `qg_binance_hist` + chữ `cex_ref` ở docstring; `registry_fix` xoá HẲN mục `trend_long_perp__SOL` kèm khoá cấp registry `source_optimization`, `pairs_evaluated` (giữ bản sao lưu); `.gitignore` đề xuất đã giữ `!nora/data/alpha/research/`.


## P9.4 part 2 — `core/{indicator, signal}.py` + dựng kế hoạch -> `backtest.py`, hằng số profile -> `params.py` (gộp nguyên văn + shim)

Ngày: 2026-10-07 · Người làm: norabt-99 (kiến trúc, chỉ di chuyển) · Trạng thái: **xong, CHƯA commit, chờ review chéo**. Không đổi logic.

**Phương pháp** như part 1 (script nối nguyên văn thân module, gỡ import nội bộ nhóm kể cả import cục bộ, docstring -> banner). Kiểm AST từng hàm/lớp/hằng cấp module so với `git HEAD`: 238 định danh nguồn; 206 giống hệt, 29 khác đúng bằng dòng import/tên gọi bên dưới (đã xem diff từng cái), 3 không còn tên cũ (`features.evaluate`, `ops.evaluate` đổi tên; `__all__` ở shim). `backtest.py`/`params.py` cũ: chỉ `run_backtest` (một import cục bộ trỏ `signal`) và `_resolve_string` (một import cục bộ trỏ `indicator`) đổi, thêm 8 + 3 định danh mới.

### Bảng ánh xạ cũ -> mới
**core/indicator.py**

- `core/signals/kernels.py`: `BASE_COLUMNS`, `KernelSpec`, `_ewm_sma_seed`, `_tv_ewm`, `_rma`, `_true_range`, `sma`, `ema`, `roc`, `er`, `adx`, `rsi`, `bbz`, `bbm`, `bbu`, `bbl`, `bbw`, `bbwp`, `atr`, `natr`, `rv`, `kcm`, `kcu`, `kcl`, `dch`, `dcl`, `vwap`, `vwapdev`, `volz`, `_w`, `REGISTRY`, `_NUM`, `_COLUMN_RE`, `MAX_PERIOD`, `parse_column`, `_PY_RE`, `PROGRAMS`, `register_program`, `is_program_column`, `_program_of`, `is_kernel_column`, `compute`, `warmup_bars`, `catalog`
- `core/strategy/pydsl/spec.py`: `REQUIRED`, `KINDS`, `Param`, `S`, `B`, `A`, `I`, `F`, `MA`, `Spec`, `FEATURE_SPECS_DATA`, `OP_SPECS_DATA`
- `core/strategy/pydsl/features.py`: `_arr`, `_clean`, `_frame`, `_roll`, `_shift`, `_wma`, `_meandev`, `_linreg`, `f_sma`, `f_ema`, `f_dema`, `f_tema`, `f_wma`, `f_rsi`, `f_atr`, `f_natr`, `f_adx`, `_di`, `f_plus_di`, `f_minus_di`, `f_macd`, `f_bbands`, `f_roc`, `f_rocp`, `f_momentum`, `f_stddev`, `f_var`, `f_cci`, `f_willr`, `f_mfi`, `f_obv`, `f_stoch`, `f_donchian_upper`, `f_donchian_lower`, `f_linearreg_slope`, `f_linearreg`, `f_rolling_mean`, `f_rolling_std`, `f_rolling_max`, `f_rolling_min`, `f_rolling_sum`, `f_zscore`, `f_returns`, `f_log_returns`, `f_trange`, `f_typprice`, `f_ohlc4`, `f_range_pct`, `f_volume_z`, `_TP`, `_HLC`, `_w`, `_sum_w`, `_spec`, `FEATURES`, `evaluate`
- `core/strategy/pydsl/ops.py`: `_num`, `_bool`, `_shift_num`, `_shift_bool`, `_fin`, `_arange_last`, `_above`, `_below`, `o_crossed_above`, `o_crossed_below`, `o_crossed`, `o_crossed_above_value`, `o_crossed_below_value`, `o_current`, `o_shift`, `o_diff`, `o_pct_change`, `o_rising`, `o_falling`, `o_fillna`, `o_ffill`, `_arr_valid`, `o_abs`, `o_clip`, `o_isna`, `o_notna`, `o_isfinite`, `o_zero_ifna`, `o_sign`, `o_replace`, `o_between`, `o_where`, `o_value_when`, `o_bars_since`, `o_hold_for`, `_hold`, `o_and_`, `o_or_`, `o_not_`, `_ret_shift`, `_ret_where`, `_op`, `_PER`, `OPS`, `evaluate`

**core/signal.py**

- `core/strategy/pydsl/errors.py`: `DslError`, `at`, `suggest`
- `core/strategy/pydsl/program.py`: `DATA_COLUMNS`, `TF_MS`, `KINDS`, `_CACHE_SIZE`, `Node`, `Ctx`, `Const`, `BoolConst`, `Data`, `_as_float`, `Bin`, `Neg`, `Cmp`, `Logic`, `Inv`, `Call`, `Pick`, `_in_ranges`, `Program`
- `core/strategy/pydsl/parser.py`: `DSL_VERSION`, `MAX_CODE_CHARS`, `MAX_NODES`, `BASE_CLASS`, `DATA_ATTRS`, `TIMEFRAME_ALIASES`, `SPECIAL_ATTRS`, `_CMP`, `_ARITH`, `_METHODS`, `_NOT_SUPPORTED_STMT`, `_position_attr_names`, `_strip_docstrings`, `code_hash`, `TupleVal`, `_Compiler`, `compile_program`
- `core/strategy/pydsl/explain.py`: `DATA_VI`, `_clean_num`, `_format_feat_call`, `expr_to_vi`, `_find_calls`, `_has_event_trigger`, `explain_program`
- `core/signals/evaluator.py`: `lag_key`, `LogicEvaluator`, `VectorEvaluator`
- `core/signals/snapshot.py`: `MINUTE`, `DEFAULT_LOOKBACK_MIN`, `_label`, `_num`, `_explain`, `_since`, `signal_snapshot`, `book_strategies`
- `core/signals/diagnostics.py`: `HORIZONS_MIN`, `MIN_EVENTS`, `_thin`, `_forward_bps`, `_stats`, `_verdict`, `check_signals`
- `core/strategy/pydsl/__init__.py`: `compile_code`, `compile_report`, `explain_report`

**core/backtest.py (thêm ở cuối)**

- `core/strategy/pydsl/profiles.py`: `Plan`, `base_name`, `_ref`, `_tree`, `_leg_signals`, `leg_level`, `build_plan`, `_check_position`

**core/params.py (thêm ở cuối)**: `FRAME_ORDER`, `RUN_FRAME`, `NORA_DEFAULTS` từ `pydsl/profiles.py`. `FRAMES` của profiles trùng giá trị với `FRAMES` đã có ở khối template -> dùng chung, không khai báo lại.

### Shim
- Alias `sys.modules` (cùng một đối tượng module; `kernels.PROGRAMS`/`REGISTRY` chỉ một bản nên `register_program` / cột `py_` của làn alpha chạy y nguyên): `core/signals/kernels`, `core/strategy/pydsl/spec` -> `core.indicator`; `core/signals/{evaluator,snapshot,diagnostics}`, `core/strategy/pydsl/{errors,program,parser,explain}` -> `core.signal`.
- Shim tái xuất (không alias được): `pydsl/features.py`, `pydsl/ops.py` (hai hàm `evaluate` trùng tên -> trong module gộp là `evaluate_feature` / `evaluate_op`; shim đặt `features.evaluate`/`ops.evaluate` đúng như cũ, mọi tên khác copy từ module gộp); `pydsl/profiles.py` (hằng số từ `params`; `Plan, build_plan, base_name, leg_level, _ref, _tree, _leg_signals, _check_position` nạp LƯỜI từ `core.backtest` qua `__getattr__` để import hằng số/FRAMES không kéo engine numba); `pydsl/__init__.py` (tái xuất `compile_code, compile_report, explain_program, explain_report, DslError, Program` từ `core.signal`).
- Không cần stub gói: `core/signal.py` vs `core/signals/` và `core/indicator.py` không trùng tên; `core/signals/__init__.py` giữ nguyên (docstring), `core/strategy/pydsl/` vẫn là gói thật chứa các shim.
- Importer cập nhật dòng import: `core/backtest.py` (evaluator, kernels -> `indicator as kernels`, `Program`), `core/params.py` (kernels cục bộ). Importer khác (alpha: custom_run, tick_run, edu_precompute, user_alphas, diagnose, strategy_doc, routers, batch; live/signals; data/shared; test) vẫn dùng đường cũ qua shim. `optimize/store.py` `_CODE_FILES`: `signals/{evaluator,kernels}.py` -> `core/{signal,indicator}.py` (khoá `--resume` đổi một lần). `utils/engine_version.py` không đổi (kernels trước đây không nằm trong hash engine).
- `test_layering.py`: thêm 2 dòng `LAYER_RULES` (`core/indicator`, `core/signal`).

### Đổi tên / chu trình đã xử lý (cơ học)
1. Trùng tên trong module gộp: `kernels._w` -> `_kw` (cùng 23 chỗ gọi trong REGISTRY; `features._w` giữ); `features.evaluate` -> `evaluate_feature`, `ops.evaluate` -> `evaluate_op` (program.py gọi `evaluate_feature`); wrapper `pydsl.explain_program` (import lười tới `explain.explain_program`, cùng chữ ký) bỏ — dùng chính `explain_program`.
2. `K.xxx` trong features (27 chỗ) -> tên trần `xxx` (kernels cùng file; đã kiểm không trùng tên cục bộ/cấp module).
3. **indicator -> signal** (features/ops import `spec`; chỉ báo đứng TRƯỚC signal): `spec.py` đặt vào `indicator.py` (không vào `signal.py` như bảng ADR §3) — `signal` import ngược từ `indicator` (`FEATURES, OPS, REQUIRED, Spec, evaluate_feature, register_program`). Vi phạm `indicator -> signal` 4 -> 0. **Cần ADR sửa dòng bảng: `spec` thuộc indicator.**
4. **profiles -> params/backtest** như đã thoả thuận với phiên alpha: `signal.py` không import `backtest.py` ở đầu file; `explain` lấy `NORA_DEFAULTS` từ `params`.
5. Còn lại (có từ trước, KHÔNG sửa được cơ học — cần quyết định): `signal.py` import CỤC BỘ trong hàm `backtest` (`snapshot.signal_snapshot` -> `PortfolioEngine`, `diagnostics.check_signals` -> `BacktestEngine`: 2 vi phạm "signal -> backtest"), `core.params.presets` (snapshot, optimize), `regime.classifier` (snapshot), `db.local_pkl` (diagnostics đọc manifest, core đọc file); `params.py:244` -> `indicator` (template kiểm cột sig.*; 1 vi phạm "params -> indicator"). Hướng sửa gợi ý (không làm ở bước này): chuyển `snapshot`/`diagnostics` lên tầng trên backtest (verdict/live) hoặc truyền engine/manifest qua tham số.

### Numba cache
`cache=True` giữ nguyên. Cache `kernels`/`features` nay ở `core/__pycache__/indicator.*.nbi`; `backtest.py` bị sửa (thêm cuối file) -> chỉ mục cache của `core/__pycache__/backtest.*.nbi` hết hiệu lực, lần chạy đầu biên dịch lại (~90 s). File `.nbi/.nbc` cũ ở `core/signals/__pycache__`, `core/strategy/pydsl/__pycache__` mồ côi.

### Layering (`test_layering`, tính trực tiếp, không ghi báo cáo)
Trước: 62 vi phạm (146 module, 25 shim). Sau: **57** (148 module, 38 shim): `indicator -> signal` 4 -> 0, `signal -> backtest` 3 -> 2; mọi cạnh khác giữ nguyên.

### Cổng
| | Kết quả |
|---|---|
| BASELINE (HEAD, trước khi sửa; 24 file, `NORA_GOLDEN_DATA_ROOT=data/binance`) | **389 passed**, 0 failed, 2 warnings (615 s) |
| SAU | **389 passed**, 0 failed, 2 warnings (817 s; lần đầu biên dịch lại cache numba của backtest.py/indicator.py) — golden, kernel_parity, portfolio_engine, causal_engine, signals_strategies, signal_snapshot, signal_explain, regime, pydsl_*, custom_backtest, edu_*, user_alphas, strategy_doc, live_bot, bot_unified, layering, ops_units, shared_data, funnel đều xanh |
| nautilus_diff S1-S3 aligned | `run_nora.py ohlc` + `adaptive` rồi `compare.py fine` / `fine _adaptive`: 36 file `out/nora_*.json` + `results_fine*.json` **giống từng byte** trước/sau (so với bản sao `out/` chụp trước khi chạy); tracker==manager 18/18 mỗi lượt; `results_fine*.json` đã commit không đổi. Lưu ý: một phiên khác chạy `ext_run_nora`/`ext_compare` cùng lúc trong `out/` nên có lần so lệch tạm thời; đo lại khi nó dừng. `ext_results_{ohlc,adaptive}.json` (S4-S8, đã commit) bị phiên kia ghi đè và khác bản commit (equity khớp Nautilus hơn) — không thuộc cổng này, không do bước này (không đổi logic; nhiều khả năng bản commit cũ hơn thay đổi sizing ở commit 58149ed) |
| Tốc độ (`bench_engine.py compare --n 3 --batch 100 --old-batch 0`, cache nóng) | sau: 1,090 s/alpha riêng (load 0,721 + kernel 0,344), 158 ms/alpha lô 100; part 1 (trước): 1,097-1,113 s, 159-162 ms. Không chậm |
| Pickle | 12 bản sao `paper.pkl`/`unified.pkl` (6 hiện hành + 6 archive) nạp được hết; không có tên nào thuộc `signals.*`/`pydsl.*` (bản lưu không chứa lớp DSL/kernel) nên shim không cần cho pickle trạng thái bot. `pickle.loads(pickle.dumps(f)) is f` cho `run_backtest`, `build_plan`, `compile_code`; hàm tên cũ phân giải qua alias |
| test_layering | trước 62 (146 module, 25 shim) -> sau **57** (148 module, 38 shim): `indicator -> signal` 4 -> 0, `signal -> backtest` 3 -> 2 |

**Vi phạm đã biết, CHỦ ĐỘNG để nguyên (quyết định điều phối 2026-10-07):** (a) `snapshot.signal_snapshot` / `diagnostics.check_signals` import cục bộ `backtest`, `params.presets`, `regime.classifier`, `db.local_pkl` — có I/O, sẽ ra khỏi core sang optimize ở P9.6; (b) `params.py:244` import cục bộ `indicator` (kiểm cột `sig.*` trong template) — để tới P9.10; (c) `spec.py` nằm trong `indicator.py` được chấp nhận, ADR §3 sẽ sửa dòng bảng.

---

## P9.6 plan — `optimize/` (search, funnel, book, process) — norabt-99 (kiến trúc, chỉ di chuyển/gộp), 2026-10-08
Trạng thái: **CHỈ KẾ HOẠCH, chưa sửa code**. Đọc: ADR §2–§5, optimize/**, api/jobs/{batch,runner}, utils/{jobs,parallel,memwatch,engine_version}, mọi module trong `batch.KINDS`, core/params/{presets,modes}, api/modes.

### 0. Phát hiện quyết định thiết kế
1. **Bản ghi job cũ KHÔNG lưu tên module.** `params.json` = `{kind, params}`, `job.json` có `kind`; runner tra `KINDS[kind]` lúc chạy. Không dữ liệu (`data/**`) nào chứa `backend.optimize.*`. => tương thích chỉ cần ở CODE (shim), không cần di trú bản ghi. Cách làm: `KINDS[kind] = {"module","func"(mặc định "run_job"),"params"}`; runner `getattr(import_module(module), func)`.
2. **Đường dẫn tính từ `__file__` đổi độ sâu khi dời file** (sai là lặng lẽ): `batch.NORA_DIR/RUN_LIMITED` (3 cấp), `book.NORA_ROOT` (2), `store.code_version` root (2) **-> sai thì băm "missing" => khoá job đổi => `--resume` mất kết quả**, `engine_version.NORA_DIR` (2), `presets.NORA_DIR` (3), `orchestrator.funnel_root/git_info` + `promote` repo (3). Cổng: `code_version()` và `engine_version()` bằng nhau từng ký tự trước/sau.
3. **Trùng tên khi gộp** (chỉ gộp hằng số khi AST giống hệt): `DEFAULTS` (book, run, funnel/run, publish, revalidate, wfa/run, regime/report, custom, edu) -> `<TASK>_DEFAULTS`; `run_job` x10 -> `run_<kind>`; `DB_NAME` (cùng "results.sqlite", gộp 1), `_SCHEMA`/`_dumps` (store vs funnel/storage) -> `_RESULTS_*` / `_RUN_*`; `make_engine` (core/backtest/run.py nhận `BacktestJob`) vs `funnel/evaluate.make_engine(dict)` -> hàm của phễu đổi `make_engine_from_dict`; `DAY/WARMUP/NORA_ROOT/NORA_DIR/_ts` trùng giá trị -> 1 bản; `alphas_dir` (presets: env NORA_ALPHAS_DIR) KHÁC `revalidate.alphas_dir` (alpha_dir) -> đặt ở hai file khác nhau, KHÔNG gộp; hàm `wfa` của revalidate -> `wfa_check` (tránh che package wfa).
4. **Layering thật:** `core/params/modes` bị `optimize/funnel/generate`, `live/bot`, `core/backtest/run` (qua make_engine) import => nếu dời cả file sang `routes/modes.py` (ADR) thì tầng dưới import tầng trên. **Đề xuất tách:** nhóm dùng cho engine/phễu (`FieldError, check_value, validate_params, schema_space, SCHEMA_SPACE_EXCLUDE, frame_keys, lift_frame, lift_frames, _num, _unit`) -> `optimize/book/build.py` (P9.6b); nhóm chỉ routes dùng (`MODES, MAX_STRATEGIES, DEFAULT_TRAIN/TEST_DAYS, STANDARD_MC*, STRESS_*, job_params, common_risk, mc_standard`) ở lại `core/params/modes.py` -> `routes/modes.py` (P9.8) cùng `api/modes.py`. **Cần review ADR §3 dòng modes.**
5. **`core/backtest/run.py` là hai thứ**: thư viện (BacktestJob, make_engine, run, result_payload, load_items, downsample, daily_nav, hằng số — wfa.py, shared, book, evaluate, regime/report, revalidate, publish, tick_run, router market import) + `run_job`. Thư viện -> `search/evaluate.py`; `run_job` -> `process/tasks.py`. `wfa/wfa.py -> optimize` là vi phạm đã có (qua shared/store/run), giữ qua shim tới P9.10.
6. `data_promote`/crawl: `run_job` đã nằm ở `crawl/{cex,dex,store}.py` (P9.2). Dòng ADR "tasks.py <- core/data/promote" lỗi thời: **không dời**, KINDS giữ đường shim (đổi sang `crawl.*` ở P9.10).
7. **ADR bỏ sót**: `optimize/funnel/estimate.py` -> stages.py; `utils/engine_version.py` -> book/registry.py (chỉ registry + routers/book dùng); `utils/{lru,jsonsafe}` đã sang crawl/store (P9.2).

### 1. Bản đồ cũ -> mới (mỗi dòng: file cũ => đích; ký hiệu cấp module nêu khi tách/đổi tên; còn lại chuyển nguyên văn)
**search/generate.py** (193) <= `funnel/generate.py` toàn bộ (canonical_params, alpha_id_of, grid_size, iter_params, SIGNAL_POSITION_KEYS, PER_SIGNAL, iter_params_factored, count_params, SPACE_MODES, space_for, incompatible, REGIME_KEY, REGIME_MODES, regime_variants, split_regime, validate_alpha).
**search/evaluate.py** (~900) <= `funnel/evaluate.py` (DAY, risk_dict, to_job, learned_regime, make_engine->`make_engine_from_dict`, _outputs, run_backtest, signal_key, run_backtest_many, base_job, _mc_kwargs, _gate_of, mc_check, mc_detail, fold_job_plan, run_wfa, aggregate_wfa, w_backtest, w_backtest_group, w_backtest_group_rss, w_wfa, w_mc, w_sizing, w_holdout) + `optimize/shared.py` (STORE_DIRS, release_memory, export_job, SharedExporter) + thư viện của `core/backtest/run.py` (NORA_ROOT, DAY, WARMUP, MAX_CURVE_POINTS, DEFAULT_CAPITAL, _ts, _mid_params, load_items, downsample, daily_nav, result_payload, BacktestJob, make_engine, run). `DEFAULTS` + `run_job` của run.py => tasks.py.
**funnel/stages.py** (~1660) <= `orchestrator` (PER_WORKER_MB, GEN_BATCH, PAGE, S2_CHUNK, FLUSH_*, MAX_ALPHAS_DEFAULT, FunnelConfig, new_run_id, funnel_root, git_info, _candidates, planned_alphas, Ctx, _stream, GROUP_*, _stream_grouped, _fmt_eta, _pages, _scalar_base, check_timeframe, stage_s0..s6/final, _s2_strategy_level, _neighbour_ratios, _series_of, _export_wfa_windows, _page_chunks, _with_series, _turnover_of, _shock_of, STAGE_FUNCS, run_funnel, _log_stage) + `gates` (STAGES..S6_*, REASON_LABELS, reason_label, _fmt, _msg, Verdict, _OK, evaluate_s1/s2/s3/s6, dsr_cut, evaluate_mc_checks, thresholds_snapshot, _ms, iso_date, compute_windows, windows_iso, wfa_folds) + `sizing` + `stats` + `estimate` + `promote` + `publish` (DEFAULTS->`FUNNEL_BOOK_DEFAULTS`, _metrics, build_report, run_job->`run_funnel_book`) + `recompute` (cache_path, read_cached, recompute_s1, run_job->`run_funnel_recompute`) + `run` (DEFAULTS->`FUNNEL_RUN_DEFAULTS`, run_job->`run_funnel_run`). Hằng `DAY` của gates dùng chung.
**funnel/storage.py** (~830) <= `funnel/storage.py` (DB_NAME, TRADE_COLS/SCHEMA, DAILY_SCHEMA, FLAT_KEYS, StageResult, _clean, _num, flat_columns, atomic_write_json, RunStore; _SCHEMA->`_RUN_SCHEMA`, _dumps->`_run_dumps`) + `optimize/store.py` (COMMIT_*, SCHEMA_VERSION, _SCHEMA->`_RESULTS_SCHEMA`, _CODE_FILES, _CODE_VERSION, canonical, code_version, data_fingerprint, make_job_key, _dumps->`_results_dumps`, ResultsStore, normalize, stream_stage).
**book/build.py** (~1250) <= `optimize/book.py` (toàn bộ; NORA_ROOT->dùng chung NORA_DIR; DEFAULTS->`BOOK_BUILD_DEFAULTS`; run_job->`run_book_build`; run_book, windows, config_count/iter_configs/configs, score, TopK, `_pool_map_safe`/`_auto_workers` alias GIỮ — test_memory_guards patch) + `core/params/presets.py` (toàn bộ; `run_job`->`run_presets_build`; import `antiluck.neighbours` -> `backend.verdict.verdict`) + nhóm modes mục 0.4.
**book/registry.py** (~490, +2 file của làn alpha sau) <= `optimize/registry.py` (TESTNET, build_registry, testnet_config, build_book, testnet_book_config, write_book, EXPLORE_STATUS, write_explore_book, publish_book) + `optimize/revalidate.py` (alphas_dir, load_alpha, alpha_strategy, _run, _oos, wfa->`wfa_check`, revalidate, apply_result, run_job->`run_alpha_revalidate`) + `utils/engine_version.py` (cả file; NORA_DIR sâu +1). Sau khi phiên alpha OK: `core/analytics/{user_alphas,strategy_doc}`.
**process/process.py** (~1200 tạm, ~700 sau P9.8) <= `api/jobs/batch.py` (mục 2) + `utils/jobs.py` (WRITE_EVERY_S, Progress, graceful_sigterm, write_job_result, options, as_list) + thân `runner.run` => `run_job_dir(job_dir)`.
**process/workers.py** (~395) <= `utils/parallel.py` (_abort_pool, pool_map_safe, pool_imap_bounded, auto_workers, default_workers, resolve_workers) + `utils/memwatch.py` (toàn bộ). Bỏ import lười `from backend.utils.memwatch import ...` thành gọi trực tiếp (cùng module global => `monkeypatch.setattr(memwatch, ...)` vẫn có hiệu lực vì cả hai đường cũ là alias CÙNG module).
**process/tasks.py** (~900) <= `core/backtest/run.py` (DEFAULTS->`BOOK_BACKTEST_DEFAULTS`, run_job->`run_book_backtest`) + `wfa/run.py` (toàn bộ; DEFAULTS->`BOOK_WFA_DEFAULTS`, run_job->`run_book_wfa`) + `core/regime/report.py` (toàn bộ, run_job->`run_regime_report`). Hoãn (xem mục 5): `custom_run`, `edu_precompute` (phiên alpha), `tick_run` (phiên logic T6; không có run_job, chỉ là thư viện tick).
**Shim**: mọi đường cũ = ALIAS `sys.modules` (cùng đối tượng, giữ monkeypatch/trạng thái): `optimize.{book,registry,revalidate,shared,store}`, `optimize.funnel.{storage,stats,...}` -> đích; `utils.{jobs,parallel,memwatch,engine_version}`; `api.jobs.batch` -> process (xem mục 2); `core.params.presets`. **Re-export tường minh (không alias được)**: `funnel/evaluate` (đổi tên make_engine), `core/backtest/run` (module tách đôi: thư viện từ search.evaluate, `run_job` từ tasks), `core/params/modes` (giữ phần routes, re-export nhóm đã dời). Mỗi shim có dòng `# P9-SHIM`. `funnel/antiluck.py` (shim P9.5) giữ nguyên.
Presets -> `book/build.py` (đúng ADR). Modes -> tách đôi như 0.4 (phần routes -> `routes/modes.py` ở P9.8).

### 2. `api/jobs/batch.py`: logic tiến trình vs kiểm tham số
**Logic tiến trình -> process.py:** `JobBusy`, `NORA_DIR, RUN_LIMITED, RUNNER, KINDS(module/func + whitelist khoá), NO_LOCK_KINDS, MAX_ACTIVE, LOG_TAIL_LINES, WAITING_MARK, _JOB_ID_RE, _EXIT_RE, _LOCK`; đường dẫn: `jobs_root, RESULT_KINDS, _persisted_dirs, job_dir, _job_dir`; `_check_params` (so whitelist KINDS; launch/run_sync gọi); meta: `_read_meta, _write_meta, _finish, _waiter, _active_count, _env, _alive, _tail_text, _read_progress`; dọn: `CRAWL_KINDS, STAGING_SUBDIR, FAILED_LOG_KEEP_DAYS, _prune_failed, prune_failed_crawl_jobs, prune_failed_jobs, KEEP_KINDS, clean_unstaged_crawl_jobs, _crawl_staged`; lưu kết quả: `PERSIST_AREAS, PERSIST_FILES, persist_dest_base, _same_result, persist_job, _persist_quietly, persist_finished_jobs`; chạy/huỷ/trạng thái: `launch, run_sync, cancel, status, status_etag, status_lite, _summary, TERMINAL_STATES, _SUMMARY_CACHE(+_MAX,_LOCK), _sig, _clone, _summary_cached, _history_dirs, list_jobs, job_label, _names`. (Khôi phục: `_finish` mất-dấu sau restart API + huỷ SIGTERM+flush; "resume" là tham số `resume` của run_job/ResultsStore -> nằm ở book/build + funnel/stages + wfa tasks, KHÔNG thuộc process.)
**Kiểm tham số -> routes/jobs.py (P9.8):** `JobError` (dùng ở cả hai: đặt ở process, routes import), `http_launch` (HTTPException), `_DATE_RE, check_date, check_symbols, check_backtest_symbols, _day_ms, check_dex_backtest, check_candidate_ids, check_number, check_report_dir, check_wfa_strategies, RUN_TIMEFRAMES, check_timeframe, build_job, MAX_CUSTOM_DAYS, MAX_CUSTOM_SYMBOLS, _BASE_RE, build_custom_backtest, build_edu_precompute, MAX_BUILD_CONFIGS, MAX_WFA_STRATEGIES, MAX_WFA_CONFIGS`.
**Thực hiện ở P9.6:** `batch.py` -> process.py **nguyên file** (khối kiểm tham số giữ nguyên, có banner `# --- P9.8 -> routes/jobs.py ---`), `api.jobs.batch` = alias. Lý do: test patch trạng thái nội bộ qua module batch (`batch.NORA_DIR`, `MAX_ACTIVE`, `_tail_text`, `subprocess.Popen`, `status`, `launch`) — tách ngay thì patch không tới hàm bên process => phải sửa test. P9.8 cắt khối kiểm tham số nguyên văn. `runner.py` GIỮ làm điểm vào `-m backend.api.jobs.runner` (tiền đề env OMP/NORA_*_CACHE_MB phải đứng trước import numpy, không thể gộp vào module mà API cũng import) — chỉ gọi `process.run_job_dir`; đổi `RUNNER` ở P9.10 (test/job_modules.launched khẳng định chuỗi cũ).

### 3. KINDS sau khi dời (module:func) và tương thích
| kind | sau P9.6 |
|---|---|
| book_backtest / book_wfa / regime_report | `backend.optimize.process.tasks:run_book_backtest / run_book_wfa / run_regime_report` |
| book_build / presets_build | `backend.optimize.book.build:run_book_build / run_presets_build` |
| funnel_run / funnel_book / funnel_recompute | `backend.optimize.funnel.stages:run_funnel_run / run_funnel_book / run_funnel_recompute` |
| alpha_revalidate | `backend.optimize.book.registry:run_alpha_revalidate` |
| custom_backtest, edu_precompute | GIỮ `core.backtest.{custom_run,edu_precompute}` tới khi phiên alpha OK (sau đó `tasks:run_custom_backtest/run_edu_precompute`) |
| data_crawl, data_crawl_okx, data_crawl_ticks, data_promote | giữ đường shim P9.2 (`core.data.*` -> `crawl.*`), đổi ở P9.10 |
| live_bot | `backend.live.bot` (P9.7) |
Tương thích: (a) bản ghi cũ chạy lại/hiển thị không đổi vì chỉ có `kind`; (b) mỗi module cũ vẫn có `run_job` (shim trỏ hàm mới) cho ai còn tra `KINDS[k]["module"]` — 2 chỗ test khẳng định chuỗi cũ (`test_funnel.py:605`, `test_edu_precompute.py:44`) sửa cùng commit (edu giữ nguyên); (c) job ĐANG chạy lúc đổi mã giữ mã cũ trong bộ nhớ (tiến trình riêng) — chỉ job MỚI nạp đường mới; không cần hoãn deploy nhưng restart `nora-api` sau khi cổng xanh; (d) `ENGINE`/job-key: không file nào trong `_CODE_FILES` bị sửa nội dung => khoá resume không đổi (ngoài một lần do P9.5).

### 4. Hàm worker pickle qua `pool_map_safe`/`pool_imap_bounded`
Pickle theo `module.qualname` của hàm: `optimize.book.run_book` (-> `book.build.run_book`), `optimize.shared.export_job` (-> `search.evaluate`), `funnel.evaluate.w_backtest|w_backtest_group|w_backtest_group_rss|w_wfa|w_mc|w_sizing|w_holdout` (-> `search.evaluate`), `wfa.wfa.run_job` (worker của wfa, KHÔNG phải run_job của job; P9.5 đã dời, đổi tên không thuộc P9.6), initializer `memwatch.worker_init` (-> `process.workers`), tham số `BacktestJob` (NamedTuple, `core.backtest.run` -> `search.evaluate`).
Rủi ro: (1) Python 3.11 + Linux = `fork`: worker thừa hưởng `sys.modules` nên import đường cũ/mới đều ổn; hàm định nghĩa ở file mới có `__module__` là đường MỚI (alias không đổi điều đó) -> pickle dùng đường mới. (2) Không có pickle lưu đĩa trong optimize/utils/api (ResultsStore = JSON/SQLite; `paper.pkl/unified.pkl` thuộc live, không đụng) => không có "pickle mồ côi". (3) Hỏng thật chỉ khi hàm bị đổi tên/hoặc đứng sau `if` mà module nạp riêng (test `job_path` nạp bản riêng từ file: đã tự gán `sys.modules[name]`) hoặc bối cảnh `spawn` (import module mới trong interpreter sạch, lộ phụ thuộc vòng). (4) Đổi tên chỉ ở `run_job` của job (không phải worker) nên không dính pickle.
Giảm thiểu: thêm test mới (một lần) cho mọi worker ở trên: `pickle.loads(pickle.dumps(f)) is f`, `f.__module__` bắt đầu bằng đường mới, và một vòng `ProcessPoolExecutor(mp_context=spawn)` chạy hàm bình thường; giữ nguyên chữ ký/tên các `w_*`; `test_memory_guards` (worker bị kill, chạy lại phần còn thiếu) + `test_scale_pipeline` (SIGTERM cha giết worker) là cổng.

### 5. File đang bị phiên khác sửa — loại trừ hoặc xếp thứ tự (`git status` 2026-10-08)
- **Phiên logic (P9.4b T6)**: `core/backtest.py`, `core/backtest/tick_run.py`, `core/execute/{amm,tracker}.py`, `test/reference_engine.py`, `test/scripts/bench_engine.py`, `test/scripts/okx_top10/{implied,load,run_oos}.py`, `test/test_amm_*.py`, docs `p6_execution_design/p9_4b_single_engine/epics`; cấm đụng cả `core/params.py`, `core/execute/*`, `live/*`. P9.6 KHÔNG sửa các file này (tick_run ở nguyên chỗ; `run.py` thư viện vẫn export `result_payload` qua shim cho tick_run). Va chạm duy nhất: T6 xoá `core/execute/tracker.py` => phải sửa `_CODE_FILES` (`optimize/store.py`) và `ENGINE_DIRS` (`utils/engine_version.py`); xếp: T6 commit TRƯỚC P9.6a (store/engine_version dời), hoặc T6 gửi thay đổi dạng "xoá 1 dòng" để P9.6 áp vào file đích.
- **P9.5 (đang chưa commit)**: `carlo/*, metrics/*, regime/*, verdict/*, wfa/{wfa,walk_forward}.py, core/{analytics/{dashboard,insights,signal_explain},metrics/*,regime/{classifier,learn}}.py, optimize/funnel/antiluck.py, optimize/store.py, test/test_layering.py, docs/bmad/p9_layering_report.md`.
- **Không liên quan, không đụng, không `git add -A`**: `DATA_SYNC_SIGNAL.md` (x3), `none/`, `SETUP.md`/`fintech-guide.html`/`okx*.html` (xoá), `utils/ops/{deploy_nginx.sh,nginx/}`, `test/scripts/migrate_data_tree.py`, `nautilus_diff/out/`.
- **Phiên alpha (ADR: chờ 4 commit + đồng ý)**: `core/backtest/{custom_run,edu_precompute}.py`, `core/analytics/{user_alphas,strategy_doc}.py`, pydsl, `diagnose*`, routers custom/education/strategies/alphas, `batch.build_custom_backtest/build_edu_precompute` (nằm trong khối kiểm tham số -> chuyển nguyên khối nên không sửa logic, nhưng báo trước).

### 6. Xung đột với P9.5 và thứ tự
P9.6 sửa/dời: `optimize/store.py` (P9.5 đã sửa `_CODE_FILES`), `test_layering.py` (thêm luật), `p9_layering_report.md`; các file P9.5 đã chạm chỉ qua import. **Bắt đầu P9.6a SAU khi P9.5 commit** (và T6 nếu đụng store/engine_version). Sau commit P9.5: `presets` import `antiluck.neighbours` -> `backend.verdict.verdict`; `wfa/wfa.py` đang import `optimize.shared/store` + `core.backtest.run` -> vẫn chạy qua alias (không sửa wfa.py ở P9.6). `funnel/antiluck.py` KHÔNG gộp vào stages (shim của verdict, gỡ ở P9.10). Phần "snapshot/diagnostics ra khỏi core sang optimize" nêu ở P9.4 part 2 cần sửa `core/signal.py` (phiên alpha) => **không làm ở P9.6**, để P9.10 hoặc khi phiên alpha OK.

### 7. Các bước con và cổng
Mọi bước: dời bằng script nối nguyên văn (như P9.4), kiểm AST từng định danh cũ vs đích (chỉ khác import/tên đổi ở mục 0.3), shim `# P9-SHIM`, bảng ánh xạ + kết quả cổng gửi phiên logic/alpha trước commit. Chạy qua `ops/run_limited.sh`, venv `~/.venvs/nora`.
- **P9.6a** `funnel/storage.py` (trước, lá) -> `search/{generate,evaluate}.py` -> `funnel/stages.py`. Cổng: test_funnel, test_scale_pipeline, test_web_perf_cache, test_dca_gate, test_run_modes, test_metrics, test_revalidate, test_ops_units, test_strategy_book, test_optimization_plumbing, test_wfa_mc, test_portfolio_wfa, test_parallel, test_memory_guards; `code_version()` trước = sau; golden `NORA_GOLDEN_DATA_ROOT=data/binance` bit-identical; test pickle worker mới (mục 4).
- **P9.6b** `book/{build,registry}.py` (+presets, nhóm modes, revalidate, engine_version). Cổng: test_book_api, test_book_mc_api, test_book_ui_backend, test_strategy_book, test_run_modes, test_revalidate, test_user_alphas, test_memory_guards (alias `_pool_map_safe`/`_auto_workers`), test_optimization_plumbing; `engine_version()` trước = sau; sổ dựng nhỏ (`book_build` n nhỏ) cho `results.sqlite` + `book.json` giống byte với HEAD; `--resume` sau SIGTERM ra cùng kết quả.
- **P9.6c** `process/{process,workers}.py` (batch + jobs + parallel + memwatch + runner.run_job_dir + KINDS module:func). Cổng: test_job_lifecycle (persist/cleanup/idempotent/rename-chết giữa chừng), test_book_api (launch/cancel/FakePopen), test_funnel (launch + KINDS), test_scale_pipeline (Progress, graceful_sigterm), test_parallel, test_memory_guards, test_ticks, test_custom_backtest, test_edu_precompute, test_web_perf_cache, test_data_paths_p93b; kiểm tay: POST backtest -> queued -> running -> done -> kết quả sang `data/backtest/<id>` và `cache/process/<id>` bị dọn; huỷ 1 job funnel rồi resume; job lỗi giữ log. Thêm (logic MỚI duy nhất, ADR §4): dọn `cache/process/_mem` > 7 ngày (hiện không ai dọn) + test.
- **P9.6d** `process/tasks.py` (run.py `run_job`, wfa/run, regime/report) + tách `core/backtest/run.py` thành shim re-export + cập nhật `LAYER_RULES` + `test/job_modules.py` (JOB_FILES trỏ file mới). Cổng: test_run_book_backtest, test_wfa_mc, test_portfolio_wfa, test_tick_backtest, test_golden_results (bit-identical), test_layering (số vi phạm không tăng so với baseline sau P9.5), nautilus_diff S1–S8 không đổi, test_pydsl_*/test_xno*/test_diagnostics_*/test_edu_*/lint_edu_samples (cổng alpha). Cuối P9.6 chạy MỘT full suite.
- **P9.6e (hoãn, theo phiên khác)**: `custom_run`, `edu_precompute` -> tasks.py khi phiên alpha OK; `tick_run` sau commit T6.

## P9.5 — `metrics/`, `regime/`, `wfa/`, `carlo/`, `verdict/` (gộp nguyên văn + shim)

Ngày: 2026-10-08 · Người làm: kiến trúc (chỉ di chuyển) · Trạng thái: **xong, CHƯA commit, chờ review chéo**. Không đổi logic. Không đụng `core/backtest.py`, `core/params.py`, `live/*`, `core/execute/*`, `api/*`.

**Phương pháp** như P9.4 (nối nguyên văn thân module, gỡ import nội bộ nhóm kể cả import cục bộ, docstring -> banner; import ngoài nhóm trỏ sang module mới). Kiểm AST từng hàm/lớp/hằng cấp module so với `git HEAD`: **250 định danh, 237 giống hệt, 13 khác đúng bằng dòng import (đã so lại sau khi bỏ import: 13/13 giống) / đổi tên `_num`**. `carlo.py`, `metrics/trades.py` là bản sao nguyên văn (thêm 1 dòng chú thích đầu file); `wfa.py` = `walk_forward.py` + 7 dòng import trỏ đường dẫn mới.

### Bảng ánh xạ cũ -> mới
**metrics/metrics.py**: `core/metrics/returns.py` (mọi hàm/hằng: `ANN`, `daily_returns_from_curve`, `return_metrics`, `curve_frame`, `daily_nav_series`, `cagr_pct`, `sharpe`, `fold_stats`, ...) + `core/metrics/portfolio.py` (`portfolio_metrics`, `series_metrics`, `curve_mdd_pct`, `flat_extras`, ...). Thứ tự: returns, portfolio.
**metrics/trades.py**: `core/metrics/trades.py` (nguyên văn). *Chờ*: `live/compare.py` (đối soát sàn <-> sim) về đây sau P9.4b (phiên kia đang sửa `live/*`).
**metrics/charts.py**: `core/analytics/dashboard.py` + `core/analytics/signal_explain.py` + `core/metrics/series_stages.py` (`stage_block`, `downsample_stage`, `RULE`; thuần chuỗi cho biểu đồ nên vào charts.py, KHÔNG vào metrics.py — ADR chưa liệt kê file này, cần thêm dòng vào bảng §3).
**regime/regime.py**: `core/regime/classifier.py` + `core/regime/learn.py` (`NAMES`, `series`, `learn_map`, `engine_by_regime`, `OBSERVE`, ...). `core/regime/report.py` (job) ở lại, P9.6.
**wfa/wfa.py**: `wfa/walk_forward.py` (nằm trong gói `backend/wfa` có sẵn; `wfa/run.py` job ở lại, P9.6).
**carlo/carlo.py**: `carlo/monte_carlo.py`.
**verdict/verdict.py**: `optimize/funnel/antiluck.py` + `core/metrics/diagnose.py` + `core/analytics/insights.py`. `core/metrics/diagnose_inputs.py` (có I/O) ở lại chỗ cũ cho phiên logic tách; verdict.py không import crawl.
Gói mới: `metrics/__init__.py`, `regime/__init__.py`, `verdict/__init__.py` (docstring). `carlo/`, `wfa/` đã là gói.

### Shim (13 alias `sys.modules`, cùng một đối tượng module; monkeypatch qua đường cũ có hiệu lực)
`core/metrics/{returns,portfolio}` -> `metrics.metrics`; `core/metrics/trades` -> `metrics.trades`; `core/metrics/series_stages`, `core/analytics/{dashboard,signal_explain}` -> `metrics.charts`; `core/regime/{classifier,learn}` -> `regime.regime`; `wfa/walk_forward` -> `wfa.wfa`; `carlo/monte_carlo` -> `carlo.carlo`; `core/metrics/diagnose`, `core/analytics/insights`, `optimize/funnel/antiluck` -> `verdict.verdict`. Không cần stub gói (không trùng tên file/thư mục: `wfa/wfa.py` nằm trong gói `wfa`, `regime/regime.py` khác `core/regime/`). `__module__` của hàm/lớp nay là `backend.metrics.metrics`, `backend.wfa.wfa`, ... (đúng tên cuối); `pickle.loads(pickle.dumps(f)) is f` cho `run_job` (wfa), `bootstrap_daily`, `portfolio_metrics`; `wfa/run.py` và `core/regime/report.py` import được.

### Đổi tên
Một: `signal_explain._num` -> `_sx_num` (3 chỗ; trùng tên `dashboard._num`, hai hàm khác nghĩa trong cùng `charts.py`). Mọi định danh khác không trùng (kiểm AST).

### Chu trình / vi phạm
Không chu trình mới. `metrics.py -> trades.py` một chiều. Importer ngoài nhóm không sửa (đi qua shim): `core/backtest.py`, `core/backtest/{run,custom_run,edu_precompute}`, `live/signals.py`, `optimize/*`, `api/*`, `wfa/run.py`. Vi phạm có từ trước, chuyển theo module (không thêm, không bớt): `charts.py` -> `db.local_pkl` (benchmark_daily_closes, I/O), `charts.py` -> `live.signals` (signal_explain), `wfa.py` -> `optimize.shared/store`, `utils.parallel`, `utils.memwatch` (6), `core.regime -> backtest` (classifier import cục bộ PortfolioEngine, giờ `regime.regime -> core.backtest`, hợp lệ), `verdict/diagnose_inputs -> crawl` (2, chờ tách).

### Đã sửa đường dẫn (chỉ path)
`optimize/store.py` `_CODE_FILES`: `core/metrics/{portfolio,returns,trades}.py` -> `metrics/{metrics,trades}.py`; `wfa/walk_forward.py` -> `wfa/wfa.py` (khoá `--resume` đổi một lần). `utils/engine_version.py` không đổi (không liệt kê file đã chuyển). `test/test_layering.py`: thêm `LAYER_RULES` `metrics`, `regime`, `verdict`; **báo cáo `docs/bmad/p9_layering_report.md` chỉ ghi khi `NORA_LAYERING_WRITE=1`** (mặc định không ghi; chỉ đạo điều phối). `test_ops_units.py` không đổi.

### Numba / pickle
Không module nào trong nhóm dùng numba -> không có cache numba bị ảnh hưởng. Pickle: 6 `paper.pkl`/`unified.pkl` (bản sao) nạp 6/6 trước, và danh sách `find_class` không chứa module nào của nhóm -> không cần shim cho pickle.

### Cổng (`NORA_GOLDEN_DATA_ROOT=data/binance`, `run_limited.sh --no-lock`, 23 file theo chỉ đạo; baseline trên cây làm việc tương đương HEAD fea526d vì commit đó chỉ gồm thay đổi đã nằm sẵn trong cây)
| | Kết quả |
|---|---|
| BASELINE (trước) | 312 passed, **10 failed** (931 s) |
| SAU | 312 passed, **10 failed** (1060 s) — đúng cùng 10 test |
| 10 đỏ có từ trước (không do bước này) | `test_portfolio_wfa::test_validate_book_main_end_to_end` + 9 ca `test_scale_pipeline` (resume/straight-run, stage_a topk, estimate) — giống hệt trước/sau (chưa điều tra nguyên nhân; thuộc ngoài P9.5) |
| `check_baseline.py` | 332/332 ok trước và sau (chỉ tính lại hash từ `out/`, không chạy lại Nautilus; nhóm này không nằm trên đường engine) |
| test_layering | trước 55 vi phạm (148 module, 38 shim) -> sau **55** (158 module, 51 shim); mọi cạnh giống hệt, chỉ đổi tên module |

### Việc còn lại
`live/compare.py` -> `metrics/trades.py` (sau P9.4b); tách `diagnose_inputs.py` (phần tính thuần -> verdict, phần nạp -> optimize/process/tasks); ADR §3 thêm `series_stages` -> charts; P9.10 gỡ shim.

## P9.5 — `metrics/{metrics,trades,charts}.py`, `regime/regime.py`, `wfa/wfa.py`, `carlo/carlo.py`, `verdict/verdict.py` (gộp nguyên văn + shim)

Ngày: 2026-10-08 · Người làm: norabt-99 (kiến trúc, chỉ di chuyển) · Trạng thái: **xong, CHƯA commit (không stage), chờ review chéo**. Không đổi logic. Nền: HEAD fea526d (+ sửa dở của phiên logic ở core/backtest*, core/execute/{amm,tracker}, test/reference_engine — không đụng).

**Phương pháp** như P9.4 (nối nguyên văn thân module từ `git HEAD`, gỡ import nội bộ nhóm kể cả import cục bộ, docstring -> banner; import ngoài nhóm chỉ đổi đường dẫn module). Kiểm AST từng hàm/lớp/hằng cấp module so với HEAD: **250 định danh nguồn, 237 giống hệt, 13 khác đúng bằng dòng import (+ đổi tên `_num`)** — đã kiểm lại bằng AST bỏ import/đổi tên: 13/13 trùng.

### Bảng ánh xạ cũ -> mới
**metrics/metrics.py** (thứ tự: returns, portfolio; import `metrics/trades`)
- `core/metrics/returns.py` -> toàn bộ (`ANN`, `daily_nav_series`, `return_metrics`, `fold_stats`, `cagr_pct`, `curve_frame`, `sharpe`, ...)
- `core/metrics/portfolio.py` -> toàn bộ (`portfolio_metrics`, `series_metrics`, `curve_mdd_pct`, `flat_extras`, ...)

**metrics/trades.py** <- `core/metrics/trades.py` (chuyển nguyên file). **CÒN CHỜ:** `live/compare.py` (đối soát sàn <-> sim) về đây sau P9.4b (phiên logic đang sửa live/*).

**metrics/charts.py** (thứ tự: dashboard, signal_explain, series_stages)
- `core/analytics/dashboard.py` (`build_dashboard`, `benchmark_daily_closes`, ...); `core/analytics/signal_explain.py` (`explain`, ...); `core/metrics/series_stages.py` (`stage_block`, `downsample_stage`, `RULE`) — series_stages là hàm thuần dựng chuỗi vẽ biểu đồ (không phải số đo) nên vào charts.py chứ không vào metrics.py (ADR không liệt kê; quyết định của tôi, dễ đổi).

**regime/regime.py** <- `core/regime/classifier.py` + `core/regime/learn.py`. `core/regime/report.py` là job -> ở lại P9.6 (`core/regime/__init__.py` giữ).

**wfa/wfa.py** <- `wfa/walk_forward.py` (nguyên file; chỉ đổi dòng import: `core.metrics.{portfolio,trades,returns}` -> `metrics.{metrics,trades}`, `core.regime.learn` -> `regime.regime`, `..carlo.monte_carlo` -> `backend.carlo.carlo`). `wfa/run.py` (job) ở lại P9.6.

**carlo/carlo.py** <- `carlo/monte_carlo.py` (nguyên file, không đổi dòng nào ngoài comment đầu).

**verdict/verdict.py** (thứ tự: antiluck, diagnose, insights) <- `optimize/funnel/antiluck.py` + `core/metrics/diagnose.py` + `core/analytics/insights.py`. `core/metrics/diagnose_inputs.py` (I/O) **ở nguyên chỗ** (phiên logic sẽ tách); verdict.py không import crawl. `Program`, `Call`, `Logic`, `Ctx`, `expr_to_vi` nay import từ `core.signal`.

### Shim (13 alias `sys.modules`, cùng một đối tượng module; không cần stub gói)
`core/metrics/{returns,portfolio}` -> `metrics.metrics`; `core/metrics/trades` -> `metrics.trades`; `core/metrics/series_stages`, `core/analytics/{dashboard,signal_explain}` -> `metrics.charts`; `core/regime/{classifier,learn}` -> `regime.regime`; `wfa/walk_forward` -> `wfa.wfa`; `carlo/monte_carlo` -> `carlo.carlo`; `core/metrics/diagnose`, `core/analytics/insights`, `optimize/funnel/antiluck` -> `verdict.verdict`. Kiểm: 13/13 `old is new`; `from backend.wfa import walk_forward as pw` có `__name__ == "backend.wfa.wfa"`; `dashboard.rt is core.metrics.returns`; `pickle.loads(pickle.dumps(f)) is f` cho `run_job`, `bootstrap_daily`, `portfolio_metrics`; `wfa/run.py` và `core/regime/report.py` import được. Không cần stub gói: `backend/wfa/` đã là gói (thêm `wfa.py` bên trong), `metrics/`, `regime/`, `verdict/` là gói mới (`__init__.py` docstring) và không trùng tên file.

### Đổi tên
Một: `signal_explain._num` -> `_sx_num` (3 chỗ) vì trùng `dashboard._num` (hai hàm khác nghĩa, trong cùng charts.py). Không đổi tên nào khác (kiểm AST không trùng tên trong 4 nhóm gộp).

### Chu trình / vi phạm
Không tạo chu trình mới: `metrics.py -> trades.py`, `charts.py -> metrics.py`, `wfa.py -> {metrics, regime, carlo}`, `verdict.py -> core.signal`, `regime.py -> core.backtest` (cục bộ, có từ trước). Còn lại, có từ trước, để nguyên: `charts.py:90 -> db.local_pkl` (benchmark_daily_closes I/O), `charts.py:559 -> live.signals` (signal_explain), `wfa.py -> core/backtest/run, optimize/shared, utils/parallel` (6, P9.6), `core -> regime` (4, core gọi classifier/loader; P9.10).

### Đường dẫn file mã
`optimize/store.py` `_CODE_FILES`: `core/metrics/{portfolio,returns,trades}.py` -> `metrics/{metrics,trades}.py`; `wfa/walk_forward.py` -> `wfa/wfa.py` (chỉ đường dẫn; khoá `--resume` đổi một lần). `utils/engine_version.py` không liệt kê file đã chuyển (chỉ core/backtest*, models, params, position_size) -> không đổi. `test_ops_units.py` không cần sửa. `test_layering.py`: `LAYER_RULES` thêm `metrics`, `regime`, `verdict`; báo cáo `p9_layering_report.md` chỉ ghi khi `NORA_LAYERING_WRITE=1` (mặc định không ghi), đã sinh lại một lần với cờ.

### Numba / pickle
Không module nào trong nhóm dùng numba -> không có cache numba bị ảnh hưởng. Pickle: 6 bản sao `data/_cache/live/*/{paper,unified}.pkl` nạp 6/6 trước (không có tên nào thuộc metrics/regime/wfa/carlo/analytics/antiluck nên shim không cần cho pickle trạng thái bot).

### Cổng (`NORA_GOLDEN_DATA_ROOT=data/binance`, `run_limited.sh --no-lock`, 23 file)
| | Kết quả |
|---|---|
| BASELINE (trước) | 312 passed, **10 failed**, 4 warnings (932 s) |
| SAU | 312 passed, **10 failed** (cùng 10), 4 warnings (1060 s) |
| 10 đỏ (có từ trước, KHÔNG do bước này) | `test_portfolio_wfa::test_validate_book_main_end_to_end` + 9 ca `test_scale_pipeline` (build_strategy_book/validate_book resume, stage_a, estimate): thư mục run (`_run_dirs`) rỗng — dấu hiệu lệch layout data/ (P9.3/P9.6), chưa điều tra sâu |
| golden, kernel_parity, metrics, mc_stress, daily_mc, wfa_mc, funnel, regime, diagnostics_*, portfolio_dashboard, book_*, overview_extras, signal_explain, custom_backtest, pydsl_parity, run_book_backtest, layering, ops_units | xanh trước và sau |
| nautilus_diff `check_baseline.py` | 332/332 ok (không chạy lại nautilus: nhóm này không nằm trong đường engine) |
| test_layering | trước 55 vi phạm (148 module, 38 shim) -> sau **55** (158 module, 51 shim); bảng theo luật giống hệt; 0 chưa ánh xạ |

## P9.6 + P9.8 (done) — `optimize/{search,funnel,book,process}` và `routes/` (gộp nguyên văn + shim), 2026-10-08

Trạng thái: **xong, KHÔNG commit, không stage** (người dùng chốt: P9 không commit). Chỉ di chuyển/gộp; không đổi logic. Cổng = SMOKE theo chỉ đạo (không chạy full suite).
Phương pháp: nối nguyên văn từ git HEAD bằng công cụ sửa theo vị trí AST (gỡ import nội bộ nhóm kể cả import cục bộ, `alias.attr` -> `attr`, import ngoài nhóm trỏ đường mới, docstring -> banner), shim `sys.modules` ở mọi đường cũ.

### Bản đồ cũ -> mới
- **optimize/process/workers.py** <- `utils/memwatch` + `utils/parallel`.
- **optimize/funnel/storage.py** <- `funnel/storage` + `optimize/store` (`DB_NAME` giống hệt -> 1 bản). Đổi tên: store `_SCHEMA/_dumps` -> `_RESULTS_SCHEMA/_results_dumps`; funnel `_SCHEMA/_dumps` -> `_RUN_SCHEMA/_run_dumps`. `code_version` root thêm một `..` (file sâu hơn một cấp).
- **optimize/search/generate.py** <- `funnel/generate`. **optimize/search/evaluate.py** <- `core/backtest/run` (thư viện: BacktestJob, make_engine, run, result_payload, load_items...; trừ DEFAULTS + run_job; khối env OMP/NORA_*_CACHE_MB giữ ở đầu file) + `funnel/evaluate` (`make_engine(dict)` -> `make_engine_from_dict`; `_make_engine` -> `make_engine`; `DAY` trùng -> 1 bản) + `optimize/shared`. `gates`/`sizing` của search/storage là proxy trì hoãn (`_Stages`) tới `funnel/stages` để không vòng import.
- **optimize/funnel/stages.py** <- `funnel/{gates,sizing,stats,estimate,orchestrator,promote,publish,recompute,run}`. Đổi tên: publish `DEFAULTS/run_job` -> `FUNNEL_BOOK_DEFAULTS/run_funnel_book`; recompute `run_job` -> `run_funnel_recompute`; run `DEFAULTS/run_job` -> `FUNNEL_RUN_DEFAULTS/run_funnel_run`.
- **optimize/book/build.py** <- `optimize/book` (`DEFAULTS/run_job/NORA_ROOT` -> `BOOK_BUILD_DEFAULTS/run_book_build/NORA_DIR`; thêm một `..`) + `core/params/presets` (`run_job` -> `run_presets_build`) + nhóm modes dùng cho engine/phễu (`FieldError, check_value, validate_params, schema_space, SCHEMA_SPACE_EXCLUDE, frame_keys, lift_frame, lift_frames, _num, _unit`). + `optimize/strategy_loader.py` (P9.9 của phiên logic, nội dung CUỐI chép nguyên văn; MỘT cache mtime; `_NORA` thêm một `..`). **KHÔNG shim**: file strategy_loader.py đã xoá; import đã đổi sang `backend.optimize.book.build` ở `core/strategy/book.py`, `test/test_strategy_dsl_parity.py` (và ghi chú trong `test/scripts/migrate_data_tree.py`). Không tạo `data/alpha/`.
- **optimize/book/registry.py** <- `utils/engine_version` (thêm một `..`; **`ENGINE_FILES` thêm `backend/optimize/search/evaluate.py`** vì thư viện run.py nằm đó, trước đây được băm qua thư mục core/backtest) + `optimize/registry` + `optimize/revalidate` (`DEFAULTS/run_job/wfa` -> `ALPHA_REVALIDATE_DEFAULTS/run_alpha_revalidate/wfa_check`) + `core/analytics/{user_alphas,strategy_doc,top_agents}` (top_agents là read model của file nghiên cứu đóng băng, router giữ import).
- **optimize/process/process.py** <- `utils/jobs` + phần tiến trình của `api/jobs/batch` (nguyên khối: JobError/JobBusy, KINDS, launch, run_sync, cancel, status*, list_jobs, job_label, persist_job/persist_finished_jobs/PERSIST_AREAS, _prune_failed/clean_unstaged_crawl_jobs, job_dir/_persisted_dirs...) + `run_job_dir` (thân `api/jobs/runner.run`; `runner.py` giữ làm điểm vào `-m backend.api.jobs.runner`, env phải đặt trước numpy). KINDS có thêm khoá `"func"` (mặc định `run_job`).
- **optimize/process/tasks.py** <- `core/backtest/run` (DEFAULTS+run_job -> `BOOK_BACKTEST_DEFAULTS/run_book_backtest`), `wfa/run` (`BOOK_WFA_DEFAULTS/run_book_wfa`), `core/regime/report` (`REGIME_REPORT_DEFAULTS/run_regime_report`), `core/backtest/custom_run` (`CUSTOM_BACKTEST_DEFAULTS/run_custom_backtest`), `core/backtest/edu_precompute` (`EDU_PRECOMPUTE_DEFAULTS/run_edu_precompute`; vẫn truyền MODULE `custom_run` qua import cục bộ -> view), `core/backtest/run_defaults`. `_ts` (3 bản giống nhau) -> dùng bản của search.evaluate; `WARMUP/DEFAULT_CAPITAL` trùng -> 1 bản. **`core/backtest/tick_run.py` Ở LẠI** (mã engine, nằm trong phạm vi băm engine_version; `run_book_backtest` vẫn import lười).
- **routes/jobs.py** <- phần kiểm tham số của `api/jobs/batch` (nguyên văn: check_*, build_job, build_custom_backtest, build_edu_precompute, http_launch, RUN_TIMEFRAMES, MAX_*); `http_launch` gọi `_proc.launch` (tra thuộc tính lúc gọi -> monkeypatch `launch` vẫn hiệu lực). **routes/modes.py** <- `api/modes` + phần chỉ-API của `core/params/modes`. **routes/{alphas,book,chart,custom,data,education,funnel,live,market,portfolio,strategies}.py** <- `api/routers/*` (chỉ đổi dòng import; `live.py` đổi 2 dòng import metrics). `main.py` import router từ `backend.routes`, giữ `backend.main:app` + hook startup user_alphas.
- Gói: `optimize/{search,process,book}/__init__.py`, `routes/__init__.py`. `optimize/book/__init__.py` là stub (tệp `optimize/book.py` cũ trùng tên thư mục): `backend.optimize.book` là VIEW của build (vẫn là gói, có `.build`, `.registry`).

### Shim (mọi đường cũ còn import được; `# P9-SHIM`)
Alias trơn (cùng đối tượng module): `funnel/{generate,gates,sizing,stats,estimate,orchestrator,promote}`, `optimize/{shared,registry}`, `utils/{engine_version,jobs,parallel,memwatch}`, `core/params/modes`, `core/backtest/run_defaults`, `core/analytics/{user_alphas,strategy_doc,top_agents}`, `api/modes`, `api/routers/*`.
`backend/_shim.py` `ModuleView` (dịch tên đã đổi, đọc/ghi/xoá đi vào module đích -> monkeypatch có hiệu lực): `optimize/{store,revalidate,book}`, `funnel/{evaluate,publish,recompute,run}`, `core/backtest/{run,custom_run,edu_precompute}` (run: đích [search.evaluate, tasks]), `core/params/presets`, `wfa/run`, `core/regime/report`, `api/jobs/batch` (đích [process, routes.jobs]; routers vẫn `batch_jobs.X` như cũ). `api/jobs/runner.py` giữ nguyên vai trò, chỉ gọi `run_job_dir`.

### KINDS sau (module:func)
book_backtest/book_wfa/regime_report/custom_backtest/edu_precompute -> `backend.optimize.process.tasks:run_book_backtest|run_book_wfa|run_regime_report|run_custom_backtest|run_edu_precompute`; book_build/presets_build -> `optimize.book.build:run_book_build|run_presets_build`; funnel_run/funnel_recompute/funnel_book -> `optimize.funnel.stages:run_funnel_run|run_funnel_recompute|run_funnel_book`; alpha_revalidate -> `optimize.book.registry:run_alpha_revalidate`; live_bot -> `live.bot:run_job`; data_crawl/data_crawl_okx/data_crawl_ticks/data_promote giữ đường `core.data.*` (shim P9.2, đổi ở P9.10). Bản ghi job cũ chỉ lưu `kind` nên đọc/chạy lại không đổi.

### Kiểm
- Số route: **trước 20 route phẳng / 58 đường openapi / 61 thao tác = sau** (cùng tập (path, methods, endpoint)). KINDS 16 = 16, tập khoá tham số giống hệt, mọi entry resolve thành callable.
- Import: 23 đường mới + 48 đường cũ import được; mỗi đường trong một interpreter sạch riêng (71, 0 lỗi, không phụ thuộc thứ tự).
- Pickle: `pickle.loads(pickle.dumps(f)) is f` cho w_backtest/_group/_group_rss/w_wfa/w_mc/w_sizing/w_holdout, export_job, run_book, wfa.run_job, worker_init, pool_map_safe, BacktestJob; `__module__` là nhà mới; `test/test_process_pickle.py` (spawn) xanh.
- AST so với git HEAD: 600 định danh cấp module, 593 giống hệt, 7 khác đúng chủ ý (code_version/NORA_ROOT/NORA_DIR thêm `..`, ENGINE_FILES thêm 1 đường, KINDS, http_launch `_proc.launch`, DAY: tuple của report); 0 thiếu. pyflakes sạch (chỉ cảnh báo có từ trước).
- `__file__`-depth: `engine_version().hash` và `code_version()` tính bằng mã CŨ (HEAD) và MỚI trên CÙNG cây làm việc: giống từng ký tự (25 file / `4755011c...`). NORA_DIR/RUN_LIMITED/book root/presets/run/funnel_root bằng trước.
- Giải thích đổi hash so với baseline đầu phiên: `code_version` — mọi file trong `_CODE_FILES` do P9.6/P9.8 KHÔNG đổi; thay đổi đến từ phiên logic (core/params.py, core/signal.py, core/strategy/{book,library}.py, và commit T6 của core/backtest.py). `engine_version` — một thay đổi do P9.6: `core/backtest/run.py` thành shim (được băm) và `ENGINE_FILES` thêm `search/evaluate.py` (nội dung thư viện run.py); còn lại do phiên logic (core/params.py, T6). Sổ dựng trước sẽ bị đánh dấu "cần dựng lại" như mọi lần engine đổi.
- pytest (chỉ bộ chỉ đạo): xem dòng kết quả cuối mục này.

### Việc dở / lưu ý
- `core/data/shared.py` (nằm trong `_CODE_FILES`) và `crawl/store.py`: chưa gộp (store.py đang được agent khác sửa ở worktree riêng). `core/analytics/feeds.py` còn dùng bởi router portfolio, `core/metrics/diagnose_inputs.py` cần tách (logic) -> để nguyên.
- `tick_run.py` ở lại core/backtest (xem trên). `test/job_modules.py`: `JOB_FILES` = (file, hàm job), `job_path` dựng file bọc gán `run_job`. `test_edu_precompute`, `test_funnel` sửa dòng khẳng định KINDS. `test_layering`: thêm luật `routes`, `_shim`.
- Phụ thuộc vòng đã xử lý: storage/search -> stages bằng proxy trì hoãn; `strategy.book` -> `optimize.strategy_loader` (P9.9 tạm của phiên logic) vẫn import được.

### P9.6 + P9.8 — bổ sung (đợt 2: gộp nốt, xoá thư mục stub, bỏ bản chép)
- **Gộp thêm**: `core/backtest/{custom_run,edu_precompute,run_defaults}` -> `process/tasks.py` (`run_custom_backtest`, `run_edu_precompute`; `DEFAULTS` -> `CUSTOM_BACKTEST_DEFAULTS`/`EDU_PRECOMPUTE_DEFAULTS`; `_ts` trùng -> bản của search.evaluate; `WARMUP/DEFAULT_CAPITAL/DAY` trùng -> 1 bản; edu vẫn truyền MODULE `custom_run` qua import cục bộ tới tasks); **`core/backtest/tick_run.py` -> `search/evaluate.py`** (không vào tasks.py: engine_version băm `search/evaluate.py` qua `ENGINE_FILES`, nên mã backtest tick vẫn nằm trong dấu vân tay engine; tasks.py chứa custom/edu nên không thể băm). `core/analytics/{user_alphas,strategy_doc,top_agents}` -> `book/registry.py`; `optimize/strategy_loader.py` (P9.9, nội dung cuối) -> `book/build.py`, **không shim**.
- **Xoá `core/params/` và `core/backtest/`** (không shim): mọi import repo-wide đã viết lại sang đích thật (59 file backend + test; chỉ đổi câu import, giữ tên cục bộ; `core/execute/*` không đụng). `core/params.py`, `core/backtest.py` giờ là module thường (numba cache khoá theo đường file nên không đổi; `__module__` của KernelBook... vẫn `backend.core.backtest`). Module bị gỡ (cho `live/state_migrate.py` của phiên logic): `backend.core.backtest.{kernel,engine,portfolio,dex}` -> `backend.core.backtest`; `.run` -> `backend.optimize.search.evaluate` (thư viện) / `backend.optimize.process.tasks` (`run_job`->`run_book_backtest`); `.run_defaults,.custom_run,.edu_precompute` -> `backend.optimize.process.tasks`; `.tick_run` -> `backend.optimize.search.evaluate`; `backend.core.params.{schema,template,builder}` -> `backend.core.params`; `.presets` -> `backend.optimize.book.build`; `.modes` -> `backend.routes.modes` (+ nhóm kiểm tham số ở `backend.optimize.book.build`, được `routes.modes` re-export). Tên đã đổi: `run_job`/`DEFAULTS` -> xem bảng trên.
- **Một định nghĩa cho một logic**: `_Stages` proxy x3 -> import cục bộ `from backend.optimize.funnel import stages as gates|sizing` trong từng hàm dùng (cùng hành vi); `alphas_dir` -> `crawl.store.alpha_dir` duy nhất (tôn trọng `NORA_ALPHAS_DIR`; build.py/registry.py/routes.funnel không còn bản riêng — LƯU Ý: bản presets cũ mặc định `data/alphas`, nay theo `alpha_dir()`); `funnel_root` (routes) -> import từ stages; `gates._ms` == `evaluate._ts` -> import; `routes.book._metrics/_METRIC_KEYS` -> import `build._metrics`. KHÔNG gộp vì ngữ nghĩa khác: `_read_json` (build: None khi lỗi; stages: None nếu không phải dict; core/backtest: {} ; routes/book: HTTP 500 khi hỏng), `_strip` (wfa bỏ thêm by_regime/shock/turnover/_daily_start so với build). `test/scripts/p9_ledger.py --dups [FOLDER]` thêm vào (cùng tên AST giống hệt / >0.8 giống, và cùng thân khác tên).
- **MISSING của ledger** (đều là xoá có chủ ý của phiên logic, hoặc do mình gộp một định nghĩa): `_EXCHANGE_RE`, `STAGING` (router data), `HISTORICAL_ALIASES`, `cache_crawl_dir`, `XNO_*`/`_plan_xno`/`xno_weights`, `apply_data_source`/`_nora_block`/`EDU_*` của custom_run/edu_precompute (đã vắng ở HEAD trước khi mình gộp), `kernel._writeback`, `alphas_dir` x4 và `_METRIC_KEYS` (gộp một bản, xem trên).
- Cổng đợt 2: smoke (66 đường import trong interpreter sạch riêng, route/KINDS bằng trước), AST so với HEAD 600/610 giống hệt (10 khác đúng chủ ý), `test_layering test_ops_units test_job_lifecycle test_data_paths_p93b test_user_alphas test_custom_backtest test_web_perf_cache test_process_pickle test_edu_precompute test_top_agents test_strategy_doc test_run_modes test_book_api test_revalidate test_strategy_dsl_parity test_book_ui_backend test_funnel test_tick_backtest test_golden_results` xanh; kernel_parity xem báo cáo.
