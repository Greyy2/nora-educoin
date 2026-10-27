# BƯỚC 2 — KIỂM KÊ, ĐÁNH GIÁ VÀ CHUẨN HÓA CHIẾN LƯỢC EDU / COIN

> **Phân biệt trạng thái:** Phần I–III là snapshot kiểm kê chỉ đọc đã có. Phần IV trở đi là kế hoạch triển khai; chưa có nghĩa 1.061 chiến lược đã được đánh giá nội dung hoặc viết lại.
>
> **An toàn dữ liệu:** Không chỉnh sửa/định dạng lại file chiến lược gốc của user. Mọi bản chuẩn hóa phải là version/fork mới, có provenance tới bản gốc. Không tự suy diễn hoặc chèn SL/TP/sizing vào chiến lược thiếu cấu hình.

## 1. Tổng quan Kho lưu trữ Chiến lược

- **Tổng số chiến lược kiểm kê:** 1061
  - `COIN/active_user`: 4 bản ghi
  - `COIN/quarantine`: 69 bản ghi
  - `COIN/strategies`: 0 bản ghi
  - `EDU/user`: 988 bản ghi
  - `EDU/strategies`: 0 bản ghi

## 2. Thống kê Trạng thái & Tính đầy đủ

| Chỉ số | Số lượng | Tỷ lệ |
|---|---|---|
| Trạng thái AST/Biên dịch: `NATIVE_NAUTILUS` | 126 | 11.9% |
| Trạng thái AST/Biên dịch: `COMPILED_CLEAN` | 934 | 88.0% |
| Trạng thái AST/Biên dịch: `EMPTY` | 1 | 0.1% |
| Phân tầng: `Tier 1 (Simple)` | 928 | 87.5% |
| Phân tầng: `Tier 2 (Advanced)` | 132 | 12.4% |
| Phân tầng: `UNKNOWN` | 1 | 0.1% |
| Thiếu Stop-Loss tường minh trong mã | 937 | 88.3% |

## 3. Danh sách Top Chiến lược Tiềm năng (COIN Active + Candidate)

| Sản phẩm | ID | Tên | Phân tầng | Biểu tượng | Khung giờ | Stop-Loss | Sizing |
|---|---|---|---|---|---|---|---|
| **COIN Active** | `18e87aa868ad` | Fast Dynamic Channel Breakout (18D + Macro Trend) | Tier 2 (Advanced) | BTC,ETH,SOL | 24h | ✅ Có | ✅ Có |
| **COIN Active** | `33312a2f4dfc` | Standard Deviation Dynamic Channel Breakout (v2.0 Regime Filtered) | Tier 2 (Advanced) | BTC,ETH,SOL | 24h | ✅ Có | ✅ Có |
| **COIN Active** | `alpha_proxima_research` | Proxima Universal Breakout (Research) | Tier 2 (Advanced) | BTC | 1m | ❌ Không | ❌ Không |
| **COIN Active** | `efa90f74cd08` | Donchian Channel Breakout (Turtle Trading) | Tier 2 (Advanced) | BTC,ETH,SOL | 24h | ✅ Có | ✅ Có |
| COIN Quarantined | `0873864b8db7` | DEMA Turbo Compound (1Y Fast Trend - x1.51 Vốn) | Tier 2 (Advanced) | BTC,ETH,SOL | 24h | ✅ Có | ✅ Có |
| COIN Quarantined | `090730ae35b8` | Fail-Fast Volatility Breakout (SL 2.4% + Macro Trend) | Tier 2 (Advanced) | BTC,ETH,SOL | 24h | ✅ Có | ✅ Có |
| COIN Quarantined | `0caaa527c1c3` | Kiểm tra engine 1m (nến xanh/đỏ) | Tier 2 (Advanced) | BTC,ETH,SOL | 1m | ✅ Có | ✅ Có |
| COIN Quarantined | `0d51ba8d2012` | OBV Volume Accumulation + RSI Momentum | Tier 2 (Advanced) | BTC,ETH,SOL | 24h | ✅ Có | ✅ Có |
| COIN Quarantined | `0f8f9e67fe25` | Statistical Trend Channel Guard (Optimized) | Tier 2 (Advanced) | BTC,ETH,SOL | 24h | ✅ Có | ✅ Có |
| COIN Quarantined | `13579fbbc966` | Chiến lược gốc của Mary | Tier 1 (Simple) | BTC@perp | 15m | ❌ Không | ❌ Không |
| COIN Quarantined | `136b5e410cae` | Williams %R Extreme Elasticity | Tier 2 (Advanced) | BTC,ETH,SOL | 24h | ✅ Có | ✅ Có |
| COIN Quarantined | `14e3b934b1e5` | ROC Momentum Exhaustion with Take-Profit | Tier 2 (Advanced) | BTC,ETH,SOL | 24h | ✅ Có | ✅ Có |
| COIN Quarantined | `15567e02a806` | Triple EMA Trend Alignment (Optimized) | Tier 2 (Advanced) | BTC,ETH,SOL | 24h | ✅ Có | ✅ Có |
| COIN Quarantined | `1a6eb53421cf` | Kiểm tra engine 1m (EMA 9/21) | Tier 2 (Advanced) | BTC,ETH,SOL | 1m | ✅ Có | ✅ Có |

