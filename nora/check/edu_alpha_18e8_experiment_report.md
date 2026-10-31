# EDU Alpha experiment & rebaseline: `18e87aa868ad`

**Alpha:** `18e87aa868ad` (Fast Dynamic Channel Breakout)  
**Owner:** `vinh`  
**Parent Rebaseline Job:** `20261027_193923_b7b8f5`  
**Verdict:** `INSUFFICIENT_SAMPLE` (< 20 OOS test trades under normalized `exit_unit=pct`)  
**Scope:** Local EDU backtest jobs only. No user alpha was modified, no bot was started, and this result does not authorize live trading.

---

## 1. Context and Rebaseline Rationale

In historical baseline reports, `18e87aa868ad` had an exit unit mismatch (`atr` vs code-declared `pct`), yielding 71 OOS trades. Rebaseline was submitted with normalized contract `exit_unit=pct` matching the code's `stop_loss_pct = 2.5` declaration.

- **Job ID:** `20261027_193923_b7b8f5`
- **Execution:** `ops/run_limited.sh -- -m backend.jobs.runner 20261027_193923_b7b8f5`
- **Resource limit:** `nora.slice` (cgroup limit 2GB, recorded peak RAM: 1,070 MB, exit code: 0)
- **Engine:** NautilusTrader 1.231.0
- **Time window:** 2023-10-06 to 2026-10-03 (train_ratio: 0.7)
- **Symbols:** 10 OKX perp symbols (BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, TRX)
- **Capital & Position:** $10,000 initial capital, leverage 10x, risk_per_trade 4.0%, stop_loss 2.5%, exit_unit `pct`.

---

## 2. Rebaseline Results (Authoritative Receipts)

| Metric | Full-Window (`simulate`) | Train-Stage (`train`) | Test-Stage (`test`, fresh capital) |
|---|---:|---:|---:|
| Return (%) | +63.45% | +63.45% | -29.25% |
| Max Drawdown (%) | 33.50% | 33.50% | 33.93% |
| Trades count | 16 | 16 | **19** |
| Win rate (`win_rate_trades`) | 43.8% | 43.8% | 5.3% |
| Profit factor (`profit_factor_trades`) | 4.691 | 4.691 | 0.132 |
| Expectancy (`expectancy_pct`) | +4.7061% | +4.7061% | -1.7471% |
| Fees (USD) | $63.71 | $63.71 | $62.92 |

---

## 3. Evaluation against Frozen Protocol Gates

1. **Trade Count Gate:** Protocol requires minimum 20 trades in OOS test stage (`min_total_trades >= 20`). The rebaseline produced exactly **19 trades** in the test stage.
2. **Outcome:** Under the normalized execution contract, the strategy does not meet the minimum sample threshold for statistically meaningful walk-forward tuning or parameter optimization.
3. **Performance:** Even within the 19 trades, win rate collapsed to 5.3% (1 win out of 19) and profit factor was 0.132 with expectancy of -1.75%/trade.

---

## 4. Final Disposition

- **Disposition:** `INSUFFICIENT_SAMPLE`
- **Decision:** Freeze alpha without parameter sweeping. Candidate `18e87aa868ad_c1_channel_hold` is archived in `nora/check/candidates/` as research documentation, not promoted.
- Original user alpha file in `nora/edu/data/alpha/user/18e87aa868ad.json` is preserved 100% intact.
