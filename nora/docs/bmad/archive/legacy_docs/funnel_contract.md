# Phễu kiểm duyệt alpha: thiết kế và hợp đồng

Mục đích: chạy **mọi alpha đã sinh** (chiến lược × tham số, tới 1.000.000) qua các tầng kiểm duyệt ngày càng khắt khe
để tìm alpha **thắng thật, sống sót được**, dùng cho testnet rồi live. Mỗi tầng có **danh sách lệnh**, **thống kê
tổng quan** cho nhóm vào và nhóm ra, **lý do loại**, và **phân tích theo chiến lược và tham số**.
Mọi dữ liệu đều thật: quality gate bắt buộc, không mock.

## 1. Các tầng (theo thứ tự)

| Mã | Tầng | Dữ liệu | Điều kiện qua (hằng số trong `backend/optimize/funnel/gates.py`) |
|---|---|---|---|
| `S0_generate` | Sinh alpha | không gian tham số của chiến lược | hợp lệ (vd. ngân sách DCA); mỗi alpha có `alpha_id` = sha1(chiến lược, tham số chuẩn hoá) |
| `S1_backtest` | Backtest sàng lọc | dev1 | lãi > 0, MDD ≤ 30%, số lệnh ≥ ngưỡng, số tài sản có lãi ≥ ngưỡng (danh mục) |
| `S2_antiluck` | Chống ăn may (xếp hạng) | dev1 (+ lân cận) | **top 5% DSR** trong các alpha đã qua S1 của cùng chiến lược (ít nhất 3; DSR với N hiệu dụng — gom cụm lần thử tương quan > 0,7, `antiluck.effective_trials`) VÀ lân cận tham số (±1 bước mỗi khoá) có lãi ≥ 60%. PBO > 0,5 chỉ **cảnh báo** (`pbo_flag`). (Trước 03/10/2026: DSR ≥ 0,95 + PBO > 0,5 loại cả chiến lược — chặn 100% kể cả nhóm alpha lãi trên holdout; quyết định nay thuộc các cổng ngoài mẫu S3/S4/S6) |
| `S3_wfa` | Walk-forward | dev2 | fold ≥ 5, ≥ 3 fold có lệnh, lãi kép OOS > 0, **t-stat lãi theo fold ≥ 1** (fold có lệnh), **bỏ fold tốt nhất vẫn ≥ −2%**, MDD fold xấu nhất ≤ 30%, lãi IS TB ≥ 0. (Trước 03/10/2026: "≥ 60% fold OOS lãi" — sai với lãi lệch phải của chiến lược theo xu hướng; xem `core/metrics/returns.fold_stats`) |
| `S4_montecarlo` | Monte Carlo | chuỗi ngày OOS của S3 | ≥ 10.000 kịch bản, P(MDD ≥ 30%) ≤ 5%, mọi kịch bản cực xấu MDD < 50% và không cháy |
| `S5_sizing` | Khối lượng sống sót | như S4 | tìm hệ số vốn lớn nhất s ∈ (0, 1] qua mọi điều kiện S4 (tìm nhị phân trên chuỗi ngày nhân s, rồi **xác nhận bằng backtest + WFA + MC thật ở s**); s < 0,2 → loại |
| `S6_holdout` | Holdout (chấm một lần) | 20% cuối | ở hệ số s: lãi > 0, MDD ≤ 30% (cả khớp đúng mức và giá xấu nhất) |
| `FINAL` | Đủ điều kiện testnet | | qua mọi tầng; ghi vào kho alpha kèm s và toàn bộ bằng chứng |

Alpha bị loại ở tầng k thì dừng; lý do loại lưu dạng mã + câu tiếng Việt (vd. `S3.positive_ratio: 40% < 60%`).

