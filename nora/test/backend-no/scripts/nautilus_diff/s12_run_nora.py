"""S12 Nora side: Real engine (PortfolioEngine) on RAW data.
"""
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))
from s12_common import CAPITAL, DAY, END, MAKER, OUT, PORT, ROOT, STAGES, START, SYMS, TAKER  # noqa: E402


def fld(col, lag=0):
    return {"frame": "24h", "column": col, "index": lag}


def strategy(st):
    ema = f"ema_{st['ema']}"
    conds = [[fld("close"), ">", fld(ema)]]
    if st["mode"] == "cross":
        conds.append([fld("close", 1), "<=", fld(ema, 1)])
    pos = {"market": "perp", "leverage": st["lev"], "fee_rate": TAKER, "maker_fee_rate": MAKER, "slippage_rate": 0.0, "order_size_pct": st["osp"],
           "sizing": "margin_pct", "stop_loss_rate": st["sl"], "cooldown": 0}
    return {"id": "s12", "side": "LONG", "tree": [conds], "stop": [{"condition": [[[fld("close"), "<", fld(ema)]]]}], "position": pos}


def run_stage(name):
    from golden_scenarios import data_root_env
    from backend.core.backtest import PortfolioEngine, RiskConfig
    from step_common import pos_row, _by_pos
    st = STAGES[name]
    t0 = int(pd.Timestamp(START, tz="UTC").timestamp() * 1000)
    t1 = int(pd.Timestamp(END, tz="UTC").timestamp() * 1000) + DAY - 60_000
    with data_root_env(ROOT):
        eng = PortfolioEngine([f"{s}@perp" for s in SYMS], [strategy(st)], t0, t1, trade_start_ts=t0, initial_capital=CAPITAL,
                              risk=RiskConfig(kill_switch_dd_pct=0.0, **PORT), use_cache=False, close_at_end=False, base_frame="1m")
        eng.run()
        res = eng.get_results()
        open_pos = eng.open_positions()
    ob = _by_pos(res["orders"])
    trades = [pos_row(p, ob, True) for p in res["positions"]]
    for tr in trades:
        tr["sym"] = tr["sym"].split("@")[0]
    trades.sort(key=lambda t: (t["enter_time"], t["sym"]))
    realized = CAPITAL + sum(t["pnl"] for t in trades)
    return {"stage": name, "trades": trades, "final_equity": res["final_equity"], "realized_equity": realized,
            "open_at_end": [{"sym": o["symbol"].split("@")[0], "enter_time": o["opened"], "entry_price": o["entry_price"], "qty": o["qty"],
                             "unrealized_pnl": o["unrealized_pnl"]} for o in open_pos],
            "rejected_for_risk": res["rejected_for_risk"]}


def main():
    only = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] != "all" else list(STAGES)
    for name in only:
        r = run_stage(name)
        json.dump(r, open(os.path.join(OUT, f"nora_{name}.json"), "w"))
        print(name, "trades", len(r["trades"]), "realized", round(r["realized_equity"], 4), "open_at_end", len(r["open_at_end"]),
              "rejected_for_risk", r["rejected_for_risk"], flush=True)


if __name__ == "__main__":
    main()
