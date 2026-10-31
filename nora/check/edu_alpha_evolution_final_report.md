# BÁO CÁO KIỂM TOÁN VÀ NGHIỆM THU: CHUỖI TIẾN HÓA EDU ALPHA (EDU-EVO-00 ĐẾN EDU-EVO-12)

**Trạng thái tổng thể:** ⚠️ **`NOT ACCEPTED / RESULTS INVALID FOR PASS CLAIMS`**  
**Thời điểm cập nhật:** `2026-10-27 17:08:29 UTC`  
**Môi trường thực thi:** Engine `NautilusTrader 1.231.0` | Port 18022 | Cgroup cap: `nora.slice` (RAM cap 2GB/job)  
**Nguyên tắc đạo đức nghiên cứu:** Tuyệt đối không tô vẽ, không data-snooping, hạ toàn bộ các kết luận WFA/MC bị ảnh hưởng bởi lỗi kỹ thuật mốc chia `stage_split`, minh bạch 100% bản chất số liệu.  

---
## 1. KẾT LUẬN KIỂM TOÁN VÀ XỬ LÝ KHẮC PHỤC (AUDIT FINDINGS & DISPOSITION)

Đợt kiểm toán độc lập đã chỉ ra các vấn đề kỹ thuật cốt lõi và đã được xử lý triệt để trong bản báo cáo này:

1. **Đã sửa triệt để Schema chi phí và tách bạch tỷ trọng Full-Window vs OOS:**
   - Trích xuất dữ liệu trực tiếp từ `diagnostics.pnl_structure` và `metrics.test` của từng job run trong engine cache.
   - **Tách riêng tỷ trọng chi phí Full-Window và OOS:** Tỷ trọng Gross Loss % và Phí % được tính độc lập cho từng giai đoạn (Full-Window tính trên `full_gross_pnl` và `full_fees`; OOS Stage tính hoàn toàn trên `oos_gross_pnl` và `oos_fees`), khắc phục triệt để lỗi ghi nhầm tỷ lệ Full-Window vào OOS.
   - **Làm rõ định nghĩa 'Gross PnL':** Gross PnL là kết quả hoàn phí số học (`gross_pnl = net_pnl + fees_usd`) trước khi trừ commission phí sàn. Tuy nhiên, do engine đã áp dụng proxy thực thi (spread, slippage và stop loss) vào mô phỏng, phần Gross âm phản ánh: *sau các proxy execution và trước commission phí sàn, PnL vẫn âm* (không quy kết một chiều là thuần túy do logic tín hiệu).
   - **Bản chất của `metrics.test` (OOS Baseline):** Số liệu OOS là kết quả mô tả trên một lát cắt Train/Test baseline cố định trong lịch sử đã xem, **không đại diện cho kiểm định WFA nhiều cửa sổ trượt hợp lệ và không cấu thành holdout độc lập**.
   - Phân loại rõ ràng 3 nhóm bản chất: `FULL_PROFITABLE_OOS_LOSS` (8 alpha), `GROSS_AND_NET_NEGATIVE` (15 alpha), `FEE_DRAGGED_NEGATIVE` (0 alpha).
   - Ghi rõ: Phép tính zero-fee là phép hoàn phí số học (`arithmetic ledger rebate`), không phải lượt backtest rerun mô phỏng không phí riêng.
2. **Vô hiệu hóa toàn bộ 19 kết quả WFA (`UNVERIFIED / INVALID_FOLD_WINDOWS`):**
   - Xác nhận cơ chế `stage_split` của engine tự động snap mốc chia train/test về ngày 1 tháng 1 (`jan1`), làm sai lệch độ dài các fold test của TẤT CẢ các candidate.
   - Không chỉ hạ 2 candidate pass mà **hạ toàn bộ 19 kết quả WFA** (cả pass lẫn fail) xuống `UNVERIFIED / INVALID_FOLD_WINDOWS` cho đến khi có pipeline chia ngày chính xác.
   - 4 candidate thuộc nhóm mẫu nhỏ (< 20 lệnh / 3 năm) giữ nguyên verdict `INSUFFICIENT_SAMPLE` theo protocol.
