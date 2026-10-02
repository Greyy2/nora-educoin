# Bộ số đo (metrics): hiện có, cách tính, chỗ thiếu

Rà ngày 02/10/2026 trên code `backend/` (sau tái cấu trúc). Quy ước chung hiện tại: năm = 365 ngày, lãi suất phi rủi ro = 0,
lợi suất ngày = vốn MTM cuối ngày UTC (`core/metrics/returns.daily_returns_from_curve`).

## 1. Đang có

### 1.1 Lợi nhuận / PnL

| Số đo | Cách tính | Ở đâu | Dùng cho |
|---|---|---|---|
| `ret_pct` (lãi kỳ) | (vốn cuối / vốn đầu − 1) × 100, vốn cuối = MTM | `metrics/portfolio.portfolio_metrics` | backtest, sổ, phễu S1/S6 |
| `ret_pct` (chuỗi nối) | Π(1 + r_ngày) − 1 | `metrics/portfolio.series_metrics` | phễu S3/S4/S5 (OOS nối) |
| `compounded_oos_ret_pct` | lãi kép OOS các fold, cả `level` và `extreme` | `wfa/walk_forward` | WFA |
| `avg_is_ret_pct` | trung bình lãi IS các fold | `wfa/walk_forward` | gate WFA |
| `pnl_usd` từng lệnh | `real_pnl` (sau phí vào/ra, funding) | `execute/tracker` | bảng lệnh |
| `pnl_pct` từng lệnh | PnL / vốn lúc mở lệnh × 100 | `execute/tracker` | MC theo lệnh |
| `fees_usd`, `funding_usd` | tổng phí, tổng funding | `metrics/portfolio` | báo cáo |
| `by_symbol`, `by_strategy` | PnL đã chốt theo tài sản / chiến lược | `backtest/portfolio` | báo cáo, gate `symbols_positive` |
| PnL hôm nay / tháng / năm, lợi nhuận theo tháng | chênh NAV | `analytics/dashboard` | trang Danh mục |
| CAGR | (NAV cuối / NAV gốc)^(365/n) − 1 | `analytics/dashboard` | **chỉ** trang Danh mục |
| Lợi nhuận so với BTC (`excess_pct`) | lãi kỳ − lãi BTC@perp cùng kỳ | `analytics/dashboard` | trang Danh mục |

### 1.2 Sụt giảm (drawdown)

| Số đo | Cách tính | Ở đâu |
|---|---|---|
| `mdd_pct` **trong nến** (khắt nhất) | đỉnh vốn MTM vs min(vốn, `equity_worst` = giá xấu nhất của nến) | `metrics/portfolio.portfolio_metrics` (backtest, sổ, phễu S1/S6) |
| `mdd_pct` **theo ngày** | trên chuỗi r_ngày nối (giá đóng ngày) | `metrics/returns.equity_mdd_pct` (phễu S3–S5), `dashboard` |
| `worst_fold_mdd_pct` | MDD lớn nhất trong các fold OOS | `wfa/walk_forward` |
| `dd_now_pct`, đường underwater | sụt giảm hiện tại so với đỉnh | `dashboard` |
| MDD Monte Carlo p50/p95, `P(MDD ≥ 30%)` | bootstrap khối 5 ngày, 10.000 đường × 365 ngày | `carlo/monte_carlo` |
| MDD từng kịch bản cực xấu | 6 kịch bản tất định + đường bootstrap tệ nhất | `carlo/monte_carlo.stress_scenarios` |
| `mae_pct` từng lệnh | lỗ treo tối đa trong lệnh (% vốn lúc mở) | `execute/tracker` |

### 1.3 Rủi ro điều chỉnh lợi nhuận

