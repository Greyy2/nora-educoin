# P7 — Chiến lược viết bằng Python (dạng xnoquant) chạy trên engine Nora

Ngày: 2026-10-06 · Nhánh: `fix/pipeline-audit` · Trạng thái: backend đã triển khai (pydsl, hồ sơ xno/nora, job custom_backtest, API); parity xnoquant chờ bộ dữ liệu TOP10 (§7.3)

## 1. Mục tiêu

1. Trang `/alpha/create`: người dùng viết chiến lược bằng Python theo dạng `SimpleAlgorithm` của xnoquant, bấm **Chạy backtest**
   và xem kết quả thật ngay tại trang. Không có số giả (bỏ `MOCK_SIM_RESULT`).
2. Code Python chạy trên **engine Nora duy nhất** (`PortfolioEngine` → kernel numba). Không có engine thứ hai, không vectorized simulator riêng.
3. Hồ sơ thực thi `xno` cho kết quả **xấp xỉ** xnoquant cùng code, cùng dữ liệu, cùng giai đoạn (dung sai §7).
4. Hồ sơ thực thi `nora` dùng quản lý vị thế của Nora (SL/TP theo ATR, rủi ro/lệnh…). Một chiến lược lõi viết lại bằng Python
   (vd. `kema_long`) chạy ở hồ sơ `nora` phải ra kết quả **trùng từng bit** với chiến lược lõi.
5. UI giống bố cục xnoquant (editor | kết quả), nhưng dùng **style và component sẵn có của Nora**.

Ràng buộc: không sửa `core/backtest/kernel.py` và `core/execute/*` (đang có việc khác sửa song song); golden test giữ trùng từng bit;
mọi job chạy qua `api/jobs/batch` + `run_limited.sh`; không `exec()` code người dùng.

## 2. Ngữ nghĩa xnoquant đã đo (2026-10-06)

Đo bằng thí nghiệm trên tài khoản xnoquant (E1 luôn long `position=1`, E2 `position=0.5`) rồi hồi quy với giá Binance (R² = 1,0).
Fixture: `test/fixtures/xno/` (kết quả thô E1, E2, KEMA long).

| Điểm | Giá trị |
|---|---|
| Thị trường `Crypto Spot`, rổ `TOP10` | BTC ETH BNB XRP ADA SOL DOGE TRX LINK BCH, giá **spot USDT Binance**, nến **ngày** |
| Nhãn thời gian | ngày `t` của xnoquant = giá đóng cửa nến Binance mở ngày `t−1` (nhãn theo giờ đóng nến) |
| Giai đoạn | 2020-01-02 → 2025-01-01; `train_ratio` 0,7 → train tới 2023-01-01, test phần còn lại |
| Vốn | `init_cash` 100.000 |
| `set_positions(mask, position=w)` | ghi mức nắm giữ mục tiêu ở nến mask đúng; lệnh gọi sau ghi đè lệnh trước (ví dụ mẫu gọi thoát trước, vào sau) |
| Khối lượng | mua **một lần**, giữ nguyên số lượng, **không cân lại** (luôn long = 10 lệnh). Kết quả tuyến tính theo `w` chính xác |
| Chia vốn giữa coin | **tỉ trọng vốn hoá cố định** (khớp vốn hoá ~cuối 11/2025, sai số log ≤ 0,12): BTC 0,69160 · ETH 0,14653 · XRP 0,05158 · BNB 0,04720 · SOL 0,02932 · TRX 0,01041 · DOGE 0,00938 · ADA 0,00561 · BCH 0,00472 · LINK 0,00366 (đo từ E1; tổng = 1). Coin chưa niêm yết (SOL tới 2020-08) giữ tiền mặt rồi mua ở nến đầu có dữ liệu |
| Phí | ≈ 0,1 % mỗi lần khớp |
| Chỉ số | `pnls` = lãi lỗ cộng dồn; `returns` = lợi suất ngày; `volatility = std·√252`; `sortino` theo 252; `annual_return` = lợi suất hình học quy năm 252 kỳ; `calmar = annual/|MDD|`; `win_rate = #(r>0)/#(r≠0)`; `profit_factor = omega = Σr⁺/Σ|r⁻|`. **Sharpe chưa xác định công thức** (không khớp mean/std·√252) |
| Short trên Spot (E3, E6) | **Không hỗ trợ short**. `position < 0` bị bỏ qua hoàn toàn trên Crypto Spot (E3: 0 lệnh, 0 phí, vốn giữ nguyên 100k; E6 tương quan 1,0000 với E4). |
| Ảnh hưởng RSI TA-Lib (E9) | **Không làm lệch KEMA**. E9 (KEMA bỏ RSI) cho kết quả trùng từng bit với KEMA gốc (tương quan 1,0000, sai số tuyệt đối = 0, 1108 lệnh, 22 lệnh đóng, vốn 865.651). |
| Cơ chế Thoát & Cân lại (E7, E8) | xnoquant **rebalance theo tỷ trọng mục tiêu** (mỗi lần mục tiêu đổi thì đặt lệnh cân lại và tính phí 0,1% trên khối lượng thay đổi: E7 tốn 15,91% phí, E8 đổi về 0,5 tốn 8,06% phí — đúng một nửa E7; cả hai đều có 1731 lệnh). Trên Spot, `position=0` không đóng dứt điểm mọi coin (E7 chỉ có 14 lệnh đóng, beta mùa gấu 2022 vẫn đạt 0,97). |

