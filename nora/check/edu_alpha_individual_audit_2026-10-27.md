# EDU Alpha individual audit — 2026-10-27

## Verdict

**The rollout is not accepted as “all alphas meet standard.”** This is a
read-only audit of the current inventory and the rollout artifacts. It does not
change or restore strategy data.

The frozen inventory timestamp is `2026-10-27T08:34:32.407753+00:00`. It lists
57 active user alpha records and 34 normalized-code groups. The inventory says
all 57 compile, but compilation only proves that the DSL parser builds a
program; it does not prove that the signal is meaningful, the saved run
configuration matches the code, or execution/accounting is correct.

| Audit dimension | Result |
|---|---:|
| Active user records reviewed | 57 / 57 |
| Unique normalized-code groups | 34 |
| Snapshot compile status | 57 `VALID` (not rerun in this audit) |
| Records with obviously ineffective/trivial market conditions | 27 |
| Remaining records | 30 — compile evidence only; not accepted pending execution/config evidence |
| Independently execution-verified and accepted here | 0 / 57 |
| Original active user files changed | 0 |
| Vinh source records preserved | 7 / 7 |

## Per-record results

The four repeated toy-code groups below account for 27 individual records. Each
record retains its own user ID and is listed separately; identical code does not
make the user records interchangeable.

