"""S9 data export. Builds a Nora data root from OKX BTC/ETH perp 1m (whole UTC days START..END, ALIGNED: open[t]:=close[t-1], high/low widened), lets
Nora's own resampler make 24h.pkl, then computes the daily signals independently in pandas (EMA = SMA-seeded alpha 2/(n+1), asserted == backend indicator.ema).
Writes out/s9/data_root/..., out/s9/bars1m_<SYM>.csv, out/s9/daily_<SYM>.csv (open_time, ohlc, flags per stage: ent_<stage>, ext_<stage>).
Run from nora/: PYTHONDONTWRITEBYTECODE=1 ops/run_limited.sh --no-lock -- test/scripts/nautilus_diff/s9_export_data.py
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))
from s9_common import DAY, END, OUT, ROOT, SRC_ROOT, STAGES, START, SYMS  # noqa: E402


def ema_sma_seed(x, n):
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    a = 2.0 / (n + 1)
    out[n - 1] = float(np.mean(x[:n]))
    for i in range(n, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def flags(daily, st):
    c = daily.close.values
    e = ema_sma_seed(c, st["ema"])
    prev_c, prev_e = np.r_[np.nan, c[:-1]], np.r_[np.nan, e[:-1]]
    with np.errstate(invalid="ignore"):
        above = c > e
        ent = above & (prev_c <= prev_e) if st["mode"] == "cross" else above
        ext = c < e
    return np.nan_to_num(ent.astype(float)).astype(bool) & np.isfinite(e), ext & np.isfinite(e), e


def main():
    from backend.crawl.store import save_resampled_dataset
    from backend.alpha.dsl.indicator import ema as nora_ema
    os.makedirs(OUT, exist_ok=True)
    t0 = int(pd.Timestamp(START, tz="UTC").timestamp() * 1000)
    t1 = int(pd.Timestamp(END, tz="UTC").timestamp() * 1000) + DAY - 60_000
    meta = {"venue": "cex", "checksums_verified": True, "exchange": "okx_swap"}
    for sym in SYMS:
        raw = pd.read_pickle(os.path.join(SRC_ROOT, "cex", sym, "perp", "1m.pkl"))
        d = raw[(raw.open_time >= t0) & (raw.open_time <= t1)][["open_time", "open", "high", "low", "close", "volume"]].reset_index(drop=True).copy()
        assert len(d) == (t1 - t0) // 60_000 + 1 and (np.diff(d.open_time.values) == 60_000).all(), f"{sym}: gaps in source window"
        d["open"] = np.r_[d.open.values[0], d.close.values[:-1]]                  # aligned: open[t] = close[t-1]
        d["high"] = np.maximum.reduce([d.high.values, d.open.values, d.close.values])
        d["low"] = np.minimum.reduce([d.low.values, d.open.values, d.close.values])
        for c in ("open", "high", "low", "close"):                               # 2dp-ish exchange ticks -> round to 8dp so csv/pkl/Nautilus agree exactly
            d[c] = d[c].round(8)
        save_resampled_dataset(symbol="perp", output_dir=os.path.join(ROOT, "cex", sym), df_1m_raw=d, pool_address="s9", crawl_ok=True,
                               requested_start_ts=t0, requested_end_ts=t1, extra_meta={**meta, "market": "perp"})
        save_resampled_dataset(symbol=sym, output_dir=os.path.join(ROOT, "cex"), df_1m_raw=d, pool_address="s9", crawl_ok=True,
                               requested_start_ts=t0, requested_end_ts=t1, extra_meta=meta)
        d.to_csv(os.path.join(OUT, f"bars1m_{sym}.csv"), index=False)
        dd = pd.read_pickle(os.path.join(ROOT, "cex", sym, "perp", "24h.pkl"))[["open_time", "open", "high", "low", "close"]].reset_index(drop=True)
        assert (dd.open_time.values % DAY == 0).all() and len(dd) == (t1 - t0 + 60_000) // DAY
        # independent daily aggregation check against the 1m bars
        g = d.groupby(d.open_time // DAY)
        assert np.array_equal(g.close.last().values, dd.close.values) and np.array_equal(g.high.max().values, dd.high.values)
        for name, st in STAGES.items():
            ent, ext, e = flags(dd, st)
            ref = nora_ema(dd.assign(close=dd.close), st["ema"]).to_numpy()
            assert np.allclose(np.nan_to_num(e), np.nan_to_num(ref), rtol=1e-12, atol=0), f"{sym} {name}: ema != backend indicator.ema"
            dd[f"ent_{name}"], dd[f"ext_{name}"] = ent.astype(int), ext.astype(int)
        dd.to_csv(os.path.join(OUT, f"daily_{sym}.csv"), index=False)
        print(sym, "1m bars", len(d), "days", len(dd), {n: (int(dd[f'ent_{n}'].sum()), int(dd[f'ext_{n}'].sum())) for n in STAGES})


if __name__ == "__main__":
    main()
