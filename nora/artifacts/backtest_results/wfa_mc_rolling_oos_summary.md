# BÁO CÁO DRY-RUN HẠ TẦNG: ROLLING OOS & MONTE CARLO (NON-DECISION DIAGNOSTICS)

*Ngày thực hiện: 2026-10-29 09:27 UTC | Mẫu số: 25 Đối Tượng Đóng Băng*

> [!CAUTION]
> **RANH GIỚI NGHIỆM THU: DRY-RUN HẠ TẦNG KỸ THUẬT — KHÔNG DÙNG RA QUYẾT ĐỊNH ALPHA**
> - Báo cáo này kiểm tra thông tuyến thuật toán tính toán Rolling OOS, Block Bootstrap Monte Carlo và DSR.
> - Folds hiện tại được cắt từ raw ledger toàn kỳ theo `enter_time`, chưa phải rerun engine riêng cho từng fold (cross-boundary trades chưa được hạch toán theo thời gian thực).
> - Sharpe là Trade PnL proxy ước lượng thô; Monte Carlo resample PnL USD danh nghĩa trên vốn cố định, không mô hình hóa dynamic sizing/compounding.
> - Tuyệt đối **KHÔNG CÓ PHÁN QUYẾT KEEP/REJECT**; cấm dùng kết quả này để loại bỏ, chẩn đoán hay tiến hóa alpha.
> - Mọi gates chính thức (Master Risk runtime clamp, Calibrated costs, Historical funding) vẫn **BỊ KHÓA (BLOCKED)**; kết quả chính thức sẽ được chạy lại khi các gates được đóng.

## 1. Bảng Tổng Hợp Chẩn Đoán Kỹ Thuật Từng Alpha (25 Đối Tượng)
| STT | ID Alpha / Leg | Phân Loại Nguồn | Lệnh OOS Gộp | Folds Lãi | OOS Ret% | OOS MDD% | Sharpe Proxy (Trade) | DSR Status | P(Ruin>15%) | Trạng Thái Dry-Run |
|---|---|---|---|---|---|---|---|---|---|---|
| 01 | `kema_long` | FIXED_PARAM_ROLLING_OOS | 28 | 0/3 Folds Positive | -4.02% | 4.38% | -1.50 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | ⚪ INSUFFICIENT_SAMPLE |
| 02 | `kema_short` | FIXED_PARAM_ROLLING_OOS | 29 | 1/3 Folds Positive | -1.82% | 2.48% | -0.60 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | ⚪ INSUFFICIENT_SAMPLE |
| 03 | `sideway_long` | LOW_SAMPLE_CRITICAL | 2 | 1/3 Folds Positive | -0.18% | 0.62% | -0.13 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | ⚪ INSUFFICIENT_SAMPLE |
| 04 | `sideway_short` | LOW_SAMPLE_CRITICAL | 2 | 2/3 Folds Positive | +0.54% | 0.00% | 1.35 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | ⚪ INSUFFICIENT_SAMPLE |
| 05 | `dca_long` | FIXED_PARAM_ROLLING_OOS | 59 | 2/3 Folds Positive | -0.21% | 0.97% | -0.22 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | 🟡 CHẨN ĐOÁN KỸ THUẬT (NON-DECISION) |
| 06 | `dca_short` | FIXED_PARAM_ROLLING_OOS | 44 | 3/3 Folds Positive | +0.51% | 0.52% | 0.65 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | 🟡 CHẨN ĐOÁN KỸ THUẬT (NON-DECISION) |
| 07 | `combo_6_system_legs` | PORTFOLIO_COMBO | 67 | 2/3 Folds Positive | -2.28% | 3.66% | -0.79 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | 🟣 COMBO_SEPARATE |
| 08 | `efa90f74cd08_v2` | FIXED_PARAM_ROLLING_OOS | 25 | 1/3 Folds Positive | -1.53% | 2.07% | -1.04 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | ⚪ INSUFFICIENT_SAMPLE |
| 09 | `18e87aa868ad_v2` | FIXED_PARAM_ROLLING_OOS | 31 | 1/3 Folds Positive | -1.39% | 2.28% | -0.75 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | 🟡 CHẨN ĐOÁN KỸ THUẬT (NON-DECISION) |
| 10 | `33312a2f4dfc_v2` | FIXED_PARAM_ROLLING_OOS | 25 | 0/3 Folds Positive | -0.79% | 1.90% | -0.38 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | ⚪ INSUFFICIENT_SAMPLE |
| 11 | `okx_01pp` | PROXY_ENTRY_RESEARCH_ONLY | 709 | 0/3 Folds Positive | -2.94% | 3.06% | -2.81 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | 🔵 PROXY_NO_DECISION |
| 12 | `okx_auroraxwt` | PROXY_ENTRY_RESEARCH_ONLY | 298 | 0/3 Folds Positive | -17.00% | 17.00% | -5.19 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 84.6% | 🔵 PROXY_NO_DECISION |
| 13 | `okx_dark_wood_dahlia` | PROXY_ENTRY_RESEARCH_ONLY | 1282 | 0/3 Folds Positive | -6.88% | 6.91% | -5.13 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | 🔵 PROXY_NO_DECISION |
| 14 | `edu_canonical_beginner_dual_ema` | FIXED_PARAM_ROLLING_OOS | 411 | 0/3 Folds Positive | -3.48% | 4.11% | -1.22 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | 🟡 CHẨN ĐOÁN KỸ THUẬT (NON-DECISION) |
| 15 | `edu_canonical_advanced_volatility_breakout` | FIXED_PARAM_ROLLING_OOS | 59 | 0/3 Folds Positive | -1.31% | 2.84% | -0.65 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | 🟡 CHẨN ĐOÁN KỸ THUẬT (NON-DECISION) |
| 16 | `026f43441cb2` | EXCLUDED_STRUCTURAL_NO_SIGNAL_LOGIC | 0 | 0/3 Folds Positive | +0.00% | 0.00% | 0.00 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | N/A | ⚫ NOT_APPLICABLE |
| 17 | `0873864b8db7` | LOW_SAMPLE_CRITICAL | 0 | 0/3 Folds Positive | +0.00% | 0.00% | 0.00 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | N/A | ⚪ INSUFFICIENT_SAMPLE |
| 18 | `090730ae35b8` | FIXED_PARAM_ROLLING_OOS | 10 | 1/3 Folds Positive | -9.33% | 19.46% | -0.33 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 83.9% | ⚪ INSUFFICIENT_SAMPLE |
| 19 | `0bf936687964` | EXCLUDED_STRUCTURAL_NO_SIGNAL_LOGIC | 0 | 0/3 Folds Positive | +0.00% | 0.00% | 0.00 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | N/A | ⚫ NOT_APPLICABLE |
| 20 | `0d51ba8d2012` | FIXED_PARAM_ROLLING_OOS | 15 | 1/3 Folds Positive | -1.29% | 1.57% | -0.84 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | ⚪ INSUFFICIENT_SAMPLE |
| 21 | `138df68946ad` | EXCLUDED_STRUCTURAL_NO_SIGNAL_LOGIC | 0 | 0/3 Folds Positive | +0.00% | 0.00% | 0.00 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | N/A | ⚫ NOT_APPLICABLE |
| 22 | `14e3b934b1e5` | FIXED_PARAM_ROLLING_OOS | 37 | 0/3 Folds Positive | -2.39% | 2.46% | -1.49 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 0.0% | 🟡 CHẨN ĐOÁN KỸ THUẬT (NON-DECISION) |
| 23 | `15567e02a806` | LOW_SAMPLE_CRITICAL | 5 | 2/3 Folds Positive | -4.79% | 17.49% | -0.16 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 72.5% | ⚪ INSUFFICIENT_SAMPLE |
| 24 | `18e87aa868ad` | FIXED_PARAM_ROLLING_OOS | 12 | 0/3 Folds Positive | -22.25% | 22.25% | -0.74 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | 87.0% | ⚪ INSUFFICIENT_SAMPLE |
| 25 | `1a1a4389a821` | EXCLUDED_STRUCTURAL_NO_SIGNAL_LOGIC | 0 | 0/3 Folds Positive | +0.00% | 0.00% | 0.00 | DSR_UNAVAILABLE_TRIALS_UNAUDITED | N/A | ⚫ NOT_APPLICABLE |

