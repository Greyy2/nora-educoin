# Hợp đồng API cho giao diện Nora (v2)

Một vòng trên UI: **Alpha** (hiệu chỉnh tham số từ chiến lược có sẵn) → **Backtest** → **WFA** → **Monte Carlo** →
theo dõi trên **Danh mục**. Hiện chưa có tài khoản live, nên Danh mục đọc kết quả backtest; nguồn Live/Paper/Testnet
dùng cùng payload khi được nối sau này.

Quy ước chung:
- Thời gian là ms UTC. Ngày dạng `YYYY-MM-DD` (UTC). Tiền tệ USDT. Phần trăm là số đã nhân 100 (`4.85` = 4,85%).
- Job nặng chạy nền qua hàng đợi `run_limited` (`backend/studio_pipeline/batch_jobs.py`). Client poll `GET /api/studio/book/jobs/{id}` mỗi 2 s.
- Trạng thái job: `queued` (đang chờ job khác) | `running` | `done` | `failed`.
- Lỗi theo FastAPI: `{detail}` với mã 4xx/5xx; 429 khi đã có quá nhiều job đang chờ.

## 1. Danh mục chiến lược, sổ, kho alpha (đã có)
`GET /api/studio/book/` →
```json
{
  "book": {"status": "HOLDOUT_FAILED|READY_FOR_TESTNET", "strategies": [{"id": "...", "params": {}}], "evidence": {}} ,
  "latest_wfa": {"path": "...", "gate_passed": false, "summary": {}},
  "catalog": [{"id": "trend_long", "family": "...", "side": "LONG", "description": "...", "space": {"stop_loss_rate": [1.5, 2.5, 3.5]}}]
}
```
Bổ sung (backend): mỗi mục catalog thêm `default_params` (giá trị giữa của mỗi khoá trong space, giống run_book_backtest);
thêm `universe` (danh sách `<SYM>@perp`) và `windows` ({start, dev1_end, dev2_end, end} dạng ngày) ở cấp gốc.

`GET /api/studio/alphas` (mới) → `{"registry": <alphas/registry.json hoặc null>, "book": <alphas/book.json hoặc null>}`.

## 2. Backtest (đã có job)
`POST /api/studio/book/backtest`
```json
{"strategies": [{"id": "breakout_4h_long", "params": {"stop_loss_rate": 2.0}}],
 "symbols": ["BTC@perp", "SOL@perp"], "start": "2025-03-01", "end": "2025-04-30",
 "risk_per_trade_pct": 0.5, "stop_fill": "level"}
```
→ `{"job_id": "..."}`. Bỏ `strategies` → dùng `alphas/book.json`.

`GET /api/studio/book/jobs/{id}` → `{"job_id","kind","status","created","started","finished","exit_code","log_tail":[...],"result":{...}|null}`.
`GET /api/studio/book/jobs?kind=book_backtest|book_wfa|book_build&limit=20` → `{"jobs":[{job_id, kind, status, created, args, label}]}` (backend: thêm lọc `kind`).

## 3. Payload Danh mục (mới)
`GET /api/studio/portfolio/dashboard?source=backtest&job_id=<id>&period=1M|3M|YTD|1Y|ALL`
`source=live|paper|testnet` → `{"available": false, "reason": "Chưa kết nối tài khoản ..."}` (HTTP 200).
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
    "cagr_pct": 20.8, "vol_annual_pct": 6.6, "win_days_pct": 58.7, "profit_factor": 1.6,
    "open_positions": 3, "strategies_running": 2
  },
  "strategies": [{"id": "breakout_4h_long", "side": "LONG", "status": "active", "weight_pct": 50,
                  "pnl": 120.4, "contribution_pct": 1.2, "sharpe": 1.4, "mdd_pct": -3.1, "pnl_30d": [...]}],
  "events": [{"time": 1745146440000, "level": "warn|crit|info", "text": "..."}]
}
```
- `bench`: mua giữ `BTC@perp`, quy về cùng NAV đầu kỳ. `drawdown_pct` ≤ 0. Mọi chuỗi trong `series` cùng độ dài với `dates`.
- `period` cắt chuỗi ngày theo cuối kỳ của dữ liệu; KPI kỳ tính trên phần đã cắt, còn `mdd`/Sharpe theo kỳ.
- Exposure/vị thế mở: tại ngày cuối của kỳ, tính từ `trade_list` (danh nghĩa / NAV).
- `events`: kill switch (`halted_at`), drawdown vượt 50%/80% hạn mức 30%, số lần bị từ chối vì rủi ro.

## 4. WFA (đã có job, bổ sung cấu hình cố định)
`POST /api/studio/book/wfa`, một trong ba dạng:
- `{"report_dir": "..."}`: các chiến lược đã đạt của một lần build;
- `{"candidates": ["id"], "n": 3}`: lấy mẫu `n` cấu hình mỗi chiến lược;
- **mới:** `{"strategies": [{"id": "...", "configs": [{...}, {...}]}]}`: cấu hình do người dùng chọn. Một cấu hình mỗi chiến lược nghĩa là tham số cố định (WFA chỉ kiểm OOS cuộn).
Cùng các trường tuỳ chọn `start`, `end`, `train_days`, `test_days`, `symbols`, `risk_per_trade_pct`.
Kết quả (`result` của job) là `report.json` của `validate_book.py`: `folds[]`, `aggregate`, `mc`, `gate`.
Backend thêm vào `aggregate`: `oos_daily_dates` song song với chuỗi lợi suất ngày (cả `level` và `extreme`),
để UI vẽ đường vốn OOS.

## 5. Monte Carlo (mới, đồng bộ, nhẹ)
`POST /api/studio/book/mc`
```json
{"wfa_job_id": "...", "basis": "extreme|level", "simulations": 4000, "block_days": 5, "horizon_days": 365,
 "ruin_threshold_pct": 30, "seed": 7, "scale": 1.0}
```
hoặc gửi trực tiếp `"daily_returns": [...]` thay cho `wfa_job_id`. Trả về:
```json
{"summary": {"median_ret_pct": 33.0, "p05_ret_pct": -11.3, "mdd_p50_pct": 16.1, "mdd_p95_pct": 28.4, "p_mdd_ge_ruin_pct": 3.6},
 "fan": {"days": [0, 5, ...], "p5": [...], "p25": [...], "p50": [...], "p75": [...], "p95": [...]},
 "mdd_hist": {"bins": [{"lo": 0, "hi": 2, "count": 10}]},
 "ret_hist": {"bins": [...]},
 "gate": {"ruin_max_pct": 5.0, "passed": true},
 "params": {...}}
```
Phải trùng số với `run_monte_carlo_daily` khi cùng seed. Giới hạn: simulations ≤ 10000, horizon_days ≤ 730.

## 6. Alpha: hiệu chỉnh tham số (đã có job build)
`POST /api/studio/book/build` `{"only": ["breakout_4h_long"], "n": 24}` → job chạy `build_strategy_book` (A→D).
Bổ sung (backend): `result` thêm `stage_a[id] = [{"params", "dev1": {ret_pct, mdd_pct, trades, symbols_positive, sharpe}, "score", "passed"}]`
cho **mọi** cấu hình đã thử, để UI hiện bảng xếp hạng. UI cho phép chọn một dòng rồi "Gửi sang Backtest",
tức điền `strategies[{id, params}]` vào form backtest.
