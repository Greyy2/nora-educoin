# Đặc Tả Ngữ Pháp Tập Con AST Cho Lớp Viết `on_bar` (Cách A)

Tài liệu này đặc tả cú pháp và ngữ nghĩa tập con AST Python mà trình biên dịch (Compiler AST) được phép chấp nhận khi người dùng hoặc AI viết chiến lược theo phong cách `on_bar` (hợp đồng hướng sự kiện chuẩn), sau đó biên dịch tĩnh thành bản đặc tả trung gian **JSON IR (Intermediate Representation)** để chạy trên engine vector hoá và Nautilus matching engine.

---

## 1. Cấu Trúc Khai Báo Lớp Chiến Lược

Một lớp chiến lược hợp lệ kế thừa từ `NoraAlpha` (hoặc `SimpleAlgorithm`):

```python
class KemaLong(NoraAlpha):
    id = "kema_long"
    family = "KEMA (theo xu hướng)"
    side = "LONG"               # "LONG" hoặc "SHORT"
    description = "Giá đóng cửa cắt LÊN dải trên kênh Keltner → mua..."

    # 1. Tham số: Định nghĩa cấu trúc, UI bánh răng đọc trực tiếp
    params = {
        "signal_tf": param("4h", choices=("15m", "1h", "4h", "24h"), label="Khung tín hiệu", help="Khung tính Keltner"),
        "ema_n":     param(30, lo=5, hi=200, step=1, unit="nến", label="Chu kỳ EMA", help="Đường giữa"),
        "atr_n":     param(14, lo=5, hi=50, step=1, unit="nến", label="Chu kỳ ATR", help="Độ rộng kênh"),
        "k_up":      param(2.0, lo=0.5, hi=5.0, step=0.1, label="Hệ số dải trên", help="Hệ số k x ATR"),
    }

    # 2. Thoát vị thế (ATR/cooldown): Nguồn sự thật khai báo
    position = {
        "exit_unit": "atr",
        "atr_frame": "4h",
        "cooldown": 240,        # Đúng giá trị hiệu lực từ snapshot 0.1
    }

    def on_init(self):
        """Khai báo chỉ báo (chỉ chạy lúc khởi tạo, không xử lý lệnh)."""
        self.ema = self.indicator.ema(self.p.signal_tf, self.p.ema_n)
        self.atr = self.indicator.atr(self.p.signal_tf, self.p.atr_n)

    def on_bar(self, bar):
        """Luật vào/thoát vị thế theo từng nến."""
        upper = self.ema.value + self.atr.value * self.p.k_up
        if not self.in_position and bar.close > upper:
            self.enter(LONG)
        elif self.in_position and bar.close < self.ema.value:
            self.exit()
```

---

## 2. Tập Con AST Hợp Lệ (Allowed Grammar)

Trình biên dịch chỉ chấp nhận các nút AST sau:

### A. Trong phương thức `on_init(self)`:
- **Gán thuộc tính chỉ báo:** `self.<attr> = self.indicator.<func>(...)`
- Các hàm chỉ báo thuộc danh sách trắng `_KERNEL_FEATURES`: `ema, sma, rsi, er, atr, adx, bbands`.
- Tham số truyền vào chỉ báo: tên cột hoặc tham số `self.p.<param_name>`.

### B. Trong phương thức `on_bar(self, bar)`:
1. **Phép gán biến đơn:** `var = <expr>` (CẤM gán tuple `a, b = x, y`, CẤM gán rút gọn `+=, -=`).
2. **Biểu thức số học:** `+`, `-`, `*`, `/`.
3. **Biểu thức so sánh:** `>`, `>=`, `<`, `<=`, `==`, `!=`.
4. **Biểu thức logic:** `and`, `or`, `not` (hoặc toán tử bitwise `&`, `|`, `~`).
5. **Cấu trúc rẽ nhánh `if / elif / else`:**
   - Điều kiện rẽ nhánh kiểm tra trạng thái chuẩn: `self.in_position`, `not self.in_position`.
   - Thân khối `if` chỉ chứa:
     - Phát ý định vào lệnh: `self.enter(LONG)` hoặc `self.enter(SHORT)`.
     - Phát ý định thoát lệnh: `self.exit()`.
     - *Tuyệt đối không có tham số cỡ lệnh (`qty`), đòn bẩy (`leverage`) hay tỷ lệ rủi ro (`risk_pct`). Thẩm quyền này thuộc Portfolio Master Risk Engine.*

