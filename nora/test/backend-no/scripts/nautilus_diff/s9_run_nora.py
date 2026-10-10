"""S9 Nora side: the REAL engine (PortfolioEngine -> KernelBook kernel) on a 24h strategy tree over the 1m base - no injected per-bar flags. The
signal columns come out of the engine's own load_data (frame values -> align_index -> gather), so the P12 entry-event gating (whatever the engine
currently does) is exercised end to end.
Run from nora/: PYTHONDONTWRITEBYTECODE=1 ops/run_limited.sh --no-lock -- test/scripts/nautilus_diff/s9_run_nora.py [stages|all] [signal_mode]
  signal_mode (optional, e.g. "level" for the legacy behaviour once the engine has the flag) is passed as position["signal_mode"]; omitted -> engine default.
Writes out/s9/nora_<stage>[_<mode>].json (same fields/layout as ext_run_nora: trades, final_equity, open_at_end, rejected_for_risk).
"""
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))      # test/ (golden_scenarios.data_root_env)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))
from s9_common import CAPITAL, DAY, END, MAKER, OUT, PORT, ROOT, STAGES, START, SYMS, TAKER  # noqa: E402


def fld(col, lag=0):
    return {"frame": "24h", "column": col, "index": lag}


def strategy(st, signal_mode=None):
    ema = f"ema_{st['ema']}"
    conds = [[fld("close"), ">", fld(ema)]]
    if st["mode"] == "cross":
        conds.append([fld("close", 1), "<=", fld(ema, 1)])
    pos = {"market": "perp", "leverage": st["lev"], "fee_rate": TAKER, "maker_fee_rate": MAKER, "slippage_rate": 0.0, "order_size_pct": st["osp"],
           "sizing": "margin_pct", "stop_loss_rate": st["sl"], "cooldown": 0}
    if signal_mode:
        pos["signal_mode"] = signal_mode
    return {"id": "s9", "side": "LONG", "tree": [conds], "stop": [{"condition": [[[fld("close"), "<", fld(ema)]]]}], "position": pos}


def run_stage(name, signal_mode=None):
    from golden_scenarios import data_root_env
    from backend.core.backtest import PortfolioEngine, RiskConfig
    from step_common import pos_row, _by_pos
    st = STAGES[name]
    t0 = int(pd.Timestamp(START, tz="UTC").timestamp() * 1000)
    t1 = int(pd.Timestamp(END, tz="UTC").timestamp() * 1000) + DAY - 60_000
    with data_root_env(ROOT):
        eng = PortfolioEngine([f"{s}@perp" for s in SYMS], [strategy(st, signal_mode)], t0, t1, trade_start_ts=t0, initial_capital=CAPITAL,
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
    return {"stage": name, "signal_mode": signal_mode or "default", "trades": trades, "final_equity": res["final_equity"], "realized_equity": realized,
            "open_at_end": [{"sym": o["symbol"].split("@")[0], "enter_time": o["opened"], "entry_price": o["entry_price"], "qty": o["qty"],
                             "unrealized_pnl": o["unrealized_pnl"]} for o in open_pos],
            "rejected_for_risk": res["rejected_for_risk"]}


def main():
    only = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] != "all" else list(STAGES)
    mode = sys.argv[2] if len(sys.argv) > 2 else None
    for name in only:
        r = run_stage(name, mode)
        json.dump(r, open(os.path.join(OUT, f"nora_{name}{'_' + mode if mode else ''}.json"), "w"))
        print(name, mode or "default", "trades", len(r["trades"]), "realized", round(r["realized_equity"], 4), "open_at_end", len(r["open_at_end"]),
              "rejected_for_risk", r["rejected_for_risk"], flush=True)


if __name__ == "__main__":
    main()
