"""Shared config for S9 (P12 part C): two symbols, 1m execution bars + a 1D signal frame (ts on close), % stop-loss on the 1m path, max_positions=1.
Everything of S9 lives in s9_*.py (+ the S9 section of EXT_REPORT.md); S1-S8 files are untouched.

Semantics under test (P12 A1): an ENTRY condition on a frame larger than the base (24h on a 1m base) fires ONCE per signal-frame bar close (event),
not on every 1m bar of the day: after a stop-out inside the day the same daily signal must not re-enter; the next daily close may.
Exit (close < EMA) stays a STATE. The stop-loss is checked on the 1m path inside the day.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import CAPITAL, TAKER, MAKER  # noqa: E402,F401

OUT = os.path.join(HERE, "out", "s9")
ROOT = os.path.join(OUT, "data_root")            # Nora data root (cex/<SYM>/perp/{1m,..,24h}.pkl) built from OKX 1m, open[t]:=close[t-1]
SYMS = ["BTC", "ETH"]                            # book order = Nora slot order = Nautilus act order
SRC_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "data", "market", "okx"))
START = "2026-01-01"                             # whole UTC days; EMA warm-up is inside the window (signals NaN -> False)
END = "2026-09-30"                               # inclusive last day
M, DAY = 60_000, 86_400_000
PORT = {"max_positions": 1, "max_per_symbol": 1, "max_gross_exposure": 10.0}

# mode: "cross" = daily close crosses above EMA(n) (close>ema and prev close<=prev ema); "level" = daily close > EMA(n) at each fresh daily bar.
# exit (both): daily close < EMA(n) (state). sl = % stop from the entry price, intrabar on 1m. lev 1, osp = % of equity as margin.
STAGES = {
    "S9a": {"mode": "cross", "ema": 20, "sl": 1.0, "osp": 50.0, "lev": 1},
    "S9b": {"mode": "level", "ema": 10, "sl": 1.5, "osp": 50.0, "lev": 1},
    "S9c": {"mode": "level", "ema": 10, "sl": 0.4, "osp": 50.0, "lev": 1},     # tight stop: many same-day stop-outs while the daily signal stays true
}
