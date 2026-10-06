# ADR-P6 — Kiến trúc thực thi thống nhất (backtest → testnet → live)

Ngày: 2026-10-06 · Trạng thái: **đã duyệt** (D1–D6 duyệt 2026-10-06) · Nhánh: `fix/pipeline-audit` · Roadmap: mục P6 · Epic: E16

## 1. Bối cảnh

Mục tiêu của hệ thống: một chiến lược (AST + tham số) chạy backtest thế nào thì đưa lên testnet/live chạy y như vậy; phần thay đổi giữa các môi trường chỉ là chiến lược, còn engine đã chuẩn hoá. NautilusTrader làm điều này bằng một lõi duy nhất (Kernel, ExecutionEngine, RiskEngine, Portfolio) và một giao diện sàn (`ExecutionClient`) mà simulator, sandbox và adapter live cùng cài; chiến lược chỉ nói chuyện với bus/cache/clock.

Hiện trạng Nora (đã kiểm chứng khi đọc code, 2026-10-06):

| Phần | Nơi | Ghi chú |
|---|---|---|
| Backtest sản xuất | `core/backtest/kernel.py` (numba) | Bản dịch nguyên văn bit-identical của `PositionTracker` + `CapitalLedger` + vòng danh mục |
| Mô phỏng Python | `core/execute/tracker.py` (`PositionTracker`) | Chỉ còn một nơi gọi `on_bar` trong sản xuất: `PaperBook.step_bar`; còn là mẫu tham số/trạng thái cho `pack_trackers` |
| Vòng danh mục Python | `live/paper.py` (`PaperBook.step_bar`) | Lặp lại quy tắc risk của kernel |
| Bot sàn | `live/bot.py` | KHÔNG dùng tracker: tự đặt lệnh (`_open_exec`, `_protect`, `step_exec`), có risk riêng (`_risk_controls`) với định nghĩa vốn khác sim |
| Oracle test | `test/reference_engine.py` | Bản đóng băng vòng lặp Python gốc, chỉ để so bit |

Hậu quả: logic khớp lệnh và rủi ro có 4 bản; parity giữa sim và live dựa vào test và `compare.py` (phát hiện lệch sau khi xảy ra), không dựa vào cấu trúc.

## 2. Quyết định

### 2.1 Mức parity (cách nói chính xác)

- **Bit-identical** (xác định, có test): kernel ↔ `reference_engine` ↔ đường event của sim (SimVenue + PositionManager).
- **Trong dung sai** (không xác định, đo bằng `compare.py`): sim ↔ sàn thật. Sàn không deterministic nên không thể hứa trùng từng bit.

### 2.2 Kiến trúc đích

```
Strategy slot (AST + params)  ->  Runner.step_bar(t, bars, signals, funding)
        PositionManager (policy một lần: sizing, SL/TP/ladder/trailing từ avg, timeout, exit)
              | ra LỆNH                           ^ nhận Fill / Reject
              v                                   |
        Venue Protocol  <-- SimVenue (backtest-py, paper)   |   OkxVenue (demo, live)
        risk.py (một risk engine)   account.py (vốn + vị thế theo sự kiện)
```

- Giao diện kéo (pull): `match_next(slot, bar) -> Optional[Fill]` cho sim, `poll()` cho OKX. Không callback lồng nhau.
- Sự kiện tối thiểu: `OrderUpdate(status)`, `Fill`, `FundingApplied`, `OrderRejected`; Position opened/changed/closed do `PositionBook` suy ra.
- Rounding theo `Filters` là thuộc tính của venue; mặc định no-op trong SimVenue (giữ golden), bật ở profile paper/shadow.
- Kernel numba giữ nguyên làm bộ tăng tốc nghiên cứu (500k alpha ≤ 4 h) và là backtest sản xuất duy nhất; đường event KHÔNG thành đường nghiên cứu thứ hai.
- `okx_venue.py` nằm ở `backend/live/` (I/O); `core/execute/` chỉ chứa Protocol và sim.

### 2.3 Quyết định đã chốt (người dùng, 2026-10-06)

1. Phạm vi: toàn bộ P6.0–P6.9, làm lần lượt từng ID, mỗi ID một commit.
2. `PositionTracker` nghỉ hưu ở P6.9 sau khi đường event bit-identical; `reference_engine` giữ làm oracle test.
3. Vốn rủi ro ở live/demo: sổ vốn ảo đã chốt, event-sourced (cùng định nghĩa sim: vốn đã chốt + funding; kill switch theo MTM xấu nhất của nến). Vốn thật của sàn chỉ là cảnh báo lệch.

### 2.4 Mặc định D1–D6 (người dùng duyệt 2026-10-06)

