> **Plan gốc P15 — hiện trạng & kiến trúc chốt xem [p16_consolidation_plan.md](p16_consolidation_plan.md).** Checkbox bên dưới chỉ tick các mục đã xong theo `p15_handover.md` §4/§5 (R1, R3); phần còn lại giữ nguyên.

# P15 — Backend = API + adapter dùng thẳng NautilusTrader (plan + TODO triển khai)

Quyết định 2026-10-10: không tự build engine. UI giữ nguyên UX và đủ dữ liệu; `backend/` chỉ còn API, adapter (UI ↔ Nautilus) và xử lý dữ liệu (crawl → catalog Nautilus). Backend cũ: `test/backend-no/` (chỉ tham chiếu để port logic KHÔNG thuộc engine; không import từ backend). Bản nháp trước (đã archive tại `archive/2026-10-p16/p15_nautilus_native_backend.v1.md`): `p15_nautilus_native_backend.v1.md`.

Nguyên tắc cứng:
1. Engine = Nautilus. Không tự mô phỏng khớp lệnh / tính vốn / tính phí. Không fork/sửa mã Nautilus (LGPL-3.0) — hành vi riêng viết trong Strategy/Actor của mình.
2. Dữ liệu: Nautilus dùng gì thì mình lưu và dùng đúng cái đó; Nautilus không dùng thì mình cũng bỏ (archive, không xoá).
3. Không số giả/stub: endpoint chưa có logic thật trả 501 + `detail.code="NOT_READY"` để UI hiện "chưa hỗ trợ", tuyệt đối không trả hằng số.
4. Một định nghĩa cho mỗi logic. `backend/nautilus/` là lớp DUY NHẤT import `nautilus_trader`.

---

## 0. Hiện trạng đã kiểm (2026-10-10)

| Mục | Thực tế | Hệ quả |
|---|---|---|
| Venv API | `nora-api.service` chạy `~/.venvs/nora` = Python 3.11 + **nautilus_trader 1.221.0** (API Cython 1.x) | Code `backend/nautilus/*` viết theo API 1.x |
| Venv thử | `~/.venvs/nautilus` = Python 3.14 + **2.0.0rc6** (API Rust/PyO3 khác, chưa stable) | Không dùng production |
| PyPI | stable mới nhất **1.231.0** (Python ≥3.12,<3.15); 2.0 đang rc1–rc6 | **Pin 1.231.0** trên venv mới Python 3.12; 2.0 theo dõi qua cơ chế cập nhật §9 |
| Venv mới | **ĐÃ TẠO** `~/.venvs/nora312` = Python 3.12.13 + nautilus_trader **1.231.0** (+pandas, pyarrow) | P0.1 chỉ còn thêm fastapi/uvicorn/numpy/numba + requirements file |
| Funding | **Đã kiểm 1.221 và 1.231**: `FundingRateUpdate` chỉ có ở data_client; exchange backtest KHÔNG thanh toán funding | **Chốt: bỏ funding** khỏi kết quả + UI + catalog (nguyên tắc 2); `funding.pkl` archive |
| Tốc độ (đo thật, §13) | 1.231: ~30k nến 1m/giây/engine; mỗi vòng lệnh (vào+SL+huỷ+đóng) ~2–2,5 ms | Mặc định Studio (10 perp × ~3 năm 1m ≈ 15,8M nến) chạy 1 engine ≈ 9 phút → KHÔNG mượt nếu không thiết kế §13 |
| Bot live | Không còn unit bot nào chạy; state cũ ở `data/live/{paper,testnet}` | Live chuyển sang TradingNode (Phase 6) |
| `nautilus/data.py` | Đọc pkl, fallback âm thầm sang 1h, `iterrows` tạo Bar (1,58M dòng 1m BTC → rất chậm), ts_event = open, precision cố định 4/8, volume đang là quote USD, nến bù `is_filled` vẫn đưa vào engine | Thay bằng catalog (Phase 1) |
| `engine.py` | Tự dựng equity O(bars×trades); trừ phí 2 lần (realized_pnl Nautilus đã gồm phí); metrics tự tính; 1 symbol; `RiskEngine bypass=True` | Thay (Phase 3) |
| `strategy.py` | Notional cố định 1000 USDT; tín hiệu theo `bar_idx`; TP/trailing chỉ qty lệnh đầu; không cooldown/timeout/ATR/risk profile; `entry_submitted` không reset sau exit tín hiệu | Viết lại (Phase 2) |
| `routes/nautilus_api.py` | Stub/hằng số: `book/mc` (-15.8 cố định), `book/wfa`/`build` trả done giả, `book/` windows 2024 cố định, `validate` luôn true, assist/explain/presets rỗng, education samples bị thay bằng mẫu `on_bar`, user alphas & jobs chỉ trong RAM, backtest chạy đồng bộ trong request (chặn worker uvicorn duy nhất) | Phase 4–5 |

