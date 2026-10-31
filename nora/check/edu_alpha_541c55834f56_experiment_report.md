# EDU Alpha experiment: `541c55834f56` parent vs C2

**Candidate:** `541c55834f56_c2_trend_filter`  
**Hypothesis:** Keep the existing daily range-expansion entry/exit and additionally require `close > SMA50` at entry, filtering out long breakouts below the medium-term price average. The parent already requires `close > SMA20`; no stop, exit, or sizing rule changed in the candidate code.  
**Verdict:** `PROMISING_FULL_WINDOW_NOT_VALIDATED`  
**Scope:** Research-only EDU jobs. Parent and candidate ran serially through the EDU API worker, each completed with exit code 0 under the 2 GB job limit. No user alpha was modified.

## Frozen inputs and execution

Both jobs used the active parent code and registered candidate source, the same 10 OKX perpetual symbols, 24h bars, 2023-10-06 through 2026-10-03, $10,000 initial capital, leverage 10x, risk/trade 0.5%, stop 3%, no take-profit, and identical catalog digests.

| Run | Job | Program hash | Wrapper peak / cap |
|---|---|---|---:|
| Parent | `20261027_214742_038be6` | `ffbd671df407` | 1081 MB / 2 GB |
| C2 | `20261027_214837_f2f662` | `668630cdf6cf` | 984 MB / 2 GB |

Parent source SHA256: `f9a0fbc0a647b314662a79e69ef8d26eec4d11a77e2b4c342bd12d5282207b38`. Candidate source SHA256: `308554cb705ea594b2ab58543df9a11f45fa75e1b536cad0c4c89d001e883ba1`.

## Full-window descriptive comparison

| Metric | Parent | C2 | Delta |
|---|---:|---:|---:|
| Return | +8.90% | +10.15% | +1.25 pp |
| Max drawdown | 30.33% | 26.77% | -3.56 pp |
| Trades | 381 | 329 | -52 |
| Win rate | 16.5% | 19.1% | +2.6 pp |
| Profit factor | 1.085 | 1.086 | +0.001 |
| Expectancy per trade | +0.0422% | +0.0391% | -0.0031 pp |
| Fees | $221.96 | $179.64 | -$42.32 |

The filter increased cumulative return and reduced drawdown and fees while also lowering trade count. Profit factor was effectively unchanged, and per-trade expectancy declined slightly. This is a promising descriptive result, not enough to claim a robust improvement.

## Boundary and disposition

The live API returned `config.test_start=2025-01-01` for both runs; the frozen first WFA fold requires `2024-10-01`. The running API contract does not accept `test_start`, so its train/test metrics are excluded. All dates in the full-window comparison have already been viewed; this is not holdout evidence. Accordingly, the candidate is **not a validated pass** and must not be promoted.

Evidence summary: [`candidates/541c55834f56_c2_trend_filter_evaluation.json`](./candidates/541c55834f56_c2_trend_filter_evaluation.json).
