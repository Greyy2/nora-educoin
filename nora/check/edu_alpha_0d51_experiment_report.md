# EDU Alpha experiment: `0d51ba8d2012` parent vs C1

**Candidate:** `0d51ba8d2012_c1_persistence`  
**Hypothesis:** Keep OBV>SMA20 and RSI14 midline cross, but require RSI>50 and OBV>SMA20 to persist across the next closed bar before triggering entry.  
**Verdict:** `BETTER_ON_RESEARCH_WINDOW_NOT_PASS`  
**Scope:** Local EDU backtest jobs only. No user alpha was changed, no bot was started, and this result does not authorize live trading.

## Frozen change

Only the entry condition changed:

```python
rsi_cross_prev = self.op.previous(self.op.crossed_above_value(rsi, self.rsi_enter_level), 1)
enter_sig = rsi_cross_prev & (rsi > self.rsi_enter_level) & (obv > obv_sma)
```

The candidate was compiled by the EDU API with program hash `9ecc9aaa16ad`. Parent code SHA256 is `44bd919a4a501343ac649a042eb41db7d677aa5e7f1d73d0660e3fe597ac3183`; candidate code SHA256 is `67564d79b06ac91f85cf1ec4d4c2fbea3320d98d23382ab0dcb3eb24a53842cd`.

Both runs used 10 OKX perpetual symbols, 24h bars, 2023-10-06 through 2026-10-03, train ratio 0.7, $10,000 initial capital, leverage 10x, risk/trade 0.5%, stop 3.0%, take-profit 0.0%, and `exit_unit=pct`. Data catalog digest, effective position settings, and execution-cost proxy match.

## Head-to-head results

| Metric | Parent | C1 | Delta (C1 - parent) |
|---|---:|---:|---:|
| Full-window return | +7.28% | +9.27% | +1.99 pp |
| Full-window max drawdown | 28.18% | 29.42% | +1.24 pp |
| Full-window trades | 256 | 238 | -18 |
| Full-window win rate | 17.6% | 14.3% | -3.3 pp |
| Full-window profit factor | 0.921 | 0.976 | +0.055 |
| Full-window fees | $124.31 | $131.95 | $+7.64 |
| Full-window expectancy (`expectancy_pct`, engine field) | +0.0001% | +0.0055% | +0.0054 pp/trade |
| Test-stage return (fresh capital) | -11.39% | -11.16% | +0.23 pp |
| Test-stage max drawdown | 24.63% | 19.74% | -4.89 pp |
| Test-stage trades | 159 | 151 | -8 |
| Test-stage win rate | 15.1% | 13.2% | -1.9 pp |
| Test-stage profit factor | 0.283 | 0.256 | -0.027 |
| Test-stage fees | $60.89 | $61.24 | $+0.35 |
| Test-stage expectancy (`expectancy_pct`, engine field) | -0.1470% | -0.1441% | +0.0029 pp/trade |

**Run receipts:** parent `20261027_195119_75f292` ([run_limited] peak RAM 1047 MB / limit 2G | exit 0); candidate `20261027_195333_c7062f` ([run_limited] peak RAM 988 MB / limit 2G | exit 0). Engine NautilusTrader 1.231.0. Fill convention is close-of-bar signal then next-bar open via synthetic OHLC quote; stop adverse ×2 is a research proxy, not venue-measured slippage. Funding, liquidation, and quote depth were not modeled.

## Interpretation and disposition

- While Full-window return improved slightly (+7.28% → +9.27%) due to skipping 18 trades, Test-stage return moved only marginally (-11.39% → -11.16%), remaining strongly negative.
- Test-stage win rate decreased from 15.1% to 13.2%, test profit factor decreased from 0.283 to 0.256, and test expectancy remained deeply negative (-0.1441%).
- Under the frozen research admission gates it does **not** pass: test return is negative, expectancy is negative, PF is below 1.05, and win rate is well below the 35% threshold.
- Waiting 1 additional close after RSI cross does not fix the underlying issue that RSI midline crosses occur within broader 60-day downtrends with negative follow-through.

**Candidate disposition:** `BETTER_ON_RESEARCH_WINDOW_NOT_PASS`. Retain as research evidence; do not promote. Preserve the parent alpha unchanged.

## Reproducible artifacts

- Candidate record: [`candidates/0d51ba8d2012_c1_persistence.json`](./candidates/0d51ba8d2012_c1_persistence.json)
- Parent job result: `../edu/data/cache/process/_mem/20261027_195119_75f292.json`
- Candidate job result: `../edu/data/cache/process/_mem/20261027_195333_c7062f.json`

## Candidate C2: SMA50 trend filter

**Candidate:** `0d51ba8d2012_c2_trend_filter`  
**Hypothesis:** Keep the RSI/OBV entry and exit rules; require `close > sma(close, 50)` at entry to avoid long entries below the medium-term price average.  
**Verdict:** `NOT_PASS`  
**Run:** EDU API job `20261027_214402_3f09f1`, completed with exit code 0; worker log reports peak RAM 1024 MB / 2 GB. The request reused the parent job's position settings, symbols, date range and data catalog. Program hash: `9355e9b34c68`; candidate source hash: `facf1d383dd587876df570a47bb5774b5b5d174538688c5e675f45c95aea4020`.

| Full-window descriptive metric | Parent | C2 | Delta |
|---|---:|---:|---:|
| Return | +7.28% | +5.87% | -1.41 pp |
| Max drawdown | 28.18% | 22.70% | -5.48 pp |
| Trades | 256 | 144 | -112 |
| Win rate | 17.6% | 18.8% | +1.2 pp |
| Profit factor | 0.921 | 0.851 | -0.070 |
| Expectancy per trade | +0.0001% | -0.0233% | -0.0234 pp |
| Fees | $124.31 | $71.46 | -$52.85 |

The filter materially reduced trades and drawdown, but also reduced net return and worsened profit factor/expectancy. Positive cumulative return does not establish a profitable edge here: the per-trade expectancy is negative and profit factor is below 1. The API response reports `test_start=2025-01-01`, while the frozen first WFA fold requires `2024-10-01`; the live API contract does not accept `test_start`. Therefore its train/test metrics are excluded, and this run is **not** an exact-fold WFA or a pass.

The per-candidate evidence summary is [`candidates/0d51ba8d2012_c2_trend_filter_evaluation.json`](./candidates/0d51ba8d2012_c2_trend_filter_evaluation.json). The two-candidate research budget for this alpha is now consumed (C1 and C2); do not add more variants against the same viewed window. Preserve the parent and record this alpha as **investigated, not passed**.
