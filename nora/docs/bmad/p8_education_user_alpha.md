# P8 — Làn Alpha: Education, chẩn đoán, nhận xét và Alpha người dùng

Ngày: 2026-10-07 · Nhánh: `fix/pipeline-audit` · Trạng thái: backend + UI đã triển khai; kết quả tính trước 50 mẫu chạy thật trên `data/binance_hist`
Liên quan: [`p7_python_strategies.md`](p7_python_strategies.md) (DSL, hồ sơ xno/nora, job `custom_backtest`) · [`roadmap.md`](roadmap.md)

## 1. Mục đích

P7 cho phép viết chiến lược bằng Python và chạy trên engine Nora. P8 là lớp **giải thích và kiểm chứng** phía trên, không có engine thứ hai và không dùng LLM:

1. **Education** (`/education`): 50 mẫu chiến lược có sẵn, mỗi mẫu có lời giải thích sinh từ code, kết quả backtest thật tính trước, chẩn đoán và nhận xét.
2. **Chẩn đoán** (`diagnostics`): đo cấu trúc lãi/lỗ, lý do thoát, exposure, so với benchmark, chế độ thị trường, điều kiện chặn tín hiệu — từ chính lần chạy.
3. **Nhận xét** (`insights`): bộ quy tắc cố định, mỗi câu truy được về một con số đo thật (`evidence`).
4. **Alpha người dùng**: chạy ở `/alpha/create` và `/education` chỉ là TẠM THỜI; lệnh **Lưu chiến lược** duy nhất ghi code + `program_hash` + cấu hình + ảnh chụp đầy đủ kết quả + bằng chứng vào kho `data/alphas/user/` (checklist do backend tính, vòng đời, chống giả mạo bằng job thật). Xem §6.

Nguyên tắc chung: mọi con số hiển thị do backend tính từ dữ liệu thật của lần chạy; thiếu đầu vào thì ghi `available: false` / `null` và giao diện hiện “—” / “không có dữ liệu” — không bịa số, không hằng số thay thế (0 / 50 / 100000), không chỉ số nào tính ở trình duyệt (giao diện chỉ đổi tên khoá / đơn vị và vẽ).

## 2. Từ DSL đến lời giải thích (không LLM)

Hai nguồn sự thật duy nhất:

| Nguồn | Vai trò |
|---|---|
| `core/strategy/pydsl/spec.py` | Chữ ký feature / operator + từ điển lý thuyết (nhãn tiếng Việt, công thức, cách đọc ngưỡng, warmup, nhóm) |
| `core/strategy/pydsl/explain.py` | `explain_program(program, profile, position)` dịch cây AST đã biên dịch sang tiếng Việt: `indicators[]`, `rules[]` (theo thứ tự `set_positions`), `execution[]` (cơ chế thực thi theo hồ sơ từ `profiles.py`), `warnings[]` (cấu trúc: sự kiện/trạng thái, thiếu chân thoát, warmup) |

Phần viết tay của mẫu chỉ là lý thuyết ngắn trong docstring. Quy tắc, chỉ báo, thực thi luôn do `explain.py` sinh lúc chạy (xem lint ở §5). `expr_to_vi` cũng dùng để gọi tên từng vế của điều kiện chặn (§3.6).

## 3. Chẩn đoán (`core/metrics/diagnose.py`)

Đầu vào do `custom_run.diagnostic_inputs` / `run_benchmark` dựng (`core/metrics/diagnose_inputs.py` đọc nến cùng kho dữ liệu với engine):

- `series`: `times` (nhãn = giờ ĐÓNG nến, nửa đêm UTC, `start .. end`), `equity` (vốn mark-to-market đóng ngày), `returns` (phần tử 0 = 0, không phải ngày giao dịch). `custom_run.daily_series`.
- `trades` (đã đóng, từ `result_payload(...)["trade_list"]`) + `positions_open` (đang mở cuối kỳ, `eng.open_positions()`).
- `benchmark`, `market`, `prices`, `frames` như dưới.

Ngày `k` = `[times[k], times[k+1])`; có `N = len(times) - 1` ngày.

### 3.1 `signal_activity`

| Trường | Định nghĩa | Nguồn |
|---|---|---|
| `total_trades`, `closed_trades`, `open_trades`, `long_trades`, `short_trades` | lệnh đã đóng + đang mở | trade_list + open_positions |
| `avg_holding_days`, `median_holding_days` | `(close hoặc end) − enter` / 1 ngày; lệnh đang mở tính tới cuối kỳ | thời gian lệnh |
| `exit_reason_counts`, `exit_reasons` (%) | đếm theo `exit_category(close_reason)` (xem bảng dưới); lệnh đang mở = `open_at_end` | `close_reason` của engine |
| `days_in_market_pct` | % số ngày có >= 1 vị thế mở | khoảng `[enter, close]` |
| `avg_exposure_pct`, `max_exposure_pct` | trung bình / lớn nhất theo ngày của `Σ |qty| × giá đóng ngày / vốn cuối ngày × 100`; thiếu giá thì dùng danh nghĩa lúc vào (ghi ở `exposure_basis`) | `prices` |
| `time_in_market_by_coin` | % số ngày có vị thế theo từng coin | khoảng lệnh |