## 4. Kết luận chính xác từ snapshot hiện tại

- Snapshot ghi nhận **1.061 record**: 4 COIN active, 69 COIN quarantine và 988 EDU user. Phải chạy lại inventory và ghi timestamp/hash trước khi bắt đầu xử lý vì số lượng và nội dung có thể đã đổi.
- `Tier 1`, `Tier 2`, `has_sl`, `has_risk_sizing`, `COMPILED_CLEAN` và `NATIVE_NAUTILUS` là các trường kiểm kê/heuristic. Chúng **không chứng minh** công thức đúng, policy risk đầy đủ, khả năng thực thi an toàn hay chiến lược đạt chuẩn bot.
- `missing_stop_loss_count = 937` nghĩa là snapshot không tìm thấy SL tường minh theo phép kiểm tra inventory. Không có nghĩa được phép gán SL mặc định 2%; phải xem xét cả code, position config, execution contract và ý định tác giả.
- Snapshot hiện chỉ cho biết tên/ID, một số indicators và cờ hiện diện. Nó không phải đánh giá từng entry/exit, sizing, cost, leverage, funding, causality hay tính phù hợp với mục tiêu chiến lược.
- Bản báo cáo trước từng khuyến nghị áp SL mặc định 2% cho chiến lược thiếu SL. **Khuyến nghị đó bị rút lại:** không áp mặc định và không chạy chiến lược thiếu hard stop theo đường có thể mở vốn thật. Giữ nguyên để học/backtest theo contract đã khai báo; mọi đường Demo/Live cần policy hard-stop riêng được phê duyệt và enforce fail-closed.

## 5. Định nghĩa chuẩn chiến lược đủ đặc tả

Mọi chiến lược, bất kể Tier, phải có một assessment record trả lời được các mục sau. Trường không áp dụng phải ghi `N/A` kèm lý do; trường không biết phải ghi `UNKNOWN/BLOCKED`, không tự đặt giá trị.

