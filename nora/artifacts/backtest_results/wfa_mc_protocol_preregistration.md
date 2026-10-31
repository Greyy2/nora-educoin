# TIỀN ĐĂNG KIỂM GIAO THỨC ĐÁNH GIÁ ROLLING OOS & MONTE CARLO (COHORT MASTER BACKTEST)
*Tài liệu tiền đăng kiểm phương pháp luận, cửa sổ kiểm định, tiêu chí mẫu mỏng và bộ ngưỡng phân loại.*
*Ngày cập nhật: 2026-10-30 07:07 UTC | Phiên bản: 1.1.0-REVISED (Đã xử lý 6 phản biện kỹ thuật)*

> [!IMPORTANT]
> **TRẠNG THÁI HIỆN TẠI: TIỀN ĐĂNG KIỂM (PRE-REGISTRATION) — THI CÔNG BỊ KHÓA (STRICTLY BLOCKED)**
> - Owner đã chốt master risk/trade ≤ 0.25%, gross ≤ 3x và one-way ≤ 2x; runtime enforcement chưa được nghiệm thu. Fee/cost, historical funding/spec và backtest-live/Demo replay cũng chưa đạt, nên chạy chính thức vẫn **BỊ CHẶN**.
> - Mọi thử nghiệm chạy hạ tầng nếu có chỉ mang nhãn: **"Dry-run hạ tầng kỹ thuật, không dùng ra quyết định alpha"** và không được đưa vào bảng lọc.
> - Owner đã chọn Phương án A (Aggregated OOS ≥ 30 trades) và chấp nhận các ngưỡng KEEP / REVIEW / REJECT tại Section 7. Đây là phê duyệt các lựa chọn phương pháp, không đóng các readiness gates.

---

## 1. Ranh Giới Phương Pháp: Rolling OOS vs True WFA

Hầu hết các alpha hiện tại có bộ tham số cố định trong mã nguồn. Cần phân định rạch ròi 2 phương thức:
1. **Rolling OOS Window Evaluation (Đánh giá cửa sổ trượt tham số cố định)**:
   - *Áp dụng cho*: Toàn bộ 17 alphas/legs đang chạy tham số cố định trong mã nguồn:
     - 6 COIN System Legs (`kema_long`, `kema_short`, `sideway_long`, `sideway_short`, `dca_long`, `dca_short`).
     - 3 COIN User V2 (`efa90f74cd08_v2`, `18e87aa868ad_v2`, `33312a2f4dfc_v2`). *Lưu ý: Do hiện tại chưa khai báo grid tham số tối ưu, 3 alpha này được phân loại duy nhất là Rolling OOS tham số cố định, không để trạng thái 'nếu'.*
     - 2 EDU Canonical (`edu_canonical_beginner_dual_ema`, `edu_canonical_advanced_volatility_breakout`).
     - 6 EDU Active User có logic tín hiệu (`0873864b8db7`, `090730ae35b8`, `0d51ba8d2012`, `14e3b934b1e5`, `15567e02a806`, `18e87aa868ad`).
   - *Bản chất*: KHÔNG có bước tái tối ưu tham số trên tập Train. Train chỉ dùng làm warmup/tích lũy trạng thái chỉ báo; OOS đánh giá hiệu suất thuần túy trên dữ liệu tương lai chưa nhìn thấy.
2. **True Walk-Forward Optimization (WFO thực thụ)**:
   - *Điều kiện cần*: Chỉ áp dụng khi chiến lược có định nghĩa rõ không gian tham số Grid (ví dụ: `lookback ∈ [10, 20, 30]`, `stop_loss_rate ∈ [2.0, 2.5, 3.0]`). Hiện tại chưa có alpha nào trong cohort có grid được duyệt, do đó **không có alpha nào chạy theo luồng True WFA trong đợt này**.

---

## 2. Giới Hạn Cốt Lõi Về Tính Độc Lập Của Dữ Liệu: Pseudo-OOS vs Pure Holdout