Kết quả đo E3–E9 đã giải thích toàn bộ nguyên nhân lệch KEMA: Nora thoát dứt điểm (flat) rồi vào lại bằng toàn bộ vốn tích lũy, trong khi xnoquant rebalance theo slot vốn ban đầu và giữ danh mục spot qua các đợt sụt giảm.

## 3. Ngôn ngữ chiến lược (DSL)

Code người dùng **không được thực thi**. `ast.parse` rồi thông dịch theo danh sách trắng:

- Một `class X(SimpleAlgorithm)` với thuộc tính lớp hằng (số, chuỗi, list chuỗi) và `def __algorithm__(self)`.
- Câu lệnh trong `__algorithm__`: gán (kể cả unpack tuple), `self.set_positions(...)`, docstring/comment. Không vòng lặp, không if, không import, không def lồng.
- Biểu thức: hằng số, tên biến cục bộ, `self.data.pv_open|high|low|close|volume`, `self.feat.<tên>(...)`, `self.op.<tên>(...)`,
  `+ - * / ** ` một/hai ngôi, so sánh `> >= < <= == !=`, `& | ~`, phương thức chuỗi `.fillna(v)`, `.shift(k≥1)`, `.abs()`.
  `and/or/not` của Python trên chuỗi → lỗi (bắt người dùng dùng `& | ~`).
- Thuộc tính lớp nhận biết: `timeframe` (mặc định `"24h"`), `position_open_times`, `position_open_ranges`, `position_close_ranges`
  (giờ UTC "HH:MM" / "HH:MM-HH:MM"), cùng các khoá vị thế của hồ sơ `nora` (§5) nếu người dùng muốn ghi đè trong code.
- `self.feat`: tên và chữ ký **giống xnoquant** (TA-Lib). Tối thiểu: `sma ema dema tema wma rsi atr natr adx plus_di minus_di macd(→3)
  bbands(→3) roc rocp momentum stddev var cci willr mfi obv stoch(→2) donchian_upper donchian_lower linearreg_slope linearreg
  rolling_mean rolling_std rolling_max rolling_min rolling_sum rolling_zscore zscore returns log_returns trange
  typprice hlc3 ohlc4 range_pct volume_z`. Chỉ báo trùng với kernel Nora (`sma ema rsi atr adx bb… roc donchian`) **gọi hàm trong
  `signals/kernels.py`** khi đầu vào là cột giá gốc để giữ một nguồn sự thật; đầu vào là chuỗi tuỳ ý thì tính bằng cùng công thức trên chuỗi đó.