| # | Nội dung | Mặc định |
|---|---|---|
| D1 | Nhiều slot chiến lược trên cùng một symbol ở live (OKX net mode chỉ có một vị thế và một giá TB mỗi symbol) | Live ép `max_per_symbol = 1`, kiểm lúc deploy (khớp `RISK` mặc định ở `core/strategy/book.py`) |
| D2 | Lệnh bảo vệ | SL/TP đặt trên sàn (sống sót khi bot sập); sim mô hình hoá giống vậy |
| D3 | Kill switch live | H/L cuối nến + kiểm tra mẫu mỗi 10 s (xấp xỉ bảo thủ của "MTM xấu nhất trong nến"; ghi rõ) |
| D4 | Giá khớp SL | OKX SL là market-on-trigger theo giá LAST; kiểm bằng `stop_fill="extreme"` của sim và hiệu chỉnh slippage từ `compare` |
| D5 | Thời điểm vào lệnh | Live vào vài giây sau khi nến đóng, sim vào ở open + trượt giá; chấp nhận và đo |
| D6 | DEX / `tick_run` | Hoãn ra ngoài P6 |

## 3. Hệ quả

- Policy vị thế (kích thước, SL/TP từ giá TB, thang DCA, trailing, timeout, thoát) nằm ở một nơi (`manager.py` + `policy.py`) và dùng được với mọi Venue: khác biệt còn lại giữa sim và live chỉ là khác biệt của sàn.
- Một risk engine (`risk.py`): `PaperBook`, runner và live cùng gọi; kernel giữ bản numba, khoá bằng parity (không thêm test kernel mới).
- Hai thay đổi hành vi có chủ đích ở live (đều hướng về sim): vốn rủi ro là sổ ảo (thay vốn đo từ sàn) và kill switch dùng H/L nến.
- `compare.py` tiến hoá từ mức lệnh sang mức sự kiện (P6.8): căn theo (symbol, slot, seq, kind), báo chênh bps theo loại lệnh, có ngân sách dung sai, xuất tham số slippage hiệu chỉnh.

## 4. Rủi ro và giảm thiểu

1. Sổ vốn dùng chung tuần tự: runner giữ đúng thứ tự (symbol, entry), gọi venue + manager theo từng ô; test parity nhiều symbol × nhiều chiến lược.
2. Vòng settle trong nến (tính lại avg/SL/liq sau mỗi tầng DCA, hoà thì thoát trước): venue trả fill kế tiếp rồi manager phản ứng; ưu tiên hoà là khoá sắp xếp tường minh.
3. Mô hình lệnh không chỉ là limit: lệnh DCA có `trigger_px` và giá khớp khác nhau; SL/trailing có `stop_fill`; TP khớp ở mức TP (từ 2026-10-06; trước đó `max(tp_level, open)`, xem mục 8); đặt trong tham số fill-model của SimVenue.
4. Quy tắc theo độ phân giải nến ("TP bỏ qua nến có DCA", "trailing dùng đỉnh các nến trước") là chính sách `intrabar_path="adverse_first"` của SimVenue, có test; sàn thật có thể khác và `compare.py` đo.
5. Thứ tự phép toán float: công thức mức giá chỉ ở `policy.py`; avg/qty/phí cộng dồn trong một `PositionBook` giữ đúng thứ tự `_add_layer`.
6. Thanh lý là fill do venue sinh (chỉ sim); OKX chỉ quan sát (cờ `generates_liquidation`).
7. Số đường Python tạm thời tăng (tracker, event path, oracle): chỉ hợp lệ trong lúc di cư; P6.9 gỡ tracker. Giữ tracker và `RefPositionTracker` làm oracle suốt P6.4–P6.8.

## 5. Kế hoạch nghỉ hưu `PositionTracker` (P6.9)

Điều kiện: P6.5 (đường event bit-identical với kernel/oracle), P6.7 (contract test OkxVenue), P6.8 (Bot unified chạy demo song song đường cũ, `compare.py` trong dung sai) đều xong và người dùng duyệt. Khi đó: gỡ `PositionTracker.on_bar` và executor trong `tracker.py`; `pack_trackers` và `BacktestEngine.add_strategy_flow` dùng `StrategyParams` chuẩn hoá thay vì tracker; golden, `test_kernel_parity`, full suite phải xanh.

## 6. Ngoài phạm vi

Trần thanh khoản theo volume nến và hiệu chỉnh `limit_through_pct` từ dữ liệu `compare` (làm sau khi P6.8 có số đo, mặc định tắt để golden không đổi); chuyển DEX/`tick_run` sang SimVenue; event store/replay kiểu Nautilus (`events.jsonl` hiện có đủ làm nền).

## 7. Tài liệu liên quan

