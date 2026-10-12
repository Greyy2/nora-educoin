"""Shared configuration for S15 (Pure Core Execution Engine Parity).
Testing NautilusTrader vs Nora matching engine semantics across 9 fundamental categories.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CAPITAL = 10_000.0
TAKER = 0.0005
MAKER = 0.0002
M = 60_000
MIN_NS = 60_000_000_000
T0_MS = 1_700_000_000_000
T0_NS = T0_MS * 1_000_000

SYM = "BTC"
VENUE = "OKX"

OUT = os.path.join(HERE, "out", "s15")
os.makedirs(OUT, exist_ok=True)
