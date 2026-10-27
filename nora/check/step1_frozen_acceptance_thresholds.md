# BẢN ĐÓNG BĂNG TIÊU CHÍ VÀ DUNG SAI NGHIỆM THU (STEP 1 FROZEN ACCEPTANCE THRESHOLDS)

> **Mục đích:** Khóa cứng toàn bộ thông số, ngưỡng sai số (tolerances), semantics kiểm toán và ghi nhận các exception kỹ thuật trước khi nghiệm thu Bước 1.

---

## 1. THÔNG SỐ VỐN, RỦI RO & ADMISSION POLICY (DEMO / PAPER BASELINE)

- **Master Capital Baseline:** `10,000.00 USDT` (bất biến).
- **Virtual Sleeve Capital:** `1,000.00 USDT` / bot.
- **Max Net Loss per Trade (SL Drag Cap):**
  - $\le 25.00\text{ USDT}$ (tương ứng $\le 0.25\%$ Master Capital / Equity, tức $\le 2.5\%$ Sleeve Capital).
  - Phải được tính và kiểm soát **trực tiếp trong production path** (`PortfolioAdmissionController.admit_order`).
  - Phép tính bao gồm toàn bộ drag: Biến động giá đến SL $+ 2 \times \text{Phí Taker} + \text{Trượt giá vào} + \text{Trượt giá thoát dừng lỗ (x2)} + \text{Lot rounding drag}$.
  - Hạn mức rủi ro kiểm tra theo **Master Equity**: $\text{Max Allowed} = \min(\text{Sleeve Cap} \times 2.5\%, \text{Master Equity} \times 0.25\%)$. Lệnh vượt trần bị từ chối với mã `RISK_PER_TRADE_EXCEEDED`.
- **Bot Daily Loss Lock (Sleeve Level):**
  - Ngưỡng: $3.0\%$ Sleeve Capital ($30.00\text{ USDT}$ trên $1,000\text{ USDT}$).
  - Tính từ mốc **UTC 00:00 đầu ngày**: $\text{Daily PnL} = \text{Realized PnL since 00:00 UTC} + \Delta\text{Unrealized} - \text{Fees} - \text{Funding}$.
  - Khi chạm ngưỡng, sleeve chuyển sang `LOCKED`. Mọi lệnh mở mới bị chặn (`SLEEVE_LOCKED_MAX_LOSS`), các lệnh giảm vị thế (`is_reduce_only=True`) vẫn được chấp nhận.
- **Master Daily Loss Lock (Circuit Breaker Level):**
  - Ngưỡng: $2.0\%$ Master Capital / Equity ($200.00\text{ USDT}$ trên $10,000\text{ USDT}$).
  - Kích hoạt khi tổng lỗ trong ngày từ 00:00 UTC $\ge 200.00\text{ USDT}$ hoặc Master Equity sụt giảm $\ge 200.00\text{ USDT}$ từ vốn gốc.
  - Trạng thái khóa phải **bền vững qua restart/reload** từ ổ đĩa (`get_live_master_ledger`).
  - `PortfolioAdmissionController.admit_order` phải chặn đứng mọi lệnh mở mới với lý do `MASTER_CIRCUIT_BREAKER_TRIGGERED`.

---

## 2. COST MODEL & TIÊU CHUẨN THỰC THI (OKX RESEARCH PROXIES)

- **Phí giao dịch:**
  - Taker fee: $5\text{ bps}$ ($0.0005$).
  - Maker fee: $2\text{ bps}$ ($0.0002$).
- **Trượt giá Taker cơ sở (Slippage Proxy):**
  - BTC: $3\text{ bps}$ ($0.0003$).
  - ETH: $5\text{ bps}$ ($0.0005$).
- **Hệ số phạt trượt giá Stop-Loss (`stop_slippage_multiplier`):** $2.0\times$
  - Khi dính Stop-Loss: Trượt giá BTC $= 2.0 \times 3\text{ bps} = 6\text{ bps}$; ETH $= 2.0 \times 5\text{ bps} = 10\text{ bps}$.
- **Khớp lệnh Next-Open:** Lệnh sinh tại giá đóng nến $[t]$ được khớp tại giá mở nến $[t+1]$ kết hợp proxy trượt giá.
- **Final-bar Unfilled Guard:** Tín hiệu sinh tại nến cuối cùng của dữ liệu **không được khớp** (không sinh fill ảo vì thiếu nến kế tiếp).

---

## 3. DUNG SAI CHẤP NHẬN ĐỐI SOÁT (ACCEPTANCE TOLERANCES)