Ánh xạ `close_reason` (chuỗi của `kernel.REASONS`) → loại thoát, **không suy từ `status`** (status SL/TP chỉ là dấu lãi/lỗ của thoát theo tín hiệu):

| `close_reason` | Loại |
|---|---|
| bắt đầu bằng `Tín hiệu thoát` hoặc chứa `ast stop` | `signal` |
| `Stop-loss ...` / `sl` | `stop_loss` |
| `Take-profit ...` / `tp` | `take_profit` |
| `Trailing ...` | `trailing` |
| chứa `hết thời gian giữ` / `timeout` | `timeout` |
| `Kill switch ...` | `kill_switch` |
| `End of Backtest` | `open_at_end` |
| `Thanh lý ...` | `liquidation` |
| khác / rỗng | `other` / `unknown` |

### 3.2 `pnl_structure`

Trên lệnh ĐÃ ĐÓNG: `win_rate` (% lệnh có pnl > 0), `winning_trades`, `losing_trades`, `avg_win`, `avg_loss`, `max_win`, `max_loss` (USDT, độ lớn dương; `null` khi không có lệnh loại đó — giao diện Education đọc các số này, không tự cộng từ danh sách lệnh), `payoff = TB lệnh thắng / |TB lệnh thua|`, `top5_profit_pct = Σ 5 lệnh thắng lớn nhất / Σ lãi gộp`, `max_consecutive_losses`, `by_year` (theo năm của `close_time`), `short_pnl_usd`, `short_closed_trades`. `by_coin` = đã chốt + lãi/lỗ lệnh đang mở theo giá cuối. `fee_drag_pct = phí / (lãi ròng + phí) × 100` với lãi ròng = `vốn cuối − vốn đầu` theo đường vốn (tính cả lệnh đang mở; `null` khi lãi gộp ≤ 0).

### 3.3 `market_comparison` và benchmark

- Benchmark là chiến lược **luôn long** `self.set_positions(self.data.pv_close > 0, position=1)` chạy qua CÙNG đường engine (`custom_run.run_benchmark`): cùng hồ sơ, rổ/trọng số, khung chiến lược, `run_frame`, `start/end`, vốn, nguồn dữ liệu. Cache theo cấu hình (mỗi job chỉ chạy một lần).
- Hồ sơ `xno`: giữ nguyên hồ sơ (mua một lần, tỉ trọng vốn hoá cố định, phí 0,1 %) — luôn long thì benchmark bằng chiến lược E1.
- Hồ sơ `nora`: chia vốn **đều** giữa các tài sản, đòn bẩy 1, `sizing=margin_pct` với `order_size_pct = 100 / n / (1 + phí taker)`, bỏ SL/TP/trailing/timeout và giới hạn rủi ro danh mục (kill-switch, exposure, `max_open_risk`, throttle) vì benchmark phải nắm giữ thuần.
- Căn chỉnh: hai đường vốn cùng `times`, cùng bắt đầu ở vốn đầu; nhãn ngày 1 (giờ đóng nến đầu kỳ) chưa có lãi/lỗ vì lệnh vào ở open nến kế tiếp, nên chiến lược và benchmark cùng đứng ở vốn đầu tới khi chiến lược vào lệnh. (Bản ghi tính trước hạ mẫu còn ≤ 400 điểm nên điểm thứ hai của chuỗi hạ mẫu nằm cách vài ngày — không phải ngày 1.) Test: `test_benchmark_aligned_with_strategy_start_and_always_long_is_itself`, `test_e1_always_long_benchmark_is_itself`.
- `strategy_cagr`, `market_cagr` dùng CÙNG định nghĩa với `metrics.simulate.nora.cagr_pct` (`metrics/returns.cagr_pct`): `(vốn cuối / vốn đầu)^(365 / số ngày lợi suất) − 1`, số ngày lợi suất = số mẫu − 1. `*_mdd` = MDD dương theo vốn đóng ngày. `excess_cagr = strategy_cagr − market_cagr`.
- `beta = cov(r_s, r_b) / var(r_b)` (ddof 0), `correlation` = Pearson, trên lợi suất ngày của các mốc chung; không có benchmark → `available: false`, không beta/tương quan.