---

## 3. Các Cú Pháp Bị Cấm Tuyệt Đối (Prohibited AST Nodes)

Để đảm bảo tính bất biến, an toàn và biên dịch được sang JSON IR không có `exec()` tự do:
- ❌ **Vòng lặp:** `for`, `while` (bị cấm vì engine chạy vector hoá hoặc batch matching).
- ❌ **Xử lý ngoại lệ / ngữ cảnh:** `try`, `except`, `with`.
- ❌ **Khối mã bất đồng bộ:** `async`, `await`.
- ❌ **Nhập thư viện ngoài:** `import`, `from ... import`.
- ❌ **Hàm tùy ý / metaprogramming:** `def` lồng, `lambda`, `eval()`, `exec()`, `getattr()`, `setattr()`.

---

## 4. Xử Lý Trạng Thái & Câu Hỏi Mở Về DCA Nhồi Tầng

> [!NOTE]
> Mục tiêu của Giai đoạn 0.5 chỉ là **Tài liệu đặc tả tập con AST**, chưa phải kết luận "DCA đã biểu diễn được". Khả năng biểu diễn trọn vẹn trạng thái DCA nhồi tầng qua AST của `on_bar` vẫn là **CÂU HỎI MỞ** cho đến khi thực nghiệm tại Giai đoạn 3.

### A. Các chiến lược thông thường (KEMA, Sideway):
Trạng thái chỉ gồm nhị phân `in_position` (0 hoặc 1). Trình biên dịch ánh xạ:
- `not self.in_position and <cond>` $\rightarrow$ Khối cây `tree` (tín hiệu vào `position = 1` hoặc `-1`).
- `self.in_position and <cond>` $\rightarrow$ Khối cây `stop` (tín hiệu thoát `position = 0`).

### B. Chiến lược DCA (Câu hỏi mở):
Chiến lược DCA có các trạng thái phức tạp:
1. `layer_count`: Số tầng hiện tại ($1, 2, ..., N$).
2. `avg_entry_price`: Giá trung bình của cả rổ lệnh.
3. `dca_gate`: Điều kiện cho phép nhồi (ví dụ: ER < 0.35, ADX < 25).
4. `step_size`: Khoảng cách giá theo ATR so với tầng trước.

**Hiện trạng Compiler:**
- Phương thức `self.set_dca_gate(...)` hiện tại **chỉ tồn tại trong `_StrategyCompiler`** (dành cho module hệ thống như `dca.py`), **chưa tồn tại trong `_Compiler`** (dành cho alpha người dùng).
- Trong cú pháp `on_bar`, việc gọi `self.set_dca_gate(...)` mới chỉ là **ĐỀ XUẤT THỬ NGHIỆM**, chưa phải API có sẵn cho người dùng.

**Hai hướng tiếp cận trong Giai đoạn 3:**
- **Hướng A (Đề xuất khai báo cấu hình):**
  DCA **không** tự quản lý vòng lặp nhồi tầng trong `on_bar`. Thay vào đó, `on_bar` chỉ phát tín hiệu lệnh đầu (`self.enter(LONG)`), còn toàn bộ cấu hình nhồi tầng được khai báo tường minh trong `params` và `dca_gate` cấu hình sẵn của engine.
- **Hướng B (Tự viết logic nhồi trong `on_bar`):**
  Đòi hỏi khai báo biến trạng thái `self.state` tường minh. Tuy nhiên, việc dịch AST trạng thái động sang mảng vector tĩnh là rất phức tạp và dễ gây rò rỉ tương lai (look-ahead bias). Nếu AST không biểu diễn nổi trạng thái động này, hệ thống sẽ dừng lại và chọn lại kiến trúc tại Giai đoạn 3.
