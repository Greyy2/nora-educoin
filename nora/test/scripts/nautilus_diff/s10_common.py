"""Shared config for S10 (exit mechanics: ATR-unit SL/TP, trailing stop, timeout), two symbols, 1m execution bars + a 1h/4h signal frame
(ts on close), max_positions=1. Everything of S10 lives in s10_*.py (+ the S10 section of EXT_REPORT.md); S1-S9 files are untouched.

Entry = EVENT (cross above EMA(n) on the signal frame, P12 A1), no exit signal: positions end ONLY through the exit mechanics under test.
Fills: ALIGNED 1m data (open[t]:=close[t-1]) -> Nautilus' "market at the signal-bar close" (= last 1m close) is the same price/instant as Nora's
"market at the next 1m open", as in S9.
Exit params (Nora position dict): stop_loss_rate / take_profit_rate / trailing_stop / trailing_activation_pct are multiples of the entry-time ATR%
when exit_unit="atr" (unit = natr_<period> of the last atr_frame candle CLOSED at the entry instant), % when exit_unit="pct". timeout = minutes.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import CAPITAL, TAKER, MAKER  # noqa: E402,F401

OUT = os.path.join(HERE, "out", "s10")
ROOT = os.path.join(OUT, "data_root")
SYMS = ["BTC", "ETH"]
SRC_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "data", "market", "okx"))
START = "2026-04-01"
END = "2026-09-30"
M, DAY = 60_000, 86_400_000
FRAME_MS = {"1h": 3_600_000, "4h": 14_400_000}
PORT = {"max_positions": 1, "max_per_symbol": 1, "max_gross_exposure": 10.0}

# frame/ema: signal = close crosses above EMA(ema) on `frame`. unit "atr"|"pct". sl/tp/trail/act: multiples of unit (0 = off). timeout minutes (0 = off).
STAGES = {
    "S10a":  {"frame": "4h", "ema": 20, "unit": "atr", "atr_frame": "1h", "atr_period": 14, "sl": 1.5, "tp": 2.0, "trail": 0.0, "act": 0.0, "timeout": 0,
              "osp": 50.0, "lev": 1},
    "S10a2": {"frame": "1h", "ema": 24, "unit": "atr", "atr_frame": "4h", "atr_period": 14, "sl": 2.0, "tp": 1.0, "trail": 0.0, "act": 0.0, "timeout": 0,
              "osp": 50.0, "lev": 1},
    "S10b":  {"frame": "4h", "ema": 20, "unit": "pct", "atr_frame": "1h", "atr_period": 14, "sl": 3.0, "tp": 0.0, "trail": 1.5, "act": 0.8, "timeout": 0,
              "osp": 50.0, "lev": 1},
    "S10b2": {"frame": "1h", "ema": 24, "unit": "atr", "atr_frame": "1h", "atr_period": 14, "sl": 3.0, "tp": 0.0, "trail": 1.5, "act": 1.0, "timeout": 0,
              "osp": 50.0, "lev": 1},
    "S10c":  {"frame": "4h", "ema": 20, "unit": "pct", "atr_frame": "1h", "atr_period": 14, "sl": 6.0, "tp": 0.0, "trail": 0.0, "act": 0.0, "timeout": 1000,
              "osp": 50.0, "lev": 1},
}
