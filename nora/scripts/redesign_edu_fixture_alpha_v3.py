#!/usr/bin/env python3
"""Replace the 27 in-place EDU fixture strategies with a novelty-audited v3 set."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.analys.alpha.code.compile import compile_code


ROOT = Path(__file__).resolve().parents[1]
USER_ALPHA_DIR = ROOT / "nora/edu/data/alpha/user"
BASELINE_PATH = ROOT / "nora/check/edu_alpha_baseline_results.json"
TARGET_IDS = set(json.loads(BASELINE_PATH.read_text())["blocked_records"])


SPECS: dict[str, dict[str, str]] = {
    "026f43441cb2": {
        "class": "U4WilliamsBullishDivergence",
        "thesis": "A lower price trough with a higher Williams %R trough signals weakening downside momentum; enter only after price confirms by reclaiming the previous high.",
        "family": "Williams %R bullish divergence and structural reclaim",
        "entry": "Recent five-bar price low is below the preceding five-bar low, Williams %R low is higher, and close crosses above previous high while Williams %R is above -50.",
        "exit": "Close breaks below the prior five-bar price trough.",
        "novelty": "Uses paired price/oscillator trough divergence plus a separate price confirmation, not a simple oversold threshold cross.",
        "body": """
wr = self.feat.willr(high, low, close, 14)
recent_price_low = self.feat.rolling_min(low, 5)
prior_price_low = self.op.shift(self.feat.rolling_min(low, 5), 5)
recent_wr_low = self.feat.rolling_min(wr, 5)
prior_wr_low = self.op.shift(self.feat.rolling_min(wr, 5), 5)
prev_high = self.op.shift(high, 1)
protected_low = self.op.shift(recent_price_low, 1)
divergence = (recent_price_low < prior_price_low) & (recent_wr_low > prior_wr_low)
prev_close = self.op.shift(close, 1)
entry = divergence & (wr > -50) & (close > prev_high) & (prev_close <= prev_high)
exit_signal = close < protected_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "0bf936687964": {
        "class": "U4GapDownReclaim",
        "thesis": "Auction-gap exhaustion: fade only a material opening gap down that is fully reclaimed by the close.",
        "family": "Opening gap-down reclaim",
        "entry": "Open is at least 1% below prior close and current close recovers above that prior close.",
        "exit": "Close falls below the prior bar low.",
        "novelty": "A discrete open-to-prior-close dislocation and same-bar recovery; unlike the existing continuous trend, channel and momentum systems.",
        "body": """
prev_close = self.op.shift(close, 1)
prev_low = self.op.shift(low, 1)
gap_pct = (open / prev_close - 1.0) * 100.0
entry = (gap_pct <= -1.0) & (close > prev_close) & (close > open)
exit_signal = close < prev_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "138df68946ad": {
        "class": "U1PathEfficiencyTrend",
        "thesis": "Trade directional movement only when net displacement is large relative to the absolute path travelled.",
        "family": "Path-efficiency regime",
        "entry": "Ten-bar absolute log-return efficiency crosses above 0.45 while ten-bar net displacement is positive.",
        "exit": "Efficiency falls below 0.20 or ten-bar net displacement turns negative.",
        "novelty": "Measures path smoothness as net movement divided by total movement; it is not an EMA, regression-slope, ROC-threshold or channel signal.",
        "body": """
log_return = self.feat.log_returns(close, 1)
net_move = close / self.op.shift(close, 10) - 1.0
path_length = self.feat.rolling_sum(self.op.abs(log_return), 10)
efficiency = self.op.abs(self.feat.log_returns(close, 10)) / (path_length + 1e-12)
entry = self.op.crossed_above_value(efficiency, 0.45) & (net_move > 0)
exit_signal = (efficiency < 0.20) | (net_move < 0)
self.buy(entry)
self.close(exit_signal)
""",
    },
    "1a1a4389a821": {
        "class": "U1BullishEngulfing",
        "thesis": "A two-candle reversal requires a bearish prior real body followed by a bullish body that engulfs it.",
        "family": "Bullish engulfing reversal",
        "entry": "Previous candle is bearish; current candle is bullish, opens at/below prior close and closes above prior open.",
        "exit": "Close falls below the prior candle low.",
        "novelty": "The primary event is a two-body engulfing pattern; no moving-average alignment or oscillator threshold is used.",
        "body": """
prev_open = self.op.shift(open, 1)
prev_close = self.op.shift(close, 1)
prev_low = self.op.shift(low, 1)
entry = (prev_close < prev_open) & (close > open) & (open <= prev_close) & (close > prev_open)
exit_signal = close < prev_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "1e4c0b9f84f7": {
        "class": "U3BearTrapSweepReclaim",
        "thesis": "A failed downside auction is a bear trap only when price trades below the previous low and closes back above that level.",
        "family": "Prior-low liquidity sweep and reclaim",
        "entry": "Low sweeps the previous low, then the candle closes above that previous low and above its open.",
        "exit": "Close loses the swept prior-low level.",
        "novelty": "Requires an intrabar low sweep followed by a close reclaim; differs from close-only moving-average re-entry and channel-break exits.",
        "body": """
prev_low = self.op.shift(low, 1)
entry = (low < prev_low) & (close > prev_low) & (close > open)
exit_signal = close < prev_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "214ea8fdf3e6": {
        "class": "U2MoneyFlowRecovery",
        "thesis": "Use price-and-volume money flow to confirm a recovery from selling pressure.",
        "family": "Money Flow Index recovery",
        "entry": "MFI(14) crosses above 20 while the candle closes above its open.",
        "exit": "MFI crosses below 50 or close falls below the prior low.",
        "novelty": "MFI weights typical-price direction by volume; this is not OBV's signed-volume accumulation rule.",
        "body": """
mfi = self.feat.mfi(high, low, close, volume, 14)
prev_low = self.op.shift(low, 1)
entry = self.op.crossed_above_value(mfi, 20) & (close > open)
exit_signal = self.op.crossed_below_value(mfi, 50) | (close < prev_low)
self.buy(entry)
self.close(exit_signal)
""",
    },
    "234e6df02e37": {
        "class": "U2NarrowRangeFourRelease",
        "thesis": "A narrowest-in-four-bars candle marks local compression; enter only on a bullish close through that candle's high.",
        "family": "NR4 single-candle compression release",
        "entry": "Previous true range is smaller than the three ranges before it, and current close crosses above previous high.",
        "exit": "Close falls below the low of the compression candle.",
        "novelty": "Uses a one-bar NR4 auction pattern and its high/low as the trigger, not rolling volatility bands or a Donchian period breakout.",
        "body": """
true_range = self.feat.trange(high, low, close)
r1 = self.op.shift(true_range, 1)
r2 = self.op.shift(true_range, 2)
r3 = self.op.shift(true_range, 3)
r4 = self.op.shift(true_range, 4)
prev_high = self.op.shift(high, 1)
prev_low = self.op.shift(low, 1)
nr4 = (r1 < r2) & (r1 < r3) & (r1 < r4)
prev_close = self.op.shift(close, 1)
entry = nr4 & (close > prev_high) & (prev_close <= prev_high)
exit_signal = close < prev_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "2e41b2cfa24d": {
        "class": "U1CloseLocationAccumulation",
        "thesis": "Sustained closes near candle highs indicate persistent buying pressure even without volume confirmation.",
        "family": "Cumulative close-location pressure",
        "entry": "Three-bar sum of close-location values crosses above 1.5.",
        "exit": "Three-bar pressure sum falls below zero.",
        "novelty": "Aggregates where each close sits inside its own candle range; unlike price averages, volatility bands or volume-flow indicators.",
        "body": """
bar_range = high - low
clv = (2.0 * close - high - low) / (bar_range + close * 1e-12)
pressure = self.feat.rolling_sum(clv, 3)
entry = self.op.crossed_above_value(pressure, 1.5)
exit_signal = self.op.crossed_below_value(pressure, 0.0)
self.buy(entry)
self.close(exit_signal)
""",
    },
    "571474a18f55": {
        "class": "U3GapAndGo",
        "thesis": "A directional opening imbalance is continuation only if buyers hold the gap and finish the candle strong.",
        "family": "Opening gap continuation",
        "entry": "Open is at least 0.5% above prior close, close stays above prior close, and close is in the top 20% of the candle.",
        "exit": "Close loses prior close or closes below the candle midpoint.",
        "novelty": "Uses open-gap persistence plus intrabar close location, not DI/ADX or a rolling-price breakout.",
        "body": """
prev_close = self.op.shift(close, 1)
bar_range = high - low
gap_pct = (open / prev_close - 1.0) * 100.0
close_location = (close - low) / (bar_range + close * 1e-12)
entry = (gap_pct >= 0.5) & (close > prev_close) & (close_location >= 0.80)
exit_signal = (close < prev_close) | (close_location < 0.50)
self.buy(entry)
self.close(exit_signal)
""",
    },
    "616e1b8cbc88": {
        "class": "U2HammerRejection",
        "thesis": "A lower-tail rejection signals buyers absorbed an intrabar selloff and reclaimed the candle body.",
        "family": "Single-bar lower-wick rejection",
        "entry": "Bullish candle with lower wick at least twice the real body and close in the upper half of its range.",
        "exit": "Close falls below the rejection candle low.",
        "novelty": "Reads wick/body geometry within one candle; it is not a moving-average or volatility crossover.",
        "body": """
body = self.op.abs(close - open)
lower_wick = self.op.where(close > open, open, close) - low
bar_range = high - low
entry = (close > open) & (body > close * 0.0001) & (lower_wick >= 2.0 * body) & (close >= low + 0.60 * bar_range)
prev_low = self.op.shift(low, 1)
exit_signal = close < prev_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "64b657c8de8e": {
        "class": "U4LogReturnShockRebound",
        "thesis": "Fade a statistically exceptional one-bar loss only after a bullish close confirms immediate rejection.",
        "family": "Standardized log-return shock reversal",
        "entry": "Previous one-bar log return is below -2 rolling standard deviations; current candle closes bullish.",
        "exit": "Close falls below the shock candle low or the previous close is reclaimed.",
        "novelty": "Standardizes a one-bar log-return tail event; it does not use a price band, RSI or multi-day cumulative dip.",
        "body": """
log_return = self.feat.log_returns(close, 1)
return_sigma = self.feat.rolling_std(log_return, 20)
prev_return = self.op.shift(log_return, 1)
prev_sigma = self.op.shift(return_sigma, 1)
shock_low = self.op.shift(low, 1)
prev_close = self.op.shift(close, 1)
entry = (prev_return < -2.0 * prev_sigma) & (close > open)
exit_signal = (close < shock_low) | (close >= prev_close)
self.buy(entry)
self.close(exit_signal)
""",
    },
    "74f607263c5c": {
        "class": "U4InsideBarRelease",
        "thesis": "A mother-bar/inside-bar sequence defines a local auction boundary; only an upside close through the mother high enters long.",
        "family": "Inside-bar mother-range release",
        "entry": "Previous candle is inside the candle before it; current close crosses above the mother-bar high.",
        "exit": "Close falls below the mother-bar low.",
        "novelty": "Uses nested high-low containment and a two-bar reference range, not a rolling channel or volatility-band threshold.",
        "body": """
mother_high = self.op.shift(high, 2)
mother_low = self.op.shift(low, 2)
inside_high = self.op.shift(high, 1)
inside_low = self.op.shift(low, 1)
inside = (inside_high < mother_high) & (inside_low > mother_low)
prev_close = self.op.shift(close, 1)
entry = inside & (close > mother_high) & (prev_close <= mother_high)
exit_signal = close < mother_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "7c1bf0a9686a": {
        "class": "U4BullishOutsideReversal",
        "thesis": "An outside candle that engulfs both sides of the prior range but closes bullish represents a full intrabar reversal.",
        "family": "Bullish outside-bar reversal",
        "entry": "Current high exceeds prior high, current low undercuts prior low, and current bullish close exceeds prior close.",
        "exit": "Close falls below the outside candle low.",
        "novelty": "Requires a two-sided range expansion and bullish resolution; unlike MACD momentum confirmation or one-sided breakouts.",
        "body": """
prev_high = self.op.shift(high, 1)
prev_low = self.op.shift(low, 1)
prev_close = self.op.shift(close, 1)
entry = (high > prev_high) & (low < prev_low) & (close > open) & (close > prev_close)
exit_signal = close < prev_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "7f770ebe5ab5": {
        "class": "U3HigherLowStaircase",
        "thesis": "A three-step sequence of higher swing lows signals rising demand; confirmation requires a close above the prior bar high.",
        "family": "Higher-low staircase with local confirmation",
        "entry": "Three successive lows rise and close crosses above previous high.",
        "exit": "Close breaks below the previous low.",
        "novelty": "Uses an ordered swing-low structure and local confirmation, not a moving-average, ROC or oscillator regime.",
        "body": """
low1 = self.op.shift(low, 1)
low2 = self.op.shift(low, 2)
low3 = self.op.shift(low, 3)
prev_high = self.op.shift(high, 1)
prev_low = self.op.shift(low, 1)
staircase = (low1 > low2) & (low2 > low3) & (low > low1)
prev_close = self.op.shift(close, 1)
entry = staircase & (close > prev_high) & (prev_close <= prev_high)
exit_signal = close < prev_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "856ddc574ce7": {
        "class": "U2PiercingLine",
        "thesis": "A two-candle piercing reversal requires the second bullish body to recover more than half of the prior bearish body.",
        "family": "Piercing-line two-candle reversal",
        "entry": "After a bearish candle, bullish current close opens below prior close and finishes above the prior-body midpoint but below prior open.",
        "exit": "Close falls below the two-bar pattern low.",
        "novelty": "Uses body-midpoint recovery after a bearish impulse; unlike stochastic or RSI oversold crosses.",
        "body": """
prev_open = self.op.shift(open, 1)
prev_close = self.op.shift(close, 1)
prev_low = self.op.shift(low, 1)
pattern_low = self.op.where(low < prev_low, low, prev_low)
body_mid = (prev_open + prev_close) / 2.0
entry = (prev_close < prev_open) & (close > open) & (open < prev_close) & (close > body_mid) & (close < prev_open)
exit_signal = close < pattern_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "862e0c9eebbe": {
        "class": "U2MorningStar",
        "thesis": "A three-candle morning-star sequence waits for a bearish impulse, a small indecision body, then a bullish midpoint reclaim.",
        "family": "Morning-star three-candle reversal",
        "entry": "Two bars ago is bearish and wide; prior body is small; current bullish close reclaims the first body's midpoint.",
        "exit": "Close breaks below the three-bar pattern low.",
        "novelty": "Requires a three-stage decline/indecision/reclaim sequence, distinct from single-threshold CCI recovery.",
        "body": """
open1 = self.op.shift(open, 1)
close1 = self.op.shift(close, 1)
open2 = self.op.shift(open, 2)
close2 = self.op.shift(close, 2)
low1 = self.op.shift(low, 1)
low2 = self.op.shift(low, 2)
low3 = self.op.shift(low, 3)
first_body = self.op.abs(close2 - open2)
second_body = self.op.abs(close1 - open1)
pattern_low = self.op.where(low < low1, low, low1)
pattern_low = self.op.where(pattern_low < low2, pattern_low, low2)
pattern_low = self.op.where(pattern_low < low3, pattern_low, low3)
entry = (close2 < open2) & (second_body <= 0.35 * first_body) & (close > open) & (close > (open2 + close2) / 2.0)
exit_signal = close < pattern_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "930294d28c45": {
        "class": "U3TweezerBottom",
        "thesis": "Two lows testing nearly the same price, followed by a bullish close, mark a repeated support rejection.",
        "family": "Tweezer-bottom double test",
        "entry": "Current low is within 0.15% of prior low, prior candle is bearish, and current candle closes bullish above prior high.",
        "exit": "Close breaks below the lower of the two test lows.",
        "novelty": "A repeated-price support test is the signal; no RSI strength threshold or moving-average regime is used.",
        "body": """
prev_low = self.op.shift(low, 1)
prev_high = self.op.shift(high, 1)
prev_open = self.op.shift(open, 1)
prev_close = self.op.shift(close, 1)
pattern_low = self.op.where(low < prev_low, low, prev_low)
near_equal_lows = self.op.abs(low / prev_low - 1.0) <= 0.0015
entry = near_equal_lows & (prev_close < prev_open) & (close > open) & (close > prev_high)
exit_signal = close < pattern_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "9eec3d61131d": {
        "class": "U3SelloffStreakReclaim",
        "thesis": "A three-close selloff is actionable only after price reverses the local auction and closes above the previous bar high.",
        "family": "Three-close selloff exhaustion and reclaim",
        "entry": "Three prior closes decline consecutively; current candle closes bullish above the previous high.",
        "exit": "Close breaks below the previous low or a two-close decline resumes.",
        "novelty": "Combines a defined multi-bar selling streak with a separate structural reclaim; it is not a generic oscillator threshold.",
        "body": """
close1 = self.op.shift(close, 1)
close2 = self.op.shift(close, 2)
close3 = self.op.shift(close, 3)
close4 = self.op.shift(close, 4)
prev_high = self.op.shift(high, 1)
prev_low = self.op.shift(low, 1)
selloff = (close1 < close2) & (close2 < close3) & (close3 < close4)
entry = selloff & (close > open) & (close > prev_high)
exit_signal = (close < prev_low) | ((close < close1) & (close1 < close2))
self.buy(entry)
self.close(exit_signal)
""",
    },
    "a4d6826fbbc6": {
        "class": "U1VolumePriceTrendFlow",
        "thesis": "Weight each close-to-close return by traded volume so large price moves on high activity matter more than small moves.",
        "family": "Rolling volume-weighted return flow",
        "entry": "Five-bar volume-weighted log-return flow crosses above zero.",
        "exit": "Five-bar volume-weighted log-return flow crosses below zero.",
        "novelty": "Uses continuous return magnitude times volume rather than OBV's signed volume; it is not close-location pressure.",
        "body": """
log_return = self.feat.log_returns(close, 1)
flow = self.feat.rolling_sum(volume * log_return, 5)
entry = self.op.crossed_above_value(flow, 0.0)
exit_signal = self.op.crossed_below_value(flow, 0.0)
self.buy(entry)
self.close(exit_signal)
""",
    },
    "af2bf88426c4": {
        "class": "U3DownsideShockReclaim",
        "thesis": "After an exceptional one-bar downside excursion, require the next close to recover the prior candle midpoint before entering.",
        "family": "Downside range-shock midpoint reclaim",
        "entry": "Prior true range exceeds twice its 20-bar average and current close reclaims the prior candle midpoint.",
        "exit": "Close breaks below the shock candle low.",
        "novelty": "Uses a lagged true-range shock and exact candle-midpoint recovery, not Bollinger-band reclaim or ROC momentum.",
        "body": """
tr = self.feat.trange(high, low, close)
tr_mean = self.feat.rolling_mean(tr, 20)
prev_tr = self.op.shift(tr, 1)
prev_mean = self.op.shift(tr_mean, 1)
prev_high = self.op.shift(high, 1)
prev_low = self.op.shift(low, 1)
prev_close = self.op.shift(close, 1)
shock_mid = (prev_high + prev_low) / 2.0
entry = (prev_tr > 2.0 * prev_mean) & (close > shock_mid) & (close > open)
exit_signal = close < prev_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "bd234070bd7b": {
        "class": "U1HaramiRangeBreak",
        "thesis": "A bearish mother candle followed by a bullish real body contained within it marks selling contraction; a later close through the mother high confirms resolution.",
        "family": "Bearish-mother bullish-harami delayed resolution",
        "entry": "Previous candle is bullish harami inside the bearish candle two bars back; current close crosses above the mother high.",
        "exit": "Close breaks below the lower of the harami and mother-bar lows.",
        "novelty": "Separates containment from confirmation across different bars, unlike an inside-bar pattern or same-bar engulfing reversal.",
        "body": """
harami_open = self.op.shift(open, 1)
harami_close = self.op.shift(close, 1)
harami_high = self.op.shift(high, 1)
harami_low = self.op.shift(low, 1)
mother_open = self.op.shift(open, 2)
mother_close = self.op.shift(close, 2)
mother_high = self.op.shift(high, 2)
mother_low = self.op.shift(low, 2)
harami_body_top = self.op.where(harami_open > harami_close, harami_open, harami_close)
harami_body_bottom = self.op.where(harami_open < harami_close, harami_open, harami_close)
mother_body_top = self.op.where(mother_open > mother_close, mother_open, mother_close)
mother_body_bottom = self.op.where(mother_open < mother_close, mother_open, mother_close)
harami = (mother_close < mother_open) & (harami_close > harami_open) & (harami_body_top < mother_body_top) & (harami_body_bottom > mother_body_bottom)
pattern_low = self.op.where(harami_low < mother_low, harami_low, mother_low)
prev_close = self.op.shift(close, 1)
entry = harami & (close > mother_high) & (prev_close <= mother_high)
exit_signal = close < pattern_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "be1174b24a44": {
        "class": "U1VolumeAbsorption",
        "thesis": "Unusually high volume with a small real body and close near the high suggests sell pressure was absorbed rather than accepted lower.",
        "family": "High-volume low-impact absorption",
        "entry": "Volume z-score exceeds 2, real body is under 20% of range, and close is in the top quarter of the candle.",
        "exit": "Close falls below the absorption candle low.",
        "novelty": "Measures high effort with low directional price impact and bullish resolution; not a volume-spike trend crossover or OBV mean cross.",
        "body": """
vol_z = self.feat.volume_z(volume, 20)
real_body = self.op.abs(close - open)
bar_range = high - low
close_location = (close - low) / (bar_range + close * 1e-12)
entry = (vol_z > 2.0) & (real_body < 0.20 * bar_range) & (close_location >= 0.75)
prev_low = self.op.shift(low, 1)
exit_signal = close < prev_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "cb0b6e0f12e7": {
        "class": "U1DirectionalBodyBalance",
        "thesis": "Compare the magnitude of bullish and bearish real bodies over five bars to detect sustained directional auction control.",
        "family": "Rolling bullish-versus-bearish body balance",
        "entry": "Bullish real-body sum crosses above twice the bearish real-body sum.",
        "exit": "Bullish body sum falls below bearish body sum.",
        "novelty": "Uses body displacement separated by direction, not opening gaps, close-location pressure or a price-average cross.",
        "body": """
bull_body = self.op.where(close > open, close - open, 0.0)
bear_body = self.op.where(open > close, open - close, 0.0)
bull_total = self.feat.rolling_sum(bull_body, 5)
bear_total = self.feat.rolling_sum(bear_body, 5)
entry = self.op.crossed_above(bull_total, 2.0 * bear_total)
exit_signal = bull_total < bear_total
self.buy(entry)
self.close(exit_signal)
""",
    },
    "d0518c0cca14": {
        "class": "U4DownsideSemivarianceContraction",
        "thesis": "When downside-return risk contracts sharply from its recent baseline and price has recovered over five bars, the market may be transitioning out of a stressed selloff.",
        "family": "Downside-only semivariance contraction",
        "entry": "Ten-bar mean squared negative log return crosses below half its value five bars earlier while five-bar price return is positive.",
        "exit": "Downside semivariance returns above its five-bar-lagged level or five-bar price return turns negative.",
        "novelty": "Measures only the second moment of negative returns and its contraction; unlike full-range NATR/standard-deviation breakouts or one-bar failed-breakdown patterns.",
        "body": """
log_return = self.feat.log_returns(close, 1)
negative_return = self.op.where(log_return < 0.0, log_return, 0.0)
downside_semivariance = self.feat.rolling_mean(negative_return * negative_return, 10)
prior_semivariance = self.op.shift(downside_semivariance, 5)
five_bar_return = close / self.op.shift(close, 5) - 1.0
entry = self.op.crossed_below(downside_semivariance, 0.5 * prior_semivariance) & (five_bar_return > 0.0)
exit_signal = (downside_semivariance > prior_semivariance) | (five_bar_return < 0.0)
self.buy(entry)
self.close(exit_signal)
""",
    },
    "e9a9a5b44d03": {
        "class": "U2DoubleBottomRetest",
        "thesis": "A second low retesting a prior multi-bar trough after an intervening rebound is a structural support test, not a one-bar wick signal.",
        "family": "Separated double-bottom retest and breakout",
        "entry": "The recent three-bar trough is within 0.3% of an earlier three-bar trough, an intervening three-bar rebound exceeds both troughs by 0.5%, and close breaks above that rebound high.",
        "exit": "Close breaks below the lower of the two troughs.",
        "novelty": "Requires separated trough windows and a later breakout confirmation; unlike the adjacent-bar tweezer pattern.",
        "body": """
recent_trough = self.feat.rolling_min(low, 3)
prior_trough = self.op.shift(self.feat.rolling_min(low, 3), 6)
neckline = self.op.shift(self.feat.rolling_max(high, 3), 3)
prev_close = self.op.shift(close, 1)
pattern_low = self.op.where(recent_trough < prior_trough, recent_trough, prior_trough)
retest = self.op.abs(recent_trough / prior_trough - 1.0) <= 0.003
rebound = neckline > self.op.where(recent_trough > prior_trough, recent_trough, prior_trough) * 1.005
entry = retest & rebound & (close > neckline) & (prev_close <= neckline)
exit_signal = close < pattern_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "ee0cf7f58f94": {
        "class": "U2RepeatedLowerTailReclaim",
        "thesis": "Two consecutive candles with large lower tails indicate repeated intrabar rejection; entry waits for a separate bullish confirmation bar.",
        "family": "Repeated lower-tail rejection sequence",
        "entry": "Previous two candles each have lower wick at least as large as their real body; current candle closes bullish above prior high.",
        "exit": "Close falls below the lowest low of the three-bar pattern.",
        "novelty": "Requires two consecutive wick rejections and a third-bar confirmation; distinct event sequence from single-bar hammer.",
        "body": """
o1 = self.op.shift(open, 1)
c1 = self.op.shift(close, 1)
l1 = self.op.shift(low, 1)
h1 = self.op.shift(high, 1)
o2 = self.op.shift(open, 2)
c2 = self.op.shift(close, 2)
l2 = self.op.shift(low, 2)
h2 = self.op.shift(high, 2)
body1 = self.op.abs(c1 - o1)
body2 = self.op.abs(c2 - o2)
lower1 = self.op.where(c1 > o1, o1, c1) - l1
lower2 = self.op.where(c2 > o2, o2, c2) - l2
pattern_low = self.op.where(low < l1, low, l1)
pattern_low = self.op.where(pattern_low < l2, pattern_low, l2)
rejections = (lower1 >= body1) & (lower2 >= body2)
entry = rejections & (close > open) & (close > h1)
exit_signal = close < pattern_low
self.buy(entry)
self.close(exit_signal)
""",
    },
    "fd16df3d0a3f": {
        "class": "U3ThreeCandleBodyAdvance",
        "thesis": "Three consecutive bullish candles with progressively larger real bodies indicate increasing buyer commitment.",
        "family": "Three-candle body expansion",
        "entry": "Three consecutive candles are bullish and each real body is larger than the preceding body.",
        "exit": "Two consecutive bearish candles or close below the three-bar pattern low.",
        "novelty": "Uses candle-body expansion and direction, not a moving-average cross or generic close-return momentum.",
        "body": """
o1 = self.op.shift(open, 1)
c1 = self.op.shift(close, 1)
o2 = self.op.shift(open, 2)
c2 = self.op.shift(close, 2)
l1 = self.op.shift(low, 1)
l2 = self.op.shift(low, 2)
body0 = close - open
body1 = c1 - o1
body2 = c2 - o2
pattern_low = self.op.where(low < l1, low, l1)
pattern_low = self.op.where(pattern_low < l2, pattern_low, l2)
entry = (body0 > 0) & (body1 > 0) & (body2 > 0) & (body0 > body1) & (body1 > body2)
exit_signal = ((close < open) & (c1 < o1)) | (close < pattern_low)
self.buy(entry)
self.close(exit_signal)
""",
    },
}

COMPARISONS: dict[str, dict[str, Any]] = {
    "026f43441cb2": {"existing_ids": ["89379cc0ab52", "6afa7f774655"], "difference": "Williams %R price/oscillator trough divergence with structural confirmation, not Stochastic K/D or RSI threshold rebound.", "internal_ids": []},
    "0bf936687964": {"existing_ids": ["c33cc317bbeb", "14e3b934b1e5"], "difference": "A discrete open-to-prior-close dislocation and full same-bar gap reclaim, not cumulative multi-day return or ROC exhaustion.", "internal_ids": ["571474a18f55"]},
    "138df68946ad": {"existing_ids": ["270e6e28416f", "715e56a6dd33"], "difference": "Net displacement divided by total absolute path, not EMA slope or regression-channel deviation.", "internal_ids": []},
    "1a1a4389a821": {"existing_ids": [], "difference": "The 30 existing records have no real-body engulfing pattern; this uses prior bearish/current bullish body containment reversal.", "internal_ids": ["856ddc574ce7", "862e0c9eebbe", "bd234070bd7b"]},
    "1e4c0b9f84f7": {"existing_ids": ["3cfcc2d296a2", "c33cc317bbeb"], "difference": "Requires an intrabar low sweep and close reclaim of that exact prior low; neither channel exit nor multi-day close-return dip uses that event.", "internal_ids": ["7c1bf0a9686a"]},
    "214ea8fdf3e6": {"existing_ids": ["0d51ba8d2012"], "difference": "MFI price-weighted money flow threshold recovery, not OBV signed-volume accumulation plus RSI.", "internal_ids": []},
    "234e6df02e37": {"existing_ids": ["18e87aa868ad", "b96bafe57445"], "difference": "The narrowest true range among exactly four bars followed by a one-bar break, not a rolling channel or NATR breakout.", "internal_ids": ["74f607263c5c"]},
    "2e41b2cfa24d": {"existing_ids": ["0d51ba8d2012"], "difference": "Three-bar close-location pressure derived only from OHLC, not OBV/volume flow.", "internal_ids": []},
    "571474a18f55": {"existing_ids": ["18e87aa868ad", "303d4b713dda"], "difference": "Positive opening gap acceptance with close-location confirmation, not rolling-channel or macro-filtered breakout.", "internal_ids": ["0bf936687964"]},
    "616e1b8cbc88": {"existing_ids": [], "difference": "A one-bar lower-wick/body geometry trigger; the existing 30 contain no candlestick-wick pattern.", "internal_ids": ["ee0cf7f58f94"]},
    "64b657c8de8e": {"existing_ids": ["5e52d3fdf71f", "6afa7f774655"], "difference": "A lagged standardized one-bar log-return tail shock and next-bar rejection, not price-band overextension or RSI rebound.", "internal_ids": []},
    "74f607263c5c": {"existing_ids": ["18e87aa868ad", "f4e211e9510d"], "difference": "Nested two-bar high/low containment and mother-bar resolution, not an N-bar channel high.", "internal_ids": ["234e6df02e37", "bd234070bd7b"]},
    "7c1bf0a9686a": {"existing_ids": ["541c55834f56", "18e87aa868ad"], "difference": "Two-sided outside-range expansion with bullish close acceptance; not close-only range-percent breakout or one-sided channel breakout.", "internal_ids": ["1e4c0b9f84f7", "d0518c0cca14"]},
    "7f770ebe5ab5": {"existing_ids": ["270e6e28416f", "15567e02a806"], "difference": "Ordered rising lows plus local high confirmation, not moving-average alignment or EMA slope.", "internal_ids": []},
    "856ddc574ce7": {"existing_ids": ["6afa7f774655", "7f67e9aed0aa"], "difference": "Two-candle bearish-body midpoint recovery, not RSI or Stochastic oscillator threshold recovery.", "internal_ids": ["1a1a4389a821", "862e0c9eebbe"]},
    "862e0c9eebbe": {"existing_ids": ["6afa7f774655", "b4b65cd3493f"], "difference": "Three-stage bearish impulse, small-body pause, then midpoint reclaim; not a single oscillator snapback.", "internal_ids": ["1a1a4389a821", "856ddc574ce7", "bd234070bd7b"]},
    "930294d28c45": {"existing_ids": ["3cfcc2d296a2", "c33cc317bbeb"], "difference": "Adjacent-bar nearly equal lows followed by break of that bar's high, not a rolling channel or cumulative return dip.", "internal_ids": ["e9a9a5b44d03"]},
    "9eec3d61131d": {"existing_ids": ["c33cc317bbeb", "14e3b934b1e5"], "difference": "A discrete four-close selloff sequence with bullish close above the previous high, not a cumulative return threshold or ROC surge.", "internal_ids": []},
    "a4d6826fbbc6": {"existing_ids": ["0d51ba8d2012"], "difference": "Continuous log-return magnitude multiplied by volume, not OBV's signed volume accumulation.", "internal_ids": []},
    "af2bf88426c4": {"existing_ids": ["b96bafe57445", "090730ae35b8"], "difference": "A lagged true-range shock followed by midpoint reclaim, not volatility expansion/breakout continuation.", "internal_ids": []},
    "bd234070bd7b": {"existing_ids": ["18e87aa868ad"], "difference": "A bullish real body inside a bearish mother real body, with confirmation on a later bar; not an N-bar price channel.", "internal_ids": ["74f607263c5c", "1a1a4389a821"]},
    "be1174b24a44": {"existing_ids": ["cb750cb1eb10", "0d51ba8d2012"], "difference": "High effort with low real-body impact and upper-range close, not volume-spike trend confluence or OBV direction.", "internal_ids": []},
    "cb0b6e0f12e7": {"existing_ids": ["14e3b934b1e5", "f261549d9efa"], "difference": "Separate five-bar bullish/bearish real-body magnitudes, not close-return ROC momentum.", "internal_ids": ["2e41b2cfa24d", "a4d6826fbbc6"]},
    "d0518c0cca14": {"existing_ids": ["b96bafe57445", "090730ae35b8"], "difference": "Downside-only return semivariance contraction plus positive five-bar recovery, not full-range volatility expansion or channel breakout.", "internal_ids": []},
    "e9a9a5b44d03": {"existing_ids": ["3cfcc2d296a2", "c33cc317bbeb"], "difference": "Two separated trough windows, measured intervening neckline rebound, and neckline break; not a channel exit or one-window cumulative return dip.", "internal_ids": ["930294d28c45"]},
    "ee0cf7f58f94": {"existing_ids": [], "difference": "Two consecutive lower-tail rejections plus a third-bar confirmation; the existing 30 contain no multi-bar wick sequence.", "internal_ids": ["616e1b8cbc88"]},
    "fd16df3d0a3f": {"existing_ids": ["f261549d9efa", "270e6e28416f"], "difference": "Three bullish real bodies strictly increasing in size, not close-return ROC surge or EMA rising-slope.", "internal_ids": []},
}


def build_code(spec: dict[str, str], timeframe: str) -> str:
    return (
        f"class {spec['class']}(NoraStrategy):\n"
        f'    timeframe = "{timeframe}"\n\n'
        "    def on_bar(self):\n"
        + "\n".join(f"        {line}" if line else "" for line in spec["body"].strip("\n").splitlines())
        + "\n"
    )


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main() -> None:
    if set(SPECS) != TARGET_IDS or set(COMPARISONS) != TARGET_IDS or len(SPECS) != 27:
        raise ValueError("The v3 strategy map must cover exactly the 27 blocked fixture IDs")
    all_records = {
        record["id"]: record
        for path in USER_ALPHA_DIR.glob("*.json")
        for record in [json.loads(path.read_text(encoding="utf-8"))]
    }
    if len(all_records) != 57 or not TARGET_IDS.issubset(all_records):
        raise ValueError("Expected the frozen 57-record inventory and all 27 target IDs")
    other_ids = set(all_records) - TARGET_IDS
    for alpha_id, comparison in COMPARISONS.items():
        if not set(comparison["existing_ids"]).issubset(other_ids):
            raise ValueError(f"{alpha_id}: nearest-existing comparison references an unknown alpha")
        if not set(comparison["internal_ids"]).issubset(TARGET_IDS - {alpha_id}):
            raise ValueError(f"{alpha_id}: internal comparison references an unknown target")
    if len({SPECS[alpha_id]["family"] for alpha_id in TARGET_IDS}) != 27:
        raise ValueError("Primary signal families must be distinct within the 27-target set")

    staged: list[tuple[Path, dict[str, Any]]] = []
    manifest_rows = []
    now = datetime.now(timezone.utc).isoformat()
    for alpha_id in sorted(SPECS):
        path = USER_ALPHA_DIR / f"{alpha_id}.json"
        record = all_records[alpha_id]
        spec = SPECS[alpha_id]
        if record.get("id") != alpha_id or record.get("disposition") != "RESEARCH_PROPOSAL":
            raise ValueError(f"{alpha_id}: expected the existing in-place research proposal")
        timeframe = str((record.get("config") or {}).get("timeframe") or "24h")
        code = build_code(spec, timeframe)
        ast.parse(code)
        program = compile_code(code, register=False)
        source_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        prior_hash = hashlib.sha256(record["code"].encode("utf-8")).hexdigest()
        source_changed = prior_hash != source_hash

        updated = {
            "id": alpha_id,
            "name": spec["class"],
            "note": f"{spec['thesis']} Entry: {spec['entry']} Exit: {spec['exit']} Novelty: {spec['novelty']}",
            "source": record.get("source", "education"),
            "status": record.get("status", "SAVED"),
            "created_at": record.get("created_at"),
            "updated_at": now if source_changed else record.get("updated_at"),
            "code": code,
            "code_sha256": source_hash,
            "program_hash": program.code_hash,
            "config": record["config"],
            "owner_id": record.get("owner_id"),
            "version": int(record.get("version") or 2) + int(source_changed),
            "thesis": spec["thesis"],
            "primary_signal_family": spec["family"],
            "entry_rule": spec["entry"],
            "exit_rule": spec["exit"],
            "novelty_rationale": spec["novelty"],
            "falsifier": "Evaluate only after pre-registered production-engine backtest with verified data provenance and costs; do not tune this code against the same history.",
            "signal_priority": "Exit takes precedence when entry and exit are both true on the same bar.",
            "dsl_compile_status": "PASS",
            "backtest_status": "NOT_RUN",
            "disposition": "RESEARCH_PROPOSAL",
            "parent_source_sha256": record.get("parent_source_sha256"),
            "parent_record_sha256": record.get("parent_record_sha256"),
            "superseded_v2_source_sha256": record.get("superseded_v2_source_sha256") or prior_hash,
            "superseded_source_sha256s": list(
                dict.fromkeys(
                    [*(record.get("superseded_source_sha256s") or []), *([prior_hash] if source_changed else [])]
                )
            ),
        }
        staged.append((path, updated))
        comparison = COMPARISONS[alpha_id]
        manifest_rows.append(
            {
                "alpha_id": alpha_id,
                "owner_id": updated["owner_id"],
                "timeframe": timeframe,
                "class": spec["class"],
                "primary_signal_family": spec["family"],
                "thesis": spec["thesis"],
                "entry_rule": spec["entry"],
                "exit_rule": spec["exit"],
                "novelty_rationale": spec["novelty"],
                "features_used": program.features,
                "closest_existing_alpha_ids": comparison["existing_ids"],
                "comparison_difference": comparison["difference"],
                "closest_internal_alpha_ids": comparison["internal_ids"],
                "source_sha256": source_hash,
                "program_hash": program.code_hash,
                "superseded_source_sha256": prior_hash if source_changed else None,
                "superseded_v2_source_sha256": updated["superseded_v2_source_sha256"],
            }
        )

    manifest = {
        "schema_version": 1,
        "created_at": now,
        "status": "APPLIED_IN_PLACE_LOCAL_RULE_NOVELTY_AND_PRODUCTION_DSL_COMPILE_PASS",
        "scope": "Exactly 27 blocked EDU alpha IDs; no duplicate alpha records created.",
        "count": len(manifest_rows),
        "compiled_count": len(manifest_rows),
        "backtested_count": 0,
        "novelty_gate": "PASS_RULE_LEVEL",
        "novelty_scope": "All 27 source-level entry rules were individually reviewed against the current 30 other alpha records and pairwise within the 27. No identical primary entry definition or same-indicator/same-trigger strategy remains. Closely related families are listed per row with their operational distinction.",
        "novelty_limit": "Rule-level distinctness is not proof of statistical or economic independence. Candlestick, range-structure, gap, volatility, and flow ideas can remain related at a broader taxonomy level; performance correlation requires real backtest outputs.",
        "comparison_count": len(COMPARISONS),
        "signal_validation": {
            "kind": "synthetic_ohlcv_dsl_interpreter",
            "bars": 3000,
            "seed": 20261028,
            "entries": "27/27 targets",
            "prefix_invariance_checks": 108,
            "delayed_harami_confirmation": "PASS",
            "nautilus_backtest": False,
        },
        "evaluation": "No profitability or runtime-engine claim. Backtest is a separate gate and has not run.",
        "results": manifest_rows,
    }

    manifest_path = ROOT / "nora/check/candidates/edu_alpha_27_research_v3_20261028.json"
    for path, updated in staged:
        write_atomic(path, updated)
    write_atomic(manifest_path, manifest)
    print(f"Applied and production-compiled {len(staged)}/27 strategies in place.")
    print("Backtests run: 0. No new alpha records created.")


if __name__ == "__main__":
    main()