Lộ trình và tiêu chí "Xong khi" từng ID: `roadmap.md` mục P6. Nguồn của kiến trúc đích: NautilusTrader (`crates/system`, `crates/execution`, `crates/backtest`, `crates/live`, adapter `sandbox`).

## 8. Ghi chú 2026-10-06: đổi quy tắc khớp có chủ đích (bảo thủ), người dùng duyệt

Lý do: test chéo engine với NautilusTrader 2.0.0rc6 (`test/scripts/nautilus_diff/REPORT.md`, commit b4b437b) cho thấy Nora lạc quan đúng ở hai quy tắc; sàn thật cũng hành xử như Nautilus. Đổi ở MỌI cài đặt, bit-identical với nhau (`tracker.py`, `kernel.py`, `sim_venue.py` + `manager.py`, oracle `test/reference_engine.py`); `live/bot.py` và `okx_venue.py` không đổi (sàn tự hành xử như vậy).

1. **SL cũ sau fill DCA.** Trong một nến, từ sau tầng DCA đầu tiên khớp, mức SL dùng cho phần còn lại của nến là mức SL lúc tầng đó khớp (tính từ avg cũ); SL tính từ avg mới có hiệu lực từ nến sau. Giá thanh lý vẫn tính lại ngay. Trước đây SL dời ngay sang mức mới (xa hơn) và nến tiếp tục quét với SL mới.
2. **Gap xuyên lệnh limit chờ sẵn.** DCA và TP khớp đúng ở mức đặt (khối lượng DCA = danh nghĩa / mức đặt) kể cả khi open đã vượt mức; trước đây khớp ở `min(level, open)` (DCA, long) / `max(tp, open)` (TP, long). Stop-market (SL, trailing) vẫn gap -> khớp ở open; lệnh market và thanh lý không đổi; AMM (`limit_taker`, swap) vẫn khớp ở open.

Golden snapshot được sinh lại có chủ đích (`test/scripts/make_golden.py`); test mới: `test/test_conservative_fills.py` (bốn cài đặt phải ra cùng kết quả). Còn lại lạc quan so với Nautilus là bảo thủ có chủ đích: SL thắng TP trong cùng nến, và nến có DCA khớp thì bỏ TP.

## 9. Ghi chú 2026-10-06 (lần 2): `intrabar_path` — khớp ĐÚNG như NautilusTrader, người dùng quyết định

Quyết định: Nora phải chính xác như chuẩn tham chiếu, không bảo thủ hơn. Tham số mới `StrategyParams.intrabar_path` (kernel: `PI_PATH`), **mặc định `"ohlc"`**:
- `"ohlc"` (= Nautilus mặc định): nến đi Open -> High -> Low -> Close. `"adaptive"` (= `bar_adaptive_high_low_ordering=True`): cực gần open trước; luật Nautilus là `bar_high_first = high - open < open - low`, nên HOÀ khoảng cách thì Low trước. `"adverse_first"` = hành vi cũ (mục 8), giữ nguyên từng bit để kiểm bền.
- Mỗi chặng là MỘT tick (chặng không đổi giá bị bỏ qua; tick mở cửa luôn xử lý). Trong tick, thứ tự nhóm của Nautilus (`iterate`: bid trước ask, limit trước stop): (a) mọi tầng DCA bị xuyên qua (kể cả tầng nằm dưới mức SL), (b) chốt lời, (c) stop (SL, trailing, thanh lý; mức cao nhất trước với long). Không theo thứ tự "gặp trước dọc đoạn giá". Cài đặt đối xứng cho short (Nautilus thật xử lý theo phía lệnh nên short khác; không đo được vì test chéo chỉ có long).
- Stop-market khớp ở mức kích hoạt (tick mở cửa/gap: ở open); limit (DCA, TP) khớp ở mức đặt; `stop_fill="extreme"` và `limit_through_pct` giữ nghĩa cũ.
- **SL / TP cố định cả nến** (kiểm bằng thực nghiệm trên Nautilus 2.0.0rc6): sự kiện fill của sàn chỉ tới strategy SAU khi cả nến đã khớp, nên SL/TP đặt lại từ avg mới sau fill DCA chỉ có hiệu lực từ nến sau (không phải "chặng sau"); tầng DCA kế vẫn nằm sẵn (thang lệnh đặt trước) nên khớp tiếp trong nến; giá thanh lý tính lại ngay. TP không còn bị bỏ qua trong nến có DCA: nếu chặng sau chạm mức TP CŨ thì khớp ở mức đó (cả vị thế). TP mới (từ avg sau DCA) mà đã "trong giá" ở close thì khớp ngay ở close như lệnh taker (Nautilus: lệnh đặt lại thấy sổ lệnh lúc close).
- Trailing: đỉnh/đáy chạy theo từng chặng; mức dùng ở một chặng là mức tính sau chặng trước; kích hoạt kiểm theo avg hiện tại mỗi chặng.
- Cài đặt giống hệt ở `policy.py` (hàm thuần), `tracker.py`, `kernel.py` (numba; `_quiet_bar` dùng đỉnh cả nến cho trailing), `sim_venue.py` + `manager.py` (venue giữ đường giá, đóng băng SL/TP ở lần kéo sự kiện đầu của nến, tự chạy đỉnh trailing từ `Order.peak`) và oracle `test/reference_engine.py`. Slot SimVenue cũ trong `paper.pkl` giữ `adverse_first`. Test: `test/test_intrabar_path.py`; golden sinh lại có chủ đích. Số liệu so chéo: `test/scripts/nautilus_diff/REPORT.md`.