- `self.op`: đúng 30 operator chuỗi thời gian của xnoquant (`crossed crossed_above crossed_below current previous shift diff pct_change
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
  Lý do: vị thế đóng bởi SL/TP/timeout (hồ sơ nora) không tự vào lại ngay trên mức target cũ — đúng như chiến lược lõi dùng sự kiện cắt (`cross_over`),
  nên `kema_long` viết lại bằng DSL trùng từng bit. Hồ sơ xno không có SL/TP nên hai cách như nhau.
- `signals/kernels.py`: `register_program(hash12, program)` + `PROGRAMS`; `is_kernel_column`/`compute`/`warmup_bars` nhận cột `py_…`
  (chưa đăng ký -> `compute` báo lỗi rõ, không NaN âm thầm). `engine.frame_features` không đổi. `core/data/shared.py:plan` trả `None` khi
  có cột `py_` -> không bao giờ ghi vào kho dùng chung (tính trong tiến trình); job còn gỡ `NORA_SHARED_DATA_DIR`.
- Mỗi chân (LONG/SHORT có mức tương ứng) là một chiến lược của `PortfolioEngine`:
  `tree = [[[{"frame": tf, "column": "py_<h>_le", "index": 0}, ">", 0.5]]]`, `stop = [{"condition": [[[{"frame": tf, "column": "py_<h>_lx", ...}, ">", 0.5]]]}]`
  (cùng dạng `materialize()`).
- Tiến trình job tự biên dịch (`pydsl.compile_code` = biên dịch + `register_program`) trước khi dựng engine; registry không đi qua tiến trình con khác.
- Job nâng `BacktestEngine.MAX_BACKTEST_DAYS` lên 4000 trong tiến trình của nó (xnoquant chạy 5 năm; API backtest sổ vẫn 1100 ngày).

## 5. Hồ sơ thực thi

| | `xno` | `nora` |
|---|---|---|
| Tài sản | rổ TOP10 cố định (§2) hoặc người dùng chọn | người dùng chọn trong vũ trụ có dữ liệu |
| Thị trường | spot, đòn bẩy 1 (short: chờ E3; tạm perp đòn bẩy 1, không funding) | perp (mặc định) / spot |
| Khối lượng | `margin_pct`, `order_size_pct = 100 × weight_sym × |w|`, mỗi tài sản một chiến lược con (khoá `symbols`) | `risk` (mặc định 0,5 %/lệnh) hoặc `margin_pct` |
| Thoát | chỉ theo tín hiệu (`stop_loss_rate = take_profit_rate = trailing = timeout = 0`) | SL/TP/trailing/timeout theo ATR như chiến lược lõi |
| Cooldown | 0 | 60 phút |
| Phí / trượt | taker = maker = 0,1 %, trượt 0 | theo venue (builder) |
| Rủi ro danh mục | không giới hạn (max_positions = số tài sản, gross không trần, kill switch tắt) | `RiskConfig` mặc định của sổ |
| Khung chạy | chính `timeframe` của chiến lược (nến ngày: tín hiệu ở nến t, khớp ở open nến t+1 ≈ close nến t); `run_frame` đổi được | 1m |
| Chỉ số | bộ chỉ số xnoquant (§2) + bộ chỉ số Nora | bộ chỉ số Nora + bộ xnoquant |

Chi tiết đã triển khai (`pydsl/profiles.py`):

- xno: một chiến lược con mỗi (tài sản, chân), `order_size_pct = 100 × weight × |w| / (1+0,001) × (1−1e-9)` — **co theo phí** để Σ ký quỹ × (1+phí) ≤ vốn
  (xnoquant cũng trừ phí khỏi vốn đầu); weight chuẩn hoá tổng = 1 (`pydsl/weights.py`, bảng đo được; tập con TOP10 chuẩn hoá lại + cảnh báo; tài sản ngoài TOP10 chia đều + cảnh báo).
  Chân SHORT chạy trên `BTC@perp` đòn bẩy 1 (funding perp vẫn tính nếu có `funding.pkl`, không tắt được ở v1) + cảnh báo.
  Nhiều mức position khác nhau trong cùng chân -> dùng |w| lớn nhất + cảnh báo (v1 không tăng/giảm vị thế theo mức).
  Vị thế cuối kỳ **không đóng** (`close_at_end=False`, vốn = MTM, giống xnoquant `open_trade_pnl`); báo ở `positions_open`.
- nora: mặc định = `BASE_POSITION` của sổ + `stop_loss_rate=3.0` (×ATR), TP/trailing/timeout = 0; ghi đè theo thứ tự mặc định < thuộc tính lớp trong code
  (khoá `POSITION_KEYS`, vd. `stop_loss_rate = 2.5`) < tham số API `position`. Mọi mặc định được dùng đều thành cảnh báo trong `warnings`; vị thế hiệu lực ghi ở `config.position`.
- Thuộc tính lớp `position_open_times|ranges`: nhãn nến = **giờ đóng** (open + khung), chỉ chặn việc đặt mức ≠ 0; `position_close_ranges` ép mức 0. Ngữ nghĩa này chưa đo trên xnoquant.

## 6. API và job

- `POST /api/studio/strategies/compile` `{code}` → `{ok, program_hash, meta:{timeframe, features, ops, columns, legs, position_levels, warmup_bars}, warnings[], error:{line, col, message}|null}`
  (lỗi code trả 200 với `ok:false`; `line`/`col` 1-based).
- `POST /api/studio/strategies/custom` `{name, code, idea?}` → `{ok, action: created|updated, id, version, strategy, warnings}` lưu vào `data/alphas/custom_strategies.json`
  (id = slug tên không dấu, version = program_hash; code lỗi -> 422 `{detail:{line,col,message}}`); `GET …/custom` → `[{id, name, idea, code, version, meta, created_at, updated_at}]`;
  `DELETE …/custom/{id}` → `{ok, deleted}` (404 nếu không có). Các endpoint `/save` cũ đã bỏ.
- `POST /api/studio/custom/backtest` `{code, profile: "xno"|"nora", universe?: "TOP10", symbols?, start, end, train_ratio?, initial_capital?, position?, market?, run_frame?, exchange?}`
  → `{job_id}`; code lỗi / tham số sai -> 422 (`Lỗi biên dịch chiến lược: dòng L, cột C: …`). `exchange` = nguồn dữ liệu (đặt `NORA_EXCHANGE` trong tiến trình job TRƯỚC khi nạp dữ liệu;
  bỏ trống = như hiện tại; tên phải nằm trong `data_layout.EXCHANGES`). Job loại `custom_backtest` (đăng ký trong `batch.KINDS`) → module `backend/core/backtest/custom_run.py` `run_job(params)`.
  Theo dõi bằng `GET /api/studio/book/jobs/{job_id}` như mọi job.
- `result.json`:
  ```json
  {"config": {...}, "program_hash": "...", "data": {"source": "...", "sha256_1m": {...}},
   "metrics": {"simulate": {"xno": {...}, "nora": {...}}, "train": {...}, "test": {...}, "notes": {...}},   // xno = bộ xno (§2, backend/core/metrics/xno.py); nora = ret_pct, mdd_pct, sharpe, sortino, cagr_pct, calmar, trades, win_rate_trades, profit_factor_trades, fees_usd
   "yearly": [{"year": 2020, "stage": "train", "cagr": 0, "sharpe": 0, "max_drawdown": 0, "profit_factor": 0, "calmar": 0}],
   "series": {"times": [...], "equity": [...], "pnl": [...], "drawdown": [...], "stage_split": 1672531200},
   "trades": [...], "positions_open": [...], "by_symbol": [...], "warnings": [...]}
  ```

Ghi chú kết quả: chuỗi `series` theo **ngày**, nhãn = nửa đêm UTC (giờ đóng nến, như xnoquant), `times` giây UTC, mốc đầu = `start` (vốn đầu);
`stage_split` = đầu năm dương lịch gần nhất của `start + train_ratio×(end−start)` (xnoquant: 2020-01-02 → 2025-01-01, 0,7 → 2023-01-01; train gồm nhãn ≤ mốc).
`simulate`/`train` cắt lát từ đường vốn của lần chạy đầy đủ; **`test` và các năm test lấy từ lần chạy lại [mốc chia, end] bắt đầu từ vốn đầu** (xnoquant tính test như vậy, đo từ fixture; `metrics.notes.test_fresh_capital = true`); đường vốn lần chạy lại ở `series.test {times, equity, drawdown}`.
Bộ xno khớp fixture (sai số < 1e-9): volatility, annual_return, cumulative_return, max_drawdown, calmar, sortino, omega/profit_factor/gain_to_pain, win_rate,
win_loss_ratio, kelly, recovery_factor, tail_ratio, var, cvar, ulcer_index; **sharpe chưa xác định** (dùng TB/σ·√252, `notes.unverified = ["xno.sharpe"]`).

## 7. Kiểm thử và tiêu chí đạt

1. DSL: phép kiểm cắt tiền tố (causal) cho **mọi** feature/operator; lỗi có số dòng; `|`/`or_` là OR thật; thứ tự `set_positions` ghi đè; mẫu xnoquant (`codes/examples` crypto) biên dịch được hoặc báo rõ hàm thiếu.
2. Parity nội bộ: `kema_long` viết bằng Python, hồ sơ `nora`, cùng tham số → `trade_list` và `equity_curve` **trùng từng bit** với chiến lược lõi.
3. Parity xnoquant (`test/test_xno_parity.py`, chạy khi có dữ liệu TOP10 2019-10 → 2025-01):
   E1 và E2 → `end_value` lệch ≤ 1 %, MDD lệch ≤ 1 điểm %, tương quan lợi suất ngày ≥ 0,99; KEMA long (code §2 fixture) → lợi suất tổng lệch ≤ 5 % tương đối, MDD ≤ 3 điểm %.
4. Golden hiện có giữ trùng từng bit. Test chọn lọc khi làm, một lượt đủ khi xong mỗi phần.

## Cách chạy

```bash
# Biên dịch thử (không cần dữ liệu)
curl -s -X POST localhost:18010/api/studio/strategies/compile -H 'content-type: application/json' -d @<(python3 -c 'import json,sys;print(json.dumps({"code":open("strategy.py").read()}))')
# Backtest hồ sơ xno trên rổ TOP10 (dữ liệu: NORA_EXCHANGE hiện tại, hoặc "exchange": "binance_hist" khi bộ TOP10 lịch sử sẵn sàng và đã có trong data_layout.EXCHANGES)
curl -s -X POST localhost:18010/api/studio/custom/backtest -H 'content-type: application/json' \
  -d '{"code": "...", "profile": "xno", "universe": "TOP10", "start": "2019-12-31", "end": "2024-12-30", "train_ratio": 0.7, "initial_capital": 100000}'
curl -s localhost:18010/api/studio/book/jobs/<job_id>          # trạng thái; result.json qua cùng endpoint như mọi job
```

Kiểm thử (từ `nora/`, qua `backend/utils/ops/run_limited.sh -- -m pytest …`): `test/test_pydsl_dsl.py` (ngữ nghĩa, lỗi dòng/cột, mẫu xnoquant, hồ sơ), `test_pydsl_causal.py`
(prefix-invariance mọi feature/operator), `test_pydsl_parity.py` (kema_long DSL = lõi, trùng từng bit), `test_custom_backtest.py` (job + API), `test_xno_parity.py` (§7.3, bỏ qua khi thiếu dữ liệu TOP10).
Với xnoquant nhãn ngày t = đóng cửa nến mở t−1 và nó vào lệnh ở đóng cửa nến 2019-12-31 → dùng `start = 2019-12-31` để so với kết quả lưu (2020-01-02 → 2025-01-01).

## 8. Tiến độ & Quyết định chốt

- **Kết quả đo thực nghiệm E3–E9 (Hoàn thành 07/10/2026)**:
  - Đã chạy cô lập 7 thí nghiệm E3–E9 trên tài khoản xnoquant thật và lưu fixture tại `test/fixtures/xno/`. Toàn bộ E3–E9 đã khép lại (không còn mở).
  - Đã xác nhận: Crypto Spot không có short (E3); RSI không phải nguyên nhân lệch KEMA (E9 trùng từng bit); xnoquant rebalance theo tỷ trọng mục tiêu và giữ vị thế spot (E7, E8).
- **Parity KEMA & Cơ chế bảo toàn vị thế (Quyết định chốt 07/10/2026)**:
  - Khi chạy ở hồ sơ `nora`, KEMA Python trùng từng bit với chiến lược lõi (`test_pydsl_parity.py`).
  - Khi chạy ở hồ sơ `xno`, Nora quản lý theo vòng đời lệnh (trade lifecycle) đóng dứt điểm khi có tín hiệu thoát nên ít chịu sụt giảm năm 2022 hơn xnoquant (11,29× vs 8,66×).
  - **Quyết định 07/10/2026**: Giữ nguyên cơ chế bảo toàn vị thế của Nora. Độ lệch giữa Nora và xnoquant là **khác biệt chấp nhận được**, không chỉnh sửa thêm engine để bám đuôi xnoquant. Test `test_kema_long_matches_xno` được giữ với đánh dấu xfail để giám sát chống trôi số liệu.
- **Công thức Sharpe của xnoquant**: Chưa công bố chính thức; Nora tính Sharpe = `mean(r) / std(r, ddof=1) × √252` trên lợi suất ngày, **không trừ lãi suất phi rủi ro** ($R_f = 0$), và đánh dấu `unverified` ở bộ xno (khối `nora` dùng √365; xem `p8_education_user_alpha.md` §8).
- **Dữ liệu**: Bộ TOP10 spot 1m từ 2019-10 đã sẵn sàng tại `data/binance_hist` (1,8G), phục vụ đầy đủ cho các test parity và job studio.