---

## 1. Kiến trúc đích

```
frontend (giữ nguyên)  ──HTTP JSON (hợp đồng p15_api_contract.md)──►
backend/
  main.py            FastAPI + phục vụ dist
  routes/            parse/validate request → gọi service; không logic
  nautilus/          LỚP DUY NHẤT import nautilus_trader
    catalog.py       đọc ParquetDataCatalog, BarType, Instrument (không ghi)
    config.py        input UI → BacktestEngineConfig / venue / fee / fill model
    strategy.py      NoraStrategy(Strategy): tín hiệu IR + vị thế + risk profile
    portfolio.py     PortfolioGuard(Actor): giới hạn danh mục, kill switch, ghi equity
    results.py       report Nautilus → JSON UI (trades/equity/metrics/series)
    runner.py        chạy 1 backtest từ RunSpec
    live.py          TradingNode + adapter OKX
    version.py       phiên bản, kiểm cập nhật (không tự cài)
  crawl/             crawl OKX + store.py: chất lượng dữ liệu + GHI CATALOG (P1)
  alpha/             DSL → IR, contract, annotate, assist, explain (port từ backend-no, giữ logic)
  signals/           chỉ báo + tín hiệu từ IR trên nến đã đóng (port indicator/signal, bỏ kernel)
  metrics/           METRIC_DEFS, notes, charts — tính từ output Nautilus
  research/          wfa, mc, regime, funnel — đều gọi nautilus/runner
  jobs/              job runner process (port optimize/process)
```
`crawl/store.py` ghi catalog qua hàm của `nautilus/` (wrangler/catalog writer) — không import `nautilus_trader` trực tiếp.

---

## 2. Phase 0 — Môi trường + hợp đồng (0,5 ngày)

- [x] **0.1 Venv** `~/.venvs/nora312` (Python 3.12): `requirements-backend.txt` pin `nautilus_trader==1.231.0`, fastapi, uvicorn, pandas, pyarrow, numpy (+ numba nếu signals cần). `ops/run_limited.sh` dùng venv mới. Đổi ExecStart `nora-api.service` SAU khi Phase 3 qua test; giữ `~/.venvs/nora` để chạy backend-no làm tham chiếu.
- [ ] **0.2 Hợp đồng API** `docs/bmad/p15_api_contract.md`: mỗi endpoint trong `frontend/src/api.js` (≈50) ghi method, request, response shape (field UI THẬT SỰ đọc — grep component), nguồn mới (Nautilus / port logic / dữ liệu). Snapshot shape thật bằng backend-no trên venv cũ → `test/fixtures/api_contract/<endpoint>.json` (chỉ key + kiểu).
- [x] **0.3 Bảng tính năng** (trong contract doc) — mỗi tham số UI gửi (`position.*`, POSITION_KEYS) → cách làm trên Nautilus:

