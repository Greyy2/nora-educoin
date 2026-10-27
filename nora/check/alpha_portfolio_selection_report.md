# Báo cáo Lựa chọn Danh mục Đa dạng hoá Alpha (GATE 7 - Portfolio Selection)

**Status:** BLOCKED — no reproducible per-variant qualification evidence  
**Date:** 2026-10-25  
**Candidate Input Count:** Unknown; the historical GATE 6 `N=0` claim is not independently reproducible from the available per-variant artifacts  
**Target Portfolio Size:** Tối đa 10 bot (không ép số lượng)  
**Active Portfolio Deployed:** **0 bots**  

---

## 1. Nguyên tắc Xây dựng Danh mục (Portfolio Policy)

Theo chỉ thị của Owner và định nghĩa tại **GATE 7**:
1. **Không ép số lượng:** Chỉ xây dựng danh mục tối đa 10 bot từ các ứng viên đã **vượt qua đầy đủ 100% các rào chắn** (Data, Native Nautilus Realism, Risk Gate, Cost Stress, DSR $\ge 0.95$, Monte Carlo).
2. **Nếu $N < 10$ ứng viên đạt chuẩn:** Báo cáo trung thực đúng $N$ ứng viên. Tuyệt đối **không hạ thấp chuẩn rào chắn** và **không sao chép/clone chiến lược** để bù cho đủ 10 bot.
3. **Nếu $N = 0$:** Báo cáo $0$ bot và từ chối cấp vốn khởi chạy, giữ nguyên toàn bộ số dư vốn an toàn tại Master Ledger.

---

## 2. Tiêu chí Đa dạng hoá Danh mục Đã Đóng băng (Frozen Standards)

Khi có ứng viên đạt chuẩn ở các chu kỳ nghiên cứu tiếp theo, quy trình chọn danh mục sẽ tự động áp dụng ma trận sau:

| Tiêu chí | Ngưỡng cho phép | Mục đích kiểm soát rủi ro |
|---|---|---|
| **Hệ số tương quan chéo (Pairwise Correlation)** | $\rho_{i,j} \le 0.50$ (trên chuỗi lợi suất OOS hàng ngày) | Tránh rủi ro tập trung khi các bot cùng chịu lỗ đồng thời |
| **Trần tỷ trọng theo Cặp tài sản (Symbol Cap)** | $\le 50\%$ tổng số bot (tối đa 5 bot / 1 symbol) | Ngăn ngừa rủi ro phụ thuộc vào riêng BTC hoặc ETH |
| **Trần tỷ trọng theo Khung thời gian (Timeframe Cap)** | $\le 40\%$ tổng số bot (tối đa 4 bot / 1 timeframe) | Đa dạng hoá chu kỳ nắm giữ vị thế (scalp vs swing) |
| **Trần tỷ trọng theo Họ chiến lược (Family Cap)** | $\le 40\%$ tổng số bot (tối đa 4 bot / 1 signal family) | Tránh rủi ro phong cách (Trend vs Mean Reversion) |
| **Joint Portfolio Monte Carlo MDD** | $\text{Aggregate MDD} \le 20.0\%$ | Đảm bảo danh mục tổng thể không sụt giảm vượt trần rủi ro |
| **Xác suất Cháy / Ruin của Danh mục** | $P(\text{Aggregate MDD} \ge 30\%) \le 5.0\%$ | Bảo vệ vốn ở mức tin cậy $95\%$ |

---

## 3. Quyết định Vận hành

- Chưa được xác nhận có biến thể nào vượt qua hay trượt các rào chắn: hiện không có raw per-variant/fold results hoặc reproducible gate receipts trong report package. Vì vậy candidate count đủ điều kiện là **UNKNOWN / NOT EVALUATED**, không được diễn giải lịch sử `N=0` thành bằng chứng đã đo.
- Quy mô portfolio hiện được phân bổ là **0 bots** vì alpha qualification, cost calibration, parity replay và master risk authority chưa qua gate; đây là quyết định chặn an toàn, không phải kết luận rằng đã kiểm định và không tìm thấy alpha.
- Không có bot nào được phê duyệt để chạy quan sát/Demo theo bộ hồ sơ này. Đây là trạng thái release gate; không thay thế việc đọc trạng thái tài khoản hiện tại.
- Không suy ra số dư Master, committed margin hoặc open positions từ báo cáo alpha; cần truy vấn snapshot ledger có nguồn riêng trước quyết định vận hành.