| Nhóm bắt buộc | Nội dung cần ghi rõ |
|---|---|
| Định danh và nguồn | Product, owner/user, strategy ID, version, original code/config hash, fork parent ID/hash, thời điểm đánh giá, người duyệt |
| Universe và dữ liệu | Spot/perp, symbol(s), venue, timeframe tín hiệu và khớp lệnh, timezone/session, nguồn dữ liệu, date range, manifest/digest, missing/stale policy |
| Indicator và toán học | Tên indicator được hỗ trợ, công thức/convention, từng period/threshold/multiplier, input series, timeframe, warm-up, NaN handling; định nghĩa sample/population cho estimator thống kê |
| Entry signal | Long/short, điều kiện logic đầy đủ, crossover event hay trạng thái level, bar xác nhận, lệnh được tạo lúc nào, điều kiện loại tín hiệu trùng/lặp |
| Execution | Market/limit/stop, next-open hay semantics đã chọn, tick/lot/minimum, partial/reject/cancel behavior, final-bar guard, giả định intrabar và stop/TP ordering |
| Position và sizing | Số vị thế tối đa theo symbol/toàn portfolio, pyramiding/DCA có hay không, vốn cấp cho strategy/sleeve, sizing mode, công thức quantity, risk budget, leverage/margin cap, rounding và reject conditions |
| Exit và bảo vệ | Hard SL bắt buộc cho đường Demo/Live; neo giá, đơn vị (%/ATR), stop trigger/fill semantics; TP (có hoặc không, nêu lý do); trailing, signal exit, timeout, cooldown; cùng-bar ordering |
| Chi phí | Taker/maker fee, slippage/spread, stop multiplier, funding/borrow nếu áp dụng, provenance và trạng thái `MEASURED`, `APPROVED_PROXY`, `UNVERIFIED` hoặc `NOT_APPLICABLE` |
| Portfolio/risk | Per-trade loss cap, sleeve/master daily loss, gross/net exposure, concentration/correlation policy, durable locks, reduce-only/emergency behavior |
| Kiểm chứng | Compiler/type/DSL validation, independent signal oracle, accounting/execution fixture, no-lookahead test, backtest windows, OOS/stress evidence, known limitations |
| Trạng thái | `EDUCATION_ONLY`, `RESEARCH`, `QUARANTINED`, `DEMO_ELIGIBLE_REVIEW_REQUIRED`, `BLOCKED`; không dùng nhãn `APPROVED/LIVE` chỉ dựa trên backtest |

### Cost contract theo sản phẩm

- **EDU:** tính phí theo cấu hình của run; slippage mặc định `0.0` theo mục tiêu học tập hiện tại. UI/report phải nói rõ kết quả không tính trượt giá và có thể lạc quan hơn execution thực tế. EDU backtest không được trình bày như bằng chứng live parity.
- **COIN:** tính phí và slippage. BTC 3 bps/side, ETH 5 bps/side cùng stop slippage 2× chỉ là research proxy hiện hành; fee tier chưa xác minh, funding history/spec còn hạn chế. Giữ provenance và các cờ promotion/ranking fail-closed.
- Không chuyển cost assumptions giữa hai sản phẩm bằng implicit default. Mỗi run phải lưu cost config/provenance cùng kết quả.

## 6. TradingView parity là chuẩn nghiệm thu cho engine Nora

Ý nghĩa của yêu cầu “khớp TradingView” ở Bước 2 là: **cùng một chiến lược, cùng dữ
liệu, cùng tham số và cùng quy ước thực thi phải cho kết quả gần như giống nhau khi
chạy trên engine backtest EDU/COIN và trên TradingView**. TradingView là reference
behavior để phát hiện Nora engine tính sai; không phải chỉ là nơi lấy một ảnh tổng
return, và cũng không phải yêu cầu thay engine Nora bằng TradingView.

Với mỗi strategy được gọi là “đúng”, phải có:

1. **Nora implementation:** code gốc hoặc normalized fork chạy thật trên engine đúng
   product (EDU hoặc COIN).
2. **TradingView implementation:** Pine reference tương đương về indicator, signal,
   order và quản trị vị thế; không được thay đổi logic để làm số đẹp.
3. **Shared run manifest:** symbol/instrument, timeframe, date range, OHLCV data,
   timezone/session, initial capital, fee, slippage, sizing, leverage, lot/tick,
   SL/TP/trailing và mọi execution flags.
4. **Comparable ledgers:** signal, order, fill/trade, equity và metrics từ cả hai
   engine.

Nếu chưa chạy được cùng strategy trên cả hai engine thì trạng thái là
`TV_PARITY_NOT_RUN/BLOCKED`, không được ghi `PASS`, `NORMALIZED` hoặc
`DEMO_ELIGIBLE`. Nautilus parity, math oracle và fixture nội bộ chỉ là lớp kiểm tra
phụ trợ; không được dùng để thay thế TV parity.

### 6.1. Contract phải đóng băng trước khi audit semantics

Mỗi strategy cần một Pine reference versioned và một shared-run manifest ghi rõ:

- symbol/exchange/instrument (ví dụ `OKX:BTCUSDT.P`), market type, timeframe, session,
  timezone, date range và dataset/chart version;
- toàn bộ input indicator/signal: period, threshold, multiplier, source, warm-up,
  `ta.rsi`/`ta.rma`/`ta.ema` convention, long/short và pyramiding;
