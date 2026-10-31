# EDU alpha evolution — COIN engine handoff

**Checkpoint:** 2026-10-27 22:18 UTC
**Status:** `PARTIAL / NOT ACCEPTED`
**Validated profitable alphas:** **0**

## What was done

At the owner's request, validation was redirected from EDU to COIN/Nautilus. The owner then asked to stop and hand off. No additional job was started after that stop request. At handoff, the COIN API reported no active jobs.

The COIN portfolio-WFA endpoint selects registered COIN strategy IDs/configs from its library. It does not accept an EDU user-alpha DSL body. Do not silently substitute a similarly named COIN built-in strategy: that would change the strategy being evaluated.

One narrow manual fold was run through COIN's custom-backtest engine with the unchanged EDU DSL source. This is **one date-bounded custom backtest, not a completed invocation of the COIN portfolio-WFA pipeline**.

## Alpha experiments completed before the handoff

| Alpha | Research candidate(s) evaluated | Current disposition |
|---|---|---|
| `0d51ba8d2012` | C1 one-bar RSI/OBV persistence; C2 `close > SMA50` | Both `NOT_PASS`; protocol limit of two candidates consumed |
| `14e3b934b1e5` | C1 ROC-rising confirmation | `NOT_PASS` |
| `541c55834f56` | C2 `close > SMA50` | Full-window comparison looked promising on cumulative return/drawdown but lowered expectancy; unvalidated, not pass |

Historical rebaseline/sample dispositions for `18e87aa868ad` and `15567e02a806` are not completed candidate evolutions. The 23-alpha queue is not complete. **Count of validated successful/pass alphas: zero.**

## User and alpha inventory checked 2026-10-28

The current EDU filesystem has **36 user accounts** and **57 active user-alpha JSON records**, owned by 33 accounts. The baseline artifact has results for 30 records; its 27 blocked records have not been backtested. Among the 30 baseline runs: **23 OOS-negative**, **6 marginal OOS-positive**, and **1 OOS-positive with only 3 test trades**. These are baseline dispositions, not outcomes of the candidate optimization work.

| User | Active alphas | Baseline OOS disposition | Candidate evolution |
|---|---:|---|---|
| An Điềm Tĩnh | 4 | 3 OOS-negative; 1 marginal positive | 0 processed |
| Đức Động Lượng | 4 | 4 OOS-negative | `0d51ba8d2012`: 2 candidates, neither passed |
| Lan Đa Chỉ Báo | 5 | 5 OOS-negative | 0 processed |
| Mai Hồi Quy | 5 | 5 OOS-negative | `14e3b934b1e5`: 1 candidate, not pass |
| Minh Lướt Sóng | 5 | 5 OOS-negative | `541c55834f56`: 1 candidate, promising but unvalidated |
| vinh | 7 | 1 OOS-negative; 5 marginal positive; 1 positive with 3 test trades | 0 processed |
| 27 fixture/test accounts | 27 total; 1 each | 27 blocked / not run | 0 processed |
| 3 other accounts | 0 each | No active alpha | 0 processed |
| **Total** | **57** | **30 baselined; 27 blocked/not run** | **3 distinct alphas; 4 candidates; 0 validated passes** |

### Source audit of the 27 blocked fixture alphas

An AST audit of all 57 active alpha JSON records found **27 exact one-rule `SimpleAlgorithm` records**, one owned by each of the 27 fixture/test accounts below. Each has one executable statement in `__algorithm__`: `set_positions(self.data.pv_close <constant comparison>, 1)`. They define no indicator, explicit exit, or separate entry/exit logic. These are syntactically valid expressions, but not a meaningful documented strategy hypothesis; the audit does not classify them as backtest failures because their baseline disposition remains `BLOCKED / NOT RUN`.

| Fixture template | Condition | Owner handle | Alpha ID |
|---|---|---|---|
| U1 BTC 1h | `pv_close > 0` | `fx_u1_357a91` | `1a1a4389a821` |
| U1 BTC 1h | `pv_close > 0` | `fx_u1_830c88` | `cb0b6e0f12e7` |
| U1 BTC 1h | `pv_close > 0` | `fx_u1_a11ce1` | `bd234070bd7b` |
| U1 BTC 1h | `pv_close > 0` | `fx_u1_bc3223` | `2e41b2cfa24d` |
| U1 BTC 1h | `pv_close > 0` | `fx_u1_d2eb85` | `138df68946ad` |
| U1 BTC 1h | `pv_close > 0` | `fx_u1_e52418` | `be1174b24a44` |
| U2 ETH 15m | `pv_close > 10` | `fx_u2_28da0d` | `ee0cf7f58f94` |
| U2 ETH 15m | `pv_close > 10` | `fx_u2_5de8f0` | `234e6df02e37` |
| U2 ETH 15m | `pv_close > 10` | `fx_u2_90c1de` | `e9a9a5b44d03` |
| U2 ETH 15m | `pv_close > 10` | `fx_u2_97902e` | `616e1b8cbc88` |
| U2 ETH 15m | `pv_close > 10` | `fx_u2_97b4fd` | `862e0c9eebbe` |
| U2 ETH 15m | `pv_close > 10` | `fx_u2_a3b6ca` | `856ddc574ce7` |
| U2 ETH 15m | `pv_close > 10` | `fx_u2_ef5029` | `214ea8fdf3e6` |
| U3 BTC small | `pv_close < 0` | `fx_u3_029bb2` | `fd16df3d0a3f` |
| U3 BTC small | `pv_close < 0` | `fx_u3_4892b8` | `7f770ebe5ab5` |
| U3 BTC small | `pv_close < 0` | `fx_u3_539073` | `1e4c0b9f84f7` |
| U3 BTC small | `pv_close < 0` | `fx_u3_59446d` | `930294d28c45` |
| U3 BTC small | `pv_close < 0` | `fx_u3_5c2be7` | `9eec3d61131d` |
| U3 BTC small | `pv_close < 0` | `fx_u3_cc36d9` | `571474a18f55` |
| U3 BTC small | `pv_close < 0` | `fx_u3_ea9b62` | `af2bf88426c4` |
| U4 BTC 1h, different window | `pv_close > 1` | `fx_u4_027040` | `0bf936687964` |
| U4 BTC 1h, different window | `pv_close > 1` | `fx_u4_3d1d69` | `a4d6826fbbc6` |
| U4 BTC 1h, different window | `pv_close > 1` | `fx_u4_405e8c` | `64b657c8de8e` |
| U4 BTC 1h, different window | `pv_close > 1` | `fx_u4_42ac16` | `d0518c0cca14` |
| U4 BTC 1h, different window | `pv_close > 1` | `fx_u4_4390cb` | `7c1bf0a9686a` |
| U4 BTC 1h, different window | `pv_close > 1` | `fx_u4_5dc329` | `026f43441cb2` |
| U4 BTC 1h, different window | `pv_close > 1` | `fx_u4_f51e6e` | `74f607263c5c` |

