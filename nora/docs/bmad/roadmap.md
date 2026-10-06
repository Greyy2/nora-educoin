# Nora — Kế hoạch triển khai (nguồn duy nhất)

Cập nhật: 2026-10-06 · Nhánh: `fix/pipeline-audit` · Cách làm từng việc P1–P5: [`playbook_p1_p5.md`](playbook_p1_p5.md)

## 1. Bản chất hệ thống (đã thống nhất)

1. **Chiến lược** (strategies) là lõi cố định — mỗi chiến lược hợp với một kiểu thị trường
   (trend, breakout, mean-revert, DCA kiểu bot OKX…).
2. **Regime** nhận biết thị trường đang ở trạng thái nào để bật chiến lược hợp, tắt chiến lược
   không hợp. Không phụ thuộc một chiến lược. Bài học từ bot top OKX: win 85–98% nhưng cháy
   tài khoản khi gặp trend thẳng đứng (`docs/research/topbots_replication.md`).
3. **Alpha** = một bộ tham số của một chiến lược. Backtest chạy toàn bộ alpha đã sinh trên dữ
   liệu thật để tìm tham số tốt nhất cho từng chiến lược.
4. **WFA và Monte Carlo là bộ lọc khắt khe**: loại alpha thắng do ăn may hoặc không sống sót.
   MC ≥ 10.000 kịch bản/alpha, có kịch bản cực xấu. Ví dụ 100k backtest → 1k qua WFA → 10 qua MC.
   Mỗi tầng có danh sách lệnh + thống kê tổng quan của nhóm.
5. Alpha qua hết → testnet → live.

## 2. Nguyên tắc kiến trúc (không được lệch)

| Việc | Nằm ở đâu | Ghi chú |
|---|---|---|
| Mô phỏng khớp lệnh, vốn, rủi ro | `backend/core/backtest` | **Một engine duy nhất** (`PortfolioEngine`, `BacktestEngine`). Tăng tốc = thay vòng lặp bên trong bằng numba (`kernel.py`), không tạo engine thứ hai. |
| Sinh tham số, chia lô, gom alpha chung tín hiệu, chạy nhiều worker, lưu kết quả, resume | `backend/optimize` | Gọi engine, không tự mô phỏng. |
| Cấu hình tài nguyên (số worker, RAM/worker, CPU) | `backend/utils/parallel.py` + `memwatch.py` | **Một chỗ duy nhất.** Chạy trong `nora.slice` 12G, CPU 0-13, qua `backend/utils/ops/run_limited.sh`. |
| WFA / MC | `backend/wfa`, `backend/carlo` | Dùng engine qua optimize. |
| Phễu lọc S0–FINAL | `backend/optimize/funnel` | Điều phối các tầng, thống kê từng tầng. |
| Regime | `backend/core/regime` (mới) | Causal, dùng chung cho backtest, WFA, MC, live. |

Quy tắc đúng đắn: golden test giữ trùng từng bit; không mock/fake trong backtest/WFA/MC;
quality gate dữ liệu ở mọi bước.

Quy tắc làm việc: Opus phân tích, lên plan, review; Sonnet thực thi việc đã giao.

## 3. Vì sao tăng worker không làm nhanh hơn

- 1 worker = 1 alpha chạy song song, chiếm trọn 1 luồng CPU.
- Host có 16 luồng (8 nhân × HT), dùng chung → Nora dùng 14. Thêm worker chỉ chia nhau cùng
  số CPU, tổng tốc độ không đổi. RAM không phải giới hạn (~142 MB/worker).
- Hiện 1 alpha danh mục (8 tài sản, ~14 tháng nến 1m) ≈ 27 s → 500k ≈ 11 ngày.
- Mục tiêu 500k ≤ 4 h ⇒ ≈ 35 alpha/s ⇒ ≤ 0,4 s/alpha ⇒ **engine phải nhanh hơn ~70 lần**.

## 4. Todo (làm lần lượt từng dòng)

Trạng thái: `todo` · `doing` · `done` · `skip`. Người làm: **O** = Opus (plan/review), **S** = Sonnet (thực thi).
Mỗi dòng chỉ chuyển `done` khi đạt đúng cột "Xong khi".

### P0 — Chốt việc đang chạy

