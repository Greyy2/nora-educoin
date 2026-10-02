# Hướng dẫn tự làm P1 → P5

Đi kèm `roadmap.md` (bảng trạng thái). File này nói **làm thế nào** cho từng dòng: bước, file, lệnh kiểm, bẫy hay gặp.
Làm **đúng thứ tự**, xong dòng nào thì sửa cột "Trạng thái" trong `roadmap.md` dòng đó.

## 0. Luật chung (áp cho mọi việc)

| Luật | Cách làm |
|---|---|
| Chạy Python | Luôn qua `backend/utils/ops/run_limited.sh` từ thư mục `nora/`. Lệnh nhẹ thêm `--no-lock`. Ví dụ: `backend/utils/ops/run_limited.sh --no-lock -- -m pytest -q test/test_golden_results.py` |
| Biến môi trường | `export PYTHONDONTWRITEBYTECODE=1` trước khi chạy |
| Golden | Sau MỌI thay đổi engine: `test/test_golden_results.py` phải xanh (trùng từng bit). Không chạy `test/make_golden.py` trừ khi CỐ Ý đổi luật khớp lệnh |
| Một engine | Không tạo engine thứ hai. Tăng tốc = sửa ruột `PortfolioEngine`/`BacktestEngine` |
| Một chỗ cấu hình worker | `backend/utils/parallel.py` + `backend/utils/memwatch.py`. Không thêm biến/cờ worker ở chỗ khác |
| Dữ liệu thật | Không mock trong backtest/WFA/MC. Quality gate (`require_data_ok`) đã chặn sẵn |
| Full test | `backend/utils/ops/run_limited.sh -- -m pytest test -q -p no:cacheprovider` (~16 phút). Chạy trước mỗi commit |
| Commit | Nhỏ, theo từng ID (vd `perf(engine): P1.2 numba kernel`) |

---

## P1 — Tốc độ (mục tiêu ≤ 0,4 s/alpha, 500k ≤ 4 h trên 14 worker)

### Hiện trạng file (đã có trên đĩa, CHƯA commit)

| File | Tình trạng |
|---|---|
| `backend/core/backtest/kernel.py` (869 dòng) | Vòng lặp numba, chưa gắn vào engine |
| `backend/core/backtest/_kernel_io.py` (381 dòng) | Chuyển dữ liệu engine ↔ mảng numpy cho kernel |
| `test/reference_engine.py` (1148 dòng) | Bản sao engine Python cũ để so (chỉ dùng trong test) |
| `test/test_kernel_parity.py` (576 dòng) | 16 test đạt; **2 test trượt**: `test_account_ruin_path` (cháy tài khoản), `test_empty_after_halt_and_no_signal_paths` (sau kill switch) |
| `backend/core/backtest/bench_engine.py` | Đo thời gian, chưa có số liệu |
| `requirements.txt` | Chưa ghim `numba` |

### P1.1 Profile
1. `backend/utils/ops/run_limited.sh --no-lock -- -m backend.core.backtest.bench_engine --help` → xem tham số.
2. Chạy 1 alpha thật (breakout_4h_long mặc định, 8 tài sản perp, cửa sổ dev1) với cProfile.
3. Ghi bảng % thời gian: nạp dữ liệu / tín hiệu (VectorEvaluator) / vòng lặp / metrics vào `docs/bmad/stories/E12-S6-profile.md`.
- **Xong khi:** biết vòng lặp chiếm bao nhiêu %. Nếu tín hiệu chiếm lớn → P1.5 (dùng chung tín hiệu) quan trọng hơn numba.

### P1.2–P1.3 Kernel trùng từng bit
1. Ghim numba: `uv pip install -p /home/vmc03/.venvs/nora/bin/python numba`, thêm dòng `numba==<phiên bản>` vào `requirements.txt`.
2. Sửa 2 test trượt trước:
   - `NORA_PARITY_CONFIGS=6 backend/utils/ops/run_limited.sh --no-lock -- -m pytest test/test_kernel_parity.py -q -k ruin`
   - So từng trường kết quả (hàm `assert_bit_identical` in trường lệch đầu tiên). Hay gặp: thứ tự phép cộng phí/funding khi vốn ≤ 0; cờ `ruined_at`; không mở lệnh sau khi halt; mẫu equity sau halt.
   - Sửa **kernel**, không sửa test, không nới so sánh.