The 30 records owned by the six multi-alpha users do **not** match this exact one-call pattern; their source uses `NoraStrategy` indicator/condition logic. That is only a source-shape distinction, not evidence that those 30 strategies are profitable or accepted. In the EDU DSL, `pv_close` maps to the candle `close` column (`nora/edu/backend/analys/alpha/code/compile.py` and `nora/edu/backend/analys/param/params.py`). The `< 0` rule is therefore incompatible with ordinary positive BTC prices; `> 0`, `> 1`, and `> 10` are price-threshold position rules, not indicator-based entry/exit ideas. Do not silently rewrite these user records; any cleanup requires an explicit owner-approved decision.

The owner requested separate research directions for these fixture records. The proposed 27-hypothesis plan, including per-alpha entry/exit ideas, falsifiers, dependencies and acceptance gates, is tracked in [edu_fixture_alpha_development_plan_20261028.md](./edu_fixture_alpha_development_plan_20261028.md). Those directions are new research proposals, not recovered author intent or backtest results.

Thus, of the three distinct alphas with candidate work, **two are not-pass** and **one remains unvalidated**. Do not count the latter as a win or fold it into the fail count.

## COIN exact-date fold evidence — parent only

- Job: `20261027_220350_5d8ae9`, state `done`, exit code 0.
- Engine: COIN custom-backtest, NautilusTrader 1.231.0.
- Alpha/source: parent `0d51ba8d2012`, program hash `457060fb8c85`.
- Window: 2024-10-01 through 2025-05-31; 10 OKX perpetual symbols; 24h; initial capital $10,000.
- `simulate`: return **+35.54%**, max drawdown **26.54%**, 61 trades, win rate **11.5%**, profit factor **2.117**, fees **$61.27**.
- Memory: wrapper reports **446 MB / 4 GB**; job RSS peak **700.8 MB**.
- Candidate was not run on this fold. Folds 2 and 3 were not run for either side. The positive fold-1 return is not a strategy pass.
- Accounting check: closed-trade PnL $3,355.53 + open-position unrealized PnL $199.11 = $3,554.64; equity rose $3,553.97, leaving about **-$0.67** unexplained. Reconcile before using this receipt for acceptance.

## Correct method for continuing

1. Keep the owner-selected COIN/Nautilus engine. Use the same frozen DSL code and effective position config for parent and candidate. The existing fold-1 parent job used leverage 10x, risk/trade 0.5%, stop 3%, no take-profit, 10 symbols, 24h, and the same OKX data catalog as earlier alpha experiments.
2. Resolve and document whether the owner accepts COIN custom-backtest runs on exact fold windows as the runner for EDU DSL. This is a manual fold sequence, not COIN's built-in portfolio-WFA API.
3. Before more candidate runs, reconcile the fold-1 ledger/equity residual; retain job `20261027_220350_5d8ae9`.
4. For one selected alpha/candidate at a time, run parent and candidate serially on all frozen windows:
   - 2024-10-01–2025-05-31
   - 2025-06-01–2026-01-31
   - 2026-02-01–2026-10-03

   Each window must be its own date-bounded COIN job. Wait for completion, capture job receipt, source/config hashes, catalog digest, trade ledger, open positions, equity and memory log before submitting the paired job. Do not run folds/candidates concurrently.
5. Apply the frozen admission gates only after all parent/candidate fold evidence and ledger reconciliation are complete. The periods have already been viewed; even a historical WFA-style pass is not untouched-holdout or live-trading authorization.
6. Preserve the protocol's max-two-candidates-per-alpha budget. `0d51ba8d2012` has consumed its budget; do not make further variants for it on these viewed dates. Keep outcomes as `PASS`, `NOT_PASS`, `INSUFFICIENT_SAMPLE`, or `BLOCKED` with evidence; do not iterate until positive by repeated tuning.
7. Process the next eligible alpha only after the current selected experiment has a complete disposition.

## Related evidence

- [Alpha queue and TODO](./edu_alpha_evolution_todo.md)
- [23-alpha diagnosis](./edu_alpha_fail_reason_and_evolution_report.md)
- [0d51 experiment report](./edu_alpha_0d51_experiment_report.md)
- [541c experiment report](./edu_alpha_541c55834f56_experiment_report.md)
- [0d51 C2 evidence](./candidates/0d51ba8d2012_c2_trend_filter_evaluation.json)
- [541c C2 evidence](./candidates/541c55834f56_c2_trend_filter_evaluation.json)
