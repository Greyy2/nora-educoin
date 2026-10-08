# P7 — Chiến lược viết bằng Python chạy trên engine Nora

Ngày: 2026-10-06 (viết lại 2026-10-07: một cấu hình thực thi duy nhất) · Nhánh: `fix/pipeline-audit` · Trạng thái: đã triển khai (pydsl, job `custom_backtest`, API)

> Ghi chú lịch sử: cú pháp DSL theo kiểu `SimpleAlgorithm` (mượn từ một nền tảng ngoài). Không còn chế độ, hồ sơ, bộ chỉ số hay fixture nào của nền tảng đó;
> chuẩn đối chiếu của engine là ngữ nghĩa backtest của NautilusTrader ([`adr-p9-backend-layout.md`](adr-p9-backend-layout.md)).

## 1. Mục tiêu

1. Trang `/alpha/create`: người dùng viết chiến lược bằng Python (`class X(SimpleAlgorithm)`), bấm **Chạy backtest** và xem kết quả thật ngay tại trang. Không có số giả.
2. Code Python chạy trên **engine Nora duy nhất** (`PortfolioEngine` → kernel numba). Không có engine thứ hai, không có chế độ / hồ sơ thực thi thứ hai.
3. Một chiến lược lõi viết lại bằng Python (vd. `kema_long`) phải ra kết quả **trùng từng bit** với chiến lược lõi (`test_pydsl_parity.py`).
4. UI dùng style và component sẵn có của Nora (editor | kết quả).

Ràng buộc: không sửa `core/backtest/kernel.py` và `core/execute/*`; golden test giữ trùng từng bit; mọi job chạy qua `api/jobs/batch` + `run_limited.sh`; không `exec()` code người dùng.

## 2. Cấu hình thực thi duy nhất

Mặc định của engine Nora (`pydsl/profiles.py`, `build_plan`); không có tham số chọn chế độ:

| Điểm | Giá trị |
|---|---|
| Thị trường, rổ | perp OKX; rổ mặc định = mọi tài sản perp trong kho dữ liệu (`run_defaults.default_universe()` = `crawl/store.list_assets`, hiện BTC ETH SOL BNB XRP DOGE ADA AVAX TRX LINK); người dùng có thể chọn tập con (`symbols`) |
| Khối lượng | theo rủi ro: `BASE_POSITION` của sổ (0,5 % vốn/lệnh, đòn bẩy trần 10, cooldown 60 phút); **độ lớn của mức `position` không đổi khối lượng** (chỉ phân biệt vào / thoát và chiều; cảnh báo nếu khác 1) |
| Thoát | tín hiệu thoát + SL 3×ATR mặc định (`NORA_DEFAULTS`); TP / trailing / timeout mặc định tắt |
| Rủi ro danh mục | `RiskConfig` mặc định của sổ |
| Phí / trượt | theo sàn (builder) |
| Khung chạy | `1m` (`run_frame` đổi được; `timeframe` của chiến lược không được nhỏ hơn) |
| Vốn / train | 10.000 USDT; `train_ratio` 0,7 |
| Dữ liệu | kho OKX (`crawl/store`); cửa sổ mặc định = phần dữ liệu chung của cả rổ (`run_defaults.default_window()`) |

Ghi đè theo thứ tự: mặc định < thuộc tính lớp trong code (khoá `params.builder.POSITION_KEYS`, vd. `stop_loss_rate = 2.5`) < tham số `position` của API / panel Cài đặt.
Mọi mặc định được dùng đều thành cảnh báo trong `warnings`; vị thế hiệu lực ghi ở `config.position`.
Thuộc tính lớp `position_open_times|ranges`: nhãn nến = **giờ đóng** (open + khung), chỉ chặn việc đặt mức ≠ 0; `position_close_ranges` ép mức 0.

## 3. Ngôn ngữ chiến lược (DSL)

Code người dùng **không được thực thi**. `ast.parse` rồi thông dịch theo danh sách trắng:

- Một `class X(SimpleAlgorithm)` với thuộc tính lớp hằng (số, chuỗi, list chuỗi) và `def __algorithm__(self)`.
- Câu lệnh trong `__algorithm__`: gán (kể cả unpack tuple), `self.set_positions(...)`, docstring/comment. Không vòng lặp, không if, không import, không def lồng.
- Biểu thức: hằng số, tên biến cục bộ, `self.data.pv_open|high|low|close|volume`, `self.feat.<tên>(...)`, `self.op.<tên>(...)`,
  `+ - * / ** ` một/hai ngôi, so sánh `> >= < <= == !=`, `& | ~`, phương thức chuỗi `.fillna(v)`, `.shift(k≥1)`, `.abs()`.
  `and/or/not` của Python trên chuỗi → lỗi (bắt người dùng dùng `& | ~`).