3. Chạy đủ: `backend/utils/ops/run_limited.sh -- -m pytest test/test_kernel_parity.py -q` (mặc định 330 cấu hình). Phải xanh 100%.
4. Gắn vào engine (diff nhỏ nhất): trong `PortfolioEngine.run()` và `BacktestEngine.run()` thay thân vòng lặp từng phút bằng gọi kernel qua `_kernel_io`; giữ nguyên chữ ký hàm, `get_results()`.
5. Xoá vòng lặp Python cũ trong engine (bản cũ chỉ còn ở `test/reference_engine.py`).
6. Kiểm: golden + parity + full test.
- **Bẫy:** numba biên dịch lần đầu mất vài giây → dùng `cache=True`; đừng đo lần đầu khi benchmark. Phép toán phải cùng thứ tự với Python (`a*b+c` khác `c+a*b` ở bit cuối). Không dùng `fastmath`.

### P1.4 Benchmark thật
1. `bench_engine` so cũ (reference) vs mới trên 8 tài sản dev1, 3 lần, lấy trung vị.
2. Ghi: s/alpha, RAM/worker (`VmHWM`), ngoại suy 10k/100k/500k với 14 worker = `N × s / 14`.
- **Xong khi:** ≤ 0,4 s/alpha. Chưa đạt → P1.5, P1.6, rồi mới P1.7.

### P1.5 `run_many`
1. Thêm `PortfolioEngine.run_many(params_list)`: nạp dữ liệu + tính tín hiệu **một lần**, gọi kernel cho từng bộ tham số vị thế.
2. Chỉ gom các alpha có **cùng tham số tín hiệu** (khoá `sig.*` giống nhau); khác tín hiệu → lần gọi khác.
3. Test: kết quả từng alpha trong `run_many` == chạy lẻ (trùng bit).

### P1.6 Optimize gom alpha
1. `backend/optimize/runner.py` (và các CLI dùng `pool_imap_bounded`): nhóm job theo khoá tín hiệu, mỗi job worker = 1 nhóm (cắt nhóm ≤ ~50 alpha để cân tải).
2. Số worker lấy `resolve_workers("auto", PER_WORKER_MB)`. Không thêm cờ mới.
3. Test: kết quả + thứ tự lưu trong `results_store` không đổi so với chạy từng alpha.

### P1.7 Successive halving (chỉ khi vẫn chậm)
- Vòng 1: mọi alpha chạy cửa sổ ngắn (vd 3 tháng) → giữ top 20%. Vòng 2: 6 tháng → top 25%. Vòng cuối: đủ dev1.
- Ghi số alpha bị loại mỗi vòng (tính vào số lần thử của DSR).

### P1.8 Load test
1. `run_funnel` 10k alpha thật → đo thời gian S1, RAM đỉnh slice (log ở `data/_cache/runs/*_mem.csv`).
2. Giữa chừng `kill -TERM` → `--resume` → kết quả trùng lần chạy liền mạch.
3. 100k tương tự (chạy đêm). Ngoại suy 500k/1M.
- **Xong khi:** 500k ước tính ≤ 4 h, không OOM, resume đúng.

### P0.3c (dời sang đây) Preset 3 chiến lược chưa tối ưu
- Sau P1.4: `build_strategy_book --only trend_short,reversion_long,reversion_short --n <lớn>` → `backend.optimize.build_presets` → kiểm `presets.json` có nguồn "build … stage A".

---

## P2 — Regime

### P2.1 Spec (viết trước, chưa code)
File `docs/bmad/stories/E15-S1-regime-spec.md`, trả lời:
| Câu hỏi | Gợi ý |
|---|---|
| Trạng thái | TREND_UP, TREND_DOWN, RANGE, VOL_EXPANSION, CRASH/HALT |
| Chỉ báo | ER (`er`), ADX (`adx`) đã có trong `core/signals/kernels.py`; thêm độ dốc EMA, phân vị biến động 90 ngày, ATR ratio, funding |
| Khung | Tính trên 1h và 4h; quyết định ở 1h đóng nến |
| Chống nhảy | Trễ chuyển: cần N nến liên tiếp thoả điều kiện mới; giữ tối thiểu M giờ |
| Causal | Chỉ dùng nến đã đóng (`avail_time = open + độ dài khung`) |

### P2.2 Engine regime
1. Tạo `backend/core/regime/{__init__,features,classifier}.py`. Đầu vào: mảng nến 1h/4h; đầu ra: mảng nhãn regime theo phút (giữ nhãn tới khi đổi).
2. Test prefix-invariant: tính trên dữ liệu `[0, t]` và `[0, T]` phải cho cùng nhãn tại mọi phút ≤ t (mẫu test giống `test_signals_*` hiện có).
3. Không đụng `core/research/regime_classifier.py` (mô tả, dùng cho UI cũ); đánh dấu deprecated.