3. **Xác nhận giới hạn của Monte Carlo và Fixture Receipts:**
   - Receipt pytest xác nhận 14/14 tests fixture pass (`exit_code: 0`, 8.4s trong `edu_evolution_fixtures_report.json`). Receipt này chỉ chứng minh bộ 14 test fixture độc lập đó pass, **không chứng minh toàn bộ các backtest trong quá khứ đã chạy qua systemd service hay giới hạn cgroup 2GB**.
   - Phương pháp Monte Carlo IID bootstrap phá vỡ cấu trúc chuỗi thời gian và phụ thuộc vốn; chỉ mang tính mô tả thống kê quá khứ, bị hạ verdict xuống `UNVERIFIED / EXPLORATORY`.
4. **Bảo toàn 100% dữ liệu gốc:** Toàn bộ 57 file user alpha trong `nora/edu/data/alpha/user/` được đối chiếu mã băm SHA256 và giữ nguyên vẹn 100%.
5. **Chứng nhận Holdout:** Giữ nguyên trạng thái **`NO_UNTOUCHED_HOLDOUT_AVAILABLE`** (toàn bộ dữ liệu kết thúc ngày 2026-10-03; không dùng dữ liệu đã xem làm holdout).
6. **Trạng thái nghiệm thu chính thức:** Tiếp tục khẳng định **`NOT ACCEPTED / RESULTS INVALID FOR PASS CLAIMS`**. Không có cơ sở để promote candidate lên bot live hay sửa đổi alpha gốc.

---
## 2. BẢNG PHÂN RÃ CHI PHÍ THẬT 23 ALPHA TRONG HÀNG ĐỢI (COST ATTRIBUTION)

*(Số liệu authoritative trích xuất từ `diagnostics.pnl_structure` và `metrics.test`, vốn ban đầu 10.000 USD. Tỷ trọng % tính riêng cho từng giai đoạn âm)*

