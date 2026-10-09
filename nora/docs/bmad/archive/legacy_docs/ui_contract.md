# Hợp đồng API cho giao diện Nora (v2)

Một vòng trên UI: **Alpha** (hiệu chỉnh tham số từ chiến lược có sẵn) → **Backtest** → **WFA** → **Monte Carlo** →
xem kết quả trên **Danh mục** (chỉ dữ liệu backtest). Bot đang chạy thật (OKX paper/demo) xem riêng ở trang **Live**
(`GET /api/studio/live/trades`, gồm `equity_series` và `started`); hai nguồn không bao giờ trộn.

Quy ước chung:
- Thời gian là ms UTC. Ngày dạng `YYYY-MM-DD` (UTC). Tiền tệ USDT. Phần trăm là số đã nhân 100 (`4.85` = 4,85%).
- Job nặng chạy nền qua hàng đợi `run_limited` (`backend/api/jobs/batch.py`). Client poll `GET /api/studio/book/jobs/{id}` mỗi 2 s.
- Trạng thái job (`status`): `queued` (đang chờ job khác) | `running` | `done` | `failed`.
- Lỗi theo FastAPI: `{detail}` với mã 4xx/5xx; 429 khi đã có quá nhiều job đang chờ.

## 1. Danh mục chiến lược, sổ, kho alpha (đã có)
`GET /api/studio/book/` →
```json
{
  "book": {"status": "HOLDOUT_FAILED|READY_FOR_TESTNET", "strategies": [{"id": "...", "params": {}}], "evidence": {}},
  "wfa": {...}, "latest_wfa": {"report_dir": "...", "gate": {}, "summary": {}},
  "catalog": [{"id": "trend_long", "family": "...", "side": "LONG", "description": "...", "space": {"stop_loss_rate": [1.5, 2.5, 3.5]},
               "default_params": {"stop_loss_rate": 2.5}}],
  "candidates": [... cùng nội dung với catalog ...],
  "universe": ["BTC@perp", "..."],
  "windows": {"start": "2023-10-20", "dev1_end": "2024-12-24", "dev2_end": "2026-02-27", "end": "2026-09-30"},
  "assets": [{"symbol": "BTC@perp", "venue": "cex", "market": "perp", "candles": {"start_ts": 0, "end_ts": 0}, "ticks": null},
             {"symbol": "AERO", "venue": "dex", "market": "spot", "candles": {"start_ts": 0, "end_ts": 0},
              "ticks": {"start_ts": 0, "end_ts": 0, "rows": 16967, "window_days": 3}, "network": "base", "fee_rate": 0.003}]
}
```
`assets` = mọi tài sản có dữ liệu (ms UTC). `ticks` chỉ có ở DEX đã crawl tick (null nếu chưa); `fee_rate` = phí pool đã xác minh on-chain (null nếu chưa có).
`catalog` và `candidates` là cùng một danh sách (giữ cả hai để tương thích); `wfa` và `latest_wfa` cũng vậy. `default_params` = giá trị giữa của mỗi khoá trong `space`
(giống `run_book_backtest`). UI đọc `catalog || candidates`, `latest_wfa || wfa`.

`GET /api/studio/alphas` (mới) → `{"registry": <data/alphas/registry.json hoặc null>, "book": <data/alphas/book.json hoặc null>}`.

## 2. Backtest (đã có job)
`POST /api/studio/book/backtest`
```json
{"strategies": [{"id": "breakout_4h_long", "params": {"stop_loss_rate": 2.0}}],
 "symbols": ["BTC@perp", "SOL@perp"], "start": "2025-03-01", "end": "2025-04-30",
 "risk_per_trade_pct": 0.5, "stop_fill": "level"}
```
→ `{"job_id": "..."}`. Bỏ `strategies` → dùng `data/alphas/book.json`.
Tài sản DEX (`symbols: ["AERO"]` hoặc `"dex:AERO"`): spot, chỉ chân LONG (SHORT / "Cả hai chiều" → 422), bắt buộc chọn `strategies`, không trộn với perp; WFA / phễu chưa hỗ trợ DEX.
`data`: `"candle"` (mặc định) | `"tick"` (chỉ DEX đã crawl tick: mỗi swap on-chain là một bước khớp lệnh, chi phí AMM đúng theo dự trữ pool; cửa sổ cắt theo độ phủ tick,
tối thiểu một nến cơ sở). Chỉ `data="tick"`: `latency_ms` (mặc định = thời gian một block của mạng), `gas_usd` (mặc định theo mạng). Kết quả tick: cùng lược đồ + `config.data="tick"`,
`config.tick_window`, `config.latency_ms`, `config.cost_model`, `tick_stats` (xem `backend/core/backtest/tick_run.py`).

