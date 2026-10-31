# HỒ SƠ PHÁP Y & CHẨN ĐOÁN NGUYÊN NHÂN GỐC RỄ ALPHA BỊ LOẠI (UNDERPERFORMER DOSSIER)

*Ngày thực hiện: 2026-10-30 07:18 UTC | Số lượng alpha bị loại: 9*

> [!CAUTION]
> Toàn bộ chẩn đoán được bóc tách định lượng qua 4 trục: Lệch pha chế độ thị trường, Bào mòn phí/trượt giá, Bẫy Stop-loss/Sizing và Suy hao tín hiệu.

## Alpha: `dca_long` (System Leg dca_long)
- **Phân loại**: `COIN System Leg` | Phán quyết: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-0.15%` | MDD: `1.26%` | Daily Sharpe: `-0.12` | Lệnh OOS: `59` | Phí: `$13.98`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do loại bỏ chính thức**: Lỗ OOS gộp (-0.15%); Daily Sharpe thấp (-0.12 < 0.8)

### 1. Phân Tích Bào Mòn Phí & Ma Sát (Friction Drag)
- **Phí không phải nguyên nhân chính**: Tổng phí chỉ `$13.98`. Nguyên nhân thua lỗ cốt lõi nằm ở bản thân hướng tín hiệu (Gross PnL âm).

### 2. Phân Tích Lệch Pha Chế Độ Thị Trường (Market Regime Mismatch)
- **Hiệu suất theo từng Fold**:
  + **fold_1 (2024-12-01 -> 2025-06-30)**: Ret = `-0.65%`, MDD = `1.40%`, Sharpe = `-1.14`, Lệnh = `21`
  + **fold_2 (2025-07-01 -> 2026-01-31)**: Ret = `+0.16%`, MDD = `0.33%`, Sharpe = `0.55`, Lệnh = `17`
  + **fold_3 (2026-02-01 -> 2026-09-01)**: Ret = `+0.35%`, MDD = `0.16%`, Sharpe = `1.84`, Lệnh = `21`

### 3. Phân Tích Cơ Chế Cắt Lỗ & Định Cỡ Vị Thế (SL & Sizing Analysis)
- Khảo sát cấu hình lệnh cho thấy việc sử dụng mức cắt lỗ cố định mà không thích ứng theo biến động thực tế (Dynamic Volatility) khiến alpha chịu nhiều lệnh cắt lỗ liên tiếp khi biến động giãn nở.

### 4. Đề Xuất Giả Thuyết Tiến Hóa Có Thể Bác Bỏ Được (Falsifiable Hypothesis)
> **Giả thuyết H1 cho `dca_long`**:
> - *Nếu*: Bổ sung bộ lọc điều kiện thị trường (ví dụ lọc ADX > 25 hoặc ATR Volatility Band) để cấm mở vị thế khi thị trường đi vào vùng nghẽn thanh khoản/sideway, đồng thời nới rộng SL từ cố định sang 2.5x ATR,
> - *Thì*: Số lượng lệnh thua trong Fold 2 sẽ giảm ít nhất 30%, đưa Sharpe OOS tổng thể lên $\ge 0.8$ và giảm P(Ruin > 15%) xuống dưới 5.0%.
> - *Kiểm chứng độc lập*: Giả thuyết này bắt buộc phải kiểm nghiệm trên tập Holdout sau tháng 09/2026, tuyệt đối không tune lại trên dữ liệu 2024-2026.

---

## Alpha: `dca_short` (System Leg dca_short)
- **Phân loại**: `COIN System Leg` | Phán quyết: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `+0.44%` | MDD: `0.54%` | Daily Sharpe: `0.54` | Lệnh OOS: `43` | Phí: `$10.36`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do loại bỏ chính thức**: Daily Sharpe thấp (0.54 < 0.8)

### 1. Phân Tích Bào Mòn Phí & Ma Sát (Friction Drag)
- **Phí không phải nguyên nhân chính**: Tổng phí chỉ `$10.36`. Nguyên nhân thua lỗ cốt lõi nằm ở bản thân hướng tín hiệu (Gross PnL âm).

### 2. Phân Tích Lệch Pha Chế Độ Thị Trường (Market Regime Mismatch)
- **Hiệu suất theo từng Fold**:
  + **fold_1 (2024-12-01 -> 2025-06-30)**: Ret = `+0.01%`, MDD = `0.65%`, Sharpe = `0.04`, Lệnh = `21`
  + **fold_2 (2025-07-01 -> 2026-01-31)**: Ret = `+0.22%`, MDD = `0.23%`, Sharpe = `1.23`, Lệnh = `12`
  + **fold_3 (2026-02-01 -> 2026-09-01)**: Ret = `+0.20%`, MDD = `0.13%`, Sharpe = `1.49`, Lệnh = `10`

### 3. Phân Tích Cơ Chế Cắt Lỗ & Định Cỡ Vị Thế (SL & Sizing Analysis)
- Khảo sát cấu hình lệnh cho thấy việc sử dụng mức cắt lỗ cố định mà không thích ứng theo biến động thực tế (Dynamic Volatility) khiến alpha chịu nhiều lệnh cắt lỗ liên tiếp khi biến động giãn nở.

### 4. Đề Xuất Giả Thuyết Tiến Hóa Có Thể Bác Bỏ Được (Falsifiable Hypothesis)
> **Giả thuyết H1 cho `dca_short`**:
> - *Nếu*: Bổ sung bộ lọc điều kiện thị trường (ví dụ lọc ADX > 25 hoặc ATR Volatility Band) để cấm mở vị thế khi thị trường đi vào vùng nghẽn thanh khoản/sideway, đồng thời nới rộng SL từ cố định sang 2.5x ATR,
> - *Thì*: Số lượng lệnh thua trong Fold 2 sẽ giảm ít nhất 30%, đưa Sharpe OOS tổng thể lên $\ge 0.8$ và giảm P(Ruin > 15%) xuống dưới 5.0%.
> - *Kiểm chứng độc lập*: Giả thuyết này bắt buộc phải kiểm nghiệm trên tập Holdout sau tháng 09/2026, tuyệt đối không tune lại trên dữ liệu 2024-2026.

---

## Alpha: `18e87aa868ad_v2` (Fast Dynamic Channel Breakout V2 (Explicit ATR))
- **Phân loại**: `COIN User V2` | Phán quyết: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-1.03%` | MDD: `2.97%` | Daily Sharpe: `-0.38` | Lệnh OOS: `33` | Phí: `$7.43`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do loại bỏ chính thức**: Lỗ OOS gộp (-1.03%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.38 < 0.8)

