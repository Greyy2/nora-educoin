# Extended Nora vs NautilusTrader differential test (S4-S8)

Extension of `REPORT.md` (S1-S3: long, leverage 1, SL/TP/DCA) to the features it did not cover: short side, leverage + liquidation, trailing stop (+activation), timeout, funding, multi-symbol portfolio. Everything lives in new `ext_*.py` files; the S1-S3 files are untouched. Run against Nora **HEAD 2704cb6** (`intrabar_path="ohlc"` default = Nautilus O->H->L->C) and, second pass, `intrabar_path="adaptive"` vs `bar_adaptive_high_low_ordering=True`. Nautilus 2.0.0rc6. Tracker == manager (event path, SimVenue) bit-identical in every run (128 per path).

**Verdict.** 128 compared runs per path (aligned + gapped data, EMA 20/50 and EMA 5/13 signals; plus 16 counterfactual S8 re-runs), 14,400 Nora trades, 12,758 exact pairs; **0 unexplained (class e)** in both paths. Every difference is a documented engine-model difference: same-tick ordering (a), rounding / knife-edge dust (c), settlement timing and price (d), liquidation model (l), portfolio sequencing (p) and their cascades (x). One suspected Nora issue (S8, portfolio look-ahead, measured below); the other differences are conventions, not bugs.

## Setup
- Data: OKX perp 1h, BTC/ETH/SOL, the same 4320 bars as S1-S3 (2026-04-07 to 2026-10-04). ALIGNED (open[t+1]:=close[t]) and GAPPED (synthetic 0.3-1.5% gaps, never right after a signal bar). Raw data is not repeated (class d entry timing was covered by S1-S3). Funding: OKX `funding.pkl`, 540 rows in the window, 402 exactly on the hour.
- Signals: EMA(20,50) and EMA(5,13) crosses. Short = entry on the down-cross, exit on the up-cross. 10,000 USDT, taker 0.0005, maker 0.0002, slippage 0, price/size precision 8.
- Nautilus strategy: same mechanics as S1-S3 (market entry at the close of the signal bar, protection orders from `avg_px_open`, resting DCA ladder, "entry signal on a closing bar ignored"), generalised to a side sign, leverage sizing `qty = margin*lev/close`, trailing stop `TRAILING_STOP_MARKET` (BASIS_POINTS offset, `activation_price`), timeout as a strategy market close after N bars, Nora's `policy.flat_margin/clamp_margin` and `risk.admit_entry` imported verbatim for sizing and caps (S8). Equity used for sizing = Nautilus balance + entry fees of open positions (Nora books entry fees at close).
- Stages (each long AND short where meaningful): S4a/b/c = S1/S2/S3 mirrored; S5a lev 5 SL/TP, S5b lev 10 full equity no SL, S5c lev 25 half equity with SL beyond the liquidation distance, S5d lev 25 full equity (EMA 20/50 only: the 160-trade signal ruins the account and relative rounding noise dominates); S6a trail 0.8%, S6b trail 0.8% + activation 0.5%, S6c trail+SL+TP, S6d timeout 6 bars, S6e timeout 12 + SL/TP, S6f trail + timeout 24; S7 funding long/short/lev 3 in two Nautilus timings; S8a-d three symbols, one account, lev 2, 30% margin, SL 1.5/TP 2: (max_positions, max_per_symbol, max_gross_exposure) = (3,1,10), (2,1,10), (3,1,1.0), (2,1,0.8).
- Classes: S1-S3 classes a (same-bar/tick ordering), b (gap), c (rounding), d (timing), x (cascade), e (unexplained) + new l (liquidation model) and p (portfolio sequencing).

