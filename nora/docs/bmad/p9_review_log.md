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