- `process_orders_on_close`, `calc_on_order_fills`, `calc_on_every_tick`, Bar Magnifier,
  order type, next-bar/open/close timing và quy tắc final bar;
- commission type/value, fixed tick slippage, spread/stop assumptions, funding nếu có;
  với COIN, bps proxy phải được quy đổi thành tick theo từng instrument và phải ghi rõ
  bản chất fixed-tick của TradingView; với EDU slippage phải là `0.0` như contract;
- initial capital, position sizing (`percent_of_equity`, cash hoặc contracts), leverage,
  lot/tick/minimum quantity, rounding và quantity tại từng order;
- SL/TP/trailing, cùng-bar High/Low ordering, gap behavior, signal close và
  `strategy.entry`/`strategy.exit`/`strategy.close` semantics.

Không tự chọn giá trị còn thiếu. Một manifest thiếu bất kỳ trường nào ở trên là
`CONTRACT_INCOMPLETE/BLOCKED`.

### 6.2. Artifact tối thiểu của một lần chạy parity

Không chấp nhận chỉ chụp ảnh tổng return hoặc nhập tay vài con số. Mỗi lần chạy
parity phải lưu artifact từ **cả Nora và TradingView**, tối thiểu gồm:

1. **Signal ledger:** bar index/timestamp, indicator values, signal name, side và lý do
   entry/exit.
2. **Order ledger:** order ID, creation bar/time, order type, requested qty, accepted/
   rejected/cancelled state và parent order.
3. **Trade ledger:** trade ID, side, entry/exit bar/time, entry/exit price, qty,
   commission, slippage/assumption, exit reason và realized PnL.
4. **Equity ledger:** equity theo bar, drawdown, trade count, gross/net profit, fees và
   các metric hiển thị trên Strategy Tester.

Artifact của hai engine phải liên kết với Pine hash/Nora code hash, shared settings
manifest, data digest và run ID. Nếu TradingView chỉ cung cấp CSV thủ công thì lưu
nguyên file, checksum, cách export, người/thời điểm xác nhận; CSV đó là evidence của
reference run, không được gọi là pipeline headless tự động.

### 6.3. Bốn lớp parity và tiêu chí PASS

| Lớp | Bắt buộc đối chiếu | Tiêu chí |
|---|---|---|
| Signal | Indicator values, signal name, side, event bar/time, warm-up | Exact theo bar/timestamp; giá trị số theo tolerance đã chốt |
| Order | Order creation, type, requested qty, accepted/rejected, parent | Exact từng order; không bỏ order bị từ chối/hủy |
| Fill/trade | Trade count, entry/exit bar, side, qty, prices, SL/TP và reason, fees/slippage | Exact hoặc tolerance theo từng field đã đóng băng; không chỉ khớp tổng PnL |
| Ledger | PnL từng trade, equity curve, fees, drawdown và metrics | Exact/tolerance theo manifest; mọi mismatch phải nêu nguyên nhân và disposition |

Một strategy chỉ được đánh dấu `TV_PARITY_PASS` khi cả bốn lớp pass trên cùng một
window, cùng data và cùng settings. Cụ thể:

- Số lệnh phải giống nhau.
- Bar/timestamp phát signal và tạo order phải giống nhau.
- Entry/exit side, loại lệnh, số lượng, giá và lý do thoát phải giống nhau trong
  tolerance đã đóng băng.
- SL/TP/trailing phải kích hoạt cùng bar và cùng thứ tự khi cùng nến chạm nhiều mức.
- Fees, slippage, PnL từng trade, equity và drawdown phải khớp trong tolerance.

Khớp số lệnh nhưng lệch bar/giá là **FAIL**. Khớp return cuối nhưng lệch trade ledger
là **FAIL**. Nếu TradingView và Nora khác vì broker emulator, intrabar hoặc fixed-tick
slippage, phải xác định lại execution contract hoặc ghi mismatch cụ thể; không được
đổi tolerance tùy ý và không được bịa số liệu để làm PASS.

### 6.4. Trạng thái hiện tại của Bước 2

