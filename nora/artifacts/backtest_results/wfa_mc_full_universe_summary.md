# INVALIDATED — Historical WFA/Monte Carlo Technical Dry-Run (93 records)

> **INVALIDATED_SOURCE_ID_COLLISION — DO NOT USE ANY METRIC OR DISPOSITION BELOW.** The run keyed user source code by bare alpha ID; colliding COIN/EDU IDs (`18e87aa868ad`, `33312a2f4dfc`) could have executed the wrong product's source. This invalidates the entire report, not only the two colliding rows. The values below are retained solely as historical run output; they have not been corrected or rerun.

*Ngày thực hiện: 2026-10-30 10:00 UTC | Git: `d7d103b0` | Chạy Engine COIN Nautilus Từng Fold*

> [!IMPORTANT]
> **TRẠNG THÁI: TECHNICAL DRY-RUN / KHÔNG DÙNG ĐỂ CHÍNH THỨC XÓA HOẶC PROMOTE ALPHA:**
> - Toàn bộ Alpha COIN và EDU đều được chạy qua Engine COIN với `close_at_end = True` và warmup 20 ngày.
> - Monte Carlo áp dụng Stationary Bootstrap (Politis & Romano 1994) trên chuỗi lợi suất ngày ghép lãi kép 10,000 lần.
> - Phân loại theo tiêu chí tiền đăng kiểm Section 7 (Phương án A: N_OOS >= 30 lệnh).

