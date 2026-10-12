# P16 — Hợp nhất sau P15 (plan, 2026-10-12)

Nguồn: audit read-only 2026-10-12 (backend / frontend / docs+data). Kế thừa `p15_handover.md` (luật kiến trúc §1, logic §2 vẫn hiệu lực; chỉ đường dẫn file đổi).
Phân vai: **Opus (medium)** phân tích, viết brief, review diff, chạy cổng kiểm. **Worker = Sonnet, effort medium**, mỗi task 1 brief, không tự mở rộng phạm vi.
Chạy test/engine: luôn qua `ops/run_limited.sh`, venv `~/.venvs/nora312`. Commit: kiểm `git diff --cached --name-status` trước mỗi commit.

## 0. Hiện trạng (tóm tắt audit)

Kiến trúc thực tế (working tree, chưa commit):
```
models/ ← alpha/(compile, contract, dsl/{indicator,signal,strategy,ta}) ← nautilus/ ← {metrics, optimize, routes}
crawl/ (độc lập), carlo/, wfa/ (lá)
```
Luồng chạy: route → `routes/process.build_and_launch` → subprocess `optimize/process/tasks.run_custom` →
- DSL: `build_plan` → `evaluate.execute` → `PortfolioEngine` → `NautilusRun.run` (NoraSlotStrategy + Coordinator) → `get_results` → `metrics.trades.build_result`
- Native Python: `NativeNautilusRunner` → `results.format_nautilus_results` → `build_result`

Vấn đề chính (theo mức nghiêm trọng):

