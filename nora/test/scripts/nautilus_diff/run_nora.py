"""Run Nora's production execution (PositionTracker == kernel path, and PositionManager+SimVenue event path) bar by bar
on the exported bars/signals. Writes out/nora_<dataset>_<signal>_<stage>.json.
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

from backend.core.execute.account import Account                      # noqa: E402
from backend.core.execute.manager import PositionManager              # noqa: E402
from backend.core.execute.models import PositionType                  # noqa: E402
from backend.core.execute.sim_venue import SimVenue                   # noqa: E402
from backend.core.execute.tracker import PositionTracker              # noqa: E402
from backend.core.params.schema import StrategyParams                 # noqa: E402

OUT = os.path.join(HERE, "out")


def make_params(st, path="ohlc"):
    return StrategyParams(intrabar_path=path, 
        market="perp", leverage=1, fee_rate=TAKER, maker_fee_rate=MAKER, slippage_rate=0.0,
        order_size_pct=st.get("osp", ORDER_SIZE_PCT), sizing="margin_pct", stop_loss_rate=st.get("sl", 0.0),
        take_profit_rate=st.get("tp", 0.0), dca_steps=list(st.get("dca_steps", [])),
        dca_multipliers=list(st.get("dca_mults", [])), max_capital_usage=1.0, cooldown=0, timeout=0, trailing_stop=0.0)


def pos_row(p, orders=()):
    return {"fills": [[int(o.order_time), float(o.order_price), float(o.qty), float(o.fee_usd), str(o.liquidity)]
                      for o in orders if o.position_id == p.result_id],
            "enter_time": int(p.enter_time), "enter_price": float(p.enter_price), "close_time": int(p.close_time),
            "close_price": float(p.close_price), "qty": float(p.qty), "avg_price": float(p.avg_price),
            "pnl": float(p.real_pnl), "fees": float(p.fees_usd), "reason": str(p.close_reason),
            "status": int(p.status), "entry_equity": float(p.entry_equity), "layers": int(p.layers or 1)}


def run(bars, sg, st, path, ipath="ohlc"):
    p = make_params(st, ipath)
    if path == "tracker":
        tr = PositionTracker(0, 0, "BTC", "L", p, PositionType.LONG, CAPITAL)
        actor, acct = tr, tr.ledger
    else:
        tr = PositionTracker(0, 0, "BTC", "L", p, PositionType.LONG, CAPITAL)
        acct = Account(CAPITAL)
        actor = PositionManager(tr, SimVenue(), slot=0, account=acct)
    rows = []
    for t, o, h, l, c, en, ex in zip(bars.open_time, bars.open, bars.high, bars.low, bars.close, sg["entry"], sg["exit"]):
        pos = actor.on_bar(int(t), float(o), float(h), float(l), float(c), entry_signal=bool(en), stop_signal=bool(ex))
        if pos is not None:
            rows.append(pos_row(pos, actor.orders))
    return {"trades": rows, "final_equity": float(acct.equity), "open_at_end": bool(actor.is_open),
            "dca_rejected": int(getattr(actor, "dca_rejected", 0))}


def main():
    ipath = sys.argv[1] if len(sys.argv) > 1 else "ohlc"
    suffix = "" if ipath == "ohlc" else "_" + ipath
    sigdf = pd.read_csv(os.path.join(OUT, "signals.csv"))
    for ds in DATASETS:
        bars = pd.read_csv(os.path.join(OUT, f"bars_{ds}.csv"))
        for sname in SIGNALS:
            sg = {"entry": sigdf[sname + "_entry"].values, "exit": sigdf[sname + "_exit"].values}
            for stname, st in STAGES.items():
                a, b = run(bars, sg, st, "tracker", ipath), run(bars, sg, st, "manager", ipath)
                ident = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
                a["tracker_eq_manager_bit_identical"] = ident
                json.dump(a, open(os.path.join(OUT, f"nora_{ds}_{sname}_{stname}{suffix}.json"), "w"))
                print(ds, sname, stname, "trades", len(a["trades"]), "final", round(a["final_equity"], 4),
                      "tracker==manager", ident)


if __name__ == "__main__":
    main()
