# Bảng Kiểm Kê Hiện Trạng Tham Số Rủi Ro & Phân Bổ Vốn (P14-B1)

Tài liệu kiểm kê chi tiết toàn bộ các khoá tham số liên quan đến vị thế, rủi ro, phân bổ vốn và bảo vệ tài khoản trong hệ thống Nora, phục vụ việc phân tách **Lớp 1 (Strategy Risk Controller)** và **Lớp 2 (Core Execution Engine)** theo kế hoạch P14.

---

## 1. Tổng Hợp Danh Mục Tham Số Rủi Ro & Vị Thế

| Tên khoá | Mặc định | Nơi định nghĩa chính | Nơi sử dụng thực tế | Ngữ nghĩa hiện tại | Đề xuất áp cho họ chiến lược (P14-B2) |
|---|---|---|---|---|---|
| `risk_profile` | `"legacy"` | `backend/core/params.py` | `position_size.py`, `backtest.py` | Xác định bộ quy tắc rủi ro của chiến lược | Tất cả |
| `market` | `"perp"` | `core/params.py:332` | `backtest.py`, `position_size.py` | Loại thị trường (`perp` / `spot` / `amm`) | Tất cả |
| `leverage` | `1.0` | `core/params.py:332` | `backtest.py`, `position_size.py` | Đòn bẩy sử dụng cho lệnh | `trend`, `breakout`, `mean_reversion`, `dca`, `legacy` |
| `stop_loss_rate` / `sl` | `0.0` | `core/params.py:332` | `backtest.py`, `position_size.py` | Tỷ lệ SL tính theo % | Bắt buộc ở `trend`, `breakout`, `mean_reversion`; tuỳ chọn ở `dca` |
| `sl_anchor` | `"avg"` | `core/position_size.py` | `backtest.py` (`PI_SL_ANCHOR`) | Điểm neo tính mức giá SL (`entry`, `avg`, `last_layer`, `none`) | `entry` cho trend/breakout; `avg` cho revert; `last_layer` cho DCA |
| `sl_beyond_last_pct` | `0.5` | `core/params.py` | `position_size.py` | Khoảng cách đặt SL vượt quá tầng DCA cuối cùng | Riêng cho họ `dca` |
| `take_profit_rate` / `tp` | `0.0` | `core/params.py:332` | `backtest.py`, `position_size.py` | Tỷ lệ chốt lời tính theo % | Tuỳ chọn (`trend`, `mean_reversion`, `dca`) |
| `trailing_stop` / `trail` | `0.0` | `core/params.py:332` | `backtest.py`, `position_size.py` | Biên độ trailing stop theo % | Cho phép ở `trend`, `breakout`; hạn chế ở `dca` |
| `trailing_activation_pct` | `0.0` | `core/params.py:332` | `backtest.py`, `position_size.py` | Ngưỡng lãi tối thiểu để kích hoạt trailing | `trend`, `breakout` |
| `dca_steps` | `[]` | `core/params.py:332` | `backtest.py`, `position_size.py` | Danh sách % khoảng cách từng tầng DCA | **Cấm** ở `trend`, `breakout`; ≤2 tầng ở `revert`; ≥1 ở `dca` |
| `dca_multipliers` | `[]` | `core/params.py:332` | `backtest.py`, `position_size.py` | Hệ số nhân khối lượng từng tầng DCA | Đồng bộ với `dca_steps` |
| `sizing` | `"margin_pct"` | `core/params.py:332` | `backtest.py`, `position_size.py` | Cách tính cỡ lệnh (`margin_pct` / `risk` / `fixed`) | `risk` cho trend/breakout; `margin_pct` cho dca/legacy |
| `order_size_pct` | `1.0` | `core/params.py:332` | `backtest.py`, `position_size.py` | Tỷ lệ vốn dùng cho lệnh đầu (% equity) | `legacy`, `dca`, `mean_reversion` |
| `risk_pct` | `1.0` | `core/params.py:332` | `backtest.py`, `position_size.py` | Tỷ lệ rủi ro chấp nhận mất nếu chạm SL (% equity) | `trend`, `breakout` |
| `timeout_bars` / `timeout` | `0` | `core/params.py:332` | `backtest.py` | Giới hạn thời gian giữ lệnh tối đa (số nến) | Khuyến khích ở `breakout`, `mean_reversion` |
| `cooldown` | `0` | `core/params.py:332` | `backtest.py` | Thời gian nghỉ tối thiểu giữa các lệnh vào (phút) | Bắt buộc ≥1 nến cho `trend`, `breakout` |