Chỉ `POST` trả khoá `job_id`. Các hàng job (GET) dùng khoá **`id`** (kèm `state`, bằng `status`); UI chuẩn hoá `job_id = job_id || id`.
`GET /api/studio/book/jobs/{id}` → `{"id","kind","args","pid","status","state","waiting_in_queue","created","started","finished","exit_code","log_tail":[...],"result":{...}|null}`
(`created/started/finished` là giây Unix; `result` chỉ có khi `done`).
`GET /api/studio/book/jobs?kind=book_backtest|book_wfa|book_build&limit=20` → `{"jobs":[{id, kind, status, created, args, label, ...}]}` (đã lọc theo `kind`).
`result` của backtest: `{ret_pct, mdd_pct, sharpe, trades, daily_nav, trade_list, equity_curve, by_symbol, by_strategy, halted_at, ...}`.

## 3. Payload Danh mục (mới)
`GET /api/studio/portfolio/dashboard?source=backtest&job_id=<id>&period=1M|3M|YTD|1Y|ALL`
`source` chỉ nhận `backtest` (mặc định); mọi giá trị khác (`live`, `testnet`, `paper`, ...) → 422.
Payload khi có dữ liệu:
```json
{
  "available": true,
  "source": {"kind": "backtest", "job_id": "...", "label": "...", "start": "2025-03-01", "end": "2025-04-30",
             "strategies": ["..."], "symbols": ["..."], "benchmark": "BTC@perp"},
  "period": "3M",
  "kpis": {
    "nav": 10234.5, "nav_change_day": 12.3, "nav_change_day_pct": 0.12,
    "pnl_today": 12.3, "pnl_month": 120.0, "pnl_year": 230.0,
    "ret_period_pct": 4.85, "bench_ret_period_pct": -0.23, "excess_pct": 5.08,
    "sharpe": 2.9, "sortino": 5.03, "calmar": 8.86,
    "mdd_pct": -2.35, "dd_now_pct": 0.0,
    "var95_1d": 61.4, "var95_pct": 0.60, "cvar95_1d": 67.2,
    "spark_nav": [...], "spark_ret": [...], "spark_dd": [...]
  },
  "series": {
    "dates": ["2025-03-01", "..."],
    "nav": [...], "bench": [...],
    "drawdown_pct": [...],
    "daily_pnl": [...],
    "rolling_sharpe_63": [...]
  },
  "distribution": {"bins": [{"lo": -0.6, "hi": -0.5, "count": 2}], "var95_pct": -0.60},
  "monthly": {"years": [{"year": 2025, "months": [2.3, null, ...], "total": 12.7}]},
  "risk": {
    "margin_used_pct": null, "exposure_gross_pct": 132, "exposure_net_pct": 95,
    "by_market": [{"name": "Crypto perp", "long_pct": 70, "short_pct": 13}],
    "cagr_pct": 20.8, "vol_annual_pct": 6.6, "win_days_pct": 58.7, "active_days": 52, "profit_factor": 1.6,
    "open_positions": 3, "strategies_running": 2
  },
  "strategies": [{"id": "breakout_4h_long", "side": "LONG", "status": "active", "weight_pct": 50,
                  "pnl": 120.4, "contribution_pct": 1.2, "sharpe": 1.4, "mdd_pct": -3.1, "pnl_30d": [...]}],
  "events": [{"time": 1745146440000, "level": "warn|crit|info", "text": "..."}],
  "positions": [{"symbol": "SOL@perp", "strategy": "trend_long_perp__SOL", "side": "LONG", "qty": 59.71, "entry_price": 119.12,
                 "mark_price": 120.48, "notional": 7193.89, "unrealized_pnl": 77.42, "opened": 1790662500000, "margin_usd": 7112.91}],
  "mock": true, "mock_note": "Dữ liệu giả lập — chưa kết nối tài khoản Live"
}
```
- Không có `job_id` : dùng backtest xong gần nhất; chưa có backtest nào thì `available:false` kèm `reason`.
- `bench`: mua giữ `BTC@perp`, quy về cùng NAV đầu kỳ. `drawdown_pct` ≤ 0, tính trên NAV theo ngày (nên `mdd_pct` KPI khác MDD intrabar của `result.mdd_pct`). Mọi chuỗi trong `series` cùng độ dài với `dates`.
- `period` cắt chuỗi ngày theo cuối kỳ của dữ liệu; KPI kỳ tính trên phần đã cắt, còn `mdd`/Sharpe theo kỳ.
- `risk.win_days_pct` = tỉ lệ ngày lãi **trong các ngày có P&L khác 0** (`risk.active_days` = số ngày đó, `null` nếu 0): ngày đứng ngoài thị trường không tính là ngày lỗ. UI ghi nhãn "Tỉ lệ ngày lãi (ngày có giao dịch)".
- Exposure/vị thế mở: tại ngày cuối của kỳ, tính từ `trade_list` (danh nghĩa / NAV) cộng `positions` (feed live/testnet/giả lập).
- `positions[]` = vị thế **đang mở** tại điểm cuối dữ liệu (không đổi theo `period`): `qty`, `entry_price` (giá TB), `mark_price` (giá đóng cửa cuối), `notional` = qty × mark,
  `unrealized_pnl` (sau phí vào lệnh; funding đã nằm trong NAV), `opened` (ms UTC), `margin_usd`. Sắp theo `notional` giảm dần. Backtest đã đóng mọi vị thế cuối kỳ nên `positions = []`.
  Vị thế đang mở được tính vào NAV (MTM) nhưng chưa vào `strategies[].pnl` (chỉ lãi/lỗ đã chốt). UI ẩn bảng "Vị thế đang mở" khi rỗng.