| Tham số UI | Nautilus |
|---|---|
| fee maker/taker | `MakerTakerFeeModel` + maker/taker fee của Instrument OKX |
| slippage | `FillModel`; tham số UI không biểu diễn được → bỏ khỏi UI |
| SL / TP | `StopMarketOrder` / `LimitOrder` reduce_only, qty = vị thế thực (sửa khi DCA khớp) |
| trailing | `TrailingStopMarketOrder` (BASIS_POINTS, activation_price) |
| DCA | `LimitOrder` các tầng; quyền DCA theo risk profile |
| timeout / cooldown | `clock.set_time_alert` / so `ts_event` trong strategy |
| ATR stop (atr_frame) | `AverageTrueRange` Nautilus trên BarType khung atr_frame (aggregation INTERNAL) |
| sizing (order_size_pct, risk %) | strategy tính từ `account.balance_free` |
| leverage | `leverages` khi `add_venue` |
| liquidation | kiểm P1.0; không có → bỏ khỏi UI, hoặc PortfolioGuard đóng khi margin < maint (ghi rõ là luật Nora) |
| max positions / gross / kill switch | `PortfolioGuard` + `RiskEngineConfig` (bỏ bypass) |
| regime gating | tín hiệu (signals), không phải engine |
| funding | theo P1.0 |
| DEX/AMM | Nautilus không backtest AMM → ẩn DEX trong meta/UI |
| tick backtest | `TradeTick` từ catalog nếu có tick, ngược lại bar |

---

## 3. Phase 1 — Dữ liệu: catalog Nautilus trong `crawl/store.py` (1 ngày)

### P1.0 Probe Nautilus 1.231 (`test/scripts/p15_probe.py`, venv mới, ghi kết quả vào §0)
- [ ] Bar 1m EXTERNAL + aggregation INTERNAL (`<SYM>.OKX-1-HOUR-LAST-INTERNAL@1-MINUTE-EXTERNAL`) chạy trong backtest; timestamp nến khung lớn = close.
- [x] Backtest có thanh toán `FundingRateUpdate` vào account không → KHÔNG (1.221 + 1.231) → bỏ funding.
- [ ] Liquidation margin trong backtest có không.
- [x] Tốc độ + RAM → §13.1.
- [ ] `Bar.volume` có ảnh hưởng khớp lệnh khi `bar_execution` không.

### P1.1 Catalog = kho chuẩn duy nhất cho engine
Vị trí `data/market/okx/catalog/` (ParquetDataCatalog). Hàm mới trong `backend/crawl/store.py` (một định nghĩa):
- [ ] `catalog_root(exchange="okx")`.
- [ ] `okx_instrument_spec(symbol)`: từ OKX public `GET /api/v5/public/instruments?instType=SWAP` (tickSz, lotSz, ctVal, minSz, lever) + phí (meta) → lưu `data/market/okx/instruments.json` (`fetched_at`); `nautilus/catalog.py::instrument(symbol)` dựng `CryptoPerpetual` từ spec. Không hard-code precision.
- [ ] `write_catalog_bars(symbol, df_1m)`: chỉ nến THẬT (`is_filled == 0`); `BarDataWrangler` (vector, không iterrows); `ts_event = ts_init = open_time + 60s` (bar close); giá theo precision instrument; ghi tăng dần sau `last_ts` đã có; idempotent.
- [x] ~~`write_catalog_funding`~~ — bỏ: backtest Nautilus không dùng funding.
- [ ] `write_catalog_ticks(symbol, df)` → `TradeTick` nếu có tick.
- [ ] `sync_catalog(symbols=None)`: gọi cuối `run_job` crawl và nhánh promote; trả số bar ghi thêm.
- [ ] Manifest `data/market/okx/catalog/_manifest/<SYM>.json` giữ metadata hiện có (`source, crawled_at, start_ts, end_ts, rows_1m, filled_ratio_1m, sha256_1m, digest_1m, crawl_issues, volume_unit`) — Data page/quality gate đọc nhanh.
- [ ] `evaluate_data_quality` đọc catalog/manifest; nến thiếu = thiếu (không bù), `filled_ratio` chỉ để báo.

