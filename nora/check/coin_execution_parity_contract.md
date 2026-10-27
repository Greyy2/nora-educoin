# COIN Execution Parity Contract & Decision Table (GATE 0)

**Version:** 1.0.0-FROZEN  
**Status:** DRAFT_UNVERIFIED (Owner Locked Decisions / Awaiting Measured Evidence)  
**Date:** 2026-10-25  
**Scope:** Nora COIN Backtest-to-Live Parity Engine & TradingNode Execution  

---

## 1. Executive Summary & Status Flags

Bản hợp đồng này đóng băng toàn bộ các quyết định bắt buộc của Owner đối với hệ sinh thái giao dịch COIN (Backtest, Replay, Paper, và OKX Demo/Testnet).
Cho đến khi toàn bộ chuỗi bằng chứng (Evidence Gates C1–C10, Replay, Risk, và Cost Model Calibration) được nghiệm thu độc lập và phê duyệt vận hành:

- `parameters_authoritative`: `false` (Không được coi các thông số chi phí/độ trễ là sự thật thị trường khi chưa đo lường).
- `execution_implemented`: `false` (Chỉ công nhận synthetic OHLC-open quote proxy L1; chưa có live venue execution engine hoàn chỉnh).
- `promotion_allowed`: `false` (Nghiêm cấm cấp cờ thăng hạng chiến lược lên Live).
- `official_ranking_allowed`: `false` (Vô hiệu hóa xếp hạng chính thức).
- `live_capital_authorized`: `false` (TUYỆT ĐỐI KHÔNG dùng vốn thật hoặc gửi lệnh lên tài khoản production).

---

## 2. Master Decision Table (Owner Decisions)

| Hạng mục | Quyết định của Owner | Trạng thái hiện tại | Bằng chứng / Ràng buộc thực thi |
|---|---|---|---|
| **Môi trường hoạt động** | **OKX Demo / Testnet ONLY** | ENFORCED | Nghiêm cấm gửi lệnh Live Production. Các endpoint live chạy giả lập Paper/Demo. |
| **Cặp tài sản được duyệt** | **BTC-USDT-SWAP, ETH-USDT-SWAP** | ENFORCED | Giới hạn vũ trụ giao dịch vào BTC và ETH vĩnh cửu; loại trừ altcoins chưa có mô hình. |
| **Vốn phân bổ cơ sở** | **10,000 USDT Virtual Master**<br>**1,000 USDT / Bot (Sleeve)** | ENFORCED | Quản lý vốn phân lớp (MasterLedger). Không cho phép bot tự ý xin vốn vượt quota. |
| **Cắt lỗ bắt buộc (Hard SL)** | **Bắt buộc có Venue Acknowledgement** | PARTIAL_PROXY | Backtest mô phỏng khớp ngay tại trigger/gap open; Live yêu cầu lệnh StopMarket được sàn xác nhận. |
| **Rủi ro tối đa mỗi lệnh** | **0.25% Master Equity** | ENFORCED | Controller từ chối vào lệnh nếu `max_loss_usdt > 0.0025 * master_equity`. |
| **Ngưỡng dừng lỗ ngày (Daily Loss)** | **2.0% Master Equity**<br>**3.0% Bot Sleeve Equity** | ENFORCED | Đóng vị thế và khóa giao dịch ngày nếu lỗ chạm ngưỡng tính từ 00:00:00 UTC. |
| **Ngưỡng dừng Max Drawdown (MDD)** | **Tạm thời: 15% Equity**<br>Chính thức: $\min(1.5 \times \text{OOS MDD}, 20\%)$ | ENFORCED | Dừng khẩn cấp (Emergency Kill Switch) khi vốn sụt giảm vượt ngưỡng. |
| **Trần đòn bẩy gộp (Gross Exposure)** | $\le \mathbf{3.0\times \text{Equity}}$ | ENFORCED | Tổng quy mô danh mục mở $\sum |\text{notional}_i| \le 3 \times \text{Master Equity}$. |
| **Trần vị thế ròng một chiều (Net Exposure)** | $\le \mathbf{2.0\times \text{Equity}}$ | ENFORCED | Tổng directional delta: $|\text{Net BTC} + \text{Net ETH}| \le 2 \times \text{Master Equity}$. |
| **Quy tắc biên ngày (UTC 00:00 Boundary)** | **Trừ funding 00:00 $\to$ Tất toán vị thế (Flatten)** | ENFORCED | Tất toán vị thế cuối ngày; chặn mọi lệnh mới có timestamp khớp $\ge 00:00:00$ UTC. |
| **Định giá PnL ngày (Daily PnL)** | $\text{Realized} + \Delta\text{Unrealized} - \text{Fees} - \text{Funding}$ | ENFORCED | So với mốc 00:00:00 UTC của ngày hiện tại, bền vững qua restart. |
| **Thời điểm khớp lệnh** | **NEXT CANDLE OPEN (L1 Quote Tick)** | ENFORCED (Nautilus) | Tín hiệu sinh tại Close nến $t$; khớp tại Open nến $t+1$ qua synthetic QuoteTick ($t + 2\text{ns}$). |
| **Trượt giá Stop-loss (Stop Slippage)** | **Hệ số x2 trượt giá tiêu chuẩn** | MODELLED (RESEARCH PROXY) | Backtest native Nautilus áp dụng proxy x2 trên quote tham chiếu khi khớp STOP_MARKET. Đây là quote tổng hợp từ OHLC, không phải slippage venue đã đo; không đủ điều kiện promote. |
| **Proxy trượt giá Taker nghiên cứu** | **BTC: 3.0 bps (0.03%)**<br>**ETH: 5.0 bps (0.05%)** | APPROVED_PROXY | Mức trượt giá nghiên cứu đã duyệt; chưa đo lường từ orderbook thật (unmeasured). |
| **Hệ số Stress Chi phí** | **Swing (5m–24h): x2**<br>**Scalp (1m): x2 và x3** | ENFORCED | Chiến lược bắt buộc phải sinh lời dưới kịch bản chi phí nhân đôi hoặc gấp ba. |
| **Bảo lưu nến cuối (Final Bar)** | **Không khớp lệnh ở nến cuối** | ENFORCED | Tín hiệu nến cuối không được khớp vì thiếu quan sát nến kế tiếp. |
| **Xử lý xung đột SL/TP cùng nến** | **Adverse Ordering (SL ưu tiên trước)** | ENFORCED | Nếu High chạm TP và Low chạm SL trong cùng 1 nến, giả định dính SL trước để chống overfit. |
| **Biến trượt giá mở cửa gap (Gap SL)** | **Khớp tại Open nến kế tiếp** | ENFORCED | Khi mở cửa gap qua mức SL, khớp ở giá Open (hoặc tệ hơn), không giữ giá trigger. |