### 3.4 `train_vs_test`

`train_sharpe/test_sharpe`, `train_cagr/test_cagr` (%), `train_mdd/test_mdd` (%) lấy từ `metrics.train` / `metrics.test` (khối `nora` ưu tiên, không có thì `xno`); `sharpe_decay = test_sharpe / train_sharpe` khi `train_sharpe > 0,1`. Test là lần chạy lại riêng từ vốn đầu tại mốc chia (như xnoquant); mốc chia = `custom_run.stage_split` (đầu năm dương lịch gần nhất không sau `start` + `ratio × (end − start)`, ví dụ 0,7 → 2023-01-01).

### 3.5 `regime_analysis`

Thị trường = giá đóng ngày của **BTC** nếu có trong rổ, không thì chỉ số rổ rebalance ngày theo trọng số (`diagnose_inputs.market_series`). Chế độ của ngày `k` xác định bằng giá thị trường **lúc mở ngày** (`times[k]`) so với **SMA200 nhân quả** (chỉ nến đã đóng, SMA gồm nến hiện tại, trượt trên toàn lịch sử nạp được kể cả trước `start`): `bull` (giá > SMA), `bear` (giá ≤ SMA), `unknown` (chưa đủ 200 nến). Mỗi chế độ: `days`, `pct_days`, `pnl_usd` (Σ lãi/lỗ theo ngày), `pnl_share_pct`, `trades_entered`, `days_in_market_pct`, `market_return_pct`, `benchmark_pnl_usd`. Σ `days` của ba chế độ = `total_days`; Σ `pnl_usd` = vốn cuối − vốn đầu.

### 3.6 `binding_condition`

Với mỗi quy tắc **vào** lệnh (`set_positions` mức ≠ 0) tách mask thành các vế cấp cao nhất `A & B & C` (cả toán tử `&` lẫn `and_`, bỏ vế trùng văn bản). Tính từng vế trên nến khung chiến lược của từng tài sản (chỉ báo tính từ đầu lịch sử như engine; đếm nến có `open_time ∈ [start, end)`; bỏ qua điều kiện giờ vào lệnh).

- >= 2 vế: mỗi vế có `pct_true`, `only_false_bars` (nến mà nó là vế DUY NHẤT sai), `share_of_near_miss_pct = only_false_bars / (số nến sai đúng một vế)`; quy tắc có `bars`, `all_true_bars`, `near_miss_bars`; `binding` = vế có `only_false_bars` lớn nhất khi có nến suýt đạt.
- 1 vế: chỉ `pct_true` (cùng `bars`, `all_true_bars`, `per_symbol`); `binding = null`, không có thống kê chặn.

### 3.7 Chuỗi theo giai đoạn (`series.stages`, `core/metrics/series_stages.py`)

`result.series` giữ chuỗi ngày đầy đủ (`times, equity, pnl, drawdown`, `benchmark`, `test` = lần chạy lại giai đoạn test) và thêm `stages = {all, train, test}`, mỗi giai đoạn **đã tính ở backend trên dữ liệu ngày đầy đủ**: `times` (giây), `equity`, `pnl` (so với điểm đầu giai đoạn), `drawdown_pct` (≤ 0, đỉnh chạy từ đầu giai đoạn), `ret_pct` (lợi suất ngày, phần tử 0 = 0), `benchmark {equity, pnl, label}`.
- `train` = điểm có nhãn ≤ mốc chia của chuỗi đầy đủ; `test` = lần chạy lại từ vốn đầu tại mốc chia (như metrics test) và **benchmark luôn long chạy lại trên cùng cửa sổ test** (`series.test.benchmark`, `custom_run.run_benchmark(start = mốc chia)`), nên đường nét đứt của giai đoạn Test không còn bị co dãn ở trình duyệt. Thiếu benchmark test → `benchmark = null` + cảnh báo.
- Hạ mẫu chỉ để vẽ và nằm ở backend, ghi rõ ở `downsample = {step, source_points, points, rule}`: tối đa 1200 điểm (kết quả tính trước Education: 400), điểm đầu đứng riêng, nhóm `step` điểm liên tiếp: nhãn/equity/pnl lấy điểm cuối nhóm, drawdown lấy đáy nhóm, `ret_pct` = lãi kép trong nhóm; gọi lại được nhiều lần (`source_points` giữ số điểm gốc). Giao diện (`lib/customResult.js: stagePlot`) chỉ đọc và vẽ; cắt theo thanh kéo là cắt chỉ số, không tính lại.
- `result.alpha_id` (= `generate_alpha_id(program_hash, config)`) và `result.checklist` (= `evaluate_checklist`) cũng do backend gắn ngay khi job xong: giao diện so `alpha_id` với bản đã lưu để biết “chưa lưu”, và hiển thị checklist trước khi lưu mà không tự tính.