- `strategies[]`: số liệu **đã thực hiện** (realised: lãi/lỗ các lệnh đã đóng, Sharpe/MDD theo chuỗi realised của chiến lược), nên tổng không khớp từng đồng với NAV mark-to-market.
- `events`: dựa trên MDD intrabar xấu nhất (không phải NAV ngày): kill switch (`halted_at`), drawdown vượt 50%/80% hạn mức 30%, và số **lần vào lệnh** bị chặn bởi giới hạn rủi ro danh mục
  (`result.risk_blocked_attempts`: các phút liên tiếp bị chặn của cùng một tracker tính là một lần; `rejected_for_risk` vẫn là số phút, golden dựa vào đó). Lời văn:
  "N lần vào lệnh bị chặn do giới hạn rủi ro danh mục (tối đa X vị thế / Y mỗi tài sản / trần exposure Z× vốn)"; kết quả cũ không có `risk_blocked_attempts` thì chỉ nêu sự việc, không nêu số.

### Bộ số đo chuẩn trong payload Danh mục (02/10/2026)

`GET /api/studio/portfolio/dashboard` trả thêm (null với kết quả job cũ):
- `stats` = `portfolio_metrics(...)["stats"]` của TOÀN kỳ chạy (không cắt theo `period`): `returns` (ret_pct, cagr_pct, vol_ann_pct, sharpe,
  sortino, calmar, mdd_daily_pct, max_dd_days, recovery_days, ulcer_index, var95_pct, cvar95_pct, skew, kurt, days, win_days_pct,
  best/worst_day_pct), `trades` (trades, wins, losses, breakeven, win_rate, loss_rate, profit_factor, payoff, expectancy_usd/pct,
  avg_win/loss_usd, best/worst_trade_usd/pct, max_consec_wins/losses, top5_share_pct, avg/max_hold_h, fees_usd, funding_usd, fee_drag_pct,
  long/short {trades, pnl_usd, win_rate}, layers_avg/max, mae_avg/worst_pct, liq_proximity_max_pct, liquidations), `exposure`
  (time_in_market_pct, peak_margin_pct, exposure_gross/net_avg/max_pct, max_concurrent), `correlation` ({pairs, avg, max} hoặc null).
- `mdd` = `{intrabar_pct, daily_pct}` — MDD trong nến (giá xấu nhất của nến) và theo ngày của toàn kỳ chạy.

## 4. WFA (đã có job, bổ sung cấu hình cố định)
`POST /api/studio/book/wfa`, một trong ba dạng:
- `{"report_dir": "..."}`: các chiến lược đã đạt của một lần build;
- `{"candidates": ["id"], "n": 3}`: lấy mẫu `n` cấu hình mỗi chiến lược;
- **mới:** `{"strategies": [{"id": "...", "configs": [{...}, {...}]}]}`: cấu hình do người dùng chọn. Một cấu hình mỗi chiến lược nghĩa là tham số cố định (WFA chỉ kiểm OOS cuộn).
Cùng các trường tuỳ chọn `start`, `end`, `train_days`, `test_days`, `symbols`, `risk_per_trade_pct`, `timeframe` (`15m`|`1h`|`4h`),
`regime` (`off` mặc định | `learn`: mỗi fold học bảng regime ↔ chiến lược trên train — `core/regime/learn.py` — rồi áp lên test; fold có thêm
`regime_map` {id: {allowed, fuse, blocked}} và `train_by_regime`; kết quả có `regime: "learn"`).
`summary.shock` = `{crash_loss, surge_loss, max_long_exposure, max_short_exposure}`: vị thế ngược chiều lớn nhất của các fold OOS (extreme), dùng cho
3 kịch bản trend thẳng đứng của MC (§5).
Kết quả (`result` của job) là `report.json` của `validate_book.py`: `folds[]`, `summary`, `gate`, và các bí danh theo hợp đồng
`aggregate` (= `summary`) và `mc` (= `summary.mc`) — cùng một đối tượng, UI đọc `aggregate`/`mc`.
Gate WFA danh mục (03/10/2026): `active_folds` (≥ 3 fold có lệnh), `fold_t` (t-stat lãi theo fold OOS extreme ≥ 1), `ex_best_fold`
(lãi kép OOS bỏ fold tốt nhất ≥ −2%) thay cho `positive_folds`; summary có thêm `fold_t`, `oos_ex_best_pct`, `n_active_folds`.
`aggregate.oos_daily` và `aggregate.oos_daily_dates` đều là `{level: [...], extreme: [...]}`, song song theo chỉ số
(ngày `YYYY-MM-DD`), để UI vẽ đường vốn OOS. `gate = {passed, checks: {<khoá>: {label, required, actual, passed}}}`.