---

## 2. Danh Mục Các Ràng Buộc & Luật Hợp Lệ Của Từng Họ (P14-B2 Preview)

### Họ 1: `legacy` (Mặc định bảo toàn 100%)
- **Hành vi:** Giữ nguyên từng bit hành vi hiện tại của hệ thống.
- **Neo SL:** `avg` (tính từ giá trung bình đầu nến).
- **Quyền DCA:** Không giới hạn.
- **Bảo toàn:** 100% test golden, 50 mẫu, 353 baseline tests không đổi.

### Họ 2: `trend` (Bắt xu hướng)
- **Hành vi:** Đón đầu xu hướng dài, trailing để gồng lãi, cắt lỗ dứt khoát khi gãy trend.
- **Neo SL:** `entry` (cố định theo điểm vào ban đầu) hoặc trailing stop.
- **Quyền DCA:** **CẤM TUYỆT ĐỐI**. Bắt xu hướng sai là cắt, không bình quân giá.
- **Sizing:** Mặc định `risk` (tính khối lượng sao cho nếu chạm SL thì mất đúng `risk_pct` vốn).
- **Vào lại:** Cần tín hiệu mới + cooldown tối thiểu 1 nến.

### Họ 3: `breakout` (Phá vỡ biên)
- **Hành vi:** Vào lệnh khi giá bứt phá mạnh, SL chặt chẽ ngay dưới ngưỡng cản/hỗ trợ.
- **Neo SL:** `entry` (chặt chẽ).
- **Quyền DCA:** **CẤM TUYỆT ĐỐI**.
- **Thoát:** Bắt buộc có SL hoặc timeout (nếu phá vỡ giả không chạy tiếp thì thoát sớm).
- **Sizing:** Mặc định `risk`.

### Họ 4: `mean_reversion` (Hồi quy về giá trung bình)
- **Hành vi:** Mua khi quá bán, bán khi quá mua, kỳ vọng giá hồi về MA/Bollinger.
- **Neo SL:** `avg`.
- **Quyền DCA:** **GIỚI HẠN TỐI ĐA 2 TẦNG**.
- **Ràng buộc thép:** Mọi tầng DCA phải nằm **TRƯỚC** mức Stop-Loss (không được đặt DCA vượt quá SL).
- **Thoát:** TP về giá trung bình hoặc tín hiệu đảo chiều.

### Họ 5: `dca` (Chiến lược kéo giá trung bình chuyên dụng)
- **Hành vi:** Tận dụng dao động để kéo giá trung bình, thoát khi hồi về hòa vốn hoặc lãi nhẹ.
- **Neo SL:** `last_layer` (SL đặt cách tầng cuối cùng một khoảng `sl_beyond_last_pct`, tính cố định từ đầu) hoặc `none` (chỉ phụ thuộc vào ngân sách rổ vốn và kill threshold).
- **Quyền DCA:** **BẮT BUỘC ≥ 1 tầng**.
- **Ràng buộc thép:**
  1. Tầng DCA cuối cùng bắt buộc phải nằm **TRƯỚC** mức SL (nếu có SL).
  2. Tổng vốn ký quỹ của toàn bộ thang DCA không được vượt quá ngân sách rổ vốn (`dca_budget_check`).
  3. Trailing stop chỉ được kích hoạt sau khi giá đã vượt qua ngưỡng Take-Profit (không trailing khi đang gồng lỗ).

---

## 3. Các Vị Trí Code Cần Tác Động Trong Giai Đoạn P14-B3 Đến B5

1. **`backend/core/position_size.py`:**
   - Định nghĩa dataclass `RiskProfile` và bảng `RISK_PROFILES`.
   - Hàm `validate_strategy_risk(params)` kiểm tra hợp lệ và trả về thông báo lỗi chi tiết.
2. **`backend/core/params.py`:**
   - Thêm khoá `risk_profile`, `sl_anchor`, `sl_beyond_last_pct` vào `POSITION_KEYS`.
3. **`backend/core/backtest.py`:**
   - Thêm cờ `PI_SL_ANCHOR` và cột `F_SL_LEVEL` để hỗ trợ mức SL tuyệt đối (`last_layer` / `entry`) độc lập với biến động giá trung bình.
   - Giữ nguyên `PI_SL_ANCHOR=0` cho profile `legacy` để đảm bảo bit-identical.