[`FastDip_TradingView_Reference.pine`](./FastDip_TradingView_Reference.pine) hiện mới
là Pine reference kiến trúc. Repository chưa có một shared-run comparator chứng minh
Nora EDU/COIN và TradingView cho cùng strategy có cùng số lệnh, signal bars, fills và
ledger. Vì vậy parity của exemplar và 1.061 record hiện là
`TV_PARITY_NOT_RUN/BLOCKED`; Gate Nautilus hiện có không thay đổi kết luận này.

## 7. Hai Tier và mẫu tham chiếu

Tier phân loại **độ phức tạp của luận điểm và toán học**, không phân loại mức độ đầy đủ hay độ an toàn. Cả hai Tier phải đạt hợp đồng ở mục 5.

### Tier 1 — EDU/simple, dễ đọc và dạy được

- Một timeframe tín hiệu chính; một giả thuyết dễ diễn giải; thường 1–3 indicator.
- Entry/exit là điều kiện xác định được bằng tay; ưu tiên ít tham số, không tối ưu hóa vô hạn.
- Không multi-asset portfolio logic, regime stack nhiều tầng, DCA/martingale hay sizing động phức tạp trong mẫu nhập môn.
- Có position policy minh bạch: market, leverage, max positions, sizing theo risk, hard SL, TP hoặc giải thích không dùng TP, timeout/cooldown, phí; EDU slippage bằng 0 nhưng phải cảnh báo.
- Mẫu tham chiếu: `EduTrendPullback` — close trên EMA50 và RSI cắt lên ngưỡng 40 để vào Long; thoát khi close dưới EMA50; SL/TP theo ATR; quantity theo risk budget.
- Đây là mẫu cấu trúc giáo dục, không phải chiến lược đã chứng minh có alpha. Mã đã được compiler EDU kiểm tra tại thời điểm ghi nhận; cần giữ test compile làm regression khi thay onboarding/template.

### Tier 2 — COIN/advanced, định lượng và nhiều điều kiện

- Có thể dùng regime filter, volatility channel, multi-timeframe/multi-asset, sizing theo biến động, portfolio/exposure constraints hoặc exit động.
- Mỗi thành phần phải có định nghĩa toán học, dữ liệu đầu vào, convention, warm-up, khung thời gian, parameter bounds, thứ tự evaluation và xử lý dữ liệu thiếu.
- Cần test causality/no-lookahead, oracle độc lập cho indicator/signal, ledger/execution fixtures, cost stress và OOS/WFA trước khi đánh giá promotion.
- Mẫu tham chiếu: Vinh Breakout `33312a2f4dfc`, *Standard Deviation Dynamic Channel Breakout (v2.0 Regime Filtered)*. Ý tưởng đã dùng làm ví dụ là `SMA20 + 1.5 × StdDev20`, breakout close qua biên trên, filter EMA100; ví dụ sizing đã nêu là hard SL 2.5% và risk 0.25% master. Đây là ví dụ thiết kế, **không xác nhận** các giá trị đó là semantics chính xác của code user hiện tại hoặc đã được hiệu chuẩn/phê duyệt.
- Không kết luận chiến lược “đạt chuẩn Tier 2” chỉ vì code native, nhiều indicator, có SL, hoặc tên có chữ advanced.

## 8. Quy tắc về code mẫu và compiler

- **EDU user strategy**: custom DSL dùng class `SimpleAlgorithm`/`NoraStrategy` với `on_start()` để khai báo series/indicator và `on_bar()` để phát `self.set_positions(mask, position=...)`. Position/risk keys là class attributes, không nhét dict `position={...}` hoặc metadata `STRATEGY` vào dạng custom code nếu compiler không hỗ trợ.
- **COIN system strategy module**: dùng đúng module contract hiện tại: `STRATEGY = {...}`, mỗi leg `SimpleAlgorithm`, khai báo `position = {...}`, `p(...)` cho signal/exit/risk params, indicator set/feature set được module compiler hỗ trợ và `__algorithm__()` hoặc lifecycle được compiler chấp nhận. Không giả định mọi user alpha COIN là module system strategy.
- `set_positions(..., position=1)` biểu thị target exposure/leg, **không phải** “dùng 100% vốn”. Vốn run/book, quantity sizing, risk admission, margin, fee reservation và portfolio cap phải được nối qua execution/portfolio contract.
- `on_bar` phải viết luật vào trước, luật thoát sau nếu semantics compiler là luật sau ghi đè luật trước. Mỗi mẫu phải compile bằng đúng compiler/product path, không chỉ parse Python.
- Không đưa syntax indicator/feature chưa được compiler tương ứng hỗ trợ. Không dùng code minh họa trước đó làm chuẩn nếu chưa qua compiler test.

