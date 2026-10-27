# FastDip Nora vs TradingView evidence

> Đây là Nora run + Pine replay độc lập trên cùng data manifest. Chưa phải export Strategy Tester từ TradingView.

- **Status:** `NORA_VS_INDEPENDENT_PINE_REPLAY; ACTUAL_TRADINGVIEW_EXPORT_PENDING`
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

- Nora và independent Pine replay hiện khớp signal bars, fixed-tick fill, quantity, fees và PnL trong tolerance đã chốt.
- MDD replay độc lập là **0.1261%** so với Nora report **0.21%**; đây là khác biệt về cách dựng equity/intrabar drawdown, chưa được gọi là TradingView MDD cho tới khi có Strategy Tester export.
- Nếu Strategy Tester export của TradingView trùng bảng Pine replay theo số trade, signal bar, entry/exit bar, giá, qty, reason, phí và PnL thì mới được nâng lên `TV_PARITY_PASS`.
- File này chưa tự tuyên bố TradingView PASS vì browser hiện chưa cung cấp Strategy Tester export thật.
- Chi tiết machine-readable nằm trong `tv_parity_fastdip_evidence.json`; bảng trade nằm trong `tv_parity_fastdip_trades.csv`.