| Số đo | Cách tính | Ở đâu |
|---|---|---|
| Sharpe | mean(r_ngày) / std(r_ngày, ddof=1) × √365 | `metrics/returns.sharpe`, `portfolio_metrics`, `series_metrics` |
| Sharpe (bản cũ) | trên **mẫu vốn mỗi giờ** nhưng nhân √365 — **sai đơn vị** (xem 3.1) | `metrics/trades.MetricsCalculator` |
| Sortino | mean / √mean(min(r,0)²) × √365; 2 bản: trả `None` (Danh mục) / `0.0` (phễu) | `metrics/returns` |
| Calmar | CAGR / \|MDD ngày\| | **chỉ** `dashboard` |
| Sharpe cuốn chiếu 63 ngày | | `dashboard` |
| VaR 95% / CVaR 95% 1 ngày | lịch sử, trên r_ngày của kỳ | **chỉ** `dashboard` |
| Biến động năm | std(r_ngày) × √365 | `dashboard` |
| `sr_daily`, `skew`, `kurt` (thô) | thống kê chuỗi ngày | `metrics/returns.daily_stats` (cho DSR) |

### 1.4 Theo lệnh

| Số đo | Cách tính | Ở đâu |
|---|---|---|
| `win_rate` / `win_pct` | lệnh PnL > 0 / tổng lệnh | `metrics/trades.trade_stats`, `portfolio_metrics` |
| `profit_factor` | Σ lãi / Σ lỗ, chặn 99 khi không lỗ | `metrics/trades.trade_stats`, `dashboard` |
| `trades` | số lệnh đã đóng | nhiều nơi |
| Tỉ lệ ngày lãi | ngày có giao dịch và lãi / ngày có giao dịch | `dashboard` |
| `layers` từng lệnh | số tầng DCA đã khớp | `execute/tracker` |

### 1.5 Kiểm duyệt / chống ăn may

| Số đo | Ở đâu |
|---|---|
| DSR (Deflated Sharpe), SR0 kỳ vọng max | `optimize/funnel/antiluck` |
| PBO (CSCV, 16 khối) | `optimize/funnel/antiluck` |
| Lân cận tham số ±1 bước | `optimize/funnel/antiluck` + S2 |
| `positive_ratio_pct` (fold OOS có lãi), `param_stability` | `wfa/walk_forward` |
| `symbols_positive`, `halted_at` (kill switch), `rejected_for_risk/capital`, `risk_blocked_attempts`, `dca_rejected` | engine + `portfolio_metrics` |
| Hệ số khối lượng sống sót `s` (S5) | `optimize/funnel/sizing` |

## 2. Theo loại chiến lược: số đo nào quyết định, đã có chưa

| Loại | Điều dễ đánh lừa | Số đo cần | Có? |
|---|---|---|---|
| **Trend / breakout** (win thấp, lãi lớn ít lần) | win rate thấp trông xấu dù có edge; lãi dồn vào vài lệnh | payoff (TB lãi / TB lỗ), expectancy/lệnh, tỉ trọng top-5 lệnh trong tổng lãi, thời gian giữ lệnh, % thời gian có vị thế | **chưa** |
| **Mean-reversion / scalp** (win cao, lãi mỏng) | phí ăn hết edge; đuôi lỗ âm | expectancy sau phí, fee drag (% lãi gộp bị phí ăn), lệnh tệ nhất, chuỗi thua dài nhất, skew âm, CVaR | phí có; còn lại **chưa** (CVaR chỉ ở Danh mục) |
| **DCA / grid kiểu bot OKX** (win 90%+, cháy khi trend thẳng) | win rate + PnL đã chốt che lỗ treo | MAE (có), số tầng max/TB, **vốn sử dụng đỉnh**, khoảng cách tối thiểu tới giá thanh lý, số lần thanh lý, thời gian nằm lỗ mỗi lệnh, recovery time, P(cháy) MC (có) | MAE, P(cháy) có; còn lại **chưa** |
| **Short / perp** | funding âm kéo dài | funding_usd (có), funding / PnL, lãi tách long/short | tách long/short **chưa** |
| **Danh mục nhiều chiến lược** | các chiến lược cùng chết một lúc | tương quan lợi suất giữa chiến lược, exposure gộp/ròng TB và max, tập trung theo tài sản | exposure chỉ điểm cuối ở Danh mục; tương quan **chưa** |
| **So sánh alpha khác độ dài cửa sổ** | `ret_pct` cửa sổ dài luôn to hơn | lợi nhuận quy năm (CAGR) trong mọi tầng phễu | **chỉ** Danh mục |

