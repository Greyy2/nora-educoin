# Tổng quan Dự án Nora (Product Brief)

Tài liệu tóm lược mục tiêu sản phẩm, bài toán nghiệp vụ, người dùng mục tiêu và các chỉ số đo lường thành công của nền tảng Nora Quantitative Trading Platform.

---

## 1. Bài toán thị trường & Bối cảnh

Trong thị trường tiền mã hoá (Crypto Derivatives CEX & DEX), hầu hết các bảng xếp hạng bot giao dịch công khai hiển thị mức lợi nhuận (ROI) phóng đại nhưng che giấu rủi ro:
- Lợi nhuận cao chủ yếu đến từ đòn bẩy quá mức (10x–30x), dễ cháy tài khoản khi thị trường biến động mạnh.
- Đường vốn chỉ tính lãi đã chốt (Closed PnL), che giấu các khoản lỗ treo chưa chốt (Unrealized Floating Losses).
- Kết quả backtest thông thường bị sai lệch nghiêm trọng do **Lookahead Bias** (nhìn trước dữ liệu tương lai), giả định khớp lệnh phi thực tế và bỏ qua chi phí trượt giá, phí funding rate.

**Nora giải quyết triệt để các vấn đề này** bằng một nền tảng nghiên cứu và thực thi định lượng khép kín, tuyệt đối nhân quả (Strictly Causal), mô phỏng chi phí sát thực tế và bắt buộc mọi chiến lược phải vượt qua các cổng kiểm định toán học đa tầng trước khi đưa vào giao dịch tiền thật.

---

## 2. Tầm nhìn sản phẩm (Product Vision)

Xây dựng một hệ thống định lượng chuẩn mực công nghiệp cho thị trường Crypto với một chu trình duy nhất, có thể tái lập kết quả từng bit:

$$\text{Thu thập dữ liệu} \longrightarrow \text{Nghiên cứu Alpha} \longrightarrow \text{Phễu kiểm định (WFA, Monte Carlo)} \longrightarrow \text{Sổ danh mục} \longrightarrow \text{Bot giao dịch Live}$$

### 4 Nguyên tắc cốt lõi:
1. **Không nới lỏng tiêu chuẩn**: Nếu không có alpha nào đạt chuẩn an toàn, hệ thống báo "không có", tuyệt đối không hạ thấp ngưỡng để có kết quả đẹp giả tạo.
2. **Causal tuyệt đối**: Mọi tín hiệu tại nến $t$ chỉ dựa trên dữ liệu đã đóng tại $t$.
3. **Mô phỏng khớp lệnh bảo thủ**: Khớp lệnh nội nến `ohlc` hai pha theo chuẩn NautilusTrader 2.0, tính đầy đủ phí giao dịch, trượt giá và funding rate.
4. **Đo lường bằng Mark-to-Market NAV**: Theo dõi hiệu suất trên vốn thực tế theo thời gian thực thay vì lãi đã chốt.

---

## 3. Chân dung người dùng (Target Personas)

1. **Nhà nghiên cứu định lượng (Quant Researcher)**:
   - Viết, kiểm thử và tối ưu hoá các thuật toán giao dịch bằng Python DSL.
   - Sử dụng Studio Editor, thư viện 50 mẫu chiến lược giáo trình, công cụ phân tích biểu đồ và phễu duyệt alpha.
2. **Kỹ sư vận hành hệ thống (Operations / Trader)**:
   - Giám sát các tác vụ tính toán nặng trên hạ tầng dùng chung (giới hạn 12GB RAM).
   - Xuất bản sổ chiến lược, cấu hình và vận hành bot giao dịch tự động trên sàn OKX (Paper, Demo và Live).

---

## 4. Chỉ số thành công cốt lõi (Key Metrics & Goals)

- **G1 (Kiểm định đa tầng)**: Alpha phải vượt qua Walk-Forward Analysis ($\ge 60\%$ fold OOS có lãi), Monte Carlo ($P(\text{MDD} \ge 30\%) \le 5\%$) và Holdout 20% dữ liệu cuối.
- **G2 (Đồng nhất bit-identical)**: Cùng dữ liệu đầu vào và tham số bắt buộc phải cho kết quả giống hệt từng bit qua các phiên bản cập nhật mã nguồn.
- **G3 (Kiểm soát tài nguyên)**: Khống chế tối đa 12GB RAM cho toàn bộ tiến trình, không gây tràn bộ nhớ OOM hệ thống.
- **G4 (Một Engine duy nhất)**: Kết quả khớp lệnh giữa mô phỏng backtest và bot thời gian thực trên sàn đồng nhất về mặt ngữ nghĩa và số liệu.
