# Nora vs NautilusTrader: cross-engine differential test

**Verdict.** On aligned data, S1 (signal market in/out) and S2 (+ SL/TP bracket) match NautilusTrader trade by trade: 35/35, 37/37, 147/147 trades identical for S1 and S2 ema20_50 and S1 ema5_13, 152/153 for S2 ema5_13, and final equity equal to 4+ decimals except where that one trade differs. The only S2 difference is one same-bar SL-vs-TP ambiguity (class a). S3 (DCA ladder) matches on 33/37 and 146/151 trades; every difference is class a (same bar/tick ordering), b (gap at open) or x (cascade). **Unexplained (class e): 0** in all 18 runs of the main (`fine`) configuration, in the 18 `okx`-precision runs and in the 8 adaptive-ordering runs. No Nora bug found.

## Setup
- NautilusTrader **2.0.0rc6** (v2 pre-release, Python 3.14.6, pandas 3.1.0rc0), venv `~/.venvs/nautilus`; the v1.x fallback was not needed. Nora: Python 3.11, `PositionTracker` (kernel/backtest path) **and** `PositionManager + SimVenue` (production event path): bit-identical in all 18 runs, so they count as one result.
- Data: OKX BTC perp 1h, 4320 bars, 2026-04-07 16:00 to 2026-10-04 15:00 UTC. open[t+1]==close[t] in only **51.2%** of bars (2211/4319); mean |gap| 0.007 bps, max 0.28 bps (1-3 ticks). ALIGNED set: open[t+1] := close[t] (high/low widened in 45 bars). RAW: unmodified. GAPPED (extra): the aligned series with 227 synthetic gaps of 0.3-1.5% (never right after a signal bar) so the gap rules actually get exercised, because aligned/raw data have essentially no gaps.
- Signals computed once in pandas and shared: EMA(20)x(50) (38 entries / 38 exits) and EMA(5)x(13) (163 / 162, for trade count). Long only. Perp, leverage 1, margin_pct sizing 20% of equity (S3: 10%, so the ladder fits `max_capital_usage`; otherwise Nora rejects layers and Nautilus does not model that), slippage 0, taker 0.0005, maker 0.0002, no funding / cooldown / timeout / trailing, 10,000 USDT.
- S1 market in/out. S2 SL 0.8% / TP 1.0% from avg (tight on purpose, so same-bar ambiguity and gaps occur). S3 SL 1.5%, TP 1.0%, DCA steps 0.5 / 0.7 / 1.0% with multipliers 1.5 / 1.5 / 1.5; SL/TP re-placed from the new avg after every DCA fill.
- Nautilus side: Strategy on_bar -> market order sized `equity*pct/100/close` (account balance), stop-market SL + limit TP reduce-only from `position.avg_px_open`, DCA ladder as resting limits, L1_MBP, `bar_execution`, ts_init = bar close, default fill model (prob_fill_on_limit 1, no slippage), `MakerTakerFeeModel`, risk engine bypassed. Nora's rule "an entry signal on a bar where a position closed is ignored" is replicated in the strategy.
- Two instrument configs: **fine** (price/size precision 8: rounding negligible; main result) and **okx** (tick 0.1, lot 0.0001 BTC: rounding effects).
- Matching: trades are paired by entry time. qty is compared as a notional fraction of entry equity and PnL as return on entry equity, so one divergence does not cascade through compounding. Final equity = realised equity after the last closed trade (Nautilus balance also contains the entry fee of a position still open at the end, about 1 USDT).
- Classes: a same-bar/tick ambiguity, b gap at open, c qty/price rounding, d entry timing open-vs-close (raw only), x cascade (extra trade caused by an earlier a/b divergence), e unexplained. Column c = matched trades whose qty differs only by lot rounding (every trade: at most about 5e-9 relative in `fine`).

## Results, aligned data (main), config fine

