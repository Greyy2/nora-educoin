# TECHNICAL DRY-RUN WFA ĐỘC LẬP & MONTE CARLO (25 ĐỐI TƯỢNG)

*Ngày thực hiện: 2026-10-30 07:18 UTC | Chạy Engine Độc Lập Từng Fold*

> [!IMPORTANT]
> **TRẠNG THÁI: CHƯA PHẢI KẾT QUẢ FORMAL / KHÔNG DÙNG ĐỂ PROMOTE HOẶC LOẠI ALPHA:**
> - Mỗi Fold được chạy độc lập với preload 20 ngày và `close_at_end = True`; các readiness gate và cohort sign-off vẫn phải đóng trước khi diễn giải.
> - Sharpe được tính chuẩn xác trên chuỗi lợi suất vốn ngày (Daily Equity Returns MTM 365 ngày).
> - Monte Carlo mô hình hóa tăng trưởng lãi kép (Compounded Equity Resampling) với 10,000 kịch bản.
> - Phân loại nghiêm ngặt theo tiêu chí tiền đăng kiểm Section 7.

## 1. Bảng Tổng Hợp Kết Quả WFA & Monte Carlo Chính Thức
| STT | ID Alpha / Leg | Phân Loại | Lệnh OOS | Folds Lãi | OOS Ret% | OOS MDD% | Daily Sharpe | P(MDD≥15%) | P(MDD≥20%) | Disposition tạm thời | Lý Do |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | `kema_long` | FIXED_PARAM_ROLLING_OOS | 28 | 0/3 Folds Positive | -0.54% | 5.81% | -0.07 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 02 | `kema_short` | FIXED_PARAM_ROLLING_OOS | 29 | 0/3 Folds Positive | -2.10% | 4.02% | -0.40 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (29) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 03 | `sideway_long` | LOW_SAMPLE_CRITICAL | 2 | 1/3 Folds Positive | -0.12% | 0.65% | -0.10 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (2) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 04 | `sideway_short` | LOW_SAMPLE_CRITICAL | 2 | 2/3 Folds Positive | +0.54% | 0.03% | 0.91 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (2) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 05 | `dca_long` | FIXED_PARAM_ROLLING_OOS | 59 | 2/3 Folds Positive | -0.15% | 1.26% | -0.12 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-0.15%); Daily Sharpe thấp (-0.12 < 0.8) |
| 06 | `dca_short` | FIXED_PARAM_ROLLING_OOS | 43 | 3/3 Folds Positive | +0.44% | 0.54% | 0.54 | 0.0% | 0.0% | 🔴 **REJECT** | Daily Sharpe thấp (0.54 < 0.8) |
| 07 | `combo_6_system_legs` | PORTFOLIO_COMBO | 66 | 1/3 Folds Positive | +2.38% | 4.65% | 0.36 | 0.0% | 0.0% | 🟣 COMBO_SEPARATE | Đánh giá cấp danh mục độc lập; cấm xếp hạng cùng các alpha đơn lẻ. |
| 08 | `efa90f74cd08_v2` | FIXED_PARAM_ROLLING_OOS | 28 | 1/3 Folds Positive | -1.42% | 3.10% | -0.50 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (28) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 09 | `18e87aa868ad_v2` | FIXED_PARAM_ROLLING_OOS | 33 | 1/3 Folds Positive | -1.03% | 2.97% | -0.38 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-1.03%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.38 < 0.8) |
| 10 | `33312a2f4dfc_v2` | FIXED_PARAM_ROLLING_OOS | 27 | 1/3 Folds Positive | -0.31% | 2.50% | -0.10 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (27) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 11 | `okx_01pp` | PROXY_ENTRY_RESEARCH_ONLY | 709 | 0/3 Folds Positive | -7.64% | 7.86% | -2.84 | 0.0% | 0.0% | 🔵 PROXY_NO_DECISION | Top Agent chỉ có tham số thoát lệnh từ OKX, điều kiện vào lệnh là proxy nghiên cứu; chỉ mang tính khảo sát kỹ thuật. |
| 12 | `okx_auroraxwt` | PROXY_ENTRY_RESEARCH_ONLY | 352 | 0/3 Folds Positive | -25.54% | 25.77% | -3.48 | 59.5% | 10.1% | 🔵 PROXY_NO_DECISION | Top Agent chỉ có tham số thoát lệnh từ OKX, điều kiện vào lệnh là proxy nghiên cứu; chỉ mang tính khảo sát kỹ thuật. |
| 13 | `okx_dark_wood_dahlia` | PROXY_ENTRY_RESEARCH_ONLY | 1284 | 0/3 Folds Positive | -12.93% | 12.99% | -4.09 | 0.0% | 0.0% | 🔵 PROXY_NO_DECISION | Top Agent chỉ có tham số thoát lệnh từ OKX, điều kiện vào lệnh là proxy nghiên cứu; chỉ mang tính khảo sát kỹ thuật. |
| 14 | `edu_canonical_beginner_dual_ema` | FIXED_PARAM_ROLLING_OOS | 411 | 0/3 Folds Positive | -8.56% | 9.55% | -1.28 | 0.1% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-8.56%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.28 < 0.8) |
| 15 | `edu_canonical_advanced_volatility_breakout` | FIXED_PARAM_ROLLING_OOS | 59 | 2/3 Folds Positive | -0.57% | 4.01% | -0.14 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-0.57%); Daily Sharpe thấp (-0.14 < 0.8) |
| 16 | `026f43441cb2` | FIXED_PARAM_ROLLING_OOS | 202 | 1/3 Folds Positive | -7.54% | 7.90% | -1.61 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-7.54%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-1.61 < 0.8) |
| 17 | `0873864b8db7` | LOW_SAMPLE_CRITICAL | 20 | 0/3 Folds Positive | -11.12% | 11.12% | -0.99 | 5.8% | 0.4% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (20) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 18 | `090730ae35b8` | FIXED_PARAM_ROLLING_OOS | 10 | 1/3 Folds Positive | +3.74% | 9.93% | 0.29 | 3.1% | 0.3% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (10) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 19 | `0bf936687964` | LOW_SAMPLE_CRITICAL | 0 | 0/3 Folds Positive | +0.00% | 0.00% | 0.00 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (0) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 20 | `0d51ba8d2012` | FIXED_PARAM_ROLLING_OOS | 15 | 1/3 Folds Positive | -3.01% | 5.35% | -0.54 | 0.0% | 0.0% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (15) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 21 | `138df68946ad` | FIXED_PARAM_ROLLING_OOS | 445 | 0/3 Folds Positive | -6.86% | 8.33% | -1.52 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-6.86%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.52 < 0.8) |
| 22 | `14e3b934b1e5` | FIXED_PARAM_ROLLING_OOS | 38 | 1/3 Folds Positive | -2.21% | 3.17% | -0.48 | 0.0% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-2.21%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.48 < 0.8) |
| 23 | `15567e02a806` | LOW_SAMPLE_CRITICAL | 4 | 1/3 Folds Positive | +11.14% | 14.48% | 0.41 | 32.6% | 14.8% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (4) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 24 | `18e87aa868ad` | FIXED_PARAM_ROLLING_OOS | 12 | 1/3 Folds Positive | -3.44% | 10.74% | -0.22 | 7.6% | 1.1% | ⚪ INSUFFICIENT_SAMPLE | Tổng số lệnh OOS gộp (12) < 30 lệnh tối thiểu theo Phương án A đã chọn. |
| 25 | `1a1a4389a821` | FIXED_PARAM_ROLLING_OOS | 1019 | 0/3 Folds Positive | -13.41% | 14.23% | -2.71 | 0.2% | 0.0% | 🔴 **REJECT** | Lỗ OOS gộp (-13.41%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.71 < 0.8) |

## 2. Thống Kê Phân Bổ Danh Mục Sau Lọc
- **🟢 KEEP (Alpha đạt chuẩn duy trì)**: 0 alphas
- **🟡 REVIEW (Vùng biên cần theo dõi)**: 0 alphas
- **🔴 REJECT (disposition tạm thời, không phải loại bỏ)**: 9 alphas
- **⚪ INSUFFICIENT_SAMPLE (< 30 lệnh OOS gộp)**: 12 alphas
- **⚫ NOT_APPLICABLE (structural label cần cohort xác minh)**: 0 bài tập EDU
- **🔵 RESEARCH_PROXY_NO_DECISION**: 3 alphas
- **🟣 PORTFOLIO_COMBO_EVALUATED_SEPARATELY**: 1 combo