| Hạng mục đối soát | Phạm vi kiểm tra | Dung sai tối đa cho phép | Ghi chú kỹ thuật |
|---|---|:---:|---|
| **Indicator Arrays** (RSI, SMA, EMA) | So sánh Nora với Math Oracle | $\Delta < 10^{-6}$ | Thực tế đạt $< 10^{-10}$ (sai số làm tròn IEEE-754) |
| **Signal Trigger Bars** | Entry / Exit Signals | $0\text{ bar}$ (Bitwise Exact) | Khớp 100% từng bar, cả Entry và Exit |
| **Order Fill Price** | Entry & Exit Prices | $\Delta < 10^{-4}\text{ USDT}$ (0 tick deviation) | So sánh sau khi làm tròn theo tick size hợp lệ của instrument (0.1 USDT cho BTC) |
| **Net Loss at SL** | Sizing verification | $\le 25.00\text{ USDT}$ | Production path đảm bảo không bao giờ vượt 25 USDT |
| **MDD Metric vs Chart Series** | `mdd_pct` vs `drawdown_pct` | $\Delta \le 0.05\%$ | Cả metrics và chart series đều dùng Intrabar Worst Drawdown (`np.minimum(eq, worst)`) |
| **Cross-Product Parity** (COIN vs EDU) | Shared Metrics (`ret`, `mdd`, `sharpe`, `trades`, `fees`) | $\Delta \le 0.01$ | Trùng khớp kết quả giữa 2 sản phẩm |
| **Trade Ledger Parity** | `symbol`, `side`, `qty`, `enter_time`, `close_time`, `enter_price`, `close_price`, `close_reason`, `fees_usd`, `funding_usd`, `pnl_usd` | $100\%$ Exact | Khớp từng trường của từng trade trong lịch sử |

---

## 4. QUY CÁCH ĐỐI CHỨNG ĐỘC LẬP & WAIVER REGISTER

### 4.1. Nautilus Trader Native Backtest Engine (ĐÃ NGHIỆM THU)
- Phải chạy qua thực thể `BacktestEngine` của Nautilus Trader (`make_engine` + `stream`).
- Strategy kế thừa `nautilus_trader.trading.strategy.Strategy`, tính toán tín hiệu động trong `on_bar` (không hardcode `bar_idx`).
- Lệnh và fill được trích xuất trực tiếp từ `engine.cache.orders()` và `engine.trader.generate_order_fills_report()`.
- So sánh đối chiếu đầy đủ từng event giữa Nora và Nautilus.

### 4.2. TradingView Pine Script v5 (ACCEPTANCE GATE, CHƯA CHẠY)
- **Trạng thái hiện tại:** `TV_PARITY_NOT_RUN/BLOCKED`; chưa được gắn nhãn PASS.
- **Phạm vi nghiệm thu:** TradingView là reference behavior bắt buộc để kiểm tra
  engine backtest EDU/COIN. Cùng strategy, dữ liệu, tham số và execution contract
  phải được chạy trên cả Nora và TradingView rồi đối chiếu signal, order, fill/trade
  và equity/metrics. Export Strategy Tester chỉ là artifact của reference run, không
  phải waiver và không thay thế comparator.
- **Các điểm cần đóng băng trước khi chạy:**
  1. **Fixed Tick Slippage vs Dynamic bps:** Trong Pine Script v5, tham số `slippage` tính bằng ticks cố định (`slippage = 180` ticks với tick 0.1 USDT chỉ tương ứng đúng 3 bps khi BTC ở quanh 60,000 USDT; khi giá dịch chuyển, số bps thực tế bị lệch).
  2. **Intrabar Emulator Divergence:** TradingView sử dụng broker emulator nội suy tick giả lập trong bar; các khác biệt về thứ tự High/Low trong bar không dùng Bar Magnifier là giả lập xấp xỉ của TV, không thể dùng làm ground truth kỹ thuật cho quantitative trading engine.
  3. **Thiếu Trade Export tự động:** TradingView Strategy Tester yêu cầu thao tác GUI thủ công trên cloud, không có pipeline xác thực headless lặp lại được trong repository.
- Nếu TradingView chưa thể cung cấp reference run/replay lặp lại được, gate phải giữ
  `BLOCKED`, không được chuyển thành waiver hoặc suy diễn PASS từ Nautilus parity.
- File [`FastDip_TradingView_Reference.pine`](file:///home/vmc03/norabt/nora/check/FastDip_TradingView_Reference.pine) là Pine reference cần được chạy và đối chiếu; chỉ lưu file không phải là bằng chứng parity.