**Regime (P2.5/P2.7, `FunnelConfig.regime`):** `off` (mặc định) | `learn` | `both`. Biến thể `learn` là khoá `"regime": "learn"` trong `params` của alpha
→ `alpha_id` riêng → mỗi biến thể là MỘT lần thử: N của DSR và ma trận PBO ở S2 đếm đủ cả hai biến thể (`both` → số alpha gấp đôi).
Alpha `learn` học bảng regime (`core/regime/learn.py`: chặn regime có ≥ 5 lệnh và tổng lãi ≤ 0) trên cửa sổ HỌC rồi mới chạy: S1/S2 = chính dev1 (trong mẫu,
đã bị DSR/PBO phạt như mọi lựa chọn trong mẫu), S3 OOS = train của từng fold, S6 holdout = toàn bộ dữ liệu trước holdout. Ngưỡng của classifier
(`classifier.DEFAULTS`) KHÔNG tối ưu; nếu sau này tối ưu thì phải đưa vào `params` như trên để được đếm. S1/S6 ghi `regime_blocked`; promote dựng
`regime` của kho từ `regime_blocked` của S6.
**Trend thẳng đứng (P2.6):** S3 ghi `metrics.shock` (vị thế ngược chiều lớn nhất ở OOS); S4/S5 thêm 3 kịch bản `vertical_*` vào MC (xem ui_contract §5).

## 2. Lưu trữ một lượt phễu (`data/_cache/funnel/<run_id>/`)

- `run.json`: cấu hình (chiến lược, số alpha, seed, cửa sổ, ngưỡng, commit, sha256 dữ liệu), trạng thái từng tầng, thời gian.
- `results.sqlite` (WAL): bảng `alphas(alpha_id, strategy, params_json, stage_reached, rejected_stage, reject_code, reject_msg, final_scale)`
  và `stage_metrics(alpha_id, stage, metrics_json)` (lãi, MDD, Sharpe, Sortino, số lệnh, win rate, profit factor, DSR, PBO cờ, số fold lãi…).
- `trades/<stage>/part-*.parquet`: danh sách lệnh (cột `alpha_id, stage, fold, symbol, side, enter_time, close_time, enter_price, close_price, qty, pnl_usd, pnl_pct, fees_usd, funding_usd, status, layers, mae_pct`).
  - Lưu **toàn bộ** lệnh cho mọi alpha **qua** S1 trở đi (S3 lưu lệnh OOS theo fold; S6 lệnh holdout).
  - Alpha **bị loại ở S1**: chỉ lưu thống kê; danh sách lệnh **tính lại khi cần** (deterministic, trùng từng bit) qua API.
- `daily/<stage>/part-*.parquet`: chuỗi NAV ngày cho alpha qua S1 (để vẽ và chạy MC).
- `mc/<alpha_id>.json`: tóm tắt 10.000 kịch bản, quạt, bảng kịch bản cực xấu, kết quả tìm s.
- Có resume: chạy lại cùng `run_id` thì bỏ qua phần đã xong.

## 3. Thống kê mỗi tầng (`GET /api/studio/funnel/runs/{run_id}/stages/{stage}/stats`)

```json
{
  "stage": "S3_wfa", "input": 1000, "passed": 87, "rejected": 913,
  "reject_reasons": [{"code": "S3.positive_ratio", "label": "Tỉ lệ fold lãi < 60%", "count": 610}],
  "distributions": {"ret_pct": {"in": {"bins": [], "p5": 0, "p50": 0, "p95": 0}, "out": {}},
                    "mdd_pct": {}, "sharpe": {}, "trades": {}, "win_rate": {}, "profit_factor": {}},
  "by_strategy": [{"strategy": "breakout_4h_long", "input": 400, "passed": 50, "pass_rate": 12.5,
                   "median_ret_pct": 0, "median_mdd_pct": 0, "best_alpha_id": "..."}],
  "param_survival": [{"strategy": "...", "param": "stop_loss_rate", "values": [{"value": 2.0, "input": 120, "passed": 30}]}],
  "top": [{"alpha_id": "...", "strategy": "...", "params": {}, "metrics": {}}]
}
```
`in` là nhóm vào tầng, `out` là nhóm qua tầng. Phân phối dùng 30 bin cố định theo khoảng phân vị 1–99 của nhóm vào.

## 4. API