Cần nêu trung thực và minh bạch giới hạn về dữ liệu trước Owner:
1. **Bản chất 'Train' và 'OOS'**: Với các chiến lược tham số cố định, tập Train mở rộng (expanding train) không thực hiện vai trò tìm kiếm tham số. Ba cửa sổ OOS thực chất chỉ là **3 lát cắt thời gian lịch sử (historical time slices)**.
2. **Rủi ro Rò rỉ Thông tin (Information Leakage)**: Đợt Master Smoke Run vừa qua đã chạy toàn bộ dữ liệu 2.7 năm (`2024-01` đến `2026-09`). Kết quả in-sample toàn kỳ đã được quan sát. Nếu trong quá trình phát triển vừa qua (ví dụ viết User V2, chỉnh sizing 0.25%, gắn SL), các quyết định kỹ thuật đã vô thức dựa vào việc quan sát hành vi thị trường 2024–2026, thì 3 cửa sổ OOS này **không còn là tập dữ liệu tinh khiết chưa từng thấy (Pure Untouched OOS)**.
3. **Kết luận kỹ thuật**: Kết quả OOS của 3 folds chỉ mang ý nghĩa **Pseudo-OOS (Kiểm định lát cắt lịch sử)**. Để có đánh giá Out-of-Sample thực sự khách quan (True Blind Holdout), hệ thống bắt buộc phải kiểm định trên dữ liệu mới hoàn toàn (sau `2026-09`) hoặc trên các cặp tiền/tài sản chưa từng được backtest.

---

## 3. Thiết Kế Cửa Sổ Kiểm Định (3 Folds trên chu kỳ 2024-01 đến 2026-09)

Tổng thời gian dữ liệu: ~2.7 năm (1,005 ngày). Phân chia 3 Folds theo mô hình Anchored Slicing:

| Fold | Khoảng Thời Gian Train (Warmup) | Độ Dài Train | Khoảng Thời Gian OOS (Đánh giá) | Độ Dài OOS | Chế Độ Thị Trường Đại Diện |
|---|---|---|---|---|---|
| **Fold 1** | `2024-01-01` → `2024-11-30` | 11 tháng | `2024-12-01` → `2025-06-30` | 7 tháng | Bull/Euphoria & Điều chỉnh |
| **Fold 2** | `2024-01-01` → `2025-06-30` | 18 tháng | `2025-07-01` → `2026-01-31` | 7 tháng | Sideway / Biến động cao |
| **Fold 3** | `2024-01-01` → `2026-01-31` | 25 tháng | `2026-02-01` → `2026-09-01` | 7 tháng | Bear / Chuyển giao xu hướng |

---

## 4. Quy Tắc Số Lệnh Tối Thiểu & Phương Án Xử Lý Mẫu Mỏng

### Mâu thuẫn thực tế dữ liệu:
OOS mỗi fold chỉ kéo dài 7 tháng. Các alpha khung 24h (User V2) chỉ có ~45–53 lệnh trong toàn bộ 2.7 năm (trung bình ~1.4 lệnh/tháng $\approx$ 10–12 lệnh mỗi fold OOS 7 tháng). Nếu áp đặt cứng nhắc $N \ge 30$ lệnh trên **mỗi fold**, toàn bộ alpha 24h và sideway sẽ tự động bị đánh dấu là `INSUFFICIENT_SAMPLE`. Chỉ có nhóm Top Agent (proxy) hoặc EMA 1h là vượt qua được ngưỡng này.

### Lựa chọn đã được Owner chốt: Phương án A (Đánh giá mẫu gộp Aggregated OOS)
  - Ngưỡng thống kê $N_{\text{trades, aggregated OOS}} \ge 30$ lệnh được tính trên **tổng cả 3 folds OOS cộng lại** (tương đương 21 tháng OOS). Với phương án này, các alpha 24h có ~30–35 lệnh OOS tổng cộng sẽ đủ điều kiện tính toán Sharpe, t-stat và DSR.
  - Từng fold riêng lẻ chỉ dùng để kiểm tra tính nhất quán phương hướng: yêu cầu ít nhất 2/3 folds có lợi nhuận dương ($Net > 0$) và không vi phạm trần Drawdown.
  - Phương án B (≥ 30 lệnh trên từng fold) **không được chọn**.

---

## 5. Phương Pháp Monte Carlo: Stationary Block Bootstrap & Phân Tích Độ Nhạy

