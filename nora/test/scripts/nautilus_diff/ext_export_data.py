"""Export bars (aligned + gapped), EMA-cross signals and funding for BTC/ETH/SOL perp 1h (OKX) to out/ext/.
Same construction as export_data.py (aligned: open[t+1]:=close[t]; gapped: synthetic gaps never right after a signal bar), per symbol.
Run: PYTHONDONTWRITEBYTECODE=1 backend/utils/ops/run_limited.sh --no-lock -- test/scripts/nautilus_diff/ext_export_data.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ext_common import OUT, SYMS  # noqa: E402

NORA = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
N_BARS = 4320
SIG = {"ema20_50": (20, 50), "ema5_13": (5, 13)}


def export(sym, seed):
    df = pd.read_pickle(os.path.join(NORA, f"data/okx/cex/{sym}/perp/1h.pkl")).reset_index(drop=True)
    sig = pd.DataFrame({"open_time": df.open_time})
    for name, (f, s) in SIG.items():
        ef, es = df.close.ewm(span=f, adjust=False).mean(), df.close.ewm(span=s, adjust=False).mean()
        up = (ef > es) & (ef.shift(1) <= es.shift(1))
        dn = (ef < es) & (ef.shift(1) >= es.shift(1))
        sig[name + "_up"], sig[name + "_dn"] = up.astype(int), dn.astype(int)
        sig.loc[:s * 5, [name + "_up", name + "_dn"]] = 0
    raw = df.iloc[-N_BARS:].reset_index(drop=True)
    sg = sig.iloc[-N_BARS:].reset_index(drop=True)
    al = raw.copy()
    al.loc[1:, "open"] = raw.close.shift(1).iloc[1:].values
    al["high"] = np.maximum(al.high, al.open)
    al["low"] = np.minimum(al.low, al.open)
    rng = np.random.default_rng(seed)
    sig_any = (sg[[c for c in sg.columns if c != "open_time"]].sum(axis=1) > 0).values
    gp, scale, n_gaps, cols, rows = al.copy(), 1.0, 0, ["open", "high", "low", "close"], []
    for i in range(len(gp)):
        if i > 1 and not sig_any[i - 1] and rng.random() < 0.06:
            scale *= 1.0 + rng.choice([-1, 1]) * rng.uniform(0.003, 0.015)
            n_gaps += 1
        rows.append(gp.iloc[i][cols].values * scale)
    prec = 1 if sym == "BTC" else (2 if sym == "ETH" else 3)
    gp[cols] = np.round(np.array(rows), prec)
    gp["high"] = np.maximum.reduce([gp.high, gp.open, gp.close])
    gp["low"] = np.minimum.reduce([gp.low, gp.open, gp.close])
    al.to_csv(os.path.join(OUT, f"bars_{sym}_aligned.csv"), index=False)
    gp.to_csv(os.path.join(OUT, f"bars_{sym}_gapped.csv"), index=False)
    sg.to_csv(os.path.join(OUT, f"signals_{sym}.csv"), index=False)
    fu = pd.read_pickle(os.path.join(NORA, f"data/okx/cex/{sym}/perp/funding.pkl"))
    t0, t1 = int(raw.open_time.iloc[0]), int(raw.open_time.iloc[-1])
    fu = fu[(fu.funding_time >= t0) & (fu.funding_time <= t1)].sort_values("funding_time")[["funding_time", "rate"]]
    fu.to_csv(os.path.join(OUT, f"funding_{sym}.csv"), index=False)
    on_hour = int((fu.funding_time % 3_600_000 == 0).sum())
    return raw.open_time.values, {"gaps": n_gaps, "funding_rows": len(fu), "funding_exactly_on_hour": on_hour,
                                  "start": str(pd.to_datetime(t0, unit="ms")), "end": str(pd.to_datetime(t1, unit="ms")),
                                  "signals": {k: {"up": int(sg[k + "_up"].sum()), "dn": int(sg[k + "_dn"].sum())} for k in SIG}}


def main():
    os.makedirs(OUT, exist_ok=True)
    stats, ts0 = {}, None
    for k, sym in enumerate(SYMS):
        ts, st = export(sym, 7 + k)
        if ts0 is None:
            ts0 = ts
        assert (ts == ts0).all(), f"{sym}: open_time differs from {SYMS[0]}"
        stats[sym] = st
    json.dump(stats, open(os.path.join(OUT, "data_stats.json"), "w"), indent=1)
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