- `POST /api/studio/funnel/runs` `{strategies: [...], n_per_strategy | full_grid, seed, symbols?, windows?, resume_run_id?}` → `{run_id, job_id}`, chạy qua hàng đợi `run_limited` như các job khác.
- `GET /api/studio/funnel/runs` → danh sách lượt (trạng thái, số alpha mỗi tầng).
- `GET /api/studio/funnel/runs/{id}` → `run.json` + đếm theo tầng (`counts: [{stage, input, passed}]`) + tiến độ/ETA.
- `GET …/stages/{stage}/stats` (mục 3).
- `GET …/alphas?stage=&status=passed|rejected&strategy=&sort=&offset=&limit=` → bảng alpha (phân trang).
- `GET …/alphas/{alpha_id}` → tham số, chỉ số từng tầng, lý do loại, s, đường NAV các tầng.
- `GET …/alphas/{alpha_id}/trades?stage=&fold=&offset=&limit=` → danh sách lệnh (phân trang); nếu chưa lưu (bị loại ở S1) thì `recompute=true` để tính lại (trả về `recomputed: true`).
- `POST …/alphas/{alpha_id}/promote` → ghi alpha FINAL vào `data/alphas/registry.json` (kèm s, bằng chứng) + cấu hình testnet; cần xác nhận ở UI.

## 5. UI: trang "Phễu kiểm duyệt" (`/funnel`)

- Danh sách lượt chạy + nút tạo lượt mới (chọn chiến lược, số alpha, ước tính thời gian trước khi chạy).
- Biểu đồ phễu: số alpha còn lại qua từng tầng, tỉ lệ qua và lý do loại chính của mỗi tầng.
- Chọn một tầng → tab **Thống kê** (phân phối nhóm vào/ra chồng lên nhau, bảng theo chiến lược, sống sót theo giá trị tham số, lý do loại),
  tab **Alpha** (bảng phân trang, lọc qua/loại, sắp xếp), tab **Lệnh** (danh sách lệnh của alpha đang chọn ở tầng đó).
- Chi tiết alpha: hành trình qua các tầng (✓/✗ + lý do), chỉ số từng tầng, NAV, danh sách lệnh theo tầng/fold,
  Monte Carlo (quạt + kịch bản cực xấu + hệ số s), nút "Đưa vào kho alpha" cho alpha FINAL.

## 6. Triển khai backend (đã làm) — chi tiết ngữ nghĩa + hình dạng phản hồi

Mã: `backend/optimize/funnel/` (`gates.py` ngưỡng, `generate.py` S0, `antiluck.py` DSR/PBO/lân cận, `sizing.py` tìm s, `storage.py` kho, `stats.py` thống kê,
`backtest.py` worker, `orchestrator.py` điều phối, `recompute.py`, `promote.py`), CLI `backend/optimize/run_funnel.py`, router `backend/api/routers/funnel.py`.
Chạy: `ops/run_limited.sh -- -m backend.optimize.run_funnel --strategies a,b --n-per-strategy 200 --seed 7` (`--full-grid`, `--resume <run_id>`, `--until <tầng>`).

### 6.1 Ngữ nghĩa từng tầng (chỗ hợp đồng để ngỏ)
- **alpha_id** = `sha1(chiến lược + "|" + JSON tham số chuẩn hoá (khoá sắp xếp))[:16]`. Lấy mẫu cùng thuật toán `build_strategy_book.iter_configs` (theo chỉ số lưới).
- **S1**: một `PortfolioEngine` trên dev1 cho CẢ vũ trụ (rủi ro chuẩn 0,5%/lệnh, SL khớp đúng mức, kill switch tắt) — cùng máy với giai đoạn A của build_strategy_book.
  Ngưỡng: lãi > 0, MDD ≤ 30%, ≥ 40 lệnh, ≥ 5 tài sản có lãi (đúng `strategy_book.GATES`). Mã loại: `S1.ret_nonpositive`, `S1.mdd`, `S1.min_trades`, `S1.symbols_positive`.
  **Lệch nhỏ so với §2**: alpha bị loại ở S1 vẫn lưu **chuỗi lợi suất ngày** (`daily/S1_backtest`, 1 hàng/alpha, list<double>) vì DSR/PBO cần ma trận ngày của MỌI alpha đã thử;
  vẫn **không** lưu danh sách lệnh (tính lại qua API).
