# ADR-P10 — Hợp đồng chiến lược (Strategy Contract) + Chỉnh sửa tại chỗ + Trợ lý viết code

Ngày: 2026-10-08 · Trạng thái: **đã duyệt & hoàn thành** · Nhánh: `fix/pipeline-audit`

## 1. Mục tiêu và bối cảnh

Viết chiến lược Python định lượng chính xác như một IDE ứng dụng code (gợi ý, hover, kiểm lỗi đúng dòng/cột), nhưng chỉ gợi ý đúng những gì engine hiểu (fintech thuần, tất định, KHÔNG AI ảo giác). Phong cách NautilusTrader: MỘT hợp đồng cố định (`on_start` / `on_bar` / `on_stop`), các bộ chuyển đổi (adapters) đưa mọi dạng đầu vào khác về MỘT mô hình chuẩn (IR `core/signal.Program` hoặc cây khuôn của sổ chiến lược) và MỘT engine vector hoá. Mã người dùng **không bao giờ exec**: chỉ `ast.parse` rồi biên dịch theo danh sách trắng an toàn.

## 2. Hợp đồng chiến lược chuẩn

```python
class MyStrategy(SimpleAlgorithm):          # Lớp cơ sở cố định (alias Strategy được ADAPT chuẩn hoá thành SimpleAlgorithm)
    timeframe = "24h"

    def on_start(self):                      # KHAI BÁO: tham số + chỉ báo (không set_positions)
        close = self.data.pv_close
        ema = self.feat.ema(close, 20)

    def on_bar(self):                        # LUẬT: vào / thoát / dừng, là biểu thức mặt nạ vector hoá
        self.set_positions(close < ema, position=0.0)         # thoát vị thế
        self.set_positions(self.op.crossed_above(close, ema), position=1.0)   # vào lệnh

    def on_stop(self):                       # tuỳ chọn: pass / dọn dẹp
        pass
```

Hoặc dạng hàm gộp:
```python
class MyStrategy(SimpleAlgorithm):
    timeframe = "24h"
    def __algorithm__(self):
        # Toàn bộ thân on_start và on_bar gộp trong def __algorithm__(self)
        ...
```

## 3. Ba trạng thái tiếp nhận mã (Contract Processing)

1. **RUN (Native)**: Mã viết chuẩn theo Strategy Contract (kế thừa `SimpleAlgorithm`, khai báo `timeframe`, các hàm `on_start`/`on_bar` hoặc `__algorithm__`, sử dụng `self.data.*`, `self.feat.*`, `self.op.*`, `self.set_positions`).
2. **ADAPT (Adapter)**: Mã hợp lệ về mặt ngữ nghĩa nhưng khác về hình thức (ví dụ: kế thừa `Strategy`, định nghĩa dạng hàm tín hiệu `def signal(data):`, JSON spec). Adapter tự động chuyển đổi sang mã chuẩn hoặc IR.
3. **REJECT (Từ chối)**: Mã vi phạm danh sách trắng an toàn (chứa `import`, `exec`, `eval`, vòng lặp `while`/`for`, gọi I/O mạng, truy cập hệ điều hành, cú pháp không tương thích). Trả về lỗi chi tiết có dòng, cột và gợi ý sửa đổi chính xác.

## 4. Hệ quả

- Mọi chiến lược hệ thống và chiến lược người dùng đều biên dịch về cùng một biểu diễn trung gian IR duy nhất (`core/signal.Program`).
- Engine thực thi duy nhất (`core/backtest.py`) chỉ làm việc với IR đã được kiểm duyệt loại và gấp hằng số, đảm bảo tốc độ tối đa và tính bất biến.