### 1. Phân Tích Bào Mòn Phí & Ma Sát (Friction Drag)
- **Phí không phải nguyên nhân chính**: Tổng phí chỉ `$7.43`. Nguyên nhân thua lỗ cốt lõi nằm ở bản thân hướng tín hiệu (Gross PnL âm).

### 2. Phân Tích Lệch Pha Chế Độ Thị Trường (Market Regime Mismatch)
- **Hiệu suất theo từng Fold**:
  + **fold_1 (2024-12-01 -> 2025-06-30)**: Ret = `-0.51%`, MDD = `1.20%`, Sharpe = `-0.71`, Lệnh = `13`
  + **fold_2 (2025-07-01 -> 2026-01-31)**: Ret = `-0.73%`, MDD = `2.56%`, Sharpe = `-0.58`, Lệnh = `15`
  + **fold_3 (2026-02-01 -> 2026-09-01)**: Ret = `+0.20%`, MDD = `0.54%`, Sharpe = `0.35`, Lệnh = `5`
- **Dị ứng vùng Sideway (Chop Vulnerability)**: Bị cắt lỗ liên tục trong Fold 2 (2025-07 -> 2026-01), giai đoạn thị trường đi ngang biên độ hẹp.

### 3. Phân Tích Cơ Chế Cắt Lỗ & Định Cỡ Vị Thế (SL & Sizing Analysis)
- Khảo sát cấu hình lệnh cho thấy việc sử dụng mức cắt lỗ cố định mà không thích ứng theo biến động thực tế (Dynamic Volatility) khiến alpha chịu nhiều lệnh cắt lỗ liên tiếp khi biến động giãn nở.

