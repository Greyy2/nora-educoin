# FastDip — Nora strategy and backtest result

Đây là đúng strategy source và đúng cấu hình đã dùng để tạo
[trade evidence CSV](./tv_parity_fastdip_trades.csv).

## Exact asset and timeframe

| Engine | Asset | Timeframe | Timezone |
|---|---|---|---|
| Nora COIN | `BTC@perp` (input symbol `BTC`) | `24h` | UTC |
| TradingView | `OKX:BTCUSDT.P` | `1D` | UTC |

`24h` in the Nora catalog and TradingView `1D` are the same daily bar
contract for this comparison. Do not use `BINANCE:BTCUSDT`, spot BTCUSDT,
or a lower timeframe.

## 1. Nora strategy source

```python
class FastDipHarvesterStrategy(NoraStrategy):
    timeframe = "24h"
    rsi_period = 10
    sma_period = 15
    macro_period = 50
    stop_loss_pct = 2.0
    take_profit_pct = 4.0
    risk_per_trade_pct = 0.25

    def on_bar(self):
        rsi_val = rsi(close, self.rsi_period)
        sma_val = sma(close, self.sma_period)
        macro = ema(close, self.macro_period)

        self.close(
            (rsi_val > 65.0) | crossunder(close, sma_val)
        )
        self.buy(
            crossover(rsi_val, 40.0)
            & (close > sma_val)
            & (close > macro)
        )
```

Source file: [FastDip_Nora_Strategy.py](./FastDip_Nora_Strategy.py)

## 2. Exact Nora run configuration

```json
{
  "symbols": ["BTC"],
  "start": "2023-10-06",
  "end": "2026-10-03",
  "timeframe": "24h",
  "initial_capital": 10000.0,
  "position": {
    "market": "perp",
    "sizing": "risk",
    "risk_per_trade_pct": 0.25,
    "stop_loss_rate": 2.0,
    "take_profit_rate": 4.0,
    "fee_rate": 0.0005,
    "maker_fee_rate": 0.0005,
    "slippage_mode": "fixed_ticks",
    "slippage_ticks": 180,
    "stop_slippage_multiplier": 2.0,
    "quantity_step": 0.001,
    "max_notional_pct": 300.0
  }
}
```

The canonical copy of this configuration is
[FastDip_Parity_Manifest.json](./FastDip_Parity_Manifest.json).

Run command:

```bash
PYTHONPATH=nora/coin /home/vmc03/.venvs/nora312/bin/python \
  nora/check/run_fastdip_nora.py
```

## 3. Nora backtest result

| Metric | Result |
|---|---:|
| Data | BTC, 24h |
| Window | 2023-10-06 → 2026-10-03 UTC |
| Bars | 1,094 |
| Initial capital | 10,000.00 USDT |
| Final equity | 10,129.05 USDT |
| Return | 1.29% |
| MDD (Nora report) | 0.21% |
| Number of trades | 3 |
| Fees | 3.38 USDT |

## 4. Nora trade result

| # | Signal bar UTC | Entry bar / price | Exit bar / price | Qty | Status | Net PnL | Fees |
|---:|---|---|---|---:|---|---:|---:|
| 1 | 2024-01-26 | 2024-01-27 / 41,840.0 | 2024-01-30 / 43,513.6 | 0.026 | TP | 42.4040 | 1.1096 |
| 2 | 2024-10-11 | 2024-10-12 / 62,557.3 | 2024-10-14 / 65,059.6 | 0.018 | TP | 43.8928 | 1.1486 |
| 3 | 2026-08-17 | 2026-08-18 / 64,518.1 | 2026-08-19 / 67,098.8 | 0.017 | TP | 42.7532 | 1.1187 |

## 5. Pine source dùng để chạy TradingView

Mã Pine tương đương nằm tại [FastDip_TradingView_Reference.pine](./FastDip_TradingView_Reference.pine).

Không dùng source khác khi chạy TradingView. Chọn:

- `OKX:BTCUSDT.P` perpetual;
- timeframe `1D`;
- cùng khoảng `2023-10-06` đến `2026-10-03`;
- commission 0.05%;
- slippage 180 ticks;
- `process_orders_on_close=false`.

## 6. Evidence files

- [FastDip_TradingView_Reference.pine](./FastDip_TradingView_Reference.pine)
- [FastDip_Nora_Strategy.py](./FastDip_Nora_Strategy.py)
- [FastDip_Parity_Manifest.json](./FastDip_Parity_Manifest.json)
- [run_fastdip_nora.py](./run_fastdip_nora.py)
- [tv_parity_fastdip_trades.csv](./tv_parity_fastdip_trades.csv)
- [tv_parity_fastdip_evidence.json](./tv_parity_fastdip_evidence.json)
- [tv_parity_fastdip_evidence.md](./tv_parity_fastdip_evidence.md)
