"""Trade-by-trade comparison Nora vs Nautilus + mismatch classification.
Usage: ~/.venvs/nora/bin/python test/scripts/nautilus_diff/compare.py [inst=fine] [suffix='']
Classes: a same-bar ambiguity | b gap at open | c rounding/precision | d entry timing open-vs-close (raw only) |
         x cascade (downstream of an earlier classified divergence) | e UNEXPLAINED
"""
import json
import os
import sys
from collections import Counter

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import CAPITAL, SIGNALS, STAGES  # noqa: E402

OUT = os.path.join(HERE, "out")
H = 3_600_000
PREC = {"fine": (1e-8, 1e-8), "okx": (0.1, 1e-4)}      # (tick, lot)
REASON = {"Stop-loss": "SL", "Take-profit": "TP", "Tín hiệu": "SIG", "End of": "END"}


def reason_n(s):
    for k, v in REASON.items():
        if s.startswith(k):
            return v
    return s


def load(path):
    return json.load(open(path))


def rel(a, b):
    return abs(a - b) / max(abs(b), 1e-300)


def compare(inst, ds, sname, stname, suffix, bars):
    st = STAGES[stname]
    tick, lot = PREC[inst]
    nn = load(os.path.join(OUT, f"nora_{ds}_{sname}_{stname}{suffix}.json"))
    na = load(os.path.join(OUT, f"nautilus_{inst}_{ds}_{sname}_{stname}{suffix}.json"))
    bar0 = int(bars.open_time.iloc[0])
    idx = {int(t): i for i, t in enumerate(bars.open_time)}
    sl, tp = st.get("sl", 0.0), st.get("tp", 0.0)
    for t in na["trades"]:                                   # Nautilus SL/TP ticks are stamped with the bar close -> use bar open time
        t["reason"] = t["reason"]
        if t["reason"] in ("SL", "TP"):
            t["close_time"] = bar0 + t["bar_exit"] * H
    N = {t["enter_time"]: dict(t, r=reason_n(t["reason"])) for t in nn["trades"]}
    A = {t["enter_time"]: dict(t, r=t["reason"]) for t in na["trades"]}
    rows, cls = [], Counter()
    detail_e = []
    first_div_end = None            # latest close time (either engine) of a diverged trade -> cascade window
    exact = 0
    for et in sorted(set(N) | set(A)):
        n, a = N.get(et), A.get(et)
        row = {"enter_time": et, "cls": None, "note": ""}
        if n is None or a is None:
            who = "nautilus-only" if n is None else "nora-only"
            orphan = None
            if n is None:       # f: entry price = a DCA level of a trade that Nautilus closed in the bar that ends at this timestamp
                for pe, pn in N.items():
                    pa = A.get(pe)
                    if pa is not None and pa["close_time"] + H == et or (pa is not None and pa.get("bar_exit") is not None and bar0 + (pa["bar_exit"] + 1) * H == et):
                        px = pn["enter_price"]
                        for k_, s_ in enumerate(st.get("dca_steps", [])):
                            px *= 1 - s_ / 100
                            if rel(a_enter := A[et]["enter_price"], px) < 1e-3:
                                orphan = (pe, k_ + 1)
                if orphan is not None:
                    row.update(cls="f", note=f"orphan DCA layer {orphan[1]} of the trade entered {orphan[0]} filled after its exit in the same bar; Nautilus did not cancel the ladder in time (artifact, not replicated)")
                    rows.append(row); cls["f"] += 1
                    first_div_end = max(first_div_end or 0, A[et]["close_time"])
                    continue
            if first_div_end is not None and et <= first_div_end + 3 * H:
                row.update(cls="x", note=f"{who} trade inside cascade window of an earlier classified divergence")
            else:
                row.update(cls="e", note=f"{who} trade, no preceding divergence")
            rows.append(row); cls[row["cls"]] += 1
            continue
        i_n, i_a = idx[n["close_time"]] if n["close_time"] in idx else None, idx.get(a["close_time"])
        fields = []
        if rel(a["enter_price"], n["enter_price"]) > max(1e-9, tick / n["enter_price"] / 2 + 1e-12):
            fields.append("enter_price")
        if a["close_time"] != n["close_time"]:
            fields.append("close_time")
        if a["r"] != n["r"]:
            fields.append("reason")
        lot_shift = (a.get("layers", 1) * lot / 2 / a["qty"]) * 0.02 if inst == "okx" else 0.0     # avg shift caused by per-layer lot rounding
        if "close_time" not in fields and rel(a["close_price"], n["close_price"]) > max(1e-9, tick / n["close_price"] / 2 + 1e-12) + lot_shift:
            fields.append("close_price")
        nq_n, nq_a = n["qty"] * n["avg_price"] / n["entry_equity"], a["qty"] * a["avg_price"] / a["entry_equity"]
        qty_rel = rel(nq_a, nq_n)
        qty_tol = lot / 2 * max(1, a.get("layers", 1)) / a["qty"] + 1e-9
        rn, ra = n["pnl"] / n["entry_equity"], a["pnl"] / a["entry_equity"]
        pred = rn * nq_a / nq_n                           # Nora return rescaled to Nautilus' (rounded) notional fraction
        price_slack = (tick / n["enter_price"] + tick / n["close_price"] + 2 * lot_shift) * nq_a + 1e-9
        pnl_resid = abs(ra - pred)
        if not fields and pnl_resid > price_slack:
            fields.append("pnl")
        row.update(qty_rel_diff=qty_rel, pnl_ret_nora=rn, pnl_ret_naut=ra, pnl_resid=pnl_resid,
                   nora=[n["enter_price"], n["close_time"], n["close_price"], n["r"]],
                   naut=[a["enter_price"], a["close_time"], a["close_price"], a["r"]])
        if not fields:
            exact += 1
            row["cls"] = "match"
            if qty_rel > 1e-12:
                row["note"] = "match (qty rounded to lot)" if qty_rel <= qty_tol else f"QTY beyond lot rounding {qty_rel:.2e}"
                if qty_rel > qty_tol:
                    row["cls"] = "e"
            rows.append(row); cls[row["cls"]] += 1
            continue
        # ---- classify ----
        t0 = min(n["close_time"], a["close_time"])
        b = bars.iloc[idx[t0]] if t0 in idx else None
        avg = n["avg_price"]
        sl_lv, tp_lv = avg * (1 - sl / 100) if sl else None, avg * (1 + tp / 100) if tp else None
        both = b is not None and sl and tp and b.low <= sl_lv and b.high >= tp_lv
        dca_tp = False
        if b is not None and tp and st.get("dca_steps") and b.high >= tp_lv:
            px, lv = n["enter_price"], []
            for s_ in st["dca_steps"]:
                px *= 1 - s_ / 100
                lv.append(px)
            dca_tp = any(b.low <= x for x in lv)
        gap_exit = False
        if b is not None:
            lv_ = [x for x in (sl_lv, tp_lv) if x]
            gap_exit = any((b.open <= x if x == sl_lv else b.open >= x) for x in lv_)
        # stale-SL test: Nautilus SL fired at the level of the avg BEFORE a DCA fill that happened in the same bar
        stale_sl = False
        if a["r"] == "SL" and sl and a.get("fills"):
            ex = a["fills"][-1]
            buys = [f for f in a["fills"][:-1] if f["side"] == "BUY"]
            same_bar = [k for k, f in enumerate(buys) if f["kind"] == "DCA" and f["bar"] == ex["bar"] and f["t"] == ex["t"]]
            if same_bar:
                k = same_bar[0]
                pre = buys[:k]
                avg_pre = sum(f["px"] * f["qty"] for f in pre) / sum(f["qty"] for f in pre)
                stale_sl = rel(a["close_price"], avg_pre * (1 - sl / 100)) < max(1e-9, tick / a["close_price"])
        # DCA-gap test: Nora fills a layer at the bar OPEN when the open gapped through the limit; Nautilus fills at the limit price
        gap_layer = False
        a_buys = [f for f in a.get("fills", []) if f["side"] == "BUY"]
        for nf, af in zip(n.get("fills", [])[:-1], a_buys):
            if rel(af["px"], nf[1]) > 1e-9:
                bt = idx.get(nf[0])
                if bt is not None and abs(nf[1] - bars.open.iloc[bt]) < 1e-6 and nf[1] < af["px"]:
                    gap_layer = True
                break
        entry_gap = rel(a["enter_price"], n["enter_price"])
        if "enter_price" in fields and ds == "raw":
            c, note = "d", f"entry price open[t+1]={n['enter_price']} vs close[t]={a['enter_price']}"
        elif set(fields) <= {"close_price", "pnl"} and ds == "raw" and rel(a["close_price"], n["close_price"]) <= entry_gap * 1.5 + 1e-9:
            c, note = "d", "exit price shifted proportionally to the entry-price gap (levels derive from avg)"
        elif set(fields) <= {"close_price", "pnl"} and n["r"] == "SIG" and ds == "raw":
            c, note = "d", "signal exit: Nora fills at next open, Nautilus at close"
        elif stale_sl:
            c = "a"
            note = ("same L-tick DCA fill(s) + stale SL: both engines exit at the old SL level (placed from the pre-DCA avg) "
                    f"{a['close_price']:.4f} (since 2026-10-06 Nora keeps the stale SL too); Nautilus also fills the lower layer(s) in the same "
                    f"tick before the SL ({a.get('layers', 1)} layers vs Nora {n.get('layers', 1)}), Nora stops first in the descending sweep")
        elif gap_layer:
            c = "b"
            note = (f"DCA limit gapped through at bar open: Nora fills the layer at open ({nf[1]}), Nautilus at its limit "
                    f"price ({af['px']}); qty/avg/TP/SL levels then differ")
        elif ("reason" in fields or "close_time" in fields) and (both or dca_tp):
            c = "a"
            note = (f"both SL&TP reachable in bar {pd.to_datetime(t0, unit='ms')}: Nora={n['r']}@{n['close_time']}, "
                    f"Nautilus={a['r']}@{a['close_time']}" if both else
                    f"DCA & TP reachable in same bar: Nora={n['r']}, Nautilus={a['r']}")
        elif set(fields) == {"close_price"} and gap_exit:
            c, note = "b", "gap at open through exit level"
        elif set(fields) <= {"pnl"} and "pnl" in fields and ds != "raw":
            c, note = "e", f"pnl residual {pnl_resid:.3e} (> rounding slack {price_slack:.3e}) with equal trades"
        else:
            c, note = "e", f"fields={fields}"
        # a diverged exit opens a cascade window (the next trades may enter on different bars)
        if c in ("a", "b", "d") or "close_time" in fields:
            first_div_end = max(n["close_time"], a["close_time"]) if first_div_end is None else max(first_div_end, n["close_time"], a["close_time"])
        row.update(cls=c, note=note, fields=fields)
        if c == "e":
            detail_e.append(row)
        rows.append(row); cls[c] += 1
    # final equity: realised equity after the last CLOSED trade (Nautilus balance also includes the entry fee of a still-open position)
    fe_n = nn["trades"] and (CAPITAL + sum(t["pnl"] for t in nn["trades"])) or CAPITAL
    fe_a = na["trades"][-1]["equity_after"] if na["trades"] else CAPITAL
    return {"inst": inst, "dataset": ds, "signal": sname, "stage": stname, "trades_nora": len(N), "trades_naut": len(A),
            "matched_pairs": sum(1 for e in N if e in A), "exact_matches": exact, "classes": dict(cls),
            "final_equity_nora": fe_n, "final_equity_naut": fe_a, "final_equity_diff": fe_a - fe_n,
            "final_equity_diff_pct": (fe_a / fe_n - 1) * 100, "nora_engine_paths_bit_identical": nn.get("tracker_eq_manager_bit_identical"),
            "unexplained": detail_e, "rows": rows}