## 5. Monte Carlo (đồng bộ, nhẹ): >= 10.000 kịch bản + kịch bản cực xấu
`POST /api/studio/book/mc`
```json
{"wfa_job_id": "...", "basis": "extreme|level", "simulations": 10000, "block_days": 5, "horizon_days": 365,
 "ruin_threshold_pct": 30, "seed": 7, "scale": 1.0, "stress_max_mdd_pct": 50, "extra_cost_daily_pct": null}
```
hoặc gửi trực tiếp `"daily_returns": [...]` thay cho `wfa_job_id`. `simulations`: mặc định **10.000**, cho phép 100–**50.000**; dưới 10.000 vẫn chạy
nhưng kết quả có `gate.gate_eligible = false` và `gate.passed = false` (không dùng làm gate). `extra_cost_daily_pct` (tuỳ chọn, 0–5): phí bổ sung
%/ngày hoạt động cho `cost_x2`; bỏ trống = hằng số bảo thủ 0,07%/ngày ((taker 0,05% + trượt giá 0,02%) × 2 chiều × vòng quay giả định 0,5×/ngày). Trả về:
```json
{"summary": {"median_ret_pct": 33.0, "p05_ret_pct": -11.3, "mdd_p50_pct": 16.1, "mdd_p95_pct": 28.4, "p_mdd_ge_ruin_pct": 3.6,
              "simulations": 10000, "block_days": 5, "horizon_days": 365, "seed": 7},
 "fan": {"days": [0, 5, ...], "p5": [...], "p25": [...], "p50": [...], "p75": [...], "p95": [...]},
 "mdd_hist": {"bins": [{"lo": 0, "hi": 2, "count": 10}]},
 "ret_hist": {"bins": [...]},
 "stress": [{"name": "worst_days_first", "label_vi": "Ngày lỗ tệ nhất đến trước", "mdd_pct": 34.07, "terminal_ret_pct": 2.39,
             "worst_day_pct": -2.75, "days_underwater": 309, "ruin": false, "days": 310, "passed": true,
             "path": {"days": [0, 5, ...], "ret_pct": [0.0, -1.2, ...]}}, ...],
 "worst_path": {"days": [0, 5, ...], "ret_pct": [...]},
 "gate": {"passed": true, "gate_eligible": true, "min_simulations": 10000, "ruin_max_pct": 5.0, "stress_max_mdd_pct": 50.0,
          "checks": {"simulations": {"label": "...", "required": ">= 10000", "actual": 10000, "passed": true},
                     "ruin": {"required": "<= 5.0%", "actual": 3.6, "passed": true},
                     "stress_mdd": {"required": "< 50%", "actual": 35.18, "passed": true, "detail": "worst_bootstrap"},
                     "stress_ruin": {"required": "không có", "actual": 0, "passed": true}}},
 "params": {...}}
```
`summary` phải trùng số với `run_monte_carlo_daily` khi cùng seed và số mô phỏng (và với bản bootstrap trước khi nâng cấp). Giới hạn: simulations 100–50000,
horizon_days ≤ 730 (vượt giới hạn hoặc `wfa_job_id` không hợp lệ: 422/4xx).

**`stress` (6 dòng, theo thứ tự)** — năm kịch bản TẤT ĐỊNH dựng từ chính chuỗi lợi suất ngày (× `scale`) và đường bootstrap tệ nhất; độ dài = số ngày lịch sử
(cộng phần chèn thêm), không cắt theo `horizon_days`:
`worst_days_first` (chuỗi xếp tăng dần: mọi ngày lỗ trước, tệ nhất trước), `reversed_order` (đảo ngược lịch sử), `crash_day` (ngày sập = 2 × ngày xấu nhất, chặn −95%,
đặt ĐẦU chuỗi), `cost_x2` (mọi ngày lợi suất ≠ 0 trừ thêm phí khứ hồi; `note_vi` nói rõ mức phí), `longest_losing_streak_x2` (chuỗi ngày lỗ liên tiếp dài nhất lặp 2 lần ở đầu, rồi lịch sử),
`worst_bootstrap` (đường có MDD lớn nhất trong các mô phỏng; `worst_path` = `stress[-1].path`). `path` = `{days, ret_pct}` lấy mẫu ≤ 75 điểm (ret_pct = % lãi từ đầu) để vẽ
chồng lên quạt; `ruin` = vốn chạm 0; `days_underwater` = số ngày vốn dưới đỉnh; `passed` = `mdd_pct < stress_max_mdd_pct` và không cháy.

