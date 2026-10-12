"""Export OKX BTC perp 1h bars (raw + ALIGNED) and precomputed EMA-cross signals for both engines.

Aligned: open[t+1] := close[t] (high/low widened to keep OHLC valid) so Nora's next-bar-open entry and
Nautilus' current-bar-close entry occur at the same price.
Run: PYTHONDONTWRITEBYTECODE=1 ops/run_limited.sh --no-lock -- test/scripts/nautilus_diff/export_data.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
NORA = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
N_BARS = int(sys.argv[1]) if len(sys.argv) > 1 else 4320          # ~6 months of 1h bars
SIGNALS = {"ema20_50": (20, 50), "ema5_13": (5, 13)}


def main():
    os.makedirs(OUT, exist_ok=True)
    df = pd.read_pickle(os.path.join(NORA, "data/market/okx/cex/BTC/perp/1h.pkl")).reset_index(drop=True)
    sig = pd.DataFrame({"open_time": df.open_time})
    for name, (f, s) in SIGNALS.items():
        ef, es = df.close.ewm(span=f, adjust=False).mean(), df.close.ewm(span=s, adjust=False).mean()
        up = (ef > es) & (ef.shift(1) <= es.shift(1))
        dn = (ef < es) & (ef.shift(1) >= es.shift(1))
        sig[name + "_entry"], sig[name + "_exit"] = up.astype(int), dn.astype(int)
        sig.loc[:s * 5, [name + "_entry", name + "_exit"]] = 0     # EMA warm-up
    raw = df.iloc[-N_BARS:].reset_index(drop=True)
    sg = sig.iloc[-N_BARS:].reset_index(drop=True)
    aligned = raw.copy()
    aligned.loc[1:, "open"] = raw.close.shift(1).iloc[1:].values
    aligned["high"] = np.maximum(aligned.high, aligned.open)
    aligned["low"] = np.minimum(aligned.low, aligned.open)
    eq = (raw.open.iloc[1:].values == raw.close.iloc[:-1].values)
    gap = (raw.open.iloc[1:].values / raw.close.iloc[:-1].values - 1).astype(float)
    stats = {"n_bars": len(raw), "start": pd.to_datetime(raw.open_time.iloc[0], unit="ms").isoformat(),
             "end": pd.to_datetime(raw.open_time.iloc[-1], unit="ms").isoformat(),
             "open_eq_prev_close_frac": float(eq.mean()), "open_eq_prev_close_n": int(eq.sum()),
             "mean_abs_gap_bps": float(np.abs(gap).mean() * 1e4), "max_abs_gap_bps": float(np.abs(gap).max() * 1e4),
             "bars_hl_widened_by_alignment": int(((aligned.high != raw.high) | (aligned.low != raw.low)).sum()),
             "signals": {k: {"entries": int(sg[k + "_entry"].sum()), "exits": int(sg[k + "_exit"].sum())} for k in SIGNALS}}
    # GAPPED: aligned series with synthetic overnight-style gaps (bar t opens away from close[t-1]; all later bars rescaled, so the
    # series stays continuous afterwards). Never right after a signal bar (that would turn it into an entry-timing difference).
    rng = np.random.default_rng(7)
    sig_any = ((sg["ema20_50_entry"] | sg["ema20_50_exit"] | sg["ema5_13_entry"] | sg["ema5_13_exit"]) > 0).values
    gapped = aligned.copy()
    scale = 1.0
    n_gaps = 0
    cols = ["open", "high", "low", "close"]
    out_rows = []
    for i in range(len(gapped)):
        if i > 1 and not sig_any[i - 1] and rng.random() < 0.06:
            scale *= 1.0 + rng.choice([-1, 1]) * rng.uniform(0.003, 0.015)
            n_gaps += 1
        out_rows.append(gapped.iloc[i][cols].values * scale)
    gapped[cols] = np.round(np.array(out_rows), 1)
    gapped["high"] = np.maximum.reduce([gapped.high, gapped.open, gapped.close])
    gapped["low"] = np.minimum.reduce([gapped.low, gapped.open, gapped.close])
    gapped.to_csv(os.path.join(OUT, "bars_gapped.csv"), index=False)
    stats["gapped_bars_injected"] = n_gaps
    raw.to_csv(os.path.join(OUT, "bars_raw.csv"), index=False)
    aligned.to_csv(os.path.join(OUT, "bars_aligned.csv"), index=False)
    sg.to_csv(os.path.join(OUT, "signals.csv"), index=False)
    json.dump(stats, open(os.path.join(OUT, "data_stats.json"), "w"), indent=1)
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
