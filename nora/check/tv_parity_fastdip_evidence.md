# FastDip Nora vs local Pine replay audit

> Đây không phải TradingView Strategy Tester evidence. Đây là Nora run so với một Python replay viết tay theo logic Pine; audit dưới đây tìm thấy mismatch nên không được gọi là parity.

- **Status:** `PARITY_NOT_PROVEN; LOCAL_REPLAY_EXIT_TIME_MISMATCH; ACTUAL_TRADINGVIEW_EXPORT_PENDING`
- **Data:** BTC 24h, 2023-10-06 đến 2026-10-03, 1094 bars, UTC
- **Nora program hash:** `18501143b505`
- **Pine SHA-256:** `0a0086f9424d47ec76daca90d7db808e8d0d431408aae9802f72c6b8a8b965b0`

## Strategy inputs cần nhập trên TradingView

| Input | Value |
|---|---:|
| RSI Period | 10 |
| SMA Period | 15 |
| Macro EMA Period | 50 |
| Entry RSI crossover | 40 |
| Exit RSI | > 65 |
| Stop loss | 2% |
| Take profit | 4% |
| Initial capital | 10,000 USDT |
| Commission | 0.05% |
| Pine slippage | 180 ticks |
| Process orders on close | false |

## Nora result

- Trades: **3**
- Return: **1.29%**
- MDD: **0.21%**
- Fees: **3.38 USDT**
- Final equity: **10129.0500 USDT**

## Independent Pine replay result

- Trades: **3**
- Signal rows: **320**
- Signal bars Nora vs independent Pine replay: **MATCH**
- Pine replay return/MDD: **1.2905% / 0.1261%**

| # | Signal bar UTC | Entry bar UTC | Exit bar UTC | Entry | Exit | Qty | Reason | PnL net |
|---:|---|---|---|---:|---:|---:|---|---:|
| 1 | 2024-01-26T00:00:00+00:00 | 2024-01-27T00:00:00+00:00 | 2024-01-30T00:00:00+00:00 | 41840.0000 | 43513.6000 | 0.0260 | TP | 42.4040 |
| 2 | 2024-10-11T00:00:00+00:00 | 2024-10-12T00:00:00+00:00 | 2024-10-14T00:00:00+00:00 | 62557.3000 | 65059.6000 | 0.0180 | TP | 43.8928 |
| 3 | 2026-08-17T00:00:00+00:00 | 2026-08-18T00:00:00+00:00 | 2026-08-19T00:00:00+00:00 | 64518.1000 | 67098.8000 | 0.0170 | TP | 42.7532 |

## Trade-by-trade mismatch: Nora vs Pine replay

| # | Field | Nora | Pine replay | Delta |
|---:|---|---:|---:|---:|
| 1 | entry_price | 41840.0000 | 41840.0000 | +0.0000 |
| 1 | exit_price | 43513.6000 | 43513.6000 | +0.0000 |
| 1 | qty | 0.0260 | 0.0260 | +0.0000 |
| 1 | pnl_usd | 42.4040 | 42.4040 | +0.0000 |
| 1 | fees_usd | 1.1096 | 1.1096 | +0.0000 |
| 2 | entry_price | 62557.3000 | 62557.3000 | +0.0000 |
| 2 | exit_price | 65059.6000 | 65059.6000 | +0.0000 |
| 2 | qty | 0.0180 | 0.0180 | +0.0000 |
| 2 | pnl_usd | 43.8928 | 43.8928 | +0.0000 |
| 2 | fees_usd | 1.1486 | 1.1486 | +0.0000 |
| 3 | entry_price | 64518.1000 | 64518.1000 | +0.0000 |
| 3 | exit_price | 67098.8000 | 67098.8000 | +0.0000 |
| 3 | qty | 0.0170 | 0.0170 | +0.0000 |
| 3 | pnl_usd | 42.7532 | 42.7532 | +0.0000 |
| 3 | fees_usd | 1.1187 | 1.1187 | +0.0000 |

## Kết luận tạm thời

- **Điều đã đối chiếu cục bộ:** Nora và Python replay có cùng 320 signal rows, cùng 3 trade, và các giá entry/exit, quantity, phí, PnL hiển thị trùng tới 4 chữ số thập phân. Cả 3 replay trades đều là TP; không có stop-fill evidence.
- **Mismatch quan sát được:** mỗi `close_time` trong Nora ledger muộn hơn `exit_time` của replay đúng 86,400,000 ms (một ngày/bar): trade 1 `2024-01-31` vs `2024-01-30`; trade 2 `2024-10-15` vs `2024-10-14`; trade 3 `2026-08-20` vs `2026-08-19`. Giá/PnL trùng không xóa được sai khác thời điểm. Chưa xác định được đây là semantics timestamp hay execution-lifecycle bug; cần truy lại raw fill/event timestamp và bar index trước khi đối chiếu lại.
- **Gate của generator không đủ chặt:** code so sánh signal bar/type, nhưng không assert; trade rows được ghép theo vị trí bằng `zip`, không kiểm tra số lượng trước khi ghép. So sánh từng trade không bao gồm entry/exit bar/time hoặc exit reason. Vì vậy phần “mismatch” được ghi trong báo cáo cũ không phải một bộ kiểm định đầy đủ; test có thể báo các cột PnL trùng dù lifecycle lệch.
- **Source provenance không khớp:** SHA-256 trong manifest là `0a0086f9424d47ec76daca90d7db808e8d0d431408aae9802f72c6b8a8b965b0`, còn [FastDip_TradingView_Reference.pine](./FastDip_TradingView_Reference.pine) hiện tại có SHA-256 `df3bc9cffd199323a2e09aaf23bef236d038033bf4d65c3017d68927192d8f94`. Không có bản source bất biến ứng với hash trong manifest, nên evidence JSON không được gắn với Pine file hiện tại.
- **Execution cost mismatch:** Python replay đặt stop slippage là `2 × 180 ticks` (36 USDT/BTC); Pine source hiện cấu hình `slippage=180` ticks global và không thể đại diện bằng cấu hình đó cho cùng mức stop proxy 36 USDT. Ba trade hiện có đều TP nên không kiểm tra được khác biệt này.
- MDD replay độc lập là **0.1261%** so với Nora report **0.21%**; đây là khác biệt về cách dựng equity/intrabar drawdown, chưa được gọi là TradingView MDD cho tới khi có Strategy Tester export.
- **Actual TradingView:** chưa chạy Strategy Tester và chưa có export. Browser chỉ xác nhận trang chart công khai; Pine Editor mở ở trạng thái guest/default, không có strategy Tester receipt. Không upload source code người dùng lên dịch vụ bên thứ ba trong lượt này.
- **Verdict:** `NOT_PARITY / NOT_VERIFIED`. Chỉ được đánh giá lại sau khi source/data/config hashes khớp, so sánh đủ số trade và đầy đủ signal/fill/exit timestamps, prices, quantity, reason, fees/PnL, có fixture stop/TP-gap/intrabar ordering, và có Strategy Tester export thật nếu tuyên bố parity với TradingView.
- Chi tiết machine-readable nằm trong `tv_parity_fastdip_evidence.json`; bảng trade nằm trong `tv_parity_fastdip_trades.csv`.
