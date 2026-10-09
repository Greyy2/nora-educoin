"""Shared config for S12 (G1: Convention of order execution on gapped/RAW data).
Two symbols (BTC, ETH), 1m execution base bars + 24h / 4h signal frames.
Data: RAW market data from OKX (open[t] != close[t-1]), gaps are preserved.
Under test:
- Mode 'next_open' (Nora default & Nautilus next-open simulation): fills at Open_{t+1}. Must match trade-by-trade!
- Mode 'close_fill' (Nautilus legacy convention): fills at Close_t. Produces convention divergence table.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import CAPITAL, TAKER, MAKER  # noqa: E402,F401

OUT = os.path.join(HERE, "out", "s12")
ROOT = os.path.join(OUT, "data_root")
SYMS = ["BTC", "ETH"]
SRC_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "data", "market", "okx"))
START = "2026-01-01"
END = "2026-09-30"
M, DAY = 60_000, 86_400_000
PORT = {"max_positions": 1, "max_per_symbol": 1, "max_gross_exposure": 10.0}

STAGES = {
    "S12a": {"frame": "24h", "mode": "cross", "ema": 20, "sl": 1.0, "osp": 50.0, "lev": 1},
    "S12b": {"frame": "24h", "mode": "level", "ema": 10, "sl": 1.5, "osp": 50.0, "lev": 1},
    "S12c": {"frame": "24h", "mode": "level", "ema": 10, "sl": 0.4, "osp": 50.0, "lev": 1},
}
