"""Run Nora's single kernel engine (SlotDriver = slot_bar on arrays; self-check: == RefPositionTracker, the frozen oracle in test/reference_engine.py)
bar by bar on the exported bars/signals. Writes out/nora_<dataset>_<signal>_<stage>.json.
Run from nora/: PYTHONDONTWRITEBYTECODE=1 backend/utils/ops/run_limited.sh --no-lock -- test/scripts/nautilus_diff/run_nora.py [ohlc|adaptive]
(intrabar_path; "adaptive" writes out/nora_<...>_adaptive.json and is compared with Nautilus bar_adaptive_high_low_ordering=True)
"""
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import STAGES, SIGNALS, DATASETS, CAPITAL, ORDER_SIZE_PCT, TAKER, MAKER  # noqa: E402

from step_common import run_single                                  # noqa: E402
from backend.core.params.schema import StrategyParams                 # noqa: E402

OUT = os.path.join(HERE, "out")


def make_params(st, path="ohlc"):
    return StrategyParams(intrabar_path=path, 
        market="perp", leverage=1, fee_rate=TAKER, maker_fee_rate=MAKER, slippage_rate=0.0,
        order_size_pct=st.get("osp", ORDER_SIZE_PCT), sizing="margin_pct", stop_loss_rate=st.get("sl", 0.0),
        take_profit_rate=st.get("tp", 0.0), dca_steps=list(st.get("dca_steps", [])),
        dca_multipliers=list(st.get("dca_mults", [])), max_capital_usage=1.0, cooldown=0, timeout=0, trailing_stop=0.0)


def run(bars, sg, st, ipath="ohlc"):
    """SlotDriver (single kernel engine) vs RefPositionTracker on the same bars; returns (SlotDriver result, bit_identical)."""
    cols = (bars.open_time.values, bars.open.values, bars.high.values, bars.low.values, bars.close.values)
    res, ident = run_single(make_params(st, ipath), "L", "BTC", cols, sg["entry"], sg["exit"], CAPITAL)
    res.pop("funding_log")                          # S1-S3 have no funding; the S1-S3 result layout never had the key
    return res, ident


def main():
    ipath = sys.argv[1] if len(sys.argv) > 1 else "ohlc"
    suffix = "" if ipath == "ohlc" else "_" + ipath
    sigdf = pd.read_csv(os.path.join(OUT, "signals.csv"))
    for ds in DATASETS:
        bars = pd.read_csv(os.path.join(OUT, f"bars_{ds}.csv"))
        for sname in SIGNALS:
            sg = {"entry": sigdf[sname + "_entry"].values, "exit": sigdf[sname + "_exit"].values}
            for stname, st in STAGES.items():
                a, ident = run(bars, sg, st, ipath)
                a["tracker_eq_manager_bit_identical"] = ident            # key name kept for compare.py; now: SlotDriver == RefPositionTracker
                json.dump(a, open(os.path.join(OUT, f"nora_{ds}_{sname}_{stname}{suffix}.json"), "w"))
                print(ds, sname, stname, "trades", len(a["trades"]), "final", round(a["final_equity"], 4),
                      "slot==ref", ident)


if __name__ == "__main__":
    main()
