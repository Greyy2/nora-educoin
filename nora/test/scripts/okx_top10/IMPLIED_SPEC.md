# Phase 4 — implied TP/SL fitting with real entries (owner's framing)

Owner: "Entry and exit points are all known from the trade list. TP and SL are not, so simulate assumptions to find the
closest approximation. Regime changes: just find the rule that fits the statistics of the current data."
So: IN-SAMPLE, all baskets, REAL fills (first fill AND adds replayed exactly as they happened). Only the exit rule is
hypothesised. Goal: the exit rule (TP / SL / trailing / time / break-even, with formulas for the levels) whose
simulated exits are closest to the real exits in time, price and PnL, for every bot. This is descriptive fitting;
label it as in-sample in all outputs. Parameters may change by regime: allow piecewise parameters by period (detected
change points, or per calendar week) and by symbol class, and report how much each split improves the fit.

## Step 1 — implied exit facts per basket (implied.py)
For each basket (load.build_baskets; also sub-position level when the bot closes layers separately), from 1m candles
between fills and the real close: realised exit return vs avg price at close time (side-adjusted, before fees),
MFE and MAE before exit (with timestamps), first-touch lag of the exit price after the last fill, giveback =
MFE - exit ret, hold, n layers, ATR1m/15m/1h at entry and at exit, leverage, notional, symbol class, hour, weekday.
Classify each exit (thresholds stated, sensitivity shown):
- TP-limit: exit ret > 0 and first touch of the exit level within 2 min before exit (price never exceeded it earlier).
- trailing / pullback: exit ret > 0, MFE > exit ret + 1x ATR1m, exit after a giveback from the MFE.
- SL: exit ret < 0 and exit within 2 min of the first touch of that adverse level (exit near the MAE extreme).
- break-even / scratch: |exit ret| < fee-ish band after a drawdown deeper than X.
- other (manual / time / unexplained).
Print the class mix per bot.

## Step 2 — level formulas (per class), in-sample
Fit the level as a function of observables with robust regression / quantile regression and simple forms:
TP% = a + b*ATR1h% (+ class/symbol dummies, + leverage, + n layers); also TP in ROI-on-margin terms (= price% * lev)
and in USDT; pick the form with the lowest robust CV of residuals. Same for SL distance, trailing giveback, and
break-even trigger depth. Check whether levels are measured from avg price, first fill, or last fill (choose by fit).

## Step 3 — exit simulation with real fills, parameter search (in-sample)
Engine: replay real fills; on each 1m bar after each fill apply the candidate exit rule (limit TP touched in-bar, stop
touched in-bar with stop-first convention, trailing on closed bars, time stop). Candidate rules = combinations of the
fitted formulas plus multipliers searched on a grid (e.g. TP multiplier 0.6..1.6, SL multiplier 0.6..1.6, giveback
0.5..2 x fitted, BE trigger, time cap), optionally piecewise by regime. Objective = mean of: exit time match +-15 min,
1 - median exit price error (bps scaled), PnL sign agreement, PnL correlation (USDT). Report the best rule and the
top-5 alternatives, and the gain from each element (ablation: TP only, +SL, +trail, +BE, +regime split).

## Step 4 — outputs and comparison
out/implied_<slug>.json: {bot, in_sample:true, class_mix, formulas (with coefficients and residual CV),
best_rule {text_vi (full Vietnamese diacritics), params}, ablation[], regimes {method, segments, params per segment},
metrics {exit_match_5/15/60, exit_px_err_bps_med/p90, pnl_sign_agree, pnl_corr, pnl_corr_usdt, real vs sim realised
PnL, cum curve real vs sim, report stats real vs sim (disc_stats.stats on the sim trade list with REAL entries)},
baselines {null time-stop, shuffled TP from the bot's own distribution (20 seeds)}, representative baskets (best,
median, worst match, biggest win, biggest loss: real vs sim fills/exits), sim_trades (bots.json schema)}.
Verdict wording: "tiệm cận tốt" (exit +-15 >= 60% and PnL corr >= 0.7), "tiệm cận một phần", "không tiệm cận được",
always with the numbers and the in-sample caveat.
