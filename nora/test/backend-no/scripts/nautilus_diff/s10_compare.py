"""S10 comparison Nora (real engine) vs Nautilus: trade-by-trade (symbol, entry time, exit time, reason, entry/exit price, qty, pnl, ATR unit), realized
equity, open-at-end, plus mechanism checks on Nora's own trades (SL/TP fill at the level computed from avg and unit; trailing fills at peak*(1-trail) with peak
re-derived from the 1m path; timeout exits exactly timeout minutes after entry; same-bar peak-raise cases counted).
Usage: ~/.venvs/nora/bin/python test/scripts/nautilus_diff/s10_compare.py [stages|all]   -> s10_results.json, exit 1 on mismatch.
Tolerances as S9: price rel 1e-9, qty rel 1e-7, pnl abs 1e-3, final equity abs 1e-2, unit_pct rel 1e-9.
"""
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from s10_common import M, OUT, STAGES, SYMS  # noqa: E402

REASON = {"Stop-loss": "SL", "Take-profit": "TP", "Trailing": "TRAIL", "Hết thời gian": "TO", "End of": "END"}


def reason_n(s):
    for k, v in REASON.items():
        if s.startswith(k):
            return v
    return s


def rel(a, b):
    return abs(a - b) / max(abs(b), 1e-300)


def compare(name):
    st = STAGES[name]
    nn = json.load(open(os.path.join(OUT, f"nora_{name}.json")))
    na = json.load(open(os.path.join(OUT, f"nautilus_{name}.json")))
    bars = {s: pd.read_csv(os.path.join(OUT, f"bars1m_{s}.csv")) for s in SYMS}
    t_first = int(bars[SYMS[0]].open_time.iloc[0])
    for t in na["trades"]:
        t["close_time"] = t_first + t["bar_exit"] * M            # every exit fill is stamped at a bar close tick -> Nora's bar numbering
    N = {(t["sym"], t["enter_time"]): dict(t, r=reason_n(t["reason"])) for t in nn["trades"]}
    A = {(t["sym"], t["enter_time"]): dict(t, r=t["reason"]) for t in na["trades"]}
    rows, bad = [], []
    for key in sorted(set(N) | set(A), key=lambda k: (k[1], k[0])):
        n, a = N.get(key), A.get(key)
        if n is None or a is None:
            bad.append({"key": list(key), "why": "only in " + ("nautilus" if n is None else "nora")})
            continue
        d = {"sym": key[0], "enter": key[1], "close_nora": n["close_time"], "close_naut": a["close_time"], "reason": n["r"], "reason_naut": a["r"],
             "d_enter_px": rel(n["enter_price"], a["enter_price"]), "d_close_px": rel(n["close_price"], a["close_price"]), "d_qty": rel(n["qty"], a["qty"]),
             "d_pnl": abs(n["pnl"] - a["pnl"]), "d_unit": rel(n["unit_pct"], a["unit_pct"]) if n["unit_pct"] else abs(a["unit_pct"]),
             "nora_pnl": n["pnl"], "naut_pnl": a["pnl"], "enter_px": n["enter_price"], "close_px_nora": n["close_price"], "close_px_naut": a["close_price"]}
        ok = (n["close_time"] == a["close_time"] and n["r"] == a["r"] and d["d_enter_px"] < 1e-9 and d["d_close_px"] < 1e-9 and d["d_qty"] < 1e-7
              and d["d_pnl"] < 1e-3 and d["d_unit"] < 1e-9)
        d["ok"] = bool(ok)
        rows.append(d)
        if not ok:
            bad.append(d)
    eq_n, eq_a = nn["realized_equity"], na["realized_equity_nora_def"]
    open_n = sorted((o["sym"], o["enter_time"]) for o in nn["open_at_end"])
    open_a = sorted((o["sym"], o["enter_time"]) for o in na["open_at_end"])
    # mechanism checks on Nora's trades
    chk = {"sl_at_level": 0, "tp_at_level": 0, "trail_at_level": 0, "trail_peak_same_bar": 0, "timeout_exact": 0, "n_sl": 0, "n_tp": 0, "n_trail": 0, "n_to": 0}
    for t in nn["trades"]:
        r = reason_n(t["reason"])
        u = t["unit_pct"] if st["unit"] == "atr" else 1.0
        avg, b = t["avg_price"], bars[t["sym"]]
        i = (t["close_time"] - t_first) // M
        if r == "SL":
            chk["n_sl"] += 1
            chk["sl_at_level"] += int(abs(t["close_price"] - avg * (1 - st["sl"] * u / 100)) <= 1e-6 * avg)
        elif r == "TP":
            chk["n_tp"] += 1
            chk["tp_at_level"] += int(abs(t["close_price"] - avg * (1 + st["tp"] * u / 100)) <= 1e-6 * avg)
        elif r == "TRAIL":
            chk["n_trail"] += 1
            j0 = (t["enter_time"] - t_first) // M
            peak_prev = float(b.high.iloc[j0:i].max()) if i > j0 else avg                     # peak up to the PREVIOUS bar (what the 1m-emulation uses)
            peak_incl = max(peak_prev, float(b.high.iloc[i]))                                 # Nora ticks h before l inside the exit bar
            lvl_prev, lvl_incl = peak_prev * (1 - st["trail"] * u / 100), peak_incl * (1 - st["trail"] * u / 100)
            chk["trail_at_level"] += int(abs(t["close_price"] - lvl_prev) <= 1e-6 * avg or abs(t["close_price"] - lvl_incl) <= 1e-6 * avg or t["close_price"] >= lvl_prev)
            chk["trail_peak_same_bar"] += int(abs(t["close_price"] - lvl_prev) > 1e-6 * avg and abs(t["close_price"] - lvl_incl) <= 1e-6 * avg)
        elif r == "TO":
            chk["n_to"] += 1
            chk["timeout_exact"] += int(t["close_time"] - t["enter_time"] == st["timeout"] * M)
    return {"stage": name, "cfg": st, "n_nora": len(nn["trades"]), "n_naut": len(na["trades"]), "n_paired_ok": sum(r["ok"] for r in rows), "n_paired": len(rows),
            "unmatched_or_bad": bad, "realized_equity_nora": eq_n, "realized_equity_naut": eq_a, "d_equity": abs(eq_n - eq_a), "open_at_end_nora": open_n,
            "open_at_end_naut": open_a, "checks": chk,
            "match": bool(not bad and abs(eq_n - eq_a) < 1e-2 and open_n == open_a), "trades": rows}