**Trend thẳng đứng (P2.6, thêm 3 dòng khi nguồn biết vị thế — job WFA có `summary.shock`; gửi `daily_returns` thì không có):**
`vertical_surge` (+40% trong 3 ngày ngược vị thế SHORT lớn nhất), `vertical_crash` (−30% trong 1 ngày ngược vị thế LONG lớn nhất), `vertical_chain`
(tăng dựng rồi sập, lặp 2 lần), đặt ĐẦU chuỗi rồi lịch sử. Lỗ mỗi vị thế: có cắt lỗ theo rủi ro → min(danh nghĩa × biên độ, 2 × rủi ro kế hoạch);
không cắt lỗ (bot DCA kiểu OKX) → min(danh nghĩa × biên độ, ký quỹ). Bỏ một trong 3 dòng này (advanced `stress_scenarios`) khi nguồn có vị thế → `custom_gates`.
`stress_scenarios` nhận tối đa 9 tên; đủ 6 kịch bản cơ bản là gate chuẩn.

**`gate`** (hằng số ở đầu `backend/carlo/monte_carlo.py`): đạt khi CẢ 4 check qua — `simulations` ≥ 10.000, `ruin` P(MDD ≥ 30%) ≤ 5%, `stress_mdd` MDD mọi dòng `stress` < 50%
(`STRESS_MAX_MDD_PCT`, đổi bằng `stress_max_mdd_pct`), `stress_ruin` không dòng nào cháy vốn. Mỗi check có `required`, `actual`, `passed`.
WFA danh mục (`summary.mc`) cũng mang `stress` (không có `path`) và `gate`; `gate.checks` của WFA có thêm `mc_simulations`, `mc_stress_mdd`, `mc_stress_ruin`.

## 6. Alpha: hiệu chỉnh tham số (đã có job build)
`POST /api/studio/book/build` `{"only": ["breakout_4h_long"], "n": 24}` → job chạy `build_strategy_book` (A→D).
`result` có `windows`, `gates`, `risk`, `candidates`, `book`, `stage_a`. `stage_a[id] = [{"params", "dev1": {ret_pct, mdd_pct, trades, symbols_positive, sharpe}, "score", "passed"}]`
cho **mọi** cấu hình đã thử (`score` là `null` khi `passed=false`), để UI hiện bảng xếp hạng.
`candidates[id] = {description, side, family, dev1_tried, dev1_top: [{params, dev1, dev2_level, dev2_extreme, dev2_pass}], accepted, stability: "3/3"}`. UI cho phép chọn một dòng rồi "Gửi sang Backtest",
tức điền `strategies[{id, params}]` vào form backtest.

**Build không ghi đè sổ đang xuất bản.** Mọi job `book_build` chạy với `--out <job_dir>/alphas` (do `batch_jobs.launch` tự thêm; client không đặt được `--out`),
nên sổ vừa dựng nằm ở `<data>/_cache/api_jobs/<job_id>/alphas/book.json` (+ `testnet/book.json` CHỈ khi holdout đạt); `nora/data/alphas/` không đổi.

`POST /api/studio/book/publish` `{"job_id": "..."}` → chép `book.json` của job sang `nora/data/alphas/` (thay sổ hiện hành); `testnet/book.json` chỉ được chép khi job có
(holdout đạt), nếu không thì `nora/data/alphas/testnet/book.json` cũ bị xoá. Trả `{"published": true, "job_id", "status", "holdout_pass", "generated_at", "strategies": [id], "written": [path], "testnet_removed": bool}`.
Lỗi: 404 không có job; 422 `job_id` sai định dạng / không phải `book_build`; 409 job chưa xong hoặc không có `alphas/book.json` trong thư mục job (không dựng ra sổ, hoặc job cũ chạy trước thay đổi này).
Thư mục đích mặc định `nora/data/alphas`; biến môi trường `NORA_ALPHAS_DIR` ghi đè (dùng cho test). UI: nút "Xuất bản sổ này" trên job build đã xong có sổ, có hộp xác nhận.

## 7. Chế độ chạy (Cơ bản / Nâng cao)
Backtest, WFA và Monte Carlo nhận `mode: "basic" | "advanced"` (mặc định `basic`). **Cơ bản** = bộ tham số tốt nhất khoá sẵn; **Nâng cao** = mọi tham số chiến lược chỉnh được
(chu kỳ chỉ báo, khung thời gian của từng điều kiện, thoát lệnh, rủi ro). Client cũ không gửi `mode` sẽ chạy ở chế độ Cơ bản: tham số `params` gửi lên bị **bỏ qua**.