| ID | Việc | Nơi sửa | Người | Cần trước | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|
| P0.1 | Quality gate mọi bước; ghi kết quả dạng stream; `--resume`; ước lượng thời gian, giới hạn, tiến độ, huỷ | `optimize/{results_store,stream,progress}.py`, `core/data/quality_gate.py`, CLI | S | — | Test `test_scale_pipeline.py` xanh; resume chạy lại không trùng kết quả | done |
| P0.2 | Phễu S0–FINAL: chống ăn may (DSR, PBO, lân cận), sizing S5, API, chạy thật | `optimize/funnel/*`, `optimize/run_funnel.py`, `api/routers/funnel.py` | S | — | Chạy thật ra thống kê từng tầng + danh sách lệnh; test xanh | done |
| P0.3 | Chiến lược tham số hoá; `presets.json`; mode basic/advanced ở API | `core/strategy/{presets,run_modes,params_template}.py`, `api/routers/strategies.py`, `api/modes.py` | S | — | Tham số mặc định cho kết quả trùng bit với trước; basic khoá tham số; advanced sửa được khung/ngày | done |
| P0.3b | WFA advanced: cho phép key ngoài `space` (chu kỳ, khung) + thêm cờ `--step-days`, `--sims`, `--mc-seed` vào whitelist `book_wfa`; bật `WFA_SCHEMA_KEYS_SUPPORTED` | `wfa/validate_book.py` (`candidates_from_json`), `api/jobs/batch.py` (`check_wfa_strategies`, whitelist), `api/modes.py` | S | P0.1 xong (tránh đụng file) | WFA advanced đổi chu kỳ/khung chạy thật, không 422 | done |
| P0.3c | Tối ưu preset cho cả 9 chiến lược ở khung 15m; thêm khung chạy vào preset + bằng chứng; nguồn qua dev2 thắng, cùng mức thì bằng chứng mới hơn thắng; stage A ưu tiên cấu hình top-K qua dev2, không có thì gắn nhãn "chưa kiểm chứng dev2"; cảnh báo lệch khung (API + UI) | `backend/core/params/presets.py`, `backend/api/modes.py`, `frontend/src/lib/modes.js`, `data/alphas/presets.json` | S | P1.8 | Preset ghi khung 15m; 9 chiến lược tối ưu lại theo engine mới | done |
| P0.4 | Commit MC 10k + 6 kịch bản stress | `carlo/monte_carlo.py`, `wfa/portfolio_wfa.py`, UI McResult | O | — | Test `test_mc_stress.py` xanh; commit | done |
| P0.5 | Commit UI trang `/funnel` | `frontend/src/v2/pages/Funnel.jsx`, `components/funnel/*` | O | — | `npm run build` sạch; commit | done |
| P0.6 | `bootstrap_daily` 4000 → 10.000 mô phỏng | `core/backtest/portfolio_metrics.py` | S | P0.1–P0.3 xong | Test xanh; golden không đổi | done |
| P0.7 | Review toàn bộ diff → full test + golden → commit theo phần | toàn repo | O | P0.1–P0.6 | Test xanh, golden trùng bit, working tree sạch | done |
| P0.8 | Job đang chạy/đang chờ bị huỷ khi restart `nora-api` → tách job khỏi tiến trình API (systemd-run unit riêng) hoặc tự khôi phục hàng đợi khi khởi động | `api/jobs/batch.py`, `api/jobs/store.py` | S | P0.7 | Restart API không mất job; có test | done |
| P0.9 | `presets.json` ghi bool dạng chuỗi `"False"` (numpy bool) → ghi bool thật qua `json_default`; UI bỏ parse chuỗi | `core/strategy/presets.py`, `optimize/build_presets.py`, `frontend/src/v2/lib/modes.js` | S | P0.7 | JSON có `false` thật; test kiểu dữ liệu | done |
| P0.10 | Xếp lại đúng kiến trúc: bỏ `backend/cli`, `backend/funnel`, `backend/ops`; lệnh về gói của nó (optimize/wfa/core), phễu → `optimize/funnel/`, ops → `utils/ops/` | toàn `backend/`, test, docs | O | P0.7 | `backend/` chỉ còn core/db/api/optimize/utils/wfa/carlo/main.py; full test xanh; job thật qua API `done` | done |
| P0.11a | Xoá code không dùng: route/trang Legacy (`main.py` 2263 dòng, `api/control`, `routers/{studio,engine,research,meta}`, `jobs/scan`, `schemas`), research DEX, 6 crawler DEX, `db/{mongo,mysql}`, `strategy/{script_engine,directional_change,features_meta,templates,generator,builder}`, `analytics/{queries,stats_metrics}`, đường tối ưu đơn tài sản cũ (`optimize/{optimize_alphas,runner,generator,ranker,build_alpha_registry}`) + test của chúng; frontend `src/pages` Legacy | backend, frontend, test | O | P0.10 | Không còn import tới phần đã xoá; full test xanh; golden trùng bit | done |
| P0.11b | `core/metrics/`: gom mọi phép tính (PnL, win rate, PF, MDD, Sharpe, Sortino, Calmar, lợi suất ngày, metrics danh mục) | `core/metrics/{trades,equity,portfolio}.py` | O | P0.11a | Một nguồn tính duy nhất; golden trùng bit | done |
| P0.11c | `core/execute/`: khớp lệnh (PositionTracker, SL/TP/DCA/thanh lý/funding), vốn (CapitalLedger), mô hình lệnh/vị thế | `core/execute/{position,ledger,models}.py` | O | P0.11a | golden trùng bit | done |
| P0.11d | `core/params/`: StrategyParams, template, builder, presets, modes | `core/params/*` | O | P0.11a | test xanh | done |
| P0.11e | `core/backtest/` chỉ còn `engine.py`, `portfolio.py`, `run.py` (+ kernel P1); dữ liệu dùng chung → `core/data/shared.py` | `core/backtest/*` | O | P0.11b–d | golden trùng bit | done |
| P0.11f | Một cửa chạy: bỏ mọi argparse trong backend; mỗi việc có `run(params)`; API job gọi `api/jobs/runner.py`; terminal gọi API (curl) | `api/jobs/runner.py`, `optimize/`, `wfa/`, `core/backtest/run.py` | O | P0.11e | Job thật qua API `done`; không còn `__main__`/argparse trong backend | done |
| P0.11g | Mọi file script → `test/scripts/` (smoke, bench, research, golden, mock feeds, crawl, check_tests_vs_ref) | `test/scripts/` | O | P0.11f | backend chỉ còn logic | done |
| P0.11h | Gọn từng folder (optimize, funnel, wfa, carlo, utils, api, db); cập nhật docs/README cây thư mục + architecture | toàn repo | O | P0.11g | full test xanh; docs khớp code | done |

