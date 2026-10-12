"""S11 data export (same as s9_export_data.py but 1h signal frame + funding): Nora data root (cex/<SYM>/perp/{1m..24h,funding}.pkl) from OKX 1m (ALIGNED
open[t]:=close[t-1]), 1h signals computed independently in pandas (EMA == backend indicator.ema asserted), funding csv.
Writes out/s11/data_root/..., bars1m_<SYM>.csv, hourly_<SYM>.csv (ohlc + ent_/ext_<stage>), funding_<SYM>.csv.
Run from nora/: PYTHONDONTWRITEBYTECODE=1 ops/run_limited.sh --no-lock -- test/scripts/nautilus_diff/s11_export_data.py
"""
import os
import shutil
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))
from s11_common import DAY, END, HOUR, OUT, ROOT, SRC_ROOT, STAGES, START, SYMS  # noqa: E402
from s9_export_data import ema_sma_seed  # noqa: E402


def flags(h, st):
    c = h.close.values
    e = ema_sma_seed(c, st["ema"])
    with np.errstate(invalid="ignore"):
        above, below = c > e, c < e
    fin = np.isfinite(e)
    long_ = st["side"] == "L"
    ent, ext = (above, below) if long_ else (below, above)
    return ent & fin, ext & fin, e


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
        d["open"] = np.r_[d.open.values[0], d.close.values[:-1]]
        d["high"] = np.maximum.reduce([d.high.values, d.open.values, d.close.values])
        d["low"] = np.minimum.reduce([d.low.values, d.open.values, d.close.values])
        for c in ("open", "high", "low", "close"):
            d[c] = d[c].round(8)
        save_resampled_dataset(symbol="perp", output_dir=os.path.join(ROOT, "cex", sym), df_1m_raw=d, pool_address="s11", crawl_ok=True,
                               requested_start_ts=t0, requested_end_ts=t1, extra_meta={**meta, "market": "perp"})
        save_resampled_dataset(symbol=sym, output_dir=os.path.join(ROOT, "cex"), df_1m_raw=d, pool_address="s11", crawl_ok=True,
                               requested_start_ts=t0, requested_end_ts=t1, extra_meta=meta)
        shutil.copy(os.path.join(SRC_ROOT, "cex", sym, "perp", "funding.pkl"), os.path.join(ROOT, "cex", sym, "perp", "funding.pkl"))
        fu = pd.read_pickle(os.path.join(SRC_ROOT, "cex", sym, "perp", "funding.pkl"))
        fu = fu[(fu.funding_time >= t0) & (fu.funding_time <= t1)][["funding_time", "rate"]].sort_values("funding_time")
        fu.to_csv(os.path.join(OUT, f"funding_{sym}.csv"), index=False)
        d.to_csv(os.path.join(OUT, f"bars1m_{sym}.csv"), index=False)
        hh = pd.read_pickle(os.path.join(ROOT, "cex", sym, "perp", "1h.pkl"))[["open_time", "open", "high", "low", "close"]].reset_index(drop=True)
        assert (hh.open_time.values % HOUR == 0).all() and len(hh) == (t1 - t0 + 60_000) // HOUR
        g = d.groupby(d.open_time // HOUR)
        assert np.array_equal(g.close.last().values, hh.close.values) and np.array_equal(g.high.max().values, hh.high.values)
        for name, st in STAGES.items():
            ent, ext, e = flags(hh, st)
            ref = nora_ema(hh.assign(close=hh.close), st["ema"]).to_numpy()
            assert np.allclose(np.nan_to_num(e), np.nan_to_num(ref), rtol=1e-12, atol=0), f"{sym} {name}: ema != backend indicator.ema"
            hh[f"ent_{name}"], hh[f"ext_{name}"] = ent.astype(int), ext.astype(int)
        hh.to_csv(os.path.join(OUT, f"hourly_{sym}.csv"), index=False)
        print(sym, "1m bars", len(d), "hours", len(hh), "funding rows", len(fu), {n: (int(hh[f'ent_{n}'].sum()), int(hh[f'ext_{n}'].sum())) for n in STAGES})


if __name__ == "__main__":
    main()
