"""Nora side of the extended differential test (S4-S8): the single kernel engine bar by bar on the exported bars/signals (SlotDriver for the
single-symbol stages, checked == RefPositionTracker; KernelBook + admission trace for the S8 portfolio stages). Writes out/ext/nora_<ds>_<signal>_<stage>_<path>.json.
Run from nora/: PYTHONDONTWRITEBYTECODE=1 ops/run_limited.sh --no-lock -- test/scripts/nautilus_diff/ext_run_nora.py [ohlc|adaptive] [stages,..] [datasets,..] [signals,..]
"""
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ext_common import skip, CAPITAL, DATASETS, MAKER, OUT, SIGNALS, STAGES, SYMS, TAKER  # noqa: E402

from step_common import run_single as _run_single, run_portfolio as _run_portfolio  # noqa: E402
from backend.core.params import StrategyParams


def make_params(st, path):
    kw = dict(
        market="perp", leverage=st["lev"], fee_rate=TAKER, maker_fee_rate=MAKER, slippage_rate=0.0,
        order_size_pct=st["osp"], sizing="margin_pct", stop_loss_rate=st.get("sl", 0.0), take_profit_rate=st.get("tp", 0.0),
        dca_steps=list(st.get("dca_steps", [])), dca_multipliers=list(st.get("dca_mults", [])), max_capital_usage=1.0,
        cooldown=0, timeout=int(st.get("timeout", 0)) * 60, trailing_stop=st.get("trail", 0.0),
        trailing_activation_pct=st.get("trail_act", 0.0), maintenance_margin_rate=st["mmr"])
    if path != "ohlc":                         # only set when non-default so the harness also runs on a Nora without the field
        kw["intrabar_path"] = path
    return StrategyParams(**kw)


def position_dict(st, path):
    """The same parameters as `make_params`, as a `position` dict of a strategy book entry (core.params.build_params fills the rest identically)."""
    return {"market": "perp", "leverage": st["lev"], "fee_rate": TAKER, "maker_fee_rate": MAKER, "slippage_rate": 0.0,
            "order_size_pct": st["osp"], "sizing": "margin_pct", "stop_loss_rate": st.get("sl", 0.0), "take_profit_rate": st.get("tp", 0.0),
            "dca_steps": list(st.get("dca_steps", [])), "dca_multipliers": list(st.get("dca_mults", [])), "cooldown": 0,
            "timeout": int(st.get("timeout", 0)) * 60, "trailing_stop": st.get("trail", 0.0),
            "trailing_activation_pct": st.get("trail_act", 0.0), "maintenance_margin_rate": st["mmr"], "intrabar_path": path}


def load(sym, ds, sname):
    bars = pd.read_csv(os.path.join(OUT, f"bars_{sym}_{ds}.csv"))
    sg = pd.read_csv(os.path.join(OUT, f"signals_{sym}.csv"))
    fu = pd.read_csv(os.path.join(OUT, f"funding_{sym}.csv"))
    return bars, sg, fu


def sig_arrays(sg, sname, side):
    up, dn = sg[sname + "_up"].values, sg[sname + "_dn"].values
    return (up, dn) if side == "L" else (dn, up)           # (entry, exit)


def run_single(bars, ent, ext, fu, st, path, sym="BTC"):
    """SlotDriver (single kernel engine) vs RefPositionTracker (oracle) on the same bars/signals/funding. -> (SlotDriver result, bit_identical)."""
    cols = (bars.open_time.values, bars.open.values, bars.high.values, bars.low.values, bars.close.values)
    ft = fu.funding_time.values if st.get("fund") else []
    fr = fu.rate.values if st.get("fund") else []
    return _run_single(make_params(st, path), st["side"], sym, cols, ent, ext, CAPITAL, ft, fr, ext_layout=True)


def run_portfolio(data, st, path):
    """data[sym] = (bars, ent, ext, fu). KernelBook stepped bar by bar with the admission trace on (see step_common.run_portfolio).
    The 'sync' view of every decision is reconstructed from the book state and asserted equal to the kernel's own admission view: the kernel admits
    at the OPEN of the bar (state before any symbol's intrabar result), i.e. Nora == the time-synchronous view of an exchange / Nautilus.
    -> (result, chunked==per-bar bit identity)."""
    assert not st.get("fund"), "portfolio stages carry no funding"
    syms = st["syms"]
    strategies = [{"id": "S", "side": "LONG", "tree": [[[{"frame": "1m", "column": "close", "index": 0}, ">", 0]]], "position": position_dict(st, path)}]
    risk = dict(st["port"], kill_switch_dd_pct=0.0)
    return _run_portfolio(strategies, syms, CAPITAL, risk, {s: (data[s][0], data[s][1], data[s][2]) for s in syms})


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "ohlc"
    only_st = sys.argv[2].split(",") if len(sys.argv) > 2 and sys.argv[2] != "all" else list(STAGES)
    only_ds = sys.argv[3].split(",") if len(sys.argv) > 3 and sys.argv[3] != "all" else DATASETS
    only_sig = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] != "all" else SIGNALS
    for ds in only_ds:
        for sname in only_sig:
            for stname in only_st:
                if skip(stname, sname):
                    continue
                st = STAGES[stname]
                data = {}
                for sym in st["syms"]:
                    bars, sg, fu = load(sym, ds, sname)
                    ent, ext = sig_arrays(sg, sname, st["side"])
                    data[sym] = (bars, ent, ext, fu)
                if len(st["syms"]) == 1:
                    sym = st["syms"][0]
                    bars, ent, ext, fu = data[sym]
                    a, ident_t = run_single(bars, ent, ext, fu, st, path, sym)
                else:
                    # sync_admission variant: the synchronous view was reconstructed and asserted == the kernel's view in run_portfolio, so the
                    # time-synchronous counterfactual run is the same run (same trades / equity / decisions) -> written from this one run
                    a, ident_t = run_portfolio(data, st, path)
                    sy = dict(a)
                    sy["path"], sy["variant"] = path, "sync_admission"
                    json.dump(sy, open(os.path.join(OUT, f"nora_{ds}_{sname}_{stname}_{path}_sync.json"), "w"))
                a["tracker_eq_manager_bit_identical"] = ident_t    # key name kept for ext_compare.py; now: SlotDriver == RefPositionTracker (single) / per-bar == chunked KernelBook (portfolio)
                a["path"] = path
                json.dump(a, open(os.path.join(OUT, f"nora_{ds}_{sname}_{stname}_{path}.json"), "w"))
                print(ds, sname, stname, path, "trades", len(a["trades"]), "final", round(a["final_equity"], 4), "slot/kernel==ref/chunked", ident_t, flush=True)


if __name__ == "__main__":
    main()
