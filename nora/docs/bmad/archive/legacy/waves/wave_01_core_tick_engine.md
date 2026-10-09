# BÁO CÁO ĐỢT SÓNG 01: LÕI TICK ENGINE & CHUẨN HOÁ DC INTRINSIC TIME

**Ngày thực hiện:** 06/09/2026  
**Mục tiêu chính:** Loại bỏ hoàn toàn mô hình nến nhân tạo trong phân tích vi mô, chuẩn hóa Directional Change theo tham số $\theta$ trên dữ liệu tick nguyên bản, kiểm tra triệt tiêu Look-ahead Bias.

---

## 1. Vấn Đề Trước Khi Thực Hiện
- Hệ thống phân tích vi mô trước đó có dấu hiệu giả lập nến để tính toán các điểm vào/ra lệnh trong danh sách trade.
- Sếp yêu cầu dứt khoát: *"e chỉ để tick data thôi , cái DC nó chỉ có theta tôi chứ làm gì có candle. Phía list trade k cần chart chỉ cần đường biến động theo tick là được (bỏ nến)"*.
- Cần kiểm tra nghiêm ngặt nguy cơ Look-ahead bias.

---

## 2. Các Thay Đổi Kỹ Thuật Đã Triển Khai
1. **Kiểm tra và xác nhận Zero Look-Ahead Bias**:
   - Rà soát toàn bộ pipeline xử lý trong `nora/backend/core/research/dc_feature_extractor.py` và `event_behavior.py`.
   - Xác nhận cơ chế event loop chỉ đọc dữ liệu theo thứ tự tăng dần của timestamp $t_0 \le t_1 \le ... \le t_k$, không có bất kỳ hàm nhìn trước tương lai.
2. **Loại bỏ nến giả lập ở giao diện List Trade**:
   - Thay thế biểu đồ nến bằng đường biến động liên tục của từng tick (Price Trajectory / Step line).
   - Đánh dấu chính xác 2 điểm quan trọng: Điểm xác nhận DC Trigger và giai đoạn Overshoot (OS).
3. **Chuẩn hóa biến cố Directional Change**:
   - Tách rời hoàn toàn tham số $\theta$ khỏi khung thời gian nến.
   - Định nghĩa trạng thái thị trường dựa trên biến cố Intrinsic Time thay vì thời gian vật lý.

---

## 3. Kết Quả Nghiệm Thu
- [x] Biểu đồ chi tiết lệnh hiển thị 100% đường tick liên tục, không còn một cây nến nào.
- [x] Thuật toán DC chạy hoàn toàn trên mảng tick, xác định đúng $\theta^*$ tối ưu theo từng cặp tài sản.
- [x] Toàn bộ test suite liên quan đến xử lý tick đạt chuẩn kiểm thử nhân quả.