## 9. Kế hoạch triển khai Bước 2 và dependency gates

### Gate 2.TV — TradingView reference parity (prerequisite)

1. Đóng băng Pine reference, settings manifest, dataset/date window và export schema.
   Pine phải là implementation tương đương của cùng strategy, không phải một strategy
   khác được viết để khớp số liệu Nora.
2. Chạy tối thiểu hai exemplar (EDU Tier 1 và COIN Tier 2) trên Nora và TradingView
   với cùng run manifest. TradingView export hoặc Strategy Tester artifact là output
   cần lưu của reference run; nó không thay thế việc chạy Nora, cũng không thay thế
   comparator trade-by-trade.
3. Xây comparator bốn lớp theo mục 6.3; lưu mismatch rows, tolerances, hashes và run
   metadata từ cả hai engine. Comparator phải fail nếu thiếu trade, lệch signal bar,
   lệch order timing, lệch qty/giá hoặc thiếu fee/SL/TP reason.
4. **Gate PASS:** hai exemplar đạt `TV_PARITY_PASS`; nếu không có export hoặc có bất kỳ
   mismatch chưa được giải thích và owner chấp nhận, gate là `BLOCKED`.

Gate 2.TV là dependency bắt buộc của Gate 2.2, Gate 2.3, Gate 2.4, Gate 2.5 và
Gate 2.6. Compile-clean, Nautilus parity hoặc internal oracle không thể bypass gate này.

### Gate 2.0 — Đóng băng baseline và schema

1. Chạy lại inventory read-only trên đúng roots của COIN và EDU; ghi timestamp, record count, per-record code/config hash, parser/compiler version và lỗi đọc.
2. So sánh với snapshot 1.061 record; báo cáo added/removed/changed/duplicate, không âm thầm cập nhật baseline cũ.
3. Chốt schema assessment ở mục 5, Tier rubric ở mục 6 và các trạng thái review. Tách rõ fact trích từ code, fact từ config, inference của reviewer và quyết định owner.
4. **Gate PASS:** 100% record trong snapshot có identity/hash và được truy nguyên về đúng product/root; không có thao tác ghi file user.

### Gate 2.1 — Audit cấu trúc tất cả record

1. Với từng record: parse, compile đúng compiler product, trích timeframe/symbol/indicator/entry/exit/position config, SL/TP/sizing/cost, data dependency và trạng thái owner.
2. Phân loại lỗi riêng: empty, parse error, compile error, unsupported feature, missing exit, missing hard SL, missing sizing, undefined cost, data/provenance missing, possible lookahead, duplicate/hash-identical.
3. Không suy diễn “có indicator” thành signal hợp lệ; không suy diễn cờ `has_sl` thành stop thực thi được; không gộp compile-clean với safety-approved.
4. Duplicates vẫn giữ từng record và ownership; có thể tham chiếu chung source hash nhưng không mất attribution.
5. **Gate PASS:** 100% record có một hàng assessment đầy đủ, mỗi kết luận có evidence pointer; tất cả unknown được giữ `UNKNOWN/BLOCKED`.

### Gate 2.2 — Review từng chiến lược và gán Tier

1. Review luận điểm và semantics riêng từng chiến lược; không chấm chất lượng dựa trên backtest return hoặc số indicator.
2. Với từng strategy được gọi là khớp/đúng, đối chiếu với TradingView theo Gate 2.TV;
   chưa có reference/export tương ứng thì giữ `TV_NOT_VERIFIED/BLOCKED`.
3. Gán Tier 1/2 theo mục 7; record không đủ thông tin gán `UNCLASSIFIED/BLOCKED`, không ép vào Tier.
4. Đánh dấu các mục thiếu/không rõ; tác giả/owner phải quyết định mọi thay đổi có thể đổi semantics (SL, TP, short, DCA, timeframe, fee, sizing).
5. Ưu tiên vòng review: bốn COIN active trước (giữ allowlist và quarantine gates), sau đó EDU onboarding/examples, rồi COIN quarantine và EDU user records theo batch. Thứ tự này không đồng nghĩa ưu tiên giao dịch.
6. **Gate PASS:** toàn bộ 1.061 (hoặc snapshot mới đã được owner chốt) có reviewer disposition, Tier hoặc lý do unclassified, blocker list và trạng thái không thể nhầm với approval; mọi claim “khớp TradingView” có evidence Gate 2.TV.

