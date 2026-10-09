"""S9 comparison Nora (real engine, 24h tree on 1m base) vs Nautilus (daily bar on_bar + 1m matching). Trade-by-trade + semantic checks.
Usage: ~/.venvs/nora/bin/python test/scripts/nautilus_diff/s9_compare.py [stages|all] [nora_suffix]   (nora_suffix e.g. "_level" for out/s9/nora_S9a_level.json)
Writes s9_results.json (compare verdict per stage) and prints a markdown report. Exit 1 if any stage does not match within the convention.
Convention (documented in REPORT.md): Nautilus fills at the signal bar close (= last 1m close), Nora at the next 1m open; the S9 data is ALIGNED
(open[t] = close[t-1]) so both are the same price and entry/exit times are the same instant (daily boundary). Tolerances: price rel 1e-9, qty rel 1e-7 (Nautilus rounds qty to the 8dp size increment, class c; the sub-1e-4 USDT equity drift it causes feeds the next sizing),
pnl abs 1e-3 USDT (Nautilus rounds qty to 8dp), final equity abs 1e-2.
"""
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from s9_common import CAPITAL, DAY, M, OUT, STAGES, SYMS  # noqa: E402

REASON = {"Stop-loss": "SL", "Tín hiệu": "SIG", "End of": "END"}


def reason_n(s):
    for k, v in REASON.items():
        if s.startswith(k):
            return v
    return s


def rel(a, b):
    return abs(a - b) / max(abs(b), 1e-300)


def compare(name, suffix=""):
    st = STAGES[name]
    nn = json.load(open(os.path.join(OUT, f"nora_{name}{suffix}.json")))
    na = json.load(open(os.path.join(OUT, f"nautilus_{name}.json")))
    bars = {s: pd.read_csv(os.path.join(OUT, f"bars1m_{s}.csv")) for s in SYMS}
    daily = {s: pd.read_csv(os.path.join(OUT, f"daily_{s}.csv")) for s in SYMS}
    t_first = int(bars[SYMS[0]].open_time.iloc[0])
    for t in na["trades"]:                       # stop fills are stamped at the bar close tick -> the bar open time (Nora numbering)
        if t["reason"] == "SL":
            t["close_time"] = t_first + t["bar_exit"] * M
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
             "d_pnl": abs(n["pnl"] - a["pnl"]), "nora_pnl": n["pnl"], "naut_pnl": a["pnl"], "enter_px": n["enter_price"], "close_px": n["close_price"]}
        ok = (n["close_time"] == a["close_time"] and n["r"] == a["r"] and d["d_enter_px"] < 1e-9 and d["d_close_px"] < 1e-9 and d["d_qty"] < 1e-7 and d["d_pnl"] < 1e-3)
        d["ok"] = bool(ok)
        rows.append(d)
        if not ok:
            bad.append(d)
    eq_n, eq_a = nn["realized_equity"], na["realized_equity_nora_def"]
    open_n = sorted((o["sym"], o["enter_time"]) for o in nn["open_at_end"])
    open_a = sorted((o["sym"], o["enter_time"]) for o in na["open_at_end"])
    # semantic checks (on Nora trades; Nautilus equality is established by the pairing above)
    trades = sorted(nn["trades"], key=lambda t: (t["sym"], t["enter_time"]))
    entries_on_boundary = all(t["enter_time"] % DAY == 0 for t in trades) and all(o[1] % DAY == 0 for o in open_n)
    same_day_reentry = 0
    for s in SYMS:
        ts = [t for t in trades if t["sym"] == s]
        for p, q in zip(ts, ts[1:]):
            if q["enter_time"] // DAY == p["close_time"] // DAY or (q["enter_time"] % DAY == 0 and p["close_time"] // DAY == q["enter_time"] // DAY):
                same_day_reentry += 1
    sl_trades = [t for t in nn["trades"] if reason_n(t["reason"]) == "SL"]
    sl_same_day = sum(1 for t in sl_trades if t["close_time"] // DAY == t["enter_time"] // DAY)
    sl_intrabar = 0
    sl_px_ok = True
    for t in sl_trades:
        b = bars[t["sym"]]
        i = (t["close_time"] - t_first) // M
        lvl = t["avg_price"] * (1 - st["sl"] / 100)
        sl_intrabar += int(t["close_time"] % DAY != 0 and float(b.low.iloc[i]) <= lvl * (1 + 1e-9))
        sl_px_ok &= abs(t["close_price"] - lvl) <= max(1e-6 * lvl, 1e-8)
    # how many trades the legacy per-minute level behaviour would have re-entered: stop-outs on a day whose governing daily signal (prev day close) is still true
    legacy_candidates = 0
    for t in sl_trades:
        dd = daily[t["sym"]]
        k = int((t["close_time"] - int(dd.open_time.iloc[0])) // DAY)          # the day of the stop-out; its signal came from day k-1
        if k >= 1 and int(dd[f"ent_{name}"].iloc[k - 1]) and t["close_time"] % DAY != 0:
            legacy_candidates += 1
    return {"stage": name, "cfg": st, "n_nora": len(nn["trades"]), "n_naut": len(na["trades"]), "n_paired_ok": sum(r["ok"] for r in rows), "n_paired": len(rows),
            "unmatched_or_bad": bad, "realized_equity_nora": eq_n, "realized_equity_naut": eq_a, "d_equity": abs(eq_n - eq_a), "open_at_end_nora": open_n,
            "open_at_end_naut": open_a, "rejected_for_risk_nora_minutes": nn["rejected_for_risk"], "sl_exits": len(sl_trades), "sl_same_day": sl_same_day,
            "sl_intrabar_path_ok": sl_intrabar, "sl_fill_at_level": bool(sl_px_ok), "same_day_reentries": same_day_reentry,
            "entries_only_at_daily_boundary": bool(entries_on_boundary), "legacy_level_reentry_candidates": legacy_candidates,
            "match": bool(not bad and abs(eq_n - eq_a) < 1e-2 and open_n == open_a), "trades": rows}


def main():
    only = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] != "all" else list(STAGES)
    suffix = sys.argv[2] if len(sys.argv) > 2 else ""
    out = {}
    print("| stage | cfg | trades nora/naut | paired ok | realized equity nora | nautilus | d | open@end | SL (same-day/intrabar/at level) | same-day re-entries | legacy-level re-entry candidates | MATCH |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name in only:
        r = compare(name, suffix)
        out[name] = {k: v for k, v in r.items() if k != "trades"}
        c = r["cfg"]
        print(f"| {name} | {c['mode']} EMA{c['ema']} SL{c['sl']}% | {r['n_nora']}/{r['n_naut']} | {r['n_paired_ok']}/{r['n_paired']} | {r['realized_equity_nora']:.4f} | "
              f"{r['realized_equity_naut']:.4f} | {r['d_equity']:.2e} | {r['open_at_end_nora']} vs {r['open_at_end_naut']} | {r['sl_exits']} ({r['sl_same_day']}/{r['sl_intrabar_path_ok']}/{r['sl_fill_at_level']}) | "
              f"{r['same_day_reentries']} | {r['legacy_level_reentry_candidates']} | {r['match']} |")
        for b in r["unmatched_or_bad"][:5]:
            print("   BAD", b)
        if not suffix:
            json.dump(r["trades"], open(os.path.join(OUT, f"s9_trades_{name}.json"), "w"))
    if not suffix:
        json.dump(out, open(os.path.join(HERE, "s9_results.json"), "w"), indent=1, sort_keys=True)
    return 0 if all(v["match"] for v in out.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