| dataset | signal | stage | trades N/A | exact | a | b | c (qty lot-rounded) | d | x | e | final eq Nora | final eq Naut | diff % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aligned | ema20_50 | S1 | 35/35 | 35 | 0 | 0 | 35 | 0 | 0 | 0 | 10441.27 | 10441.27 | +0.0000 |
| aligned | ema20_50 | S2 | 37/37 | 37 | 0 | 0 | 37 | 0 | 0 | 0 | 9966.34 | 9966.34 | +0.0000 |
| aligned | ema20_50 | S3 | 37/38 | 33 | 4 | 0 | 33 | 0 | 1 | 0 | 10298.51 | 10160.29 | -1.3421 |
| aligned | ema5_13 | S1 | 147/147 | 147 | 0 | 0 | 147 | 0 | 0 | 0 | 10158.10 | 10158.10 | -0.0000 |
| aligned | ema5_13 | S2 | 153/153 | 152 | 1 | 0 | 152 | 0 | 0 | 0 | 9800.95 | 9836.87 | +0.3665 |
| aligned | ema5_13 | S3 | 151/152 | 146 | 5 | 0 | 146 | 0 | 1 | 0 | 10026.46 | 10024.17 | -0.0228 |

## Raw data (open[t+1] != close[t]), config fine

| dataset | signal | stage | trades N/A | exact | a | b | c (qty lot-rounded) | d | x | e | final eq Nora | final eq Naut | diff % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| raw | ema20_50 | S1 | 35/35 | 14 | 0 | 0 | 14 | 21 | 0 | 0 | 10441.28 | 10441.27 | -0.0001 |
| raw | ema20_50 | S2 | 37/37 | 25 | 0 | 0 | 25 | 12 | 0 | 0 | 9966.34 | 9966.34 | +0.0000 |
| raw | ema20_50 | S3 | 37/38 | 21 | 3 | 0 | 21 | 13 | 1 | 0 | 10298.53 | 10160.29 | -1.3423 |
| raw | ema5_13 | S1 | 147/147 | 41 | 0 | 0 | 41 | 106 | 0 | 0 | 10158.09 | 10158.10 | +0.0001 |
| raw | ema5_13 | S2 | 153/153 | 63 | 1 | 0 | 63 | 89 | 0 | 0 | 9800.92 | 9836.87 | +0.3668 |
| raw | ema5_13 | S3 | 151/152 | 56 | 2 | 0 | 56 | 93 | 1 | 0 | 10026.48 | 10024.17 | -0.0230 |

Entry price differs by the open/close gap on 12-106 trades per run (class d). Everything else behaves as on aligned data; beyond the class-a effects, final equity moves by at most 0.0001% in S1/S2.

## Gapped data (synthetic gaps), config fine

| dataset | signal | stage | trades N/A | exact | a | b | c (qty lot-rounded) | d | x | e | final eq Nora | final eq Naut | diff % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gapped | ema20_50 | S1 | 35/35 | 35 | 0 | 0 | 35 | 0 | 0 | 0 | 10345.50 | 10345.50 | -0.0000 |
| gapped | ema20_50 | S2 | 38/38 | 36 | 0 | 2 | 36 | 0 | 0 | 0 | 9940.07 | 9935.69 | -0.0441 |
| gapped | ema20_50 | S3 | 38/39 | 27 | 7 | 4 | 27 | 0 | 1 | 0 | 10171.74 | 10060.23 | -1.0962 |
| gapped | ema5_13 | S1 | 147/147 | 147 | 0 | 0 | 147 | 0 | 0 | 0 | 10053.98 | 10053.98 | -0.0000 |
| gapped | ema5_13 | S2 | 153/153 | 145 | 1 | 7 | 145 | 0 | 0 | 0 | 9775.95 | 9759.45 | -0.1688 |
| gapped | ema5_13 | S3 | 151/152 | 129 | 7 | 15 | 129 | 0 | 1 | 0 | 9985.30 | 9877.75 | -1.0771 |

S2 gapped: every SL exit where the open gapped through the stop (4 + 7 trades) is identical in both engines (stop-market fills at market = open; Nora `min(level, open)`). Every TP exit where the open gapped above the TP (2 + 7 trades) differs: Nora fills at the open (`max(tp, open)`), Nautilus at the limit price (e.g. Nora 54040.4 vs Nautilus 53964.5). S3: Nora fills a DCA limit that gapped through at the open price, Nautilus at the limit price, which changes qty, avg and the TP/SL levels (class b).

## Rounding effects (config okx: tick 0.1, lot 0.0001 BTC), all datasets

