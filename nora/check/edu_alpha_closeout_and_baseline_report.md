# BÁO CÁO ĐO LƯỜNG BASELINE SƠ BỘ KHO ALPHA NORA EDU

> [!WARNING]
> **TUYÊN BỐ VỀ BẢN CHẤT NGHIÊN CỨU & NGUYÊN TẮC KHOA HỌC:**
> 1. Đây là **Báo cáo Đo lường Baseline Sơ bộ (Preliminary Baseline Measurement)** ghi nhận kết quả mô phỏng ban đầu của các alpha. Báo cáo này **KHÔNG PHẢI** là nghiệm thu bàn giao cuối cùng, không chứng minh trading edge thực tế, và không cấu thành phê duyệt triển khai Live Trading.
> 2. **27/57 Alpha người dùng tiếp tục bị CHẶN (`BLOCKED_UNKNOWN_INTENT`)** do chứa điều kiện hằng số/bất khả thi (`close > 0`, `close > 10`, `close < 0`, `close > 1`). Hệ thống bảo toàn nguyên vẹn bản ghi và không tự suy diễn ý đồ của người dùng.
> 3. **Không sử dụng nhãn 'ROBUST':** Việc đánh giá độ bền đòi hỏi quy trình Walk-Forward đa khung thời gian và kiểm định Holdout độc lập một lần duy nhất. Báo cáo này chỉ ghi nhận các số đo mô tả (descriptive baseline).

## 1. THÔNG SỐ THỰC THI & GIỚI HẠN MÔ HÌNH (EXECUTION DISCLOSURES)
- **Engine thực thi:** `NautilusTrader 1.231.0` chạy trong tiến trình con độc lập qua `ops/run_limited.sh`.
- **Giới hạn tài nguyên (Execution Gate):** Tuân thủ cgroup slice `nora.slice` với trần RAM **2 GB/job** (`MemoryMax=2G`, không swap, `nice 10`, CPU affinity `0-13`). Mức sử dụng RAM đỉnh thực tế từ **907.5 MiB đến 1,499.3 MiB** (100% nằm dưới trần 2 GB, 0 lỗi OOM).
- **Semantics của In-Sample (Train) vs Out-of-Sample (OOS):**
  - Giai đoạn In-Sample (Train) và Out-of-Sample (OOS) là các lần mô phỏng **chạy riêng biệt** trong engine (`backend/analys/metrics/trades.py::stage_split`).
  - Giai đoạn OOS bắt đầu từ mốc chia thời gian với **vốn khởi điểm ban đầu mới (fresh capital 10,000 USD)** và từ trạng thái ban đầu không có vị thế mở, không phải là luồng vốn nối tiếp từ Train.
  - Vì là hai lần chạy độc lập, số lệnh phát sinh trong OOS ở một số chiến lược có thể chênh lệch hoặc lớn hơn số lệnh Full-window (ví dụ: `bf519617d973` Full có 9 lệnh nhưng OOS chạy riêng sinh 22 lệnh).
- **Cơ chế khớp lệnh & Chi phí:**
  - **Khớp lệnh (Fill):** Khớp tại giá mở cửa nến tiếp theo (`synthetic OHLC open quote`).
  - **Phí giao dịch (Fees):** Phí CEX phái sinh chuẩn (Maker 0.02%, Taker 0.05%).
  - **Trượt giá (Slippage):** Giả định bằng 0 (`slippage_ticks=0`); chưa đo lường trượt giá sổ lệnh L2 thực tế.
  - **Funding Rate & Liquidation:** Chưa được mô hình hóa trong đợt chạy baseline này.
- **Dữ liệu lịch sử:** Nến chuẩn 1m/24h từ kho OKX Perpetual (`BTC`, `ETH`, `SOL`, `BNB`, `XRP`, `DOGE`, `ADA`, `AVAX`, `LINK`, `TRX`).