## 4. Quy tắc nhận xét (`core/analytics/insights.py`, 24 quy tắc)

Mỗi quy tắc: `id`, `severity` (`warning` | `good` | `info`), thông điệp tiếng Việt + `evidence` (đúng các giá trị đã kích hoạt). Đầu vào thiếu → không kích hoạt. Kết quả sắp warning → good → info. Một quy tắc lỗi không làm mất quy tắc khác.

| id | Mức | Điều kiện (ngưỡng) | Khoá `evidence` |
|---|---|---|---|
| `beta_driven` (`BETA_DRIVEN_ID`) | warning | benchmark có; tương quan >= 0,9 và beta >= 0,8 | beta, correlation, strategy_cagr, market_cagr, excess_cagr |
| `overfit_gap` | warning | train_sharpe >= 0,8 và test_sharpe < 0,5 × train_sharpe | train_sharpe, test_sharpe, decay_pct |
| `fee_drag` | warning | fee_drag_pct >= 20 | fee_drag_pct, fees_usd, gross_pnl_before_fees_usd |
| `tail_dependent` | warning | >= 12 lệnh đóng và top5_profit_pct >= 50 | top5_profit_pct, closed_trades |
| `rarely_in_market` | info | days_in_market_pct < 10 và có lệnh | days_in_market_pct, avg_exposure_pct, total_trades |
| `always_in` | info | days_in_market_pct >= 95 | days_in_market_pct, avg_exposure_pct |
| `bear_loss` | warning | có chế độ; bear >= 30 ngày, bear pnl < 0, bull pnl > 0, \|bear pnl\| >= 5 % vốn đầu | bear_pnl_usd, bear_days, bull_pnl_usd, bull_days, initial_capital, benchmark_bear_pnl_usd, market |
| `positive_bear_performance` | good | bear >= 30 ngày, bear pnl > 0, thị trường bear giảm (< 0 %), có vị thế >= 10 % số ngày bear | bear_pnl_usd, bear_days, bear_market_return_pct, bear_days_in_market_pct, market |
| `high_win_rate` | good | win_rate >= 65 và >= 10 lệnh đóng | win_rate, payoff, closed_trades |
| `low_win_rate_trend` | info | win_rate < 40, payoff >= 2, >= 10 lệnh đóng | win_rate, payoff, closed_trades |
| `drawdown_heavy` | warning | strategy_mdd (ngày) >= 35 % | max_drawdown_pct, market_mdd_pct |
| `high_consecutive_losses` | warning | chuỗi thua >= 6 | max_consecutive_losses |
| `low_trade_count` | warning | 0 < tổng lệnh < 20 | total_trades, closed_trades, open_trades |
| `strong_alpha` | good | benchmark có; tương quan <= 0,65, excess_cagr > 0, test_sharpe >= 0,9 | correlation, excess_cagr, test_sharpe |
| `robust_oos` | good | sharpe_decay >= 0,8, test_sharpe >= 1, train_sharpe >= 1 | train_sharpe, test_sharpe, sharpe_decay |
| `sl_dominant_exit` | warning | >= 10 lệnh đóng và >= 40 % thoát bằng stop-loss | stop_loss_pct_of_closed, stop_loss_trades, closed_trades |
| `tp_dominant_exit` | good | >= 10 lệnh đóng và >= 45 % chạm take-profit | take_profit_pct_of_closed, take_profit_trades, closed_trades |
| `kill_switch_hit` | warning | có lệnh thoát `kill_switch` | kill_switch_trades |
| `negative_excess` | warning | benchmark có; excess_cagr < −5 điểm %/năm | excess_cagr, strategy_cagr, market_cagr |
| `concentrated_coin` | warning | > 1 coin, coin lãi nhiều nhất >= 65 % tổng lãi các coin có lãi | top_coin, share_pct, top_coin_pnl_usd |
| `short_profitable` | good | >= 5 lệnh short đóng, tổng lãi short > 0 | short_closed_trades, short_pnl_usd |
| `short_losing` | warning | >= 5 lệnh short đóng, tổng lãi short < 0 | short_closed_trades, short_pnl_usd |
| `only_long_bias` | info | 0 short và >= 1 long | long_trades, short_trades |
| `binding_condition` | info | quy tắc >= 3 vế, near_miss_bars >= 20, vế chặn >= 50 % số nến suýt đạt (chọn tỉ lệ cao nhất) | rule_index, line, side, n_conjuncts, conjunct, conjunct_index, pct_true, only_false_bars, near_miss_bars, all_true_bars, share_of_near_miss_pct |