| # | Vấn đề | Chỗ |
|---|---|---|
| A1 | **Số giả**: `backend/scripts/generate_sample_results.py` sinh equity bằng `random`/Gauss; `routes/alpha.py:85-116` phục vụ `sample_results.json` như kết quả thật (vi phạm luật 4 "không số giả") | scripts/, routes/alpha.py, data/alpha/education/sample_results.json |
| A2 | Hỏng import: `ta.py` untracked nhưng `compile.py:22` import; `test/scripts/lint_edu_samples.py:35` (`backend.models.strategy`) → test_edu_samples_lint lỗi collect; `research_regime_diagnosis.py:61` import `backend.regime` | |
| A3 | **Hai đường engine**: `NautilusRun.run` vs `NativeNautilusRunner.run` (venue setup copy); hai formatter `engine.get_results` vs `results.format_nautilus_results`; `results.py` đoán TP/SL theo dấu PnL, placeholder mae/max_price/leverage, unrealized≈0; `close_at_end` no-op; không chunk; equity tracker sai đa symbol; benchmark native luôn AttributeError (nuốt thành warning) | nautilus/runner.py, results.py, tasks.py:170-318 |
| A4 | Logic trùng: 3 bảng FRAME_MS (params:172, catalog:39, trades:214); 2 aggregate by_symbol; normalize symbol tay (tasks:172); tail `run_custom` lặp | |
| A5 | Route chứa logic: `post_mc` gate (optimize.py:461-528), `_nav` (1145), `_build_meta` (process.py:851) | |
| A6 | Back-edge `metrics/regime.py:26` → nautilus | |
| A7 | `exec` code người dùng không sandbox trong job process (compile.py:1012) | |
| A8 | UI: R4 chỉ có ở Studio (Backtest/WFA/MC/Funnel/Live không có provenance/warnings/selector); `canSave` nới → lưu trùng program_hash; regex timeframe trong runForm trùng compile meta; polling 400–800 ms; số cứng (10000 vốn, '1h', list frame); SavedAlphaList chết; `emptyOutDir:false` dồn chunk | frontend/src |
| A9 | Dữ liệu: signal/chart/data route vẫn đọc pkl (`data/market/okx/cex`), engine đọc catalog 1m → 2 nguồn; funding.pkl còn tham chiếu dù engine funding=0; `data/alpha/funnel` 2.9G + wfa/backtest/live cũ của engine cũ | |
| A10 | Docs lệch: handover/plan/api_contract mâu thuẫn nhau & code; architecture/*, prd, epics, knowledge_base mô tả engine cũ/DEX; sprint-status không có P15; E16-S9, E21-S2..S8 lỗi thời | |

Trạng thái R1–R7 (P15): R1 ❌ (1 lỗi collect), R2 ❌, R3 ✅, R4 ◐ (Studio), R5 ❌ (thay bằng số giả), R6 chưa chạy, R7 chưa (đúng kế hoạch).

## 1. Quyết định cần anh chốt (trước Phase 2)

- **D1 — Đường native Python**: (khuyến nghị) giữ native nhưng dùng CHUNG lõi `NautilusRun` (venue/data/chạy) + MỘT formatter; DSL chỉ là một Strategy đặc biệt. Phương án khác: bỏ native.
- **D2 — Kết quả mẫu education**: (khuyến nghị) xoá generator giả + file json; thay bằng cache kết quả thật (R5) làm nóng bằng job runner. Trong lúc chưa có cache: card hiển thị "chưa chạy", không số.
- **D3 — Sandbox native code**: tối thiểu chạy trong job subprocess có giới hạn (đã có run_limited) + chặn import ngoài whitelist; hay chấp nhận rủi ro (chỉ user nội bộ)?
- **D4 — Nguồn dữ liệu duy nhất**: chuyển signal/chart/data route sang catalog + `aggregate_frame`, rồi archive pkl (khuyến nghị, Phase 4).

## 2. Phases & tasks

Mỗi task: worker Sonnet/medium; brief do Opus viết khi giao (file, thay đổi chính xác, tiêu chí, KHÔNG đụng gì). Tasks cùng phase không đụng file chung → chạy song song.

### Phase 1 — Xanh lại & khoá cây (không đổi hành vi)
| T | Việc | File | Cổng |
|---|---|---|---|
| 1.1 | `git add` `alpha/dsl/ta.py`; sửa import `lint_edu_samples.py` → `backend.alpha.dsl.strategy`; `research_regime_diagnosis.py` → `backend.metrics.regime` | 3 file | `pytest --collect-only` 0 error |
| 1.2 | R2: chuyển `test/scripts/nautilus_diff/*` (s10/s11/s12/s15 run+compare, script import engine cũ) → `test/backend-no/scripts/`; cập nhật regex cổng R2 loại trừ `NativeNautilusRunner` | test/scripts | grep cổng R2 = 0 |
| 1.3 | Dọn comment/AGENTS.md nhắc `core/backtest.py`, `regime/regime.py`, `backend/live` → đường dẫn mới | evaluate, signal, params, routes/optimize, AGENTS.md | grep `core/backtest\|regime/regime` = 0 ngoài backend-no |
| 1.4 | Commit refactor (core→alpha/dsl+models, regime→metrics) thành 1 commit sạch | — | full suite 0 failed (Opus chạy) |

### Phase 2 — Gỡ số giả + một lõi engine (sau D1, D2)
| T | Việc | Cổng |
|---|---|---|
| 2.1 | Xoá `backend/scripts/generate_sample_results.py` + `sample_results.json` (archive file vào `data/archive/`); `routes/alpha.py` bỏ fallback sample-result giả; endpoint sample result trả 404/`NOT_READY` khi chưa có cache thật | grep `random` trong backend/ không còn sinh kết quả; test_no_mock mở rộng phủ route này |
| 2.2 | Tách `nautilus/engine.py` → hàm lõi duy nhất `run_engine(strategies, instruments, bars, venue_cfg)`; `NautilusRun` và `NativeNautilusRunner` cùng gọi; chunk dữ liệu chung | test_nautilus_engine + test_nautilus_native + test_dca_nautilus_native xanh; kết quả DSL bit-identical trước/sau |
| 2.3 | Một formatter: bỏ `results.format_nautilus_results`, native dùng `get_results` (close_reason từ order tag/loại lệnh thật, không đoán dấu PnL; mae/max_price từ dữ liệu hoặc bỏ field kèm provenance, không placeholder); unrealized MTM theo giá cuối; `close_at_end` thực đóng | không còn `PositionStatus.TP if pnl > 0`; test native kiểm close_reason |
| 2.4 | `tasks.run_custom`: gộp tail DSL/native; benchmark native dùng plan thật (có venue) → không còn AttributeError; dùng `catalog.normalize_symbol` | test_custom_backtest native+DSL có benchmark |
| 2.5 | Một bảng FRAME_MS (`models/params`), catalog/trades import; một `aggregate_by_symbol` | p9_ledger --dups sạch |

### Phase 3 — Routes mỏng + phân lớp
| T | Việc | Cổng |
|---|---|---|
| 3.1 | `post_mc` gate → `optimize/book` hoặc `carlo`; `_nav` → metrics; `_build_meta` → module meta (models hoặc alpha/contract) | routes chỉ parse/validate (review Opus); test_book_* xanh |
| 3.2 | Bỏ back-edge `metrics/regime` → nautilus (nhận dữ liệu qua tham số hoặc dùng catalog từ crawl) | import graph: metrics không import nautilus |
| 3.3 | (theo D3) chặn import ngoài whitelist cho native code; lỗi rõ ràng | test: code import `os`/`subprocess` bị từ chối |

### Phase 4 — Dữ liệu một nguồn (sau D4)
| T | Việc | Cổng |
|---|---|---|
| 4.1 | `DataSource` (signal), chart (`routes/alpha.py:513`), `routes/data.py:89` đọc catalog + `aggregate_frame` | test_strategy_signal_parity bit-identical (tín hiệu trên catalog = pkl) |
| 4.2 | Gỡ tham chiếu funding.pkl (models:491, dsl/strategy:713, cache key evaluate) | grep `funding.pkl` = 0 |
| 4.3 | Archive `data/market/okx/cex/*.pkl`, `data/alpha/funnel`, `data/{wfa,backtest,live}` cũ → `data/archive/2026-10-p16/` (move, không xoá) | app chạy, full suite xanh |

### Phase 5 — R5 cache + UI R4 đầy đủ
| T | Việc | Cổng |
|---|---|---|
| 5.1 | Cache kết quả theo (program_hash, RunSpec, digest catalog, version Nautilus, base_frame); job làm nóng 50 mẫu education qua job runner | mở mẫu lần 2 ≤1 s; mẫu chưa chạy → UI "chưa có kết quả" |
| 5.2 | UI: component chung `ProvenanceBadge` + `WarningsPanel` dùng ở CustomResult, Backtest/WFA/MC, Funnel AlphaDrawer, Live; selector Chuẩn/Nhanh ở Backtest; mặc định lấy từ meta | E2E: badge đúng 2 chế độ ở mỗi trang |
| 5.3 | UI dọn: khôi phục chặn lưu trùng `program_hash`; bỏ regex timeframe (dùng compile meta); bỏ ternary no-op + `activateTab` trùng; xoá SavedAlphaList; 10000/'1h'/frame list/MAX_TOTAL → meta; polling về 1500–2000 ms; `emptyOutDir` + chiến lược dọn dist cũ | vite build sạch; review Opus |
| 5.4 | R6: restart nora-api, chạy `scratchpad/e2e_api.py` | exit 0 |

### Phase 6 — Docs & backlog
| T | Việc |
|---|---|
| 6.1 | Gộp `p15_handover.md` + `nautilus_architecture.md` thành 1 doc kiến trúc hiện hành (đường dẫn mới, sửa claim sai: catalog chỉ 1m, không Bayesian, không CapitalLedger, live chỉ check kết nối, test_all_modes không tồn tại) |
| 6.2 | `p15_api_contract.md`: thanh lý/slippage = không mô phỏng (khớp code) |
| 6.3 | Archive: `architecture/*` cũ, `p14_*`, `p15_*.v1`, knowledge_base 01/03/04; prd FR-20/31/NFR-6 + "332/332 parity" đánh dấu superseded |
| 6.4 | sprint-status: thêm epic E22 (P15) + E23 (P16 này); đóng E16-S9 → thay bằng R7 (TradingNode); E21-S2/S4/S6/S7/S8 → "won't do (unsupported/501)"; S3/S5 → test hành vi Coordinator/NoraSlotStrategy |

### Phase 7 — R7 Live trên Nautilus TradingNode (cần anh duyệt riêng, ngoài P16)

## 3. Thứ tự & song song
P1 (1.1‖1.2‖1.3 → 1.4) → chốt D1–D4 → P2 (2.1‖2.5, rồi 2.2 → 2.3 → 2.4) ‖ P6 → P3 (3.1‖3.2‖3.3) → P4 (4.1 → 4.2 → 4.3) → P5 (5.1‖5.2‖5.3 → 5.4).
Cổng mỗi phase: Opus review diff + quick tests nhắm đích; full suite 1 lần cuối phase; `p9_ledger --dups` sạch.

---

## 4. Kiến trúc file đích (anh duyệt 2026-10-12)

Flow: UI → routes → jobs → alpha (biên dịch) → signal (tín hiệu) → nautilus (backtest) → kết quả → metrics; sau đó wfa (N × backtest) và carlo (đọc lệnh).

```
backend/
├── main.py
├── data.py              DỮ LIỆU THỊ TRƯỜNG — 1 file (thay crawl/, xem §5)
├── routes/              [1] API: chỉ parse/validate → jobs
├── jobs/                [2] runner.py · tasks.py · workers.py         ← optimize/process
├── alpha/               [3] BIÊN DỊCH: compile.py · contract.py · plan.py (build_plan)
├── signal/              [4] TÍN HIỆU (numpy thuần, không Nautilus)
│   indicator.py · ta.py · nodes.py (← dsl/signal.py) · compute.py (← SignalEngine/SignalPortfolio) · regime.py
├── nautilus/            [5] BACKTEST — duy nhất import nautilus_trader
│   backtest.py (1 lõi: gộp engine.NautilusRun + runner.py) · strategy.py (adapter VÀO) · portfolio.py
│   results.py (adapter RA: gộp engine._results + results.py) · catalog.py (instrument, Bar, ghi catalog) · live.py · version.py
├── metrics/             [6] hậu backtest: metrics · trades · charts · regime (không import nautilus)
├── wfa/                 [7] giữ nguyên (gọi nautilus.backtest theo cửa sổ)
├── carlo/               [7] giữ nguyên (đọc danh sách lệnh)
├── optimize/            [7] search/ · funnel/ · book/  (bỏ process/ → jobs/)
└── models/              models.py · params.py · position_size.py · storage.py (đường dẫn + IO json, ← crawl/store.py)
```
Luật import: `routes → jobs → {optimize, wfa} → nautilus → signal → models`; `alpha → signal` (danh mục indicator); `metrics, carlo` không import nautilus/signal; `data.py` → models, ghi catalog qua `nautilus.catalog` (lazy); `signal` đọc nến qua `data.py`.

## 5. Plan gộp crawl/ → `backend/data.py`

### 5.1 Hiện trạng crawl/ (3.4k LOC)
| File | Nội dung | Còn dùng? |
|---|---|---|
| `cex.py` 649 | Crawler Binance (Vision zip + REST, funding) + crawler OKX (CDN zip theo ngày HK + REST, funding) → pkl staging | Binance: KHÔNG (dữ liệu đã archive). OKX: CÓ |
| `dex.py` 636 | Tick swap on-chain (RPC, pool, decode) | KHÔNG (DEX → 501) |
| `store.py` 2127 | Trộn 6 thứ: (a) đường dẫn data/alpha/run/live/cache; (b) IO json/pickle/parquet atomic, ByteLRU, options; (c) symbol/universe/mặc định chạy; (d) đọc pkl, CandleLoader, resample, fill_missing, ticks_to_bars, manifest; (e) quality gate ~450 dòng; (f) job promote staging | (a)(b) không phải dữ liệu thị trường; (d) bỏ sau khi chuyển catalog |
| Ngoài crawl | `test/scripts/build_catalog.py` (pkl → catalog; **đang gãy**: import `write_catalog_bars` không tồn tại), `test/scripts/fetch_instruments.py` (instruments.json) | Việc lõi nhưng nằm ở script |

Vấn đề: không có đường tự động crawl → catalog. Crawl ra pkl; catalog dựng tay bằng script gãy. 64 file import `backend.crawl.*`.

### 5.2 Đích: `backend/data.py` (~1.0–1.2k LOC), 6 mục
1. **Universe & symbol**: `UNIVERSE` (10 OKX USDT-SWAP), `normalize_symbol`, `base_name`, `require_perp`, `default_window`, `run_defaults`. (Một định nghĩa — `nautilus.catalog.normalize_symbol` gọi về đây.)
2. **Instruments**: `fetch_instruments()` (từ fetch_instruments.py) → `data/market/okx/instruments.json`.
3. **Crawl OKX 1m**: CDN zip theo ngày + REST lấp khoảng trống, chỉ nến thật (không fill), cache zip. Tăng dần: chỉ tải phần sau mốc cuối của catalog.
4. **Ghi catalog**: `update_catalog(symbol)` = crawl → kiểm chất lượng → `nautilus.catalog.write_bars(...)` (atomic theo symbol) → `_manifest/<SYM>.json` (rows, khoảng, digest). Thay build_catalog.py + staging/promote.
5. **Đọc**: `load_bars(symbol, frame, start, end) -> dict numpy` (pyarrow đọc 1m + `aggregate_frame` — MỘT định nghĩa, chuyển từ nautilus/catalog.py), `daily_close`, `catalog_digest`, `coverage()` cho routes/data.
6. **Chất lượng**: `evaluate_quality(symbol)` / `require_data_ok(symbols)` trên catalog (khoảng trống, trùng, OHLC hợp lệ, độ phủ) — viết gọn từ quality gate cũ, giữ ngưỡng.
7. **Job**: `run_job(params)` = cập nhật catalog cho danh sách symbol (kind `data_update` thay `data_crawl`, `data_crawl_okx`, `data_crawl_ticks`, `data_promote`).

Tách khỏi crawl (không phải dữ liệu thị trường): (a)(b) → `models/storage.py`; `DEFAULT_CAPITAL`, `DEFAULT_TRAIN_RATIO` → `models/params.py`.
Bỏ (archive vào `test/backend-no/crawl/`, không xoá): Binance crawler, `dex.py`, đọc/ghi pkl, `CandleLoader`, resample/fill_missing/ticks_to_bars, chọn sàn (`EXCHANGES`, binance), staging/promote.
Funding: engine không mô phỏng → KHÔNG crawl (D5 — mở lại khi có mô hình funding).

### 5.3 Tasks (worker Sonnet/medium; Opus review + cổng)
| T | Việc | Phụ thuộc | Cổng |
|---|---|---|---|
| D1 | Tạo `models/storage.py` từ (a)(b) của store.py; sửa mọi import (cơ học, ~50 file); store.py re-export tạm | Phase 1 | grep import đường dẫn/IO từ `backend.crawl` = 0; full suite xanh |
| D2 | Viết `backend/data.py` mục 1–2–5–6 (đọc catalog, universe, quality); `aggregate_frame`/`normalize_symbol` chuyển về đây, nautilus/catalog gọi lại | D1 | `load_bars` bit-identical với `catalog.exec_arrays` hiện tại (10 symbol × 1m/15m/1h); quality gate cũ vs mới cùng verdict trên 10 symbol |
| D3 | Mục 3–4–7: crawl OKX tăng dần → `nautilus.catalog.write_bars` (thêm hàm ghi) → manifest; job kind `data_update` trong jobs; xoá kind cũ | D2 | test với zip/REST ghi sẵn (fixture, không mạng): crawl 2 ngày → catalog + manifest đúng; chạy lại không đổi digest |
| D4 | Chuyển người dùng pkl sang `data.load_bars`: signal compute (DataSource), charts (`routes/alpha.py:513`), `routes/data.py`, benchmark daily close | D2, = Phase 4.1 | test_strategy_signal_parity bit-identical; grep `read_pickle\|\.pkl` trong backend = 0 |
| D5 | Archive `backend/crawl/` + test cũ (test_crawler_and_gate, test_okx_data, test_pkl_meta, test_ticks, test_data_layout…) → `test/backend-no/`; viết test mới `test/test_data.py`; cập nhật p9_ledger | D3, D4 | grep `backend.crawl` = 0; full suite xanh; p9_ledger --dups sạch |
| D6 | Archive `data/market/okx/cex/*.pkl` → `data/archive/2026-10-p16/` (move); restart nora-api + E2E | D5 | app chạy, e2e exit 0 |

Thứ tự: D1 → D2 → (D3 ‖ D4) → D5 → D6. D4 trùng Phase 4.1 (gộp làm một).
Rủi ro: tín hiệu tính trên pkl hiện có nến fill (`is_filled`) — catalog chỉ nến thật → D4 phải chứng minh bit-identical hoặc ghi rõ khác biệt và được anh duyệt trước khi đổi.
