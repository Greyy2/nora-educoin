"""Nora side of the extended differential test (S4-S8): production execution (PositionTracker == kernel path AND PositionManager+SimVenue
event path; Runner for the portfolio stage) bar by bar on the exported bars/signals. Writes out/ext/nora_<ds>_<signal>_<stage>_<path>.json.
Run from nora/: PYTHONDONTWRITEBYTECODE=1 backend/utils/ops/run_limited.sh --no-lock -- test/scripts/nautilus_diff/ext_run_nora.py [ohlc|adaptive] [stages,..] [datasets,..] [signals,..]
"""
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ext_common import skip, CAPITAL, DATASETS, MAKER, OUT, SIGNALS, STAGES, SYMS, TAKER  # noqa: E402

from backend.core.execute.account import Account                      # noqa: E402
from backend.core.execute.manager import PositionManager              # noqa: E402
from backend.core.execute.models import PositionType                  # noqa: E402
from backend.core.execute.runner import Runner                        # noqa: E402
from backend.core.execute.sim_venue import SimVenue                   # noqa: E402
from backend.core.execute.tracker import PositionTracker              # noqa: E402
from backend.core.params.schema import StrategyParams                 # noqa: E402


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


def pos_row(p, orders=()):
    return {"sym": p.symbol, "fills": [[int(o.order_time), float(o.order_price), float(o.qty), float(o.fee_usd), str(o.liquidity)]
                                       for o in orders if o.position_id == p.result_id],
            "enter_time": int(p.enter_time), "enter_price": float(p.enter_price), "close_time": int(p.close_time),
            "close_price": float(p.close_price), "qty": float(p.qty), "avg_price": float(p.avg_price),
            "pnl": float(p.real_pnl), "fees": float(p.fees_usd), "funding": float(p.funding_usd or 0.0), "reason": str(p.close_reason),
            "status": int(p.status), "entry_equity": float(p.entry_equity), "layers": int(p.layers or 1),
            "lev": float(p.leverage_used)}


def load(sym, ds, sname):
    bars = pd.read_csv(os.path.join(OUT, f"bars_{sym}_{ds}.csv"))
    sg = pd.read_csv(os.path.join(OUT, f"signals_{sym}.csv"))
    fu = pd.read_csv(os.path.join(OUT, f"funding_{sym}.csv"))
    return bars, sg, fu


def sig_arrays(sg, sname, side):
    up, dn = sg[sname + "_up"].values, sg[sname + "_dn"].values
    return (up, dn) if side == "L" else (dn, up)           # (entry, exit)


def run_single(bars, ent, ext, fu, st, mode, path, sym="BTC"):
    p = make_params(st, path)
    pt = PositionType.LONG if st["side"] == "L" else PositionType.SHORT
    tr = PositionTracker(0, 0, sym, "L", p, pt, CAPITAL)
    if mode == "tracker":
        actor, acct = tr, tr.ledger
    else:
        acct = Account(CAPITAL)
        actor = PositionManager(tr, SimVenue(), slot=0, account=acct)
    ft = fu.funding_time.values if st.get("fund") else []
    fr = fu.rate.values if st.get("fund") else []
    fi, rows, fund_log = 0, [], []
    for t, o, h, l, c, en, ex in zip(bars.open_time, bars.open, bars.high, bars.low, bars.close, ent, ext):
        t = int(t)
        while fi < len(ft) and ft[fi] <= t:                 # same as kernel / Runner: funding due <= bar open, paid at the open price
            pay = actor.apply_funding(float(fr[fi]), float(o), int(ft[fi]))
            if pay:
                fund_log.append([t, int(ft[fi]), float(fr[fi]), float(o), float(pay)])
            fi += 1
        pos = actor.on_bar(t, float(o), float(h), float(l), float(c), entry_signal=bool(en), stop_signal=bool(ex))
        if pos is not None:
            rows.append(pos_row(pos, actor.orders))
    return {"trades": rows, "final_equity": float(acct.equity), "open_at_end": bool(actor.is_open),
            "dca_rejected": int(getattr(actor, "dca_rejected", 0)), "funding_log": fund_log}