## 3. Lỗi / không nhất quán phải sửa trước

1. **Sharpe của `MetricsCalculator` sai đơn vị:** lấy chênh lệch giữa các mẫu vốn (mỗi 60 phút + mỗi lần đóng lệnh, khoảng cách không đều) rồi nhân √365 như số liệu ngày → Sharpe bị lệch nhiều lần. Đang dùng ở `test/scripts/check_signals_strategies.py` và 1 test. Sửa: tính trên lợi suất ngày (`daily_returns_from_curve`).
2. **Định nghĩa thắng/thua khác nhau:** `MetricsCalculator` đếm lệnh hoà (PnL = 0) là THUA; `trade_stats` / `portfolio_metrics` không đếm hoà vào thắng lẫn thua. Thống nhất: thắng > 0, thua < 0, hoà riêng.
3. **Ba kiểu MDD cùng tên `mdd_pct`:** trong nến (S1/S6, sổ), theo ngày (S3–S5, Danh mục), MC. Cùng một alpha có thể hiện MDD khác nhau giữa các trang. Sửa: đặt tên rõ `mdd_intrabar_pct` / `mdd_daily_pct` và báo cả hai ở mọi tầng.
4. **Hai bản Sortino** (None vs 0.0) và **Sharpe tính lại 3 chỗ** (`returns.sharpe`, `portfolio_metrics`, `series_metrics`) với cùng công thức: gom về một hàm.
5. **CAGR, Calmar, VaR/CVaR, biến động chỉ có ở Danh mục**, phễu và WFA không có → không so được alpha theo lợi nhuận quy năm/đuôi lỗ.
6. **Profit factor chặn 99** khi không có lệnh lỗ: đúng cho JSON nhưng phải hiện kèm số lệnh lỗ = 0 để không đọc nhầm.

## 4. Đề xuất bộ số đo chuẩn (một hàm, mọi tầng dùng chung)

`core/metrics/summary.py: summarize(result, start_ts) -> dict` thay `portfolio_metrics`/`series_metrics`/`MetricsCalculator`, trả:

- **Lợi nhuận:** `ret_pct`, `cagr_pct`, `pnl_usd`, `fees_usd`, `funding_usd`, `fee_drag_pct`
- **Sụt giảm:** `mdd_intrabar_pct`, `mdd_daily_pct`, `max_dd_duration_days`, `recovery_days`, `ulcer_index`
- **Rủi ro điều chỉnh:** `sharpe`, `sortino`, `calmar`, `vol_ann_pct`, `var95_pct`, `cvar95_pct`, `skew`, `kurt`
- **Theo lệnh:** `trades`, `win_rate`, `loss_rate`, `breakeven`, `profit_factor`, `payoff`, `expectancy_usd`, `expectancy_pct`, `avg_win`, `avg_loss`, `best_trade`, `worst_trade`, `max_consec_losses`, `top5_share_pct`, `avg_hold_h`, `time_in_market_pct`, `long_short` (lãi/lệnh/win tách theo chiều)
- **DCA / đòn bẩy:** `mae_avg_pct`, `mae_worst_pct`, `layers_avg`, `layers_max`, `peak_capital_use_pct`, `min_liq_distance_pct`, `liquidations`
- **Danh mục:** `by_symbol`, `by_strategy`, `symbols_positive`, `corr_strategies`, `exposure_gross_avg/max`, `exposure_net_avg/max`

Mọi tầng (backtest, sổ, phễu S1–S6, WFA, Danh mục) gọi cùng `summarize`; golden backtest không đổi (chỉ thêm số đo, không đổi engine).