1. **Phương pháp Resampling**:
   - Sử dụng **Stationary Block Bootstrap** (không dùng IID simple bootstrap) nhằm bảo toàn tính phụ thuộc thời gian (autocorrelation) và đặc tính cụm lệnh của chiến lược DCA/Breakout.
   - **Độ dài khối cơ sở (Base Block Length)**: $b = 5$ trades liên tiếp. Đây là **giả định kỹ thuật**.
   - **Kiểm định độ nhạy bắt buộc (Sensitivity Analysis)**: Để tránh kết quả phụ thuộc vào việc chọn $b$, bắt buộc chạy đối soát ở 3 mức: $b \in \{3, 5, 10\}$ trades. Nếu khoảng tin cậy hoặc xác suất ruin thay đổi đột ngột giữa các mức $b$, phải ghi nhận độ bất định cao trong báo cáo.
2. **Tham số mô phỏng**:
   - Số đường mô phỏng: $1,000\text{ paths}$, seed cố định `seed = 42`, vốn ban đầu: $10,000\text{ USDT}$.
3. **Đồng bộ định nghĩa Ruin với Policy Owner**:
   - Thay vì dùng ngưỡng tùy tiện $MDD > 30\%$, định nghĩa Ruin trong Monte Carlo được đồng bộ trực tiếp với chính sách kiểm soát rủi ro của Owner:
     - **Ngưỡng Hard Stop / Ruin chính**: $MDD > 15\%$ (tương ứng với Drawdown Hard Stop $15\%$ của policy).
     - **Ngưỡng Phụ (Extreme Tail Risk)**: $MDD > 20\%$ (tương ứng với trần $\min(1.5 \times \text{MDD}_{\text{in-sample}}, 20\%)$).
     - Báo cáo phải xuất đồng thời $P(MDD > 15\%)$ và $P(MDD > 20\%)$.
4. **Giới hạn phương pháp luận**:
   - Monte Carlo chỉ đo biến thiên thứ tự của các lệnh đã có trong lịch sử; **không thể mô phỏng các regime hoặc cú sập thanh khoản chưa từng gặp trong giai đoạn 2024–2026**.

---

## 6. Thước Đo Deflated Sharpe Ratio (DSR) & Quy Tắc Đếm Số Thử Nghiệm ($N$)

1. **Quy tắc đếm số thử nghiệm ($N_{\text{trials}}$)**:
   - $N$ là tổng số lượng cấu hình/phiên bản thực tế đã được khảo sát trong toàn bộ quá trình nghiên cứu. Chọn $N$ nhỏ (ví dụ chỉ 24) sẽ làm DSR cao giả tạo (lạc quan thái quá).
   - Kiểm kê số thử nghiệm:
     - $N_{\text{cohort}} = 24$: Nếu chỉ tính các alpha độc lập trong cohort smoke-run hiện tại.
     - $N_{\text{universe}} = 72$: Có 72 variants trong manifest, nhưng hiện tất cả đều `BLOCKED_NOT_EVALUATED`; đây **không phải 72 trials đã chạy**. Chỉ dùng $N=72$ như sensitivity giả định bảo thủ, không mô tả là số thử nghiệm thực tế.
     - $N_{\text{historical}}$: **Chưa đếm** (hiện tại chưa có danh sách kiểm kê chính thức cho các bản nháp V1/V2 cũ, nên không đưa con số ước tính vào tính toán DSR cho tới khi có danh sách đếm được).
2. **Kịch bản tính toán DSR**: Báo cáo chỉ được gọi $N=24$ là số hiện diện trong cohort smoke; $N=72$ là sensitivity giả định, không phải trial count quan sát. DSR chính thức vẫn cần kiểm kê các cấu hình đã thử trong lịch sử; nếu chưa có, ghi `DSR_UNAVAILABLE` thay vì khẳng định $N$ chính xác.

---

## 7. Bảng Ngưỡng Phân Loại: `OWNER ĐÃ CHẤP NHẬN — 2026-10-29`

*Owner đã chấp nhận các ngưỡng đề xuất dưới đây. DSR vẫn phải tuân theo giới hạn trial-count ở Section 6; các ngưỡng không mở khóa WFA/Monte Carlo khi readiness gates còn BLOCKED.*

