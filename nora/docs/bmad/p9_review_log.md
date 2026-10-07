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