Các ngưỡng là quy ước của sản phẩm (không phải tiêu chuẩn thống kê); đổi ngưỡng thì sửa `insights.py` và test `test_diagnostics_and_insights.py`.

## 5. Mẫu Education: lint, xuất, tính trước, endpoint

- **Nguồn mẫu**: `frontend/src/components/education/educationSamples.js` (50 mẫu = 5 nhóm × 10; trường `key, name, category, difficulty, profile, position (chỉ nora), summary, code`).
- **Lint nghiêm ngặt** (`test/scripts/lint_edu_samples.py`, chạy trong pytest bởi `test_edu_samples_lint.py`): mã `SCHEMA` (đủ trường, 5 nhóm × 10, xno không có `position`, khoá `position` hợp lệ), `COMPILE` (biên dịch + dựng được plan của hồ sơ), `BOILER` (không còn khung "Trading Rules" / "STEP n"), `NUMBA` (không nhắc Numba), `RISK` (chỉ nhắc SL/TP/trailing/timeout khi hồ sơ nora khai báo tham số tương ứng, hoặc nói rõ thoát theo tín hiệu, hoặc phủ định đúng), `RISKNUM` (số N×ATR khớp tham số vị thế), `SHORT` (không nhắc short khi chương trình không có chân SHORT), `EXEC` (câu về thực thi thuộc `explain.py`), `INDIC` (không nhắc chỉ báo không dùng), `NUMBER` (mọi số trong tên/tóm tắt/docstring phải là hằng số có thật). Nguyên tắc: mọi câu giải thích phải ĐÚNG với code và hồ sơ thực thi.
- **Xuất**: `test/scripts/export_edu_samples.py [--check]` → `data/education/samples.json` (`--check` thoát mã 1 nếu cũ so với file JS).
- **Job `edu_precompute`** (`core/backtest/edu_precompute.py`, đăng ký ở `api/jobs/batch.py`): mỗi mẫu chạy qua ĐÚNG `custom_run.run_custom` (cùng engine, benchmark, chẩn đoán, nhận xét). Mặc định `start 2019-12-31 → end 2024-12-31` (tương đương 2020-01-02 → 2025-01-01 theo nhãn xnoquant: tín hiệu nến 12-31 khớp ở open 01-01), `train_ratio 0,7`, vốn 100.000. Mẫu xno chạy rổ TOP10 spot `binance_hist`. Mẫu nora chạy `BTC@perp` trên kho hiện tại; bị chặn (cổng chất lượng / thiếu dữ liệu) thì lùi về TOP10 spot `binance_hist`, `market=spot`, khung chạy 1h và ghi `config.fallback` + `warnings`. Ghi `data/education/results/<key>.json` (series hạ mẫu ≤ 400 điểm) và `index.json` (`start, end, train_ratio, initial_capital`, từng mẫu `status`, `program_hash`, số đo chính, `insights`, `fallback`).
- **Cửa sổ mặc định của UI**: form Education và `/alpha/create` lấy `start/end/train_ratio/vốn` từ `index.json` (`frontend/src/lib/eduDefaults.js`); chưa có chỉ mục thì `2019-12-31 → 2024-12-31`, 0,7, 100.000. Nhờ đó chạy lại mẫu giữ nguyên ra đúng số đã tính trước. Form chỉ nằm trong bộ nhớ của phiên (không còn localStorage): mở lại trang là về mặc định.
- **Endpoint** (`api/routers/education.py`): `GET /api/studio/education/results` (index), `GET /api/studio/education/results/{key}` (bản ghi đầy đủ, `key` khớp `^[a-z0-9_]{1,80}$`), `POST /api/studio/education/precompute` (body tuỳ chọn `only, start, end, train_ratio, initial_capital`) → `{"job_id"}`, theo dõi `GET /api/studio/book/jobs/{job_id}`.
- **UI**: trạng thái trang (bản nháp, form, lần chạy) CHỈ trong bộ nhớ; xem §6.1. `usePrecomputed` khớp bản ghi theo `program_hash` của code đang mở (biên dịch qua `/strategies/compile`) và hồ sơ; khớp → hiển thị ngay, sửa code → báo bản tính trước đã cũ. Giải thích từng phần (`EduResult.jsx`) chỉ mở khi bấm nút "Xem giải thích từng phần"; công thức trong đó khớp mã `metrics/xno.py`, `metrics/returns.py`, `metrics/trades.py`.

## 6. Alpha người dùng (`core/analytics/user_alphas.py`, `api/routers/alphas.py`)

### 6.1 Mô hình lưu giữ (người dùng chốt 2026-10-07)