- Thuộc tính lớp nhận biết: `timeframe` (mặc định `"24h"`), `position_open_times`, `position_open_ranges`, `position_close_ranges`
  (giờ UTC "HH:MM" / "HH:MM-HH:MM"), cùng các khoá vị thế (§5) nếu người dùng muốn ghi đè trong code.
- `self.feat`: tên và chữ ký theo TA-Lib. Tối thiểu: `sma ema dema tema wma rsi atr natr adx plus_di minus_di macd(→3)
  bbands(→3) roc rocp momentum stddev var cci willr mfi obv stoch(→2) donchian_upper donchian_lower linearreg_slope linearreg
  rolling_mean rolling_std rolling_max rolling_min rolling_sum rolling_zscore zscore returns log_returns trange
  typprice hlc3 ohlc4 range_pct volume_z`. Chỉ báo trùng với kernel Nora (`sma ema rsi atr adx bb… roc donchian`) **gọi hàm trong
  `signals/kernels.py`** khi đầu vào là cột giá gốc để giữ một nguồn sự thật; đầu vào là chuỗi tuỳ ý thì tính bằng cùng công thức trên chuỗi đó.
- `self.op`: 30 operator chuỗi thời gian (`crossed crossed_above crossed_below current previous shift diff pct_change
  rising falling fillna ffill abs clip isna notna isfinite zero_ifna sign replace between where value_when bars_since hold_for
  crossed_above_value crossed_below_value and_ or_ not_`). Mọi phép đều causal (không `shift` âm, không bfill).
- Hàm/thuộc tính không hỗ trợ → lỗi biên dịch có **số dòng + cột** và danh sách tên gần đúng. Không bao giờ trả NaN âm thầm.

Kết quả biên dịch: một **chương trình** (cây biểu thức đã kiểm) + metadata (`timeframe`, cột giá dùng, feature dùng, warmup ước tính,
số mức `position` khác nhau, cảnh báo). Chương trình chạy trên DataFrame nến của khung `timeframe` của **một** tài sản và trả chuỗi
mục tiêu `target[t] ∈ [-1, 1]` (NaN = không quy tắc nào → giữ mức trước; đầu chuỗi = 0).

## 4. Đưa vào engine (không đụng kernel)

`target` của mỗi tài sản được biến thành **cột tín hiệu** của khung `timeframe`, đọc qua đúng đường kernel hiện có:

- Tên cột: `py_<hash12>_<k>` với `hash12 = sha1(DSL_VERSION | ast đã chuẩn hoá, bỏ chú thích/docstring)[:12]`, `k ∈ {le, lx, se, sx}`.
- Định nghĩa (đã chọn, `pydsl/program.py`): **vào = sự kiện, thoát = trạng thái**: `le = explicit>0` (quy tắc đặt mức > 0 ngay ở nến này),
  `lx = target<=0`; `se = explicit<0`, `sx = target>=0` (`explicit` = mức đặt tường minh tại nến, `target` = ffill của nó, đầu chuỗi 0).
  Lý do: vị thế đóng bởi SL/TP/timeout không tự vào lại ngay trên mức target cũ — đúng như chiến lược lõi dùng sự kiện cắt (`cross_over`),
  nên `kema_long` viết lại bằng DSL trùng từng bit.
- `signals/kernels.py`: `register_program(hash12, program)` + `PROGRAMS`; `is_kernel_column`/`compute`/`warmup_bars` nhận cột `py_…`
  (chưa đăng ký -> `compute` báo lỗi rõ, không NaN âm thầm). `engine.frame_features` không đổi. `core/data/shared.py:plan` trả `None` khi
  có cột `py_` -> không bao giờ ghi vào kho dùng chung (tính trong tiến trình); job còn gỡ `NORA_SHARED_DATA_DIR`.
- Mỗi chân (LONG/SHORT có mức tương ứng) là một chiến lược của `PortfolioEngine`:
  `tree = [[[{"frame": tf, "column": "py_<h>_le", "index": 0}, ">", 0.5]]]`, `stop = [{"condition": [[[{"frame": tf, "column": "py_<h>_lx", ...}, ">", 0.5]]]}]`
  (cùng dạng `materialize()`).
- Tiến trình job tự biên dịch (`pydsl.compile_code` = biên dịch + `register_program`) trước khi dựng engine; registry không đi qua tiến trình con khác.
- Job nâng `BacktestEngine.MAX_BACKTEST_DAYS` lên 4000 trong tiến trình của nó (cho phép chạy nhiều năm; API backtest sổ vẫn 1100 ngày).

## 5. API và job

- `POST /api/studio/strategies/compile` `{code}` → `{ok, program_hash, meta:{timeframe, features, ops, columns, legs, position_levels, warmup_bars}, warnings[], error:{line, col, message}|null}`
  (lỗi code trả 200 với `ok:false`; `line`/`col` 1-based). `POST /api/studio/strategies/explain` `{code, position?}` → giải thích cấu trúc (chỉ báo, quy tắc, cơ chế thực thi, cảnh báo).