## 2. TỔNG KẾT PHÂN BỔ BASELINE (30 ALPHA ĐỦ ĐIỀU KIỆN)
- **Tổng số Alpha User:** 57 (30 `VALID_AS_IS`, 27 `BLOCKED_UNKNOWN_INTENT`).
- **Số Alpha hoàn thành chạy Baseline:** **30/30** (100% hoàn tất qua runner, 0 lỗi runtime).
- **Khảo sát Lợi nhuận Toàn kỳ (Full Window):** 15 Dương (50%) / 15 Không dương (50%).
- **Phân loại Mô tả theo Kết quả Thực tế:**
  - **Lợi nhuận OOS dương biên (`OOS_MARGINAL_POSITIVE`):** **6/30** (20.0%) — Đạt lợi nhuận dương trên OOS (+0.81% đến +6.87%, Sharpe OOS 0.10 đến 0.31), nhưng hiệu suất suy giảm mạnh so với In-Sample.
  - **Lợi nhuận OOS dương với mẫu nhỏ (`OOS_POSITIVE_SMALL_SAMPLE`):** **1/30** (3.3%) — Chiến lược FastDip (`8a47cdbcc942` của Vinh) lãi +18.17% trên OOS nhưng chỉ có duy nhất **3 lệnh** trên cửa sổ ngắn 3 tháng, không thể so sánh tương đương với 29 alpha còn lại.
  - **Toàn kỳ dương nhưng OOS âm (`FULL_POSITIVE_OOS_NEGATIVE`):** **8/30** (26.7%) — Lợi nhuận toàn kỳ và Train dương nhưng OOS âm.
  - **Toàn kỳ không dương và OOS âm (`FULL_NON_POSITIVE_OOS_NEGATIVE`):** **15/30** (50.0%) — Trong đó 13 alpha âm cả Train lẫn OOS, 2 alpha có Train dương nhẹ (+0.18% và +1.71%) nhưng toàn kỳ và OOS đều âm.
- **Cảnh báo Lệch Đơn vị Runtime (Unit Mismatch):** **7/30 Alpha của user Vinh** code khai báo `stop_loss_pct` nhưng cấu hình runtime thực tế đang ăn `exit_unit='atr'` (thoát lệnh theo khoảng cách biến động ATR chứ không phải % giá cố định).

## 3. BẢNG DỮ LIỆU ĐO LƯỜNG CHI TIẾT (FULL SIMULATE VS OUT-OF-SAMPLE)