| Thứ | Ở đâu | Sống bao lâu |
|---|---|---|
| Bản nháp code, form chạy, tab, lần chạy hiện tại ở `/alpha/create` và `/education` | **bộ nhớ trình duyệt** (React state; `hooks/useMemState`) — không localStorage | tới khi đóng / tải lại trang |
| Kết quả một lần chạy (job `custom_backtest`) | thư mục job `jobs_root()` = `data/_cache/api_jobs/<job_id>/` | **24 giờ** nếu không được alpha đã lưu tham chiếu (`cleanup_unsaved_jobs`) |
| Kết quả tính trước của 50 mẫu Education (không phải lượt chạy của người học) | `data/education/results/` | bền; sinh lại bằng job `edu_precompute`, không bao giờ bị TTL xoá |
| **Alpha người dùng** (chỉ khi bấm **Lưu chiến lược**) | `data/alphas/user/<alpha_id>.json` (`get_user_alphas_dir`, một chỗ) | bền, vòng đời SAVED → CANDIDATE → ARCHIVED |

Chỉ localStorage còn dùng cho tuỳ chọn giao diện vô hại: giao diện sáng/tối (`nora-theme`), đã xem hướng dẫn Education (`nora-edu-result-tour-seen`), bề rộng ngăn kéo Alpha. Đường dẫn mỗi loại dữ liệu đặt ở một chỗ để phiên engine chuyển file sau theo ADR-P9 §4 mà không sửa logic: `jobs_root()` (batch) cho job tạm, `get_user_alphas_dir()` cho alpha người dùng, `edu_precompute.RESULTS_DIR` cho kết quả tính trước.

**Cảnh báo chưa lưu** (`hooks/useUnsavedGuard`, `components/studio/LeaveGuardDialog`): một bản nháp “chưa lưu” khi — chưa lưu lần nào mà code khác lúc mở hoặc đã có lần chạy; hoặc đã lưu mà code khác bản lưu, hay kết quả lần chạy (`alpha_id` do backend tính) khác bản lưu (`lib/studioDraft.isDraftDirty`). Đóng tab / tải lại: `beforeunload`; chuyển trang trong ứng dụng: `useBlocker` của react-router (cần data router, `App.jsx` dùng `createBrowserRouter` + `RouterProvider`, react-router-dom 6.30); đổi mỗi query string không chặn. Hộp thoại: **Ở lại** / **Lưu rồi rời** (chỉ khi bản đang mở là bản duy nhất chưa lưu và đã có lần chạy xong của đúng code) / **Rời không lưu**. Đóng một tab chưa lưu hỏi xác nhận.

**Một nút lưu**: “Lưu chiến lược” (cả hai trang) chỉ bật khi có lần chạy XONG của chính code đang soạn (cùng văn bản lúc chạy, hoặc cùng `program_hash` với bản biên dịch gần nhất); bấm → hộp thoại tên + ghi chú + checklist (lấy từ `result.checklist` của backend) → `POST /api/studio/alphas/user`. Không còn lưu code đơn thuần và không còn nút “Đẩy vào Alpha”. Mục **Đã lưu** ở tab Mẫu liệt kê `GET /api/studio/alphas/user`; mở một mục nạp code + cấu hình + KẾT QUẢ ĐÃ LƯU (`GET /user/{id}` → `result`) mà không chạy lại, đánh dấu “Đã lưu”, không dirty. Bản ghi cũ (trước 2026-10-07, không có `result`) mở được code + cấu hình và được báo “bản cũ”.

**Đã gỡ**: `GET/POST/DELETE /api/studio/strategies/custom` (kho code-only) và các hàm bọc ở `api.js`. `data/alphas/custom_strategies.json` (1 mục, không có kết quả) **bỏ không dùng**, còn nằm tại chỗ; phiên engine xoá khi chuyển dữ liệu (ADR-P9 §4).

**TTL** (`cleanup_unsaved_jobs`, `cleanup_quietly`): xoá thư mục job `custom_backtest` đã kết thúc quá 24 giờ (tuổi = `finished`, hoặc `created`) mà không có alpha đã lưu nào tham chiếu (`job_id` / `evidence.job_id`); bỏ qua job đang chạy/chờ, mọi loại job khác (kể cả `edu_precompute`) và thư mục lạ. Gọi nền khi API khởi động (`main.py`) và sau mỗi lần `POST /api/studio/custom/backtest`; lỗi dọn dẹp không làm hỏng yêu cầu. Không chạm `api/jobs/batch.py` (chỉ đọc `jobs_root()`).

### 6.2 Kho, bản ghi, chống giả mạo