### Gate 2.3 — Chuẩn hóa bản mẫu và compiler regression

1. Chốt hai exemplar canonical:
   - EDU Tier 1: `EduTrendPullback` lifecycle `on_start/on_bar`, class attributes rõ, RSI/EMA signal, risk-based sizing, ATR SL/TP, phí cấu hình, slippage 0.
   - COIN Tier 2: dynamic standard-deviation channel + regime EMA100; exact source semantics phải được xác minh trước khi dùng làm bản rewrite của Vinh Breakout; fee/slippage proxy có provenance.
2. Không gọi các exemplar là profitable/production-ready; thêm cảnh báo EDU về zero slippage và COIN về proxy/unverified cost.
3. Compile test qua EDU custom-strategy compiler và COIN module compiler tương ứng; assert schema/position keys/signals/cost values, không chỉ assert không exception.
4. **Gate PASS:** hai mẫu compile đúng product compiler; có test đảm bảo risk/exit keys được materialize; không có field giả định/không hỗ trợ.

### Gate 2.4 — Tạo normalized fork/version, giữ nguyên bản gốc

1. Chỉ sau khi Gate 2.0–2.3 pass mới tạo bản fork cho từng record được chuẩn hóa. Ghi `source_product`, `source_id`, `source_code_sha256`, `source_config_sha256`, `normalized_version`, reviewer, rationale và changed-fields diff.
2. Không ghi đè/định dạng lại mã user. Bản gốc vẫn mở được và hash phải giữ nguyên.
3. Không tự thêm SL/TP, thay sizing/leverage, bỏ short/DCA, đổi indicator/frame hay sửa signal để “đạt checklist”. Mục nào thiếu quyết định thì fork giữ `BLOCKED` thay vì bịa giá trị.
4. Các COIN quarantine tiếp tục quarantine; EDU user data không được copy vào COIN. Không tự chuyển candidate sang active/approved.
5. **Gate PASS:** mọi fork có provenance đầy đủ; original hashes unchanged; diff từng trường có ý nghĩa được reviewer/owner phê duyệt; không có thay đổi semantics không giải trình.

### Gate 2.5 — Kiểm thử correctness và acceptance theo fork

1. **Static/compiler:** đúng compiler, feature support, parameter ranges, schema materialization, no prohibited imports/dynamic execution.
2. **Signal:** fixture deterministic và oracle độc lập; test entry/exit bar, event-vs-level, warm-up, missing data, final-bar no-fill, duplicate signal.
3. **Execution/accounting:** test long/short nếu áp dụng, entry/exit, hard stop, gap/intrabar stop, TP, trailing, timeout, fees, funding khi có, tick/lot rounding, quantity, realized/unrealized PnL và equity. Mọi thiếu contract phải là `NOT_TESTED`, không PASS.
4. **Risk:** chứng minh tính quantity từ allocated capital/risk budget, phí/slippage đến stop, leverage/margin caps; reject khi vượt risk hoặc không thể đặt active stop.
5. **Cost split:** EDU fee-on/slippage-zero và cảnh báo; COIN fee-on/slippage proxy/stress, provenance và status unverified rõ.
6. **No-lookahead:** kiểm tra dữ liệu nến đã đóng, multi-timeframe alignment, funding timestamp và mọi feature dùng tại signal time.
7. **Result UX:** kiểm tra provenance, assumptions, warnings, blockers và distinction giữa `EDUCATION_ONLY`, `RESEARCH`, `BLOCKED`, `DEMO_ELIGIBLE_REVIEW_REQUIRED`.
8. **Gate PASS:** từng fork có test report tái lập; không có blocker High/Critical chưa được owner chấp nhận; không tuyên bố parity tổng quát ngoài fixture.

### Gate 2.6 — Hoàn tất Bước 2