| dataset | signal | stage | trades N/A | exact | a | b | c (qty lot-rounded) | d | x | e | final eq Nora | final eq Naut | diff % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aligned | ema20_50 | S1 | 35/35 | 35 | 0 | 0 | 35 | 0 | 0 | 0 | 10441.27 | 10440.92 | -0.0033 |
| aligned | ema20_50 | S2 | 37/37 | 37 | 0 | 0 | 37 | 0 | 0 | 0 | 9966.34 | 9966.30 | -0.0004 |
| aligned | ema20_50 | S3 | 37/38 | 33 | 4 | 0 | 33 | 0 | 1 | 0 | 10298.51 | 10160.22 | -1.3429 |
| aligned | ema5_13 | S1 | 147/147 | 147 | 0 | 0 | 147 | 0 | 0 | 0 | 10158.10 | 10158.99 | +0.0088 |
| aligned | ema5_13 | S2 | 153/153 | 152 | 1 | 0 | 152 | 0 | 0 | 0 | 9800.95 | 9836.64 | +0.3642 |
| aligned | ema5_13 | S3 | 151/152 | 146 | 5 | 0 | 146 | 0 | 1 | 0 | 10026.46 | 10024.20 | -0.0226 |
| raw | ema20_50 | S1 | 35/35 | 24 | 0 | 0 | 24 | 11 | 0 | 0 | 10441.28 | 10440.92 | -0.0034 |
| raw | ema20_50 | S2 | 37/37 | 25 | 0 | 0 | 25 | 12 | 0 | 0 | 9966.34 | 9966.30 | -0.0004 |
| raw | ema20_50 | S3 | 37/38 | 22 | 3 | 0 | 22 | 12 | 1 | 0 | 10298.53 | 10160.22 | -1.3430 |
| raw | ema5_13 | S1 | 147/147 | 74 | 0 | 0 | 74 | 73 | 0 | 0 | 10158.09 | 10158.99 | +0.0089 |
| raw | ema5_13 | S2 | 153/153 | 75 | 1 | 0 | 75 | 77 | 0 | 0 | 9800.92 | 9836.64 | +0.3645 |
| raw | ema5_13 | S3 | 151/152 | 74 | 2 | 0 | 74 | 75 | 1 | 0 | 10026.48 | 10024.20 | -0.0228 |
| gapped | ema20_50 | S1 | 35/35 | 35 | 0 | 0 | 35 | 0 | 0 | 0 | 10345.50 | 10345.34 | -0.0016 |
| gapped | ema20_50 | S2 | 38/38 | 36 | 0 | 2 | 36 | 0 | 0 | 0 | 9940.07 | 9935.59 | -0.0452 |
| gapped | ema20_50 | S3 | 38/39 | 27 | 7 | 4 | 27 | 0 | 1 | 0 | 10171.74 | 10060.38 | -1.0948 |
| gapped | ema5_13 | S1 | 147/147 | 147 | 0 | 0 | 147 | 0 | 0 | 0 | 10053.98 | 10054.37 | +0.0039 |
| gapped | ema5_13 | S2 | 153/153 | 146 | 1 | 6 | 146 | 0 | 0 | 0 | 9775.95 | 9759.48 | -0.1684 |
| gapped | ema5_13 | S3 | 151/152 | 131 | 7 | 13 | 131 | 0 | 1 | 0 | 9985.30 | 9877.53 | -1.0793 |

Rounding changes final equity by -0.0033% to +0.0088% in S1 and about -0.0004% in S2 ema20_50 (S2 ema5_13 differs by 0.36% only through its class-a trade). Classification is unchanged.

## Same-bar ordering: default O-H-L-C vs `bar_adaptive_high_low_ordering=True` (aligned and gapped, S2/S3, fine)