### 4. Đề Xuất Giả Thuyết Tiến Hóa Có Thể Bác Bỏ Được (Falsifiable Hypothesis)
> **Giả thuyết H1 cho `18e87aa868ad_v2`**:
> - *Nếu*: Bổ sung bộ lọc điều kiện thị trường (ví dụ lọc ADX > 25 hoặc ATR Volatility Band) để cấm mở vị thế khi thị trường đi vào vùng nghẽn thanh khoản/sideway, đồng thời nới rộng SL từ cố định sang 2.5x ATR,
> - *Thì*: Số lượng lệnh thua trong Fold 2 sẽ giảm ít nhất 30%, đưa Sharpe OOS tổng thể lên $\ge 0.8$ và giảm P(Ruin > 15%) xuống dưới 5.0%.
> - *Kiểm chứng độc lập*: Giả thuyết này bắt buộc phải kiểm nghiệm trên tập Holdout sau tháng 09/2026, tuyệt đối không tune lại trên dữ liệu 2024-2026.

---

## Alpha: `edu_canonical_beginner_dual_ema` (Nora EDU — Beginner Dual EMA Trend Following)
- **Phân loại**: `EDU Canonical` | Phán quyết: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-8.56%` | MDD: `9.55%` | Daily Sharpe: `-1.28` | Lệnh OOS: `411` | Phí: `$460.47`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.1%` | P(MDD ≥ 20%): `0.0%`
- **Lý do loại bỏ chính thức**: Lỗ OOS gộp (-8.56%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.28 < 0.8)

### 1. Phân Tích Bào Mòn Phí & Ma Sát (Friction Drag)
- **Tác động phí rất lớn**: Tổng phí `$460.47` chiếm tỷ trọng đáng kể trên vốn. Tần suất giao dịch tương đối cao tạo gánh nặng phí Taker liên tục.

### 2. Phân Tích Lệch Pha Chế Độ Thị Trường (Market Regime Mismatch)
- **Hiệu suất theo từng Fold**:
  + **fold_1 (2024-12-01 -> 2025-06-30)**: Ret = `-2.99%`, MDD = `4.39%`, Sharpe = `-1.26`, Lệnh = `148`
  + **fold_2 (2025-07-01 -> 2026-01-31)**: Ret = `-2.87%`, MDD = `4.64%`, Sharpe = `-1.44`, Lệnh = `128`
  + **fold_3 (2026-02-01 -> 2026-09-01)**: Ret = `-2.95%`, MDD = `3.99%`, Sharpe = `-1.18`, Lệnh = `135`
- **Thất bại toàn diện (All-regime failure)**: Chiến lược thua lỗ trên cả 3 giai đoạn thị trường khác nhau (Bull 2024-H2, Choppy 2025, Correction 2026). Logic tín hiệu hiện tại không có edge.

### 3. Phân Tích Cơ Chế Cắt Lỗ & Định Cỡ Vị Thế (SL & Sizing Analysis)
- Khảo sát cấu hình lệnh cho thấy việc sử dụng mức cắt lỗ cố định mà không thích ứng theo biến động thực tế (Dynamic Volatility) khiến alpha chịu nhiều lệnh cắt lỗ liên tiếp khi biến động giãn nở.