### P1.2 Bỏ những gì Nautilus không dùng (archive `data/archive/2026-10-p15/`, KHÔNG xoá)
- [ ] Nến bù `is_filled=1` → không vào catalog.
- [ ] Pkl resample `5m/15m/1h/4h/24h` → ngừng sinh; khung lớn do Nautilus aggregate. Biểu đồ UI cần khung lớn → `nautilus/catalog.py::bars_frame(symbol, frame, start, end)` đọc 1m catalog + MỘT hàm resample (`resample_from_1m`), LRU theo mtime.
- [ ] `1m.pkl` → archive sau khi P1.4 xanh; crawl incremental lấy `last_ts` từ catalog, ghi thẳng catalog.
- [ ] Volume: đơn vị base (OKX `volCcy`); dữ liệu cũ quote USD → base = quote/close, ghi `volume_unit` manifest.
- [ ] `funding.pkl` → archive; UI/meta bỏ funding (đã chốt).
- [ ] `data/market/okx/dex` (40M) + `data/market/binance` (3,2G; universe chỉ OKX từ 2026-10-07) → archive; meta không liệt kê.
- [ ] Xoá `backend/nautilus/data.py` (pkl, fallback 1h, iterrows) → thay `catalog.py`.

### P1.3 Vận hành
- [ ] `ops/run_limited.sh python -m backend.crawl.store --sync-catalog [--symbols …]`; lần đầu build đủ 10 asset.

### P1.4 Kiểm
- [ ] `test_catalog.py`: số bar == số dòng `is_filled==0` pkl; min/max ts; OHLC từng dòng khớp (sau làm tròn tickSz); precision == OKX spec; sync lần 2 không ghi thêm.

---

## 4. Phase 2 — Tín hiệu + Strategy (2 ngày)

### P2.1 `backend/alpha/` + `backend/signals/` (port, không đổi logic)
- [ ] Port từ `test/backend-no`: `alpha/{compile,contract}.py`, `core/indicator.py`, phần tín hiệu của `core/signal.py` (IR → entry/exit, `F|__fresh`, signal_mode event/level, `resolve_position_auto`), phần tham số của `core/params.py`. BỎ kernel, intrabar path, KernelBook, reference engine.
- [ ] Hàm duy nhất `signals.evaluate(ir, bars_by_frame) -> DataFrame` index = ts close (ns), trên nến ĐÃ ĐÓNG; backtest gọi trước, live gọi trên cửa sổ cuộn.
- [ ] Test port xanh (sửa import, không sửa kỳ vọng): `test_pydsl_*`, `test_dsl_reference`, `test_signal_event`, `test_p12_auto_defaults`, `test_alpha_contract`, `test_edu_samples_lint`.

### P2.2 `nautilus/strategy.py` — `NoraStrategy`
- [ ] Config: `instrument_id, bar_type_exec (1m EXTERNAL), signal_frame, side_mode, position{…}, risk_profile, signal_table`.
- [ ] Tín hiệu tra theo `bar.ts_event` (không bar_idx).
- [ ] Vào lệnh market tại sự kiện đóng nến khung tín hiệu (chuẩn Nautilus). Sizing từ `balance_free` × order_size_pct × leverage; `make_qty`; < minSz → bỏ + warning.
- [ ] SL/TP/trailing đặt sau fill entry; DCA khớp → `modify_order` qty SL/TP = vị thế thực; neo SL theo risk profile (avg / entry / last_layer + beyond %).
- [ ] DCA tầng Limit; cooldown (ts), timeout (time alert → đóng market); exit tín hiệu → `close_position` + `cancel_all_orders`; reset state ở MỌI nhánh thoát.
- [ ] Loại lệnh (ENTRY/DCA/SL/TP/TRAIL/EXIT/TIMEOUT) ghi vào `tags` của lệnh Nautilus — không giữ dict song song.
- [ ] Risk profiles (P14-B) = bảng trong `alpha/contract.py`; contract từ chối cấu hình trái luật trước khi chạy.