---

## 3. Các thông số ĐÁNH DẤU CHƯA XÁC MINH (UNVERIFIED / UNKNOWN)

Các thành phần sau đây **tuyệt đối không được gán nhãn authoritative**:
1. **Fee Tier:** Tỷ lệ phí Taker/Maker hiện tại sử dụng mức mặc định (0.05% / 0.02%), chưa xác minh từ API Demo/Testnet của OKX.
2. **Funding History:** Lịch sử funding công khai chỉ có một phần; chưa có chuỗi liên tục từng 8h cho toàn bộ khoảng thời gian backtest.
3. **Độ sâu sổ lệnh (Quote Depth):** Synthetic quote tick hiện tại giả định thanh khoản vô hạn; chưa mô phỏng trượt giá tác động thị trường (market impact) theo volume nến.
4. **Độ trễ truyền mạng (Network Latency):** Chưa đo lường RTT thực tế tới server OKX Demo tại Tokyo/Hong Kong.

---

## 4. Cơ chế Cách ly & Chặn phát hành (Fail-Closed Quarantine)

- Mọi candidate hoặc backtest job thiếu chữ ký số xác thực nguồn gốc (`server-owned parity attestation`) đều bị từ chối 400 `ALPHA_RESULT_STALE_OR_UNPROVEN` trước khi khởi chạy bất kỳ worker/process nào.
- Cờ `parity_verified` trong database hoặc request payload của client bị bỏ qua hoàn toàn.
- Chỉ khi bộ cấp chứng chỉ của máy chủ (`ServerAttestationStore`) hoàn thành kiểm tra mã, tham số, dữ liệu, chi phí và cổng rủi ro, cờ xác thực mới được cấp phát.

## 5. Revalidation bổ sung (2026-10-26)

- `NoraSlotStrategy` được dựng qua `build_slots` cho cả backtest và TradingNode; `Coordinator` cũng được dùng chung. `ArraySignals` cấp tín hiệu tính trước cho backtest, còn `LiveSignals` cập nhật incremental từ nến live; cả hai gọi chung `evaluate_signals`.
- Bổ sung `nora/coin/tests/test_signal_provider_parity.py`: (1) fixture deterministic 1m -> 5m so sánh tín hiệu incremental với mảng offline và oracle độc lập `close_5m[t] > close_5m[t-1]`, gồm cả thời điểm không có sự kiện; (2) alpha production `kema_long` với tín hiệu/ATR 1m, so sánh `match`, `stop`, `dca`, `vol` giữa provider incremental/offline và xác nhận fixture phát sinh cả entry lẫn stop.
- Revalidation local: focused signal/execution/accounting tests **42/42 PASS**; toàn bộ `nora/coin/tests` **78/78 PASS**; hai provider parity tests **5 lần chạy liên tiếp, mỗi lần 2/2 PASS**; `git diff --check` PASS.
- Phạm vi kết quả: xác nhận fixture cụ thể và test suite hiện tại, không chứng minh mọi chiến lược, feed gaps/reconnect, bootstrap/catch-up/restart, order lifecycle ngoài sàn, cost calibration hay forward result.
- Không thay đổi các cờ fail-closed ở Mục 1. Chưa chạy bot Testnet/Demo và chưa gửi lệnh; việc khởi chạy Testnet cần operator approval và kiểm tra cấu hình môi trường/credentials tại thời điểm chạy.