- **Kho**: `data/alphas/user/<alpha_id>.json`, ghi nguyên tử (`.tmp` rồi `os.replace`, NaN/Inf → null). `alpha_id = sha1(program_hash + ":" + json(profile, symbols đã sắp, start, end, train_ratio, initial_capital, timeframe, position))[:12]` — cùng code + cùng cấu hình chạy → cùng id (lưu lại là `updated`, không nhân bản; giữ `status` và `created_at`).
- **Chống giả mạo**: `POST /api/studio/alphas/user` nhận `job_id` + `code` (+ tên, ghi chú), KHÔNG nhận kết quả từ client (trường lạ bị bỏ qua). Server đọc `result.json` của job `custom_backtest` đã `done`, từ chối kết quả thiếu `config`/`metrics.simulate`/`program_hash`, biên dịch lại `code` và so `program_hash`; lệch → HTTP 409.
- **Bản ghi** (không phụ thuộc thư mục job sau khi lưu): `id, name, note, source, status, created_at, updated_at, code, program_hash, profile, config, metrics, checklist, data_sha, job_id, final_equity`, `evidence` = `{job_id, program_hash, data_source, data_sha256_1m, git_commit, job_created, job_finished, engine}`, `explain` (`explain_program` lúc lưu) và **`result`** = ảnh chụp đầy đủ của job (`config, data, metrics, yearly, series` gồm `stages` + `benchmark` + `test`, `trades, positions_open, by_symbol, warnings, diagnostics, insights, final_equity`, `alpha_id`, `checklist`, `meta`). Không ghi vào `registry.json` hay chiến lược lõi.
- **Checklist** (`evaluate_checklist`, chỉ cảnh báo, không chặn; nguồn DUY NHẤT — giao diện chỉ hiển thị, không còn tính lại): `trades_ge_20` (>= 20 lệnh đóng), `has_test_stage`, `test_sharpe_positive` (Sharpe test > 0; khối nora, không có thì khối xno), `mdd_under_50` (MDD theo ngày < 50 %: khối nora `mdd_pct` đã là %, khối xno `max_drawdown` × 100), `not_pure_beta` (không có insight `BETA_DRIVEN_ID`). Mỗi mục có `state` ∈ `pass | fail | missing` (`passed` = true | false | null): thiếu đầu vào (không có danh sách lệnh, thiếu Sharpe/MDD test, không có insights) → `missing`, `value = "không có dữ liệu"`, không đạt cũng không trượt; số 0 thật không bị thay bằng giá trị dự phòng. `all_passed` chỉ đúng khi cả 5 mục `pass`; `n_missing` đếm mục thiếu.
- **Vòng đời**: `SAVED → CANDIDATE → ARCHIVED` (`POST /user/{id}/status`, `POST /user/{id}/archive`; không xoá cứng).
- **API**: `POST /user`, `GET /user?sort=date|sharpe|cagr&status=...` (danh sách gọn: bỏ `result` và `explain`, có `has_result`), `GET /user/{id}` (đầy đủ), `POST /user/{id}/status`, `POST /user/{id}/archive`. `sort=sharpe` = Sharpe test khối nora (365); `sort=cagr` = `cagr_pct` toàn kỳ khối nora (365 ngày); mục thiếu giá trị xếp cuối. `catalog()` hiển thị nhóm Alpha người dùng cùng định dạng thẻ; số đo thẻ (`strategy_doc._user_card_metrics`) lấy khoá tường minh (nora: `ret_pct, mdd_pct, sharpe, sortino, win_rate_trades, profit_factor_trades, trades`; thiếu khối nora mới dùng xno `cumulative_return, max_drawdown × 100, sharpe, sortino`), thiếu → `null` (giao diện “—”), 0 thật được giữ.

## 7. Hợp đồng với làn engine

Làn P8 chỉ **đọc** các giao diện dưới đây và không sửa `core/backtest/{kernel,engine,portfolio,run}.py`, `core/execute/*`, `core/params/*`, kho dữ liệu. Làn engine đổi bất kỳ giao diện nào phải chạy bộ gate bên dưới.

| Giao diện | Ai dùng | Điều khoản |
|---|---|---|
| `PortfolioEngine(symbols, strategies, start − WARMUP, end, trade_start_ts, initial_capital, risk=RiskConfig.from_dict, venue, close_at_end, base_frame, shared_dir)`, `.run()`, `.get_results()`, `.open_positions()` | `custom_run.execute` | chữ ký + khoá kết quả |
| `get_results()`: `equity_curve[{time, equity}]` (time = giờ MỞ nến chạy), `orders[].fee_usd/order_time`, `by_symbol{pnl_usd, trades, wins, fees_usd}` | `daily_series`, `build_result` | nhãn ngày = `time + FRAME_MS[base_frame]` |
| `core.backtest.run.result_payload(res, start, end)["trade_list"]` (`symbol, side, enter_time, close_time, qty, pnl, pnl_pct, notional, close_reason, status, fees_usd, ...`) | diagnose, `rows_from_trade_list` | `close_reason` là chuỗi trong `kernel.REASONS` (§3.1) |
| `open_positions()` (`symbol, side, qty, notional, unrealized_pnl, opened`) | exposure, pnl_structure | |
| `FRAME_MS`, `BacktestEngine.MAX_BACKTEST_DAYS` (job nâng lên 4000), `BacktestEngine._prepare_candles` | custom_run, diagnose_inputs | |
| `core.params.builder`: `POSITION_KEYS`, `resolve_costs(venue, market, fee, slippage, maker_fee)` | profiles, lint, benchmark nora | |
| `data_layout` (`NORA_EXCHANGE`, `NORA_LOCAL_DATA_ROOT`), `local_pkl.read_manifest` (`sha256_1m`, `start_ts`, `end_ts`), `CandleLoader` | custom_run, diagnose_inputs, edu_precompute | |

