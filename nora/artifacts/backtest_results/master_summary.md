# BÁO CÁO MASTER BACKTEST TOÀN BỘ ALPHA (COIN & EDU: 2024 - 2026)

- **Thời gian chạy**: `2024-01-01` đến `2026-09-01` (Catalog OKX)
- **Vốn khởi điểm**: `10,000.00 USDT`
- **Mục đích**: Kiểm tra thông tuyến kỹ thuật đường ống backtest và xác thực hợp đồng AST của từng Alpha (Smoke-Run Kỹ Thuật)
- **CẢNH BÁO PHẠM VI**: Smoke run kỹ thuật hoàn tất; CHƯA CÓ ĐÁNH GIÁ HIỆU SUẤT ALPHA (đang chặn bởi 4 gates rủi ro và chưa kiểm định OOS/WFA).

## 1. Kho COIN — System Legs (Đơn Lẻ & Combo)
*Lưu ý: Các legs được ép chạy trên khung 1h để kiểm tra thông tuyến đường ống; cấu hình native của KEMA trong hệ thống là 4h.*
| ID Alpha | Tên Chiến Lược | Phân Loại | Lệnh (Trades) | Thắng (Win%) | Lợi Nhuận (Ret%) | Sụt Giảm (MDD%) | Sharpe | Simulated Fee (USD, preset proxy) | Trạng Thái Pipeline |
|---|---|---|---|---|---|---|---|---|---|
| `kema_long` | System Leg kema_long | COIN System Leg | 40 | 27.5% | +3.09% | 5.22% | 0.57 | 27.7 | ✅ Pipeline SUCCESS |
| `kema_short` | System Leg kema_short | COIN System Leg | 40 | 37.5% | -2.63% | 4.45% | -0.44 | 28.6 | ✅ Pipeline SUCCESS |
| `sideway_long` | System Leg sideway_long | COIN System Leg | 2 | 50.0% | -0.18% | 0.88% | -0.14 | 4.6 | ✅ Pipeline SUCCESS |
| `sideway_short` | System Leg sideway_short | COIN System Leg | 3 | 100.0% | +0.93% | 0.78% | 0.96 | 11.3 | ✅ Pipeline SUCCESS |
| `dca_long` | System Leg dca_long | COIN System Leg | 87 | 87.4% | -0.79% | 1.82% | -0.45 | 16.5 | ✅ Pipeline SUCCESS |
| `dca_short` | System Leg dca_short | COIN System Leg | 67 | 88.1% | +0.40% | 0.92% | 0.25 | 17.6 | ✅ Pipeline SUCCESS |
| `combo_6_system_legs` | Combo 6 System Legs (Portfolio | COIN Portfolio | 100 | 56.0% | +0.52% | 4.59% | 0.40 | 45.3 | ✅ Pipeline SUCCESS |

## 2. Kho COIN — User Alphas V2 & Top Agent Drafts
*Lưu ý: User V2 chạy rổ BTC/ETH/SOL ở đòn bẩy 10x (vượt policy ≤3x) và chưa có cơ chế Master Risk quản lý rủi ro tổng thể cho toàn rổ. Top Agent chỉ lấy tham số thoát/sizing từ OKX, điều kiện vào lệnh là proxy nghiên cứu.*
| ID Alpha | Tên Chiến Lược | Phân Loại | Lệnh (Trades) | Thắng (Win%) | Lợi Nhuận (Ret%) | Sụt Giảm (MDD%) | Sharpe | Simulated Fee (USD, preset proxy) | Trạng Thái Pipeline |
|---|---|---|---|---|---|---|---|---|---|
| `efa90f74cd08_v2` | Donchian Channel Breakout V2 ( | COIN User V2 | 45 | 33.3% | +0.72% | 2.85% | 0.16 | 7.5 | ✅ Pipeline SUCCESS |
| `18e87aa868ad_v2` | Fast Dynamic Channel Breakout  | COIN User V2 | 53 | 41.5% | +3.22% | 2.85% | 0.68 | 11.3 | ✅ Pipeline SUCCESS |
| `33312a2f4dfc_v2` | StdDev Dynamic Channel Breakou | COIN User V2 | 46 | 45.7% | +3.61% | 2.50% | 0.73 | 10.2 | ✅ Pipeline SUCCESS |
| `okx_01pp` | Top Agent okx_01pp | COIN Top Agent | 1197 | 58.1% | -5.60% | 6.00% | -1.88 | 281.1 | ✅ Pipeline SUCCESS |
| `okx_auroraxwt` | Top Agent okx_auroraxwt | COIN Top Agent | 467 | 15.8% | -28.68% | 30.04% | -3.42 | 679.8 | ✅ Pipeline SUCCESS |
| `okx_dark_wood_dahlia` | Top Agent okx_dark_wood_dahlia | COIN Top Agent | 1963 | 57.5% | -13.65% | 13.66% | -4.79 | 577.6 | ✅ Pipeline SUCCESS |

## 3. Kho EDU — Canonical Templates & Mẫu 10 Active User Alphas
*Lưu ý: Chạy trên tập mẫu kỹ thuật 10/57 alphas active lấy theo thứ tự index đầu danh mục (`active_user_alphas[:10]`); đây là mẫu tuần tự kiểm thử đường ống, KHÔNG mang tính đại diện thống kê cho cả kho 57 alphas EDU. Giữ nguyên hiện trạng code và sizing của học viên.*
| ID Alpha | Tên Chiến Lược | Phân Loại | Lệnh (Trades) | Thắng (Win%) | Lợi Nhuận (Ret%) | Sụt Giảm (MDD%) | Sharpe | Simulated Fee (USD, preset proxy) | Trạng Thái Pipeline |
|---|---|---|---|---|---|---|---|---|---|
| `edu_canonical_beginner_dual_ema` | Nora EDU — Beginner Dual EMA T | EDU Canonical | 668 | 29.0% | -7.81% | 8.76% | -1.35 | 380.2 | ✅ Pipeline SUCCESS |
| `edu_canonical_advanced_volatility_breakout` | Nora EDU — Advanced Volatility | EDU Canonical | 102 | 43.1% | +1.55% | 4.13% | 0.31 | 79.2 | ✅ Pipeline SUCCESS |
| `026f43441cb2` | EDU User 026f4344 | EDU Active User | 1 | 0.0% | +2.34% | 4.86% | 0.33 | 0.5 | ✅ Pipeline SUCCESS |
| `0873864b8db7` | EDU User 0873864b | EDU Active User | 4 | 25.0% | -27.04% | 30.76% | -0.61 | 41.0 | ✅ Pipeline SUCCESS |
| `090730ae35b8` | EDU User 090730ae | EDU Active User | 17 | 35.3% | +64.69% | 25.19% | 0.89 | 200.5 | ✅ Pipeline SUCCESS |
| `0bf936687964` | EDU User 0bf93668 | EDU Active User | 1 | 0.0% | +2.34% | 4.86% | 0.33 | 0.5 | ✅ Pipeline SUCCESS |
| `0d51ba8d2012` | EDU User 0d51ba8d | EDU Active User | 23 | 13.0% | -4.64% | 4.74% | -1.17 | 14.1 | ✅ Pipeline SUCCESS |
| `138df68946ad` | EDU User 138df689 | EDU Active User | 1 | 0.0% | +2.34% | 4.86% | 0.33 | 0.5 | ✅ Pipeline SUCCESS |
| `14e3b934b1e5` | EDU User 14e3b934 | EDU Active User | 76 | 40.8% | +0.32% | 5.60% | 0.07 | 44.4 | ✅ Pipeline SUCCESS |
| `15567e02a806` | EDU User 15567e02 | EDU Active User | 10 | 50.0% | +77.04% | 31.57% | 0.93 | 188.9 | ✅ Pipeline SUCCESS |
| `18e87aa868ad` | EDU User 18e87aa8 | EDU Active User | 20 | 30.0% | +61.24% | 21.90% | 0.91 | 194.2 | ✅ Pipeline SUCCESS |
| `1a1a4389a821` | EDU User 1a1a4389 | EDU Active User | 1 | 0.0% | +2.34% | 4.86% | 0.33 | 0.5 | ✅ Pipeline SUCCESS |

## 4. Đánh Giá Kỹ Thuật Tổng Hợp & Giới Hạn Nghiệm Thu
- **Kết luận cốt lõi**: Smoke run kỹ thuật hoàn tất; chưa có đánh giá hiệu suất alpha.
- **Ý nghĩa trạng thái Pipeline SUCCESS**: Trạng thái `Pipeline SUCCESS` chỉ xác nhận quá trình biên dịch AST, nạp dữ liệu, sinh tín hiệu và thực thi mô phỏng hoàn tất không có lỗi runtime crash. Đây KHÔNG phải chứng nhận chất lượng alpha hay chứng nhận accounting pass đối với thị trường thực tế.
- **Bốn Gates Rủi Ro Còn Mở Chặn Đánh Giá Hiệu Suất**:
  1. *Chính sách Risk per trade*: Khác biệt giữa 0.5% (System legs/EDU) và 0.25% (Top agent/V2) chưa được Owner chốt làm chuẩn duy nhất.
  2. *Chi phí mô phỏng*: Preset 0.00160 là giả định nghiên cứu (UNVERIFIED), chưa phản ánh trượt giá orderbook L2 thực tế.
  3. *Mô hình Funding Rate*: Chưa tích hợp funding rate lịch sử thực tế của sàn OKX.
  4. *Đòn bẩy chưa kẹp trần*: Policy Master Risk quy định ≤ 3x nhưng engine hiện chưa được kẹp trần runtime (Top Agent chạy 20x, User V2 chạy 10x).
- **Độ Phủ & Tính Đại Diện Của Tập Mẫu EDU**: Tập mẫu 10/57 alphas EDU active được lấy tuần tự theo thứ tự xuất hiện đầu danh mục (`active_user_alphas[:10]`), là mẫu kiểm thử kỹ thuật đường ống, **KHÔNG mang tính đại diện thống kê** cho toàn bộ 57 alphas trong kho EDU. Bốn bài tập có kết quả tương đồng (+2.34%) do đặc tính mã nguồn học viên chỉ có điều kiện mua và không có điều kiện bán (hành vi Buy & Hold).
- **Phạm vi & Giới hạn Schema Ledger**: Đã xuất 25 raw trade ledgers dạng transaction execution (ghi nhận enter/close price, qty, fees, pnl). Schema hiện tại chưa bao gồm stop trigger price, nguồn fill (fill source/path), hay slippage attribution.
- **Tình trạng Worktree & Bản chất Provenance**: Input manifest là bản **tái dựng hậu kiểm** (`post_run_reconstruction`) từ artifact kết quả, sổ cái và mã nguồn trên đĩa, không phải snapshot tự động được thu thập trong thời gian chạy thực tế. Môi trường kiểm toán ghi nhận `git_dirty = true`; giá trị `tracked_dirty_diff_sha256` là mã băm của git diff áp dụng riêng cho các **tracked files** bị sửa đổi, **hoàn toàn không bao gồm nội dung của các file untracked**.
- **Kết Quả Kiểm Thẩm Định Test Suites & Git Cleanliness**:
  + `nora/coin/tests/test_master_smoke_provenance_and_closure.py`: **5/5 PASS (100%)** (xác nhận toàn vẹn 25 ledgers, provenance manifest/hashes, attribution auroraxwt, parity EDU/COIN 11 trade rows, và audit văn phong không overclaim).
  + `git diff --check`: **0 cảnh báo/lỗi (sạch hoàn toàn)**.
- **Cổng rủi ro & nghiệm thu**: Đánh giá hiệu suất và thăng hạng vẫn tạm dừng (`promotion_allowed = false`, `execution_implemented = false`); không coi kết quả smoke-run là bằng chứng giao dịch có lãi thực tế hay sẵn sàng cho testnet/live.