| dataset | signal | stage | trades N/A | exact | a | b | c (qty lot-rounded) | d | x | e | final eq Nora | final eq Naut | diff % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aligned | ema20_50 | S2 | 37/37 | 37 | 0 | 0 | 37 | 0 | 0 | 0 | 9966.34 | 9966.34 | +0.0000 |
| aligned | ema20_50 | S3 | 37/37 | 33 | 4 | 0 | 33 | 0 | 0 | 0 | 10298.51 | 10154.42 | -1.3992 |
| aligned | ema5_13 | S2 | 153/153 | 153 | 0 | 0 | 153 | 0 | 0 | 0 | 9800.95 | 9800.95 | -0.0000 |
| aligned | ema5_13 | S3 | 151/151 | 146 | 5 | 0 | 146 | 0 | 0 | 0 | 10026.46 | 10016.27 | -0.1016 |
| gapped | ema20_50 | S2 | 38/38 | 36 | 0 | 2 | 36 | 0 | 0 | 0 | 9940.07 | 9935.69 | -0.0441 |
| gapped | ema20_50 | S3 | 38/38 | 27 | 7 | 4 | 27 | 0 | 0 | 0 | 10171.74 | 10054.42 | -1.1534 |
| gapped | ema5_13 | S2 | 153/153 | 146 | 0 | 7 | 146 | 0 | 0 | 0 | 9775.95 | 9723.80 | -0.5334 |
| gapped | ema5_13 | S3 | 151/151 | 129 | 7 | 15 | 129 | 0 | 0 | 0 | 9985.30 | 9869.97 | -1.1550 |

With adaptive ordering (extreme nearest the open first) the single aligned S2 disagreement disappears: **S2 aligned is 100% identical (37/37 and 153/153)**. The case: 2026-09-11 13:00 (entry bar), open 77990.1, low 77220.0, high 79316.6, SL 77366.18, TP 78770.0, both reachable. Nora (adverse side first) takes SL, Nautilus default O->H->L->C takes TP; adaptive visits L first because the open is nearer the low, which is Nora's choice.

## What each class contains
- a, S2 (1 trade, ema5_13): the same-bar SL/TP case above.
- a, S3 stale SL (3 trades ema20_50, 4 trades ema5_13, aligned): a DCA layer and the previous SL level are crossed in the same L tick. Nautilus cannot re-place the SL between two fills inside one synthetic tick, so the SL computed from the pre-layer avg fires. Verified numerically: the Nautilus SL price equals avg_before_layer*(1-sl%), e.g. trade 1790773200000, SL 83364.99 hit in the same tick as the 83391.89 layer; Nora recomputes avg and SL after each layer and survives the bar. This is the one place where Nora's rule ("avg/SL re-derived after every DCA layer, same bar") is more optimistic than an exchange where the SL is replaced only after the fill event. It is a modelling assumption, not an implementation bug.
- a, S3 DCA and TP in one bar (1 trade per signal): Nora skips TP in a bar with a DCA fill (documented, `test_no_take_profit_in_same_bar_as_dca_fill`), Nautilus fills the DCA then the TP in that bar, so Nautilus exits one bar earlier (e.g. entry 1781161200000).
- b: gap rules above (TP and DCA layers fill at the open in Nora, at the limit price in Nautilus; Nora's choice is what a real exchange does for a marketable limit, Nautilus is conservative).
- c: lot/tick rounding only.
- d: raw data entry price (open[t+1] vs close[t]) and the proportional shift of exit levels derived from avg.
- x: one extra Nautilus trade per S3 run: after Nautilus exited a bar earlier (class a), it could act on an entry signal that Nora ignored because its position was still open.
- **e: none.** Debugging notes: three issues found and fixed in the Nautilus strategy (not in Nora) before the final runs, each of which first looked like a Nora difference: the bar on which an exit signal was executed also blocking the next entry, `cancel_all_orders` cancelling the resting DCA ladder, and SL orders still in SUBMITTED state not being cancelled (`is_open` vs `not is_closed`).

## Not covered / caveats
- Long side only; one instrument; leverage 1 (no liquidation, margin model not exercised); no funding, trailing, timeout or slippage; hourly bars only (Nora's 1m engine path not exercised); S3 uses a smaller first order than S1/S2.
- Real gaps in this data are at most 3 ticks, so the gap rules are exercised only by the synthetic GAPPED set.
- Nautilus fill model as specified: prob_fill_on_limit 1, prob_slippage 0, full-size fills (no queue or liquidity consumption).

## Reproduce
See `README.md`. `results_fine.json`, `results_okx.json`, `results_fine_adaptive.json` in this folder hold per-run summaries plus every non-exact trade with its class and note. Raw per-trade data lives in `out/` (not committed).