- `GET /api/studio/custom/defaults` → `{symbols, start, end, train_ratio, initial_capital}` tính từ kho dữ liệu (form chạy lấy mặc định ở đây, trình duyệt không giữ hằng số ngày/rổ).
- `POST /api/studio/custom/backtest` `{code, symbols?, start, end, train_ratio?, initial_capital?, position?, run_frame?}` → `{job_id}`; code lỗi / tham số sai → 422
  (`Lỗi biên dịch chiến lược: dòng L, cột C: …`). Job `custom_backtest` (đăng ký trong `batch.KINDS`) → `backend/core/backtest/custom_run.py` `run_job(params)`. Theo dõi bằng `GET /api/studio/book/jobs/{job_id}`.
- `result.json`:
  ```json
  {"config": {...}, "program_hash": "...", "data": {"source": "okx", "sha256_1m": {...}},
   "metrics": {"simulate": {...}, "train": {...}, "test": {...}, "notes": {...}},
   "yearly": [{"year": 2024, "stage": "train", "days": 366, "cagr_pct": 0, "sharpe": 0, "mdd_pct": 0, "profit_factor_trades": 0, "calmar": 0}],
   "series": {"times": [...], "equity": [...], "pnl": [...], "drawdown": [...], "stage_split": 1672531200, "stages": {...}, "benchmark": {...}},
   "trades": [...], "positions_open": [...], "by_symbol": [...], "diagnostics": {...}, "insights": [...], "checklist": {...}, "warnings": [...]}
  ```

**Một bộ chỉ số phẳng** cho mỗi giai đoạn (`metrics.simulate|train|test`): `ret_pct, mdd_pct, sharpe, sortino, cagr_pct, calmar, trades, win_rate_trades, profit_factor_trades, fees_usd`
(`core/metrics/returns.py`: năm = 365 ngày, lãi suất phi rủi ro 0; Sharpe/Sortino/CAGR/Calmar/MDD trên lợi suất ngày MTM; win rate và profit factor theo lệnh đóng). Cơ sở ghi một lần ở `metrics.notes`
(`annualization_days: 365`, `stage_basis`, `test_fresh_capital`). Bảng `yearly` dùng cùng định nghĩa.

Chuỗi `series` theo **ngày**, nhãn = nửa đêm UTC (giờ đóng nến), `times` giây UTC, mốc đầu = `start` (vốn đầu); `stage_split` = đầu năm dương lịch gần nhất của `start + train_ratio×(end−start)`
(nếu mốc đó chưa cách `start` 30 ngày thì lấy chính điểm ratio). `simulate`/`train` cắt lát từ đường vốn của lần chạy đầy đủ; **`test` và các năm test lấy từ lần chạy lại [mốc chia, end] bắt đầu từ vốn đầu**
(`metrics.notes.test_fresh_capital = true`); đường vốn lần chạy lại ở `series.test`. Benchmark "luôn long" chạy qua cùng engine (chia đều, đòn bẩy 1, không SL/TP) trên cả toàn kỳ và cửa sổ test.

## 6. Kiểm thử

1. DSL (`test_pydsl_dsl.py`, `test_pydsl_causal.py`): ngữ nghĩa, lỗi có số dòng/cột, phép kiểm cắt tiền tố (causal) cho **mọi** feature/operator, `|`/`or_` là OR thật, thứ tự `set_positions` ghi đè.
2. Parity nội bộ (`test_pydsl_parity.py`): `kema_long` viết bằng Python, cùng tham số → `trade_list` và `equity_curve` **trùng từng bit** với chiến lược lõi.
3. Job + API (`test_custom_backtest.py`), chẩn đoán trên dữ liệu OKX thật (`test_diagnostics_real.py`, bỏ qua khi thiếu dữ liệu), giải thích (`test_pydsl_explain.py`).
4. Trình soạn code trong Chrome thật: `test/scripts/check_code_editor.py` (Playwright).
5. Golden giữ trùng từng bit (`test_golden_results.py`).

Chạy (từ `nora/`): `ops/run_limited.sh --no-lock -- -m pytest test/test_pydsl_dsl.py test/test_pydsl_causal.py test/test_pydsl_explain.py test/test_pydsl_parity.py test/test_custom_backtest.py -q`.

```bash
curl -s -X POST localhost:18010/api/studio/strategies/compile -H 'content-type: application/json' -d @<(python3 -c 'import json;print(json.dumps({"code":open("strategy.py").read()}))')
curl -s -X POST localhost:18010/api/studio/custom/backtest -H 'content-type: application/json' \
  -d '{"code": "...", "start": "2024-01-01", "end": "2025-12-31"}'
curl -s localhost:18010/api/studio/book/jobs/<job_id>          # trạng thái + result.json như mọi job
```