- **S2**: thứ tự kiểm PBO(chiến lược) → DSR → lân cận (lân cận chỉ chạy cho alpha còn sống sau hai kiểm tra đầu). N = số alpha đã chấm xong S1 của chiến lược (có `sr_daily`);
  phương sai Sharpe các lần thử lấy từ MỌI alpha đó; Sharpe/độ lệch/kurtosis THEO NGÀY. PBO: CSCV 16 khối (12.870 cách chia), tối đa 2000 alpha điểm IS (lãi/MDD) cao nhất,
  hạng trung bình khi hoà, ít hơn 4 alpha thì không đo (không gắn cờ). Lân cận = ±1 bước lưới mỗi khoá; "có lãi" = lãi dev1 > 0; kết quả S1 đã lưu (kể cả điểm bị loại ở S1) được dùng lại,
  điểm chưa có thì chạy backtest dev1 và ghi vào `stage_metrics` với `stage="S2_neighbour"` (không phải tầng của phễu, không có trong bảng `alphas`). Mã: `S2.pbo`, `S2.dsr`, `S2.neighbor`.
- **S3**: mỗi alpha chạy MỘT mình, tham số cố định; fold train 120 / test 30 ngày trên dev2. Mỗi fold: IS = backtest cửa sổ train (SL level, kill tắt), OOS = backtest cửa sổ test
  (**chỉ SL "extreme"** = cơ sở kết luận, kill BẬT). (Không chạy OOS "level" để giảm một nửa chi phí; S6 vẫn chấm cả hai.) Lưu lệnh OOS (cột `fold`) + chuỗi ngày OOS theo fold cho MỌI alpha được chấm ở S3.
  Mã: `S3.folds`, `S3.positive_ratio`, `S3.oos_compound`, `S3.worst_fold_mdd`, `S3.avg_is`.
- **S4**: `run_monte_carlo_daily_detail` (≥ 10.000 kịch bản, 5 kịch bản cực xấu + worst_bootstrap) trên chuỗi ngày OOS nối của S3 ở **s = 1** → `mc/<alpha_id>.json`.
  **Làm rõ hợp đồng**: để S5 có nghĩa, S4 KHÔNG loại alpha chỉ vì trượt ở s = 1; S4 đạt khi **qua mọi check MC ở khối lượng tối thiểu s = 0,2** (còn cứu được bằng giảm khối lượng).
  Số đo S4 ghi cả `passes_full_size`, `p_mdd_ge_30`/`stress_max_mdd` ở s = 1 và ở s = 0,2. Mã: `S4.days`, `S4.simulations`, `S4.p_mdd`, `S4.stress_mdd`, `S4.stress_ruin`.
- **S5**: tìm nhị phân s ∈ [0,2, 1] (dung sai 0,01, làm tròn xuống 0,01) trên chuỗi ngày × s; rồi **xác nhận bằng chạy thật** ở s: backtest dev1 (qua cổng S1) + WFA (qua cổng S3) + MC (10.000, qua cổng S4) ở s = 1 trên chuỗi OOS thật của lần chạy ở s.
  Quy đổi s → khối lượng: các chiến lược dùng `sizing="risk"` nên `risk_per_trade_pct = 0,5 × s` làm qty mọi lệnh ∝ s (sizing `margin_pct`: nhân `order_size_pct`). Không tỉ lệ tuyệt đối vì trần danh nghĩa/đòn bẩy/trần tổng danh nghĩa, nên phải xác nhận thật.
  Xác nhận trượt → hạ s thêm 0,05 và xác nhận lại (tối đa 4 lần; s < 0,2 → `S5.scale_low`, hết lượt → `S5.confirm`). `mc/<alpha_id>.json`: `mc` = MC trên chuỗi đã xác nhận ở s, `mc_full_size` = MC S4 ở s = 1,
  `scale_search` = `[{s, passed, p_mdd_ge_30, stress_max_mdd}]`, `attempts`, `verified: {backtest, wfa, mc}`. Lệnh/ngày OOS ở s lưu ở `trades/S5_sizing`, `daily/S5_sizing`.