### 7.1 Lược đồ tham số + preset: `GET /api/studio/strategies`
→ mảng 7 chiến lược lõi (cùng thứ tự `catalog`):
```json
[{"id": "trend_long", "family": "Theo xu hướng", "side": "LONG", "description": "...",
  "frames_allowed": ["1m", "5m", "15m", "1h", "4h", "24h"],
  "params_schema": {
    "sig.trend_tf": {"group": "signal", "type": "choice", "choices": ["15m", "1h", "4h", "24h"], "default": "1h", "label_vi": "Khung xu hướng", "unit": "", "help_vi": "..."},
    "sig.ema_fast": {"group": "signal", "type": "int", "min": 5, "max": 100, "step": 1, "default": 50, "label_vi": "EMA nhanh", "unit": "nến", "help_vi": "..."},
    "sig.adx_min":  {"group": "signal", "type": "float", "min": 10.0, "max": 40.0, "step": 1.0, "default": 20.0, "...": "..."},
    "stop_loss_rate": {"group": "exit", "type": "float", "min": 0.5, "max": 10.0, "step": 0.1, "default": 2.5, "unit": "× ATR", "...": "..."},
    "risk_per_trade_pct": {"group": "risk", "type": "float", "min": 0.05, "max": 5.0, "default": 0.5, "unit": "% vốn", "...": "..."}},
  "preset": {"params": {"sig.adx_min": 25, "...": "ĐẦY ĐỦ mọi khoá của params_schema"}, "source": "build 20261001_115808 stage A top-1 dev1",
             "source_kind": "book|stage_a|default", "evidence": {"stage": "dev1", "dev1": {"ret_pct": 28.22, "mdd_pct": 27.57, "sharpe": 0.92, "trades": 783, "symbols_positive": 8},
                                                                 "accepted": false, "dev2_pass": false, "dev2_extreme": {"ret_pct": -13.97}}}}]
```
- `params_schema` là dict **có thứ tự** (tín hiệu → thoát lệnh → rủi ro). Khoá nhóm `signal` có tiền tố `sig.` (cùng quy ước `space`, `book.json`, cấu hình WFA); nhóm `exit`/`risk` là khoá vị thế.
  `type`: `int` | `float` (kèm `min`, `max`, `step`) | `choice` (kèm `choices`, giá trị là chuỗi như `"4h"`). `unit`: `nến`, `phút`, `× ATR`, `% vốn`, `x`. `help_vi` là chú thích tiếng Việt.
  Nhóm `signal` gồm chu kỳ (`sig.ema_fast`, `sig.ema_slow`, `sig.adx_n`, `sig.dch_n`, `sig.rsi_n`, `sig.bb_n`, `sig.er_n`, `sig.roc_n`, `sig.ema_n`...), hệ số (`sig.bb_k`), ngưỡng (`sig.adx_min`,
  `sig.roc_min`, `sig.rsi_lo|hi`, `sig.er_max`) và khung thời gian (`sig.trend_tf`, `sig.entry_tf`, `sig.signal_tf`, `sig.roc_tf`, `sig.regime_tf`). Nhóm `exit`: `stop_loss_rate`, `take_profit_rate`,
  `trailing_stop`, `trailing_activation_pct` (cả bốn theo × ATR), `timeout`, `cooldown` (phút), `atr_frame`, `atr_period`. Nhóm `risk`: `risk_per_trade_pct`, `max_notional_pct`, `leverage`.
- Mặc định (`default`) tái lập đúng chiến lược cũ: giá trị literal cũ của cây (EMA 50/200, ADX 14, Donchian 20, khung 1h/15m...) và mức giữa của không gian tối ưu cho tham số thoát lệnh.
- `preset` lấy từ `data/alphas/presets.json` (job `presets_build`: `POST /api/studio/strategies/presets`): ưu tiên sổ `book.json` → lần `build_strategy_book` mới nhất có cấu hình qua cổng dev1 (stage A top-1 theo điểm) →
  mặc định (`source = "mặc định — chưa tối ưu"`, `evidence = null`). `evidence.accepted/dev2_pass` cho biết cấu hình đó đã qua kiểm chứng dev2 hay chưa — UI cần hiện rõ khi là `false`.
- `POST /api/studio/strategies/validate` `{"id": "trend_long", "params": {...}}` → `{"ok": bool, "errors": [{"field", "message"}], "resolved": {tham số đầy đủ}|null}` (không chạy job; khoá thiếu lấy từ preset).