### P2.3 `nautilus/portfolio.py` — `PortfolioGuard(Actor)`
- [ ] Max vị thế đồng thời, gross exposure, kill switch DD → `TradingState.REDUCING/HALTED`.
- [ ] Ghi equity MTM mỗi lần đóng nến `equity_frame` (mặc định 1h): `balance_total + unrealized_pnls(venue)` — NGUỒN DUY NHẤT cho equity/drawdown.

### P2.4 Test
- [ ] `test_nora_strategy.py` dữ liệu thật đoạn ngắn: entry/SL/TP/DCA/trailing/cooldown/timeout đúng kỳ vọng tính tay từ fills Nautilus.
- [ ] Chuyển kịch bản `test/scripts/nautilus_diff` S1–S12 thành `test/regression/nautilus/` chạy NoraStrategy → hash fills/positions (dùng cho §9).

---

## 5. Phase 3 — Runner + kết quả (1,5 ngày)

### P3.1 `nautilus/config.py` + `runner.py`
- [ ] `build_run(payload) -> RunSpec` chuẩn hoá MỘT lần (symbols, start/end ms, capital, fee, leverage, position, risk_profile, train_ratio); lỗi → 422 có `field`.
- [ ] `run(spec, progress=None)`: `BacktestEngine`, `add_venue(OKX, NETTING, MARGIN, USDT, leverages, fee_model, bar_execution=True, bar_adaptive_high_low_ordering=True)`, instruments + bars từ catalog, tất cả symbol trong 1 engine (chung vốn), RiskEngine bật.
- [ ] Output thô: `generate_order_fills_report`, `generate_positions_report`, `generate_account_report`, equity PortfolioGuard, `portfolio.analyzer`. Dispose sau mỗi lần chạy.
- [ ] Nạp bar theo chunk từ catalog; không iterrows.

### P3.2 `nautilus/results.py` → shape UI (theo contract)
- [ ] `trades` từ positions report (+ fills cho từng chân DCA): thời gian, side, giá vào/TB/ra, qty, `pnl` = realized_pnl Nautilus (đã gồm phí — không trừ lần 2), fees = commissions, ret_pct, reason (tag lệnh đóng), bars_held.
- [ ] `series.stages.{all,train,test}` từ equity PortfolioGuard (downsample ≤2000 điểm, giữ điểm đáy DD); benchmark buy&hold từ close catalog.
- [ ] `metrics.{simulate,train,test}`: mỗi key `meta.metrics.defs` đúng một hàm trong `metrics/metrics.py`; ưu tiên giá trị `PortfolioAnalyzer` khi có, `help_vi` ghi "theo Nautilus" + chu kỳ annualize Nautilus dùng.
- [ ] `yearly`, `by_symbol`, `positions_open`, `warnings`, `notes` (port `metrics/charts.py`, `trades.py`; mọi số trích từ output này).

### P3.3 Test
- [ ] `test_results_contract.py`: shape khớp `test/fixtures/api_contract/custom_backtest.json`.
- [ ] Bất biến: equity cuối series == balance account cuối + unrealized; Σ fees == Σ commissions fills; số trades == positions closed.

---

## 6. Phase 4 — Jobs + API Studio (1,5 ngày)

- [ ] **4.1 Jobs**: port `optimize/process` (process riêng, `data/jobs/<id>/`, progress, cancel, prune: lỗi xoá ngay, tạm dừng giữ 7 ngày, EphemeralGone 410). Bỏ `JOBS_STORE` RAM + chạy đồng bộ trong request.
- [ ] **4.2** Custom / book backtest → job gọi runner.
- [ ] **4.3** Strategies/alpha (`compile, validate, annotate, assist/*, dsl, explain, presets, catalog, source`) → module alpha port P2.1; xoá stub.
- [ ] **4.4** User alphas → đĩa `data/alpha/user` (port), không RAM.
- [ ] **4.5** Education samples → 50 mẫu DSL thật ở `data/alpha/education` (bỏ mẫu `def on_bar` giả).
- [ ] **4.6** `/studio/meta`: engine `{name, version, docs_url}`; POSITION_KEYS chỉ tham số trong bảng 0.3; ẩn DEX/funding/liquidation theo P1.0; venue chỉ OKX.
- [ ] **4.7** Chart explain / regime: candles + chỉ báo + tín hiệu thật từ catalog + `signals.evaluate`.
- [ ] **4.8** Data `/api/data/crawl|promote|ticks/*` → crawl thật + `sync_catalog`; Data page đọc manifest.
- [ ] **4.9** `/studio/nautilus/version|check_update` chỉ báo; bỏ `update_command` tự cài.