## 2. Thống Kê Phân Bổ Trạng Thái
- **🟡 DRY_RUN_DIAGNOSTIC_ONLY (Đủ mẫu để chẩn đoán, không phán quyết)**: 6 alphas
- **⚪ INSUFFICIENT_SAMPLE (< 30 lệnh OOS gộp)**: 11 alphas
- **⚫ NOT_APPLICABLE (Buy & Hold 1 trade không có logic bán)**: 4 bài tập EDU
- **🔵 RESEARCH_PROXY_NO_DECISION (Top Agent chỉ có exit proxy)**: 3 alphas
- **🟣 PORTFOLIO_COMBO_EVALUATED_SEPARATELY (Rổ danh mục vốn chung)**: 1 combo
- **TUYỆT ĐỐI KHÔNG GÁN NHÃN `KEEP` HOẶC `REJECT` TRONG ĐỢT DRY-RUN NÀY**.

## 3. Các Giới Hạn Phương Pháp Luận Cần Giải Quyết
1. **Lỗi cắt fold theo enter_time**: Các fold hiện tại được cắt từ raw ledger toàn kỳ theo enter_time, chưa phải rerun engine riêng cho từng fold. Các lệnh mở cuối fold nhưng đóng ở fold sau được tính toàn bộ PnL vào fold mở lệnh; các lệnh mở trước OOS fold đóng trong fold bị bỏ qua.
2. **Chỉ số Sharpe**: Được tính trên PnL USD mỗi trade với annualization ước lượng, chưa phải chuỗi lợi suất vốn theo ngày (Daily Equity Returns).
3. **Monte Carlo**: Resample PnL USD danh nghĩa trên vốn ban đầu cố định $10,000, chưa mô hình hóa sizing theo % equity động (khi drawdown thì margin giảm, khi lãi thì compounding).
4. **DSR**: Số trial thực tế ($N_{\text{trials}}$) chưa được kiểm kê; 72 biến thể universe đang ở trạng thái BLOCKED_NOT_EVALUATED. Toàn bộ giá trị số DSR (bao gồm số 0.0 thăm dò của `dca_short`) đã bị loại bỏ khỏi bảng chẩn đoán để ngăn chặn mọi ngộ nhận phán quyết.
5. **Khảo sát độ nhạy Block Length**: Phân tích độ nhạy sơ bộ với $b \in \{3, 5, 10\}$ cho thấy độ biến thiên của phân phối khi thay đổi độ dài khối; chưa đủ cơ sở để kết luận về tính chất tương quan chuỗi hay chế độ thị trường.
6. **Kết luận**: **Chưa lọc alpha tệ, chưa chẩn đoán nguyên nhân và chưa tiến hóa dựa trên bảng dry-run này**.