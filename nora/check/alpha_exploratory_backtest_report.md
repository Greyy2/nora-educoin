# COIN Alpha Manifest Exploratory Backtest

- **Status:** COMPLETED_EXPLORATORY
- **Run ID:** `71793413e6480d97`
- **Manifest:** 1 variants; SHA-256 `e8c3de427a7ebe739c4d592c269575239d4573303ecec4ac6e29cd88e02da6c7`
- **Active catalog:** `/home/vmc03/norabt/nora/coin/data/market/okx/catalog`
- **Catalog digests:** {"BTC": "cd026438b6a668b1", "ETH": "8d62dc2d69c4d5cf"}
- **Initial capital per independent run:** 10,000.00 USDT
- **Run config:** default alpha parameters, 0.5% base risk/trade, legacy shared risk config, stop_fill=`level`, regime off; no parameter optimization.
- **Important:** this is an exploratory screen over the latest available period within the engine's 1,100-day limit (including its 20-day warm-up), not WFA/OOS, DSR, cost stress, parity certification, or bot eligibility. Per-variant timestamps and whether the window was capped are in raw artifacts. Fee tier is unverified; funding is not modeled; liquidation is not modeled; quotes are synthetic OHLC-open proxies.
- **Raw artifacts:** `/home/vmc03/.local/share/norabt-alpha-runs/exploratory-71793413e6480d97/raw/` (gzip JSON per variant).

## Per-variant results

| Candidate | Symbol | Frame | Status | Net return % | Net PnL USDT | Closed trades | Win % | Avg closed PnL USDT | MDD intrabar % | MDD daily % | Fees USDT | Sharpe |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| kema_long | BTC-USDT-SWAP | 5m | COMPLETED_EXPLORATORY | 6.85 | 684.8322446900002 | 45 | 31.1 | 15.218494326444445 | 5.16 | 5.0 | 34.50996531 | 0.79 |

## Candidate aggregate (descriptive only)

| Candidate | Variants complete | Positive equity return | Total closed trades | Mean variant return % | Mean MDD intrabar % |
|---|---:|---:|---:|---:|---:|
| kema_long | 1/1 | 1 | 45 | 6.85 | 5.16 |

Metrics are per independent single-symbol run; candidate aggregates are not a combined portfolio and are not risk-normalized.
A positive full-window return is not an alpha pass. No run in this report may be promoted.