| Tiêu Chí Đánh Giá | `KEEP` (Đạt Chuẩn Chuyển Tiếp) | `REVIEW` (Cần Xem Xét & Chẩn Đoán) | `REJECT` (Loại Bỏ Hoặc Đại Tu) | Ghi Chú Kỹ Thuật |
|---|---|---|---|---|
| **Độ Bền OOS (Consistency)** | $\ge 2/3$ folds OOS có lợi nhuận dương ($Net > 0$) | $1/3$ folds OOS có lợi nhuận dương | $0/3$ folds OOS có lợi nhuận dương | Đo tính ổn định qua 3 lát cắt thị trường |
| **OOS Sharpe Ratio** | $\text{Sharpe}_{\text{OOS}} \ge 0.8$ | $0.2 \le \text{Sharpe}_{\text{OOS}} < 0.8$ | $\text{Sharpe}_{\text{OOS}} < 0.2$ | Tính trên OOS gộp (Aggregated OOS) |
| **Deflated Sharpe (DSR, sensitivity $N=72$)** | $DSR \ge 0.95$ (Độ tin cậy 95%) | $0.80 \le DSR < 0.95$ | $DSR < 0.80$ | $N=72$ chỉ là kịch bản giả định bảo thủ cho tới khi kiểm kê trials thực tế |
| **Xác Suất Ruin MC ($P(\text{MDD} > 15\%)$)** | $P(\text{MDD} > 15\%) \le 5.0\%$ | $5.0\% < P \le 15.0\%$ | $P(\text{MDD} > 15\%) > 15.0\%$ | Đồng bộ với Drawdown Stop 15% |
| **Xác Suất Thắng MC ($P(\text{Profit} > 0)$)** | $P(\text{Profit}) \ge 80.0\%$ | $60.0\% \le P < 80.0\%$ | $P(\text{Profit}) < 60.0\%$ | Block bootstrap $b=5$, seed 42 |
| **Độ Đầy Đủ Mẫu (Theo Phương Án A)** | $N_{\text{trades, agg OOS}} \ge 30$ | $15 \le N < 30$ | $N < 15$ | Nếu $N < 30$: Gán `INSUFFICIENT_SAMPLE` |

---

## 8. Bảng Kiểm Kê Từng Đối Tượng Trong Cohort Đóng Băng (25 Rows)