## 7. Phase 5 — Research trên Nautilus (2 ngày)

- [ ] WFA: cửa sổ train/test theo thời gian → mỗi cửa sổ 1 `runner.run`; port logic tổng hợp `backend-no/wfa`.
- [ ] Monte Carlo: port `carlo` — hậu xử lý trades/daily returns Nautilus.
- [ ] Funnel / book build / publish: port `optimize/{search,funnel,book}`; mỗi config 1 `runner.run` qua pool process (RAM nora.slice); `/funnel/estimate` = số config × thời gian đo P1.0. Chậm → thu không gian tham số mặc định, KHÔNG tự viết engine nhanh.
- [ ] Portfolio dashboard/trades từ kết quả job book.

## 8. Phase 6 — Live (sau backtest, 2 ngày, cần anh duyệt khởi động)

- [ ] `nautilus/live.py`: `TradingNode` + OKX data/exec client (demo trước), keys CHỈ từ `~/.config/nora/okx.env`; cùng `NoraStrategy` + `PortfolioGuard`.
- [ ] Unit `nora-live@<mode>` trong nora.slice; một account một node.
- [ ] Endpoints live (`bot, trades, compare, compare_events, positions, balance, status`) đọc cache/persistence Nautilus.
- [ ] Đối soát 24h demo với lịch sử lệnh OKX.

## 9. Cơ chế cập nhật Nautilus

- [ ] Pin trong `requirements-backend.txt`; API không tự cài/nâng.
- [ ] `ops/nautilus_upgrade_check.sh` + timer tuần: có stable mới → venv tạm → cài → chạy `test/regression/nautilus` + `test_results_contract` + probe P1.0 → báo cáo `data/cache/nautilus_upgrade/<ver>.md` (khác biệt fills/equity/metrics).
- [ ] Nâng = đổi pin + cổng xanh + cập nhật hash + CHANGELOG (link release notes).
- [ ] 2.0 stable → story riêng; chỉ sửa trong `backend/nautilus/`.

## 10. Phase 7 — Dọn + docs

- [ ] Xoá `nautilus/data.py`, `engine.py` cũ, stub trong `routes/nautilus_api.py` (tách routes: studio, alpha, book, data, live, meta).
- [ ] Test chỉ dành engine tự build (`test_kernel_*`, `test_intrabar_path`, `test_golden_*`, `test_event_path_parity`, `test_amm_*`, `test_extreme_fill`, `test_conservative_fills`, `reference_engine.py`…) → `test/backend-no/tests/` (ngoài suite).
- [ ] `test_layering.py`: chỉ `backend/nautilus` import `nautilus_trader`.
- [ ] `docs/backend.md`: sơ đồ §1 + link https://nautilustrader.io/docs/latest/ (backtesting, data catalog, strategies, adapters/okx).

## 11. Definition of Done