## 1. Bảng Tổng Hợp Xếp Hạng Toàn Bộ Alpha
| STT | ID Alpha / Leg | Nhóm | Lệnh OOS | Folds Lãi | OOS Ret% | OOS MDD% | Daily Sharpe | P(MDD≥15%) | P(MDD≥20%) | Disposition | Lý Do Chi Tiết |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | `kema_long` | COIN System Leg | 28 | 0/3 Folds Positive | -0.54% | 5.81% | -0.07 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 02 | `kema_short` | COIN System Leg | 29 | 0/3 Folds Positive | -2.1% | 4.02% | -0.4 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (29) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 03 | `sideway_long` | COIN System Leg | 2 | 1/3 Folds Positive | -0.12% | 0.65% | -0.1 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (2) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 04 | `sideway_short` | COIN System Leg | 2 | 2/3 Folds Positive | 0.54% | 0.03% | 0.91 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (2) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 05 | `dca_long` | COIN System Leg | 59 | 2/3 Folds Positive | -0.15% | 1.26% | -0.12 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-0.15%); Daily Sharpe thấp (-0.12 < 0.8) |
| 06 | `dca_short` | COIN System Leg | 43 | 3/3 Folds Positive | 0.44% | 0.54% | 0.54 | 0.0% | 0.0% | 🔴 **REJECT** | Daily Sharpe thấp (0.54 < 0.8) |
| 07 | `combo_6_system_legs` | COIN Portfolio | 66 | 1/3 Folds Positive | 2.38% | 4.65% | 0.36 | 0.0% | 0.0% | 🟣 COMBO_SEPARATE | Đánh giá cấp danh mục độc lập; cấm xếp hạng cùng các alpha đơn lẻ. |
| 08 | `combo_top3` | COIN Portfolio | 81 | 1/3 Folds Positive | 3.36% | 3.43% | 0.54 | 0.0% | 0.0% | 🟣 COMBO_SEPARATE | Đánh giá cấp danh mục độc lập; cấm xếp hạng cùng các alpha đơn lẻ. |
| 09 | `18e87aa868ad` | COIN User | 67 | 1/3 Folds Positive | -9.85% | 22.78% | -0.16 | 67.4% | 53.8% | 🔴 **REJECT** | Lỗ OOS gộp (-9.85%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.16 < 0.8); MDD sâu (22.78% > 20%); P(MDD≥15%) cao (67.4% > 10%) |
| 10 | `18e87aa868ad_v2` | COIN User V2 | 33 | 1/3 Folds Positive | -1.03% | 2.97% | -0.38 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-1.03%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.38 < 0.8) |
| 11 | `33312a2f4dfc` | COIN User | 57 | 1/3 Folds Positive | -7.8% | 23.21% | -0.11 | 64.4% | 51.7% | 🔴 **REJECT** | Lỗ OOS gộp (-7.80%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.11 < 0.8); MDD sâu (23.21% > 20%); P(MDD≥15%) cao (64.4% > 10%) |
| 12 | `33312a2f4dfc_v2` | COIN User V2 | 27 | 1/3 Folds Positive | -0.31% | 2.5% | -0.1 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (27) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 13 | `alpha_proxima_research` | COIN Native Research | N/A | NOT_RUN | N/A | N/A | N/A | N/A | N/A | 🔵 NATIVE_RESEARCH_NO_DECISION | Native research alpha is excluded until its live REST warmup is replaced by a deterministic catalog/replay data adapter. |
| 14 | `efa90f74cd08` | COIN User | 112 | 1/3 Folds Positive | -6.71% | 19.36% | -0.41 | 27.0% | 8.5% | 🔴 **REJECT** | Lỗ OOS gộp (-6.71%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.41 < 0.8); P(MDD≥15%) cao (27.0% > 10%) |
| 15 | `efa90f74cd08_v2` | COIN User V2 | 28 | 1/3 Folds Positive | -1.42% | 3.1% | -0.5 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 16 | `okx_01pp` | COIN Top Agent | 709 | 0/3 Folds Positive | -7.64% | 7.86% | -2.84 | 0.0% | 0.0% | 🔵 PROXY_NO_DECISION | Top Agent chỉ có tham số thoát lệnh từ OKX, điều kiện vào lệnh là proxy nghiên cứu; chỉ mang tính khảo sát kỹ thuật. |
| 17 | `okx_auroraxwt` | COIN Top Agent | 352 | 0/3 Folds Positive | -25.54% | 25.77% | -3.48 | 59.5% | 10.1% | 🔵 PROXY_NO_DECISION | Top Agent chỉ có tham số thoát lệnh từ OKX, điều kiện vào lệnh là proxy nghiên cứu; chỉ mang tính khảo sát kỹ thuật. |
| 18 | `okx_dark_wood_dahlia` | COIN Top Agent | 1284 | 0/3 Folds Positive | -12.93% | 12.99% | -4.09 | 0.0% | 0.0% | 🔵 PROXY_NO_DECISION | Top Agent chỉ có tham số thoát lệnh từ OKX, điều kiện vào lệnh là proxy nghiên cứu; chỉ mang tính khảo sát kỹ thuật. |
| 19 | `edu_canonical_beginner_dual_ema` | EDU Canonical | 411 | 0/3 Folds Positive | -8.56% | 9.55% | -1.28 | 0.1% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-8.56%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.28 < 0.8) |
| 20 | `edu_canonical_advanced_volatility_breakout` | EDU Canonical | 59 | 2/3 Folds Positive | -0.57% | 4.01% | -0.14 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-0.57%); Daily Sharpe thấp (-0.14 < 0.8) |
| 21 | `026f43441cb2` | EDU User | 202 | 1/3 Folds Positive | -7.54% | 7.9% | -1.61 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-7.54%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-1.61 < 0.8) |
| 22 | `04e66d1c63d7` | EDU User | 28 | 0/3 Folds Positive | -7.52% | 10.85% | -0.7 | 6.6% | 0.9% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 23 | `0873864b8db7` | EDU User | 73 | 3/3 Folds Positive | 71.33% | 20.92% | 0.85 | 20.1% | 6.1% | 🔴 **REJECT** | MDD sâu (20.92% > 20%); P(MDD≥15%) cao (20.1% > 10%) |
| 24 | `090730ae35b8` | EDU User | 57 | 1/3 Folds Positive | -8.1% | 24.06% | -0.1 | 65.8% | 53.1% | 🔴 **REJECT** | Lỗ OOS gộp (-8.10%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.10 < 0.8); MDD sâu (24.06% > 20%); P(MDD≥15%) cao (65.8% > 10%) |
| 25 | `0bf936687964` | EDU User | 0 | 0/3 Folds Positive | 0.0% | 0.0% | 0.0 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (0) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 26 | `0d51ba8d2012` | EDU User | 156 | 1/3 Folds Positive | -8.96% | 27.51% | -0.22 | 73.7% | 49.8% | 🔴 **REJECT** | Lỗ OOS gộp (-8.96%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.22 < 0.8); MDD sâu (27.51% > 20%); P(MDD≥15%) cao (73.7% > 10%) |
| 27 | `138df68946ad` | EDU User | 445 | 0/3 Folds Positive | -6.86% | 8.33% | -1.52 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-6.86%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.52 < 0.8) |
| 28 | `14e3b934b1e5` | EDU User | 627 | 0/3 Folds Positive | -26.12% | 31.62% | -1.25 | 80.3% | 56.0% | 🔴 **REJECT** | Lỗ OOS gộp (-26.12%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.25 < 0.8); MDD sâu (31.62% > 20%); P(MDD≥15%) cao (80.3% > 10%) |
| 29 | `15567e02a806` | EDU User | 37 | 2/3 Folds Positive | -23.82% | 37.48% | -0.3 | 97.3% | 89.5% | 🔴 **REJECT** | Lỗ OOS gộp (-23.82%); Daily Sharpe thấp (-0.30 < 0.8); MDD sâu (37.48% > 20%); P(MDD≥15%) cao (97.3% > 10%) |
| 30 | `1a1a4389a821` | EDU User | 1019 | 0/3 Folds Positive | -13.41% | 14.23% | -2.71 | 0.2% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-13.41%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.71 < 0.8) |
| 31 | `1e4c0b9f84f7` | EDU User | 1200 | 0/3 Folds Positive | -15.27% | 16.37% | -3.54 | 0.5% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-15.27%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-3.54 < 0.8) |
| 32 | `214ea8fdf3e6` | EDU User | 694 | 0/3 Folds Positive | -12.41% | 12.75% | -2.64 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-12.41%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.64 < 0.8) |
| 33 | `234e6df02e37` | EDU User | 3436 | 0/3 Folds Positive | -31.77% | 32.15% | -5.45 | 95.9% | 49.0% | 🔴 **REJECT** | Lỗ OOS gộp (-31.77%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-5.45 < 0.8); MDD sâu (32.15% > 20%); P(MDD≥15%) cao (95.9% > 10%) |
| 34 | `270e6e28416f` | EDU User | 74 | 2/3 Folds Positive | -7.61% | 43.99% | 0.07 | 93.3% | 85.5% | 🔴 **REJECT** | Lỗ OOS gộp (-7.61%); Daily Sharpe thấp (0.07 < 0.8); MDD sâu (43.99% > 20%); P(MDD≥15%) cao (93.3% > 10%) |
| 35 | `2e41b2cfa24d` | EDU User | 569 | 0/3 Folds Positive | -9.74% | 10.3% | -2.34 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-9.74%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.34 < 0.8) |
| 36 | `303d4b713dda` | EDU User | 57 | 1/3 Folds Positive | -8.18% | 23.5% | -0.12 | 65.0% | 52.2% | 🔴 **REJECT** | Lỗ OOS gộp (-8.18%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.12 < 0.8); MDD sâu (23.50% > 20%); P(MDD≥15%) cao (65.0% > 10%) |
| 37 | `342d4c6f38d5` | EDU User | 28 | 0/3 Folds Positive | -7.52% | 10.85% | -0.7 | 6.6% | 0.9% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 38 | `3cfcc2d296a2` | EDU User | 270 | 0/3 Folds Positive | -26.74% | 30.11% | -1.21 | 84.8% | 64.0% | 🔴 **REJECT** | Lỗ OOS gộp (-26.74%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.21 < 0.8); MDD sâu (30.11% > 20%); P(MDD≥15%) cao (84.8% > 10%) |
| 39 | `4b538efbcd2f` | EDU User | 28 | 0/3 Folds Positive | -7.52% | 10.85% | -0.7 | 6.6% | 0.9% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 40 | `4f28285aa44c` | EDU User | 7 | 0/3 Folds Positive | -4.85% | 12.03% | -0.53 | 4.6% | 0.8% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (7) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 41 | `53b031ab4a02` | EDU User | 23 | 1/3 Folds Positive | -4.5% | 11.55% | -0.33 | 9.2% | 1.7% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (23) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 42 | `541c55834f56` | EDU User | 289 | 0/3 Folds Positive | -33.0% | 36.03% | -1.32 | 91.1% | 75.5% | 🔴 **REJECT** | Lỗ OOS gộp (-33.00%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.32 < 0.8); MDD sâu (36.03% > 20%); P(MDD≥15%) cao (91.1% > 10%) |
| 43 | `571474a18f55` | EDU User | 0 | 0/3 Folds Positive | 0.0% | 0.0% | 0.0 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (0) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 44 | `59420fcec1be` | EDU User | 28 | 0/3 Folds Positive | -7.52% | 10.85% | -0.7 | 6.6% | 0.9% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 45 | `5e52d3fdf71f` | EDU User | 343 | 0/3 Folds Positive | -27.83% | 31.59% | -2.04 | 72.6% | 44.0% | 🔴 **REJECT** | Lỗ OOS gộp (-27.83%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.04 < 0.8); MDD sâu (31.59% > 20%); P(MDD≥15%) cao (72.6% > 10%) |
| 46 | `6055aa8f661e` | EDU User | 75 | 1/3 Folds Positive | -4.07% | 13.37% | -0.14 | 22.1% | 5.3% | 🔴 **REJECT** | Lỗ OOS gộp (-4.07%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.14 < 0.8); P(MDD≥15%) cao (22.1% > 10%) |
| 47 | `616e1b8cbc88` | EDU User | 2690 | 0/3 Folds Positive | -28.33% | 28.59% | -6.09 | 85.1% | 14.9% | 🔴 **REJECT** | Lỗ OOS gộp (-28.33%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-6.09 < 0.8); MDD sâu (28.59% > 20%); P(MDD≥15%) cao (85.1% > 10%) |
| 48 | `61bd7e012c21` | EDU User | 28 | 0/3 Folds Positive | -7.52% | 10.85% | -0.7 | 6.6% | 0.9% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 49 | `64b657c8de8e` | EDU User | 0 | 0/3 Folds Positive | 0.0% | 0.0% | 0.0 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (0) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 50 | `6608376d73ff` | EDU User | 23 | 1/3 Folds Positive | -4.5% | 11.55% | -0.33 | 9.2% | 1.7% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (23) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 51 | `6afa7f774655` | EDU User | 47 | 0/3 Folds Positive | -14.82% | 15.6% | -1.94 | 9.1% | 1.0% | 🔴 **REJECT** | Lỗ OOS gộp (-14.82%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.94 < 0.8) |
| 52 | `6e51e396268f` | EDU User | 28 | 0/3 Folds Positive | -7.52% | 10.85% | -0.7 | 6.6% | 0.9% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 53 | `715e56a6dd33` | EDU User | 63 | 0/3 Folds Positive | -13.13% | 13.93% | -1.64 | 6.0% | 0.5% | 🔴 **REJECT** | Lỗ OOS gộp (-13.13%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.64 < 0.8) |
| 54 | `717c1890c59e` | EDU User | 50 | 2/3 Folds Positive | 9.61% | 29.43% | 0.32 | 86.4% | 67.3% | 🔴 **REJECT** | Daily Sharpe thấp (0.32 < 0.8); MDD sâu (29.43% > 20%); P(MDD≥15%) cao (86.4% > 10%) |
| 55 | `74f607263c5c` | EDU User | 354 | 1/3 Folds Positive | -3.61% | 6.32% | -0.74 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-3.61%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.74 < 0.8) |
| 56 | `7c1bf0a9686a` | EDU User | 598 | 0/3 Folds Positive | -11.27% | 12.04% | -2.62 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-11.27%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.62 < 0.8) |
| 57 | `7f3486d63ca8` | EDU User | 265 | 1/3 Folds Positive | -11.84% | 17.99% | -0.65 | 46.6% | 19.1% | 🔴 **REJECT** | Lỗ OOS gộp (-11.84%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.65 < 0.8); P(MDD≥15%) cao (46.6% > 10%) |
| 58 | `7f67e9aed0aa` | EDU User | 121 | 0/3 Folds Positive | -21.9% | 25.26% | -1.59 | 47.6% | 16.6% | 🔴 **REJECT** | Lỗ OOS gộp (-21.90%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.59 < 0.8); MDD sâu (25.26% > 20%); P(MDD≥15%) cao (47.6% > 10%) |
| 59 | `7f770ebe5ab5` | EDU User | 601 | 0/3 Folds Positive | -10.99% | 11.75% | -2.73 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-10.99%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.73 < 0.8) |
| 60 | `856ddc574ce7` | EDU User | 45 | 1/3 Folds Positive | 4.49% | 31.39% | 0.22 | 76.1% | 50.6% | 🔴 **REJECT** | Chỉ có 1/3 folds lãi; Daily Sharpe thấp (0.22 < 0.8); MDD sâu (31.39% > 20%); P(MDD≥15%) cao (76.1% > 10%) |
| 61 | `862e0c9eebbe` | EDU User | 39 | 0/3 Folds Positive | -8.45% | 22.97% | -0.28 | 52.7% | 27.0% | 🔴 **REJECT** | Lỗ OOS gộp (-8.45%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-0.28 < 0.8); MDD sâu (22.97% > 20%); P(MDD≥15%) cao (52.7% > 10%) |
| 62 | `89379cc0ab52` | EDU User | 205 | 0/3 Folds Positive | -23.24% | 28.51% | -1.28 | 65.8% | 36.8% | 🔴 **REJECT** | Lỗ OOS gộp (-23.24%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.28 < 0.8); MDD sâu (28.51% > 20%); P(MDD≥15%) cao (65.8% > 10%) |
| 63 | `8a47cdbcc942` | EDU User | 8 | 1/3 Folds Positive | 11.37% | 10.56% | 0.58 | 8.7% | 1.5% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (8) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 64 | `930294d28c45` | EDU User | 36 | 0/3 Folds Positive | -9.83% | 11.03% | -0.92 | 9.1% | 1.3% | 🔴 **REJECT** | Lỗ OOS gộp (-9.83%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-0.92 < 0.8) |
| 65 | `93edc7884cff` | EDU User | 28 | 0/3 Folds Positive | -7.52% | 10.85% | -0.7 | 6.6% | 0.9% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 66 | `9b86a200202a` | EDU User | 23 | 1/3 Folds Positive | -4.5% | 11.55% | -0.33 | 9.2% | 1.7% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (23) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 67 | `9eec3d61131d` | EDU User | 249 | 0/3 Folds Positive | -6.01% | 6.14% | -1.74 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-6.01%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.74 < 0.8) |
| 68 | `a4d6826fbbc6` | EDU User | 1297 | 0/3 Folds Positive | -14.44% | 15.54% | -2.97 | 0.7% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-14.44%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.97 < 0.8) |
| 69 | `a61e009cedcd` | EDU User | 28 | 0/3 Folds Positive | -7.52% | 10.85% | -0.7 | 6.6% | 0.9% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 70 | `a7d15861ca72` | EDU User | 28 | 0/3 Folds Positive | -7.52% | 10.85% | -0.7 | 6.6% | 0.9% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 71 | `af2bf88426c4` | EDU User | 272 | 0/3 Folds Positive | -5.5% | 6.72% | -1.24 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-5.50%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.24 < 0.8) |
| 72 | `b4b65cd3493f` | EDU User | 292 | 0/3 Folds Positive | -20.99% | 24.56% | -1.29 | 52.8% | 22.9% | 🔴 **REJECT** | Lỗ OOS gộp (-20.99%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.29 < 0.8); MDD sâu (24.56% > 20%); P(MDD≥15%) cao (52.8% > 10%) |
| 73 | `b5dcc380d5c8` | EDU User | 28 | 0/3 Folds Positive | -7.52% | 10.85% | -0.7 | 6.6% | 0.9% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 74 | `b96bafe57445` | EDU User | 17 | 0/3 Folds Positive | -9.81% | 10.64% | -1.08 | 6.0% | 0.9% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (17) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 75 | `bd234070bd7b` | EDU User | 87 | 0/3 Folds Positive | -5.13% | 5.39% | -1.71 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-5.13%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.71 < 0.8) |
| 76 | `be1174b24a44` | EDU User | 41 | 0/3 Folds Positive | -1.94% | 1.99% | -1.21 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-1.94%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.21 < 0.8) |
| 77 | `bf519617d973` | EDU User | 54 | 1/3 Folds Positive | 81.79% | 44.31% | 0.57 | 92.2% | 79.8% | 🔴 **REJECT** | Chỉ có 1/3 folds lãi; Daily Sharpe thấp (0.57 < 0.8); MDD sâu (44.31% > 20%); P(MDD≥15%) cao (92.2% > 10%) |
| 78 | `c33cc317bbeb` | EDU User | 182 | 0/3 Folds Positive | -33.51% | 33.68% | -2.69 | 81.7% | 53.9% | 🔴 **REJECT** | Lỗ OOS gộp (-33.51%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.69 < 0.8); MDD sâu (33.68% > 20%); P(MDD≥15%) cao (81.7% > 10%) |
| 79 | `ca1dece21d96` | EDU User | 23 | 1/3 Folds Positive | -4.5% | 11.55% | -0.33 | 9.2% | 1.7% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (23) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 80 | `cb0b6e0f12e7` | EDU User | 1032 | 0/3 Folds Positive | -11.85% | 12.85% | -2.29 | 0.2% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-11.85%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.29 < 0.8) |
| 81 | `cb750cb1eb10` | EDU User | 18 | 0/3 Folds Positive | -8.3% | 10.32% | -0.76 | 7.3% | 0.9% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (18) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 82 | `d0518c0cca14` | EDU User | 570 | 0/3 Folds Positive | -10.8% | 11.48% | -3.59 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-10.80%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-3.59 < 0.8) |
| 83 | `d07a33dd2875` | EDU User | 28 | 0/3 Folds Positive | -7.52% | 10.85% | -0.7 | 6.6% | 0.9% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 84 | `e14386758315` | EDU User | 23 | 1/3 Folds Positive | -4.5% | 11.55% | -0.33 | 9.2% | 1.7% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (23) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 85 | `e9a9a5b44d03` | EDU User | 69 | 0/3 Folds Positive | -8.43% | 21.0% | -0.37 | 39.7% | 15.7% | 🔴 **REJECT** | Lỗ OOS gộp (-8.43%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-0.37 < 0.8); MDD sâu (21.00% > 20%); P(MDD≥15%) cao (39.7% > 10%) |
| 86 | `ee0cf7f58f94` | EDU User | 54 | 0/3 Folds Positive | -10.16% | 26.83% | -0.29 | 65.3% | 39.6% | 🔴 **REJECT** | Lỗ OOS gộp (-10.16%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-0.29 < 0.8); MDD sâu (26.83% > 20%); P(MDD≥15%) cao (65.3% > 10%) |
| 87 | `ef59802613e9` | EDU User | 28 | 0/3 Folds Positive | -7.52% | 10.85% | -0.7 | 6.6% | 0.9% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 88 | `efb1fbe2db86` | EDU User | 57 | 1/3 Folds Positive | -7.8% | 23.21% | -0.11 | 64.4% | 51.7% | 🔴 **REJECT** | Lỗ OOS gộp (-7.80%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.11 < 0.8); MDD sâu (23.21% > 20%); P(MDD≥15%) cao (64.4% > 10%) |
| 89 | `f261549d9efa` | EDU User | 229 | 1/3 Folds Positive | -12.49% | 27.63% | -0.28 | 75.6% | 47.2% | 🔴 **REJECT** | Lỗ OOS gộp (-12.49%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.28 < 0.8); MDD sâu (27.63% > 20%); P(MDD≥15%) cao (75.6% > 10%) |
| 90 | `f4e211e9510d` | EDU User | 74 | 1/3 Folds Positive | -5.7% | 18.48% | -0.14 | 56.5% | 29.6% | 🔴 **REJECT** | Lỗ OOS gộp (-5.70%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.14 < 0.8); P(MDD≥15%) cao (56.5% > 10%) |
| 91 | `fa9587a97fa9` | EDU User | 50 | 1/3 Folds Positive | -43.75% | 53.55% | -0.31 | 97.9% | 93.8% | 🔴 **REJECT** | Lỗ OOS gộp (-43.75%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.31 < 0.8); MDD sâu (53.55% > 20%); P(MDD≥15%) cao (97.9% > 10%) |
| 92 | `fd16df3d0a3f` | EDU User | 241 | 0/3 Folds Positive | -7.82% | 8.87% | -2.2 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-7.82%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.20 < 0.8) |
| 93 | `ff025ca8e44b` | EDU User | 23 | 1/3 Folds Positive | -4.5% | 11.55% | -0.33 | 9.2% | 1.7% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (23) < 30 lệnh tối thiểu theo Phương án A đã chọn. |

## 2. Thống Kê Phân Bổ Toàn Bộ Danh Mục
- **🟢 KEEP (Alpha đạt chuẩn duy trì)**: 0 alphas
- **🟡 REVIEW (Vùng biên cần theo dõi)**: 0 alphas
- **🔴 REJECT (Alpha yếu kém - Disposition tạm thời)**: 56 alphas
- **⚪ INSUFFICIENT_SAMPLE (< 30 lệnh OOS gộp)**: 31 alphas
- **🔵 RESEARCH_PROXY_NO_DECISION**: 3 alphas
- **🔵 RESEARCH_NATIVE_NO_DECISION**: 1 alphas
- **🟣 PORTFOLIO_COMBO_EVALUATED_SEPARATELY**: 2 combos