def run_portfolio(data, st, mode, path, sync=False):
    """data[sym] = (bars, ent, ext, fu). Runner = the production portfolio loop (admit_entry, shared Account, gross from last_close).
    Harness-level instrumentation (backend untouched): `runner.admit_entry` is wrapped to log, for every admission decision, BOTH views of the
    same history: the Nora view (what Runner passes: earlier symbols have processed their WHOLE bar t, marks of earlier symbols = close[t]) and
    the time-synchronous view of an exchange/Nautilus (state at the open of bar t: earlier symbols' open-of-bar exits and entries done, their
    intrabar SL/TP/trailing of bar t NOT yet happened, every mark = close[t-1], equity without those intrabar results).
    sync=True returns the synchronous view to Runner instead (counterfactual: Nora with look-ahead-free admission; sizing equity inside the tracker
    still sees earlier symbols' intrabar PnL)."""
    import backend.core.execute.runner as runner_mod
    p = make_params(st, path)
    acct = Account(CAPITAL)
    books, venue = [], (SimVenue() if mode == "manager" else None)
    slot = 0
    for sym in st["syms"]:
        tr = PositionTracker(0, 0, sym, "L", p, PositionType.LONG, CAPITAL)
        if mode == "tracker":
            tr.ledger = acct
            tr.capital = acct.initial
            actor = tr
        else:
            actor = PositionManager(tr, venue, slot=slot, account=acct)
        slot += 1
        books.append({"symbol": sym, "entries": [{"strategy": "S", "side": "LONG", "tracker": actor}]})
    risk = dict(st["port"], kill_switch_dd_pct=0.0)
    rows, step_closed = [], []
    syms = st["syms"]
    actors = [b["entries"][0]["tracker"] for b in books]
    cur = {"t": 0, "S0": None, "queue": [], "decisions": []}

    def collect(sym, e, pos, low, high):
        rows.append(pos_row(pos, e["tracker"].orders))
        step_closed.append((sym, pos))

    real_admit = runner_mod.admit_entry

    def admit(n_open, per, equity, peak, gross, open_risk, max_pos, max_per, cap, mor=0.0, ddt=0.0, ddf=0.25):
        X = cur["queue"].pop(0)
        ox, S0, t = syms.index(X), cur["S0"], cur["t"]
        adm_n = real_admit(n_open, per, equity, peak, gross, open_risk, max_pos, max_per, cap, mor, ddt, ddf)
        n_a, gross_a = 0, 0.0
        for k, y in enumerate(syms):
            if k < ox:
                kept = S0["open"][y] and not S0["pend_exit"][y]
                q_ent = actors[k].qty if (actors[k].is_open and actors[k].entry_time == t) else 0.0
                for sym_, pos in step_closed:                   # entered at this open and already closed intrabar (SL/TP in the same bar)
                    if sym_ == y and pos.enter_time == t:
                        q_ent = pos.qty
                entered = q_ent > 0
                is_open, q = kept or entered, (S0["qty"][y] if kept else q_ent)
            else:
                is_open, q = S0["open"][y], S0["qty"][y]
            if is_open:
                n_a += 1
                gross_a += q * S0["last_close"][y]
        intrabar = sum(pos.real_pnl for sym_, pos in step_closed if syms.index(sym_) < ox and not str(pos.close_reason).startswith(("Tín hiệu", "Hết")))
        eq_a = equity - intrabar
        if not (n_a < int(max_pos) and per < int(max_per)):
            gross_a = 0.0
        adm_a = real_admit(n_a, per, eq_a, peak, gross_a, open_risk, max_pos, max_per, cap, mor, ddt, ddf)
        cur["decisions"].append({"t": t, "sym": X, "nora": {"n_open": n_open, "gross": gross, "eq": equity, "can": adm_n.can_open, "mnn": adm_n.max_new_notional},
                                 "sync": {"n_open": n_a, "gross": gross_a, "eq": eq_a, "can": adm_a.can_open, "mnn": adm_a.max_new_notional}})
        return adm_a if sync else adm_n

    runner_mod.admit_entry = admit
    try:
        runner = Runner(venue, acct, books, risk, 0, collect=collect, initial_capital=CAPITAL)
        n = len(data[syms[0]][0])
        cols = {s: {k: data[s][0][k].values for k in ("open_time", "open", "high", "low", "close")} for s in syms}
        for i in range(n):
            t = int(cols[syms[0]]["open_time"][i])
            bars = {s: (float(cols[s]["open"][i]), float(cols[s]["high"][i]), float(cols[s]["low"][i]), float(cols[s]["close"][i])) for s in syms}
            sig = {s: [{"match": bool(data[s][1][i]), "stop": bool(data[s][2][i]), "vol": None}] for s in syms}
            cur["t"] = t
            cur["S0"] = {"open": {s: a.is_open for s, a in zip(syms, actors)}, "qty": {s: a.qty for s, a in zip(syms, actors)},
                         "pend_exit": {s: a.pending_exit for s, a in zip(syms, actors)},
                         "last_close": {s: runner.last_close[k] for k, s in enumerate(syms)}}
            cur["queue"] = [s for s, a in zip(syms, actors) if a.pending_entry and not a.is_open]
            del step_closed[:]
            runner.step_bar(t, bars, sig)
    finally:
        runner_mod.admit_entry = real_admit
    return {"trades": rows, "final_equity": float(acct.equity), "rejected_for_risk": runner.rejected_for_risk, "decisions": cur["decisions"],
            "open_at_end": [b["symbol"] for b in books if b["entries"][0]["tracker"].is_open]}


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
                    a = run_single(bars, ent, ext, fu, st, "tracker", path, sym)
                    b = run_single(bars, ent, ext, fu, st, "manager", path, sym)
                else:
                    a, b = run_portfolio(data, st, "tracker", path), run_portfolio(data, st, "manager", path)
                    sy = run_portfolio(data, st, "tracker", path, sync=True)
                    sy["path"], sy["variant"] = path, "sync_admission"
                    json.dump(sy, open(os.path.join(OUT, f"nora_{ds}_{sname}_{stname}_{path}_sync.json"), "w"))
                ident_t = json.dumps(a["trades"], sort_keys=True) == json.dumps(b["trades"], sort_keys=True) and a["final_equity"] == b["final_equity"]
                a["tracker_eq_manager_bit_identical"] = ident_t
                a["path"] = path
                json.dump(a, open(os.path.join(OUT, f"nora_{ds}_{sname}_{stname}_{path}.json"), "w"))
                print(ds, sname, stname, path, "trades", len(a["trades"]), "final", round(a["final_equity"], 4), "tracker==manager", ident_t, flush=True)


if __name__ == "__main__":
    main()
