# Mechanism discovery (phase 2) — learn each bot's decision rules from its own decision points

Phase 1 (families_*.py, run_*.py) hand-wrote rule families and grid-searched them. Result: no bot beats chance
convincingly. Phase 2 inverts it: build a supervised dataset of every moment the bot COULD have acted, label the
moments it DID act, pool across all assets the bot trades (normalised features), learn which observable state
predicts the action, then turn the learned model into the simplest rule that keeps its accuracy and simulate it.

Read-only inputs: /home/vmc03/norabt/none/okx-top10/bots.json; candles via load.candle_arrays (1m, all symbols).
Reuse: load.py (build_baskets, collapse, candle_arrays, window), match.py (basket_row, level_a, level_b), sim.py.
Do NOT modify backend/. Everything lives in test/scripts/okx_top10/. Heavy runs via
/home/vmc03/norabt/nora/backend/utils/ops/run_limited.sh.

ML libs: the nora venv has no sklearn. Create a separate research venv ~/.venvs/okxr
(numpy, pandas, scikit-learn, numba, scipy). Never pip install into ~/.venvs/nora.

## Forensic facts already established (use as feature hints, verify, do not assume)
- US equity open 13:30 UTC dominates entries for Auroraxwt (13-14 UTC = 40% of fills), Dark-Wood-Dahlia, 01pp, Sugary;
  stock perps (SPCX, SNDK, MU, AAPL, TSLA, LITE) trade almost only 13-16 UTC and ~20 UTC (US close).
  Auroraxwt basket 44 (SNDK long) closed at 13:33:31, 3.5 min after the open.
- Sugary: round entry/exit prices (limit orders), round lot sizes (10/20/50/100/200 ETH), sibling layers closed
  one-by-one seconds apart (hand). Auroraxwt: 8-decimal averaged fill prices (market/algo), siblings closed same second.
- Take-profit distance is NOT constant in %, USDT, %margin or ATR multiple (CV > 1). Winners exit 0.13% (median)
  BELOW the best price reached since the last fill (Auroraxwt, Sugary) -> exits come after a pullback from the peak:
  test trailing / giveback-from-MFE logic explicitly.
- ~50% of Auroraxwt/Sugary winning exits happen within 2 min of the first touch of the exit price; the rest lag hours.
- Adds: Auroraxwt adds as price moves against (short adds as price rises), step not constant.

## 1. Decision-point panels (disc_panels.py), per bot, pooled across symbols
All features computed ONLY from closed 1m bars at or before the decision bar (no look-ahead). Time on the 1m grid.

EXIT panel — for each basket, every 1m bar from the bar after its last fill preceding the first close, up to and
including the bar of the first close. label=1 on the bar containing the first close. (Also a variant starting
from the first fill, for adds-interleaved baskets.)
ADD panel — for each basket, every 1m bar between consecutive fills while the basket is open and before the first
close. label=1 on bars where a fill occurs (use tranches: collapse() with 15-min gap, and also raw fills).
ENTRY panel — for each symbol the bot traded and each side, every 5m bar while the bot had no open basket on
(sym, side) and the symbol had candles. label=1 on the bar of a basket's first fill. Negatives may be subsampled
(keep weights) to <= 200k rows per bot.

Features (each also in ATR units where it is a distance; ATR from 14 closed bars of 1m, 15m, 1h):
- position: uPnL% vs avg, uPnL/ATR, MFE since last fill and since first fill (% and ATR), giveback = MFE - uPnL
  (% , ATR, ratio to MFE), adverse excursion (MAE), minutes since first/last fill, n fills/tranches, last step %,
  notional vs first fill.
- price state: returns over 1/3/5/15/60/240 min (%, z by symbol), RSI(14) on 1m/5m/15m/1h, close vs EMA 9/21/50 on
  1m/5m/15m, Bollinger %b(20,2) on 5m/15m/1h, distance to rolling high/low of prior 15/60/240/1440 min, distance to
  nearest round number (price rounded at 3 and 4 significant digits), 1m volume z-score, range expansion.
- calendar: minute of day UTC, minutes since/to US open 13:30 and US close 20:00 (handle DST: both periods in data
  are EDT, so 13:30/20:00 UTC), weekday, minutes to next funding (00/08/16 UTC), is_stock_perp.
- book: number of other open baskets of the bot at that minute, same-side count, bot's realised PnL earlier that day.

## 2. Models (disc_models.py)
Time split per bot: train = first 60% of baskets by first-fill time; test = last 40% (for ENTRY panel: split by time
at the same cutoff). Small bots (< 40 baskets): leave-one-basket-out instead, report that it is LOO.
For each panel:
- HistGradientBoostingClassifier (class_weight balanced or sample weights) -> test ROC AUC, PR AUC,
  permutation importance (top 15) on test.