def main():
    only = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] != "all" else list(STAGES)
    out = {}
    print("| stage | trades nora/naut | paired ok | reasons (SL/TP/TRAIL/TO) | realized equity nora | nautilus | d | open@end | MATCH |")
    print("|---|---|---|---|---|---|---|---|---|")
    for name in only:
        r = compare(name)
        out[name] = {k: v for k, v in r.items() if k != "trades"}
        c = r["checks"]
        print(f"| {name} | {r['n_nora']}/{r['n_naut']} | {r['n_paired_ok']}/{r['n_paired']} | {c['n_sl']}/{c['n_tp']}/{c['n_trail']}/{c['n_to']} | "
              f"{r['realized_equity_nora']:.4f} | {r['realized_equity_naut']:.4f} | {r['d_equity']:.2e} | {r['open_at_end_nora']} vs {r['open_at_end_naut']} | {r['match']} |")
        print("   checks", c)
        for b in r["unmatched_or_bad"][:5]:
            print("   BAD", b)
        json.dump(r["trades"], open(os.path.join(OUT, f"s10_trades_{name}.json"), "w"))
    if len(only) == len(STAGES):
        json.dump(out, open(os.path.join(HERE, "s10_results.json"), "w"), indent=1, sort_keys=True)
    return 0 if all(v["match"] for v in out.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
