# INVALIDATED — Historical Alpha Disposition Dossier

> **INVALIDATED_SOURCE_ID_COLLISION — DO NOT USE.** Bare-ID source mapping could select the wrong source across COIN and EDU; this invalidates every row and all derived causes in this dossier. Historical content is retained without correction and must not be used to rank, promote, reject, or remove alpha.

*Tổng số Alpha bị REJECT: 56 alphas (chỉ số mô tả kỹ thuật, không quy kết định tính)*


## Alpha: `dca_long` (System Leg dca_long)
- **Phân loại**: `COIN System Leg` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-0.15%` | MDD: `1.26%` | Daily Sharpe: `-0.12` | Lệnh OOS: `59` | Phí: `$13.98`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-0.15%); Daily Sharpe thấp (-0.12 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$13.98` trên `59` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `1.26%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `2/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `59` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `dca_short` (System Leg dca_short)
- **Phân loại**: `COIN System Leg` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `+0.44%` | MDD: `0.54%` | Daily Sharpe: `0.54` | Lệnh OOS: `43` | Phí: `$10.36`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Daily Sharpe thấp (0.54 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$10.36` trên `43` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `0.54%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `3/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `43` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `18e87aa868ad` (Fast Dynamic Channel Breakout (18D + Macro Trend))
- **Phân loại**: `COIN User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-9.85%` | MDD: `22.78%` | Daily Sharpe: `-0.16` | Lệnh OOS: `67` | Phí: `$104.58`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `67.4%` | P(MDD ≥ 20%): `53.8%`
- **Lý do phân loại**: Lỗ OOS gộp (-9.85%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.16 < 0.8); MDD sâu (22.78% > 20%); P(MDD≥15%) cao (67.4% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$104.58` trên `67` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `22.78%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `67.4%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `67` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `18e87aa868ad_v2` (Fast Dynamic Channel Breakout V2 (Explicit ATR))
- **Phân loại**: `COIN User V2` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-1.03%` | MDD: `2.97%` | Daily Sharpe: `-0.38` | Lệnh OOS: `33` | Phí: `$7.43`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-1.03%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.38 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$7.43` trên `33` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `2.97%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `33` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `33312a2f4dfc` (Standard Deviation Dynamic Channel Breakout (v2.0 Regime Filtered))
- **Phân loại**: `COIN User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-7.80%` | MDD: `23.21%` | Daily Sharpe: `-0.11` | Lệnh OOS: `57` | Phí: `$95.50`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `64.4%` | P(MDD ≥ 20%): `51.7%`
- **Lý do phân loại**: Lỗ OOS gộp (-7.80%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.11 < 0.8); MDD sâu (23.21% > 20%); P(MDD≥15%) cao (64.4% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$95.50` trên `57` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `23.21%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `64.4%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `57` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `efa90f74cd08` (Donchian Channel Breakout (Turtle Trading))
- **Phân loại**: `COIN User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-6.71%` | MDD: `19.36%` | Daily Sharpe: `-0.41` | Lệnh OOS: `112` | Phí: `$38.73`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `27.0%` | P(MDD ≥ 20%): `8.5%`
- **Lý do phân loại**: Lỗ OOS gộp (-6.71%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.41 < 0.8); P(MDD≥15%) cao (27.0% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$38.73` trên `112` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `19.36%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `27.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `112` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `edu_canonical_beginner_dual_ema` (Nora EDU — Beginner Dual EMA Trend Following)
- **Phân loại**: `EDU Canonical` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-8.56%` | MDD: `9.55%` | Daily Sharpe: `-1.28` | Lệnh OOS: `411` | Phí: `$460.47`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.1%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-8.56%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.28 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$460.47` trên `411` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `9.55%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.1%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `411` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `edu_canonical_advanced_volatility_breakout` (Nora EDU — Advanced Volatility Breakout & ATR Guard)
- **Phân loại**: `EDU Canonical` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-0.57%` | MDD: `4.01%` | Daily Sharpe: `-0.14` | Lệnh OOS: `59` | Phí: `$71.26`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-0.57%); Daily Sharpe thấp (-0.14 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$71.26` trên `59` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `4.01%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `2/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `59` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `026f43441cb2` (U4WilliamsBullishDivergence)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-7.54%` | MDD: `7.90%` | Daily Sharpe: `-1.61` | Lệnh OOS: `202` | Phí: `$283.01`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-7.54%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-1.61 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$283.01` trên `202` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `7.90%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `202` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `0873864b8db7` (DEMA Turbo Compound (1Y Fast Trend - x1.51 Vốn))
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `+71.33%` | MDD: `20.92%` | Daily Sharpe: `0.85` | Lệnh OOS: `73` | Phí: `$233.57`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `20.1%` | P(MDD ≥ 20%): `6.1%`
- **Lý do phân loại**: MDD sâu (20.92% > 20%); P(MDD≥15%) cao (20.1% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$233.57` trên `73` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `20.92%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `20.1%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `3/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `73` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `090730ae35b8` (Fail-Fast Volatility Breakout (SL 2.4% + Macro Trend))
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-8.10%` | MDD: `24.06%` | Daily Sharpe: `-0.10` | Lệnh OOS: `57` | Phí: `$98.62`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `65.8%` | P(MDD ≥ 20%): `53.1%`
- **Lý do phân loại**: Lỗ OOS gộp (-8.10%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.10 < 0.8); MDD sâu (24.06% > 20%); P(MDD≥15%) cao (65.8% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$98.62` trên `57` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `24.06%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `65.8%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `57` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `0d51ba8d2012` (OBV Volume Accumulation + RSI Momentum)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-8.96%` | MDD: `27.51%` | Daily Sharpe: `-0.22` | Lệnh OOS: `156` | Phí: `$97.44`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `73.7%` | P(MDD ≥ 20%): `49.8%`
- **Lý do phân loại**: Lỗ OOS gộp (-8.96%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.22 < 0.8); MDD sâu (27.51% > 20%); P(MDD≥15%) cao (73.7% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$97.44` trên `156` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `27.51%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `73.7%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `156` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `138df68946ad` (U1PathEfficiencyTrend)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-6.86%` | MDD: `8.33%` | Daily Sharpe: `-1.52` | Lệnh OOS: `445` | Phí: `$701.69`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-6.86%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.52 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$701.69` trên `445` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `8.33%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `445` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `14e3b934b1e5` (ROC Momentum Exhaustion with Take-Profit)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-26.12%` | MDD: `31.62%` | Daily Sharpe: `-1.25` | Lệnh OOS: `627` | Phí: `$308.00`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `80.3%` | P(MDD ≥ 20%): `56.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-26.12%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.25 < 0.8); MDD sâu (31.62% > 20%); P(MDD≥15%) cao (80.3% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$308.00` trên `627` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `31.62%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `80.3%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `627` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `15567e02a806` (Triple EMA Trend Alignment (Optimized))
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-23.82%` | MDD: `37.48%` | Daily Sharpe: `-0.30` | Lệnh OOS: `37` | Phí: `$291.45`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `97.3%` | P(MDD ≥ 20%): `89.5%`
- **Lý do phân loại**: Lỗ OOS gộp (-23.82%); Daily Sharpe thấp (-0.30 < 0.8); MDD sâu (37.48% > 20%); P(MDD≥15%) cao (97.3% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$291.45` trên `37` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `37.48%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `97.3%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `2/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `37` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `1a1a4389a821` (U1BullishEngulfing)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-13.41%` | MDD: `14.23%` | Daily Sharpe: `-2.71` | Lệnh OOS: `1019` | Phí: `$1168.02`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.2%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-13.41%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.71 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$1168.02` trên `1019` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `14.23%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.2%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `1019` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `1e4c0b9f84f7` (U3BearTrapSweepReclaim)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-15.27%` | MDD: `16.37%` | Daily Sharpe: `-3.54` | Lệnh OOS: `1200` | Phí: `$1248.75`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.5%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-15.27%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-3.54 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$1248.75` trên `1200` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `16.37%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.5%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `1200` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `214ea8fdf3e6` (U2MoneyFlowRecovery)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-12.41%` | MDD: `12.75%` | Daily Sharpe: `-2.64` | Lệnh OOS: `694` | Phí: `$1029.69`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-12.41%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.64 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$1029.69` trên `694` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `12.75%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `694` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `234e6df02e37` (U2NarrowRangeFourRelease)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-31.77%` | MDD: `32.15%` | Daily Sharpe: `-5.45` | Lệnh OOS: `3436` | Phí: `$3570.98`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `95.9%` | P(MDD ≥ 20%): `49.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-31.77%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-5.45 < 0.8); MDD sâu (32.15% > 20%); P(MDD≥15%) cao (95.9% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$3570.98` trên `3436` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `32.15%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `95.9%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `3436` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `270e6e28416f` (EMA Trend Rider (Rising Slope - Optimized))
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-7.61%` | MDD: `43.99%` | Daily Sharpe: `0.07` | Lệnh OOS: `74` | Phí: `$292.95`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `93.3%` | P(MDD ≥ 20%): `85.5%`
- **Lý do phân loại**: Lỗ OOS gộp (-7.61%); Daily Sharpe thấp (0.07 < 0.8); MDD sâu (43.99% > 20%); P(MDD≥15%) cao (93.3% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$292.95` trên `74` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `43.99%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `93.3%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `2/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `74` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `2e41b2cfa24d` (U1CloseLocationAccumulation)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-9.74%` | MDD: `10.30%` | Daily Sharpe: `-2.34` | Lệnh OOS: `569` | Phí: `$725.77`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-9.74%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.34 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$725.77` trên `569` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `10.30%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `569` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `303d4b713dda` (Macro Trend Filtered Breakout (EMA 105 Filter))
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-8.18%` | MDD: `23.50%` | Daily Sharpe: `-0.12` | Lệnh OOS: `57` | Phí: `$96.02`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `65.0%` | P(MDD ≥ 20%): `52.2%`
- **Lý do phân loại**: Lỗ OOS gộp (-8.18%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.12 < 0.8); MDD sâu (23.50% > 20%); P(MDD≥15%) cao (65.0% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$96.02` trên `57` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `23.50%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `65.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `57` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `3cfcc2d296a2` (Donchian Lower Channel Exit)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-26.74%` | MDD: `30.11%` | Daily Sharpe: `-1.21` | Lệnh OOS: `270` | Phí: `$124.77`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `84.8%` | P(MDD ≥ 20%): `64.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-26.74%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.21 < 0.8); MDD sâu (30.11% > 20%); P(MDD≥15%) cao (84.8% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$124.77` trên `270` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `30.11%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `84.8%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `270` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `541c55834f56` (Daily Range Expansion (High - Low) / Close)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-33.00%` | MDD: `36.03%` | Daily Sharpe: `-1.32` | Lệnh OOS: `289` | Phí: `$136.16`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `91.1%` | P(MDD ≥ 20%): `75.5%`
- **Lý do phân loại**: Lỗ OOS gộp (-33.00%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.32 < 0.8); MDD sâu (36.03% > 20%); P(MDD≥15%) cao (91.1% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$136.16` trên `289` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `36.03%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `91.1%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `289` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `5e52d3fdf71f` (Bollinger Band Overextension Exit)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-27.83%` | MDD: `31.59%` | Daily Sharpe: `-2.04` | Lệnh OOS: `343` | Phí: `$144.78`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `72.6%` | P(MDD ≥ 20%): `44.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-27.83%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.04 < 0.8); MDD sâu (31.59% > 20%); P(MDD≥15%) cao (72.6% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$144.78` trên `343` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `31.59%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `72.6%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `343` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `6055aa8f661e` (Triple Filter: EMA + MACD + RSI)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-4.07%` | MDD: `13.37%` | Daily Sharpe: `-0.14` | Lệnh OOS: `75` | Phí: `$55.35`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `22.1%` | P(MDD ≥ 20%): `5.3%`
- **Lý do phân loại**: Lỗ OOS gộp (-4.07%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.14 < 0.8); P(MDD≥15%) cao (22.1% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$55.35` trên `75` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `13.37%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `22.1%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `75` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `616e1b8cbc88` (U2HammerRejection)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-28.33%` | MDD: `28.59%` | Daily Sharpe: `-6.09` | Lệnh OOS: `2690` | Phí: `$2855.19`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `85.1%` | P(MDD ≥ 20%): `14.9%`
- **Lý do phân loại**: Lỗ OOS gộp (-28.33%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-6.09 < 0.8); MDD sâu (28.59% > 20%); P(MDD≥15%) cao (85.1% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$2855.19` trên `2690` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `28.59%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `85.1%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `2690` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `6afa7f774655` (RSI Rebound with Fast SMA Filter)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-14.82%` | MDD: `15.60%` | Daily Sharpe: `-1.94` | Lệnh OOS: `47` | Phí: `$32.60`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `9.1%` | P(MDD ≥ 20%): `1.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-14.82%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.94 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$32.60` trên `47` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `15.60%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `9.1%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `47` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `715e56a6dd33` (Linear Regression Channel Deviation)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-13.13%` | MDD: `13.93%` | Daily Sharpe: `-1.64` | Lệnh OOS: `63` | Phí: `$42.58`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `6.0%` | P(MDD ≥ 20%): `0.5%`
- **Lý do phân loại**: Lỗ OOS gộp (-13.13%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.64 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$42.58` trên `63` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `13.93%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `6.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `63` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `717c1890c59e` (Weighted Moving Average (WMA) Crossover (Optimized))
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `+9.61%` | MDD: `29.43%` | Daily Sharpe: `0.32` | Lệnh OOS: `50` | Phí: `$257.38`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `86.4%` | P(MDD ≥ 20%): `67.3%`
- **Lý do phân loại**: Daily Sharpe thấp (0.32 < 0.8); MDD sâu (29.43% > 20%); P(MDD≥15%) cao (86.4% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$257.38` trên `50` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `29.43%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `86.4%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `2/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `50` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `74f607263c5c` (U4InsideBarRelease)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-3.61%` | MDD: `6.32%` | Daily Sharpe: `-0.74` | Lệnh OOS: `354` | Phí: `$628.14`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-3.61%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.74 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$628.14` trên `354` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `6.32%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `354` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `7c1bf0a9686a` (U4BullishOutsideReversal)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-11.27%` | MDD: `12.04%` | Daily Sharpe: `-2.62` | Lệnh OOS: `598` | Phí: `$766.41`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-11.27%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.62 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$766.41` trên `598` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `12.04%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `598` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `7f3486d63ca8` (Dual Oscillator Climax Exit)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-11.84%` | MDD: `17.99%` | Daily Sharpe: `-0.65` | Lệnh OOS: `265` | Phí: `$134.49`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `46.6%` | P(MDD ≥ 20%): `19.1%`
- **Lý do phân loại**: Lỗ OOS gộp (-11.84%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.65 < 0.8); P(MDD≥15%) cao (46.6% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$134.49` trên `265` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `17.99%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `46.6%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `265` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `7f67e9aed0aa` (Stochastic & RSI Confluence System)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-21.90%` | MDD: `25.26%` | Daily Sharpe: `-1.59` | Lệnh OOS: `121` | Phí: `$61.51`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `47.6%` | P(MDD ≥ 20%): `16.6%`
- **Lý do phân loại**: Lỗ OOS gộp (-21.90%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.59 < 0.8); MDD sâu (25.26% > 20%); P(MDD≥15%) cao (47.6% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$61.51` trên `121` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `25.26%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `47.6%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `121` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `7f770ebe5ab5` (U3HigherLowStaircase)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-10.99%` | MDD: `11.75%` | Daily Sharpe: `-2.73` | Lệnh OOS: `601` | Phí: `$762.86`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-10.99%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.73 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$762.86` trên `601` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `11.75%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `601` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `856ddc574ce7` (U2PiercingLine)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `+4.49%` | MDD: `31.39%` | Daily Sharpe: `0.22` | Lệnh OOS: `45` | Phí: `$45.08`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `76.1%` | P(MDD ≥ 20%): `50.6%`
- **Lý do phân loại**: Chỉ có 1/3 folds lãi; Daily Sharpe thấp (0.22 < 0.8); MDD sâu (31.39% > 20%); P(MDD≥15%) cao (76.1% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$45.08` trên `45` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `31.39%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `76.1%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `45` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `862e0c9eebbe` (U2MorningStar)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-8.45%` | MDD: `22.97%` | Daily Sharpe: `-0.28` | Lệnh OOS: `39` | Phí: `$45.45`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `52.7%` | P(MDD ≥ 20%): `27.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-8.45%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-0.28 < 0.8); MDD sâu (22.97% > 20%); P(MDD≥15%) cao (52.7% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$45.45` trên `39` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `22.97%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `52.7%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `39` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `89379cc0ab52` (Stochastic Oscillator (%K, %D) Bull Cross)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-23.24%` | MDD: `28.51%` | Daily Sharpe: `-1.28` | Lệnh OOS: `205` | Phí: `$111.68`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `65.8%` | P(MDD ≥ 20%): `36.8%`
- **Lý do phân loại**: Lỗ OOS gộp (-23.24%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.28 < 0.8); MDD sâu (28.51% > 20%); P(MDD≥15%) cao (65.8% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$111.68` trên `205` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `28.51%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `65.8%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `205` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `930294d28c45` (U3TweezerBottom)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-9.83%` | MDD: `11.03%` | Daily Sharpe: `-0.92` | Lệnh OOS: `36` | Phí: `$33.96`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `9.1%` | P(MDD ≥ 20%): `1.3%`
- **Lý do phân loại**: Lỗ OOS gộp (-9.83%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-0.92 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$33.96` trên `36` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `11.03%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `9.1%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `36` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `9eec3d61131d` (U3SelloffStreakReclaim)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-6.01%` | MDD: `6.14%` | Daily Sharpe: `-1.74` | Lệnh OOS: `249` | Phí: `$494.89`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-6.01%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.74 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$494.89` trên `249` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `6.14%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `249` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `a4d6826fbbc6` (U1VolumePriceTrendFlow)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-14.44%` | MDD: `15.54%` | Daily Sharpe: `-2.97` | Lệnh OOS: `1297` | Phí: `$1302.37`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.7%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-14.44%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.97 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$1302.37` trên `1297` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `15.54%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.7%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `1297` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `af2bf88426c4` (U3DownsideShockReclaim)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-5.50%` | MDD: `6.72%` | Daily Sharpe: `-1.24` | Lệnh OOS: `272` | Phí: `$534.38`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-5.50%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.24 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$534.38` trên `272` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `6.72%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `272` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `b4b65cd3493f` (Commodity Channel Index (CCI) Snapback)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-20.99%` | MDD: `24.56%` | Daily Sharpe: `-1.29` | Lệnh OOS: `292` | Phí: `$122.51`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `52.8%` | P(MDD ≥ 20%): `22.9%`
- **Lý do phân loại**: Lỗ OOS gộp (-20.99%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.29 < 0.8); MDD sâu (24.56% > 20%); P(MDD≥15%) cao (52.8% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$122.51` trên `292` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `24.56%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `52.8%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `292` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `bd234070bd7b` (U1HaramiRangeBreak)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-5.13%` | MDD: `5.39%` | Daily Sharpe: `-1.71` | Lệnh OOS: `87` | Phí: `$198.00`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-5.13%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.71 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$198.00` trên `87` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `5.39%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `87` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `be1174b24a44` (U1VolumeAbsorption)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-1.94%` | MDD: `1.99%` | Daily Sharpe: `-1.21` | Lệnh OOS: `41` | Phí: `$105.73`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-1.94%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.21 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$105.73` trên `41` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `1.99%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `41` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `bf519617d973` (Double Exponential Moving Average (DEMA - Optimized))
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `+81.79%` | MDD: `44.31%` | Daily Sharpe: `0.57` | Lệnh OOS: `54` | Phí: `$355.95`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `92.2%` | P(MDD ≥ 20%): `79.8%`
- **Lý do phân loại**: Chỉ có 1/3 folds lãi; Daily Sharpe thấp (0.57 < 0.8); MDD sâu (44.31% > 20%); P(MDD≥15%) cao (92.2% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$355.95` trên `54` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `44.31%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `92.2%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `54` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `c33cc317bbeb` (Multi-Day Cumulative Return Dip Buying)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-33.51%` | MDD: `33.68%` | Daily Sharpe: `-2.69` | Lệnh OOS: `182` | Phí: `$91.73`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `81.7%` | P(MDD ≥ 20%): `53.9%`
- **Lý do phân loại**: Lỗ OOS gộp (-33.51%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.69 < 0.8); MDD sâu (33.68% > 20%); P(MDD≥15%) cao (81.7% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$91.73` trên `182` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `33.68%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `81.7%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `182` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `cb0b6e0f12e7` (U1DirectionalBodyBalance)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-11.85%` | MDD: `12.85%` | Daily Sharpe: `-2.29` | Lệnh OOS: `1032` | Phí: `$1232.30`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.2%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-11.85%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.29 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$1232.30` trên `1032` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `12.85%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.2%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `1032` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `d0518c0cca14` (U4DownsideSemivarianceContraction)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-10.80%` | MDD: `11.48%` | Daily Sharpe: `-3.59` | Lệnh OOS: `570` | Phí: `$705.35`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-10.80%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-3.59 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$705.35` trên `570` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `11.48%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `570` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `e9a9a5b44d03` (U2DoubleBottomRetest)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-8.43%` | MDD: `21.00%` | Daily Sharpe: `-0.37` | Lệnh OOS: `69` | Phí: `$62.53`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `39.7%` | P(MDD ≥ 20%): `15.7%`
- **Lý do phân loại**: Lỗ OOS gộp (-8.43%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-0.37 < 0.8); MDD sâu (21.00% > 20%); P(MDD≥15%) cao (39.7% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$62.53` trên `69` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `21.00%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `39.7%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `69` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `ee0cf7f58f94` (U2RepeatedLowerTailReclaim)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-10.16%` | MDD: `26.83%` | Daily Sharpe: `-0.29` | Lệnh OOS: `54` | Phí: `$49.08`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `65.3%` | P(MDD ≥ 20%): `39.6%`
- **Lý do phân loại**: Lỗ OOS gộp (-10.16%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-0.29 < 0.8); MDD sâu (26.83% > 20%); P(MDD≥15%) cao (65.3% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$49.08` trên `54` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `26.83%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `65.3%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `54` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `efb1fbe2db86` (Volatility Expansion Channel (StdDev 1.51 + Macro Trend))
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-7.80%` | MDD: `23.21%` | Daily Sharpe: `-0.11` | Lệnh OOS: `57` | Phí: `$95.50`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `64.4%` | P(MDD ≥ 20%): `51.7%`
- **Lý do phân loại**: Lỗ OOS gộp (-7.80%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.11 < 0.8); MDD sâu (23.21% > 20%); P(MDD≥15%) cao (64.4% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$95.50` trên `57` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `23.21%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `64.4%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `57` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `f261549d9efa` (ROC Momentum Surge)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-12.49%` | MDD: `27.63%` | Daily Sharpe: `-0.28` | Lệnh OOS: `229` | Phí: `$136.60`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `75.6%` | P(MDD ≥ 20%): `47.2%`
- **Lý do phân loại**: Lỗ OOS gộp (-12.49%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.28 < 0.8); MDD sâu (27.63% > 20%); P(MDD≥15%) cao (75.6% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$136.60` trên `229` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `27.63%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `75.6%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `229` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `f4e211e9510d` (Rolling 30-Day Multi-Week High Breakout)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-5.70%` | MDD: `18.48%` | Daily Sharpe: `-0.14` | Lệnh OOS: `74` | Phí: `$67.14`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `56.5%` | P(MDD ≥ 20%): `29.6%`
- **Lý do phân loại**: Lỗ OOS gộp (-5.70%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.14 < 0.8); P(MDD≥15%) cao (56.5% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$67.14` trên `74` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `18.48%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `56.5%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `74` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `fa9587a97fa9` (Trend Alignment Momentum (Optimized))
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-43.75%` | MDD: `53.55%` | Daily Sharpe: `-0.31` | Lệnh OOS: `50` | Phí: `$293.03`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `97.9%` | P(MDD ≥ 20%): `93.8%`
- **Lý do phân loại**: Lỗ OOS gộp (-43.75%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.31 < 0.8); MDD sâu (53.55% > 20%); P(MDD≥15%) cao (97.9% > 10%)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$293.03` trên `50` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `53.55%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `97.9%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `1/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `50` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.

## Alpha: `fd16df3d0a3f` (U3ThreeCandleBodyAdvance)
- **Phân loại**: `EDU User` | Phán quyết tạm thời: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-7.82%` | MDD: `8.87%` | Daily Sharpe: `-2.20` | Lệnh OOS: `241` | Phí: `$465.08`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do phân loại**: Lỗ OOS gộp (-7.82%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.20 < 0.8)
- **1. Ma sát phí (Mô tả số liệu)**: Tổng phí `$465.08` trên `241` lệnh OOS.
- **2. Sụt giảm vốn & SL (Mô tả số liệu)**: Drawdown OOS thực tế đạt `8.87%` (ngưỡng tối đa cho phép $\le 20.0\%$); xác suất mô phỏng bootstrap P(MDD ≥ 15%) = `0.0%`.
- **3. Nhất quán Folds (Mô tả số liệu)**: Đạt `0/3 Folds Positive` fold có lợi nhuận dương qua 3 chu kỳ OOS độc lập.
- **4. Quy mô mẫu (Mô tả số liệu)**: Đạt `241` lệnh OOS gộp, đáp ứng điều kiện mẫu tối thiểu (Phương án A: $\ge 30$ lệnh) để chấm điểm OOS.