- **S6**: holdout chấm MỘT lần ở s với kill switch BẬT; đạt khi **cả** khớp đúng mức (`level`) **và** giá xấu nhất (`extreme`) có lãi > 0 và MDD ≤ 30%. Lệnh `level` ở `trades/S6_holdout` (cột `stage="S6_holdout"`),
  lệnh `extreme` cùng thư mục với `stage="S6_holdout_extreme"`. Mã: `S6.holdout_ret`, `S6.holdout_mdd`.
- **FINAL**: `alphas.final_scale = s` (chỉ đặt ở FINAL); số đo S5 có `final_scale` cho mọi alpha qua S5.

### 6.2 Kho: phần thêm so với §2
`results.sqlite`: ngoài `alphas`/`stage_metrics` còn `parts`, `alpha_files`, `kv`; `alphas` thêm `ord`, `stage_idx`, `rejected_idx`; `stage_metrics` thêm `passed` và cột phẳng `ret_pct, mdd_pct, sharpe, trades, win_rate, profit_factor, score`
(`score = ret_pct / max(mdd_pct, 1)`). Parquet `enter_time`/`close_time` = epoch ms (int64). `daily/<stage>/part-*.parquet`: `alpha_id, stage, fold, start_date, rets`. SQLite là sổ cam kết: file parquet chưa commit bị dọn khi resume.
`stage_metrics` khoá số đo: S1 `ret_pct, mdd_pct, sharpe, sortino, trades, win_rate, profit_factor, symbols_positive, sr_daily, skew, kurt, n_days, by_symbol…`; S2 thêm `dsr, dsr_sr0, neighbor_ratio, neighbor_n, pbo_strategy, pbo_flag, n_trials`;
S3 thêm `folds, folds_profitable, positive_ratio (0..1), worst_fold_mdd, is_ret_avg, fold_detail[]`; S4 thêm `p_mdd_ge_30, stress_max_mdd, simulations, mdd_p95, passes_full_size, min_size_*`;
S5 thêm `final_scale, search_s, search_steps, confirm_attempts`; S6 thêm `extreme_ret_pct, extreme_mdd_pct`.

### 6.3 Hình dạng phản hồi API (`/api/studio/funnel`)
- Sắp xếp: `sort=-ret_pct` (dấu `-` đầu = giảm dần); khoá: `ret_pct, mdd_pct, sharpe, trades, win_rate, profit_factor, score, final_scale, order`; mặc định `-score` (có `stage`) / `order`.
- `POST /runs` → `{run_id, job_id}`; job loại `funnel_run` (đăng ký vào `batch.KINDS` lúc nạp router; `run_id` nằm trong `args` của job và trong `run.json`/`api_job.json`). `run_id` dạng `fr-YYYYMMDD-xxxxxx`.
  Body thêm: `force_large` (> 200.000 alpha, trần cứng 1.000.000). `resume_run_id` chạy tiếp lượt cũ (cấu hình lấy từ `run.json`). API ghi `run.json` trạng thái `queued` ngay khi nhận.
- `GET /runs` → `{runs:[{run_id, job_id, status, created, started, finished, strategies, n_per_strategy, full_grid, total_alphas, counts:[{stage, input, done, passed, rejected, top_reject:{code,label,count}|null}], progress:{stage,done,total,eta_s,rate,peak_rss_mb}|null}]}`.
  `input` = số alpha đủ điều kiện vào tầng (= số qua của tầng trước), `done` = số đã chấm (khác `input` khi tầng đang chạy). `GET /runs/{id}` = bản ghi trên + `config, stages, until, wall_s`.