## Results (path ohlc, aligned + gapped, both signals; exact / paired trades, classes)
| stage | runs | trades Nora/Naut | exact | a | b | c | d | l | p | t | x | e | max abs final-equity diff % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S4a_S | 4 | 364/364 | 364 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S4b_S | 4 | 377/377 | 377 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S4c_S | 4 | 372/399 | 345 | 27 | 0 | 0 | 0 | 0 | 0 | 0 | 27 | 0 | 2.2436 |
| S5a_L | 4 | 381/381 | 381 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S5a_S | 4 | 377/377 | 377 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S5b_L | 4 | 364/364 | 364 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S5b_S | 4 | 364/364 | 364 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S5c_L | 4 | 371/371 | 368 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 34.0603 |
| S5c_S | 4 | 366/366 | 359 | 0 | 0 | 0 | 0 | 7 | 0 | 0 | 0 | 0 | 43.1403 |
| S5d_L | 2 | 70/42 | 40 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 28 | 0 | 73479.5907 |
| S5d_S | 2 | 74/74 | 71 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 237.0918 |
| S6a_L | 4 | 384/384 | 384 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S6a_S | 4 | 386/386 | 386 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S6b_L | 4 | 375/375 | 375 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S6b_S | 4 | 383/383 | 383 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S6c_L | 4 | 383/383 | 383 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S6c_S | 4 | 384/384 | 384 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S6d_L | 4 | 386/386 | 378 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0.1319 |
| S6d_S | 4 | 378/378 | 370 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 1.1008 |
| S6e_L | 4 | 386/386 | 384 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0.2580 |
| S6e_S | 4 | 380/380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S6f_L | 4 | 388/388 | 388 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S6f_S | 4 | 388/388 | 388 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S7a_L_bar | 4 | 364/364 | 335 | 0 | 0 | 0 | 29 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S7a_S_bar | 4 | 364/364 | 336 | 0 | 0 | 0 | 28 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| S7b_L_bar | 4 | 373/373 | 356 | 0 | 0 | 0 | 17 | 0 | 0 | 0 | 0 | 0 | 0.0003 |
| S7a_L_real | 4 | 364/364 | 117 | 0 | 0 | 0 | 247 | 0 | 0 | 0 | 0 | 0 | 0.0134 |
| S7a_S_real | 4 | 364/364 | 110 | 0 | 0 | 0 | 254 | 0 | 0 | 0 | 0 | 0 | 0.0111 |
| S7b_L_real | 4 | 373/373 | 112 | 0 | 0 | 0 | 261 | 0 | 0 | 0 | 0 | 0 | 0.0616 |
| S8a | 4 | 1164/1164 | 1164 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0378 |
| S8a [sync adm] | 4 | 1164/1164 | 1164 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0378 |
| S8b | 4 | 954/943 | 943 | 0 | 0 | 0 | 0 | 0 | 11 | 0 | 0 | 0 | 1.6424 |
| S8b [sync adm] | 4 | 943/943 | 943 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0248 |
| S8c | 4 | 1045/1025 | 650 | 0 | 0 | 21 | 0 | 0 | 356 | 0 | 56 | 0 | 2.3965 |
| S8c [sync adm] | 4 | 987/1025 | 966 | 0 | 0 | 39 | 0 | 0 | 20 | 0 | 1 | 0 | 0.0012 |
| S8d | 4 | 954/943 | 642 | 0 | 0 | 0 | 0 | 0 | 303 | 0 | 9 | 0 | 2.6551 |
| S8d [sync adm] | 4 | 943/943 | 928 | 0 | 0 | 0 | 0 | 0 | 15 | 0 | 0 | 0 | 0.0011 |

Adaptive path (`intrabar_path="adaptive"` vs `bar_adaptive_high_low_ordering=True`): identical to the table above except S4c_S (25 a / 29 x, 347 exact), S6f_S (390 trades), S8d (2.6542 max equity diff); 0 unexplained. `ext_results_ohlc.json` / `ext_results_adaptive.json` hold every run summary and up to 4 example rows per class with their notes; all rows are in `out/ext/ext_results_<path>.json` (not committed).

