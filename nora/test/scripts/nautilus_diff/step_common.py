"""Nora side of the Nautilus differential tests on the SINGLE kernel engine (P9.4b T5).
Single slot  : SlotDriver (backend.core.backtest, slot_bar/slot_funding on arrays) vs RefPositionTracker (test/reference_engine.py, frozen Python oracle).
Portfolio    : KernelBook (the paper/live step engine), stepped bar by bar with the admission trace (ADM rows) switched on.
No PositionTracker / PositionManager / SimVenue / Runner / PaperBook is imported here.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))       # test/ -> reference_engine
from reference_engine import RefPositionTracker                              # noqa: E402

from backend.core import backtest as bt                                    # noqa: E402
from backend.core.backtest import KernelBook, SlotDriver                   # noqa: E402
from backend.core.models import PositionType                       # noqa: E402
from backend.core.position_size import SlotSpec                                 # noqa: E402
from backend.core.position_size import admit_entry                         # noqa: E402


def pos_row(p, orders_by_pos, ext=False):
    """ext=False: S1-S3 layout; ext=True: extended layout (sym first, funding + lev added)."""
    fills = [[int(o.order_time), float(o.order_price), float(o.qty), float(o.fee_usd), str(o.liquidity)] for o in orders_by_pos.get(p.result_id, [])]
    r = {"sym": p.symbol} if ext else {}
    r.update({"fills": fills, "enter_time": int(p.enter_time), "enter_price": float(p.enter_price), "close_time": int(p.close_time),
              "close_price": float(p.close_price), "qty": float(p.qty), "avg_price": float(p.avg_price), "pnl": float(p.real_pnl),
              "fees": float(p.fees_usd)})
    if ext:
        r["funding"] = float(p.funding_usd or 0.0)
    r.update({"reason": str(p.close_reason), "status": int(p.status), "entry_equity": float(p.entry_equity), "layers": int(p.layers or 1)})
    if ext:
        r["lev"] = float(p.leverage_used)
    return r


def _by_pos(orders):
    d = {}
    for o in orders:
        d.setdefault(o.position_id, []).append(o)
    return d


def run_single(params, side, sym, cols, ent, ext, capital, fund_t=(), fund_r=(), ext_layout=False):
    """Feed the same bars/signals/funding to the SlotDriver (result) and the RefPositionTracker (oracle).
    cols = (open_time, open, high, low, close). Returns (result dict, bit_identical)."""
    pt = PositionType.LONG if side == "L" else PositionType.SHORT
    ref = RefPositionTracker(0, 0, sym, "L", params, pt, capital)
    drv = SlotDriver([SlotSpec(0, 0, sym, "L", params, pt, capital)], meta=[(sym, "")])
    out = {}
    for name, actor, ledger in (("ref", ref, ref.ledger), ("slot", drv[0], drv.ledger)):
        fi, closed, fund_log = 0, [], []
        for t, o, h, l, c, en, ex in zip(*cols, ent, ext):
            t = int(t)
            while fi < len(fund_t) and fund_t[fi] <= t:         # funding due <= bar open, paid at the open price (kernel phase 1)
                pay = actor.apply_funding(float(fund_r[fi]), float(o))
                if pay:
                    fund_log.append([t, int(fund_t[fi]), float(fund_r[fi]), float(o), float(pay)])
                fi += 1
            pos = actor.on_bar(t, float(o), float(h), float(l), float(c), entry_signal=bool(en), stop_signal=bool(ex))
            if pos is not None:
                closed.append(pos)
            # the oracle keeps pending funding state in the same bar order, nothing else to do
        fi = 0
        orders = _by_pos(actor.orders)
        out[name] = {"trades": [pos_row(p, orders, ext_layout) for p in closed], "final_equity": float(ledger.equity),
                     "open_at_end": bool(actor.is_open), "dca_rejected": int(getattr(actor, "dca_rejected", 0)), "funding_log": fund_log}
    ident = json.dumps(out["ref"], sort_keys=True) == json.dumps(out["slot"], sort_keys=True)
    return out["slot"], ident


# ── portfolio ────────────────────────────────────────────────────────────────
def _is_open_phase_exit(reason):
    return str(reason).startswith(("Tín hiệu", "Hết"))


def _close(a, b, tol=1e-9):
    return a == b or abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def new_book(strategies, syms, capital, risk, adm_capacity):
    return KernelBook(strategies, list(syms), "1m", capital, dict(risk), trade_start=0, record_full=True, record_events=True,
                      adm_capacity=adm_capacity)


def run_portfolio(strategies, syms, capital, risk, data, with_sync=True):
    """data[sym] = (bars DataFrame with open_time/open/high/low/close, entry array, exit array). KernelBook stepped one bar at a time.
    Returns the result dict {trades, final_equity, rejected_for_risk, decisions, open_at_end} and the 'chunked == per-bar' bit identity.
    decisions: one row per admission check from the kernel ADM trace (t, k, n_open, per_b, eq, gross, can_open, max_new) in the old key order;
    the 'sync' view is RECONSTRUCTED here from the book state before the bar (time-synchronous exchange view: state at the open of bar t, earlier
    symbols' open-of-bar exits/entries done, their intrabar SL/TP of bar t not yet happened, marks = close[t-1]) and asserted equal to the
    kernel's own view (the kernel admits at the open of the bar, so Nora == a look-ahead-free exchange)."""
    n = len(data[syms[0]][0])
    cols = {s: {k: data[s][0][k].values for k in ("open_time", "open", "high", "low", "close")} for s in syms}
    kb = new_book(strategies, syms, capital, risk, adm_capacity=4 * n * len(syms) + 16)
    max_pos, max_per, cap = int(risk["max_positions"]), int(risk["max_per_symbol"]), float(risk["max_gross_exposure"])
    for key in ("max_open_risk_pct", "dd_throttle_pct"):
        assert not risk.get(key), "sync reconstruction covers max_positions / max_per_symbol / max_gross_exposure only"
    feed = []
    for i in range(n):
        t = int(cols[syms[0]]["open_time"][i])
        bars = {s: (float(cols[s]["open"][i]), float(cols[s]["high"][i]), float(cols[s]["low"][i]), float(cols[s]["close"][i])) for s in syms}
        sig = {s: [{"match": bool(data[s][1][i]), "stop": bool(data[s][2][i]), "vol": None}] for s in syms}
        feed.append((t, bars, sig, None))
    decisions, n_adm, n_ev = [], 0, 0
    for t, bars, sig, fu in feed:
        open0 = [bool(kb.I[k, bt.I_OPEN]) for k in range(kb.nt)]
        qty0 = [float(kb.F[k, bt.F_QTY]) for k in range(kb.nt)]
        lc0 = kb.last_close
        eq0 = kb.ledger.equity
        closed = kb.step_bar(t, bars, sig, fu)
        adm = kb.adm
        rows, n_adm = adm[n_adm:], len(adm)
        entries = {e["slot"]: e["qty"] for e in kb.events[n_ev:] if e["kind"] == "entry" and e["t"] == t}
        n_ev = len(kb.events)
        for r in rows:
            k, ox = int(r[bt.AD_K]), int(r[bt.AD_K])
            nora = {"n_open": int(r[bt.AD_NOPEN]), "gross": float(r[bt.AD_GROSS]), "eq": float(r[bt.AD_EQ]), "can": bool(r[bt.AD_CAN]),
                    "mnn": float(r[bt.AD_MAXNEW])}
            if with_sync:
                n_a, gross_a, eq_a = 0, 0.0, eq0
                for y in range(kb.nt):
                    if y < ox:
                        xo = [p for p in closed if p["symbol"] == kb.slots[y]["symbol"] and p["close_time"] == t
                              and p["enter_time"] < t and _is_open_phase_exit(p["reason"])]
                        eq_a += sum(p["pnl"] for p in xo)
                        kept = open0[y] and not xo
                        q_ent = entries.get(y, 0.0)
                        is_open, q = kept or q_ent > 0, (qty0[y] if kept else q_ent)
                    else:
                        is_open, q = open0[y], qty0[y]
                    if is_open:
                        n_a += 1
                        gross_a += q * lc0[kb.slots[y]["book"]]
                per = int(r[bt.AD_PERB])
                if not (n_a < max_pos and per < max_per):
                    gross_a = 0.0
                adm_a = admit_entry(n_a, per, eq_a, eq_a, gross_a, 0.0, max_pos, max_per, cap)
                sync = {"n_open": n_a, "gross": gross_a, "eq": eq_a, "can": adm_a.can_open, "mnn": adm_a.max_new_notional}
                bad = [f for f in nora if not (_close(nora[f], sync[f], 1e-9) if isinstance(nora[f], float) else nora[f] == sync[f])]
                # eq: the reconstruction uses the 6-decimal rounded trade pnl -> absolute 1e-5 slack
                bad = [f for f in bad if not (f == "eq" and abs(nora[f] - sync[f]) < 1e-5)]
                assert not bad, f"t={t} slot={k}: kernel admission view != reconstructed synchronous view in {bad}: nora={nora} sync={sync}"
            decisions.append({"t": int(r[bt.AD_T]), "sym": kb.slots[k]["symbol"], "nora": nora, "sync": dict(nora)})
    assert not kb.G[bt.G_OVF]
    pos, orders = kb.full_objects()
    ob = _by_pos(orders)
    res = {"trades": [pos_row(p, ob, True) for p in pos], "final_equity": float(kb.ledger.equity), "rejected_for_risk": int(kb.rejected_for_risk),
           "decisions": decisions, "open_at_end": [p["symbol"] for p in kb.positions()]}
    # self-check: the same history fed in ONE chunk gives the same result (per-bar stepping == step_bars)
    k2 = new_book(strategies, syms, capital, risk, adm_capacity=0)
    k2.step_bars(feed)
    pos2, orders2 = k2.full_objects()
    ob2 = _by_pos(orders2)
    ident = (json.dumps([pos_row(p, ob2, True) for p in pos2], sort_keys=True) == json.dumps(res["trades"], sort_keys=True)
             and float(k2.ledger.equity) == res["final_equity"] and int(k2.rejected_for_risk) == res["rejected_for_risk"])
    return res, ident
