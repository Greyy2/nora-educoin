"""S10 Nora side: the REAL engine (PortfolioEngine -> KernelBook kernel), strategy tree on the signal frame (1h/4h) over the 1m base, position params
exit_unit/atr_frame/atr_period + stop_loss_rate/take_profit_rate/trailing_stop/trailing_activation_pct/timeout. No exit signal (stop tree empty).
Run from nora/: PYTHONDONTWRITEBYTECODE=1 ops/run_limited.sh --no-lock -- test/scripts/nautilus_diff/s10_run_nora.py [stages|all]
Writes out/s10/nora_<stage>.json (trades incl. unit_pct = the ATR% Nora used at entry, final_equity, open_at_end, rejected_for_risk).
"""
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))
from s10_common import CAPITAL, DAY, END, MAKER, OUT, PORT, ROOT, STAGES, START, SYMS, TAKER  # noqa: E402


def strategy(st):
    f = lambda col, lag=0: {"frame": st["frame"], "column": col, "index": lag}      # noqa: E731
    ema = f"ema_{st['ema']}"
    pos = {"market": "perp", "leverage": st["lev"], "fee_rate": TAKER, "maker_fee_rate": MAKER, "slippage_rate": 0.0, "order_size_pct": st["osp"],
           "sizing": "margin_pct", "cooldown": 0, "exit_unit": st["unit"], "atr_frame": st["atr_frame"], "atr_period": st["atr_period"],
           "stop_loss_rate": st["sl"], "take_profit_rate": st["tp"], "trailing_stop": st["trail"], "trailing_activation_pct": st["act"],
           "timeout": st["timeout"]}
    return {"id": "s10", "side": "LONG", "tree": [[[f("close"), ">", f(ema)], [f("close", 1), "<=", f(ema, 1)]]], "stop": [], "position": pos}


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
    trades = []
    for p in res["positions"]:
        tr = pos_row(p, ob, True)
        tr["sym"] = tr["sym"].split("@")[0]
        tr["unit_pct"] = float(p.unit_pct)
        trades.append(tr)
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
        from collections import Counter
        print(name, "trades", len(r["trades"]), dict(Counter(t["reason"][:12] for t in r["trades"])), "realized", round(r["realized_equity"], 4),
              "open_at_end", len(r["open_at_end"]), "rejected", r["rejected_for_risk"], flush=True)


if __name__ == "__main__":
    main()