- `GET …/stages/{stage}/stats`: đúng §3 (`input` = số đã chấm của tầng; thêm `eligible`, `label`; S2 thêm `strategy_level:{chiến lược:{n_trials, sr_var, pbo, flag…}}`). Bin: `[{lo, hi, count}]`, kèm `n, p5, p50, p95`. Tầng đã xong được ghi đệm `stats/<stage>.json`.
- `GET …/alphas` → `{total, offset, limit, stage, items:[{alpha_id, strategy, params, stage_reached, rejected_stage, reject_code, reject_msg, final_scale, metrics}]}`; `metrics` phẳng của `stage` được hỏi (không có `stage`: của tầng alpha đã tới).
- `GET …/alphas/{id}` → các trường alpha + `stage_metrics:{tầng:{…}}`, `metrics` (tầng đã tới), `nav:{tầng:{dates, values}}` (S1/S3/S5/S6; vốn đầu 10.000), `mc` (cùng dạng `POST /book/mc`: `summary, fan, mdd_hist, ret_hist, stress, worst_path, gate, params`; sau S5 là MC ở s đã xác nhận),
  `mc_full_size`, `scale_search`, `verified`, `confirm_attempts`, `min_size`, `stored_trades:{tầng: bool}`.
- `GET …/alphas/{id}/trades?stage=&fold=&offset=&limit=&recompute=` → `{items, total, offset, limit, stage, fold, stored, folds?}`; item: `fold, symbol, side, enter_time (ISO UTC), close_time, enter_price, close_price, qty, pnl_usd, pnl_pct, fees_usd, funding_usd, status, layers, mae_pct`.
  Chưa lưu (loại ở S1) → `stored:false, items:[], can_recompute:true`; `recompute=true` → tính lại tất định (tiến trình con `run_limited --no-lock -m backend.optimize.funnel.recompute`, đệm ở `<run>/recomputed/`) → thêm `recomputed:true`.
- `POST …/promote` body `{confirm: true, note?}` (thiếu confirm → 400; chưa FINAL → 409) → `{registry_path, alpha_id, registry_alpha_id, final_scale, testnet_config}`: thêm/ thay mục `funnel__<chiến lược>__<alpha_id>` trong `registry.json`
  (cùng các khoá của `registry.build_registry` + khoá mới `funnel` chứa s, bằng chứng, MC) và ghi `testnet/funnel__….json` (định dạng `testnet/book.json`, rủi ro/lệnh = 0,5 × s).
- Thêm (ngoài hợp đồng gốc): `POST /runs/{id}/cancel` (SIGTERM → resume được), `GET /estimate?strategies=&n_per_strategy=|full_grid=&workers=` (ước tính thời gian S1 trước khi chạy).

## 7. Số đo mở rộng của alpha (02/10/2026)

`metrics_json` mỗi tầng có thêm (core/metrics/portfolio.flat_extras): `cagr_pct`, `calmar`, `cvar95_pct`, `max_dd_days`, `payoff`,
`expectancy_pct`, `max_consec_losses`, `top5_share_pct`, `mae_worst_pct`, `liq_proximity_max_pct`, `liquidations`, `fee_drag_pct`,
`mdd_daily_pct`, `mdd_intrabar_pct` (S1/S6), `mdd_basis` ("intrabar" ở S1/S6, "daily" ở S3–S5). `GET /alphas?sort=` nhận thêm các khoá này
(đọc bằng json_extract; thêm "-" để giảm dần). Bảng lệnh có thêm `strategy`, `margin_usd`, `leverage`, `entry_equity`.

## 8. Xuất bản sổ từ alpha FINAL (04/10/2026)

`POST /api/studio/funnel/runs/{run_id}/book` `{alpha_ids: [...], risk_per_trade_pct, wfa_job_id, dry_run}` → job `funnel_book`
(`backend/optimize/funnel/publish.py`): mỗi chiến lược một alpha FINAL (bỏ khoá regime); `wfa_job_id` phải là job `book_wfa` advanced chạy ĐÚNG các
cấu hình đó ở cùng rủi ro và gate QUA; holdout (dev2_end → end, khung của lượt) chấm một lần bằng `evaluate_s6` → `registry.write_book` ghi `book.json`
(READY_FOR_TESTNET + `testnet/book.json` khi đạt, HOLDOUT_FAILED khi trượt). S5 tìm s ∈ [0,2; 3,0] (rủi ro/lệnh tối đa 1,5%).
