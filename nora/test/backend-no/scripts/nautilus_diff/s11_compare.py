"""S11 comparison Nora (real engine, 1h tree on 1m base; cooldown, DCA ladder, funding) vs Nautilus. Trade-by-trade incl. every fill (time, price, qty, fee,
maker/taker), funding per trade, realized equity. Usage: ~/.venvs/nora/bin/python test/scripts/nautilus_diff/s11_compare.py [stages|all]
Writes s11_results.json; exit 1 on mismatch. Tolerances (as S9): price rel 1e-9, qty abs 5.01e-9 per entry layer (the exit qty is the sum of the rounded layers) + rel 1e-7 (half the 8dp Nautilus size increment + the sub-1e-4 USDT equity drift that rounding feeds into the next sizing; as S9), pnl/fees/funding abs 1e-3, final equity abs 1e-2.
Fill time: Nora order_time = open_time of the 1m bar; Nautilus market fills carry the act instant (== that open_time), stop/limit fills the matched bar -> t_first + bar*1min.
"""
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from s11_common import M, OUT, STAGES, SYMS, dca_lists  # noqa: E402

REASON = {"Stop-loss": "SL", "Tín hiệu": "SIG", "End of": "END"}


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

    def ftime(f):
        return t_first + f["bar"] * M if f["kind"] in ("SL", "DCA") else f["t"]

    for t in na["trades"]:
        t["close_time"] = ftime(t["fills"][-1])
    N = {(t["sym"], t["enter_time"]): dict(t, r=reason_n(t["reason"])) for t in nn["trades"]}
    A = {(t["sym"], t["enter_time"]): dict(t, r=t["reason"]) for t in na["trades"]}
    bad, n_ok, n_fills, layers_total, dca_trades = [], 0, 0, 0, 0
    max_d = {"px": 0.0, "qty": 0.0, "pnl": 0.0, "fee": 0.0, "fund": 0.0}
    for key in sorted(set(N) | set(A), key=lambda k: (k[1], k[0])):
        n, a = N.get(key), A.get(key)
        if n is None or a is None:
            bad.append({"key": list(key), "why": "only in " + ("nautilus" if n is None else "nora")})
            continue
        nf, af = n["fills"], a["fills"]
        why = []
        if len(nf) != len(af):
            why.append(f"fills {len(nf)} vs {len(af)}")
        else:
            for x, y in zip(nf, af):
                n_fills += 1
                if int(x[0]) != ftime(y) or rel(x[1], y["px"]) > 1e-9 or abs(x[2] - y["qty"]) > 5.01e-9 * max(1, len(nf) - 1) + 1e-7 * abs(y["qty"]) or abs(x[3] - y["fee"]) > 1e-3 \
                        or (x[4].upper()[:1] != y["liq"].upper()[:1]):
                    why.append(f"fill nora={x} naut={[ftime(y), y['px'], y['qty'], y['fee'], y['liq']]}")
                max_d["px"] = max(max_d["px"], rel(x[1], y["px"]))
                max_d["qty"] = max(max_d["qty"], abs(x[2] - y["qty"]) / max(abs(y["qty"]), 1e-300))
        if n["close_time"] != a["close_time"] or n["r"] != a["r"]:
            why.append(f"close {n['close_time']}/{n['r']} vs {a['close_time']}/{a['r']}")
        d_pnl, d_fee, d_fund = abs(n["pnl"] - a["pnl"]), abs(n["fees"] - a["fees"]), abs(n["funding"] - a["funding"])
        max_d["pnl"], max_d["fee"], max_d["fund"] = max(max_d["pnl"], d_pnl), max(max_d["fee"], d_fee), max(max_d["fund"], d_fund)
        if d_pnl > 1e-3 or d_fee > 1e-3 or d_fund > 1e-3 or n["layers"] != a["layers"] or rel(n["avg_price"], a["avg_price"]) > 1e-9:
            why.append(f"pnl/fees/funding/layers/avg nora={[n['pnl'], n['fees'], n['funding'], n['layers'], n['avg_price']]} naut={[a['pnl'], a['fees'], a['funding'], a['layers'], a['avg_price']]}")
        layers_total += n["layers"]
        dca_trades += n["layers"] > 1
        if why:
            bad.append({"key": list(key), "why": why})
        else:
            n_ok += 1
    eq_n, eq_a = nn["realized_equity"], na["realized_equity_nora_def"]
    open_n = sorted((o["sym"], o["enter_time"]) for o in nn["open_at_end"])
    open_a = sorted((o["sym"], o["enter_time"]) for o in na["open_at_end"])
    # semantic checks on Nora trades
    gap_min = None
    for s in SYMS:
        ts = sorted((t for t in nn["trades"] if t["sym"] == s), key=lambda t: t["enter_time"])
        for p, q in zip(ts, ts[1:]):
            g = (q["enter_time"] - M - p["close_time"]) // M        # signal bar (entry - 1m) minus close, minutes
            gap_min = g if gap_min is None else min(gap_min, g)
    fund_n, fund_a = sum(t["funding"] for t in nn["trades"]), sum(t["funding"] for t in na["trades"])
    return {"stage": name, "cfg": st, "n_nora": len(nn["trades"]), "n_naut": len(na["trades"]), "n_paired_ok": n_ok, "n_fills_checked": n_fills,
            "unmatched_or_bad": bad, "realized_equity_nora": eq_n, "realized_equity_naut": eq_a, "d_equity": abs(eq_n - eq_a),
            "open_at_end_nora": open_n, "open_at_end_naut": open_a, "layers_total": layers_total, "trades_with_dca": dca_trades,
            "dca_rejected_nora": nn["dca_rejected"], "cool_skips_naut": na["cool_skips"], "min_signal_gap_min": gap_min, "funding_nora": fund_n,
            "funding_naut": fund_a, "funding_events_charged_naut": len(na["funding_log"]), "max_diff": max_d,
            "sl_exits": sum(1 for t in nn["trades"] if reason_n(t["reason"]) == "SL"),
            "match": bool(not bad and abs(eq_n - eq_a) < 1e-2 and open_n == open_a and abs(fund_n - fund_a) < 1e-2)}


def main():
    only = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] != "all" else list(STAGES)
    out = {}
    print("| stage | cfg | trades nora/naut | paired ok | fills | layers (trades w/ DCA) | SL | cooldown skips (naut) / min gap | funding nora/naut | realized equity nora | nautilus | d | MATCH |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name in only:
        r = compare(name)
        out[name] = r
        c = r["cfg"]
        cd = f"{sum(r['cool_skips_naut'].values())} / {r['min_signal_gap_min']}"
        print(f"| {name} | {c['side']} lev{c['lev']} SL{c['sl']}% cool{c['cool']} dca={c['dca']} | {r['n_nora']}/{r['n_naut']} | {r['n_paired_ok']}/{r['n_nora']} | {r['n_fills_checked']} | "
              f"{r['layers_total']} ({r['trades_with_dca']}) | {r['sl_exits']} | {cd} | {r['funding_nora']:.4f}/{r['funding_naut']:.4f} | {r['realized_equity_nora']:.4f} | "
              f"{r['realized_equity_naut']:.4f} | {r['d_equity']:.2e} | {r['match']} |")
        for b in r["unmatched_or_bad"][:4]:
            print("   BAD", b)
    json.dump(out, open(os.path.join(HERE, "s11_results.json"), "w"), indent=1, sort_keys=True)
    return 0 if all(v["match"] for v in out.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