| ID | Tên chiến lược | Chủ sở hữu | Cửa sổ dữ liệu | Toàn kỳ (%) | MDD (%) | Train (%) | OOS (%) | OOS Sharpe | Lệnh (Full/OOS) | Phí ($) | Exit Unit | Phân loại Mô tả |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `0873864b8db7` | DEMA Turbo Compound (1Y  | Vinh | 2023-10-06..2026-10-03 (tr=0.7) | **+130.52%** | 24.23% | +112.40% | **+6.87%** | 0.31 | 272 / 149 | 995.8 | ⚠️ `atr` | `OOS_MARGINAL_POSITIVE` |
| `090730ae35b8` | Fail-Fast Volatility Bre | Vinh | 2023-10-06..2026-10-03 (tr=0.7) | **+69.24%** | 24.67% | +64.30% | **+3.00%** | 0.19 | 119 / 56 | 194.1 | ⚠️ `atr` | `OOS_MARGINAL_POSITIVE` |
| `0d51ba8d2012` | OBV Volume Accumulation  | 43f5220e | 2023-10-06..2026-10-03 (tr=0.7) | **+7.28%** | 28.18% | +19.26% | **-11.39%** | -0.53 | 256 / 159 | 124.3 | `pct` | `FULL_POSITIVE_OOS_NEGATIVE` |
| `14e3b934b1e5` | ROC Momentum Exhaustion  | 23dc66cd | 2023-10-06..2026-10-03 (tr=0.7) | **-29.81%** | 30.17% | -22.21% | **-27.78%** | -1.90 | 736 / 381 | 238.2 | `pct` | `FULL_NON_POSITIVE_OOS_NEGATIVE` |
| `15567e02a806` | Triple EMA Trend Alignme | 23dc66cd | 2023-10-06..2026-10-03 (tr=0.7) | **+0.20%** | 31.84% | +0.20% | **-33.74%** | -1.69 | 24 / 9 | 165.7 | `pct` | `FULL_POSITIVE_OOS_NEGATIVE` |
| `18e87aa868ad` | Fast Dynamic Channel Bre | Vinh | 2023-10-06..2026-10-03 (tr=0.7) | **+70.16%** | 24.88% | +73.67% | **-1.97%** | 0.05 | 130 / 71 | 220.7 | ⚠️ `atr` | `FULL_POSITIVE_OOS_NEGATIVE` |
| `270e6e28416f` | EMA Trend Rider (Rising  | a214b36a | 2023-10-06..2026-10-03 (tr=0.7) | **-31.35%** | 31.74% | -31.35% | **-23.26%** | -0.84 | 13 / 17 | 48.0 | `pct` | `FULL_NON_POSITIVE_OOS_NEGATIVE` |
| `303d4b713dda` | Macro Trend Filtered Bre | Vinh | 2023-10-06..2026-10-03 (tr=0.7) | **+69.19%** | 24.25% | +63.67% | **+3.38%** | 0.20 | 112 / 56 | 189.5 | ⚠️ `atr` | `OOS_MARGINAL_POSITIVE` |
| `33312a2f4dfc` | Standard Deviation Dynam | Vinh | 2023-10-06..2026-10-03 (tr=0.7) | **+68.09%** | 23.80% | +62.57% | **+3.38%** | 0.20 | 115 / 56 | 188.5 | ⚠️ `atr` | `OOS_MARGINAL_POSITIVE` |
| `3cfcc2d296a2` | Donchian Lower Channel E | 43f5220e | 2023-10-06..2026-10-03 (tr=0.7) | **-26.41%** | 30.21% | -3.51% | **-26.77%** | -1.78 | 351 / 193 | 135.7 | `pct` | `FULL_NON_POSITIVE_OOS_NEGATIVE` |
| `4f28285aa44c` | Dual EMA + ADX Trend Str | 23dc66cd | 2023-10-06..2026-10-03 (tr=0.7) | **-4.40%** | 4.97% | -2.52% | **-3.66%** | -0.49 | 10 / 7 | 7.3 | `pct` | `FULL_NON_POSITIVE_OOS_NEGATIVE` |
| `541c55834f56` | Daily Range Expansion (H | dd3d4fba | 2023-10-06..2026-10-03 (tr=0.7) | **+8.90%** | 30.33% | +40.78% | **-25.74%** | -1.35 | 381 / 189 | 222.0 | `pct` | `FULL_POSITIVE_OOS_NEGATIVE` |
| `5e52d3fdf71f` | Bollinger Band Overexten | 76c58142 | 2023-10-06..2026-10-03 (tr=0.7) | **-24.74%** | 30.02% | -3.36% | **-24.89%** | -1.36 | 504 / 228 | 192.4 | `pct` | `FULL_NON_POSITIVE_OOS_NEGATIVE` |
| `6055aa8f661e` | Triple Filter: EMA + MAC | a214b36a | 2023-10-06..2026-10-03 (tr=0.7) | **+5.09%** | 16.14% | +5.13% | **+0.81%** | 0.10 | 139 / 73 | 70.0 | `pct` | `OOS_MARGINAL_POSITIVE` |
| `6afa7f774655` | RSI Rebound with Fast SM | a214b36a | 2023-10-06..2026-10-03 (tr=0.7) | **-12.03%** | 12.99% | -4.33% | **-10.25%** | -1.72 | 57 / 47 | 24.3 | `pct` | `FULL_NON_POSITIVE_OOS_NEGATIVE` |
| `715e56a6dd33` | Linear Regression Channe | 43f5220e | 2023-10-06..2026-10-03 (tr=0.7) | **-13.52%** | 14.56% | -6.28% | **-11.02%** | -1.61 | 99 / 63 | 42.2 | `pct` | `FULL_NON_POSITIVE_OOS_NEGATIVE` |
| `717c1890c59e` | Weighted Moving Average  | dd3d4fba | 2023-10-06..2026-10-03 (tr=0.7) | **+126.95%** | 31.89% | +172.89% | **-9.49%** | -0.07 | 59 / 46 | 373.1 | `pct` | `FULL_POSITIVE_OOS_NEGATIVE` |
| `7f3486d63ca8` | Dual Oscillator Climax E | dd3d4fba | 2023-10-06..2026-10-03 (tr=0.7) | **-11.22%** | 22.19% | +1.71% | **-17.14%** | -0.99 | 424 / 267 | 177.6 | `pct` | `FULL_NON_POSITIVE_OOS_NEGATIVE` |
| `7f67e9aed0aa` | Stochastic & RSI Conflue | dd3d4fba | 2023-10-06..2026-10-03 (tr=0.7) | **-15.90%** | 20.49% | +0.18% | **-16.75%** | -1.42 | 158 / 124 | 68.1 | `pct` | `FULL_NON_POSITIVE_OOS_NEGATIVE` |
| `89379cc0ab52` | Stochastic Oscillator (% | 76c58142 | 2023-10-06..2026-10-03 (tr=0.7) | **-19.14%** | 26.32% | -0.47% | **-20.96%** | -1.40 | 299 / 208 | 123.8 | `pct` | `FULL_NON_POSITIVE_OOS_NEGATIVE` |
| `8a47cdbcc942` | Fast Dip Harvester (3M D | Vinh | 2026-07-01..2026-10-03 (tr=0.3) | **+18.17%** | 1.03% | +0.00% | **+18.17%** | 3.36 | 3 / 3 | 16.0 | ⚠️ `atr` | `OOS_POSITIVE_SMALL_SAMPLE` |
| `b4b65cd3493f` | Commodity Channel Index  | 23dc66cd | 2023-10-06..2026-10-03 (tr=0.7) | **-21.49%** | 27.69% | -13.35% | **-13.17%** | -0.79 | 479 / 287 | 171.9 | `pct` | `FULL_NON_POSITIVE_OOS_NEGATIVE` |
| `b96bafe57445` | Normalized ATR (NATR) Vo | 76c58142 | 2023-10-06..2026-10-03 (tr=0.7) | **-7.44%** | 11.02% | -4.38% | **-6.55%** | -0.94 | 45 / 18 | 25.5 | `pct` | `FULL_NON_POSITIVE_OOS_NEGATIVE` |
| `bf519617d973` | Double Exponential Movin | 76c58142 | 2023-10-06..2026-10-03 (tr=0.7) | **-31.86%** | 32.28% | -31.86% | **-12.32%** | -0.13 | 9 / 22 | 43.7 | `pct` | `FULL_NON_POSITIVE_OOS_NEGATIVE` |
| `c33cc317bbeb` | Multi-Day Cumulative Ret | dd3d4fba | 2023-10-06..2026-10-03 (tr=0.7) | **-31.12%** | 31.48% | -13.90% | **-28.81%** | -2.31 | 205 / 166 | 75.5 | `pct` | `FULL_NON_POSITIVE_OOS_NEGATIVE` |
| `cb750cb1eb10` | EMA Golden Cross + Volum | 76c58142 | 2023-10-06..2026-10-03 (tr=0.7) | **-4.57%** | 7.86% | -2.86% | **-5.05%** | -0.64 | 28 / 18 | 13.8 | `pct` | `FULL_NON_POSITIVE_OOS_NEGATIVE` |
| `efb1fbe2db86` | Volatility Expansion Cha | Vinh | 2023-10-06..2026-10-03 (tr=0.7) | **+67.88%** | 23.81% | +62.41% | **+3.38%** | 0.20 | 115 / 56 | 188.4 | ⚠️ `atr` | `OOS_MARGINAL_POSITIVE` |
| `f261549d9efa` | ROC Momentum Surge | 23dc66cd | 2023-10-06..2026-10-03 (tr=0.7) | **+1.28%** | 29.95% | +26.62% | **-21.42%** | -1.33 | 413 / 241 | 223.9 | `pct` | `FULL_POSITIVE_OOS_NEGATIVE` |
| `f4e211e9510d` | Rolling 30-Day Multi-Wee | a214b36a | 2023-10-06..2026-10-03 (tr=0.7) | **+15.97%** | 15.10% | +24.12% | **-6.59%** | -0.57 | 166 / 77 | 103.6 | `pct` | `FULL_POSITIVE_OOS_NEGATIVE` |
| `fa9587a97fa9` | Trend Alignment Momentum | 43f5220e | 2023-10-06..2026-10-03 (tr=0.7) | **+63.45%** | 33.50% | +63.45% | **-29.25%** | -1.14 | 16 / 19 | 63.7 | `pct` | `FULL_POSITIVE_OOS_NEGATIVE` |

## 4. QUAN SÁT KỸ THUẬT & CÁC YẾU TỐ CẦN KIỂM CHỨNG (EMPIRICAL OBSERVATIONS)

### A. Hiện tượng chênh lệch giữa In-Sample và Out-of-Sample (8 Alpha nhóm FULL_POSITIVE_OOS_NEGATIVE):
- **Hiện tượng:**
  - `717c1890c59e` (WMA Crossover): Tập Train (70% thời gian) đạt **+172.89%**, nhưng sang tập Test OOS (30% thời gian) ghi nhận **-9.49%**.
  - `fa9587a97fa9` (Trend Alignment): Tập Train đạt **+63.45%**, nhưng OOS sụt giảm xuống **-29.25%** (Sharpe OOS -1.14).
  - `541c55834f56` (Daily Range Expansion): Train đạt **+40.78%**, OOS ghi nhận **-25.74%**.
- **Ý nghĩa kỹ thuật:** Sự sụt giảm hiệu suất mạnh giữa Train và OOS là tín hiệu cảnh báo rõ ràng. Tuy nhiên, để xác định đây là do hiện tượng curve-fitting (overfitting tham số) hay do thị trường chuyển pha chế độ (regime shift), cần thực hiện thêm các phân tích phân rã lợi nhuận theo chế độ thị trường (regime attribution) và kiểm định walk-forward rolling window.

### B. Vai trò của chi phí giao dịch (Fee Impact):
- **Số liệu quan sát:**
  - `14e3b934b1e5` (ROC Momentum): Phát sinh **736 lệnh**, tiền phí sàn ghi nhận **238.2 USD**, PnL toàn kỳ **-29.81%**.
  - `5e52d3fdf71f` (Bollinger Overextension): Phát sinh **504 lệnh**, phí sàn **192.4 USD**, PnL **-24.74%**.
  - `b4b65cd3493f` (CCI Snapback): Phát sinh **479 lệnh**, phí sàn **171.9 USD**, PnL **-21.49%**.
- **Đánh giá:** Chi phí giao dịch ở mức hàng trăm USD là yếu tố khách quan làm suy giảm vốn trong điều kiện giao dịch tần suất lớn. Tuy nhiên, để xác định tỷ trọng tác động chính xác của phí sàn đối với tổng khoản lỗ, cần thực hiện thêm các lượt chạy đối chứng giả định không phí (`zero-fee counterfactual runs`).

### C. Tỷ lệ thắng thấp và cấu hình Stop-Loss:
- **Số liệu quan sát:**
  - `bf519617d973` (DEMA Optimized): Tỷ lệ thắng **0.0%** (9 lệnh full / 22 lệnh OOS), lỗ toàn kỳ **-31.86%**; cấu hình `stop_loss_rate = 2.5%`.
  - `4f28285aa44c` (Dual EMA + ADX): Tỷ lệ thắng **0.0%** (10 lệnh full / 7 lệnh OOS), lỗ **-4.40%**; cấu hình `stop_loss_rate = 3.0%`.
  - `270e6e28416f` (EMA Trend Rider): Tỷ lệ thắng **7.7%** (13 lệnh full / 17 lệnh OOS), lỗ **-31.35%**; cấu hình `stop_loss_rate = 2.5%`.
- **Đánh giá:** Các chiến lược này đều có mức Stop-Loss cố định từ 2.5% đến 3.0% trên khung nến ngày 24h. Tỷ lệ thắng cực thấp là hiện tượng cần đối chiếu với trade-level log chi tiết để phân biệt giữa việc bị chạm ngưỡng cắt lỗ do biến động ngắn hạn (whipsaw) hay do bản thân tín hiệu vào lệnh ngược pha xu hướng.

### D. Nhóm Alpha có OOS dương và trường hợp FastDip (`8a47cdbcc942`):
- **Nhóm 6 Alpha OOS dương biên:**
  - `0873864b8db7` (DEMA Turbo Compound): Toàn kỳ đạt **+130.52%**, Train đạt **+112.40%**, nhưng OOS chỉ còn **+6.87%** với Sharpe OOS rơi xuống **0.31**.
  - Các alpha breakout channel của Vinh (`090730ae35b8`, `303d4b713dda`, `33312a2f4dfc`, `efb1fbe2db86`) và `6055aa8f661e`: Đều ghi nhận OOS dương ở mức nhỏ (**+0.81% đến +3.38%**). Cả 6 alpha này đều chạy dưới cấu hình `exit_unit="atr"`.
- **Chiến lược FastDip (`8a47cdbcc942`):**
  - Đạt lợi nhuận OOS **+18.17%**, Sharpe 3.36, MDD 1.03%.
  - Tuy nhiên, chiến lược này chỉ được cấu hình chạy trong **cửa sổ ngắn 3 tháng** (`2026-07-01` đến `2026-10-03`, train ratio 0.3) và **chỉ phát sinh duy nhất 3 lệnh giao dịch**.
  - Đây là kích thước mẫu quá nhỏ, chưa đủ để đánh giá độ bền thống kê. Cửa sổ và tỷ lệ train của FastDip tách biệt hoàn toàn với 29 alpha còn lại, không cấu thành cùng một mặt phẳng so sánh.

## 5. DANH SÁCH 27 ALPHA BỊ CHẶN (BLOCKED_UNKNOWN_INTENT)

| ID | Tên Alpha | Chủ sở hữu | Lý do kỹ thuật & Căn cứ pháp lý |
|---|---|---|---|
| `026f43441cb2` | U4_BTC_1h_Different_Window | 16e97dcc | Biểu thức điều kiện hằng số `close > 1` trên BTC; luôn vào LONG và không có điều kiện thoát lệnh. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `0bf936687964` | U4_BTC_1h_Different_Window | e53ccc4b | Biểu thức điều kiện hằng số `close > 1` trên BTC; luôn vào LONG và không có điều kiện thoát lệnh. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `138df68946ad` | U1_BTC_1h_Alpha | ecf30ed0 | Biểu thức điều kiện hằng số `close > 0` trên BTC; luôn vào LONG ngay từ nến 1 và không có điều kiện thoát lệnh. Theo quy tắc cốt lõi 'Unknown semantics remain blocked, not guessed', không tự bịa đặt luật thay thế. |
| `1a1a4389a821` | U1_BTC_1h_Alpha | 2922e08b | Biểu thức điều kiện hằng số `close > 0` trên BTC; luôn vào LONG ngay từ nến 1 và không có điều kiện thoát lệnh. Theo quy tắc cốt lõi 'Unknown semantics remain blocked, not guessed', không tự bịa đặt luật thay thế. |
| `1e4c0b9f84f7` | U3_BTC_Small_Alpha | 9b7a10c3 | Biểu thức điều kiện bất khả thi `close < 0` trên giá thị trường BTC; không bao giờ sinh tín hiệu giao dịch. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `214ea8fdf3e6` | U2_ETH_15m_Alpha | 423d35ac | Biểu thức điều kiện hằng số `close > 10` trên ETH; luôn vào LONG và không có điều kiện thoát lệnh. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `234e6df02e37` | U2_ETH_15m_Alpha | 5de31662 | Biểu thức điều kiện hằng số `close > 10` trên ETH; luôn vào LONG và không có điều kiện thoát lệnh. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `2e41b2cfa24d` | U1_BTC_1h_Alpha | 3bbc767f | Biểu thức điều kiện hằng số `close > 0` trên BTC; luôn vào LONG ngay từ nến 1 và không có điều kiện thoát lệnh. Theo quy tắc cốt lõi 'Unknown semantics remain blocked, not guessed', không tự bịa đặt luật thay thế. |
| `571474a18f55` | U3_BTC_Small_Alpha | 82e8ccc3 | Biểu thức điều kiện bất khả thi `close < 0` trên giá thị trường BTC; không bao giờ sinh tín hiệu giao dịch. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `616e1b8cbc88` | U2_ETH_15m_Alpha | 184e6dc9 | Biểu thức điều kiện hằng số `close > 10` trên ETH; luôn vào LONG và không có điều kiện thoát lệnh. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `64b657c8de8e` | U4_BTC_1h_Different_Window | c7f8e101 | Biểu thức điều kiện hằng số `close > 1` trên BTC; luôn vào LONG và không có điều kiện thoát lệnh. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `74f607263c5c` | U4_BTC_1h_Different_Window | 726ff949 | Biểu thức điều kiện hằng số `close > 1` trên BTC; luôn vào LONG và không có điều kiện thoát lệnh. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `7c1bf0a9686a` | U4_BTC_1h_Different_Window | dbbb50a3 | Biểu thức điều kiện hằng số `close > 1` trên BTC; luôn vào LONG và không có điều kiện thoát lệnh. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `7f770ebe5ab5` | U3_BTC_Small_Alpha | eb5d7e2e | Biểu thức điều kiện bất khả thi `close < 0` trên giá thị trường BTC; không bao giờ sinh tín hiệu giao dịch. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `856ddc574ce7` | U2_ETH_15m_Alpha | 9fc184ee | Biểu thức điều kiện hằng số `close > 10` trên ETH; luôn vào LONG và không có điều kiện thoát lệnh. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `862e0c9eebbe` | U2_ETH_15m_Alpha | e7c99860 | Biểu thức điều kiện hằng số `close > 10` trên ETH; luôn vào LONG và không có điều kiện thoát lệnh. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `930294d28c45` | U3_BTC_Small_Alpha | 439fa753 | Biểu thức điều kiện bất khả thi `close < 0` trên giá thị trường BTC; không bao giờ sinh tín hiệu giao dịch. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `9eec3d61131d` | U3_BTC_Small_Alpha | 79183007 | Biểu thức điều kiện bất khả thi `close < 0` trên giá thị trường BTC; không bao giờ sinh tín hiệu giao dịch. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `a4d6826fbbc6` | U4_BTC_1h_Different_Window | 4547f1f5 | Biểu thức điều kiện hằng số `close > 1` trên BTC; luôn vào LONG và không có điều kiện thoát lệnh. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `af2bf88426c4` | U3_BTC_Small_Alpha | bf158b51 | Biểu thức điều kiện bất khả thi `close < 0` trên giá thị trường BTC; không bao giờ sinh tín hiệu giao dịch. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `bd234070bd7b` | U1_BTC_1h_Alpha | bbd150bc | Biểu thức điều kiện hằng số `close > 0` trên BTC; luôn vào LONG ngay từ nến 1 và không có điều kiện thoát lệnh. Theo quy tắc cốt lõi 'Unknown semantics remain blocked, not guessed', không tự bịa đặt luật thay thế. |
| `be1174b24a44` | U1_BTC_1h_Alpha | 657914b9 | Biểu thức điều kiện hằng số `close > 0` trên BTC; luôn vào LONG ngay từ nến 1 và không có điều kiện thoát lệnh. Theo quy tắc cốt lõi 'Unknown semantics remain blocked, not guessed', không tự bịa đặt luật thay thế. |
| `cb0b6e0f12e7` | U1_BTC_1h_Alpha | f9292fff | Biểu thức điều kiện hằng số `close > 0` trên BTC; luôn vào LONG ngay từ nến 1 và không có điều kiện thoát lệnh. Theo quy tắc cốt lõi 'Unknown semantics remain blocked, not guessed', không tự bịa đặt luật thay thế. |
| `d0518c0cca14` | U4_BTC_1h_Different_Window | f4ded671 | Biểu thức điều kiện hằng số `close > 1` trên BTC; luôn vào LONG và không có điều kiện thoát lệnh. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `e9a9a5b44d03` | U2_ETH_15m_Alpha | 95f7a5a4 | Biểu thức điều kiện hằng số `close > 10` trên ETH; luôn vào LONG và không có điều kiện thoát lệnh. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `ee0cf7f58f94` | U2_ETH_15m_Alpha | 97cac501 | Biểu thức điều kiện hằng số `close > 10` trên ETH; luôn vào LONG và không có điều kiện thoát lệnh. Phân loại BLOCKED_UNKNOWN_INTENT. |
| `fd16df3d0a3f` | U3_BTC_Small_Alpha | d836143a | Biểu thức điều kiện bất khả thi `close < 0` trên giá thị trường BTC; không bao giờ sinh tín hiệu giao dịch. Phân loại BLOCKED_UNKNOWN_INTENT. |

## 6. ĐỀ XUẤT BƯỚC TIẾP THEO (NEXT STEPS)

1. **Bảo toàn dữ liệu user:** Giữ nguyên trạng 100% kho dữ liệu gốc và 27 alpha bị chặn; không can thiệp cho đến khi có căn cứ ý đồ từ chủ sở hữu.
2. **Không kết luận vội vã:** Báo cáo này đóng vai trò là cột mốc đo lường baseline ban đầu. Không sử dụng kết quả này để tuyên bố pass hoặc sẵn sàng giao dịch.
3. **Kế hoạch Nghiên cứu Tiến hóa có Kiểm soát:**
   - Tạo fork nghiên cứu độc lập (`research_candidate_v1`), không ghi đè kho user.
   - Chạy các lượt đối chứng (counterfactual runs) để kiểm tra giả thuyết fee drag và stop-loss whipsaw.
   - Áp dụng kiểm định Walk-Forward đa khung thời gian và bảo vệ tập dữ liệu Holdout độc lập.