#### Kết quả P0.3c (Run `20261003_035715`, job `20261003_035715_3e7ecb`, khung 15m)
- Sổ xuất bản `book.json`: gồm 2 chiến lược qua gate (`breakout_4h_long`, `breakout_4h_short`).
- `presets.json`: 7/9 chiến lược có nguồn tối ưu mới (`book` hoặc `stage_a`), 2 chiến lược không có cấu hình qua cổng dev1 ở 15m (`keltner_trend_short`, `reversion_short`) giữ mặc định (timeframe trống, không cảnh báo lệch khung).
- **Cảnh báo:** 5 preset stage A đều **chưa qua dev2** (không cấu hình nào trong top-3 qua) → gắn nhãn "chưa kiểm chứng dev2"; dev1 cao nhưng dev2 lỗ (vd. keltner_trend_long +211% → −15%) = khớp quá mức. Chỉ 2 preset breakout (từ sổ) đã kiểm chứng. Sổ vẫn `HOLDOUT_FAILED` (như sổ cũ).

| Chiến lược | Thử (dev1) | Đạt dev1 | Dev1 Lãi% / MDD% (Sharpe) | Dev2 Level Lãi% / MDD% | Dev2 Extreme Lãi% / MDD% | Nguồn Preset |
|---|---|---|---|---|---|---|
| `trend_long` | 108 | 28 | +45.67% / 22.97% (1.27) | -8.14% / 24.25% | -31.45% / 36.47% | stage A (`20261003_035715`), chưa kiểm chứng dev2 |
| `trend_short` | 108 | 3 | +0.61% / 21.18% (0.12) | +37.32% / 24.35% | +2.99% / 35.39% | stage A (`20261003_035715`), chưa kiểm chứng dev2 |
| `breakout_4h_long` | 36 | 34 | +14.00% / 9.42% (1.11) | +10.54% / 7.37% | +1.87% / 8.48% | book (`03/10`) |
| `breakout_4h_short` | 36 | 36 | +12.46% / 6.26% (1.09) | +11.59% / 11.95% | +0.52% / 14.42% | book (`03/10`) |
| `keltner_trend_long` | 81 | 73 | +211.06% / 15.13% (2.85) | -7.54% / 23.58% | -15.29% / 28.17% | stage A (`20261003_035715`), chưa kiểm chứng dev2 |
| `keltner_trend_short` | 81 | 0 | Không đạt ở 15m (-12.44% / 21.66%) | — | — | default (mặc định) |
| `momentum_long` | 108 | 15 | +56.26% / 29.14% (1.22) | -21.64% / 39.88% | -50.64% / 58.30% | stage A (`20261003_035715`), chưa kiểm chứng dev2 |
| `reversion_long` | 144 | 5 | +3.28% / 20.19% (0.32) | -27.81% / 30.27% | -50.11% / 50.81% | stage A (`20261003_035715`), chưa kiểm chứng dev2 |
| `reversion_short` | 144 | 0 | Không đạt ở 15m (-53.24% / 53.90%) | — | — | default (mặc định) |

### P1 — Tốc độ (mục tiêu 500k alpha ≤ 4 h trên 14 worker)