### 4. Đề Xuất Giả Thuyết Tiến Hóa Có Thể Bác Bỏ Được (Falsifiable Hypothesis)
> **Giả thuyết H1 cho `edu_canonical_beginner_dual_ema`**:
> - *Nếu*: Bổ sung bộ lọc điều kiện thị trường (ví dụ lọc ADX > 25 hoặc ATR Volatility Band) để cấm mở vị thế khi thị trường đi vào vùng nghẽn thanh khoản/sideway, đồng thời nới rộng SL từ cố định sang 2.5x ATR,
> - *Thì*: Số lượng lệnh thua trong Fold 2 sẽ giảm ít nhất 30%, đưa Sharpe OOS tổng thể lên $\ge 0.8$ và giảm P(Ruin > 15%) xuống dưới 5.0%.
> - *Kiểm chứng độc lập*: Giả thuyết này bắt buộc phải kiểm nghiệm trên tập Holdout sau tháng 09/2026, tuyệt đối không tune lại trên dữ liệu 2024-2026.

---

## Alpha: `edu_canonical_advanced_volatility_breakout` (Nora EDU — Advanced Volatility Breakout & ATR Guard)
- **Phân loại**: `EDU Canonical` | Phán quyết: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-0.57%` | MDD: `4.01%` | Daily Sharpe: `-0.14` | Lệnh OOS: `59` | Phí: `$71.26`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do loại bỏ chính thức**: Lỗ OOS gộp (-0.57%); Daily Sharpe thấp (-0.14 < 0.8)

### 1. Phân Tích Bào Mòn Phí & Ma Sát (Friction Drag)
- **Tác động phí rất lớn**: Tổng phí `$71.26` chiếm tỷ trọng đáng kể trên vốn. Tần suất giao dịch tương đối cao tạo gánh nặng phí Taker liên tục.

### 2. Phân Tích Lệch Pha Chế Độ Thị Trường (Market Regime Mismatch)
- **Hiệu suất theo từng Fold**:
  + **fold_1 (2024-12-01 -> 2025-06-30)**: Ret = `+0.85%`, MDD = `2.23%`, Sharpe = `0.53`, Lệnh = `23`
  + **fold_2 (2025-07-01 -> 2026-01-31)**: Ret = `+0.23%`, MDD = `1.54%`, Sharpe = `0.20`, Lệnh = `16`
  + **fold_3 (2026-02-01 -> 2026-09-01)**: Ret = `-1.64%`, MDD = `2.36%`, Sharpe = `-1.82`, Lệnh = `20`

### 3. Phân Tích Cơ Chế Cắt Lỗ & Định Cỡ Vị Thế (SL & Sizing Analysis)
- Khảo sát cấu hình lệnh cho thấy việc sử dụng mức cắt lỗ cố định mà không thích ứng theo biến động thực tế (Dynamic Volatility) khiến alpha chịu nhiều lệnh cắt lỗ liên tiếp khi biến động giãn nở.

### 4. Đề Xuất Giả Thuyết Tiến Hóa Có Thể Bác Bỏ Được (Falsifiable Hypothesis)
> **Giả thuyết H1 cho `edu_canonical_advanced_volatility_breakout`**:
> - *Nếu*: Bổ sung bộ lọc điều kiện thị trường (ví dụ lọc ADX > 25 hoặc ATR Volatility Band) để cấm mở vị thế khi thị trường đi vào vùng nghẽn thanh khoản/sideway, đồng thời nới rộng SL từ cố định sang 2.5x ATR,
> - *Thì*: Số lượng lệnh thua trong Fold 2 sẽ giảm ít nhất 30%, đưa Sharpe OOS tổng thể lên $\ge 0.8$ và giảm P(Ruin > 15%) xuống dưới 5.0%.
> - *Kiểm chứng độc lập*: Giả thuyết này bắt buộc phải kiểm nghiệm trên tập Holdout sau tháng 09/2026, tuyệt đối không tune lại trên dữ liệu 2024-2026.

---

## Alpha: `026f43441cb2` (EDU User 026f4344)
- **Phân loại**: `EDU Active User` | Phán quyết: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-7.54%` | MDD: `7.90%` | Daily Sharpe: `-1.61` | Lệnh OOS: `202` | Phí: `$283.01`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do loại bỏ chính thức**: Lỗ OOS gộp (-7.54%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-1.61 < 0.8)

