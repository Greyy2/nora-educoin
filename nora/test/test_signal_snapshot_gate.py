"""Cổng tín hiệu P17: băm mảng tín hiệu (match/stop/vol/dca) của 2 tài sản x khung 1h trên dữ liệu catalog thật phải bằng fixture p17_signal_snapshot.json."""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "p17_signal_snapshot.json")
sys.path.insert(0, os.path.join(HERE, "scripts"))

SYMS = ["BTC@perp", "ETH@perp"]
FRAMES = ["1h"]


def test_signal_snapshot_subset_identical():
    from backend.data import data as _data  # noqa: F401
    import p16_engine_snapshot as snap
    base = json.load(open(FIXTURE, encoding="utf-8"))
    cur = snap.case_signals(SYMS, FRAMES)
    for fr in FRAMES:
        assert set(cur[fr]) == set(SYMS)
        for sym in SYMS:
            assert cur[fr][sym] == base[fr][sym], (fr, sym)