| Alpha ID | Name | Result | Finding |
|---|---|---|---|
| `026f43441cb2` | U4_BTC_1h_Different_Window | **FAIL** | `close > 1` is effectively always true for BTC; only sets LONG and has no exit. |
| `0bf936687964` | U4_BTC_1h_Different_Window | **FAIL** | Same ineffective U4 code; no exit. |
| `64b657c8de8e` | U4_BTC_1h_Different_Window | **FAIL** | Same ineffective U4 code; no exit. |
| `74f607263c5c` | U4_BTC_1h_Different_Window | **FAIL** | Same ineffective U4 code; no exit. |
| `7c1bf0a9686a` | U4_BTC_1h_Different_Window | **FAIL** | Same ineffective U4 code; no exit. |
| `a4d6826fbbc6` | U4_BTC_1h_Different_Window | **FAIL** | Same ineffective U4 code; no exit. |
| `d0518c0cca14` | U4_BTC_1h_Different_Window | **FAIL** | Same ineffective U4 code; no exit. |
| `138df68946ad` | U1_BTC_1h_Alpha | **FAIL** | `close > 0` is always true for BTC prices; only sets LONG and has no exit. |
| `1a1a4389a821` | U1_BTC_1h_Alpha | **FAIL** | Same ineffective U1 code; no exit. |
| `2e41b2cfa24d` | U1_BTC_1h_Alpha | **FAIL** | Same ineffective U1 code; no exit. |
| `bd234070bd7b` | U1_BTC_1h_Alpha | **FAIL** | Same ineffective U1 code; no exit. |
| `be1174b24a44` | U1_BTC_1h_Alpha | **FAIL** | Same ineffective U1 code; no exit. |
| `cb0b6e0f12e7` | U1_BTC_1h_Alpha | **FAIL** | Same ineffective U1 code; no exit. |
| `1e4c0b9f84f7` | U3_BTC_Small_Alpha | **FAIL** | `close < 0` cannot occur for BTC spot/perpetual market prices; no entries. |
| `571474a18f55` | U3_BTC_Small_Alpha | **FAIL** | Same impossible U3 condition. |
| `7f770ebe5ab5` | U3_BTC_Small_Alpha | **FAIL** | Same impossible U3 condition. |
| `930294d28c45` | U3_BTC_Small_Alpha | **FAIL** | Same impossible U3 condition. |
| `9eec3d61131d` | U3_BTC_Small_Alpha | **FAIL** | Same impossible U3 condition. |
| `af2bf88426c4` | U3_BTC_Small_Alpha | **FAIL** | Same impossible U3 condition. |
| `fd16df3d0a3f` | U3_BTC_Small_Alpha | **FAIL** | Same impossible U3 condition. |
| `214ea8fdf3e6` | U2_ETH_15m_Alpha | **FAIL** | `close > 10` is effectively always true for ETH; only sets LONG and has no exit. |
| `234e6df02e37` | U2_ETH_15m_Alpha | **FAIL** | Same ineffective U2 code; no exit. |
| `616e1b8cbc88` | U2_ETH_15m_Alpha | **FAIL** | Same ineffective U2 code; no exit. |
| `856ddc574ce7` | U2_ETH_15m_Alpha | **FAIL** | Same ineffective U2 code; no exit. |
| `862e0c9eebbe` | U2_ETH_15m_Alpha | **FAIL** | Same ineffective U2 code; no exit. |
| `e9a9a5b44d03` | U2_ETH_15m_Alpha | **FAIL** | Same ineffective U2 code; no exit. |
| `ee0cf7f58f94` | U2_ETH_15m_Alpha | **FAIL** | Same ineffective U2 code; no exit. |
| `0873864b8db7` | DEMA Turbo Compound (1Y Fast Trend - x1.51 Vốn) | **NOT ACCEPTED** | Snapshot compile only; no per-alpha execution oracle or comparison of saved position overrides to code. |
| `090730ae35b8` | Fail-Fast Volatility Breakout (SL 2.4% + Macro Trend) | **NOT ACCEPTED** | Title/code say stop 2.4%; saved run config says `exit_unit=atr`, so effective stop semantics need a verified run/config decision. |
| `0d51ba8d2012` | OBV Volume Accumulation + RSI Momentum | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units and was not tested against code/result. |
| `14e3b934b1e5` | ROC Momentum Exhaustion with Take-Profit | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `15567e02a806` | Triple EMA Trend Alignment (Optimized) | **NOT ACCEPTED** | Snapshot compile only; effective risk and signal behavior not verified against its saved run config. |
| `18e87aa868ad` | Fast Dynamic Channel Breakout (18D + Macro Trend) | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no execution oracle. |
| `270e6e28416f` | EMA Trend Rider (Rising Slope - Optimized) | **NOT ACCEPTED** | Snapshot compile only; effective risk and signal behavior not verified against its saved run config. |
| `303d4b713dda` | Macro Trend Filtered Breakout (EMA 105 Filter) | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no execution oracle. |
| `33312a2f4dfc` | Standard Deviation Dynamic Channel Breakout (v2.0 Regime Filtered) | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no execution oracle. |
| `3cfcc2d296a2` | Donchian Lower Channel Exit | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no execution oracle. |
| `4f28285aa44c` | Dual EMA + ADX Trend Strength Filter | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `541c55834f56` | Daily Range Expansion (High - Low) / Close | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `5e52d3fdf71f` | Bollinger Band Overextension Exit | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `6055aa8f661e` | Triple Filter: EMA + MACD + RSI | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `6afa7f774655` | RSI Rebound with Fast SMA Filter | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `715e56a6dd33` | Linear Regression Channel Deviation | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `717c1890c59e` | Weighted Moving Average (WMA) Crossover (Optimized) | **NOT ACCEPTED** | Snapshot compile only; effective risk and signal behavior not verified against its saved run config. |
| `7f3486d63ca8` | Dual Oscillator Climax Exit | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `7f67e9aed0aa` | Stochastic & RSI Confluence System | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `89379cc0ab52` | Stochastic Oscillator (%K, %D) Bull Cross | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `8a47cdbcc942` | Fast Dip Harvester (3M DCA Dynamic - CAGR 108%) | **FAIL / BLOCKED** | Saved result has only 3 trades, no data hash or job ID; the checklist itself fails the 20-trade minimum. Code/title claim 2%/4% exits while saved config uses `exit_unit=atr`; the stored metrics do not validate the claim. |
| `b4b65cd3493f` | Commodity Channel Index (CCI) Snapback | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `b96bafe57445` | Normalized ATR (NATR) Volatility Breakout | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `bf519617d973` | Double Exponential Moving Average (DEMA - Optimized) | **NOT ACCEPTED** | Snapshot compile only; effective risk and signal behavior not verified against its saved run config. |
| `c33cc317bbeb` | Multi-Day Cumulative Return Dip Buying | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `cb750cb1eb10` | EMA Golden Cross + Volume Spike Confluence | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `efb1fbe2db86` | Volatility Expansion Channel (StdDev 1.51 + Macro Trend) | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no execution oracle. |
| `f261549d9efa` | ROC Momentum Surge | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `f4e211e9510d` | Rolling 30-Day Multi-Week High Breakout | **NOT ACCEPTED** | Snapshot compile only; saved position config uses ATR units; no signal/accounting oracle. |
| `fa9587a97fa9` | Trend Alignment Momentum (Optimized) | **NOT ACCEPTED** | Snapshot compile only; no per-alpha signal/accounting test. Its previous v2 file was overwritten by the rollout script; the frozen hash-matching copy exists in the cleanup backup. |

“NOT ACCEPTED” does not mean the strategy is necessarily unprofitable or its
signal is necessarily wrong. It means the evidence currently available does not
prove that it meets the technical/educational acceptance standard.