1. Mọi endpoint trong `frontend/src/api.js` trả dữ liệu thật hoặc 501 NOT_READY có chủ đích; `npm run api:check` sạch.
2. E2E Playwright: Studio (Education + Create Alpha: chạy, tour, notes), Book, Funnel, WFA, MC, Data, Live — không lỗi console, không ô trống vì thiếu field.
3. 50 mẫu education + 3 chiến lược hệ thống chạy trên Nautilus; bảng so engine cũ (backend-no, venv cũ): khác biệt chỉ từ quy ước Nautilus (khớp tại close nến tín hiệu, không nến bù, phí/precision OKX thật), mỗi nhóm có giải thích.
4. Studio 10 symbol × 3 năm: thời gian đo thật, UI có progress, không chặn API.
5. Regression Nautilus có hash; kết quả probe P1.0 ghi §0.
6. Grep routes không còn hằng/stub (`-15.8`, done giả, mảng rỗng cố định).
7. `p9_ledger.py`: logic port từ backend-no không mất, không trùng định nghĩa.

## 12. Thứ tự + giao việc

| Bước | Phụ thuộc | Ai |
|---|---|---|
| P0 + P1.0 probe | — | 2 worker song song |
| P1 catalog | P1.0 | worker A |
| P2.1 port alpha/signals | P0 | worker B (song song P1) |
| P2.2–2.3 strategy/guard → P3 runner/results | P1, P2.1 | worker C |
| P4 jobs + API (4.3–4.5 làm sớm từ P2.1) | P3 | worker B + D |
| P5 research | P4.1 | worker D |
| P6 live | P3 | sau, anh duyệt |
| P7 + DoD | tất cả | Opus review + ledger |

---

## 13. Chạy thật + mượt trên UI (yêu cầu 2026-10-10: "không mock, mượt như engine cũ, chỉ thay core")

### 13.1 Số đo thật (BTC-USDT-SWAP OKX, nến thật `is_filled==0`, nora.slice, script `scratchpad/probe_speed*.py` → chuyển vào `test/scripts/p15_probe.py`)

| Cấu hình | Nến | Lệnh khớp | Thời gian run | RAM đỉnh |
|---|---|---|---|---|
| 1.231, 1 năm 1m, tín hiệu 1h INTERNAL, không lệnh | 525.601 | 0 | 16,5–17,3 s | 444 MB |
| 1.231, 1 năm 1m, có lệnh | 525.601 | 4.555 | 29,6–30,2 s | 444 MB |
| 1.231, 1 năm 1h làm nến khớp | 8.761 | 4.556 | 11,7 s | 244 MB |
| 1.221, 1 năm 1m, không lệnh, bypass logging | 525.601 | 0 | 14,7 s | — |
| 1.221, 3 năm 1h | 26.281 | 13.778 | 29–34 s | 437 MB |

Kết luận đo: lõi Nautilus ≈ 30k nến/giây/engine (không phụ thuộc callback Python — bỏ subscribe 1m vẫn 32k/s); chi phí lệnh ~2–2,5 ms/vòng, tăng nhẹ hơn tuyến tính theo độ dài (cần profile P13.4). Engine cũ: 8,4 s cho mặc định Studio. Lõi Nautilus một luồng không thể đạt 8,4 s ở độ phân giải 1m cho 15,8M nến — phải thiết kế, KHÔNG được giả kết quả.

### 13.2 Thiết kế để mượt (mọi số đều từ Nautilus chạy thật)
- [ ] **Độ phân giải khớp lệnh** (tham số `exec_frame` trong RunSpec + meta + RunSettings UI, có ước lượng thời gian từ §13.1):
  - `signal` (Nhanh, mặc định Studio Education/Create Alpha): nến khớp = khung tín hiệu (vd 1h), `bar_adaptive_high_low_ordering=True` (quy tắc Nautilus). 10 perp × 3 năm 1h ≈ 263k nến ≈ 9 s + lệnh → cùng cỡ engine cũ.
  - `1m` (Chuẩn): nến 1m EXTERNAL, tín hiệu khung lớn INTERNAL — cho book build/publish/WFA cuối, ứng viên live, và nút "Chạy chuẩn 1m" trong Studio. Chạy nền có tiến độ.
  - Kết quả ghi rõ `exec_frame` (badge trên Result + notes) — người dùng luôn biết đang xem loại nào. Không tự động đổi ngầm.
