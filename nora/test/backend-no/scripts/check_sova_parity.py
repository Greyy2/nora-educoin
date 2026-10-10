"""Đối chiếu tín hiệu Keltner của Nora (keltner_trend_long/short) với KEMA của sova trên CÙNG dữ liệu.

sova (tham chiếu): sova/backend/core/indicator.calculate_keltner_bands + strategies/kema.py — tính trên nến ĐÓNG của khung tín hiệu,
LONG khi close cắt lên dải trên (close[1] < up[1] và close > up), SHORT khi cắt xuống dải dưới.
Nora: engine thật (live/signals.evaluate với khung chạy = khung tín hiệu). Tín hiệu của Nora ở nến t dùng nến khung ĐÃ ĐÓNG trước t
(không nhìn trước), nên kỳ vọng nora[t] == sova[t-1] (lệch đúng 1 nến), không lệch nào khác.

Chạy: ops/run_limited.sh --no-lock -- test/scripts/check_sova_parity.py [--symbols BTC,ETH] [--tf 4h]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

NORA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SOVA = os.path.join(os.path.dirname(NORA), "sova", "backend")
sys.path.insert(0, NORA)


def sova_signals(df: pd.DataFrame, ema_n: int, atr_n: int, k_up: float, k_dn: float):
    sys.path.insert(0, SOVA)
    from core.indicator import calculate_atr, calculate_ema
    c, h, l = (df[x].to_numpy(dtype=float) for x in ("close", "high", "low"))
    ema, atr = calculate_ema(c, ema_n), calculate_atr(h, l, c, atr_n)
    up, dn = ema + k_up * atr, ema - k_dn * atr
    cp, upp, dnp = np.roll(c, 1), np.roll(up, 1), np.roll(dn, 1)
    cp[0], upp[0], dnp[0] = c[0], up[0], dn[0]
    with np.errstate(invalid="ignore"):
        return (cp < upp) & (c > up), (cp > dnp) & (c < dn), ema, atr


def nora_signals(sym: str, df: pd.DataFrame, tf: str, params: dict):
    from backend.core.params import materialize, schema_defaults
    from backend.optimize.book.build import CANDIDATES
    from backend.core import backtest as bt
    by = {c["id"]: c for c in CANDIDATES}
    sts = [materialize(by[i], {**schema_defaults(by[i]), **params}, risk_per_trade_pct=1.0, stop_fill="level")
           for i in ("keltner_trend_long", "keltner_trend_short")]
    frames = {tf: df[["open_time", "open", "high", "low", "close", "volume"]].assign(is_filled=0)}
    if tf != "4h":
        frames["4h"] = pd.read_pickle(os.path.join(ls_root(), sym, "perp", "4h.pkl"))
    v = bt.evaluate_signals(sym, sts, frames, tf)
    long_e, short_e = v["entries"][0], v["entries"][1]
    return v["t"], long_e["match"], short_e["match"], long_e["stop"]


def ls_root():
    from backend.crawl.store import default_data_root
    return os.path.join(default_data_root(), "cex")


def compare(name, nora_t, nora_x, sova_t, sova_x):
    """Lệch nến tốt nhất trong {0, 1, 2} (kỳ vọng 0 hoặc 1 tuỳ quy ước nhãn thời gian) và số nến lệch ở mức đó."""
    n = np.asarray(nora_x, dtype=bool)
    warm = 300                                                                     # bỏ đoạn khởi động chỉ báo
    best = None
    for lag in (0, 1, 2):
        s = pd.Series(sova_x, index=sova_t).shift(lag).fillna(False).astype(bool).reindex(nora_t, fill_value=False).to_numpy()
        diff = np.flatnonzero(n[warm:] != s[warm:])
        if best is None or len(diff) < len(best[1]):
            best = (lag, diff, s)
    lag, diff, s = best
    return {"name": name, "lag": lag, "nora": int(n[warm:].sum()), "sova": int(s[warm:].sum()), "mismatch": int(len(diff)),
            "first_mismatch": [pd.Timestamp(int(nora_t[warm + i]), unit="ms", tz="UTC").strftime("%Y-%m-%d %H:%M") for i in diff[:3]]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTC,ETH,SOL,BNB,XRP,DOGE,ADA,AVAX")
    ap.add_argument("--tf", default="4h")
    ap.add_argument("--configs", default="20:14:2.0:2.0,30:14:2.5:1.5,50:20:1.5:2.5")
    a = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore")
    from backend.core.indicator import compute
    total = 0
    for cfg in a.configs.split(","):
        ema_n, atr_n, k_up, k_dn = int(cfg.split(":")[0]), int(cfg.split(":")[1]), float(cfg.split(":")[2]), float(cfg.split(":")[3])
        params = {"sig.signal_tf": a.tf, "sig.ema_n": ema_n, "sig.atr_n": atr_n, "sig.k_up": k_up, "sig.k_dn": k_dn}
        for sym in a.symbols.split(","):
            df = pd.read_pickle(os.path.join(ls_root(), sym, "perp", f"{a.tf}.pkl")).reset_index(drop=True)
            sl, ss, ema, atr = sova_signals(df, ema_n, atr_n, k_up, k_dn)
            ne, na = compute(df, f"ema_{ema_n}").to_numpy(), compute(df, f"atr_{atr_n}").to_numpy()
            ind = {"ema_maxrel": float(np.nanmax(np.abs(ne[300:] / ema[300:] - 1))), "atr_maxrel": float(np.nanmax(np.abs(na[300:] / atr[300:] - 1)))}
            t, nl, ns, nstop = nora_signals(sym, df, a.tf, params)
            st = df["open_time"].to_numpy()
            rows = [compare("LONG vào", t, nl, st, sl), compare("SHORT vào", t, ns, st, ss), compare("LONG thoát", t, nstop, st, ss)]
            bad = sum(r["mismatch"] for r in rows)
            total += bad
            print(f"{cfg:18s} {sym:5s} ema lệch {ind['ema_maxrel']:.1e} atr lệch {ind['atr_maxrel']:.1e} | "
                  + " | ".join(f"{r['name']} (trễ {r['lag']} nến): nora {r['nora']} sova {r['sova']} lệch {r['mismatch']}{' ' + str(r['first_mismatch']) if r['mismatch'] else ''}"
                               for r in rows), flush=True)
    print(f"TỔNG LỆCH: {total}")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