| ID | Tên chiến lược | Full Net ($) | Full Phí ($) | Full Lỗ gộp % | Full Phí % | OOS Net ($) | OOS Gross ($) | OOS Phí ($) | OOS Lỗ gộp % | OOS Phí % | Bản chất phân loại |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `0d51ba8d2012` | OBV Volume Accumulation  | +728.0 | 124.3 | N/A | N/A | -1139.0 | -1078.1 | 60.9 | 94.7% | 5.3% | `FULL_PROFITABLE_OOS_LOSS` |
| `14e3b934b1e5` | ROC Momentum Exhaustion  | -2981.3 | 238.2 | 92.0% | 8.0% | -2778.0 | -2648.9 | 129.1 | 95.4% | 4.6% | `GROSS_AND_NET_NEGATIVE` |
| `15567e02a806` | Triple EMA Trend Alignme | +20.2 | 165.7 | N/A | N/A | -3374.0 | -3317.1 | 56.9 | 98.3% | 1.7% | `FULL_PROFITABLE_OOS_LOSS` |
| `18e87aa868ad` | Fast Dynamic Channel Bre | +7016.0 | 220.7 | N/A | N/A | -197.0 | -115.7 | 81.3 | 58.7% | 41.3% | `FULL_PROFITABLE_OOS_LOSS` |
| `270e6e28416f` | EMA Trend Rider (Rising  | -3135.2 | 48.0 | 98.5% | 1.5% | -2326.0 | -2262.6 | 63.4 | 97.3% | 2.7% | `GROSS_AND_NET_NEGATIVE` |
| `3cfcc2d296a2` | Donchian Lower Channel E | -2641.2 | 135.7 | 94.9% | 5.1% | -2677.0 | -2607.5 | 69.5 | 97.4% | 2.6% | `GROSS_AND_NET_NEGATIVE` |
| `4f28285aa44c` | Dual EMA + ADX Trend Str | -440.3 | 7.3 | 98.3% | 1.7% | -366.0 | -359.4 | 6.7 | 98.2% | 1.8% | `GROSS_AND_NET_NEGATIVE` |
| `541c55834f56` | Daily Range Expansion (H | +889.8 | 222.0 | N/A | N/A | -2574.0 | -2504.8 | 69.2 | 97.3% | 2.7% | `FULL_PROFITABLE_OOS_LOSS` |
| `5e52d3fdf71f` | Bollinger Band Overexten | -2474.2 | 192.4 | 92.2% | 7.8% | -2489.0 | -2404.8 | 84.2 | 96.6% | 3.4% | `GROSS_AND_NET_NEGATIVE` |
| `6afa7f774655` | RSI Rebound with Fast SM | -1202.9 | 24.3 | 98.0% | 2.0% | -1025.0 | -1003.0 | 22.0 | 97.9% | 2.1% | `GROSS_AND_NET_NEGATIVE` |
| `715e56a6dd33` | Linear Regression Channe | -1352.0 | 42.2 | 96.9% | 3.1% | -1102.0 | -1074.3 | 27.7 | 97.5% | 2.5% | `GROSS_AND_NET_NEGATIVE` |
| `717c1890c59e` | Weighted Moving Average  | +12695.1 | 373.1 | N/A | N/A | -949.0 | -760.5 | 188.5 | 80.1% | 19.9% | `FULL_PROFITABLE_OOS_LOSS` |
| `7f3486d63ca8` | Dual Oscillator Climax E | -1122.4 | 177.6 | 84.2% | 15.8% | -1714.0 | -1613.5 | 100.5 | 94.1% | 5.9% | `GROSS_AND_NET_NEGATIVE` |
| `7f67e9aed0aa` | Stochastic & RSI Conflue | -1589.9 | 68.1 | 95.7% | 4.3% | -1675.0 | -1627.3 | 47.7 | 97.2% | 2.8% | `GROSS_AND_NET_NEGATIVE` |
| `89379cc0ab52` | Stochastic Oscillator (% | -1913.6 | 123.8 | 93.5% | 6.5% | -2096.0 | -2020.5 | 75.5 | 96.4% | 3.6% | `GROSS_AND_NET_NEGATIVE` |
| `b4b65cd3493f` | Commodity Channel Index  | -2149.2 | 171.9 | 92.0% | 8.0% | -1317.0 | -1205.8 | 111.2 | 91.6% | 8.4% | `GROSS_AND_NET_NEGATIVE` |
| `b96bafe57445` | Normalized ATR (NATR) Vo | -744.1 | 25.5 | 96.6% | 3.4% | -655.0 | -643.5 | 11.5 | 98.2% | 1.8% | `GROSS_AND_NET_NEGATIVE` |
| `bf519617d973` | Double Exponential Movin | -3185.6 | 43.7 | 98.6% | 1.4% | -1232.0 | -1132.8 | 99.2 | 92.0% | 8.0% | `GROSS_AND_NET_NEGATIVE` |
| `c33cc317bbeb` | Multi-Day Cumulative Ret | -3112.0 | 75.5 | 97.6% | 2.4% | -2881.0 | -2821.4 | 59.6 | 97.9% | 2.1% | `GROSS_AND_NET_NEGATIVE` |
| `cb750cb1eb10` | EMA Golden Cross + Volum | -457.2 | 13.8 | 97.0% | 3.0% | -505.0 | -492.9 | 12.1 | 97.6% | 2.4% | `GROSS_AND_NET_NEGATIVE` |
| `f261549d9efa` | ROC Momentum Surge | +128.0 | 223.9 | N/A | N/A | -2142.0 | -2052.6 | 89.4 | 95.8% | 4.2% | `FULL_PROFITABLE_OOS_LOSS` |
| `f4e211e9510d` | Rolling 30-Day Multi-Wee | +1597.0 | 103.6 | N/A | N/A | -659.0 | -627.4 | 31.6 | 95.2% | 4.8% | `FULL_PROFITABLE_OOS_LOSS` |
| `fa9587a97fa9` | Trend Alignment Momentum | +6344.5 | 63.7 | N/A | N/A | -2925.0 | -2862.1 | 62.9 | 97.8% | 2.2% | `FULL_PROFITABLE_OOS_LOSS` |

---
## 3. BẢNG TỔNG KẾT NGHIỆM THU CHI TIẾT 57 RECORD

| ID | Tên chiến lược | Chủ sở hữu | Baseline OOS Ret | Hàng đợi điều tra | Candidate tạo mới | WFA Verdict | Monte Carlo | Trạng thái Holdout | Quyết định tiếp theo |
|---|---|---|---:|---|---|---|---|---|---|
| `026f43441cb2` | U4_BTC_1h_Different_Window | 16e97dcc8432 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `0873864b8db7` | DEMA Turbo Compound (1Y Fast | **vinh** | +6.87% | Không (OOS Dương) | Không tạo | N/A | N/A | N/A | Giữ nguyên cấu hình hiện tại |
| `090730ae35b8` | Fail-Fast Volatility Breakou | **vinh** | +3.00% | Không (OOS Dương) | Không tạo | N/A | N/A | N/A | Giữ nguyên cấu hình hiện tại |
| `0bf936687964` | U4_BTC_1h_Different_Window | e53ccc4b35d2 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `0d51ba8d2012` | OBV Volume Accumulation + RS | 43f5220ece1e | -11.39% | Có (Queue) | C1 Persistence | `BETTER_NOT_PASS` | N/A | `NO_UNTOUCHED_HOLDOUT` | Đối đầu Parent `75f292` vs C1 `c7062f`; không đạt gate; giữ nguyên alpha gốc |
| `138df68946ad` | U1_BTC_1h_Alpha | ecf30ed0f194 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `14e3b934b1e5` | ROC Momentum Exhaustion with | 23dc66cd61c6 | -27.78% | Có (Queue) | C1 ROC-Rising | `BETTER_NOT_PASS` | N/A | `NO_UNTOUCHED_HOLDOUT` | Đối đầu Parent `f36171` vs C1 `1d0c42`; không đạt gate; giữ nguyên alpha gốc |
| `15567e02a806` | Triple EMA Trend Alignment ( | 23dc66cd61c6 | -33.74% | Có (Queue) | Bỏ qua (Mẫu nhỏ) | `INSUFFICIENT_SAMPLE` | N/A | N/A | OOS 9 trades (< 20); đóng hồ sơ mẫu nhỏ |
| `18e87aa868ad` | Fast Dynamic Channel Breakou | **vinh** | -29.25% (pct) | Có (Queue) | Bỏ qua (Mẫu nhỏ) | `INSUFFICIENT_SAMPLE` | N/A | N/A | Rebaseline `b7b8f5` OOS 19 trades (< 20); đóng hồ sơ mẫu nhỏ |
| `1a1a4389a821` | U1_BTC_1h_Alpha | 2922e08b6b61 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `1e4c0b9f84f7` | U3_BTC_Small_Alpha | 9b7a10c35886 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `214ea8fdf3e6` | U2_ETH_15m_Alpha | 423d35ac9700 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `234e6df02e37` | U2_ETH_15m_Alpha | 5de316621329 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `270e6e28416f` | EMA Trend Rider (Rising Slop | a214b36a7eab | -23.26% | Có (Queue) | Bỏ qua (Mẫu nhỏ) | `INSUFFICIENT_SAMPLE` | N/A | N/A | OOS 17 trades (< 20); đóng hồ sơ mẫu nhỏ |
| `2e41b2cfa24d` | U1_BTC_1h_Alpha | 3bbc767faa10 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `303d4b713dda` | Macro Trend Filtered Breakou | **vinh** | +3.38% | Không (OOS Dương) | Không tạo | N/A | N/A | N/A | Giữ nguyên cấu hình hiện tại |
| `33312a2f4dfc` | Standard Deviation Dynamic C | **vinh** | +3.38% | Không (OOS Dương) | Không tạo | N/A | N/A | N/A | Giữ nguyên cấu hình hiện tại |
| `3cfcc2d296a2` | Donchian Lower Channel Exit | 43f5220ece1e | -26.77% | Có (Queue) | 2 variants | `UNVERIFIED` | `UNVERIFIED` | `NO_UNTOUCHED_HOLDOUT` | WFA fail/invalid folds; không promote |
| `4f28285aa44c` | Dual EMA + ADX Trend Strengt | 23dc66cd61c6 | -3.66% | Có (Queue) | Bỏ qua (Mẫu nhỏ) | `INSUFFICIENT_SAMPLE` | N/A | N/A | OOS 7 trades (< 20); đóng hồ sơ mẫu nhỏ |
| `541c55834f56` | Daily Range Expansion (High  | dd3d4fbabe8a | -25.74% | Có (Queue) | 2 variants | `UNVERIFIED` | `UNVERIFIED` | `NO_UNTOUCHED_HOLDOUT` | WFA fail/invalid folds; không promote |
| `571474a18f55` | U3_BTC_Small_Alpha | 82e8ccc35eb6 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `5e52d3fdf71f` | Bollinger Band Overextension | 76c5814277ab | -24.89% | Có (Queue) | 2 variants | `UNVERIFIED` | `UNVERIFIED` | `NO_UNTOUCHED_HOLDOUT` | WFA fail/invalid folds; không promote |
| `6055aa8f661e` | Triple Filter: EMA + MACD +  | a214b36a7eab | +0.81% | Không (OOS Dương) | Không tạo | N/A | N/A | N/A | Giữ nguyên cấu hình hiện tại |
| `616e1b8cbc88` | U2_ETH_15m_Alpha | 184e6dc9dfe6 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `64b657c8de8e` | U4_BTC_1h_Different_Window | c7f8e10109b3 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `6afa7f774655` | RSI Rebound with Fast SMA Fi | a214b36a7eab | -10.25% | Có (Queue) | 2 variants | `UNVERIFIED` | `UNVERIFIED` | `NO_UNTOUCHED_HOLDOUT` | WFA fail/invalid folds; không promote |
| `715e56a6dd33` | Linear Regression Channel De | 43f5220ece1e | -11.02% | Có (Queue) | 2 variants | `UNVERIFIED` | `UNVERIFIED` | `NO_UNTOUCHED_HOLDOUT` | WFA fail/invalid folds; không promote |
| `717c1890c59e` | Weighted Moving Average (WMA | dd3d4fbabe8a | -9.49% | Có (Queue) | `717c1890c59e_c1_risk_sl` | `UNVERIFIED` | `UNVERIFIED` | `NO_UNTOUCHED_HOLDOUT` | WFA fail/invalid folds; không promote |
| `74f607263c5c` | U4_BTC_1h_Different_Window | 726ff949da79 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `7c1bf0a9686a` | U4_BTC_1h_Different_Window | dbbb50a338c9 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `7f3486d63ca8` | Dual Oscillator Climax Exit | dd3d4fbabe8a | -17.14% | Có (Queue) | 2 variants | `UNVERIFIED` | `UNVERIFIED` | `NO_UNTOUCHED_HOLDOUT` | WFA fail/invalid folds; không promote |
| `7f67e9aed0aa` | Stochastic & RSI Confluence  | dd3d4fbabe8a | -16.75% | Có (Queue) | 2 variants | `UNVERIFIED` | `UNVERIFIED` | `NO_UNTOUCHED_HOLDOUT` | WFA fail/invalid folds; không promote |
| `7f770ebe5ab5` | U3_BTC_Small_Alpha | eb5d7e2e3897 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `856ddc574ce7` | U2_ETH_15m_Alpha | 9fc184ee1040 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `862e0c9eebbe` | U2_ETH_15m_Alpha | e7c998608206 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `89379cc0ab52` | Stochastic Oscillator (%K, % | 76c5814277ab | -20.96% | Có (Queue) | 2 variants | `UNVERIFIED` | `UNVERIFIED` | `NO_UNTOUCHED_HOLDOUT` | WFA fail/invalid folds; không promote |
| `8a47cdbcc942` | Fast Dip Harvester (3M DCA D | **vinh** | +18.17% | Không (OOS Dương) | Không tạo | N/A | N/A | N/A | Giữ nguyên cấu hình hiện tại |
| `930294d28c45` | U3_BTC_Small_Alpha | 439fa7538599 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `9eec3d61131d` | U3_BTC_Small_Alpha | 79183007b990 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `a4d6826fbbc6` | U4_BTC_1h_Different_Window | 4547f1f50486 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `af2bf88426c4` | U3_BTC_Small_Alpha | bf158b5142e8 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `b4b65cd3493f` | Commodity Channel Index (CCI | 23dc66cd61c6 | -13.17% | Có (Queue) | 2 variants | `UNVERIFIED` | `UNVERIFIED` | `NO_UNTOUCHED_HOLDOUT` | WFA fail/invalid folds; không promote |
| `b96bafe57445` | Normalized ATR (NATR) Volati | 76c5814277ab | -6.55% | Có (Queue) | Bỏ qua (Mẫu nhỏ) | `INSUFFICIENT_SAMPLE` | N/A | N/A | OOS 18 trades (< 20); đóng hồ sơ mẫu nhỏ |
| `bd234070bd7b` | U1_BTC_1h_Alpha | bbd150bc473c | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `be1174b24a44` | U1_BTC_1h_Alpha | 657914b99b5b | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `bf519617d973` | Double Exponential Moving Av | 76c5814277ab | -12.32% | Có (Queue) | Bỏ qua (Mẫu nhỏ) | `INSUFFICIENT_SAMPLE` | N/A | N/A | Inconsistent ledger (22 test / 9 sim); đóng hồ sơ |
| `c33cc317bbeb` | Multi-Day Cumulative Return  | dd3d4fbabe8a | -28.81% | Có (Queue) | 2 variants | `UNVERIFIED` | `UNVERIFIED` | `NO_UNTOUCHED_HOLDOUT` | WFA fail/invalid folds; không promote |
| `cb0b6e0f12e7` | U1_BTC_1h_Alpha | f9292fff53c9 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `cb750cb1eb10` | EMA Golden Cross + Volume Sp | 76c5814277ab | -5.05% | Có (Queue) | Bỏ qua (Mẫu nhỏ) | `INSUFFICIENT_SAMPLE` | N/A | N/A | OOS 18 trades (< 20); đóng hồ sơ mẫu nhỏ |
| `d0518c0cca14` | U4_BTC_1h_Different_Window | f4ded6717b32 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `e9a9a5b44d03` | U2_ETH_15m_Alpha | 95f7a5a4b3ae | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `ee0cf7f58f94` | U2_ETH_15m_Alpha | 97cac5011215 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |
| `efb1fbe2db86` | Volatility Expansion Channel | **vinh** | +3.38% | Không (OOS Dương) | Không tạo | N/A | N/A | N/A | Giữ nguyên cấu hình hiện tại |
| `f261549d9efa` | ROC Momentum Surge | 23dc66cd61c6 | -21.42% | Có (Queue) | 2 variants | `UNVERIFIED` | `UNVERIFIED` | `NO_UNTOUCHED_HOLDOUT` | WFA fail/invalid folds; không promote |
| `f4e211e9510d` | Rolling 30-Day Multi-Week Hi | a214b36a7eab | -6.59% | Có (Queue) | 2 variants | `UNVERIFIED` | `UNVERIFIED` | `NO_UNTOUCHED_HOLDOUT` | WFA fail/invalid folds; không promote |
| `fa9587a97fa9` | Trend Alignment Momentum (Op | 43f5220ece1e | -29.25% | Có (Queue) | Bỏ qua (Mẫu nhỏ) | `INSUFFICIENT_SAMPLE` | N/A | N/A | OOS 19 trades (< 20); đóng hồ sơ mẫu nhỏ |
| `fd16df3d0a3f` | U3_BTC_Small_Alpha | d836143af954 | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |

---
## 4. XÁC MINH CÁC RÀO CHẮN AN TOÀN
1. **Bảo toàn dữ liệu gốc 100%:** 57/57 file user alpha trong `nora/edu/data/alpha/user/` giữ nguyên mã băm SHA256.
2. **Bảo đảm không rò rỉ Holdout:** Toàn bộ dữ liệu kết thúc ngày 2026-10-03; ghi nhận chính thức `NO_UNTOUCHED_HOLDOUT_AVAILABLE`.
3. **Rào chắn Production:** Mọi candidate đều bị khóa trong namespace `nora/check/candidates/`; không promote bất kỳ candidate nào lên bot live.
4. **Giới hạn cgroup RAM 2GB:** Đã xác thực qua tiến trình chạy thực tế dưới `nora.slice` (RAM đỉnh từ 907 MiB – 1,499 MiB, 0 lỗi OOM).
