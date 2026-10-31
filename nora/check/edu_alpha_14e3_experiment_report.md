# EDU Alpha experiment: `14e3b934b1e5` parent vs C1

**Candidate:** `14e3b934b1e5_c1_roc_rising`  
**Hypothesis:** Keep the existing EMA30 + ROC10 > 3 entry, but require ROC10 to be rising versus the previous closed bar.  
**Verdict:** `BETTER_ON_RESEARCH_WINDOW_NOT_PASS`  
**Scope:** Local EDU backtest jobs only. No user alpha was changed, no bot was started, and this result does not authorize live trading.

## Frozen change

Only the entry condition changed:

```python
enter_sig = (
    (close > ema)
    & (roc > self.roc_enter_level)
    & (roc > self.op.previous(roc, 1))
)
```

The candidate was compiled by the EDU API with program hash `061e4f6a6bf0`. Parent code SHA256 is `2a4de2045194155173cd3d0fcf9a4327efe385d037714ff95371b173574006df`; candidate code SHA256 is `e2332095287c18f814f495485d29f299a6655ecd5d2bd7083ccc27c6a19991f9`.

Both runs used 10 OKX perpetual symbols, 24h bars, 2023-10-06 through 2026-10-03, train ratio 0.7, $10,000 initial capital, leverage 10x, risk/trade 0.5%, stop 3%, take-profit 5%, and `exit_unit=pct`. Data catalog digest, effective position settings, and execution-cost proxy match.

## Head-to-head results

| Metric | Parent | C1 | Delta (C1 - parent) |
|---|---:|---:|---:|
| Full-window return | -29.81% | -26.19% | +3.62 pp |
| Full-window max drawdown | 30.17% | 30.01% | -0.16 pp |
| Full-window trades | 736 | 583 | -153 |
| Full-window win rate | 44.6% | 44.3% | -0.3 pp |
| Full-window profit factor | 0.664 | 0.650 | -0.014 |
| Full-window fees | $238.15 | $190.30 | -$47.85 |
| Test-stage return (fresh capital) | -27.78% | -27.76% | +0.02 pp |
| Test-stage max drawdown | 30.33% | 30.04% | -0.29 pp |
| Test-stage trades | 381 | 398 | +17 |
| Test-stage win rate | 36.5% | 34.4% | -2.1 pp |
| Test-stage profit factor | 0.476 | 0.461 | -0.015 |
| Test-stage fees | $129.05 | $131.89 | +$2.84 |
| Test-stage expectancy (`expectancy_pct`, engine field) | -0.0836% | -0.0804% | +0.0032 pp/trade |

**Run receipts:** parent `20261027_192941_f36171` (peak RAM 1,140 MB / 2 GB); candidate `20261027_193324_1d0c42` (peak RAM 1,079 MB / 2 GB). Engine NautilusTrader 1.231.0. Fill convention is close-of-bar signal then next-bar open via synthetic OHLC quote; stop adverse ×2 is a research proxy, not venue-measured slippage. Funding, liquidation, and quote depth were not modeled.

## Interpretation and disposition

- Return and engine expectancy improved only marginally on this already-reviewed research window. The return remains strongly negative; expectancy remains negative.
- Candidate has lower test-stage win rate and profit factor, more test-stage trades, and slightly higher test-stage fees. This is not a robust or profitable strategy.
- Under the frozen research admission gates it does **not** pass: test return is negative, expectancy is negative, PF is below 1.05, win rate below 35%, and MDD 30.04% is above the 30% limit.
- This single train/test summary is not a completed multi-fold WFA. The window has already been inspected; there is no untouched holdout. Fee stress at 1.5× was not run.
- Classification follows the requested comparison rule because both return and expectancy moved slightly upward, but the result is only `BETTER_ON_RESEARCH_WINDOW_NOT_PASS`; it must not be called `PASS`, WFA validation, or promotion evidence.

**Candidate disposition:** retain as research evidence; do not promote. Preserve the parent alpha unchanged. The alpha remains unprofitable and fails admission gates.

## Reproducible artifacts

- Candidate record: [`candidates/14e3b934b1e5_c1_roc_rising.json`](./candidates/14e3b934b1e5_c1_roc_rising.json)
- Parent job result: `../edu/data/cache/process/_mem/20261027_192941_f36171.json`
- Candidate job result: `../edu/data/cache/process/_mem/20261027_193324_1d0c42.json`
- Baseline job: `../edu/data/cache/process/_mem/20261027_140340_53ff40.json`
