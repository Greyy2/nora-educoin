# 03. CƠ SỞ TOÁN HỌC & ĐỊNH LƯỢNG (MATHEMATICAL FOUNDATIONS)

Tài liệu này tổng hợp các nền tảng toán học, vật lý kinh tế (econophysics) và các định luật tỷ lệ (Scaling Laws) làm nền móng cho Nora.

---

## 1. Directional Change (DC) & Intrinsic Time

### 1.1. Định Nghĩa Biến Cố DC
Cho chuỗi giá theo tick $P(t)$. Một biến cố Directional Change với ngưỡng tỷ lệ $\theta > 0$ được định nghĩa bằng hai trạng thái:
- **Upward DC Event**: Xảy ra khi giá tăng từ điểm đáy cục bộ (Trough $P_{min}$) lên mức:
  $$P(t) \ge P_{min} \times (1 + \theta)$$
- **Downward DC Event**: Xảy ra khi giá giảm từ điểm đỉnh cục bộ (Peak $P_{max}$) xuống mức:
  $$P(t) \le P_{max} \times (1 - \theta)$$

### 1.2. Giai Đoạn Overshoot (OS)
Sau khi biến cố DC được xác nhận tại mức giá $P_{DC}$, xu hướng có thể tiếp tục di chuyển cùng chiều trước khi xuất hiện một đợt đảo chiều mới. Đoạn đường di chuyển thêm này gọi là **Overshoot**:
$$\Delta X_{OS} = \left|\frac{P_{extreme} - P_{DC}}{P_{DC}}\right|$$

Tổng biến động của một chu kỳ (Total Move) bao gồm:
$$\Delta X_{Total} = \theta + \Delta X_{OS}$$

---

## 2. Các Định Luật Tỷ Lệ (Glattfelder Scaling Laws)

Nghiên cứu của Guillaume et al. (1997) và Glattfelder et al. (2011) chỉ ra rằng thị trường tài chính tuân theo 12 định luật lũy thừa (Power Laws) độc lập với quy mô tài sản. Trong đó, 2 định luật cốt lõi được Nora ứng dụng gồm:

### 2.1. Định Luật Tần Số Biến Cố (Event Frequency Law)
Số lượng biến cố DC trung bình $N(\theta)$ trong một khoảng thời gian tỷ lệ nghịch với ngưỡng $\theta$ theo quy luật hàm mũ:
$$N(\theta) \propto \theta^{-E}$$
Trong đó, số mũ $E \approx 2.0$ trên các thị trường có tính thanh khoản cao và cấu trúc lành mạnh. Nếu $E$ suy biến mạnh (ví dụ $E < 1.3$), cặp tài sản đó có dấu hiệu thanh khoản ảo hoặc bị thao túng giá.

### 2.2. Định Luật Chiều Dài Overshoot (Overshoot Law)
Độ dài trung bình của đoạn Overshoot xấp xỉ bằng chính ngưỡng $\theta$:
$$\langle \Delta X_{OS} \rangle \approx \theta$$
Tỷ số giữa Overshoot và DC:
$$R_{OS} = \frac{\langle \Delta X_{OS} \rangle}{\theta} \approx 1.0$$

---

## 3. Overshoot Deficit (OD) & Động Lực Học Hồi Quy

### 3.1. Khái Niệm Overshoot Deficit
Trong cấu trúc vi mô, khi một bước sóng DC hình thành nhưng đoạn Overshoot không đạt tới mức kỳ vọng $1.0\theta$ (nghĩa là $R_{OS} \ll 1.0$), thị trường rơi vào trạng thái **Overshoot Deficit**:
- **Ý nghĩa vật lý**: Lực đẩy của bên mua/bán đã cạn kiệt ngay sau khi vượt ngưỡng kích hoạt; phe đối lập đã hấp thụ hết thanh khoản và sẵn sàng đảo chiều.
- **Tín hiệu**: Đây là điều kiện tiên quyết cho chiến lược `DC_OVERSHOOT_FADE` (đánh chặn sóng rướn hụt hơi).

### 3.2. Unity Band (0.20 - 0.32R)
- Vùng giá nằm trong biên độ hồi quy $0.20R - 0.32R$ so với đỉnh/đáy 24h là điểm cân bằng vi mô nơi xác suất xuất hiện sự giằng co giữa phe Momentum và phe Mean-Reversion đạt cực đại.

---

## 4. Phân Loại Trạng Thái Thị Trường (Market Regime Classification)

Nora phân chia trạng thái thị trường dựa trên tổ hợp của 3 chỉ số vi mô:
1. **Choppiness Index (CI)**: Đo lường mức độ hỗn loạn/đi ngang của dòng giá.
2. **Normalized Volatility**: Mức độ bung mở của dải biến động so với đường trung bình 24h.
3. **Flow Imbalance (Order Flow Imbalance - OFI)**: Chênh lệch khối lượng ròng giữa bên mua chủ động (Maker/Taker) và bên bán chủ động.

| Trạng Thái (Regime) | Đặc Điểm Vi Mô | Chiến Lược Đề Xuất (Playbook) |
| :--- | :--- | :--- |
| **`RANGE_CHOP_REGIME`** | Choppiness cao (>60), Volatility thấp, Flow giằng co | `DC_OVERSHOOT_FADE` (Bắt sóng rướn cạn lực) |
| **`VOL_EXPANSION_REGIME`** | Choppiness giảm mạnh, Volatility bùng nổ, Flow lệch 1 chiều | `VOL_EXPANSION_BREAKOUT` (Đánh thuận trend bung nổ) |
| **`TRENDING_MOMENTUM`** | $R_{OS} > 1.5$, chuỗi DC cùng chiều liên tiếp | `MOMENTUM_TREND_RIDE` (Cưỡi sóng xu hướng dài) |
| **`ILLIQUID_LOW_VOLUME`** | Tần số tick thưa thớt, trượt giá ước tính > 0.5% | `DO_NOT_TRADE` (Cấm giao dịch) |