**Gate test** (chạy trước khi nhận thay đổi engine; từ `nora/`, qua `run_limited.sh --no-lock -- -m pytest ...`):
`test_pydsl_dsl.py`, `test_pydsl_causal.py`, `test_pydsl_explain.py`, `test_pydsl_parity.py` (kema_long DSL = lõi, trùng từng bit, cần dữ liệu OKX), `test_custom_backtest.py`, `test_xno_parity.py`, `test_diagnostics_and_insights.py`, `test_diagnostics_real.py` (E1 luôn long: benchmark = chính nó), `test_edu_precompute.py`, `test_edu_samples_lint.py`, `test_user_alphas.py`, `test_strategy_doc.py`, `test_dsl_reference.py`; cộng golden (`test_golden_results.py`) và `test_kernel_parity.py` của làn engine.

## 8. Giới hạn đã biết

- **KEMA vs xnoquant**: Nora đóng dứt điểm khi có tín hiệu thoát (ít chịu đợt sụt giảm 2022 hơn: 11,29× so với 8,66×); xnoquant rebalance theo tỉ trọng mục tiêu. Quyết định 07/10/2026: **khác biệt chấp nhận được**, không chỉnh engine để bám xnoquant (`test_kema_long_matches_xno` giữ xfail để giám sát trôi số liệu). Chi tiết ở `p7_python_strategies.md` §8.
- **Sharpe của xnoquant chưa xác minh**: không khớp `mean/std·√252` trên fixture. khối xno dùng `mean(r) / std(r, ddof=1) × √252` (khối nora cùng công thức nhưng × √365), **không** trừ lãi suất phi rủi ro (`R_f = 0`); khối `xno` ghi `metrics.notes.unverified = ["xno.sharpe"]`.
- **Hai quy ước quy năm cùng tồn tại**: khối `xno` (Sharpe, Sortino, Calmar, `annual_return`, bảng theo năm / giai đoạn) dùng 252 kỳ/năm và tính cả phần tử 0 đứng đầu (khớp fixture xnoquant, nên `days` lớn hơn số ngày giao dịch 1 đơn vị); khối `nora` (`cagr_pct`, `sharpe`, `sortino`, `calmar`; `metrics/returns.py: ANN = 365`) dùng 365 và bỏ phần tử đầu. Giao diện **ghi rõ cơ sở ở nhãn** thay vì trộn: ô tổng hợp = “CAGR (365 ngày)” và “Sharpe (252 kỳ)” (khối xno), bảng theo năm = “CAGR xno (252 kỳ)”, Chẩn đoán Train/Test và Sharpe của hộp thoại lưu = “Sharpe (365 ngày)”; chú thích và tooltip nêu công thức.
- **Hai kiểu Profit Factor**: khối `xno` = `Σ r ngày dương / |Σ r ngày âm|`; khối `nora` = `Σ pnl lệnh lãi / |Σ pnl lệnh lỗ|` trên lệnh đã đóng, chặn ở 99.
- **MDD ở job `custom_backtest`** là theo vốn đóng ngày (`series_metrics`); MDD trong nến của engine (khắt hơn) không có trong kết quả này.
- **Mẫu nora khi dữ liệu OKX bị chặn**: `edu_precompute` lùi về TOP10 spot `binance_hist`, khung 1h, `market=spot` và gắn `config.fallback` + cảnh báo; kết quả đó KHÔNG tương đương `BTC@perp`/1m. Các mẫu này chỉ nên đọc như minh hoạ cơ chế.
- `test_pydsl_parity.py` (dữ liệu thật) đang fail vì lệch sha manifest OKX, không liên quan P8; không sửa dữ liệu trong làn này.
- Năm chỉ có < 2 ngày lợi suất (ví dụ 2019 khi `start = 2019-12-31`) bị bỏ khỏi `yearly` (backend) và UI vẫn lọc dòng không có số đo.
