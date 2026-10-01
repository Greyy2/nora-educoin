# Hợp đồng API cho giao diện Nora (v2)

Một vòng trên UI: **Alpha** (hiệu chỉnh tham số từ chiến lược có sẵn) → **Backtest** → **WFA** → **Monte Carlo** →
theo dõi trên **Danh mục**. Danh mục có ba nguồn: **Live | Testnet | Backtest**. Chưa có tài khoản live/testnet, nên Live và Testnet đang
dùng feed **giả lập** (lệnh mô phỏng bằng engine thật, xem §3); khi nối tài khoản thật chỉ cần cài `LiveFeed`/`TestnetFeed` (backend/core/analytics/feeds.py),
payload và UI không đổi.

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
  "windows": {"start": "2023-10-20", "dev1_end": "2024-12-24", "dev2_end": "2026-02-27", "end": "2026-09-30"}
}
```
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

Chỉ `POST` trả khoá `job_id`. Các hàng job (GET) dùng khoá **`id`** (kèm `state`, bằng `status`); UI chuẩn hoá `job_id = job_id || id`.
`GET /api/studio/book/jobs/{id}` → `{"id","kind","args","pid","status","state","waiting_in_queue","created","started","finished","exit_code","log_tail":[...],"result":{...}|null}`
(`created/started/finished` là giây Unix; `result` chỉ có khi `done`).
`GET /api/studio/book/jobs?kind=book_backtest|book_wfa|book_build&limit=20` → `{"jobs":[{id, kind, status, created, args, label, ...}]}` (đã lọc theo `kind`).
`result` của backtest: `{ret_pct, mdd_pct, sharpe, trades, daily_nav, trade_list, equity_curve, by_symbol, by_strategy, halted_at, ...}`.

## 3. Payload Danh mục (mới)
`GET /api/studio/portfolio/dashboard?source=backtest&job_id=<id>&period=1M|3M|YTD|1Y|ALL`
`source=live|testnet|backtest` (mặc định `backtest`; UI mặc định Live). `source=paper` (hoặc giá trị lạ) → 422.
- `source=live|testnet`: nếu feed thật chưa nối (hiện luôn vậy) thì dùng **feed giả lập** `data/_cache/mock_feeds/{live,testnet}.json`, payload thêm
  `"mock": true, "mock_note": "Dữ liệu giả lập — chưa kết nối tài khoản <Live|Testnet>"` và `source.mock = true`; `source.label` = mô tả feed
  (`source_desc`), `source.job_id = null`. Chưa có file giả lập → `{"available": false, "reason": "... chạy `python -m backend.cli.make_mock_feeds` ..."}` (HTTP 200).
  Payload backtest không có `mock`/`mock_note`.
- Feed giả lập do `python -m backend.cli.make_mock_feeds` (qua `run_limited.sh`) sinh, tất định, trên dữ liệu mới nhất, vị thế cuối dữ liệu **không bị đóng ép**:
  `testnet` = sổ đã chốt (`book.json`) trên 8 perp, 60 ngày, vốn 10.000 USDT; `live` = alpha `trend_long_perp__SOL` (chỉ SOL, `order_size_pct` × hệ số vốn
  "extreme" tối đa trong `portfolio_*__SOL.json`) + sổ, 120 ngày, vốn 25.000 USDT. File: `{"mock": true, "generated_at", "source_desc", "kind", "positions", ...kết quả dạng book_backtest}`.
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
(`mock`/`mock_note` chỉ có ở feed giả lập.)
- Không có `job_id` (với `source=backtest`): dùng backtest xong gần nhất; chưa có backtest nào thì `available:false` kèm `reason`.
- `bench`: mua giữ `BTC@perp`, quy về cùng NAV đầu kỳ. `drawdown_pct` ≤ 0, tính trên NAV theo ngày (nên `mdd_pct` KPI khác MDD intrabar của `result.mdd_pct`). Mọi chuỗi trong `series` cùng độ dài với `dates`.
- `period` cắt chuỗi ngày theo cuối kỳ của dữ liệu; KPI kỳ tính trên phần đã cắt, còn `mdd`/Sharpe theo kỳ.
- `risk.win_days_pct` = tỉ lệ ngày lãi **trong các ngày có P&L khác 0** (`risk.active_days` = số ngày đó, `null` nếu 0): ngày đứng ngoài thị trường không tính là ngày lỗ. UI ghi nhãn "Tỉ lệ ngày lãi (ngày có giao dịch)".
- Exposure/vị thế mở: tại ngày cuối của kỳ, tính từ `trade_list` (danh nghĩa / NAV) cộng `positions` (feed live/testnet/giả lập).
- `positions[]` = vị thế **đang mở** tại điểm cuối dữ liệu (không đổi theo `period`): `qty`, `entry_price` (giá TB), `mark_price` (giá đóng cửa cuối), `notional` = qty × mark,
  `unrealized_pnl` (sau phí vào lệnh; funding đã nằm trong NAV), `opened` (ms UTC), `margin_usd`. Sắp theo `notional` giảm dần. Backtest đã đóng mọi vị thế cuối kỳ nên `positions = []`.
  Vị thế đang mở được tính vào NAV (MTM) nhưng chưa vào `strategies[].pnl` (chỉ lãi/lỗ đã chốt). UI ẩn bảng "Vị thế đang mở" khi rỗng.
- `strategies[]`: số liệu **đã thực hiện** (realised: lãi/lỗ các lệnh đã đóng, Sharpe/MDD theo chuỗi realised của chiến lược), nên tổng không khớp từng đồng với NAV mark-to-market.
- `events`: dựa trên MDD intrabar xấu nhất (không phải NAV ngày): kill switch (`halted_at`), drawdown vượt 50%/80% hạn mức 30%, số lần bị từ chối vì rủi ro.

## 4. WFA (đã có job, bổ sung cấu hình cố định)
`POST /api/studio/book/wfa`, một trong ba dạng:
- `{"report_dir": "..."}`: các chiến lược đã đạt của một lần build;
- `{"candidates": ["id"], "n": 3}`: lấy mẫu `n` cấu hình mỗi chiến lược;
- **mới:** `{"strategies": [{"id": "...", "configs": [{...}, {...}]}]}`: cấu hình do người dùng chọn. Một cấu hình mỗi chiến lược nghĩa là tham số cố định (WFA chỉ kiểm OOS cuộn).
Cùng các trường tuỳ chọn `start`, `end`, `train_days`, `test_days`, `symbols`, `risk_per_trade_pct`.
Kết quả (`result` của job) là `report.json` của `validate_book.py`: `folds[]`, `summary`, `gate`, và các bí danh theo hợp đồng
`aggregate` (= `summary`) và `mc` (= `summary.mc`) — cùng một đối tượng, UI đọc `aggregate`/`mc`.
`aggregate.oos_daily` và `aggregate.oos_daily_dates` đều là `{level: [...], extreme: [...]}`, song song theo chỉ số
(ngày `YYYY-MM-DD`), để UI vẽ đường vốn OOS. `gate = {passed, checks: {<khoá>: {label, required, actual, passed}}}`.

## 5. Monte Carlo (mới, đồng bộ, nhẹ)
`POST /api/studio/book/mc`
```json
{"wfa_job_id": "...", "basis": "extreme|level", "simulations": 4000, "block_days": 5, "horizon_days": 365,
 "ruin_threshold_pct": 30, "seed": 7, "scale": 1.0}
```
hoặc gửi trực tiếp `"daily_returns": [...]` thay cho `wfa_job_id`. Trả về:
```json
{"summary": {"median_ret_pct": 33.0, "p05_ret_pct": -11.3, "mdd_p50_pct": 16.1, "mdd_p95_pct": 28.4, "p_mdd_ge_ruin_pct": 3.6,
              "simulations": 4000, "block_days": 5, "horizon_days": 365, "seed": 7},
 "fan": {"days": [0, 5, ...], "p5": [...], "p25": [...], "p50": [...], "p75": [...], "p95": [...]},
 "mdd_hist": {"bins": [{"lo": 0, "hi": 2, "count": 10}]},
 "ret_hist": {"bins": [...]},
 "gate": {"ruin_max_pct": 5.0, "passed": true},
 "params": {...}}
```
Phải trùng số với `run_monte_carlo_daily` khi cùng seed. Giới hạn: simulations ≤ 10000, horizon_days ≤ 730 (vượt giới hạn hoặc `wfa_job_id` không hợp lệ: 422/4xx).

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