## Blocking findings in the claimed rollout

1. **The 27 simple records are compile-valid but not meaningful market strategies.**
   Their source consists of one constant-threshold position rule. These should be
   explicitly classified as DSL/compiler examples or rewritten only with owner
   intent; do not present them as validated alphas.
2. **The claimed 27 educational rewrites did not rewrite code.** The normalization
   script copies the original record and adds metadata/disclosures. Direct
   comparison shows all 50 generated v2 code strings are unchanged from their
   corresponding original code. The 23 “duplicate mappings” also retain a full
   copy of the duplicate code; `canonical_id` metadata alone does not make the
   executable code use a canonical implementation.
3. **One prior version was overwritten.** The inventory froze
   `fa9587a97fa9.v2.json` with SHA-256
   `73c004968c74790e3a042da899f98887e7b8f0d3f497b96c411c4dfbb1333fc4`.
   The normalization script writes `v2` without checking for an existing file.
   The current v2 differs, but the exact frozen version is present at
   `.backup/edu_cleanup_snapshot_20261027_081046/alpha_user/_versions/fa9587a97fa9.v2.json`.
   The original alpha file itself remains unchanged. This audit did not restore
   the prior version.
4. **Assessment “validity” was inferred from compile status.** The assessment
   script assigns `VALID_AS_IS` to every compiling Vinh strategy and
   `NEEDS_EDUCATIONAL_REWRITE` to other unique compiling strategies; it does not
   analyze signal quality, effective run configuration, risk units, or outcomes.
5. **The regression test does not validate normalized v2 files.** Its user-alpha
   loop compiles the original code embedded in the frozen manifest. It does not
   compare each v2 code/config with source, nor build a plan using each alpha's
   saved `config.position` and verify effective settings.
6. **Onboarding extraction is not trustworthy for Quick RSI.** The inventory
   script hard-codes an older Quick RSI string with `stop_loss_rate = 0.02`.
   That string is not present verbatim in the current component, although the
   test separately checks that the current component contains `2.0`. Thus the
   manifest's compile test is for stale example code, not the current Quick RSI
   sample.
7. **Canonical advanced breakout has a likely impossible entry condition.**
   It compares `close > rolling_max(high, 20)` without shifting the channel to
   exclude the current bar. Since current close cannot exceed current high, the
   documented breakout cannot occur as written. This template needs a verified
   prior-bar channel and a deterministic signal fixture before being taught as
   executable.
8. **Current test execution is blocked in this environment.** The focused pytest
   run could not collect tests because system Python 3.10 has no `pandas`; the
   previously used `/home/vmc03/.venvs/nora312/bin/python` no longer exists.
   Therefore the attached “23/23 PASS” is not independently reproduced here.

## What did pass / was preserved

- The frozen manifest reports `VALID` for the 57 original user-alpha code strings,
  50 education samples, 3 onboarding examples, and 3 system strategy modules.
  These are inventory-time compile results, not current rerun evidence.
- SHA-256 comparison confirmed all 57 active user-alpha source files still match
  their frozen hashes, including all 7 of Vinh's alpha files.
- The overwritten `fa9587a97fa9.v2.json` has an exact hash-matching backup copy;
  no restore was performed.

## Acceptance decision and next gates

**Do not mark EDU alpha rollout complete. Do not present the 27 toy records as
validated strategies or the stored FastDip metrics as verified performance.**

1. Protect and, with owner approval, restore the frozen prior
   `fa9587a97fa9.v2.json` from the exact-hash backup before further version writes.
2. Fix the normalization workflow to refuse existing version paths, produce a
   real reviewed diff when a rewrite is intended, and record a canonical reference
   without copying executable code as a fake deduplication.
3. For each of the 57 records, compile the current source, build the execution
   plan using its actual saved config, assert effective parameter provenance and
   units, then run deterministic signal/execution/accounting fixtures. Treat
   duplicate records individually for owner/config mapping even when sharing a
   code fixture.
4. Reclassify the 27 threshold examples as explicitly non-alpha teaching fixtures
   or obtain the owner's intended logic; do not invent replacement rules.
5. Re-extract onboarding examples from the actual frontend source; add a
   consistency test that fails if the manifest/test sample diverges from it.
6. Repair and test the advanced breakout template, then rerun the focused EDU
   suite in the configured environment with dependencies available.
7. Only then reconcile every user alpha, education sample, onboarding entry, and
   system strategy with explicit `PASS`, `FAIL`, or `BLOCKED` evidence. Profitability,
   TradingView parity, public deployment, and live-trading approval remain separate
   claims/gates.