### 7.2 Ngữ nghĩa `mode`
| | `basic` | `advanced` |
|---|---|---|
| Backtest `strategies[]` | chỉ cần `id` (tối đa 7, không lặp); **`params`, `risk_per_trade_pct`, `stop_fill` bị bỏ qua** — dùng preset, rủi ro = mức nhỏ nhất của các preset, `stop_fill=level` | `params` kiểm theo `params_schema`; khoá thiếu lấy từ **preset**; `risk_per_trade_pct`/`stop_fill` theo request |
| WFA | fold mặc định 120/30, gate chuẩn; nguồn = `candidates` hoặc `strategies[].id` (mỗi chiến lược 1 cấu hình = preset); `report_dir`, `train_days`, `test_days`, `n`, `configs` bị bỏ qua/từ chối | `train_days`, `test_days`, `step_days`, `sims`, `mc_seed`, `candidates`+`n`, `report_dir`, `strategies[].configs[]` (kiểm theo schema) |
| Monte Carlo | 10.000 kịch bản, block 5, horizon 365, ngưỡng cháy 30%, seed 7, đủ 6 kịch bản cực xấu, gate chuẩn; mọi tham số MC của client bị bỏ qua (chỉ lấy nguồn `wfa_job_id`/`daily_returns`) | `simulations` (100–50.000), `block_days`, `horizon_days`, `seed`, `scale`, `ruin_threshold_pct`, `stress_max_mdd_pct`, `extra_cost_daily_pct`, `stress_scenarios` (tập con của `worst_days_first, reversed_order, crash_day, cost_x2, longest_losing_streak_x2, worst_bootstrap`) |
| Cửa sổ ngày, `symbols` | cho phép | cho phép |

Ràng buộc nâng cao: mọi chiến lược trong **một lần backtest** phải cùng `risk_per_trade_pct` (danh mục dùng một mức rủi ro; nếu request có `risk_per_trade_pct` thì mức đó thắng, không thì các `params.risk_per_trade_pct` phải bằng nhau);
`sig.ema_fast < sig.ema_slow`. WFA nâng cao hiện **chỉ nhận khoá thuộc không gian tối ưu** (`space`: ngưỡng, thoát lệnh) trong `strategies[].configs`; chu kỳ/khung thời gian đổi qua backtest.
`embargo_days > 0` và các cờ `step_days`/`sims`/`mc_seed` chưa nằm trong danh sách trắng job `book_wfa` trả 422 "Máy chủ chưa hỗ trợ ..." (xem báo cáo giao việc).

### 7.3 `custom_gates` và không xuất bản được
Ở chế độ nâng cao, nếu request **đổi ngưỡng gate** (`ruin_threshold_pct` ≠ 30, `stress_max_mdd_pct` ≠ 50, thiếu kịch bản cực xấu) hoặc dùng **< 10.000 kịch bản** (MC `simulations`, WFA `sims`) thì kết quả mang
`custom_gates: true`, `promotable: false` (và `gate.gate_eligible = false` với MC). Chỉ đổi tham số dữ liệu (block, horizon, seed, scale) hoặc tham số chiến lược thì vẫn là gate chuẩn.
`POST /api/studio/book/publish` từ chối job có `custom_gates` bằng **409** ("... KHÔNG được xuất bản/promote ..."). MC có nguồn `wfa_job_id` của job `custom_gates` cũng bị đánh dấu như vậy.
MC (đồng bộ): `params` có thêm `mode`, `custom_gates`, `promotable`, `ignored_client_params`; `gate.custom_gates`.

### 7.4 Bản ghi job
`POST /book/backtest|wfa` vẫn trả `{"job_id"}`. `GET /book/jobs/{id}` và các hàng của `GET /book/jobs` có thêm:
`mode`, `custom_gates`, `promotable`, `ignored_client_params` (basic: client có gửi tham số bị bỏ qua) và **`resolved`** — tham số ĐẦY ĐỦ đã giải quyết để tái lập:
```json
{"mode": "advanced", "custom_gates": false, "promotable": true, "ignored_client_params": false,
 "resolved": {"source": "client+presets", "symbols": ["BTC", "SOL"], "start": "2025-03-01", "end": "2025-06-30", "risk_per_trade_pct": 0.5, "stop_fill": "level",
              "strategies": [{"id": "trend_long", "params": {"sig.trend_tf": "4h", "sig.ema_fast": 20, "...": "mọi khoá của params_schema"}, "preset_source": null}]}}
```
WFA: `resolved.strategies[] = {id, configs: [tham số đầy đủ]}`, `train_days`, `test_days`, `step_days`, `sims`, `mc_seed`. Khi job `done`, `result` được phản chiếu `mode`, `custom_gates`, `promotable`.
Job nhận tham số tối thiểu (khoá của `space` + khoá khác mặc định) qua `--strategies` (JSON, khung thời gian là chuỗi) hoặc `strategies.json` của thư mục job.

### 7.5 Lỗi 422 theo trường
`detail` là danh sách kiểu FastAPI, mỗi phần tử có thêm `field` (đường dẫn trường) và `msg` tiếng Việt:
```json
{"detail": [{"loc": ["body", "strategies[0].params.sig.ema_fast"], "field": "strategies[0].params.sig.ema_fast", "type": "value_error",
             "msg": "trend_long: EMA nhanh (sig.ema_fast) phải nằm trong khoảng 5 đến 100 nến, nhận 150"}]}
```
Các lỗi: khoá lạ (kèm gợi ý `sig.`), sai kiểu / không nguyên / ngoài `[min, max]`, khung thời gian không thuộc `choices`, `sig.ema_fast >= sig.ema_slow`, cột kernel không hợp lệ sau khi thay tham số
(chu kỳ phải nguyên 2..500, `k` trong (0, 10]), ngân sách DCA vượt trần vốn, `risk_per_trade_pct` khác nhau giữa các chiến lược, id chiến lược lạ/lặp/quá 7, `stress_scenarios` không hợp lệ.

