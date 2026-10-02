# Nora — Kế hoạch triển khai (nguồn duy nhất)

Cập nhật: 2026-10-02 · Nhánh: `fix/pipeline-audit` · Cách làm từng việc P1–P5: [`playbook_p1_p5.md`](playbook_p1_p5.md)

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
| P0.3c | Tối ưu preset cho trend_short, reversion_long, reversion_short (đang dùng mặc định chưa tối ưu) | `optimize/build_presets.py`, `data/alphas/presets.json` | S | P1.4 (engine nhanh) | Preset có nguồn tối ưu, ghi rõ bằng chứng | chuyển sang P1 (cần P1.4) |
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

### P1 — Tốc độ (mục tiêu 500k alpha ≤ 4 h trên 14 worker)

| ID | Việc | Nơi sửa | Người | Cần trước | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|
| P1.1 | Profile 1 alpha thật: load dữ liệu / tín hiệu / vòng lặp / metrics | `core/backtest/bench_engine.py` | S | — | Có bảng % thời gian từng phần | doing |
| P1.2 | Numba kernel thay vòng lặp trong `PortfolioEngine`/`BacktestEngine`; xoá vòng lặp Python cũ | `core/backtest/kernel.py`, `portfolio.py`, `engine.py` | S | P1.1 | Một engine duy nhất; giữ nguyên hàm gọi và kết quả | doing |
| P1.3 | Kiểm parity: 3 golden + ≥ 300 cấu hình ngẫu nhiên (DCA, ATR, risk sizing, thanh lý, cooldown, stop_fill, kill switch) | `test/test_fast_engine.py`, `test/reference_engine.py` | S | P1.2 | 100% trùng từng bit; lệch → sửa kernel, không nới | doing |
| P1.4 | Benchmark thật 8 tài sản dev1: s/alpha cũ vs mới; RAM/worker | `core/backtest/bench_engine.py` | S | P1.3 | ≤ 0,4 s/alpha | todo |
| P1.5 | Core thêm `run_many(params_list)` cho alpha chung tín hiệu | `core/backtest/portfolio.py` | S | P1.3 | Kết quả từng alpha trùng bit với chạy lẻ | todo |
| P1.6 | `optimize` gom alpha theo tín hiệu vào lệnh, chia lô, gọi `run_many`; worker lấy từ `utils/parallel` | `optimize/runner.py`, `utils/parallel.py` | S | P1.5, P0 | Không thêm cấu hình worker mới; test xanh | todo |
| P1.7 | Lọc thô nhiều vòng (successive halving) — chỉ làm nếu P1.4–P1.6 chưa đạt | `optimize/` | S | P1.6 | Đạt mục tiêu thời gian | todo |
| P1.8 | Load test thật 10k và 100k; ngoại suy 500k/1M; kiểm RAM, ổn định, resume | `nora.slice` | O+S | P1.6 | 500k ước tính ≤ 4 h; không OOM; resume đúng | todo |

### P2 — Regime và điều phối chiến lược

| ID | Việc | Nơi sửa | Người | Cần trước | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|
| P2.1 | Thiết kế regime: trạng thái, chỉ báo, khung, trễ chuyển, thời gian tối thiểu | `docs/bmad/stories/E15-*` | O | P0 | Spec được duyệt | todo |
| P2.2 | Engine regime causal đa khung (15m/1h/4h/1d): tăng mạnh, giảm mạnh, đi ngang, biến động bùng nổ, sập/đứng giá | `core/regime/` | S | P2.1 | Test prefix-invariant (không nhìn tương lai) | todo |
| P2.3 | Bảng ghép regime ↔ chiến lược + cầu chì: trend thẳng đứng/biến động bùng nổ thì cấm nhồi DCA, có thể đóng sớm | `core/regime/`, `core/backtest` | S | P2.2, P1.3 | Golden không đổi khi tắt regime; có test cầu chì | todo |
| P2.4 | Đo độ chuẩn: nhãn causal vs nhãn dữ liệu tương lai (bảng nhầm lẫn, độ trễ) + PnL từng chiến lược theo regime | `cli/regime_report.py` | S | P2.2 | Báo cáo trên 8 tài sản; chiến lược lãi trong regime của nó | todo |
| P2.5 | Backtest theo regime: tối ưu từng chiến lược trong regime → backtest cả sổ có chuyển đổi → WFA (ngưỡng regime chỉ học trên train) | `optimize/`, `wfa/` | S | P2.3, P1.6 | Sổ nhiều chiến lược qua WFA | todo |
| P2.6 | MC thêm kịch bản trend thẳng đứng (+40%/3 ngày, −30%/1 ngày, chuỗi liên tiếp) | `carlo/monte_carlo.py` | S | P0.4 | Bot kiểu OKX trượt cổng; test xanh | todo |
| P2.7 | Ngưỡng regime tính là tham số trong DSR/PBO | `optimize/funnel/` | S | P2.5, P0.2 | Số trial tính đủ | todo |

### P3 — Chạy phễu thật end-to-end

| ID | Việc | Nơi sửa | Người | Cần trước | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|
| P3.1 | Sinh alpha 7 chiến lược (có regime) → backtest → WFA → MC → FINAL trên dữ liệu thật | `optimize/run_funnel.py` | S | P1, P2 | Chạy hết, không lỗi, không OOM | todo |
| P3.2 | Thống kê từng tầng: số lượng, phân phối chỉ số, danh sách lệnh | `optimize/funnel/` | S | P3.1 | Có số liệu ví dụ 100k → 1k → 10 | todo |
| P3.3 | Alpha SOL: sizing S5; cập nhật registry, gỡ testnet nếu trượt | `data/alphas/` | S | P0.2 | Registry đúng trạng thái | todo |
| P3.4 | Xuất sổ testnet nếu holdout đạt | `optimize/book_export.py` | O | P3.2 | `READY_FOR_TESTNET` hoặc ghi rõ lý do trượt | todo |

### P4 — UI

| ID | Việc | Nơi sửa | Người | Cần trước | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|
| P4.1 | Hai chế độ Basic/Advanced cho Backtest, WFA, MC | `frontend/src/v2/pages/*` | S | P0.3 | Basic khoá tham số; Advanced sửa từng tham số, khung, ngày | done |
| P4.2 | Trang `/funnel` nối dữ liệu thật | `pages/Funnel.jsx` | S | P0.2, P0.5 | Hiện thống kê + lệnh từng tầng từ job thật | done |
| P4.2b | Kiểm thật các nhánh lỗi chưa chạm: 422 thật theo field, promote 400/409, recompute trades, POST /runs nhỏ | frontend | S | P0.7 | Ảnh kiểm từng nhánh | todo |
| P4.3 | Hiển thị regime hiện tại, lịch sử, chiến lược đang bật | `pages/Portfolio.jsx` | S | P2.2 | Có cả sáng/tối | todo |
| P4.4 | Ảnh kiểm sáng/tối; `npm run build` sạch | frontend | O | P4.1–P4.3 | Không lỗi console | todo |

### P5 — Tài liệu và báo cáo

| ID | Việc | Nơi sửa | Người | Cần trước | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|
| P5.1 | Cập nhật BMAD: E12 tốc độ, E13 hai chế độ, E14 phễu, E15 regime; `sprint-status.yaml` | `docs/bmad/` | S | từng phase | Story khớp code | todo |
| P5.2 | Báo cáo chốt | — | O | P0–P4 | Gửi user | todo |

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