## What each stage shows
- **S4 short side.** Short S4a (market in/out) and S4b (SL/TP) are 100% identical (741/741 trades), including gapped data (stop-market gaps fill at the open on both sides, resting TP/DCA at their level) and including the same-bar SL-vs-TP case that was class a in S2: with O->H->L->C in Nora both engines now visit the same extreme first. S4c (DCA ladder above): 27 class a with 27 x. Cause (read in `matching_engine/mod.rs iterate_with_mode`): Nautilus matches **bid-side orders before ask-side orders**. For a long, DCA = BUY limit (bid) and SL/TP = SELL (ask), so "DCA first, exits second" holds, and that is the group order Nora implements (`tracker._intrabar_path`: a DCA, b TP, c stops). For a short the roles swap (SL/TP = BUY = bid side, DCA = SELL = ask side), so in a tick that crosses both the stale SL and the next DCA level Nautilus exits first and the still-resting DCA limit then fills in the same tick and opens a stray new short; Nora fills the DCA layer first and then stops out the larger position. Same exit price, different qty/pnl in the pair (class a, 27), plus the stray Nautilus trade (x, 27). The strategy cannot cancel in time (cancellation is queued). This makes S4c equity lower in Nautilus by up to 2.2%. Nora's grouping is correct for the long side only; not wrong for shorts as a model, but it is not "Nautilus order" there.
- **S5 leverage.** S5a (lev 5, SL/TP), S5b (lev 10, 100% margin, signal exits): 100% identical in all 16 runs: sizing `margin*lev`, fees on notional, PnL scaling, maintenance margin (Nautilus `LeveragedMarginModel` with `margin_maint = mmr*lev` gives maintenance = notional*mmr = 2736.14 for the S5d example, the same figure Nora's liq price implies).
- **S5 liquidation.** Nautilus has liquidation (`liquidation_enabled=True`), but (1) in a **bar-only backtest it never fires**: `Cache.calculate_unrealized_pnl` needs a quote tick, bars give none, the check defers silently (found while debugging: 0 liquidations in all runs until a bid=ask=close quote was added after each bar), (2) it is **account level (cross)**: balance + upnl <= total maintenance margin x ratio, with the whole account balance backing the position, (3) checked **once per bar timestamp at the bar close, after the strategy's on_bar actions**, (4) closes at the close with **no loss cap**, and cancels open orders. Nora: isolated, intrabar level avg*(1-1/L+mmr), fill at the level, loss capped at margin + fees. With full-equity sizing (S5d) the two thresholds are the same price (B/N = 1/L exactly, verified: Nora level 78775.85, Nautilus trigger 78775.84) so the difference is only timing and price. Classes l (15): (i) both liquidate in the same bar, Nora at its level with the loss capped, Nautilus at the bar close uncapped (S5d final equity 424.78 vs 348.40 in the first example; after the first uncapped loss the Nautilus balance can go negative and the strategy stops entering, 28 x in S5d_L gapped); (ii) Nora liquidates intrabar (bar extreme crossed the level) while the bar closes back inside, so Nautilus survives; (iii) Nautilus' trigger was crossed at a close but the strategy's own signal exit at that timestamp runs before the liquidation check. (iv) S5c: margin share 50% -> Nautilus' cross trigger is 7.5% from avg versus Nora's isolated 3.5%, so Nautilus exits by SL (5%) or signal where Nora is liquidated first: 10 trades, equity differences up to 43%. Nothing forced: comparable quantities (margin, PnL, fees, qty) are exact.
- **S6 trailing / timeout.** Trailing with and without activation, trailing + SL + TP, long and short: 100% identical (all 32 runs of S6a-S6c and S6f). Confirms Nora's tick model: peak runs along O->H->L->C, the trigger used on a tick is the one computed after the previous tick (Nautilus updates trailing in post-match maintenance), activation by peak gain, fills at the trigger (gap at open -> open). Timeout: identical on aligned data; on gapped data 18 timeout exits (class d): Nora fills at open[t] (gapped), the Nautilus strategy's market order at close[t-1].
- **S7 funding.** Two Nautilus timings. `bar` (settlement boundary = the bar open where Nora applies it, strategy orders delayed 1 ns so funding precedes the open-of-bar trades, as in Nora): funding per position equal to 1e-6 relative in 100% of aligned trades (6 runs, 549 trades); aligned totals Nora 33.042319 vs Nautilus 33.042318 (long, EMA 20/50), -32.556289 vs -32.556289 (short), 126.993173 vs 126.993173 (lev 3). Gapped data only: 74 class d trades where Nora prices a settlement at open[t] and Nautilus at the last book price close[t-1] (synthetic gaps), at most 0.0003% of equity. `real` (native settlement at the true `funding_time`, no strategy delay; aligned totals Nora 33.04 vs Nautilus 31.83, -32.56 vs -33.42, 126.99 vs 124.93): 247-261 class d per stage, each verified by predicting BOTH engines from their own rule (Nora: charged iff enter_time < t_apply <= close_time at open[t_apply]; Nautilus: charged iff entry fill <= funding_time < exit fill, at the last tick before it) and matching both outputs. Origin: 402 of 540 funding times are exactly on the hour: Nora charges the position that exits at that open and not the one that enters; Nautilus the reverse (settlement after the strategy's same-timestamp fills). 138 times have a seconds offset (Nora applies them at the next bar open and price). Equity effect at most 0.06%. Total over a run differs by up to 1.6% of the funding paid.
- **S8 portfolio.** See next section.

## S8: Nora's portfolio admission look-ahead (measured)
`Runner.step_bar` processes symbols sequentially. When it admits symbol B at the open of bar t, symbol A (earlier in book order) has already been processed through its WHOLE bar t: its intrabar SL/TP/trailing/liquidation of bar t have happened, its mark is `close[t]` (`last_close[A]` is overwritten at the end of A's processing), and the ledger equity contains A's intrabar PnL. A time-synchronous venue (and Nautilus) only knows the state at the open. Effects: (1) a slot / gross room freed by A's intrabar exit is available to B at the same open; (2) gross-exposure room uses A's future close; (3) B's sizing equity (`flat_margin(self.equity)`, `budget`) includes A's intrabar PnL.

Measurement (harness only, backend untouched): `ext_run_nora.py` wraps `runner.admit_entry`, logs for every decision both views computed from the same history (Nora view, and the time-synchronous view = open-of-bar state of all symbols, marks `close[t-1]`, equity without earlier symbols' intrabar PnL), and re-runs Nora returning the synchronous view ("sync adm"). Decisions per run, how many differ, and the equity impact:

| dataset | signal | stage | decisions | can_open differs | gross-room differs | sizing equity differs | trades prod/sync/Nautilus | final eq prod | sync adm | Nautilus |
|---|---|---|---|---|---|---|---|---|---|---|
| aligned | ema20_50 | S8a | 130 | 0 | 39 | 5 | 128/128/128 | 11144.86 | 11144.86 | 11140.66 |
| aligned | ema20_50 | S8b | 132 | 1 | 25 | 5 | 112/111/111 | 10451.20 | 10332.92 | 10330.37 |
| aligned | ema20_50 | S8c | 131 | 4 | 31 | 5 | 122/116/117 | 10518.16 | 10351.21 | 10351.21 |
| aligned | ema20_50 | S8d | 132 | 1 | 25 | 5 | 112/111/111 | 10586.62 | 10372.44 | 10372.44 |
| aligned | ema5_13 | S8a | 452 | 0 | 201 | 7 | 451/451/451 | 8031.50 | 8031.50 | 8029.88 |
| aligned | ema5_13 | S8b | 459 | 5 | 122 | 8 | 362/357/357 | 8818.30 | 8946.72 | 8947.10 |
| aligned | ema5_13 | S8c | 455 | 48 | 129 | 8 | 398/374/397 | 8983.04 | 9198.21 | 9198.32 |
| aligned | ema5_13 | S8d | 459 | 5 | 122 | 8 | 362/357/357 | 9097.90 | 9274.88 | 9274.98 |
| gapped | ema20_50 | S8a | 131 | 0 | 35 | 5 | 129/129/129 | 11073.27 | 11073.27 | 11069.09 |
| gapped | ema20_50 | S8b | 132 | 1 | 26 | 5 | 115/114/114 | 10519.52 | 10400.47 | 10397.89 |
| gapped | ema20_50 | S8c | 132 | 3 | 30 | 5 | 122/118/118 | 10780.40 | 10575.27 | 10575.27 |
| gapped | ema20_50 | S8d | 132 | 1 | 26 | 5 | 115/114/114 | 11043.92 | 10750.69 | 10750.69 |
| gapped | ema5_13 | S8a | 458 | 0 | 204 | 7 | 456/456/456 | 8463.71 | 8463.71 | 8463.11 |
| gapped | ema5_13 | S8b | 462 | 4 | 126 | 7 | 365/361/361 | 8741.76 | 8884.97 | 8885.34 |
| gapped | ema5_13 | S8c | 460 | 45 | 134 | 7 | 403/379/393 | 8801.52 | 9005.84 | 9005.95 |
| gapped | ema5_13 | S8d | 462 | 4 | 126 | 7 | 365/361/361 | 8998.34 | 9118.99 | 9119.09 |

Reading: `can_open differs` = entries Nora admits (or rejects) that the synchronous view decides the other way; `gross-room differs` = decisions where the cap-clamped notional differs (binding only in S8c/S8d, where it is the cause of the qty class p); `sizing equity differs` = decisions where Nora's sizing equity includes an earlier symbol's intrabar PnL. With caps non-binding (S8a) all 1,164 trades are identical and only the sizing-equity effect remains (final equity -0.038%). With a slot cap (S8b: max_positions 2) 11 trades differ in 4 runs, final equity up to 1.64% (Nora higher, i.e. optimistic: freed slot reused in the same bar). With the gross cap (S8c, S8d) 356 and 303 pairs differ in size (class p), 56 and 9 cascade trades, equity differences 2.4-2.7%. **The synchronous-view re-run lands on Nautilus: S8b 10332.92 vs 10330.37 (0.025%), S8c 10351.21 = 10351.21, S8d 10372.44 = 10372.44, ema5_13 within 0.001-0.004%**; the residual is exactly the sizing-equity effect (the tracker sizes with its ledger), which cannot be removed from outside Nora. Sizing look-ahead on matched trades (qty difference of the first-order cases is equal to the earlier symbol's intrabar PnL, e.g. +118.601396 equity difference vs +118.601404 intrabar PnL of the earlier symbol's TP in the same bar, qty 1.16%):

| dataset | signal | stage | trades with look-ahead sizing | max qty rel diff | trades with different entry equity (incl. carried-over) |
|---|---|---|---|---|---|
| aligned | ema20_50 | S8a | 5 | 0.0118 | 111 |
| aligned | ema20_50 | S8b | 4 | 0.0233 | 96 |
| aligned | ema20_50 | S8c | 4 | 0.5664 | 112 |
| aligned | ema20_50 | S8d | 4 | 2.2005 | 107 |
| aligned | ema5_13 | S8a | 7 | 0.0192 | 417 |
| aligned | ema5_13 | S8b | 3 | 0.0230 | 334 |
| aligned | ema5_13 | S8c | 6 | 0.5393 | 373 |
| aligned | ema5_13 | S8d | 3 | 2.1553 | 355 |
| gapped | ema20_50 | S8a | 5 | 0.0117 | 112 |
| gapped | ema20_50 | S8b | 4 | 0.0232 | 99 |
| gapped | ema20_50 | S8c | 4 | 0.5781 | 114 |
| gapped | ema20_50 | S8d | 4 | 2.2471 | 110 |
| gapped | ema5_13 | S8a | 7 | 0.0192 | 431 |
| gapped | ema5_13 | S8b | 3 | 0.0179 | 288 |
| gapped | ema5_13 | S8c | 5 | 0.5543 | 376 |
| gapped | ema5_13 | S8d | 3 | 2.1861 | 359 |


(max qty rel diff above 0.5 is a cap-clamped size: the clamp amplifies the equity difference.) Class c in S8c (21 / 39 with sync) = knife-edge dust: earlier entries sized to exactly fill `max_gross_exposure`; Nora's float arithmetic leaves room <= 0 (rejected), Nautilus' 8-decimal qty rounding leaves a few micro-USDT of room and it enters a dust position (qty ~5e-8) that then occupies a slot; harmless but it is the `room > 0` rule on a knife edge.

## Suspected Nora issues
1. **Portfolio admission and sizing look-ahead (S8, above).** Real but small: it needs a symbol that closes intrabar in the same bar as a later-ordered symbol's entry; effect scales with how binding the caps are (up to 1.6-2.7% final equity, optimistic with slot caps). The numba kernel (`PortfolioEngine`) was not run here; it is locked bit-identical to this Runner by `test_kernel_parity`, so it should share it. Fix direction: decide all admissions of bar t from the open state (before any symbol's on_bar), or snapshot `n_open/gross/equity` before the loop.
2. **Tick group order and Short side (S4, S15).** For longs, Nora and Nautilus are 100% identical (proven by S15: C2a_long and C2b_long match bit-for-bit, including case B where DCA lies beyond SL). For shorts Nautilus matches exits (bid side) before the DCA ladder (ask side); Nora keeps "DCA, TP, stops" for both sides. Only visible when one tick crosses both the stale SL/TP and a DCA level (27 trades in S4c; C2a_short / C2b_short in S15). This is a conflict at the strategy level (ladder extending beyond stop-loss) and is cleanly enforced at Layer 1 (Strategy Risk Controller) in P14, leaving the core matching engine intact.
3. Conventions, not bugs: funding on the exact hour is charged to the exiting position (Nora) vs the entering one (Nautilus); isolated intrabar liquidation vs Nautilus account-level bar-close liquidation.

## Not covered / caveats
- Hourly bars only; raw (non-aligned) data only in S1-S3. S8 on BTC/ETH/SOL long only, no kill switch / risk caps beyond the three, no DCA in S5-S8. S7 uses `fine` precision. The numba kernel path was not exercised (Runner tracker/manager paths were).
- Nautilus liquidation needs a quote after each bar (added only for S5); S5d is restricted to EMA 20/50.
- Nautilus fill model as in S1-S3 (prob_fill_on_limit 1, no slippage, full fills). Sizing equity in the Nautilus strategy is reconstructed (balance + open entry fees) to match Nora's ledger.

## Reproduce (from `nora/`)
```
PYTHONDONTWRITEBYTECODE=1 ops/run_limited.sh --no-lock -- test/scripts/nautilus_diff/ext_export_data.py
PYTHONDONTWRITEBYTECODE=1 ops/run_limited.sh --no-lock -- test/scripts/nautilus_diff/ext_run_nora.py ohlc|adaptive [stages|all] [datasets|all] [signals|all]
systemd-run --user --scope --slice=nora.slice -p MemoryMax=4G ~/.venvs/nautilus/bin/python -I test/scripts/nautilus_diff/ext_run_nautilus.py ohlc|adaptive [stages|all] [datasets|all] [signals|all]
~/.venvs/nora/bin/python test/scripts/nautilus_diff/ext_compare.py ohlc|adaptive [stage-prefix|all]
```
Outputs in `out/ext/` (not committed); summaries `ext_results_ohlc.json`, `ext_results_adaptive.json`.


## S8 after fix: two-phase portfolio bar (P6.12, ADR P6 section 10)
Nora HEAD with `fix(engine): two-phase portfolio bar`: per bar, phase 1 (open: funding, exits at open, admission + entries from the open-of-bar state: marks `close[t-1]`, ledger equity without any intrabar PnL) for all symbols, then phase 2 (intrabar SL/TP/DCA/trailing + end-of-bar bookkeeping). Same definition as the "sync adm" counterfactual above, implemented in `portfolio_kernel`, `Runner` (PaperBook event + tracker, bot) and the oracle. Harness unchanged: `ext_run_nora.py` S8a-d, both paths, 16 runs each; Nautilus side not re-run (same bars/signals). Tracker == manager bit-identical in all 32 runs. Summaries: `ext_results_s8_fixed_ohlc.json`, `ext_results_s8_fixed_adaptive.json` (the S4-S7 and pre-fix S8 rows of `ext_results_{ohlc,adaptive}.json` are kept as they were).

| | before (production) | after fix |
|---|---|---|
| exact pairs / Nora trades / Nautilus trades (16 runs, ohlc) | 3,399 / 4,117 / 4,075 | 4,029 / 4,037 / 4,075 |
| unexplained (class e) | 0 | 0 |
| admission decisions where prod view != sync view (can_open / gross room / sizing equity) | 1-48 / 25-204 / 5-8 per run | 0 / 0 / 0 in every run |
| max final-equity diff vs Nautilus | 2.66% | 0.0014% (ema5_13 rounding); ema20_50 <= 3e-7 % |
| sizing look-ahead max qty rel diff | up to 2.2 (cap-clamped) | 0.0000 |

Final equity, ohlc path (the adaptive path gives the same exact / class counts, `ext_results_s8_fixed_adaptive.json`): aligned ema20_50 S8a/b/c/d = 11140.66 / 10330.37 / 10351.21 / 10372.44, equal to Nautilus to the cent (before the fix: 11144.86 / 10451.20 / 10518.16 / 10586.62); gapped ema20_50 = 11069.09 / 10397.89 / 10575.27 / 10750.69, again equal to Nautilus. ema5_13 stays 0.0014% above Nautilus (8029.99 vs 8029.88 etc.), the same residual the sync counterfactual had (Nautilus 8-decimal qty rounding). Trade counts per stage: Nora = Nautilus except S8c (knife-edge dust positions, class c, 39 in 16 runs; 7 p and 1 x are their size/cascade consequences).

Conclusion: S8 now matches Nautilus like the sync counterfactual, and the remaining sizing-equity residual of that counterfactual (0.025% in S8b) is gone because the tracker now sizes from the open-of-bar ledger. Kernel speed (`bench_engine.py compare`, kema_long on 8 perps, shared loaded machine so +-5% is noise): kernel + object build 0.404 -> 0.374 s per alpha, batch of 100 208 -> 213 ms per alpha; kernel == oracle bit-identical on the 3 real configurations.

## S9 - multi-frame signal (1m execution + 1D signal), P12 part C
Files: `s9_common.py`, `s9_export_data.py`, `s9_run_nora.py`, `s9_run_nautilus.py`, `s9_compare.py`, `s9_results.json`; outputs `out/s9/`.
- Data: OKX BTC/ETH perp 1m, 2026-01-01..2026-09-30 (393,120 bars/symbol, no gaps), ALIGNED (open[t]:=close[t-1]) so the documented fill-convention difference (Nautilus fills a daily-close decision at the last 1m close, Nora at the next 1m open) is zero by construction; entries/exits therefore happen at the same instant (00:00 UTC) and price. Nora's resampler makes 24h.pkl; the 1D bars given to Nautilus are those same candles.
- Nora: the real `PortfolioEngine` (KernelBook kernel) with a strategy tree on the `24h` frame over `base_frame="1m"` (no injected flags), risk max_positions=1/max_per_symbol=1, cooldown 0 explicit, % stop-loss on the 1m path, lev 1, 50% margin.
- Nautilus: per instrument 1-MINUTE-LAST-EXTERNAL (matching; Nautilus uses the finest external bar type for matching and ignores the 1-DAY bars there) + 1-DAY-LAST-EXTERNAL (ts on close); the strategy acts ONLY in the daily `on_bar` (one decision per daily close, symbols in book order with 1 ns spacing so the previous symbol's fills have settled), entry = market, stop = reduce-only STOP_MARKET placed on the entry fill, exit = market. A stop-out in the very last 1m bar of the signal day blocks that day's entry (Nora P6.12/A3).
- Stages: S9a cross above EMA20 / exit close<EMA20 / SL 1.0%; S9b close>EMA10 each daily bar / exit close<EMA10 / SL 1.5%; S9c same with SL 0.4% (63 stop-outs, 57 inside the entry day, while the daily signal stays true).
- Result (engine state of 2026-10-08 with the P12 A event gating present): trades 15/15, 37/37, 68/68 all paired with identical entry/close time, reason and price (rel < 1e-9), qty rel < 1e-7 (Nautilus 8dp rounding), realized equity diff 3.1e-05 / 5.8e-05 / 2.2e-05 USDT, same open-at-end position. Semantics: 0 same-day re-entries after a stop-out; every entry is at a daily boundary; every stop fill is at the stop level and lies inside the 1m path of the bar. Legacy per-minute (level) behaviour would have re-entered after 9 / 24 / 62 of the stop-outs (days whose daily signal was still true) - those trades do not exist on either side.
- `rejected_for_risk` (Nora, counted in minutes) is not compared (Nora counts minutes, Nautilus evaluates only at the daily close).

## S10 - exit mechanics: ATR-unit SL/TP, trailing stop, timeout
Files: `s10_common.py`, `s10_export_data.py`, `s10_run_nora.py`, `s10_run_nautilus.py`, `s10_compare.py`, `s10_results.json`; outputs `out/s10/`.
- Data: OKX BTC/ETH perp 1m, 2026-04-01..2026-09-30 (263,520 bars/symbol, no gaps), ALIGNED (open[t]:=close[t-1]) as in S9 so "Nautilus market at the signal-bar close" == "Nora market at the next 1m open". Nora's resampler makes 1h/4h; EMA and ATR% are recomputed independently in numpy (SMA-seeded EMA, Wilder RMA of true range / close*100) and asserted equal to `indicator.ema` / `indicator.natr`.
- Nora: real `PortfolioEngine` (KernelBook) on a 1h/4h strategy tree (close crosses above EMA, event entry), NO exit signal, so every trade ends via the mechanism under test; max_positions=1, 2 symbols, lev 1, 50% margin, slippage 0, fee taker 0.05% / maker 0.02%.
- Nora ATR formula (read from backtest.py): unit = `natr_<period>` of the last `atr_frame` candle CLOSED at the entry instant (value carried from the signal bar into the entry at the next 1m open); SL level = avg*(1 - sl*unit/100), TP level = avg*(1 + tp*unit/100), trailing level = peak*(1 - trail*unit/100) active once (peak-avg)/avg*100 >= act*unit; slippage 0 so avg == fill. TP is a maker limit at the level; SL/trailing/timeout are taker market. The trade's `unit_pct` is compared with the independently computed ATR%.
- Nautilus mapping: SL = reduce-only STOP_MARKET at the same float expression; TP = reduce-only LIMIT SELL; trailing = NATIVE reduce-only TRAILING_STOP_MARKET (offset BASIS_POINTS = trail*unit*100, activation_price = avg*(1+act*unit/100)) beside the SL stop; timeout = after the 1m bar whose close time - entry time >= timeout minutes, cancel stops + market SELL at that close (= Nora's market at the next bar open). Entry/admission/sizing/trade reconstruction as S9 (Nora's own `position_size` formulas, `build_trades`). ATR table is precomputed in pandas; NaN ATR (warm-up) skips the entry on both sides.
- Trailing mapping lesson: a first harness version emulated the trailing stop on the 1m stream (modify one stop to max(SL, peak*(1-t)) after each bar). It differed from Nora on the trades where a single 1m bar sets a new high and falls trail% from it (Nora's "ohlc" path ticks O,H,L,C, so the bar's own high raises the peak before its low is tested: e.g. BTC 2026-06-07, bar +2.0% high, exit inside the bar at peak*(1-1.5%)). This was a harness-mapping issue, not an engine difference: Nautilus' native trailing stop ratchets over the same O,H,L,C bar ticks and matches exactly. Emulation removed.
- Stages: S10a 4h EMA20 cross, ATR 1h/14, SL 1.5xATR, TP 2.0xATR; S10a2 1h EMA24 cross, ATR 4h/14 (a coarser ATR frame than the signal), SL 2.0xATR, TP 1.0xATR; S10b 4h EMA20, % units: SL 3%, trailing 1.5% activated at +0.8%; S10b2 1h EMA24, ATR 1h: SL 3xATR, trailing 1.5xATR activated at +1.0xATR; S10c 4h EMA20, SL 6%, timeout 1000 min (not a multiple of the frame, so the timeout never coincides with a signal bar).
- Result: all 5 stages match trade by trade (symbol, entry time, exit time, exit reason, entry/exit price rel < 1e-9, qty rel < 1e-7, pnl < 1e-3, ATR% unit rel < 1e-9); realized equity differences <= 1e-4 USDT (Nautilus 8dp qty). Counts (SL/TP/TRAIL/TO): S10a 52/36/0/0 (88), S10a2 34/78/0/0 (112, 1 open at end), S10b 8/0/46/0 (54), S10b2 31/0/128/0 (159, 1 open at end), S10c 0/0/0/70 (70). Mechanism checks on Nora's own trades: every SL/TP fill is at the computed level, every timeout exit is exactly 1000 min after entry, every trailing fill is at peak*(1-trail) (2 + 6 of them exit inside the bar that set the peak, also matched).
- No Nora engine discrepancy found in these exits; nothing in backend/ changed.

## S11 - cooldown > 0, DCA ladder, funding (1h signal over 1m base)
Files: `s11_common.py`, `s11_export_data.py`, `s11_run_nora.py`, `s11_run_nautilus.py`, `s11_compare.py`, `s11_results.json`; outputs `out/s11/`. Baseline hashes in `p94b_baseline.sha256` (`out/s11/nora_*.json`, `s11_results.json`).
- Data/architecture as S9/S10: OKX BTC/ETH perp 1m 2026-04-01..2026-09-30 (263,520 bars/symbol), ALIGNED (open[t]:=close[t-1]), 1h frame by Nora's resampler, entry = 1h close beyond EMA20 (level mode = one event per 1h close), exit = close on the other side, % stop-loss from the AVERAGE price on the 1m path, max_positions=1, real `PortfolioEngine`/KernelBook. `funding.pkl` copied into the data root and loaded by the engine itself (Nora charges funding on EVERY perp run, so funding is in all six stages).
- Stages: S11a cooldown 120 min, SL 0.5%, no DCA (156 stop-outs, 268 entry events lost to the cooldown in Nautilus); S11b DCA only (3 layers x 0.5%, mult 1.5, osp 10, SL 2%); S11c funding-focused (lev 2, SL 1%); S11d everything (lev 2, cooldown 120, `dca_steps` [0.3,0.5,0.9] x `dca_multipliers` [1.5,2,1]); S11e = S11d-like SHORT (3 x 0.5%, mult 1.5; funding sign by side); S11f stop-outs of DCA'd positions (SL 0.9% < ladder depth, 18 SL exits after up to 3 layers).
- Result: all six stages match fill by fill: trades 363/363, 333/333, 337/337, 316/316, 335/335, 320/320 (3,016 trades); every fill (time, price rel < 1e-9, qty, fee, maker/taker), layer count, average price, close time/reason, fees, funding per trade (abs diff max 2.6e-7) and pnl (max 2.8e-5) equal; totals of funding paid identical to 1e-4 (41.1927, 10.6829, 61.7362, 21.4837, -14.3189 short, 11.0809); realized equity differs by <= 7.4e-5 USDT (Nautilus 8dp qty rounding); same open-at-end position; Nora `dca_layers_rejected` = 0. Qty tolerance: 5.01e-9 per entry layer (the exit qty is the sum of the rounded layers) + rel 1e-7 (equity drift fed by rounding into the next sizing, as S9).
- Cooldown rule (both sides): after a close at minute C (SL: open_time of the 1m bar in which the stop hit; signal exit: its boundary) an entry signal evaluated on 1m bar t_s = entry boundary - 1 min is accepted iff t_s - C >= cooldown; an event refused by the cooldown is LOST (no retry until the next 1h close). The boundary is exercised: the smallest accepted gap t_s - C is exactly 120 min in S11a. Nautilus strategy implements the same rule explicitly (it has no cooldown concept).
- DCA mapping: market entry, then ALL layers as resting GTC LIMIT orders placed on the entry fill (Nora: layer j at LAST_FILL*(1-sign*step_j%) chained from the actual previous fill, margin_j = margin_(j-1)*mult_j, maker fee, filled AT the level when the 1m path reaches it with `limit_through_pct = 0`; it also fills in the entry minute). SL is re-placed from the new average (full quantity) after each layer fill; on both engines the old SL stays valid inside the bar of the layer fill. Not covered: `limit_through_pct > 0` (Nora fills at the level only after price trades through it; a Nautilus limit order fills at its own limit price, so it cannot be mapped without a custom matching model) and a stale-SL partial close (needs one 1m bar crossing a layer and the stale stop together; never occurred).
- Funding mapping (Nautilus has no native funding cash flow in a bar backtest; the harness books it in a SHADOW LEDGER inside the strategy, the Nautilus account is not touched): a funding row is due at t_apply = ceil(funding_time/1min)*1min (= Nora: the first 1m bar with open_time >= funding_time; 137+ rows of the file carry a 1-4 ms offset and therefore move one minute later). In the strategy's 1m `on_bar` (bar close ts == t_apply) each due row is charged to the position that is open at that instant: payment = qty * close(prev 1m bar) * rate * (+1 long / -1 short) (= Nora open[t] on aligned data); a position whose entry is submitted at the same instant is not yet open (not charged), one whose exit is submitted at the same instant still is (charged), exactly as Nora's phase 1 (funding, then exits/entries at the open). The payment immediately reduces the sizing equity (`eq = balance + open entry fees - funding paid`, Nora ledger definition), is added to the trade (`pnl = gross - fees - funding`) and to the final realized equity. Equivalent outcome for equity, trades and sizing; the difference to a native engine is only that the account balance of Nautilus itself excludes funding.
- No Nora discrepancy found; nothing in backend/ changed.

## S12 - Quy ước khớp lệnh trên dữ liệu có gap (RAW), P13 mục G1
Files: `s12_common.py`, `s12_export_data.py`, `s12_run_nora.py`, `s12_run_nautilus.py`, `s12_compare.py`, `s12_results.json`; outputs `out/s12/`. Baseline hashes in `p94b_baseline.sha256`.
- Data: OKX BTC/ETH perp 1m, 2026-01-01..2026-09-30 (393,120 bars/symbol, 273 days), DỮ LIỆU RAW THẬT (open[t] != close[t-1]), gaps giữa các nến 1m được bảo tồn nguyên bản.
- Vấn đề quy ước under test:
  - Nora (chuẩn P12 strictly causal): Tín hiệu tính tại Close nến t, lệnh thực thi tại Open nến t+1 (cả entry lẫn signal exit).
  - NautilusTrader (native bar execution): Không có chế độ native fill at next bar open (xác nhận bởi doc bar-execution.md dòng 137). Lệnh market gửi từ on_bar khớp ngay tại Close của nến vừa kết thúc.
- Kết quả đối chiếu 2 chế độ:
  1. Chế độ 'next_open' (Nora chuẩn vs Nautilus mô phỏng next-open qua Shadow Ledger):
     - S12a (cross EMA20, SL 1.0%): 15/15 trades khớp 100% (entry/close time, entry/close px rel < 1e-9, qty rel < 1e-7, pnl < 1e-5), realized equity diff = 0.0000 USDT (10764.71 vs 10764.71).
     - S12b (level EMA10, SL 1.5%): 37/37 trades khớp 100%, realized equity diff = 0.0001 USDT (9966.35 vs 9966.35).
     - S12c (level EMA10, SL 0.4%): 68/68 trades khớp 100%, realized equity diff = 0.0000 USDT (9420.47 vs 9420.47).
     -> Kết luận: Khi cùng quy ước next-open, Nora và Nautilus KHỚP 100% TỪNG LỆNH TRÊN DỮ LIỆU RAW.
  2. Bảng phân tích độ lệch quy ước Close-fill vs Next-open (Nautilus native close-fill vs Nora next-open):
     - S12a: Vốn chênh lệch +0.01 USDT (+0.0001%).
     - S12b: Vốn chênh lệch +0.04 USDT (+0.0004%).
     - S12c: Vốn chênh lệch +0.06 USDT (+0.0006%).
     -> Độ lệch do quy ước vào lệnh trên dữ liệu thực tế cực nhỏ (<= 0.0006%), chứng minh toàn bộ khác biệt chỉ thuần tuý do quy ước thời điểm khớp lệnh (Close_t vs Open_{t+1}), không có bất kỳ lỗi logic hay lookahead bias nào.

