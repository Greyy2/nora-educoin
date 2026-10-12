"""Shared config for S11 (cooldown > 0, DCA ladder, funding), same architecture as S9: 2 symbols, 1m execution bars + a 1H signal frame (ts on close),
% stop-loss on the 1m path, max_positions=1. Everything of S11 lives in s11_*.py (+ the S11 section of EXT_REPORT.md); older files are untouched.

Semantics under test: (a) cooldown: after a position closes at minute C an entry signal evaluated on the 1m bar t_s is accepted only if t_s - C >= cooldown
(t_s = entry boundary - 1 min; C = open_time of the 1m bar in which the stop hit, or the boundary of a signal exit); a 1h entry EVENT dropped by the
cooldown is LOST (no retry before the next 1h bar close).  (b) DCA: after the market entry, post-only limit layers: layer j at LAST_FILL*(1-sign*step_j%),
margin_j = margin_(j-1)*mult_j, maker fee, fill at the level; SL is % from the AVERAGE price (stale inside the bar of a DCA fill).  (c) funding (always on for perp in Nora, so applied in EVERY stage; S11c is the funding-focused one): OKX funding
rows applied at the open of the first 1m bar with open_time >= funding_time to the position open at that open: payment = qty*open*rate*(+1 long/-1 short),
charged to equity at once (it reduces the sizing equity), and into the trade pnl at close.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import CAPITAL, TAKER, MAKER  # noqa: E402,F401

OUT = os.path.join(HERE, "out", "s11")
ROOT = os.path.join(OUT, "data_root")
SYMS = ["BTC", "ETH"]
SRC_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "data", "market", "okx"))
START = "2026-04-01"
END = "2026-09-30"
M, HOUR, DAY = 60_000, 3_600_000, 86_400_000
PORT = {"max_positions": 1, "max_per_symbol": 1, "max_gross_exposure": 10.0}

# side L/S; ema on the 1h frame; entry = 1h close beyond the EMA (level mode, fires once per 1h close = event); exit = close on the other side (state).
# sl = % from the average; cool = cooldown minutes; dca_steps/dca_mults = per-layer step % and margin multiplier (None = no DCA); fund = apply funding.
STAGES = {
    "S11a": {"side": "L", "ema": 20, "sl": 0.5, "osp": 50.0, "lev": 1, "cool": 120, "dca": None, "fund": False},
    "S11b": {"side": "L", "ema": 20, "sl": 2.0, "osp": 10.0, "lev": 1, "cool": 0, "dca": {"n": 3, "step": 0.5, "mult": 1.5}, "fund": False},
    "S11c": {"side": "L", "ema": 20, "sl": 1.0, "osp": 40.0, "lev": 2, "cool": 0, "dca": None, "fund": True},
    "S11d": {"side": "L", "ema": 20, "sl": 2.0, "osp": 10.0, "lev": 2, "cool": 120, "dca": {"steps": [0.3, 0.5, 0.9], "mults": [1.5, 2.0, 1.0]}, "fund": True},
    "S11e": {"side": "S", "ema": 20, "sl": 2.0, "osp": 10.0, "lev": 2, "cool": 120, "dca": {"n": 3, "step": 0.5, "mult": 1.5}, "fund": True},
    # stop-loss tighter than the ladder depth: stop-outs of DCA'd positions (SL from the AVERAGE price, re-placed after every layer, qty of the full position)
    "S11f": {"side": "L", "ema": 20, "sl": 0.9, "osp": 12.0, "lev": 1, "cool": 120, "dca": {"steps": [0.3, 0.3, 0.3], "mults": [1.5, 1.5, 1.5]}, "fund": True},
}


def dca_lists(st):
    """(steps, mults) of a stage as Nora derives them (dca_steps/dca_multipliers, else dca_max_layers x dca_step_pct x dca_size_multiplier)."""
    d = st["dca"]
    if not d:
        return [], []
    if "steps" in d:
        return list(d["steps"]), list(d["mults"])
    return [d["step"]] * d["n"], [d["mult"]] * d["n"]