def main():
    inst = sys.argv[1] if len(sys.argv) > 1 else "fine"
    suffix = sys.argv[2] if len(sys.argv) > 2 else ""
    res = []
    for ds in ("aligned", "raw", "gapped"):
        p = os.path.join(OUT, f"bars_{ds}.csv")
        if not os.path.exists(p):
            continue
        bars = pd.read_csv(p)
        for sname in SIGNALS:
            for stname in STAGES:
                if not os.path.exists(os.path.join(OUT, f"nautilus_{inst}_{ds}_{sname}_{stname}{suffix}.json")):
                    continue
                res.append(compare(inst, ds, sname, stname, suffix, bars))
    json.dump(res, open(os.path.join(OUT, f"results_{inst}{suffix}.json"), "w"), indent=1, default=str)
    slim = [{k: v for k, v in r.items() if k not in ("rows", "unexplained")} | {
        "unexplained": r["unexplained"] + [x for x in r["rows"] if x["cls"] == "e" and x not in r["unexplained"]],
        "non_exact": [{k: x.get(k) for k in ("enter_time", "cls", "note", "nora", "naut")} for x in r["rows"] if x["cls"] not in ("match",)]}
        for r in res]
    json.dump(slim, open(os.path.join(HERE, f"results_{inst}{suffix}.json"), "w"), indent=1, default=str)
    print("| dataset | signal | stage | trades N/A | exact | a | b | c(rounding only) | d | f | x | e | final eq Nora | final eq Naut | diff % |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in res:
        c = r["classes"]
        print(f"| {r['dataset']} | {r['signal']} | {r['stage']} | {r['trades_nora']}/{r['trades_naut']} | {r['exact_matches']} | "
              f"{c.get('a', 0)} | {c.get('b', 0)} | {sum(1 for x in r['rows'] if 'rounded' in x['note'])} | {c.get('d', 0)} | {c.get('f', 0)} | {c.get('x', 0)} | "
              f"{c.get('e', 0)} | {r['final_equity_nora']:.2f} | {r['final_equity_naut']:.2f} | {r['final_equity_diff_pct']:+.4f} |")
    for r in res:
        for e in r["unexplained"]:
            print("UNEXPLAINED", r["dataset"], r["signal"], r["stage"], e["enter_time"], e["note"], e.get("nora"), e.get("naut"))
        for x in r["rows"]:
            if x["cls"] == "e" and x not in r["unexplained"]:
                print("UNEXPLAINED", r["dataset"], r["signal"], r["stage"], x["enter_time"], x["note"])


if __name__ == "__main__":
    main()
