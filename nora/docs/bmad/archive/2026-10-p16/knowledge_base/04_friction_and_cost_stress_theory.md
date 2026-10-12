# 04. MA SÁT THỰC TẾ & MÔ HÌNH KIỂM ĐỊNH STRESS (FRICTION & COST STRESS THEORY)

## 1. Bản Chất Của Ma Sát Trên Sàn Phi Tập Trung (DEX Friction)

Trong môi trường DEX (Uniswap v2/v3, Aerodrome, Curve...), chi phí thực tế cho mỗi lệnh giao dịch round-trip (Mua + Bán) cao hơn rất nhiều so với sàn CEX. Một mô hình backtest không tính đến ma sát thực tế là một mô hình giả dối (delusional).

Tổng ma sát một giao dịch phải chịu:
$$\text{Total Friction} = \text{DEX Fee} + \text{Price Impact / Slippage} + \text{Gas Fee} + \text{MEV Leakage}$$

Trong đó:
1. **DEX Protocol Fee**: Phí pool cố định (thường từ 0.05% đến 0.30% mỗi chiều).
2. **Price Impact & Slippage**: Hàm số phụ thuộc vào độ sâu thanh khoản (Liquidity Depth $k = x \cdot y$) và quy mô lệnh (Order Size). Với các pool có thanh khoản mỏng, trượt giá có thể lên tới 0.20% - 0.50%.
3. **Gas Cost (L1 / L2)**: Trên Ethereum Mainnet có thể từ \$5 - \$50; trên L2 (Base, Arbitrum) dao động từ \$0.01 - \$0.20. Khi tính theo basis point (bps) trên một volume lệnh nhỏ, gas cost trở thành gánh nặng lớn.
4. **MEV & Sandwich Attack**: Nguy cơ bị bot MEV chèn lệnh khi gửi transaction vào mempool công khai.

---

## 2. Bốn Tầng Kiểm Định Chi Phí (Four-Tier Cost Stress Model)

Hệ thống Nora chuẩn hóa 4 cấp độ chi phí ma sát để kiểm tra độ bền của Alpha:

```text
[TẦNG 1: ZERO COST]        0 bps      -> Kiểm tra xem tín hiệu có tồn tại Alpha thô hay không
          ↓
[TẦNG 2: BASELINE DEX]    35 bps      -> Điều kiện bình thường trên DEX (Phí Pool 30 bps + Gas 5 bps)
          ↓
[TẦNG 3: CONSERVATIVE]    65 bps      -> Điều kiện có trượt giá thực tế (Pool 30 + Slippage 25 + Gas 10)
          ↓
[TẦNG 4: STRESS HURDLE]  100-150 bps  -> Điều kiện khắc nghiệt: Biến động cao, mạng nghẽn, trượt giá nặng
```

### Chi Tiết Từng Cấp Độ:

| Cấp Độ | Mức Ma Sát (Round-trip) | Mục Đích Đánh Giá |
| :--- | :--- | :--- |
| **1. Zero Cost** | **0.0 bps** | Đảm bảo logic dự báo giá có tính nhân quả (Causal Predictive Power) độc lập với chi phí. Nếu ở mức 0 bps mà PnL âm hoặc Sharpe < 0, tín hiệu lập tức bị loại bỏ. |
| **2. Baseline DEX** | **35.0 bps** *(0.35%)* | Kiểm tra xem chiến lược có đủ bù đắp mức phí cơ bản của Liquidity Pool trên mạng Base/Ethereum hay không. |
| **3. Conservative** | **65.0 bps** *(0.65%)* | Ngưỡng tiêu chuẩn tối thiểu để được cấp trạng thái `SURVIVED_FRICTION_HURDLE`. Đây là mức ma sát bình quân của một trader tổ chức giao dịch trên DEX. |
| **4. Stress Hurdle** | **100.0 - 150.0 bps** *(1.0% - 1.5%)* | Thử thách khả năng sống sót khi thị trường rơi vào hoảng loạn, spread dãn rộng và mạng lưới on-chain tăng phí đột biến. |

---

## 3. Công Thức Falsification (Loại Bỏ Giả Thuyết)

Một giả thuyết Alpha được phân loại vào một trong hai trạng thái:
1. **`FALSIFIED_AFTER_COST`**:
   $$\text{Net Expectancy} = \text{Gross Expectancy} - \text{Friction Hurdle} \le 0$$
   *(Chiến lược bị khai tử vì lợi nhuận kỳ vọng không đủ bù đắp chi phí ma sát)*.
2. **`SURVIVED_FRICTION_HURDLE`**:
   $$\text{Net Expectancy} > 0 \quad \text{và} \quad \text{Scaling Law Score} \ge 70.0$$
   *(Chiến lược sống sót qua rào cản ma sát, đủ điều kiện bước tiếp vào pha Walk-Forward Analysis)*.
