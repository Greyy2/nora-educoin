# P13 — Đối chiếu NautilusTrader: các hành vi còn thiếu kịch bản (plan + todo)

Chuẩn: kết quả (lệnh, thời điểm, giá, khối lượng, phí, vốn) khớp NautilusTrader `develop`
(https://github.com/nautechsystems/nautilus_trader/tree/develop); kiến trúc/code/định nghĩa được khác.
Harness: `nora/test/scripts/nautilus_diff/` (S1–S11 đã khớp, `check_baseline.py` 349/349).
Nguồn Nautilus để đọc: bản cài `~/.venvs/nautilus` (2.0.0rc6, chỉ .so + .pyi) và mã Rust rc7 tại
`/tmp/claude-1000/-home-vmc03-norabt/f6c991d9-12fb-4d9b-bd10-7dd169814dbb/scratchpad/nt/src` (nếu mất: `git clone -b develop https://github.com/nautechsystems/nautilus_trader`).
Khuôn mẫu: copy bộ `s11_*.py` (export dữ liệu aligned → Nora chạy engine thật → Nautilus chạy dưới
`systemd-run --user --scope --slice=nora.slice -p MemoryMax=6G ~/.venvs/nautilus/bin/python -I ...` → compare thoát 1 khi lệch → `check_baseline.py --write` khi khớp).

## 0. Hiện trạng (đã khớp, chỉ khác làm tròn)
- Khớp logic: phí taker/maker, trượt giá, SL/TP % và ATR, trailing, timeout, đường đi trong nến (OHLC/adaptive), danh mục nhiều coin + giới hạn vị thế/vốn (S8), đa khung 1D/1m (S9), cooldown, DCA nhiều tầng, funding (S11).
- Khác chấp nhận được: làm tròn khối lượng 8 chữ số của Nautilus → vốn lệch ≤ 1e-4 USDT.
- Khác QUY ƯỚC (không phải lỗi) cần ghi nhận: Nautilus khớp lệnh market gửi từ `on_bar` ở giá đóng nến tín hiệu; Nora khớp ở open nến kế. Harness dùng dữ liệu "aligned" (open[t+1]=close[t]) nên trùng giá. Trên dữ liệu có gap giá entry khác nhau (REPORT.md:19). → mục G1 dưới.

## TODO

### G1. Quy ước khớp lệnh trên dữ liệu có gap (S12)
- Mục tiêu: chứng minh khác biệt CHỈ do quy ước close-vs-next-open.
- Nautilus: không có chế độ "fill at next bar open" (doc `bar-execution.md`); cách mô phỏng next-open: strategy đặt lệnh ở `on_bar` của nến 1m đầu tiên SAU nến tín hiệu (subscribe 1m, giữ cờ pending), hoặc dùng `ts_init` = open của nến kế.
- Việc: S12 = S9/S10 trên dữ liệu RAW (không aligned) với mô phỏng next-open phía Nautilus → phải khớp từng lệnh; thêm bảng "close-fill" để thấy độ lệch quy ước.
- Xong khi: S12 khớp; EXT_REPORT ghi rõ quy ước.

### G2. `limit_through_pct > 0` (khớp limit chỉ khi giá xuyên qua mức) (S13)
- Nora: lệnh limit (TP, tầng DCA) khớp khi đường đi 1m đi QUA mức thêm `limit_through_pct` (đọc `core/backtest.py` _intrabar / _layer_cost, `params.limit_through_pct`).
- Nautilus: LIMIT khớp ở giá limit khi chạm; liên quan `FillModel(prob_fill_on_limit=...)`, cấu hình venue `bar_execution`, `queue_position`, `liquidity_consumption` — xác minh tên/ý nghĩa trong rc7 (`crates/execution/src/matching_engine/`, `crates/backtest/src/config.rs`, doc `docs/concepts/backtesting`).
- Cách ánh xạ đề xuất: phía Nautilus đặt LIMIT ở mức xuyên (limit ± through) nhưng hạch toán giá khớp = mức gốc (shadow ledger như funding S11c); hoặc strategy tự kiểm 1m low/high ≤ level·(1−through) rồi gửi lệnh market tại level (giả định khớp đúng level). Chọn cách khớp ĐÚNG ngữ nghĩa Nora, ghi rõ.
- Stages: TP limit với through 0.05%/0.2%; DCA với through. Xong khi khớp từng lệnh.

### G3. Một nến 1m chạm cả tầng DCA lẫn cắt lỗ cũ (S11g)
- Nora: thứ tự trong nến theo đường đi O→H/L→C; khi tầng DCA khớp, SL mới tính từ giá TB mới, SL cũ còn hiệu lực trong nến đó (xem S11 note).
- Nautilus: mọi lệnh bị cắt trên cùng tick khớp cùng lúc, limit trước stop (REPORT.md:5); stop dời ở on_bar chỉ có hiệu lực từ nến sau.
- Việc: tạo dữ liệu tổng hợp (hoặc chọn đoạn thật) có nến 1m đi qua tầng DCA rồi qua SL cũ; so 2 thứ tự (ohlc/adaptive). Nếu Nora khác Nautilus → báo, quyết định chuẩn theo Nautilus.

### G4. Thanh lý (liquidation) và sụt ký quỹ (S13b)
- Nora: giá thanh lý theo `maintenance_margin_rate`, đòn bẩy, isolated (đọc `position_size.liq_price`, kernel liq path).
- Nautilus: `MarginAccount` + `MarginModel` (leveraged/standard), xác minh có tự thanh lý trong backtest không (`crates/model/src/accounts/margin.rs`, `crates/execution/.../liquidation`?). Nếu không có → strategy đặt STOP_MARKET reduce-only tại giá thanh lý Nora tính, đối chiếu giá/khối lượng/phí.
- Stages: đòn bẩy 10–20× với biến động đủ chạm liq.

### G5. Sizing theo rủi ro + trần notional + kill switch (S13c)
- Nora: `sizing="risk"` (khối lượng = risk_per_trade_pct·equity / khoảng SL), `max_notional_pct`, `max_capital_usage`, kill switch theo sụt vốn danh mục (`core/position_size.py admit_entry/kill_triggered`, RiskConfig).
- Nautilus: không có sizing — strategy tính khối lượng bằng đúng công thức Nora từ equity tài khoản Nautilus (`portfolio.account.balance_total`) — kiểm equity dùng (realized hay MTM) khớp Nora.
- Kill switch: strategy dừng vào lệnh khi sụt vốn ≥ ngưỡng; so thời điểm dừng.

### G6. `stop_fill="extreme"` và gap qua mức dừng (S13d)
- Nora: `stop_fill` level/extreme; gap mở qua mức dừng.
- Nautilus: gap-open tick khớp ở open (`fill_at_market=true` trên tick mở, `mod.rs:1969-1995`). So cả hai chế độ trên dữ liệu raw có gap.

### G7. Engine tick/AMM cho DEX (S14)
- Nora: `run_tick` (optimize/search/evaluate.py), `TickBook`, AMM constant-product/stable (`core/backtest.py` _amm_out_raw/_amm_price_impact_raw, `reserve_price`), phí pool + gas, dữ liệu `market/okx/dex/<pool>/ticks.parquet`.
- Nautilus: không có AMM. Có `TradeTick`/`QuoteTick`, `OrderBookDelta`, `FillModel`; có thể viết `SimulationModule`/custom venue hoặc mô phỏng ngoài.
- Cách đối chiếu (2 lớp):
  1. Toán AMM: so `amm_amount_out/price_impact` với cài đặt độc lập (Uniswap v2 x·y=k có phí; stable-swap Curve/Aerodrome) trên lưới đầu vào → khớp tới 1e-12.
  2. Luồng lệnh: Nautilus dùng TradeTick từ swap thật, strategy gửi market; giá khớp = giá AMM sau impact tính bởi cùng hàm độc lập (shadow ledger) → so thời điểm/giá/phí/gas với Nora `run_tick`.
- Xong khi: S14a (toán AMM) + S14b (luồng lệnh 1 pool) khớp.

### G8. Live/paper KernelBook từng bước = batch = Nautilus (S15)
- Nora: `KernelBook.step_bar` (bot paper/live) phải ra đúng như batch (đã có `test_kernel_step_parity`).
- Việc: chạy S9/S11 qua KernelBook step-by-step (như bot) thay vì PortfolioEngine batch → so với Nautilus. Bảo đảm bot chạy thật khớp Nautilus, không chỉ backtest.

## Quy trình mỗi mục
1. Đọc mã Nora liên quan → ghi ngữ nghĩa chính xác (công thức, thứ tự trong nến) vào đầu file `sNN_common.py`.
2. Đọc mã Nautilus (rc7/develop) tương ứng → ghi cách ánh xạ (native hay mô phỏng/shadow ledger) + lý do.
3. Export dữ liệu (aligned trước, raw sau), chạy 2 bên, compare từng lệnh; dung sai: giá rel < 1e-9, qty rel < 1e-7 (+ làm tròn 8 chữ số), pnl < 1e-3, vốn < 1e-3.
4. Lệch: xác định do harness (sửa harness) hay engine Nora (DỪNG, báo lệnh lệch đầu tiên + bằng chứng; sửa engine theo Nautilus chỉ sau khi duyệt; golden dựng lại có giải thích).
5. Khớp: `check_baseline.py --write` (đọc lại file baseline ngay trước khi ghi), README + EXT_REPORT thêm mục.

## Thứ tự đề xuất
G1 → G3 → G2 → G5 → G6 → G4 → G8 → G7 (G7 lớn nhất, làm cuối).
