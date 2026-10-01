# 04. ĐẶC TẢ CHIẾN THUẬT & PLAYBOOK GIAO DỊCH (PLAYBOOK SPECIFICATIONS)

Tài liệu này chuẩn hóa toàn bộ các chiến lược (Playbooks) được sinh ra từ lõi nghiên cứu định lượng của Nora. Mỗi chiến thuật đều xuất phát từ biến cố vi mô theo thời gian nội tại (Intrinsic Time) và phải vượt qua bài kiểm tra ma sát (Cost Hurdle).

---

## 1. Playbook 1: `DC_OVERSHOOT_FADE` (Đánh Chặn Sóng Rướn Hụt Hơi)

### 1.1. Bối Cảnh Thị Trường (Regime)
- Áp dụng khi thị trường ở trạng thái **`RANGE_CHOP_REGIME`** (Đi ngang / Nhiễu vi mô).
- Chỉ số Choppiness cao ($CI > 60$), biên độ giá dao động giằng co trong hộp tích lũy.

### 1.2. Luận Điểm Vi Mô (Microstructure Thesis)
- Khi một biến cố DC xuất hiện nhưng đoạn Overshoot bị suy giảm nghiêm trọng ($OD < 0$ hoặc $R_{OS} < 0.5$), nghĩa là động lực mua/bán đã cạn kiệt ngay khi giá rướn qua ngưỡng $\theta$.
- Phe đối lập đã hấp thụ hết thanh khoản của các lệnh Market Orders và chuẩn bị ép giá quay đầu về điểm cân bằng.

### 1.3. Quy Tắc Vào / Đóng Lệnh
- **Điều kiện Kích hoạt (Entry Trigger)**:
  - Giá xác nhận biến cố Directional Change tại ngưỡng $\theta^*$.
  - Tỷ số Overshoot $R_{OS} < 0.6 \times \text{median}(R_{OS})$.
  - Order Flow Imbalance (OFI) đảo chiều ngược lại với hướng DC vừa hình thành.
- **Điểm Cắt Lỗ (Stop Loss)**: Đặt tại mức vượt quá $1.5 \times \theta^*$ tính từ điểm cực trị (Extreme Price).
- **Điểm Chốt Lời (Take Profit)**: Đặt tại vùng **Unity Band** ($0.20R - 0.32R$) hoặc khi xuất hiện biến cố DC ngược chiều.
- **Rào cản ma sát**: Yêu cầu Gross Expectancy tối thiểu $\ge 80\text{ bps}$ để đảm bảo sau khi trừ 65 bps phí vẫn có lời.

---

## 2. Playbook 2: `VOL_EXPANSION_BREAKOUT` (Đánh Bùng Nổ Biến Động)

### 2.1. Bối Cảnh Thị Trường (Regime)
- Áp dụng khi thị trường ở trạng thái **`VOL_EXPANSION_REGIME`** (Dải biến động mở rộng đột ngột).
- Choppiness giảm dốc, thanh khoản khớp lệnh dồn dập, độ lệch chuẩn biến động 24h tăng vọt.

### 2.2. Luận Điểm Vi Mô
- Thị trường thoát khỏi giai đoạn tích lũy nén chặt. Một đợt sóng DC hình thành kèm theo dòng tiền Taker áp đảo một chiều, kích hoạt chuỗi thanh lý hoặc trượt giá dây chuyền (Liquidity Cascade).

### 2.3. Quy Tắc Vào / Đóng Lệnh
- **Điều kiện Kích hoạt (Entry Trigger)**:
  - Giá phá vỡ ngưỡng cực trị 24h kèm theo biến cố DC xác nhận cùng chiều.
  - Tốc độ khớp lệnh (Tick Frequency) tăng gấp đôi so với trung bình 24h ($\lambda_{tick} > 2.0 \times \bar{\lambda}$).
  - Khối lượng mua/bán ròng (Net Flow) đồng thuận với xu hướng phá vỡ.
- **Điểm Cắt Lỗ (Stop Loss)**: Khi giá hồi quy sâu quá $0.8 \times \theta^*$ tính từ điểm DC Trigger (False Breakout).
- **Điểm Chốt Lời (Take Profit)**: Trailing Stop theo các nhịp DC kế tiếp cho tới khi xuất hiện đảo chiều đối nghịch.

---

## 3. Playbook 3: `MOMENTUM_TREND_RIDE` (Cưỡi Sóng Xu Hướng Lớn)

### 3.1. Bối Cảnh Thị Trường (Regime)
- Áp dụng khi thị trường xác lập xu hướng mạnh một chiều bền bỉ.
- Tỷ số Overshoot duy trì ở mức cao ($R_{OS} > 1.5$), các bước sóng DC cùng chiều xuất hiện liên tiếp (Cascading DCs).

### 3.2. Quy Tắc Vào / Đóng Lệnh
- **Điều kiện Kích hoạt**: Gia nhập vị thế sau mỗi nhịp thoái lui nhẹ (Pullback) giữ vững trên mốc $\theta^*$.
- **Bảo vệ lợi nhuận**: Nâng mức dừng lỗ theo từng điểm cực trị mới của mỗi leg DC.

---

## 4. Playbook 4: `DO_NOT_TRADE` (Cấm Giao Dịch / Chế Độ An Toàn)

### 4.1. Điều Kiện Kích Hoạt Tự Động
Hệ thống **tuyệt đối không cấp quyền giao dịch** nếu cặp tài sản rơi vào bất kỳ điều kiện nào sau đây:
1. **Thiếu thanh khoản**: Thanh khoản Pool Liquidity $< \$100,000$ hoặc Spread ước tính $> 0.50\%$.
2. **Dữ liệu bẩn**: Bị chặn bởi `DataQualityGate` (chứa khoảng trống timestamp $> 2$ giờ hoặc giá nhảy dị thường).
3. **Thất bại bài kiểm tra ma sát**: Mang nhãn `FALSIFIED_AFTER_COST` (Net Expectancy âm ở mức phí Conservative 65 bps).
4. **Vi phạm luật phân phối**: Chỉ số Scaling Law Score $< 60.0$ (dấu hiệu bot tự wash-trade làm méo mó định luật Glattfelder).
