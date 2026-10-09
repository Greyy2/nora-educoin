"""S10 data export (same construction as s9_export_data.py): Nora data root from OKX BTC/ETH perp 1m (whole UTC days, ALIGNED open[t]:=close[t-1],
high/low widened), Nora's own resampler makes 1h/4h/...; signals and ATR% computed INDEPENDENTLY in pandas/numpy (EMA SMA-seeded, Wilder RMA SMA-seeded
over true range, natr = atr/close*100) and asserted == backend indicator.ema / indicator.natr.
Writes out/s10/data_root, out/s10/bars1m_<SYM>.csv, sig_<frame>_<SYM>.csv (open_time, ohlc, ent_<stage>), atr_<frame>_<SYM>.csv (open_time, natr<period>).
Run from nora/: PYTHONDONTWRITEBYTECODE=1 ops/run_limited.sh --no-lock -- test/scripts/nautilus_diff/s10_export_data.py
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))
from s10_common import DAY, END, OUT, ROOT, SRC_ROOT, STAGES, START, SYMS  # noqa: E402


def sma_seed(x, n, alpha):
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    out[n - 1] = float(np.mean(x[:n]))
    for i in range(n, len(x)):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out


def natr_np(df, n):
    h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.r_[np.nan, c[:-1]]
    tr = np.fmax.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])      # first bar: prev close NaN -> h-l (pandas max skips NaN)
    return sma_seed(tr, n, 1.0 / n) / c * 100.0


def main():
    from backend.crawl.store import save_resampled_dataset
    from backend.core.indicator import ema as nora_ema, natr as nora_natr
    os.makedirs(OUT, exist_ok=True)
    t0 = int(pd.Timestamp(START, tz="UTC").timestamp() * 1000)
    t1 = int(pd.Timestamp(END, tz="UTC").timestamp() * 1000) + DAY - 60_000
    meta = {"venue": "cex", "checksums_verified": True, "exchange": "okx_swap"}
    for sym in SYMS:
        raw = pd.read_pickle(os.path.join(SRC_ROOT, "cex", sym, "perp", "1m.pkl"))
        d = raw[(raw.open_time >= t0) & (raw.open_time <= t1)][["open_time", "open", "high", "low", "close", "volume"]].reset_index(drop=True).copy()
        assert len(d) == (t1 - t0) // 60_000 + 1 and (np.diff(d.open_time.values) == 60_000).all(), f"{sym}: gaps in source window"
        d["open"] = np.r_[d.open.values[0], d.close.values[:-1]]
        d["high"] = np.maximum.reduce([d.high.values, d.open.values, d.close.values])
        d["low"] = np.minimum.reduce([d.low.values, d.open.values, d.close.values])
        for c in ("open", "high", "low", "close"):
            d[c] = d[c].round(8)
        save_resampled_dataset(symbol="perp", output_dir=os.path.join(ROOT, "cex", sym), df_1m_raw=d, pool_address="s10", crawl_ok=True,
                               requested_start_ts=t0, requested_end_ts=t1, extra_meta={**meta, "market": "perp"})
        save_resampled_dataset(symbol=sym, output_dir=os.path.join(ROOT, "cex"), df_1m_raw=d, pool_address="s10", crawl_ok=True,
                               requested_start_ts=t0, requested_end_ts=t1, extra_meta=meta)
        d.to_csv(os.path.join(OUT, f"bars1m_{sym}.csv"), index=False)
        frames = {}
        for fr in ("1h", "4h"):
            f = pd.read_pickle(os.path.join(ROOT, "cex", sym, "perp", f"{fr}.pkl"))[["open_time", "open", "high", "low", "close"]].reset_index(drop=True)
            ms = 3_600_000 if fr == "1h" else 14_400_000
            g = d.groupby(d.open_time // ms)                              # independent aggregation check against the 1m bars
            assert len(f) == (t1 - t0 + 60_000) // ms and np.array_equal(g.close.last().values, f.close.values) \
                and np.array_equal(g.high.max().values, f.high.values) and np.array_equal(g.low.min().values, f.low.values)
            frames[fr] = f
            nt = natr_np(f, 14)
            ref = nora_natr(f, 14).to_numpy()
            assert np.allclose(np.nan_to_num(nt), np.nan_to_num(ref), rtol=1e-12, atol=0), f"{sym} {fr}: natr != backend indicator.natr"
            pd.DataFrame({"open_time": f.open_time, "natr14": nt}).to_csv(os.path.join(OUT, f"atr_{fr}_{sym}.csv"), index=False)
        sig = {fr: frames[fr].copy() for fr in frames}
        for name, st in STAGES.items():
            fr = sig[st["frame"]]
            c = fr.close.values
            e = sma_seed(c, st["ema"], 2.0 / (st["ema"] + 1))
            ref = nora_ema(fr, st["ema"]).to_numpy()
            assert np.allclose(np.nan_to_num(e), np.nan_to_num(ref), rtol=1e-12, atol=0), f"{sym} {name}: ema != backend indicator.ema"
            pc, pe = np.r_[np.nan, c[:-1]], np.r_[np.nan, e[:-1]]
            with np.errstate(invalid="ignore"):
                ent = (c > e) & (pc <= pe)
            fr[f"ent_{name}"] = (ent & np.isfinite(e) & np.isfinite(pe)).astype(int)
        for fr in sig:
            sig[fr].to_csv(os.path.join(OUT, f"sig_{fr}_{sym}.csv"), index=False)
        print(sym, "1m bars", len(d), {n: int(sig[st["frame"]][f"ent_{n}"].sum()) for n, st in STAGES.items()})


if __name__ == "__main__":
    main()