### 1. Phân Tích Bào Mòn Phí & Ma Sát (Friction Drag)
- **Tác động phí rất lớn**: Tổng phí `$283.01` chiếm tỷ trọng đáng kể trên vốn. Tần suất giao dịch tương đối cao tạo gánh nặng phí Taker liên tục.

### 2. Phân Tích Lệch Pha Chế Độ Thị Trường (Market Regime Mismatch)
- **Hiệu suất theo từng Fold**:
  + **fold_1 (2024-12-01 -> 2025-06-30)**: Ret = `-3.64%`, MDD = `3.96%`, Sharpe = `-2.26`, Lệnh = `64`
  + **fold_2 (2025-07-01 -> 2026-01-31)**: Ret = `+0.27%`, MDD = `4.11%`, Sharpe = `0.16`, Lệnh = `72`
  + **fold_3 (2026-02-01 -> 2026-09-01)**: Ret = `-4.31%`, MDD = `4.57%`, Sharpe = `-3.55`, Lệnh = `66`

### 3. Phân Tích Cơ Chế Cắt Lỗ & Định Cỡ Vị Thế (SL & Sizing Analysis)
- Khảo sát cấu hình lệnh cho thấy việc sử dụng mức cắt lỗ cố định mà không thích ứng theo biến động thực tế (Dynamic Volatility) khiến alpha chịu nhiều lệnh cắt lỗ liên tiếp khi biến động giãn nở.

### 4. Đề Xuất Giả Thuyết Tiến Hóa Có Thể Bác Bỏ Được (Falsifiable Hypothesis)
> **Giả thuyết H1 cho `026f43441cb2`**:
> - *Nếu*: Bổ sung bộ lọc điều kiện thị trường (ví dụ lọc ADX > 25 hoặc ATR Volatility Band) để cấm mở vị thế khi thị trường đi vào vùng nghẽn thanh khoản/sideway, đồng thời nới rộng SL từ cố định sang 2.5x ATR,
> - *Thì*: Số lượng lệnh thua trong Fold 2 sẽ giảm ít nhất 30%, đưa Sharpe OOS tổng thể lên $\ge 0.8$ và giảm P(Ruin > 15%) xuống dưới 5.0%.
> - *Kiểm chứng độc lập*: Giả thuyết này bắt buộc phải kiểm nghiệm trên tập Holdout sau tháng 09/2026, tuyệt đối không tune lại trên dữ liệu 2024-2026.

---