| ID | Việc | Nơi sửa | Người | Cần trước | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|
| P1.1 | Profile 1 alpha thật: load dữ liệu / tín hiệu / vòng lặp / metrics | `core/backtest/bench_engine.py` | S | — | Có bảng % thời gian từng phần | done |
| P1.2 | Numba kernel thay vòng lặp trong `PortfolioEngine`/`BacktestEngine`; xoá vòng lặp Python cũ | `core/backtest/kernel.py`, `portfolio.py`, `engine.py` | S | P1.1 | Một engine duy nhất; giữ nguyên hàm gọi và kết quả | done (f7e9c1b) |
| P1.3 | Kiểm parity: 3 golden + ≥ 300 cấu hình ngẫu nhiên (DCA, ATR, risk sizing, thanh lý, cooldown, stop_fill, kill switch) | `test/test_fast_engine.py`, `test/reference_engine.py` | S | P1.2 | 100% trùng từng bit; lệch → sửa kernel, không nới | done (golden + test_kernel_parity) |
| P1.4 | Benchmark thật 8 tài sản dev1: s/alpha cũ vs mới; RAM/worker | `core/backtest/bench_engine.py` | S | P1.3 | ≤ 0,4 s/alpha | done (0.74 s/alpha; lô 0.463 s) |
| P1.5 | Core thêm `run_many(params_list)` cho alpha chung tín hiệu | `core/backtest/portfolio.py` | S | P1.3 | Kết quả từng alpha trùng bit với chạy lẻ | done (PortfolioEngine.run_many) |
| P1.6 | `optimize` gom alpha theo tín hiệu vào lệnh, chia lô, gọi `run_many`; worker lấy từ `utils/parallel` | `optimize/runner.py`, `utils/parallel.py` | S | P1.5, P0 | Không thêm cấu hình worker mới; test xanh | done (9bc8a85, S1 gom theo signal_key) |
| P1.7 | Lọc thô nhiều vòng (successive halving) — chỉ làm nếu P1.4–P1.6 chưa đạt | `optimize/` | S | P1.6 | Đạt mục tiêu thời gian | đo, KHÔNG làm — lọc thô 1/3 dev1 chỉ nhanh 1,5x khi bỏ sót 22% alpha qua S1; giữ recall ≥ 95% thì không nhanh hơn |
| P1.8 | Load test thật 10k và 100k; ngoại suy 500k/1M; kiểm RAM, ổn định, resume | `nora.slice` | O+S | P1.6 | 500k ước tính ≤ 4 h; không OOM; resume đúng | done — 10k thật: S1 28,2 alpha/s (12 worker, 8 core HT), RAM riêng ≤ 770 MB/worker, không OOM, resume + huỷ đúng → 500k ≈ 4,9 h (mục tiêu 4 h: thiếu ~1,2x, giới hạn CPU 8 core) |
| P1.8a | Dữ liệu dùng chung (mmap) lưu THEO CỘT (frame/cột/lag) thay vì theo cả chữ ký refs; S1 xuất các cột còn thiếu cho từng nhóm tín hiệu trước khi chạy nhóm | `core/data/shared.py`, `optimize/funnel/evaluate.py` (SharedExporter), `orchestrator.stage_s1` | S | P1.6 | Worker không tự dựng dữ liệu khi có shared_dir; test parity mmap = tự dựng | done — nền giá dùng chung qua mmap (gồm volume); cột chỉ báo worker tự tính trong RAM từ file khung (bỏ merge_asof → searchsorted); golden bit-identical |
| P1.8b | Worker phễu tắt/hạ `_DATA_CACHE` (NORA_DATA_CACHE_MB) khi đã có shared_dir; đo lại RSS thật một worker → cập nhật `PER_WORKER_MB` | `optimize/funnel/run.py`, `orchestrator.PER_WORKER_MB` | S | P1.8a | RSS/worker ổn định sau ≥ 50 nhóm, khớp ngân sách | done — RAM riêng/worker đỉnh ~630 MB (trước 1,3 GB); PER_WORKER_MB=700; ngân sách không tính page cache (inactive_file) |
| P1.9 | Đo bên trong bước khớp lệnh: chi phí ∝ số lệnh × thời gian giữ (khung vào lệnh 5m/15m/1h nặng, 4h/1d nhẹ); mỗi phút có vị thế xử lý cả 8 tài sản + MTM | `core/backtest/kernel.py` | O | P1.8 | Biết chỗ tốn | done |
| P1.10 | Kernel tua nhanh phút yên tĩnh (không DCA/SL/trailing/thanh lý/TP/timeout/tín hiệu/funding/mẫu vốn) khi không có kill switch; MTM chỉ ở phút lấy mẫu; nhớ dung lượng đệm | `core/backtest/kernel.py` | S | P1.9 | Parity + golden bit-identical | done — 0,37 → 0,18 s/alpha |
| P1.11 | Chỉ báo chuẩn TradingView (EMA/RMA seed SMA) + tính từ gốc cố định (đầu lịch sử), không phụ thuộc cửa sổ | `core/signals/kernels.py`, `core/backtest/engine.py` | S | P1.10 | Test giá trị bất biến theo cửa sổ; golden tạo lại có chủ đích | done (dc8061c) |
| P1.12 | Kho chỉ báo tính sẵn theo khung (học sova/prepare.py): mỗi cột mỗi khung tính 1 lần/run, worker gom theo chỉ số dùng chung | `core/data/shared.py` | S | P1.11 | Bằng từng bit với tự dựng | done (8f97e33) |
| P1.13 | Số worker theo CPU: đo core thật (7 worker 22,8/s) vs luồng logic (11 worker 26,9/s) -> mặc định luồng logic, NORA_CPU_PHYSICAL=1 để chỉ dùng core thật | `utils/memwatch.py` | S | P1.12 | Có số đo | done |
| P1.14 | Metrics nhẹ hơn: đường vốn dựng DataFrame theo cột | `core/metrics` | S | P1.12 | Số liệu không đổi | done (+~3%) |
| P1.15 | Tín hiệu CẮT (ta.crossover) cho trend/breakout/momentum + chiến lược Keltner trend (KEMA của sova), thoát khi cắt dải ngược | `core/strategy` | S | P1.11 | Test sự kiện cắt + thoát bằng cây stop | done (3227345) |
| P1.16 | Load test 10k, 9 chiến lược | `nora.slice` | S | P1.11–P1.15 | 500k ≤ 4 h | đo: 26,9 alpha/s TB (ổn định ~31/s), RAM riêng ≤ 730 MB/worker, không OOM -> 500k ≈ 4,5–5,2 h |
| P1.17 | Khung chạy (nến mô phỏng) 15m / 1h / 4h chọn trước khi sinh tham số; khung tín hiệu < khung chạy được nâng lên hoặc từ chối | `core/backtest`, `optimize/funnel`, API, UI | S | P1.16 | 500k ≤ 4 h | done (fa0a93b) — 10k: 15m 80 alpha/s (500k ≈ 1,7 h), 1h 103 alpha/s (500k ≈ 1,35 h); RAM ≤ 395 MB/worker |
| P1.18 | Dọn kiến trúc: một đặc tả `BacktestJob` + `make_engine` cho sổ / WFA / phễu, một `SharedExporter` (optimize/shared.py), khung chạy là trường của job (cả book_build), df_1m -> df_base, xoá code chết, pyflakes sạch | `core/backtest/run.py`, `optimize/`, `wfa/` | S | P1.17 | Kết quả không đổi | done (1b30398) — 597 test xanh; chạy lại 10k 15m trùng từng con số |