### P2.3 Ghép regime ↔ chiến lược + cầu chì
1. Thêm vào chiến lược trường `regimes_allowed` (vd trend_long: TREND_UP; reversion: RANGE).
2. Engine: chặn vào lệnh khi regime không cho phép; khi regime chuyển sang VOL_EXPANSION/CRASH: cấm nhồi DCA (đếm `dca_blocked_regime`), tuỳ chọn đóng lệnh.
3. Mặc định `regimes_allowed = None` (tắt) → golden phải trùng bit.

### P2.4 Đo độ chuẩn
1. Lệnh `backend/core/regime/regime_report.py` (`python -m backend.core.regime.regime_report`): nhãn "thật" = dựa vào 7 ngày tương lai (ER/lợi suất); so với nhãn causal → bảng nhầm lẫn, độ trễ phát hiện trung bình.
2. Với mỗi chiến lược: PnL theo từng regime (backtest không bật regime, gán lệnh theo regime lúc vào).
- **Xong khi:** mỗi chiến lược lãi trong regime được phép của nó. Không lãi → sửa bảng ghép, không ép số.

### P2.5 Backtest/WFA theo regime
- Tối ưu từng chiến lược khi bật regime; sổ nhiều chiến lược chạy chung; WFA: ngưỡng regime nằm trong không gian tham số → chỉ chọn trên train.

### P2.6 MC trend thẳng đứng
- Thêm vào `carlo/monte_carlo.py` (cạnh 6 kịch bản stress hiện có): `vertical_up` (+40%/3 ngày), `vertical_down` (−30%/1 ngày), `vertical_chain` (3 đợt liên tiếp). Test: bot kiểu OKX (`research_topbots`) phải trượt gate.

### P2.7 DSR/PBO
- Số lần thử N trong `optimize/funnel/antiluck.py` phải nhân thêm số tổ hợp ngưỡng regime đã thử.

---

## P3 — Chạy phễu thật end-to-end
1. `backend/utils/ops/run_limited.sh -- -m backend.optimize.run_funnel --strategies <7 chiến lược> --n-per-strategy <N> --seed 7`
2. Theo dõi trên `/funnel` (UI) hoặc `GET /api/studio/funnel/runs/{id}`.
3. Ghi bảng 100k → ? → ? vào `docs/research/funnel_run_<ngày>.md` (số lượng, lý do loại hàng đầu mỗi tầng).
4. SOL (P3.3): chạy S5 sizing cho `trend_long_perp__SOL`; cập nhật `data/alphas/registry.json`; trượt → xoá `data/alphas/testnet/trend_long_perp__SOL.json`.
5. P3.4: chỉ `POST /api/studio/funnel/promote` cho alpha FINAL; holdout dùng một lần.
- Lưu ý: lần chạy thử 02/10: 112 alpha → S1 75 → **S2 0** (PBO/DSR). Kết quả 0 là bình thường nếu chiến lược chưa có lợi thế thật; không nới gate.

---

## P4 — UI
| Việc | Cách kiểm |
|---|---|
| P4.2b nhánh lỗi | Gửi cấu hình sai trên `/backtest` Nâng cao → lỗi hiện đúng ô; `/funnel` bấm Promote alpha không FINAL → thông báo 409; "Tính lại lệnh" cho alpha bị loại S1 |
| P4.3 regime | Sau P2.2: thêm API `GET /api/studio/regime?symbol=` → dải màu regime trên NAV ở `/portfolio`, chip "đang bật/tắt" cho từng chiến lược |
| P4.4 | `cd frontend && npm run build` sạch; mở từng trang sáng/tối, console không lỗi |
- Không đặt đường dẫn chứa `miner`, `mining`, `ads`, `tracker`, `analytics` (trình duyệt chặn).
- Chạy dev: `cd frontend && npx vite --port 18012`; xem qua port-forward IDE.

---

## P5 — Tài liệu
- Mỗi việc xong: thêm/sửa story `docs/bmad/stories/E1x-*.md` (Story, AC, Tasks, Evidence = commit + số liệu), cập nhật `sprint-status.yaml`.
- Báo cáo chốt: bảng kết quả P1 (tốc độ), P2 (độ chuẩn regime), P3 (phễu), rủi ro còn lại.
