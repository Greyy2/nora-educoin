"""S12 comparison Nora vs Nautilus on RAW data (G1).
Checks:
1. 'next_open' parity: Nora (next-open) vs Nautilus (next-open simulated) trade-by-trade. Must match!
2. 'close_fill' convention delta: compares next-open vs close-fill entry prices, PnL and final equity.
"""
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from s12_common import CAPITAL, DAY, M, OUT, STAGES, SYMS  # noqa: E402

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
    daily = {s: pd.read_csv(os.path.join(OUT, f"daily_{s}.csv")) for s in SYMS}
    t_first = int(bars[SYMS[0]].open_time.iloc[0])
    for t in na["trades"]:
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
    is_match = bool(not bad and abs(eq_n - eq_a) < 1e-2 and open_n == open_a)

    # Convention comparison with close_fill if available
    close_fill_path = os.path.join(OUT, f"nautilus_{name}_close_fill.json")
    conv_delta = {}
    if os.path.exists(close_fill_path):
        nac = json.load(open(close_fill_path))
        eq_c = nac["realized_equity_nora_def"]
        conv_delta = {
            "realized_equity_close_fill": eq_c,
            "d_equity_vs_next_open": eq_c - eq_a,
            "d_equity_pct": (eq_c - eq_a) / CAPITAL * 100.0,
            "n_trades_close_fill": len(nac["trades"])
        }

    return {"stage": name, "cfg": st, "n_nora": len(nn["trades"]), "n_naut": len(na["trades"]),
            "n_paired_ok": sum(r["ok"] for r in rows), "n_paired": len(rows),
            "unmatched_or_bad": bad, "realized_equity_nora": eq_n, "realized_equity_naut": eq_a, "d_equity": abs(eq_n - eq_a),
            "open_at_end_nora": open_n, "open_at_end_naut": open_a, "match": is_match, "conv_delta": conv_delta, "trades": rows}


def main():
    only = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] != "all" else list(STAGES)
    out = {}
    print("| stage | cfg | trades nora/naut | paired ok | realized eq nora | nautilus | d | open@end | close_fill eq | delta % | MATCH |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    all_ok = True
    for name in only:
        res = compare(name)
        out[name] = res
        ok_mark = "✅ PASS" if res["match"] else "❌ FAIL"
        if not res["match"]:
            all_ok = False
        cf_eq = f"{res['conv_delta'].get('realized_equity_close_fill', 0):.2f}" if res['conv_delta'] else "N/A"
        cf_delta = f"{res['conv_delta'].get('d_equity_pct', 0):+.4f}%" if res['conv_delta'] else "N/A"
        print(f"| {name} | {res['cfg']['mode']} {res['cfg']['ema']} sl={res['cfg']['sl']} | {res['n_nora']}/{res['n_naut']} | {res['n_paired_ok']}/{res['n_paired']} | {res['realized_equity_nora']:.2f} | {res['realized_equity_naut']:.2f} | {res['d_equity']:.4f} | {len(res['open_at_end_nora'])} | {cf_eq} | {cf_delta} | {ok_mark} |")
    json.dump(out, open(os.path.join(OUT, "s12_results.json"), "w"), indent=2)
    json.dump(out, open(os.path.join(HERE, "s12_results.json"), "w"), indent=2)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