| STT | ID Đối Tượng | Tên Đối Tượng | Phân Loại Danh Mục | Lệnh Smoke | Phân Loại Tính Chất Mã Nguồn | Phương Thức Đánh Giá Gán |
|---|---|---|---|---|---|---|
| 1 | `kema_long` | System Leg kema_long | COIN System Leg | 40 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |
| 2 | `kema_short` | System Leg kema_short | COIN System Leg | 40 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |
| 3 | `sideway_long` | System Leg sideway_long | COIN System Leg | 2 | LOW_SAMPLE_CRITICAL | `FIXED_PARAM_ROLLING_OOS` |
| 4 | `sideway_short` | System Leg sideway_short | COIN System Leg | 3 | LOW_SAMPLE_CRITICAL | `FIXED_PARAM_ROLLING_OOS` |
| 5 | `dca_long` | System Leg dca_long | COIN System Leg | 87 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |
| 6 | `dca_short` | System Leg dca_short | COIN System Leg | 67 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |
| 7 | `combo_6_system_legs` | Combo 6 System Legs (Portfolio | COIN Portfolio | 100 | PORTFOLIO_COMBO | `PORTFOLIO_ROLLING_OOS` |
| 8 | `efa90f74cd08_v2` | Donchian Channel Breakout V2 ( | COIN User V2 | 45 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |
| 9 | `18e87aa868ad_v2` | Fast Dynamic Channel Breakout  | COIN User V2 | 53 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |
| 10 | `33312a2f4dfc_v2` | StdDev Dynamic Channel Breakou | COIN User V2 | 46 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |
| 11 | `okx_01pp` | Top Agent okx_01pp | COIN Top Agent | 1197 | PROXY_ENTRY_RESEARCH_ONLY | `RESEARCH_ONLY_NO_DECISION` |
| 12 | `okx_auroraxwt` | Top Agent okx_auroraxwt | COIN Top Agent | 467 | PROXY_ENTRY_RESEARCH_ONLY | `RESEARCH_ONLY_NO_DECISION` |
| 13 | `okx_dark_wood_dahlia` | Top Agent okx_dark_wood_dahlia | COIN Top Agent | 1963 | PROXY_ENTRY_RESEARCH_ONLY | `RESEARCH_ONLY_NO_DECISION` |
| 14 | `edu_canonical_beginner_dual_ema` | Nora EDU — Beginner Dual EMA T | EDU Canonical | 668 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |
| 15 | `edu_canonical_advanced_volatility_breakout` | Nora EDU — Advanced Volatility | EDU Canonical | 102 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |
| 16 | `026f43441cb2` | EDU User 026f4344 | EDU Active User | 1 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |
| 17 | `0873864b8db7` | EDU User 0873864b | EDU Active User | 4 | LOW_SAMPLE_CRITICAL | `FIXED_PARAM_ROLLING_OOS` |
| 18 | `090730ae35b8` | EDU User 090730ae | EDU Active User | 17 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |
| 19 | `0bf936687964` | EDU User 0bf93668 | EDU Active User | 1 | LOW_SAMPLE_CRITICAL | `FIXED_PARAM_ROLLING_OOS` |
| 20 | `0d51ba8d2012` | EDU User 0d51ba8d | EDU Active User | 23 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |
| 21 | `138df68946ad` | EDU User 138df689 | EDU Active User | 1 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |
| 22 | `14e3b934b1e5` | EDU User 14e3b934 | EDU Active User | 76 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |
| 23 | `15567e02a806` | EDU User 15567e02 | EDU Active User | 10 | LOW_SAMPLE_CRITICAL | `FIXED_PARAM_ROLLING_OOS` |
| 24 | `18e87aa868ad` | EDU User 18e87aa8 | EDU Active User | 20 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |
| 25 | `1a1a4389a821` | EDU User 1a1a4389 | EDU Active User | 1 | FIXED_PARAM_ROLLING_OOS | `FIXED_PARAM_ROLLING_OOS` |

### Tóm tắt phân bổ 25 đối tượng:
- **1 Portfolio Combo**: `combo_6_system_legs` $\rightarrow$ Đánh giá riêng ở cấp danh mục, cấm xếp hạng.
- **4 Bài EDU loại trừ cấu trúc**: `026f43441cb2`, `0bf936687964`, `138df68946ad`, `1a1a4389a821` $\rightarrow$ Loại trừ do mã nguồn chỉ có lệnh Mua, không có logic bán/thoát lệnh.
- **3 Top Agent Proxy**: `okx_01pp`, `okx_auroraxwt`, `okx_dark_wood_dahlia` $\rightarrow$ Đánh giá Rolling OOS dạng proxy nghiên cứu (`RESEARCH_ONLY_NO_DECISION`), cấm đưa vào bảng lọc KEEP/REJECT.
- **4 Cảnh báo mẫu mỏng**: `sideway_long` (2 lệnh), `sideway_short` (3 lệnh), `0873864b8db7` (4 lệnh), `15567e02a806` (10 lệnh) $\rightarrow$ Chắc chắn rơi vào `INSUFFICIENT_SAMPLE`.
- **13 Rolling OOS tham số cố định**:
  - 4 COIN System legs: `kema_long` (40), `kema_short` (40), `dca_long` (87), `dca_short` (67).
  - 3 COIN User V2: `efa90f74cd08_v2` (45), `18e87aa868ad_v2` (53), `33312a2f4dfc_v2` (46).
  - 2 EDU Canonical: `edu_canonical_beginner_dual_ema` (668), `edu_canonical_advanced_volatility_breakout` (102).
  - 4 EDU Active User: `090730ae35b8` (17), `0d51ba8d2012` (23), `14e3b934b1e5` (76), `18e87aa868ad` (20).

---

## 9. Biên Bản Phê Duyệt Của Owner (Owner Sign-off & Lock)

*Owner đã chốt các lựa chọn phương pháp bên dưới. Đây chưa phải chữ ký phê duyệt toàn bộ protocol; việc thi công vẫn cần các readiness gates tại đầu tài liệu.*

- **Quy tắc số lệnh**: `PHƯƠNG ÁN A — Aggregated OOS >= 30 trades` (Owner đã chốt 2026-10-29).
- **Ngưỡng KEEP / REVIEW / REJECT**: `SECTION 7 — OWNER ĐÃ CHẤP NHẬN` (2026-10-29).
- **Master Risk đã chốt**: risk/trade <= 0.25% master, gross <= 3x equity, one-way <= 2x equity; runtime enforcement còn mở.
- **Full protocol sign-off**: `CHƯA GHI NHẬN`.
- **Trạng thái thi công**: `STRICTLY_BLOCKED` cho tới khi data/spec/funding, cost, execution/Demo replay và runtime risk gates được nghiệm thu.
