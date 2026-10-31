#!/usr/bin/env python3
"""Build separate, immutable research candidates for the 27 blocked fixture alphas."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EDU_DIR = ROOT / "nora/edu"
ALPHA_DIR = EDU_DIR / "data/alpha/user"
BASELINE_PATH = ROOT / "nora/check/edu_alpha_baseline_results.json"
DEFAULT_OUTPUT = ROOT / "nora/check/candidates/edu_fixture_alpha_candidates_v2_20261028.json"
DEFAULT_COMPILE_RESULTS = ROOT / "nora/check/candidates/edu_fixture_alpha_compile_results_v2_20261028.json"


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def strategy(class_name: str, timeframe: str, body: str) -> str:
    body_lines = body.strip("\n").splitlines()
    ordinary_lines = []
    entry_actions = []
    exit_actions = []
    for line in body_lines:
        statement = line.strip()
        if statement.startswith("self.buy("):
            entry_actions.append(line)
        elif statement.startswith("self.close("):
            exit_actions.append(line)
        else:
            ordinary_lines.append(line)
    if len(entry_actions) != 1 or len(exit_actions) != 1:
        raise ValueError(f"{class_name}: expected exactly one buy and one close action")
    ordered_lines = ordinary_lines + entry_actions + exit_actions
    return (
        f"class {class_name}(NoraStrategy):\n"
        f'    timeframe = "{timeframe}"\n\n'
        "    def on_bar(self):\n"
        + "\n".join(f"        {line}" if line else "" for line in ordered_lines)
        + "\n"
    )


SPECS: dict[str, dict[str, str]] = {
    "1a1a4389a821": {
        "class": "U1EmaPullback",
        "thesis": "Pullback entry only while the intermediate EMA trend is rising.",
        "entry": "Close crosses above EMA20 while EMA20 is above EMA50.",
        "exit": "Close crosses below EMA50.",
        "falsifier": "Reject if net edge disappears after fees or is concentrated in one trend segment.",
        "body": """