- Shallow DecisionTreeClassifier depth 2,3,4 (min_samples_leaf scaled) -> printed rules + test AUC.
- Monotone 1-2 feature threshold rules (best single feature, best pair) found on train -> test AUC.
- Report what fraction of the GBM's AUC lift over 0.5 the depth-3 tree / pair rule keeps.

## 3. Simulation from the learned rule (disc_sim.py)
EXIT hazard: walk each TEST basket from its real last fill (replay real fills) minute by minute; exit at the first
bar where the model score exceeds a threshold chosen on TRAIN so that the train exit-timing match (+-15 min) is
maximised; fill at that bar's close. Do it for GBM, depth-3 tree, and best pair rule.
ADD hazard: same, generate adds; full simulation = real first fill + learned adds + learned exit.
ENTRY: generate first fills per symbol from the entry model (threshold from train, cooldown while a basket is open),
Level B recall/precision +-15/60 min (match.level_b), compared against the existing random and hour-matched baselines.
Metrics: match.level_a on test (+-5/15/60 exit, add match, layer equality, PnL corr), plus the two phase-1 baselines
(null time-stop, shuffled TP drawn from train) recomputed with the same code.

## 4. Iterate until the rule stops improving
Look at the misses: for the test baskets where the sim exit is > 60 min off, print the state at the real exit vs at
the sim exit, find the feature that separates them, add it, refit. Log each iteration (what changed, why, test
metrics) into the JSON. Stop when 3 consecutive iterations improve test +-15 exit match by < 1 pt.
Per bot, also try PER-SYMBOL-CLASS models (stock perps vs crypto majors vs others) — one bot may run different logic
per asset class.

## 5. Output
out/disc_<slug>.json per bot:
{bot, n_baskets, split, panels:{exit|add|entry:{n_rows, n_pos, gbm:{auc_test, pr_auc, importance[]},
 tree3:{auc_test, rules_text}, pair:{features, thresholds, auc_test}}},
 mechanism:{exit:"<plain Vietnamese rule>", add:"…", entry:"…"},
 sim:{level_a_test:{…}, baselines:{null, shuffled_tp}, level_b_test:{…}},
 iterations:[{i, change, why, metrics}], representative:[5 baskets with real vs sim fills/exits for charts],
 cum_curve_test:{t, real, sim}, verdict:{label, why (numbers)}}
Verdict labels: "khớp tốt" (exit +-15 >= 60% and add match >= 50% and PnL corr >= 0.7, each beating p95 baseline);
"khớp một phần" (one of the three passes and CI95 lower bound beats p95 baseline); "không tái tạo được" otherwise.
Be honest: if the GBM itself has test AUC < 0.65, say the action is not predictable from price/time state.

Run order: Auroraxwt first (largest sample, 916 baskets), then Dark-Wood-Dahlia, 01pp, M Power7, Sugary, Scary,
Physical, Professor-Wang, Faithful, Firsthand. Tiny bots (Faithful 10, Firsthand 15 baskets): skip ML, write a
per-trade case table (state at entry/exit) and say the sample is too small.

## 6. Level S — free-running backtest over the SAME window must reproduce the bot's reported output (owner's main target)
The owner's acceptance test: "backtest the reconstructed strategy over exactly the bot's period and get the same
output". So, besides the conditioned Levels A/B, every bot gets a FREE-RUNNING backtest:
- Engine: walk 1m candles of every symbol the bot traded, from the bot's first trade to its last close
  (bots.json `first`/`last`), with the learned entry + add + exit rules (no real fills injected), the bot's own sizing
  (notional per fill learned from its fills: per symbol class median, and layer size ratio), its leverage per symbol
  (median), fees 5 bps taker per side, funding ignored unless the bot holds > 8h (then apply OKX funding if available,
  else flag). Max concurrent baskets = the bot's observed max.
- Output a trade list in EXACTLY the bots.json trade schema {sym, side, lev, o, c, po, pc, pnl, pr, mg, mae, add, bk}
  and compute the report metrics with the SAME code as /home/vmc03/norabt/none/okx-top10/analyze.py (copy its metric
  block into disc_stats.py as a function stats(trades) -> dict; do not re-derive the formulas): n, perDay, win, pf,
  payoff, longPct, levMed, holdMed/holdWin/holdLoss, maxLoss, maxWin, top5Share, addPct, addDownPct, stepMed,
  maxLayers, baskets, momPct, syms mix, realized.
- Compare real vs sim per metric (table real | sim | rel. error), daily realized-PnL series correlation (by close day),
  cumulative realized PnL curve real vs sim, symbol mix overlap (1 - total variation distance), and trade overlap:
  % real baskets with a sim basket same sym+side whose first fill is within +-15/+-60 min (and the converse).
- Fit order: choose rule parameters on the TRAIN window only; report Level S on the TEST window AND on the full
  window (state both clearly). Report a "stats match score" = share of the 12 core metrics within +-20% relative
  (or +-5 pp for percentages).
- Iterate (section 4) using Level S too: the reconstruction is good only if it matches BOTH the statistics and the
  timing; say which one fails and why.
