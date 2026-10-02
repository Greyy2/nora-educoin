# 02. LUẬT THÉP TỪ SẾP (BOSS MANDATES & RULE BASE)

Tài liệu này ghi chép trực tiếp các nguyên tắc chỉ đạo tối cao từ Sếp qua các đợt đánh giá hệ thống. Mọi lập trình viên (Developer) và mô hình trí tuệ nhân tạo (AI Assistant) khi tiếp cận dự án **BẮT BUỘC PHẢI TUÂN THỦ 100%**, không được tự ý sửa đổi hay hạ chuẩn.

---

## 🛑 NGUYÊN TẮC 1: 100% CAUSAL TICK DATA (KHÔNG LOOK-AHEAD BIAS)
> *"kiểm tra xem có look ahead k nhé. e chỉ để tick data thôi..."*

- **Bản chất**: Trong thực tế giao dịch, tương lai là ẩn số. Một sai lầm kinh điển của các hệ thống backtest kém chất lượng là dùng giá đỉnh/đáy trong tương lai của nến (High/Low) để ra quyết định ở hiện tại (Look-ahead bias).
- **Quy tắc thi hành**:
  1. Toàn bộ chuỗi sự kiện được xử lý tuần tự theo thời gian thực của từng swap/tick ($t_0 \to t_1 \to t_2$).
  2. Tại thời điểm tick $t_k$, thuật toán chỉ được phép truy cập thông tin của quá khứ $t \le t_k$.
  3. Tuyệt đối không dùng các hàm `resample()`, `interpolate()`, `rolling().center` làm méo mó dòng dữ liệu quá khứ.

---

## 🛑 NGUYÊN TẮC 2: DIRECTIONAL CHANGE (DC) CHỈ CÓ THETA ($\theta$), CẤM ÉP THÀNH CÂY NẾN
> *"cái DC nó chỉ có theta tôi chứ làm gì có candle..."*

- **Bản chất**: Directional Change là khái niệm vật lý thị trường theo thời gian nội tại (Intrinsic Time). Một biến cố DC chỉ xuất hiện khi giá đảo chiều một khoảng tỷ lệ $\theta$ (ví dụ: 1.5%, 2.0%, 3.0%) so với điểm cực trị (Extreme Price).
- **Quy tắc thi hành**:
  1. Ngưỡng DC $\theta^*$ được xác định độc lập và bất biến với khung nến 15m, 1h hay 4h.
  2. Không bao giờ được tính toán DC dựa trên giá đóng nến (Close) hay giá mở nến (Open) của khung thời gian cố định.
  3. Giá trị $\theta^*$ phải phản ánh đúng đặc tính vi mô của cặp giao dịch trên dữ liệu tick nguyên bản.

---

## 🛑 NGUYÊN TẮC 3: LIST TRADE BIỂU DIỄN ĐƯỜNG BIẾN ĐỘNG THEO TICK (BỎ NẾN)
> *"phía list trade k cần chart chỉ cần đường biến động theo tick là được (bỏ nến)"*

- **Bản chất**: Biểu diễn dạng nến trong bảng danh sách lệnh giao dịch (Trade List / Backtest Inspection) làm sai lệch nhận thức về đường đi của giá giữa điểm Entry và Exit.
- **Quy tắc thi hành**:
  1. Loại bỏ toàn bộ giao diện nến giả lập (simulated candles) ở khu vực kiểm tra chi tiết lệnh.
  2. Thay thế bằng đường biểu diễn biến động liên tục (Continuous Tick Trajectory / Price Step Line) nối liền từ điểm vào lệnh (Entry), các tick trung gian, tới điểm đóng lệnh (Exit).
  3. Trực quan hóa rõ ràng điểm xác nhận DC Trigger và giai đoạn Overshoot (OS) theo từng tick.

---

## 🛑 NGUYÊN TẮC 4: KIỂM ĐỊNH CHI PHÍ ĐA TẦNG - TỪ ZERO TỚI STRESS
> *"sau khi hoàn thiện lõi, e thử 1 vài mô hình chi phí từ zero tới stress ấy"*

- **Bản chất**: Rất nhiều chiến lược giao dịch tần suất cao (HFT / Microstructure) cho đường cong vốn đẹp như mơ ở điều kiện lý thuyết nhưng lập tức phá sản khi đưa vào thực tế do phí sàn, gas fee và trượt giá (slippage).
- **Quy tắc thi hành (4 Tầng Chi Phí Cố Định)**:
  1. **Zero Cost (0 bps)**: Kiểm tra xem bản thân tín hiệu toán học có thực sự tồn tại Alpha thô (Raw Edge) hay chỉ là biến ngẫu nhiên.
  2. **Baseline DEX Cost (35 bps)**: Phí Swap chuẩn Uniswap/Base (30 bps) + Gas fee tối thiểu (5 bps).
  3. **Conservative Cost (65 bps)**: Phí Swap (30 bps) + Trượt giá trung bình (25 bps) + Gas biến động (10 bps).
  4. **Stress Hurdle (100 - 150 bps)**: Mô phỏng điều kiện nghẽn mạng On-chain, thanh khoản mỏng, trượt giá lớn và MEV/Sandwich attack.
  - **Tiêu chuẩn vượt qua**: Một chiến lược chỉ được cấp cờ `SURVIVED_FRICTION_HURDLE` khi và chỉ khi giữ được Net Expectancy dương sau khi trừ đi mức cản ma sát (Friction Hurdle).

---

## 🛑 NGUYÊN TẮC 5: TỔ CHỨC DỰ ÁN SẠCH SẼ, CHỈ DUY TRÌ 2 SCRIPT ĐIỀU KHIỂN
> *"start và stop cho hệ thống chỉ cần 2 file còn lại clear để sạch folder server này"*

- **Quy tắc thi hành**:
  1. Thư mục gốc (`/home/ubuntu/norabt/`) chỉ duy trì đúng 2 file shell điều khiển:
     - `nora/start.sh`: Khởi động backend uvicorn chạy daemon, tự động dọn dẹp port cũ và health-check.
     - `nora/stop.sh`: Tắt hệ thống an toàn bằng SIGTERM ➔ SIGKILL fallback và giải phóng cổng 18010.
  2. Tuyệt đối không để các file script test lẻ tẻ, docs nháp, hay các bản prototype frontend cũ vương vãi ở thư mục gốc.
  3. Giữ nguyên vẹn các thư mục lõi phục vụ engine gốc (`coin_monitor/`, `coin_service/`, `coins/`, `data/`).