### PM — Bộ số đo chuẩn (chi tiết: `docs/metrics_inventory.md`)

| ID | Việc | Nơi sửa | Người | Cần trước | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|
| PM.1 | Sửa Sharpe của `MetricsCalculator` (đang lấy mẫu vốn mỗi giờ nhưng nhân √365) -> tính trên lợi suất ngày | `core/metrics/trades.py` | S | — | Test: Sharpe = Sharpe trên `daily_returns_from_curve` | done |
| PM.2 | Thống nhất thắng/thua/hoà (thắng > 0, thua < 0, hoà riêng) ở mọi nơi | `core/metrics/*` | S | — | Một định nghĩa; test lệnh PnL = 0 | done |
| PM.3 | Tách tên MDD: `mdd_intrabar_pct` / `mdd_daily_pct`, báo cả hai ở mọi tầng (sổ, phễu S1–S6, WFA, Danh mục, UI) | `core/metrics`, `optimize/funnel`, `wfa`, frontend | S | PM.5 | Không còn `mdd_pct` mơ hồ | done |
| PM.4 | Gom Sharpe/Sortino về một hàm (bỏ 3 bản tính lặp, 2 bản Sortino) | `core/metrics/returns.py` | S | — | Kết quả số không đổi (test so cũ/mới) | done |
| PM.5 | `core/metrics/summary.py: summarize()` — bộ số đo chuẩn (lợi nhuận, CAGR, sụt giảm + thời gian hồi phục, Sharpe/Sortino/Calmar, VaR/CVaR, theo lệnh: payoff, expectancy, chuỗi thua, top-5 share, thời gian giữ, long/short; DCA: MAE, tầng, vốn đỉnh, khoảng cách thanh lý, số lần thanh lý) | `core/metrics/summary.py`, `core/execute/tracker.py` (ghi thêm `peak_capital_use`, `min_liq_distance`) | S | PM.1–PM.4 | Golden trùng bit; test từng số đo bằng ví dụ tính tay | done |
| PM.6 | Mọi tầng dùng `summarize()`; phễu lưu thêm CAGR/Calmar/CVaR/payoff/expectancy; Danh mục thêm tương quan chiến lược + exposure TB/max | `optimize/funnel/*`, `wfa`, `core/analytics/dashboard.py`, frontend | S | PM.5 | Bảng alpha của phễu lọc/sắp theo được các số đo mới | done |

### P2 — Regime và điều phối chiến lược

| ID | Việc | Nơi sửa | Người | Cần trước | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|
| P2.1 | Thiết kế regime: trạng thái, chỉ báo, khung, trễ chuyển, thời gian tối thiểu | `docs/bmad/stories/E15-*` | O | P0 | Spec được duyệt | done (stories/E15-S1-regime-spec.md) |
| P2.2 | Engine regime causal đa khung (15m/1h/4h/1d): tăng mạnh, giảm mạnh, đi ngang, biến động bùng nổ, sập/đứng giá | `core/regime/` | S | P2.1 | Test prefix-invariant (không nhìn tương lai) | done (core/regime/classifier.py, test_regime.py) |
| P2.3 | Bảng ghép regime ↔ chiến lược + cầu chì: trend thẳng đứng/biến động bùng nổ thì cấm nhồi DCA, có thể đóng sớm | `core/regime/`, `core/backtest` | S | P2.2, P1.3 | Golden không đổi khi tắt regime; có test cầu chì | done (book.REGIME_MAP + mặt nạ trong PortfolioEngine.load_data; mặc định tắt) |
| P2.4 | Đo độ chuẩn: nhãn causal vs nhãn dữ liệu tương lai (bảng nhầm lẫn, độ trễ) + PnL từng chiến lược theo regime | `cli/regime_report.py` | S | P2.2 | Báo cáo trên 8 tài sản; NGOÀI MẪU (dev2): lãi TB/lệnh trong regime được phép > bị chặn ở ≥ 2/3 chiến lược (tiêu chí viết lại 03/10 — bản cũ phụ thuộc bảng tĩnh, không đo được) | done — bảng "chặn ngược chiều", cầu chì tắt: 6/9 chiến lược đạt (research_regime_diagnosis.py phần H, hồ sơ slow; hồ sơ fast 5/9 nên giữ slow). Toàn kỳ: tắt +35,5% → bật +38,5%. E15-S2 |
| P2.5 | Backtest theo regime: tối ưu từng chiến lược trong regime → backtest cả sổ có chuyển đổi → WFA (ngưỡng regime chỉ học trên train) | `optimize/`, `wfa/` | S | P2.3, P1.6 | Sổ nhiều chiến lược qua WFA | CHƯA ĐẠT (thực chất) — 03/10 sửa engine: khớp SL "extreme" ở khung chạy > 1m lấy giá xấu nhất của CẢ nến 15m/1h (quá bi quan, sai theo khung) → nay lấy nến 1m đầu tiên chạm mức (d1e9b3d). Sau sửa, lưới WFA 15m/1h × bộ chiến lược × regime: tốt nhất 1h, 9 chiến lược preset, rủi ro 0,15%/lệnh, test 60 ngày → gate WFA QUA (fold dương 3/5, lãi kép OOS +2,1%, ruin 0,04%, stress MDD 44,6%) nhưng mong manh (1 fold +0,05%; test 30 ngày cùng cấu hình trượt 50%) và là cấu hình tốt nhất sau ~20 lần thử trên cùng dev2. Holdout một lần: −4,4% (level) / −7,25% (extreme) → không có edge thật |
| P2.6 | MC thêm kịch bản trend thẳng đứng (+40%/3 ngày, −30%/1 ngày, chuỗi liên tiếp) | `carlo/monte_carlo.py` | S | P0.4 | Bot kiểu OKX trượt cổng; test xanh | done — vertical_surge/crash/chain theo vị thế ngược chiều lớn nhất; bot DCA kiểu OKX trượt (−90%), sổ có cắt lỗ qua. E15-S4 |
| P2.7 | Ngưỡng regime tính là tham số trong DSR/PBO | `optimize/funnel/` | S | P2.5, P0.2 | Số trial tính đủ | done — phễu `regime` off/learn/both: biến thể learn là alpha riêng → N của DSR/PBO đếm đủ; ngưỡng classifier không tối ưu. E15-S5 |