close = close
ema20 = self.feat.ema(close, 20)
ema50 = self.feat.ema(close, 50)
entry = self.op.crossed_above(close, ema20) & (ema20 > ema50)
exit_signal = self.op.crossed_below(close, ema50)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "cb0b6e0f12e7": {
        "class": "U1DonchianBullBreak",
        "thesis": "A prior-range breakout with a bullish close avoids treating positive price as a signal.",
        "entry": "Close crosses above the prior 20-bar Donchian high and closes above open.",
        "exit": "Close crosses below EMA10.",
        "falsifier": "Reject if false breakouts and costs erase the net edge.",
        "body": """
close = close
upper = self.feat.donchian_upper(high, 20)
ema10 = self.feat.ema(close, 10)
entry = self.op.crossed_above(close, upper) & (close > open)
exit_signal = self.op.crossed_below(close, ema10)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "bd234070bd7b": {
        "class": "U1RsiRecoveryTrend",
        "thesis": "An oversold recovery is considered only when the long-term price regime is positive.",
        "entry": "RSI14 crosses above 35 within eight bars of RSI being below 30, with close above EMA100.",
        "exit": "RSI14 crosses above 70 or close falls below EMA50.",
        "falsifier": "Reject if it does not improve risk-adjusted results over same-window buy-and-hold.",
        "body": """
close = close
rsi14 = self.feat.rsi(close, 14)
ema100 = self.feat.ema(close, 100)
ema50 = self.feat.ema(close, 50)
recent_oversold = self.op.bars_since(rsi14 < 30) <= 8
entry = self.op.crossed_above_value(rsi14, 35) & recent_oversold & (close > ema100)
exit_signal = self.op.crossed_above_value(rsi14, 70) | (close < ema50)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "2e41b2cfa24d": {
        "class": "U1BollingerSqueezeBreak",
        "thesis": "A volatility contraction followed by an upper-band break may capture expansion rather than buy any positive price.",
        "entry": "Prior-bar NATR14 is below its SMA20 and close crosses above the Bollinger upper band.",
        "exit": "Close crosses below the Bollinger middle band.",
        "falsifier": "Reject if results fail pre-registered cost stress or depend on one squeeze threshold.",
        "body": """
close = close
natr14 = self.feat.natr(high, low, close, 14)
natr_mean = self.feat.sma(natr14, 20)
upper, middle, lower = self.feat.bbands(close, 20, 2.0, 2.0)
squeezed = self.op.previous(natr14 < natr_mean, 1)
entry = squeezed & self.op.crossed_above(close, upper)
exit_signal = self.op.crossed_below(close, middle)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "138df68946ad": {
        "class": "U1LinearSlopeTurn",
        "thesis": "A positive turn in regression slope is a directional momentum signal, unlike an absolute price threshold.",
        "entry": "Linear-regression slope14 crosses above zero while close is above EMA50.",
        "exit": "Slope14 crosses below zero.",
        "falsifier": "Reject if exposure-adjusted results do not improve on a trend benchmark.",
        "body": """
close = close
slope14 = self.feat.linearreg_slope(close, 14)
ema50 = self.feat.ema(close, 50)
entry = self.op.crossed_above_value(slope14, 0) & (close > ema50)
exit_signal = self.op.crossed_below_value(slope14, 0)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "be1174b24a44": {
        "class": "U1ObvAccumulation",
        "thesis": "Volume-flow confirmation may distinguish accumulation from a price-only trend.",
        "entry": "Close is above EMA50 and OBV crosses above its 20-bar mean.",
        "exit": "Close falls below EMA20 or OBV crosses below its mean.",
        "falsifier": "Reject if volume provenance is not consistent or net performance does not improve.",
        "body": """
close = close
ema50 = self.feat.ema(close, 50)
ema20 = self.feat.ema(close, 20)
obv = self.feat.obv(close, volume)
obv_mean = self.feat.sma(obv, 20)
entry = (close > ema50) & self.op.crossed_above(obv, obv_mean)
exit_signal = (close < ema20) | self.op.crossed_below(obv, obv_mean)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "ee0cf7f58f94": {
        "class": "U2BollingerReclaim",
        "thesis": "A reclaim of the lower volatility band after weakness may capture a short mean-reversion move.",
        "entry": "Close crosses back above Bollinger lower band while RSI14 is below 45.",
        "exit": "Close crosses above Bollinger middle band.",
        "falsifier": "Reject if cost stress removes the edge or only 800 bars are available for evaluation.",
        "body": """
close = close
rsi14 = self.feat.rsi(close, 14)
upper, middle, lower = self.feat.bbands(close, 20, 2.0, 2.0)
entry = self.op.crossed_above(close, lower) & (rsi14 < 45)
exit_signal = self.op.crossed_above(close, middle)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "234e6df02e37": {
        "class": "U2DonchianExpansion",
        "thesis": "A short-horizon range breakout is traded only when volatility is not already extreme.",
        "entry": "Close crosses above prior 20-bar Donchian high and NATR14 is below twice its 50-bar mean.",
        "exit": "Close crosses below EMA20.",
        "falsifier": "Reject if trade costs make net expectancy non-positive.",
        "body": """
close = close
upper = self.feat.donchian_upper(high, 20)
natr14 = self.feat.natr(high, low, close, 14)
natr_mean = self.feat.sma(natr14, 50)
ema20 = self.feat.ema(close, 20)
entry = self.op.crossed_above(close, upper) & (natr14 < 2.0 * natr_mean)
exit_signal = self.op.crossed_below(close, ema20)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "e9a9a5b44d03": {
        "class": "U2MacdZeroRegime",
        "thesis": "A MACD zero-line transition with a higher-timeframe trend filter seeks a durable momentum regime.",
        "entry": "MACD line crosses above zero while close is above EMA100.",
        "exit": "MACD line crosses below zero or close falls below EMA50.",
        "falsifier": "Reject if the chosen data window cannot support enough independent trades.",
        "body": """
close = close
macd_line, signal_line, histogram = self.feat.macd(close, 12, 26, 9)
ema100 = self.feat.ema(close, 100)
ema50 = self.feat.ema(close, 50)
entry = self.op.crossed_above_value(macd_line, 0) & (close > ema100)
exit_signal = self.op.crossed_below_value(macd_line, 0) | (close < ema50)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "616e1b8cbc88": {
        "class": "U2NatrExpansionBreak",
        "thesis": "A range breakout concurrent with rising normalized volatility may identify expansion rather than quiet drift.",
        "entry": "NATR14 crosses above its 20-bar mean while close crosses above the prior 20-bar Donchian high.",
        "exit": "Close crosses below EMA20.",
        "falsifier": "Reject if outcome is highly sensitive to the fixed volatility lookback or threshold.",
        "body": """
close = close
natr14 = self.feat.natr(high, low, close, 14)
natr_mean = self.feat.sma(natr14, 20)
upper = self.feat.donchian_upper(high, 20)
ema20 = self.feat.ema(close, 20)
entry = self.op.crossed_above(natr14, natr_mean) & self.op.crossed_above(close, upper)
exit_signal = self.op.crossed_below(close, ema20)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "862e0c9eebbe": {
        "class": "U2CciSnapbackTrend",
        "thesis": "A CCI recovery from an unusually weak reading is considered only in a positive medium-term regime.",
        "entry": "CCI14 crosses above -100 while close is above EMA50.",
        "exit": "CCI14 crosses above +100 or close falls below EMA20.",
        "falsifier": "Reject if net results are worse than a simple, pre-registered mean-reversion benchmark.",
        "body": """
close = close
cci14 = self.feat.cci(high, low, close, 14)
ema50 = self.feat.ema(close, 50)
ema20 = self.feat.ema(close, 20)
entry = self.op.crossed_above_value(cci14, -100) & (close > ema50)
exit_signal = self.op.crossed_above_value(cci14, 100) | (close < ema20)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "856ddc574ce7": {
        "class": "U2StochasticRecovery",
        "thesis": "A stochastic turn from oversold may capture a rebound while a trend filter avoids some falling-market entries.",
        "entry": "Slow %K crosses above %D below 20 while close is above EMA50.",
        "exit": "Slow %K crosses below %D above 80 or close falls below EMA20.",
        "falsifier": "Reject if trade sample is insufficient or results exist only in one market regime.",
        "body": """
close = close
slowk, slowd = self.feat.stoch(high, low, close, 14, 3, 0, 3, 0)
ema50 = self.feat.ema(close, 50)
ema20 = self.feat.ema(close, 20)
entry = self.op.crossed_above(slowk, slowd) & (slowk < 20) & (close > ema50)
exit_signal = (self.op.crossed_below(slowk, slowd) & (slowk > 80)) | (close < ema20)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "214ea8fdf3e6": {
        "class": "U2ObvBreakout",
        "thesis": "A price breakout is accepted only when cumulative volume flow is already positive.",
        "entry": "Close crosses above prior Donchian high while OBV is above its 20-bar mean.",
        "exit": "Close falls below EMA20 or OBV crosses below its mean.",
        "falsifier": "Reject if volume data semantics/provenance are not verified for ETH.",
        "body": """
close = close
upper = self.feat.donchian_upper(high, 20)
ema20 = self.feat.ema(close, 20)
obv = self.feat.obv(close, volume)
obv_mean = self.feat.sma(obv, 20)
entry = self.op.crossed_above(close, upper) & (obv > obv_mean)
exit_signal = (close < ema20) | self.op.crossed_below(obv, obv_mean)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "fd16df3d0a3f": {
        "class": "U3EmaRegimeGate",
        "thesis": "A long-only allocation gate avoids holding through a defined bearish intermediate trend.",
        "entry": "Close crosses above EMA50.",
        "exit": "Close crosses below EMA50.",
        "falsifier": "Reject if drawdown reduction comes only from near-permanent cash exposure without better risk-adjusted results.",
        "body": """
close = close
ema50 = self.feat.ema(close, 50)
entry = self.op.crossed_above(close, ema50)
exit_signal = self.op.crossed_below(close, ema50)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "7f770ebe5ab5": {
        "class": "U3RocRecoveryGate",
        "thesis": "A long-only regime gate re-enters after short-term momentum turns positive rather than reacting to price sign.",
        "entry": "ROC10 crosses above zero while close is above EMA20.",
        "exit": "ROC10 crosses below zero.",
        "falsifier": "Reject if the gate exits too late or misses rebounds enough to underperform its exposure-matched benchmark.",
        "body": """
close = close
roc10 = self.feat.roc(close, 10)
ema20 = self.feat.ema(close, 20)
entry = self.op.crossed_above_value(roc10, 0) & (close > ema20)
exit_signal = self.op.crossed_below_value(roc10, 0)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "1e4c0b9f84f7": {
        "class": "U3DonchianBreakdownGate",
        "thesis": "A structural breakdown closes the long allocation; re-entry waits for a moving-average reclaim.",
        "entry": "Close crosses above EMA20.",
        "exit": "Close breaks below the prior 20-bar Donchian low.",
        "falsifier": "Reject if whipsaws increase turnover/costs or breakdowns fail to reduce tail losses.",
        "body": """
close = close
lower = self.feat.donchian_lower(low, 20)
ema20 = self.feat.ema(close, 20)
entry = self.op.crossed_above(close, ema20)
exit_signal = self.op.crossed_below(close, lower)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "930294d28c45": {
        "class": "U3RsiStrengthGate",
        "thesis": "An RSI strength regime requires recovery above the neutral line and a positive price trend.",
        "entry": "RSI14 crosses above 50 while close is above EMA50.",
        "exit": "RSI14 crosses below 45.",
        "falsifier": "Reject if thresholds are unstable across folds or the trade sample is inadequate.",
        "body": """
close = close
rsi14 = self.feat.rsi(close, 14)
ema50 = self.feat.ema(close, 50)
entry = self.op.crossed_above_value(rsi14, 50) & (close > ema50)
exit_signal = self.op.crossed_below_value(rsi14, 45)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "9eec3d61131d": {
        "class": "U3MacdRiskGate",
        "thesis": "A zero-line momentum regime controls long exposure and avoids the impossible negative-price condition.",
        "entry": "MACD line crosses above zero.",
        "exit": "MACD line crosses below zero.",
        "falsifier": "Reject if it fails to improve drawdown or net risk-adjusted results against the same-market benchmark.",
        "body": """
close = close
macd_line, signal_line, histogram = self.feat.macd(close, 12, 26, 9)
entry = self.op.crossed_above_value(macd_line, 0)
exit_signal = self.op.crossed_below_value(macd_line, 0)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "af2bf88426c4": {
        "class": "U3BollingerReclaim",
        "thesis": "After a lower-band excursion, re-entry waits for a middle-band reclaim and positive one-bar return.",
        "entry": "Close crosses above Bollinger middle within eight bars of closing below lower band, with ROC1 positive.",
        "exit": "Close crosses below Bollinger lower band.",
        "falsifier": "Reject if late entries underperform or the result is too sensitive to band settings.",
        "body": """
close = close
upper, middle, lower = self.feat.bbands(close, 20, 2.0, 2.0)
roc1 = self.feat.roc(close, 1)
recent_lower_break = self.op.bars_since(close < lower) <= 8
entry = self.op.crossed_above(close, middle) & recent_lower_break & (roc1 > 0)
exit_signal = self.op.crossed_below(close, lower)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "571474a18f55": {
        "class": "U3DirectionalTrendGate",
        "thesis": "Directional movement distinguishes a positive trend transition from price-level noise.",
        "entry": "Plus DI crosses above minus DI while close is above EMA50.",
        "exit": "ADX is above 25 and minus DI exceeds plus DI.",
        "falsifier": "Reject if the fixed ADX rule leaves too few trades or is unstable across folds.",
        "body": """
close = close
adx14 = self.feat.adx(high, low, close, 14)
plus_di = self.feat.plus_di(high, low, close, 14)
minus_di = self.feat.minus_di(high, low, close, 14)
ema50 = self.feat.ema(close, 50)
entry = self.op.crossed_above(plus_di, minus_di) & (close > ema50)
exit_signal = (adx14 > 25) & (minus_di > plus_di)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "0bf936687964": {
        "class": "U4DonchianTrendBreak",
        "thesis": "A 20-bar prior-high breakout holds until a faster trend guide is lost.",
        "entry": "Close crosses above prior 20-bar Donchian high.",
        "exit": "Close crosses below EMA10.",
        "falsifier": "Reject if results depend on one breakout or turnover costs erase net returns.",
        "body": """
close = close
upper = self.feat.donchian_upper(high, 20)
ema10 = self.feat.ema(close, 10)
entry = self.op.crossed_above(close, upper)
exit_signal = self.op.crossed_below(close, ema10)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "a4d6826fbbc6": {
        "class": "U4RsiMomentumRegime",
        "thesis": "RSI neutral-line recovery is used as momentum entry only above a slower trend filter.",
        "entry": "RSI14 crosses above 50 while close is above EMA100.",
        "exit": "RSI14 crosses below 45.",
        "falsifier": "Reject if it fails against an exposure-matched trend benchmark.",
        "body": """
close = close
rsi14 = self.feat.rsi(close, 14)
ema100 = self.feat.ema(close, 100)
entry = self.op.crossed_above_value(rsi14, 50) & (close > ema100)
exit_signal = self.op.crossed_below_value(rsi14, 45)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "64b657c8de8e": {
        "class": "U4TrendFilteredReversion",
        "thesis": "A lower-band reclaim is treated as mean reversion only while the long-term close regime is positive.",
        "entry": "Close crosses above Bollinger lower while close is above EMA100.",
        "exit": "Close crosses above Bollinger middle.",
        "falsifier": "Reject if the trend filter leaves too little sample or the result is inferior to a simple benchmark.",
        "body": """
close = close
upper, middle, lower = self.feat.bbands(close, 20, 2.0, 2.0)
ema100 = self.feat.ema(close, 100)
entry = self.op.crossed_above(close, lower) & (close > ema100)
exit_signal = self.op.crossed_above(close, middle)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "d0518c0cca14": {
        "class": "U4SqueezeDonchianBreak",
        "thesis": "A low-volatility contraction followed by a prior-range high break targets volatility expansion.",
        "entry": "Previous NATR14 is below its 20-bar mean and close crosses above prior Donchian high.",
        "exit": "Close crosses below EMA20.",
        "falsifier": "Reject if fold results are unstable or thresholds appear selected after viewing outcomes.",
        "body": """
close = close
natr14 = self.feat.natr(high, low, close, 14)
natr_mean = self.feat.sma(natr14, 20)
upper = self.feat.donchian_upper(high, 20)
ema20 = self.feat.ema(close, 20)
squeezed = self.op.previous(natr14 < natr_mean, 1)
entry = squeezed & self.op.crossed_above(close, upper)
exit_signal = self.op.crossed_below(close, ema20)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "7c1bf0a9686a": {
        "class": "U4MacdHistogramAcceleration",
        "thesis": "A rising MACD histogram confirms improving momentum after the MACD line leads its signal.",
        "entry": "MACD line crosses above signal, histogram has risen for two bars, and close is above EMA50.",
        "exit": "MACD line crosses below signal.",
        "falsifier": "Reject if histogram confirmation fails to improve expectancy over a plain MACD cross.",
        "body": """
close = close
macd_line, signal_line, histogram = self.feat.macd(close, 12, 26, 9)
ema50 = self.feat.ema(close, 50)
hist_rising = self.op.rising(histogram, 2)
entry = self.op.crossed_above(macd_line, signal_line) & hist_rising & (close > ema50)
exit_signal = self.op.crossed_below(macd_line, signal_line)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "026f43441cb2": {
        "class": "U4DemaCross",
        "thesis": "A faster double-EMA cross tests whether reduced lag compensates for added whipsaw.",
        "entry": "DEMA12 crosses above DEMA36.",
        "exit": "DEMA12 crosses below DEMA36.",
        "falsifier": "Reject if turnover-adjusted performance is below the pre-registered EMA trend benchmark.",
        "body": """
close = close
dema_fast = self.feat.dema(close, 12)
dema_slow = self.feat.dema(close, 36)
entry = self.op.crossed_above(dema_fast, dema_slow)
exit_signal = self.op.crossed_below(dema_fast, dema_slow)
self.close(exit_signal)
self.buy(entry)
""",
    },
    "74f607263c5c": {
        "class": "U4ObvBreakoutConfirmation",
        "thesis": "A breakout must coincide with a fresh volume-flow confirmation, not merely positive OBV level.",
        "entry": "Close crosses above prior Donchian high on the same bar OBV crosses above its 20-bar mean.",
        "exit": "Close crosses below EMA20 or OBV crosses below its mean.",
        "falsifier": "Reject if the signal relies on isolated volume spikes or lacks reproducible volume provenance.",
        "body": """
close = close
upper = self.feat.donchian_upper(high, 20)
ema20 = self.feat.ema(close, 20)
obv = self.feat.obv(close, volume)
obv_mean = self.feat.sma(obv, 20)
entry = self.op.crossed_above(close, upper) & self.op.crossed_above(obv, obv_mean)
exit_signal = (self.op.crossed_below(close, ema20)
               | self.op.crossed_below(obv, obv_mean))
self.close(exit_signal)
self.buy(entry)
""",
    },
}


def build_candidate(alpha_id: str, blocked_ids: set[str]) -> dict[str, Any]:
    path = ALPHA_DIR / f"{alpha_id}.json"
    raw = path.read_bytes()
    parent = json.loads(raw)
    if parent.get("disposition") == "RESEARCH_PROPOSAL":
        raise ValueError(
            f"{alpha_id} already contains the in-place research candidate; "
            "do not generate a second candidate record"
        )
    if alpha_id not in blocked_ids:
        raise ValueError(f"{alpha_id} is not listed as blocked in the baseline artifact")
    spec = SPECS[alpha_id]
    timeframe = str(parent.get("config", {}).get("timeframe") or "24h")
    code = strategy(spec["class"], timeframe, spec["body"])
    tree = ast.parse(code)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.ClassDef):
        raise ValueError(f"{alpha_id}: generated source must contain exactly one strategy class")
    on_bar = next(
        node for node in tree.body[0].body
        if isinstance(node, ast.FunctionDef) and node.name == "on_bar"
    )
    actions = [
        node.value.func.attr
        for node in on_bar.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "self"
        and node.value.func.attr in {"buy", "close"}
    ]
    if actions != ["buy", "close"]:
        raise ValueError(f"{alpha_id}: exit must follow entry so exit wins on simultaneous signals")

    return {
        "candidate_id": f"fixture-{alpha_id}-research-v2",
        "parent_id": alpha_id,
        "parent_source_sha256": sha256(parent.get("code", "").encode()),
        "parent_record_sha256": sha256(raw),
        "parent_config_sha256": sha256(canonical_json(parent.get("config", {}))),
        "owner_id": parent.get("owner_id"),
        "template_name": parent.get("name"),
        "timeframe": timeframe,
        "config": parent.get("config", {}),
        "thesis": spec["thesis"],
        "entry_rule": spec["entry"],
        "exit_rule": spec["exit"],
        "falsifier": spec["falsifier"],
        "signal_priority": "Exit takes precedence when entry and exit are both true on the same bar.",
        "code": code,
        "code_sha256": sha256(code.encode()),
        "syntax_status": "AST_PARSE_PASS",
        "dsl_compile_status": "NOT_RUN",
        "backtest_status": "NOT_RUN",
        "disposition": "RESEARCH_PROPOSAL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check-only", action="store_true", help="Validate source and IDs without writing the artifact")
    parser.add_argument("--compile", action="store_true", help="Compile every candidate using the EDU DSL compiler")
    parser.add_argument(
        "--compile-results",
        type=Path,
        help="Merge receipts from the production EDU compile endpoint",
    )
    args = parser.parse_args()

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    blocked_ids = set(baseline["blocked_records"])
    if blocked_ids != set(SPECS):
        missing = sorted(blocked_ids - set(SPECS))
        extra = sorted(set(SPECS) - blocked_ids)
        raise ValueError(f"Candidate inventory mismatch; missing={missing}, extra={extra}")

    candidates = [build_candidate(alpha_id, blocked_ids) for alpha_id in sorted(SPECS)]
    if len({item["candidate_id"] for item in candidates}) != 27:
        raise ValueError("Candidate IDs are not unique")

    if args.compile:
        sys.path.insert(0, str(EDU_DIR))
        from backend.analys.alpha.code.compile import compile_code

        for item in candidates:
            program = compile_code(item["code"], register=False)
            item["dsl_compile_status"] = "PASS"
            item["program_hash"] = program.code_hash

    compile_results_sha256 = None
    if args.compile_results:
        receipts = json.loads(args.compile_results.read_text(encoding="utf-8"))
        by_candidate = {row["candidate_id"]: row for row in receipts.get("results", [])}
        if len(by_candidate) != len(candidates):
            raise ValueError("Compile receipt count does not match the candidate count")
        for item in candidates:
            receipt = by_candidate.get(item["candidate_id"])
            if receipt is None or receipt.get("parent_id") != item["parent_id"]:
                raise ValueError(f"Missing/mismatched compile receipt for {item['candidate_id']}")
            if receipt.get("ok") is not True:
                item["dsl_compile_status"] = "FAIL"
                item["compile_error"] = receipt.get("error")
            else:
                item["dsl_compile_status"] = "PASS"
                item["program_hash"] = receipt.get("program_hash")
        compile_results_sha256 = sha256(args.compile_results.read_bytes())

    compile_pass = sum(item["dsl_compile_status"] == "PASS" for item in candidates)

    artifact = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "DSL_COMPILE_PASS" if compile_pass == len(candidates)
            else "PARTIAL_DSL_COMPILE" if compile_pass
            else "CANDIDATES_DEFINED_DSL_COMPILE_NOT_RUN"
        ),
        "disclaimer": (
            "Research proposals only. No profitability, OOS, promotion, or live-trading claim. "
            "These candidate definitions are applied in place to the existing EDU user-alpha records."
        ),
        "source_baseline_timestamp": baseline.get("timestamp"),
        "candidate_count": len(candidates),
        "compile_pass_count": compile_pass,
        "compile_receipts_sha256": compile_results_sha256,
        "candidates": candidates,
    }
    if not args.check_only:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {len(candidates)} candidates to {args.output}")
    else:
        print(f"Validated {len(candidates)} candidates; output not written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
