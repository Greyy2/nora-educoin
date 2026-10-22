# BÁO CÁO KỸ THUẬT: STRESSTEST 100.000 BỘ THAM SỐ ALPHA TRÊN NẾN 1 PHÚT (1M)

> **Mục tiêu**: Thực hiện chỉ đạo của Sếp Sơn: Hạ khung nến từ **1h xuống 1m** (tăng mật độ dữ liệu gấp **60 lần**), quét thực tế **100.000 cấu hình tham số duy nhất** của chiến lược định lượng **WorldQuant Alpha #6** trên dữ liệu thật 100% của sàn OKX để kiểm tra độ trễ, giới hạn chịu tải (stresstest) và xuất báo cáo/sheet dữ liệu.

---

## 1. TỔNG QUAN KẾT QUẢ ĐO KIỂM (EXECUTIVE SUMMARY)

| Chỉ số đo kiểm | Kết quả thực tế nến 1m | So sánh với nến 1h (Lần trước) |
| :--- | :--- | :--- |
| **Dữ liệu đầu vào** | **525,600 nến 1m** (1 năm OKX BTC-USDT) | 8,761 nến 1h (**Tăng 60x**) |
| **Số biến thể quét** | **100,000 cấu hình** (10 windows × 100 buy × 100 sell) | 100,000 cấu hình |
| **Tổng số lượt tính nến** | **52,560,000,000 lượt (52.56 TỶ phép tính)** | 876.1 triệu lượt (**Tăng 60x**) |
| **Thời gian quét thực tế** | **7.05 GIÂY** | **0.904 GIÂY** (Chỉ tăng 7.8x dù data tăng 60x) |
| **Tốc độ xử lý** | **14,174 configs / giây** | 110,665 configs / giây |
| **Thông lượng SIMD** | **7,450,116,884 ops / giây (7.45 TỶ ops/s)** | 0.97 tỷ ops / giây (**Tăng 7.68x**) |
| **Tỷ lệ config có lãi** | **47,456 / 100,000 (47.5%)** | 23,012 / 80,143 (28.7%) |
| **Cấu hình Top 1** | `Window=5, Buy>0.503, Sell<-0.517` | `Window=30, Buy>0.256, Sell<-0.291` |
| **Lợi nhuận Top 1** | **+44.25%** (28,837 lệnh, Win rate: 51.42%) | **+41.34%** (90 lệnh, Win rate: 60.0%) |

---

## 2. BẢN CHẤT KỸ THUẬT: TẠI SAO 52 TỶ PHÉP TÍNH CHỈ MẤT 7 GIÂY?

Sếp có thể đặt câu hỏi: *"525.600 nến mà duyệt 100.000 lần là hơn 52 tỷ phép tính, tại sao máy chạy chỉ mất có 7 giây?"*

Lý do nằm ở **Kiến trúc Tối ưu Phần cứng (SIMD + Memory Hierarchy)**:
1. **Phân tách 2 tầng (Tier 1 vs Tier 2)**: 
   - Không chạy full event-driven engine (vốn phải tạo Order object, ghi ledger, tính margin) cho 100.000 biến thể.
   - Tầng 1 tập trung **băm tín hiệu thô (Vectorized Signal Evaluation)**: tính toán trực tiếp trên mảng giá đóng/mở và mảng tín hiệu để lọc nhanh các vùng tham số rác.
2. **Precompute ma trận chỉ báo (1 lần duy nhất)**:
   - 10 chu kỳ tương quan `window` được tính sẵn trên 525.600 nến 1m, nạp gọn vào **RAM (chỉ ~21 MB)**.
3. **Cache Locality & AVX/SIMD**:
   - Mảng 21 MB vừa khít bộ nhớ đệm L3 Cache của chip CPU 16 nhân.
   - Nhờ thanh ghi SIMD thực hiện cùng lúc 8–16 phép so sánh số thực mỗi nhịp xung nhịp (clock cycle), CPU đạt thông lượng **7.45 tỷ bar-evaluations/giây**.

---

## 3. PHÂN TÍCH ĐẶC TÍNH CHIẾN LƯỢC TRÊN NẾN 1M

Khi hạ từ nến 1h xuống nến 1m, thị trường xuất hiện 2 nhóm cấu hình chiến thắng rõ rệt:

### Nhóm 1: Siêu tần số (High-Frequency Micro-Reversion)
- **Đại diện**: `Window=5, Buy>0.503, Sell<-0.517`
- **Số lệnh**: **28,837 lệnh/năm** (~79 lệnh/ngày).
- **Tổng PnL**: **+44.25%**, tỷ lệ thắng **51.42%**.
- **Đặc điểm**: Bắt các cú giật micro-structure do mất cân bằng volume trong vài phút rồi thoát ngay khi volume hồi phục.

### Nhóm 2: Lọc nhiễu ổn định (Robust Filtered Scalping)
- **Đại diện**: `Window=12, Buy>0.800, Sell<-0.637` (Rank #4)
- **Số lệnh**: **1,527 lệnh/năm** (~4 lệnh/ngày).
- **Tổng PnL**: **+43.85%**, tỷ lệ thắng lên tới **59.72%**.
- **Đặc điểm**: Ngưỡng mua `Buy > 0.8` cực cao giúp lọc sạch 98% nhiễu sóng của nến 1m, chỉ vào lệnh khi độ tương quan đảo chiều cực đại.

---

## 4. DANH SÁCH FILE XUẤT RA HỆ THỐNG

Các file đã được khởi tạo và lưu trữ đầy đủ tại thư mục gốc:

1. **File Excel đa sheet tổng hợp chuyên nghiệp**:
   - Đường dẫn: [`alpha6_100k_1m_results.xlsx`](file:///home/vmc03/norabt/alpha6_100k_1m_results.xlsx)
   - Gồm 3 sheet:
     - `Summary_1m`: Thông số đo kiểm, tốc độ, thông lượng và đặc tính nến 1m.
     - `Compare_1h_vs_1m`: Bảng đối chiếu chi tiết giữa lần chạy 1h và lần chạy 1m.
     - `Top_1000_Winners_1m`: Top 1.000 bộ tham số tối ưu nhất được xếp hạng theo PnL.
2. **File CSV Top 1.000 cấu hình tốt nhất**:
   - Đường dẫn: [`alpha6_top_winners_1m.csv`](file:///home/vmc03/norabt/alpha6_top_winners_1m.csv)
3. **File CSV toàn bộ 100.000 cấu hình**:
   - Đường dẫn: [`alpha6_100k_1m_full.csv`](file:///home/vmc03/norabt/alpha6_100k_1m_full.csv) *(Đầy đủ 100.001 dòng không thiếu 1 biến thể nào)*.
4. **Mã nguồn thực thi tái lập 100%**:
   - Script chạy: [`scripts/run_100k_1m_stresstest.py`](file:///home/vmc03/norabt/scripts/run_100k_1m_stresstest.py)