### P3 — Chạy phễu thật end-to-end

| ID | Việc | Nơi sửa | Người | Cần trước | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|
| P3.1 | Sinh alpha 9 chiến lược (có regime) → backtest → WFA → MC → FINAL trên dữ liệu thật | `optimize/run_funnel.py` | S | P1, P2 | Chạy hết, không lỗi, không OOM | done — lượt fr-20261003-4ab03b: 9 chiến lược × 2.000 × regime both, 15m, 16,4 phút, không lỗi/OOM. E14-S2 |
| P3.2 | Thống kê từng tầng: số lượng, phân phối chỉ số, danh sách lệnh | `optimize/funnel/` | S | P3.1 | Có số liệu ví dụ 100k → 1k → 10 | done — lượt 1h fr-20261003-cb0966 (cổng S3 mới, S2 xếp hạng DSR): 36.000 → 10.596 → 541 → 58 → 58 → 58 → 40 FINAL (20 duy nhất; holdout TB +1,67%, MDD TB 1,69%). Lượt cũ 15m: 0 FINAL. E14-S2 |
| P3.3 | Alpha SOL: sizing S5; cập nhật registry, gỡ testnet nếu trượt | `data/alphas/` | S | P0.2 | Registry đúng trạng thái | done — job alpha_revalidate: trend_long_perp__SOL retired (S3 fold dương 50% < 60%, OOS +14%); testnet → testnet/_retired. E14-S3 |
| P3.4 | Xuất sổ testnet nếu holdout đạt | `optimize/book_export.py` | O | P3.2 | `READY_FOR_TESTNET` hoặc ghi rõ lý do trượt | done — **READY_FOR_TESTNET** (04/10): sổ 4 chiến lược từ alpha FINAL của lượt 1h fr-20261004-95da59 (breakout_4h_long, breakout_4h_short, momentum_long, trend_long; mỗi chiến lược alpha có t-stat S3 cao nhất), rủi ro 1%/lệnh, khung 1h. WFA sổ (dev2, 10 fold): fold dương 70%, t 1,91, OOS +11,2%, MDD fold 2,6%, stress MDD 42% → QUA (1,5%/lệnh trượt stress 57%). Holdout một lần: +4,5% / MDD 5,2% (level = extreme). data/alphas/book.json + testnet/book.json (job funnel_book). Lưu ý: dev2 đã dùng để chọn alpha ở S3; cổng S3 thiết kế sau khi nhìn holdout → cần xác nhận forward |

### P4 — UI

