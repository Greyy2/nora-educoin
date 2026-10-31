# EDU Alpha experiment & disposition: `15567e02a806`

**Alpha:** `15567e02a806` (Triple EMA Trend Alignment)  
**Owner:** `23dc66cd61c6`  
**Verdict:** `INSUFFICIENT_SAMPLE` (9 OOS test trades across historical period)  
**Scope:** Local EDU evaluation only. No user alpha was modified, no bot was started, and this result does not authorize live trading.

---

## 1. Context and Baseline Data

- **Historical Baseline Job:** `20261027_105423_b6e41b`
- **Engine:** NautilusTrader 1.231.0
- **Time window:** 2023-10-06 to 2026-10-03 (train_ratio: 0.7)
- **Symbols:** 10 OKX perp symbols (BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, TRX)
- **Timeframe:** 24h

---

## 2. Baseline Metrics

| Metric | Full-Window (`simulate`) | Test-Stage (`test`) |
|---|---:|---:|
| Return (%) | +0.20% | -33.74% |
| Trades count | 24 | **9** |
| Fees (USD) | $165.70 | $56.90 |
| PnL Net (USD) | +$20.20 | -$3,374.00 |

---

## 3. Evaluation against Frozen Protocol Gates

1. **Trade Count Gate:** Protocol requires minimum 20 trades in OOS test stage (`min_total_trades >= 20`). The test stage produced only **9 trades** across the ~1-year OOS period (less than 1 trade per month across 10 symbols).
2. **Outcome:** In accordance with protocol EDU-EVO-06 and Batch E, strategies with < 20 OOS test trades are classified as `INSUFFICIENT_SAMPLE` and must not be subjected to parameter sweeping or tuning.
3. **Hypothesis Evaluation:** While a candidate C1 (`15567e02a806_c1_risk_sl`) was generated in research artifacts, testing is withheld due to sample insufficiency.

---

## 4. Final Disposition

- **Disposition:** `INSUFFICIENT_SAMPLE`
- **Decision:** Freeze alpha without parameter sweeping. Candidate variants archived in `nora/check/candidates/15567e02a806/`.
- Original user alpha file in `nora/edu/data/alpha/user/15567e02a806.json` is preserved 100% intact.