## 10. Ghi chú 2026-10-06 (lần 3): nến danh mục HAI PHA — hết nhìn trước giữa các tài sản (P6.12), người dùng duyệt

Lỗi (đo ở `test/scripts/nautilus_diff/EXT_REPORT.md`, mục S8): mỗi nến, vòng danh mục chạy TRỌN nến của tài sản A (mở nến, SL/TP/DCA trong nến, đóng nến, `last_close[A] = close[t]`) rồi mới xét lệnh vào chờ của tài sản B ở open t. Nên hạn mức của B (số vị thế, trần gross, trần rủi ro mở, dd_throttle) và VỐN dùng để tính khối lượng thấy cả những lệnh thoát trong nến và giá đóng nến của A — chuyện xảy ra SAU thời điểm open t. Lệch vốn cuối so với NautilusTrader tới 1.6-2.7% (lạc quan khi trần số vị thế: slot do A nhả trong nến được B dùng ngay ở open).

Sửa: mỗi nến chia hai pha cho mọi tài sản theo thứ tự sổ (định nghĩa "sync" của `ext_run_nora.py`, đã khớp Nautilus trong 0.025%):
1. **Pha 1 — mở nến.** Funding (theo từng tài sản, ở giá open); từng slot: luật bỏ qua, `admit_entry` rồi `on_bar_open` (thoát chờ / hết thời gian giữ ở open, vào lệnh chờ ở open). Hạn mức xét theo trạng thái LÚC MỞ NẾN: vị thế mở sau các lệnh thoát/vào ở open của tài sản đứng trước (tài sản đứng sau chưa xử lý nên vị thế của nó vẫn tính là mở), gross định giá mọi vị thế theo `last_close` = đóng nến TRƯỚC (kể cả vị thế vừa vào ở open), vốn = sổ vốn sau funding + lệnh thoát ở open. Không còn gán `last_close[b] = open` trước khi tính gross.
2. **Pha 2 — trong nến.** Mọi tài sản theo thứ tự sổ: `on_bar_rest` (đường giá `ohlc` / `adaptive` / `adverse_first` như cũ, sổ sách cuối nến, cờ vào / thoát chờ), rồi cập nhật `last_close/low/high/open`.
3. **Pha 3.** MTM, `peak_mtm`, kill switch — không đổi.

Cài đặt giống hệt ở cả bốn nơi: `kernel.py::portfolio_kernel` (`_on_bar_open` + `_on_bar_rest`; `_on_bar` = hai hàm đó cho đường đơn tài sản; tua nhanh phút yên tĩnh không đổi vì mỗi slot vẫn chỉ phụ thuộc trạng thái của chính nó giữa các nến yên tĩnh), `Runner.step_bar` (PaperBook event + tracker, bot sàn qua `unified.py`), oracle `test/reference_engine.py::RefPortfolioEngine.run`; `PositionTracker` / `PositionManager` / `RefPositionTracker` có thêm `on_bar_open(t, o, h, l, c, can_open)` và `on_bar_rest(t, o, h, l, c, entry_signal, stop_signal, closed, vol, dca_gate)`, còn `on_bar()` = cả hai. Đường đơn tài sản (`BacktestEngine` / `single_kernel`) không đổi kết quả (một tài sản, hai pha liền nhau). Thứ tự ghi lệnh đóng: lệnh đóng ở open của mọi tài sản đứng trước lệnh đóng trong nến.

Hệ quả: golden `portfolio_synthetic` / `portfolio_real` sinh lại có chủ đích; test mới `test/test_portfolio_sync_open.py` (slot nhả trong nến không dùng được ở open; gross room và vốn tính khối lượng theo trạng thái lúc mở nến; thoát tại open thì dùng được). Số liệu so chéo sau sửa: mục "after fix" của `EXT_REPORT.md`. Giới hạn đã biết: funding áp theo từng tài sản trong pha 1 (hạn mức của tài sản đứng trước chưa thấy funding của tài sản đứng sau tại cùng open).