- [ ] **Tiến độ + kết quả từng phần thật**: PortfolioGuard ghi equity/trades đã đóng ra `data/jobs/<id>/partial.json` mỗi N giây (thời gian mô phỏng, % theo ts). UI hiện thanh tiến độ + đường equity đang chạy (đây là dữ liệu thật đến thời điểm đó, đánh dấu "đang chạy"). Hoàn tất → thay bằng kết quả đầy đủ.
- [ ] **Cache kết quả**: khoá = sha256(IR/code chuẩn hoá, RunSpec, `digest` catalog các symbol, phiên bản Nautilus, exec_frame). Chạy lại cùng cấu hình → trả ngay. Đổi dữ liệu/phiên bản → tự hết hạn.
- [ ] **Làm nóng sẵn**: sau mỗi `sync_catalog` / nâng Nautilus → job nền chạy 50 mẫu education + 3 chiến lược hệ thống ở cấu hình mặc định (exec `signal`) → Education mở ra có kết quả ngay (kết quả thật, có `computed_at`).
- [ ] **Song song đúng luật**: một engine cho cả danh mục (giữ max_positions, gross cap, kill switch, sizing theo vốn chung — như engine cũ). Chỉ tách mỗi symbol một process khi RunSpec KHÔNG có ràng buộc chéo (1 symbol; hoặc vốn chia cố định mỗi symbol + không cap danh mục) — điều kiện kiểm trong `config.py`, ghi `parallel=true` vào kết quả.
- [ ] **Nạp nhanh**: catalog parquet + `BarDataWrangler`/đọc trực tiếp (đo: 1,3–1,6 s/1 năm/symbol); cache LRU bar theo (symbol, frame, khoảng, mtime) trong process job dùng lại.
- [ ] **Không chặn API**: mọi chạy engine trong process job (P4.1); API chỉ đọc progress/partial/result.

### 13.3 Đảm bảo không mock (cổng bắt buộc)
- [ ] `test_no_mock.py`: (a) grep `backend/routes` + `backend/nautilus` không có số liệu hằng trong response (danh sách cấm: `-15.8`, `"status": "done"` không đi kèm job thật, `confidence_95`, windows ngày cố định, mảng rỗng trả thẳng ở endpoint dữ liệu); (b) mỗi response kết quả có `provenance = {engine:"nautilus_trader", version, exec_frame, catalog_digest, run_id, computed_at}`; (c) chạy custom backtest thật trên đoạn 30 ngày → trades/fills khớp `generate_order_fills_report()` của chính engine đó (đếm + tổng phí + PnL).
- [ ] UI hiển thị `provenance` (tooltip ở badge engine trên Result) — một chỗ, từ API.
- [ ] Endpoint chưa có logic → 501 `NOT_READY`; UI có trạng thái "chưa hỗ trợ" (không placeholder số).

### 13.4 Tối ưu lõi (không sửa Nautilus)
- [ ] Profile vòng lệnh (py-spy native) để tìm phần tăng hơn tuyến tính: thử `cache` config (không lưu snapshot vị thế), `OmsType`, cách huỷ lệnh (huỷ theo id thay `cancel_all_orders`), `LoggingConfig(bypass_logging=True)`, `run_analysis=False` khi không cần.
- [ ] Ghi kết quả vào §13.1; mục tiêu: Studio `signal` ≤ 15 s, `1m` 1 symbol 3 năm ≤ 60 s.

### 13.5 Nghiệm thu "mượt"
1. Education: mở mẫu → kết quả hiện ≤ 1 s (cache làm nóng); đổi tham số → ≤ 15 s (exec `signal`, 10 perp × 3 năm).
2. Create Alpha: chạy code mới → tiến độ ≤ 1 s sau bấm, kết quả ≤ 15 s (`signal`); "Chạy chuẩn 1m" có tiến độ + equity từng phần.
3. API vẫn phản hồi (< 200 ms) trong lúc job chạy.
4. Mọi số trên màn hình truy được về `run_id` + Nautilus report.
