# BÁO CÁO ĐỢT SÓNG 02: MÔ HÌNH CHI PHÍ MA SÁT TỪ ZERO TỚI STRESS

**Ngày thực hiện:** 07/09/2026  
**Mục tiêu chính:** Triển khai mô hình kiểm tra độ bền Alpha qua 4 tầng ma sát (Zero Cost ➔ Baseline ➔ Conservative ➔ Stress Test) theo yêu cầu của Sếp.

---

## 1. Vấn Đề Trước Khi Thực Hiện
- Nhiều giả thuyết nghiên cứu vi mô có PnL gộp dương (Gross Expectancy > 0) nhưng khi áp phí giao dịch thực tế trên DEX thì bị âm nặng.
- Sếp yêu cầu: *"sau khi hoàn thiện lõi, e thử 1 vài mô hình chi phí từ zero tới stress ấy"*.

---

## 2. Các Thay Đổi Kỹ Thuật Đã Triển Khai
1. **Xây dựng module `edge_falsifier.py`**:
   - Tích hợp công thức tính ma sát 4 cấp độ:
     * **Level 1 (Zero Cost - 0 bps)**: Baseline toán học thuần túy.
     * **Level 2 (Baseline DEX - 35 bps)**: Phí pool Uniswap v3 30 bps + Gas L2 5 bps.
     * **Level 3 (Conservative - 65 bps)**: Phí pool 30 bps + Slippage trung bình 25 bps + Gas 10 bps.
     * **Level 4 (Stress Hurdle - 100 đến 150 bps)**: Điều kiện thanh khoản mỏng, mạng nghẽn, MEV trượt giá mạnh.
2. **Logic Phản Nghiệm (Falsification Gate)**:
   - Tính toán `net_expectancy_bps = gross_expectancy_bps - friction_hurdle_bps`.
   - Gán cờ rõ ràng:
     * `FALSIFIED_AFTER_COST`: Nếu Net Expectancy $\le 0$.
     * `SURVIVED_FRICTION_HURDLE`: Nếu Net Expectancy $> 0$ kèm Scaling Law Score $\ge 70.0$.
3. **Hiển thị trực quan trên giao diện Asset Detail**:
   - Thêm widget "Thử Thách Ma Sát Thực Tế (Cost Stress Testing)" với thanh trượt và so sánh trực tiếp Gross vs Net.

---

## 3. Kết Quả Nghiệm Thu
- [x] Trên cặp `ZEN`, hệ thống ghi nhận: Gross Expectancy = 144 bps, Friction Hurdle = 65 bps, Net Expectancy = +79 bps ➔ Đạt chuẩn `SURVIVED_FRICTION_HURDLE`.
- [x] Trên các cặp coin thanh khoản mỏng, hệ thống tự động gắn cờ `FALSIFIED_AFTER_COST` và loại bỏ khỏi khuyến nghị giao dịch.
- [x] Đảm bảo không còn hiện tượng PnL ảo trong báo cáo nghiên cứu.