### 7.6 Giao diện `/backtest` (P4.1)
Công tắc "Cơ bản | Nâng cao" ở đầu cả ba bước; mọi request gửi `mode`. Cơ bản: chọn chiến lược, hiện preset chỉ đọc + nguồn/bằng chứng (nói rõ "mặc định — chưa tối ưu"; cảnh báo khi preset trượt dev2),
rủi ro/khớp cắt lỗ/fold 120-30/MC 10.000 hiện dạng khoá. Nâng cao: mọi khoá của `params_schema` có ô nhập đúng kiểu (số có min/max, chọn khung thời gian), kiểm phía client + `POST /strategies/validate`;
422 theo `field` được gắn vào đúng ô. WFA nâng cao: chỉ khoá thuộc `space` sửa được; `step_days`/`sims`/`mc_seed` và khoá ngoài `space` bị khoá ghi "chưa hỗ trợ ở WFA (đang làm)" cho tới khi
`WFA_SCHEMA_KEYS_SUPPORTED` (frontend `lib/modes.js`) bật (API chưa công bố cờ này). Kết quả `custom_gates`/`promotable:false` hiện huy hiệu "Cấu hình tuỳ chỉnh — không xuất bản được", nút Xuất bản bị khoá kèm lý do.
Nhãn tham số chỉ lấy từ `frontend/src/v2/lib/params.js` (không dùng `label_vi` của API). Job hiện `mode` + `resolved` ở JobPanel và Lịch sử chạy.

## 8. Regime thị trường (P4.3) và kiểm lại alpha trong kho (P3.3)

`GET /api/studio/market/regime?days=30&symbols=BTC,SOL` (days 1–365, mặc định cả vũ trụ perp):
```json
{"days": 30, "frame": "15m", "names": ["UNKNOWN", "RANGE", ...], "labels_vi": {"RANGE": "Đi ngang", ...},
 "symbols": [{"symbol": "BTC@perp", "as_of": 1790...,
              "current": {"state": "RANGE", "label": "Đi ngang", "since": 1790...},
              "segments": [[start_ms, end_ms, "RANGE"], ...],
              "share_pct": {"RANGE": 74.2, "TREND_UP": 17.9},
              "strategies_on": ["reversion_long", "reversion_short"], "strategies_off": [...]}]}
```
Nhãn trên nến 15m đã đóng qua `classifier.series` (cùng đường với backtest). `strategies_on` theo bảng regime tĩnh của sổ (`book.REGIME_MAP`).

`POST /api/studio/alphas/{alpha_id}/revalidate?apply=false` → `{job_id}` (job `alpha_revalidate`, `backend/optimize/revalidate.py`): chạy lại cây tín hiệu +
tham số đã lưu của alpha bằng engine hiện hành: WFA dev2 (cổng S3) → hệ số s qua MC (S5, có trend thẳng đứng) → holdout ở s (S6). Kết quả:
`{status: "validated"|"retired", final_scale, reject_code, reason, wfa, sizing, holdout, shock, windows}`. `apply=true`: ghi `status` + `revalidation`
vào `registry.json`; `retired` → `testnet/<id>.json` chuyển sang `testnet/_retired/`. Feed live bỏ qua alpha `retired`.

## 9. Bot theo sổ (E9, 04/10/2026) — sàn triển khai: OKX

`POST /api/studio/live/bot` `{mode: "paper" | "demo" | "live", venue: "okx" | "binance", once: false, capital: 10000, confirm_live: false}` → `{job_id}`
(job `live_bot`, chạy lâu, không giữ khoá hàng đợi; 409 nếu bot cùng sàn + chế độ đang chạy; live cần `confirm_live: true`). Dừng:
`POST /api/studio/book/jobs/{job_id}/cancel`. `GET /api/studio/live/bot?venue=okx&mode=paper&events=50` → `{venue, mode, running, state, events}`.
- paper: nến thật của sàn (REST công khai), khớp bằng PaperBook (= engine từng nến).
- demo: OKX Demo Trading (khoá demo, header x-simulated-trading) — vốn ảo; live: OKX tài khoản thật — CÙNG mã, khác khoá (NORA_OKX_DEMO=0).
- Khoá OKX: `~/.config/nora/okx.env` (quyền 600): NORA_OKX_KEY, NORA_OKX_SECRET, NORA_OKX_PASSPHRASE, NORA_OKX_DEMO (1 = demo, mặc định).
- Tài khoản OKX phải ở `net_mode` (bot kiểm). Binance (`venue: binance`) chỉ để tham khảo: paper / testnet, không live.
Trạng thái: `data/_cache/live/<venue>_<mode>/` (state.json, events.jsonl, paper.pkl).