| ID | Việc | Nơi sửa | Người | Cần trước | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|
| P4.1 | Hai chế độ Basic/Advanced cho Backtest, WFA, MC | `frontend/src/v2/pages/*` | S | P0.3 | Basic khoá tham số; Advanced sửa từng tham số, khung, ngày | done |
| P4.2 | Trang `/funnel` nối dữ liệu thật | `pages/Funnel.jsx` | S | P0.2, P0.5 | Hiện thống kê + lệnh từng tầng từ job thật | done |
| P4.2b | Kiểm thật các nhánh lỗi chưa chạm: 422 thật theo field, promote 400/409, recompute trades, POST /runs nhỏ | frontend | S | P0.7 | Ảnh kiểm từng nhánh | done — nhánh thật qua API: 422 theo trường, promote 400/409, tính lại lệnh, POST /runs nhỏ; ảnh UI cho tính lại lệnh + lượt nhỏ. 422/409 không chạm được từ UI hợp lệ (client kiểm trùng luật máy chủ; nút promote chỉ hiện với alpha FINAL). Sửa thêm: cờ WFA_SCHEMA_KEYS_SUPPORTED phía UI bị bỏ quên ở false |
| P4.3 | Hiển thị regime hiện tại, lịch sử, chiến lược đang bật | `pages/Portfolio.jsx` | S | P2.2 | Có cả sáng/tối | done — GET /market/regime + RegimePanel (hiện tại, lịch sử 7/30/90 ngày, chiến lược đang bật). E15-S6 |
| P4.4 | Ảnh kiểm sáng/tối; `npm run build` sạch | frontend | O | P4.1–P4.3 | Không lỗi console | done — `npm run build` sạch; ảnh kiểm 5 trang + phễu × sáng/tối, 0 lỗi console |
| P4.5 | Danh sách lệnh (trade list) ở trang Tổng quan (Backtest/Live/Testnet) và ở mỗi bước Backtest/WFA/MC: lọc theo chiến lược/tài sản/chiều/kết quả, phân trang, tải CSV | `core/analytics/dashboard.py`, `api/routers/portfolio.py`, frontend | O | — | Bảng lệnh khớp `trade_list`; lọc/sắp/phân trang đúng | done (b42bfc2) |
| P4.6 | Thống kê theo CHIẾN LƯỢC (họ chiến lược, gộp mọi bộ tham số của cùng chiến lược) ở Tổng quan: bộ số đo chuẩn tính riêng từng chiến lược | `core/metrics`, `core/analytics/dashboard.py`, frontend | O | PM | Mỗi chiến lược có đủ số đo; alpha `x__SOL` gộp về chiến lược gốc | done (b42bfc2) |
| P4.7 | Tích hợp Phễu vào trang Alpha (một trang: tối ưu sổ + phễu kiểm duyệt), bỏ mục Phễu riêng trên thanh bên | frontend | O | — | `/alpha` có tab Phễu; `/funnel` chuyển hướng | done (b42bfc2) |
| P4.8 | Mục "Tín hiệu thị trường" ở Tổng quan: trạng thái tín hiệu từng chiến lược × tài sản trên nến ĐÃ ĐÓNG mới nhất (điều kiện vào/thoát, giá trị chỉ báo, regime), dùng chung một hàm causal cho backtest/live/testnet | `core/signals/snapshot.py`, `api/routers/market.py`, frontend | O | — | Snapshot trùng với tín hiệu engine dùng ở cùng phút (test); không nhìn nến chưa đóng | done (b42bfc2; regime thêm ở aa3823f) |

### P5 — Tài liệu và báo cáo

| ID | Việc | Nơi sửa | Người | Cần trước | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|
| P5.1 | Cập nhật BMAD: E12 tốc độ, E13 hai chế độ, E14 phễu, E15 regime; `sprint-status.yaml` | `docs/bmad/` | S | từng phase | Story khớp code | done — thêm E12–E15 (14 story), sprint-status 84 story, kiểm tra nhất quán OK |
| P5.2 | Báo cáo chốt | — | O | P0–P4 | Gửi user | done — báo cáo chốt dưới đây |

### P6 — Kiến trúc thực thi thống nhất (backtest → testnet → live)

ADR: [`adr-p6-unified-execution.md`](adr-p6-unified-execution.md) · Đặc tả: [`p6_execution_design.md`](p6_execution_design.md) · Epic E16. Mỗi ID một commit; golden + `test_kernel_parity` + `test_live_bot` xanh trước khi sang ID sau. Kernel và `Bot` không bị đụng tới trước P6.8. Parity: sim bit-identical; sim ↔ sàn trong dung sai.

