# Playbook reconstruction (phase 3): explicit, human-readable strategy per bot, estimated from the bot's own trades

Phase 1 searched rule families for exact timestamp match; phase 2 learns hazards with ML. Phase 3 writes each bot's
strategy as an explicit playbook derived from forensic statistics of its trades, estimates every parameter directly
from TRAIN-window statistics (no grid search against match scores), runs a FREE-RUNNING backtest over the bot's own
period on its own symbols, and compares the output with the real trades (DISCOVERY_SPEC.md section 6 "Level S").

## Forensic profile (measured on all baskets; re-measure on TRAIN only before using)
Side-adjusted pre-entry return = (close[i-1]/close[i-1-k]-1)*sign(side); "x%" = share of entries where it is > 0
(50% = no direction); "vol" = median |return| at entry / same at random times same symbol, same minute of day.
Exit: "loser ret/MAE" ~1.0 = losers closed at the worst point (stop-loss); ~0.1 = losers held until price came back.

| Bot | Direction at entry | Vol at entry | Exit profile (basket ret on notional) | Other |
|---|---|---|---|---|
| Auroraxwt | none (r1..r240 all 45-51%) | 2.5-3.7x | TP ~0.28% (q25 0.12 / q75 0.40, ret/ATR1h ~0.33), losers held to recovery (ret/MAE 0.10), win 93% | long and short open at the same time on one symbol (410 overlapping pairs); 32% re-entries within 5 min of a close; entries cluster 13:30-16 UTC on stock perps; notional unit ~27k/54k USDT |
| Sugary-PoH-GasCap | contrarian 15m-4h (r15 8%, r60 13%) | 1.5-2.9x | TP ~0.9%, losers partly held (0.53), win 95% | 76% short ETH; round-price limit orders; adds 0.23-0.5% |
| Scary-Merge-Llama | contrarian 1m-4h (r60 22%) | 2.2-3.4x | TP ~0.58%, SL at the extreme (1.00), win 85% | 86% long ETH/BTC |
| 01pp | contrarian 4h-1d (r240 35%, r1440 32%) | 1.7-2.3x | TP ~0.84%, loser -2.1% (0.82), hold ~15-19h | both sides, 26 symbols, peak 14 UTC |
| Physical-Epoch-Fuel | contrarian 5m-4h (r5 15%) in uptrend | 2.1-2.8x | TP ~2.5%, SL ~-3% (0.84), hold ~72h | round-price limit entries; adds average down 1-3% |
| Firsthand-ATL-Pansy | momentum 15m (r15 93%) after counter 24h | 1.5-2.0x | TP ~1.15%, SL ~-0.6% at extreme (1.06) | BTC only, 100x, 01-04 UTC |
| Dark-Wood-Dahlia | contrarian intrabar/15m (r0 28%, r15 34%) | 2.0-2.3x | TP ~2.1%, loser -0.87% (0.61), hold W 25h | 60 symbols, 13:30 UTC cluster |
| M Power7 | weak; dip vs VWAP/EMA20 | 1.6-2.0x | TP ~1.75%, SL at extreme (0.99) | stock/commodity perps |
| Professor-Wang | weak | 1.7-2.1x | TP ~1.46%, SL ~-1.42% | cross-symbol clusters around 12:15-12:40 UTC (macro releases) |
| Faithful-Punk-Fuse | contrarian 1d (r1440 30%) | ~2x | TP large (~3.5%, trail), SL ~-1.4% | long only ETH/BTC, holds winners ~10 days |

## Playbook model (one parameterised engine, per-bot parameters)
Entry, evaluated on each closed 1m bar per symbol of the bot:
- session gate: UTC minutes-of-day (15-min buckets) holding >= 80% of the bot's TRAIN first fills for that symbol class
  (stock perps / crypto majors / others); weekday mask from TRAIN.
- activity gate: |return over H_vol| >= q_vol * rolling median |return| of the same symbol (H_vol, q_vol from TRAIN).
- direction: contrarian / momentum / none on horizon H_dir, chosen as the horizon with the strongest TRAIN bias.
  "none" bots (Auroraxwt): open the side opposite to the last 1-min move OR both sides; pick by TRAIN long/short mix
  and overlap rate; also test "random side with the TRAIN long share" with 20 seeds and report the spread.
- rate calibration: thresholds set so simulated first fills per day per symbol class equal the TRAIN rate; cooldown
  after a close = TRAIN median re-entry gap; max concurrent baskets = TRAIN max.
Adds: when adverse move from the last fill >= step (TRAIN median step, in % or ATR whichever has lower CV), size ratio =
TRAIN median, max layers = TRAIN p95.
Exit: TP on average price = TRAIN median winner ret per symbol class (and a vol-scaled variant ret = c * ATR1h);
losers: if TRAIN loser ret/MAE >= 0.8 -> stop at TRAIN median loser MAE; if <= 0.6 -> no stop, exit at breakeven
after a drawdown deeper than TRAIN median loser MAE, plus a max hold = TRAIN p95 hold; in between -> both.
Sizing/leverage: TRAIN per-symbol median notional per fill and leverage. Fees 5 bps per side.

## Evaluation (Level S, same window)
Reuse disc_stats.py stats() (the analyze.py metric code) and the Level S comparison layout from run_disc.py (read
them; copy into playbook code if needed, do not edit them). For TEST and FULL windows report: the metric table real |
sim | rel. error, stats-match score (share of core metrics within +-20% rel or +-5 pp), daily realised PnL corr, cum
curve, symbol mix overlap, and EPISODE overlap: % real baskets with a sim basket same symbol (any side and same side)
opening within +-15 min, +-60 min, +-4 h, and the converse precision; random-entry baseline with the same session and
rate gates (20 seeds) for every overlap number.
Iterate: compare real vs sim per metric, explain each gap (which rule causes it), adjust the RULE (not by fitting to
test), log iterations. Write out/playbook_<slug>.json with {bot, profile (re-measured on TRAIN), params, rules_vi
(plain Vietnamese playbook: entry/add/exit/sizing), level_s:{test, full}, overlap, baselines, iterations,
sim_trades (full window, bots.json schema), verdict}. Report honestly which parts reproduce and which do not.