- Assessment coverage 100% snapshot; mọi chiến lược có kết luận Tier/blocked và lý do.
- Mọi strategy được tuyên bố “normalized” có fork/version và source provenance; chiến lược không thể chuẩn hóa vẫn được liệt kê blocked, không bị bỏ khỏi tổng số.
- User originals hashes không đổi; COIN/EDU isolation và quarantine không đổi nếu chưa có phê duyệt riêng.
- EDU/COIN tests, compiler tests, focused fixtures và import-boundary tests pass; báo cáo có test command, kết quả, timestamp và limitations.
- `promotion_allowed = false` và `live_capital_authorized = false` vẫn giữ nguyên; Bước 2 không cấp quyền Demo/Live và không thay thế cost calibration/OOS/owner approval.

## 10. Work packages, dependency và đầu ra

| ID | Công việc | Dependency | Đầu ra bắt buộc | Không được làm |
|---|---|---|---|---|
| S2-01 | Refresh immutable inventory | — | Snapshot/hash diff và read errors | Không ghi lại strategy store |
| S2-02 | Chốt assessment schema/Tier rubric | S2-01 | Schema version + decision register | Không gọi heuristic là approval |
| S2-TV | Xây TradingView parity evidence | S2-02 | Pine/settings/run manifests, Nora-vs-TV 4-layer comparator, mismatch report | Không dùng Nautilus/internal oracle thay reference run |
| S2-03 | Batch audit toàn bộ record | S2-01, S2-02, S2-TV | Assessment rows đủ 100%, evidence/blockers | Không bỏ qua record lỗi/duplicate |
| S2-04 | Duyệt exemplar EDU/COIN và compiler tests | S2-02, S2-TV | Hai mã mẫu compile + TV parity + schema assertions | Không dùng API syntax giả định |
| S2-05 | Owner review semantics còn thiếu | S2-03, S2-04 | Quyết định có provenance hoặc blocker | Không tự đặt SL/TP/cost |
| S2-06 | Tạo normalized forks theo lô | S2-05 | Forks/version map/source hashes/diffs | Không sửa originals hoặc chuyển quarantine |
| S2-07 | Test từng fork và report | S2-06, S2-TV | Reproducible per-strategy validation + TV comparison | Không coi aggregate suite là coverage đầy đủ |
| S2-08 | Bước 2 acceptance | S2-03, S2-04, S2-07, S2-TV | Coverage, TV evidence, exceptions, owner sign-off | Không bật promotion/Live |

## 11. Các blocker và câu hỏi cần owner quyết định trong quá trình làm

- Các strategy thiếu SL: tác giả/owner chọn hard-stop semantics và giá trị; đến khi chọn thì chỉ được giữ ở trạng thái học/nghiên cứu phù hợp, không đi vào đường execution có vốn.
- TP có thể không dùng nếu exit policy khác (signal/trailing/timeout), nhưng phải khai báo rõ `TP_DISABLED` và lý do; không coi field vắng mặt là quyết định có chủ ý.
- Không có dữ liệu authoritative cho fee/funding/instrument spec: ghi proxy/unverified và giới hạn kết luận; không dùng để xếp hạng/promotion chính thức.
- Chiến lược có thể thay đổi ý nghĩa khi chuyển DSL/engine: giữ blocker cho tới khi owner duyệt mapping và có fixture chứng minh hành vi trước/sau.
- Chưa có TradingView reference run/replay và comparator tái lập được: toàn bộ claim
  parity là `NOT VERIFIED`; cần Pine reference, chart settings, cùng dữ liệu và
  trade export/Strategy Tester artifact trước khi gọi bất kỳ strategy nào là khớp.
- TradingView broker emulator/Bar Magnifier và fixed-tick slippage có thể không tương đương execution
  venue; mismatch phải được ghi rõ field, window, nguyên nhân và mức ảnh hưởng. Việc
  owner chấp nhận một mismatch không được đổi trạng thái thành `TV_PARITY_PASS`;
  chỉ được ghi nhận là exception có giới hạn trong báo cáo.
- Mọi kết quả audit phải tách ba nhãn: **đã trích xuất**, **đã kiểm thử**, **đã được owner phê duyệt**. Không gộp chúng thành “đạt chuẩn bot”.