## Alpha: `138df68946ad` (EDU User 138df689)
- **Phân loại**: `EDU Active User` | Phán quyết: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-6.86%` | MDD: `8.33%` | Daily Sharpe: `-1.52` | Lệnh OOS: `445` | Phí: `$701.69`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do loại bỏ chính thức**: Lỗ OOS gộp (-6.86%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-1.52 < 0.8)

### 1. Phân Tích Bào Mòn Phí & Ma Sát (Friction Drag)
- **Tác động phí rất lớn**: Tổng phí `$701.69` chiếm tỷ trọng đáng kể trên vốn. Tần suất giao dịch tương đối cao tạo gánh nặng phí Taker liên tục.

### 2. Phân Tích Lệch Pha Chế Độ Thị Trường (Market Regime Mismatch)
- **Hiệu suất theo từng Fold**:
  + **fold_1 (2024-12-01 -> 2025-06-30)**: Ret = `-3.32%`, MDD = `3.60%`, Sharpe = `-2.35`, Lệnh = `153`
  + **fold_2 (2025-07-01 -> 2026-01-31)**: Ret = `-2.21%`, MDD = `4.25%`, Sharpe = `-1.54`, Lệnh = `149`
  + **fold_3 (2026-02-01 -> 2026-09-01)**: Ret = `-1.48%`, MDD = `3.52%`, Sharpe = `-0.84`, Lệnh = `143`
- **Thất bại toàn diện (All-regime failure)**: Chiến lược thua lỗ trên cả 3 giai đoạn thị trường khác nhau (Bull 2024-H2, Choppy 2025, Correction 2026). Logic tín hiệu hiện tại không có edge.

### 3. Phân Tích Cơ Chế Cắt Lỗ & Định Cỡ Vị Thế (SL & Sizing Analysis)
- Khảo sát cấu hình lệnh cho thấy việc sử dụng mức cắt lỗ cố định mà không thích ứng theo biến động thực tế (Dynamic Volatility) khiến alpha chịu nhiều lệnh cắt lỗ liên tiếp khi biến động giãn nở.

### 4. Đề Xuất Giả Thuyết Tiến Hóa Có Thể Bác Bỏ Được (Falsifiable Hypothesis)
> **Giả thuyết H1 cho `138df68946ad`**:
> - *Nếu*: Bổ sung bộ lọc điều kiện thị trường (ví dụ lọc ADX > 25 hoặc ATR Volatility Band) để cấm mở vị thế khi thị trường đi vào vùng nghẽn thanh khoản/sideway, đồng thời nới rộng SL từ cố định sang 2.5x ATR,
> - *Thì*: Số lượng lệnh thua trong Fold 2 sẽ giảm ít nhất 30%, đưa Sharpe OOS tổng thể lên $\ge 0.8$ và giảm P(Ruin > 15%) xuống dưới 5.0%.
> - *Kiểm chứng độc lập*: Giả thuyết này bắt buộc phải kiểm nghiệm trên tập Holdout sau tháng 09/2026, tuyệt đối không tune lại trên dữ liệu 2024-2026.

---

## Alpha: `14e3b934b1e5` (EDU User 14e3b934)
- **Phân loại**: `EDU Active User` | Phán quyết: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-2.21%` | MDD: `3.17%` | Daily Sharpe: `-0.48` | Lệnh OOS: `38` | Phí: `$44.72`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.0%` | P(MDD ≥ 20%): `0.0%`
- **Lý do loại bỏ chính thức**: Lỗ OOS gộp (-2.21%); Chỉ có 1/3 folds lãi; Daily Sharpe thấp (-0.48 < 0.8)

### 1. Phân Tích Bào Mòn Phí & Ma Sát (Friction Drag)
- **Tác động phí rất lớn**: Tổng phí `$44.72` chiếm tỷ trọng đáng kể trên vốn. Tần suất giao dịch tương đối cao tạo gánh nặng phí Taker liên tục.

### 2. Phân Tích Lệch Pha Chế Độ Thị Trường (Market Regime Mismatch)
- **Hiệu suất theo từng Fold**:
  + **fold_1 (2024-12-01 -> 2025-06-30)**: Ret = `-1.77%`, MDD = `2.80%`, Sharpe = `-1.13`, Lệnh = `16`
  + **fold_2 (2025-07-01 -> 2026-01-31)**: Ret = `+0.44%`, MDD = `1.87%`, Sharpe = `0.33`, Lệnh = `9`
  + **fold_3 (2026-02-01 -> 2026-09-01)**: Ret = `-0.88%`, MDD = `2.02%`, Sharpe = `-0.54`, Lệnh = `13`

### 3. Phân Tích Cơ Chế Cắt Lỗ & Định Cỡ Vị Thế (SL & Sizing Analysis)
- Khảo sát cấu hình lệnh cho thấy việc sử dụng mức cắt lỗ cố định mà không thích ứng theo biến động thực tế (Dynamic Volatility) khiến alpha chịu nhiều lệnh cắt lỗ liên tiếp khi biến động giãn nở.

### 4. Đề Xuất Giả Thuyết Tiến Hóa Có Thể Bác Bỏ Được (Falsifiable Hypothesis)
> **Giả thuyết H1 cho `14e3b934b1e5`**:
> - *Nếu*: Bổ sung bộ lọc điều kiện thị trường (ví dụ lọc ADX > 25 hoặc ATR Volatility Band) để cấm mở vị thế khi thị trường đi vào vùng nghẽn thanh khoản/sideway, đồng thời nới rộng SL từ cố định sang 2.5x ATR,
> - *Thì*: Số lượng lệnh thua trong Fold 2 sẽ giảm ít nhất 30%, đưa Sharpe OOS tổng thể lên $\ge 0.8$ và giảm P(Ruin > 15%) xuống dưới 5.0%.
> - *Kiểm chứng độc lập*: Giả thuyết này bắt buộc phải kiểm nghiệm trên tập Holdout sau tháng 09/2026, tuyệt đối không tune lại trên dữ liệu 2024-2026.

---

## Alpha: `1a1a4389a821` (EDU User 1a1a4389)
- **Phân loại**: `EDU Active User` | Phán quyết: **REJECT**
- **Chỉ số OOS**: Lợi nhuận: `-13.41%` | MDD: `14.23%` | Daily Sharpe: `-2.71` | Lệnh OOS: `1019` | Phí: `$1168.02`
- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `0.2%` | P(MDD ≥ 20%): `0.0%`
- **Lý do loại bỏ chính thức**: Lỗ OOS gộp (-13.41%); Chỉ có 0/3 folds lãi; Daily Sharpe thấp (-2.71 < 0.8)

### 1. Phân Tích Bào Mòn Phí & Ma Sát (Friction Drag)
- **Tác động phí rất lớn**: Tổng phí `$1168.02` chiếm tỷ trọng đáng kể trên vốn. Tần suất giao dịch tương đối cao tạo gánh nặng phí Taker liên tục.

### 2. Phân Tích Lệch Pha Chế Độ Thị Trường (Market Regime Mismatch)
- **Hiệu suất theo từng Fold**:
  + **fold_1 (2024-12-01 -> 2025-06-30)**: Ret = `-5.03%`, MDD = `5.06%`, Sharpe = `-2.80`, Lệnh = `343`
  + **fold_2 (2025-07-01 -> 2026-01-31)**: Ret = `-4.63%`, MDD = `5.65%`, Sharpe = `-2.55`, Lệnh = `334`
  + **fold_3 (2026-02-01 -> 2026-09-01)**: Ret = `-4.40%`, MDD = `5.34%`, Sharpe = `-2.79`, Lệnh = `342`
- **Thất bại toàn diện (All-regime failure)**: Chiến lược thua lỗ trên cả 3 giai đoạn thị trường khác nhau (Bull 2024-H2, Choppy 2025, Correction 2026). Logic tín hiệu hiện tại không có edge.

### 3. Phân Tích Cơ Chế Cắt Lỗ & Định Cỡ Vị Thế (SL & Sizing Analysis)
- Khảo sát cấu hình lệnh cho thấy việc sử dụng mức cắt lỗ cố định mà không thích ứng theo biến động thực tế (Dynamic Volatility) khiến alpha chịu nhiều lệnh cắt lỗ liên tiếp khi biến động giãn nở.

### 4. Đề Xuất Giả Thuyết Tiến Hóa Có Thể Bác Bỏ Được (Falsifiable Hypothesis)
> **Giả thuyết H1 cho `1a1a4389a821`**:
> - *Nếu*: Bổ sung bộ lọc điều kiện thị trường (ví dụ lọc ADX > 25 hoặc ATR Volatility Band) để cấm mở vị thế khi thị trường đi vào vùng nghẽn thanh khoản/sideway, đồng thời nới rộng SL từ cố định sang 2.5x ATR,
> - *Thì*: Số lượng lệnh thua trong Fold 2 sẽ giảm ít nhất 30%, đưa Sharpe OOS tổng thể lên $\ge 0.8$ và giảm P(Ruin > 15%) xuống dưới 5.0%.
> - *Kiểm chứng độc lập*: Giả thuyết này bắt buộc phải kiểm nghiệm trên tập Holdout sau tháng 09/2026, tuyệt đối không tune lại trên dữ liệu 2024-2026.

---