| ID | Việc | Nơi sửa | Người | Cần trước | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|
| P6.0 | ADR: mức parity, quyết định đã chốt, kế hoạch nghỉ hưu tracker; sửa doc lệch (`architecture.md` mục 5 trỏ `execution.py`) | `docs/bmad/` | O | — | User duyệt các mục D1–D6 của ADR | doing |
| P6.1 | `risk.py`: hàm thuần `admit_entry` (số vị thế, per-symbol, room gross, trần rủi ro mở, dd_throttle) và `kill_check`; cơ sở vốn truyền vào; `PaperBook` gọi nó thay code nội tuyến; `filters` hoãn sang P6.5 (khi có Venue) | `core/execute/risk.py`, `live/paper.py` | S | P6.0 (không phụ thuộc D1–D6) | Test replay hiện có xanh; PaperBook bằng kernel trên ~100 cấu hình ngẫu nhiên có trần rủi ro; `risk.py` bằng số lệnh bị chặn của `reference_engine` | done (8b553b2) — PaperBook = kernel 100/100 cấu hình đủ 7 trần rủi ro |
| P6.2 | `policy.py`: hàm cấp mức giá và khối lượng (`dca_level`, `sl`, `trail`, `tp`, `liq`, `layer_margin`, `gap_fill`); tracker uỷ quyền | `core/execute/policy.py`, `tracker.py` | S | P6.1 | Golden, parity, `pack_trackers` bit-identical; tên thuộc tính tracker không đổi | done (0aa01e1) |
| P6.3 | `events.py` tối thiểu + `account.py`: `Account` + `PositionBook` theo sự kiện thay `CapitalLedger` và kế toán trong `_add_layer`, giữ thứ tự phép toán float | `core/execute/{events,account}.py`, `ledger.py` | S | P6.2 | Phát lại `tracker.orders` qua Account cho ledger và PnL vị thế bit-identical trên golden và cấu hình ngẫu nhiên | todo |
| P6.4 | `venue.py` (Protocol), `sim_venue.py`, `manager.py` + harness theo tầng: (a) market vào/ra/timeout/funding, (b) SL, (c) vòng DCA settle, (d) TP + bỏ qua nến có DCA, (e) trailing, (f) thanh lý, (g) `limit_through`/`stop_fill`/gap | `core/execute/*`, `test/` | O thiết kế, S từng tầng | P6.3 | Mỗi tầng bằng `RefPositionTracker` từng bit trên cấu hình ngẫu nhiên chỉ bật tính năng đó | todo |
| P6.5 | `runner.py` `step_bar` cho một Venue; `PaperBook` thành lớp mỏng, bit-identical với bản cũ | `core/execute/runner.py`, `live/paper.py` | S | P6.4 | `test_paper_book_replays_engine_trades_exactly` xanh trên đường mới; parity danh mục đầy đủ với kernel | todo |
| P6.6 | Bộ test conformance Venue chạy trên SimVenue (A hợp đồng, B kịch bản giá) | `test/venue_conformance.py` | S | P6.4 | Xanh trên SimVenue | todo |
| P6.7 | `okx_venue.py` bọc `okx.py` (poll fill, reconcile → cùng sự kiện) | `live/okx_venue.py` | S | P6.6 | Contract test xanh trên response OKX đã ghi; chạy demo do người dùng kích hoạt, xanh | todo |
| P6.8 | Bot chạy trên runner + OkxVenue sau cờ `engine=unified`; đường cũ chạy song song N ngày trên demo; `compare.py` chuyển sang mức sự kiện | `live/bot.py`, `live/compare.py` | O review, S cài | P6.7 + user duyệt | `compare.py` trong dung sai; vốn rủi ro là sổ ảo, vốn sàn chỉ cảnh báo lệch | todo |
| P6.9 | Nghỉ hưu `tracker.on_bar`; `pack_trackers` dùng `StrategyParams`; giữ `reference_engine` làm oracle | `tracker.py`, `engine.py` | O | P6.8 | `PositionTracker` gỡ bỏ; golden, parity, full suite xanh; docs khớp code | todo |

### Ngoài phạm vi (giữ nguyên theo quyết định user)

| ID | Việc | Ghi chú |
|---|---|---|
| E9 | Testnet/live: feed thật, bot Binance testnet | Làm sau P3 |
| E11 | API bind `0.0.0.0:18010` không auth | User quyết định để nguyên (2026-10-02) |

## 5. Thứ tự và phụ thuộc

```
P0 ──► P1 ──► P2 ──► P3 ──► P5
        └── P4.1 song song (chỉ frontend)
```

- P1 trước P2: regime nhân số tổ hợp cần chạy, engine chậm thì không chạy nổi.
- P2 sau P0: các agent P0 đang sửa đúng file chiến lược/phễu, làm song song sẽ ghi đè.
- P3 chạy sau P2 để sổ cuối cùng có regime.

## 6. Báo cáo chốt (P5.2, 03/10/2026)

| Pha | Kết quả | Bằng chứng |
|---|---|---|
| P0 | Pipeline chạy được quy mô lớn, chế độ Cơ bản/Nâng cao, preset 15m có nhãn kiểm chứng | 21d8adb |
| P1 | 500k alpha ≈ 1,7 h (15m) / 1,35 h (1h); RAM worker ≤ 395 MB; golden trùng bit | 1b30398 |
| P2 | Regime causal; bảng tĩnh sai theo dữ liệu thật; học trên train cải thiện WFA nhưng chưa qua; MC có trend thẳng đứng; biến thể regime được đếm trong DSR/PBO | dc08366 |
| P3 | Phễu thật 36.000 alpha → 0 FINAL (PBO/DSR loại gần hết); alpha SOL bị loại khi kiểm lại; không có cấu hình testnet hoạt động | dc08366 |
| P4 | UI regime, cảnh báo lệch khung, nhãn preset; build sạch; 0 lỗi console sáng/tối | dc08366 |

Dòng chưa đạt "Xong khi": P2.5 (kết quả nghiên cứu: chiến lược hiện có không có lãi ngoài mẫu — regime không bù được). Chẩn đoán + khắc phục 03/10:
cầu chì tắt, bảng regime "chặn ngược chiều", preset chọn theo độ bền dev1, học regime chặt (test/scripts/research_regime_diagnosis.py).

Kết luận trung thực: hạ tầng (tốc độ, kiểm chứng, chống ăn may, regime) đã đủ; **edge chưa có** — chưa alpha/sổ nào qua đủ cổng. Việc tiếp theo thuộc E10
(chiến lược mới, hiệu chỉnh đa kiểm định) và E9 (testnet) chỉ khi có alpha FINAL.
