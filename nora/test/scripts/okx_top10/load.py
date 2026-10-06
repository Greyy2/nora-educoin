"""Nạp bots/summary, dựng BASKET theo (bot, sym, side), nạp nến 1m (data_staging/cex).

Định nghĩa basket (khớp analyze.py: trường bk/add):
  với mỗi (sym, side), sắp sub-position theo thời điểm mở o; một sub-position thuộc basket hiện tại nếu
  o < max(c) của basket hiện tại (tức còn mở lúc nó mở) -> "add"; ngược lại mở basket mới.
  Chuỗi chồng lấn này là CHAIN: có thể nối nhiều đợt cách nhau nhiều ngày nếu luôn có >=1 sub-position còn mở
  (vd basket 23 tầng của 01pp). `bk` trong bots.json là id toàn cục của cùng định nghĩa -> kiểm tra khớp.
Tranche: fill liên tiếp cách <=15 phút gộp lại (collapse()); chỉ số add/layer "tr_" của Level A tính trên tranche.
Fill: t=o, px=po, notional=mg*lev (USDT), qty=notional/po. Close của từng sub-position: t=c, px=pc.
"""
import json, os, collections
import numpy as np
import pandas as pd

BOTS_JSON = "/home/vmc03/norabt/none/okx-top10/bots.json"
SUMMARY_JSON = "/home/vmc03/norabt/none/okx-top10/summary.json"
CANDLE_DIR = "/home/vmc03/norabt/nora/data_staging/cex"
MIN = 60_000


def load_bots():
    return json.load(open(BOTS_JSON))


def load_summary():
    return json.load(open(SUMMARY_JSON))


def get_bot(name):
    for b in load_bots():
        if b["name"] == name:
            return b
    raise KeyError(name)


def slug(name):
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")


def collapse(fills, gap_ms=15 * MIN):
    """Gộp các fill liên tiếp cách nhau <= gap_ms thành 1 TRANCHE (1 lệnh vào khớp từng phần / chia nhỏ).
    Trên 01pp ~47% 'add' xảy ra trong <15 phút sau fill trước với giá lệch ~6 bps -> thực chất là cùng một lệnh vào, không phải tầng DCA."""
    out = []
    for f in fills:
        q = f["notional"] / f["px"]
        if out and f["t"] - out[-1]["t_last"] <= gap_ms:
            g = out[-1]; g["notional"] += f["notional"]; g["qty"] += q; g["n"] += 1; g["t_last"] = f["t"]
            g["px"] = (g["px"] * (g["qty"] - q) + f["px"] * q) / g["qty"]
        else:
            out.append(dict(t=f["t"], t_last=f["t"], px=f["px"], notional=f["notional"], qty=q, n=1))
    return out


def build_baskets(bot):
    """Trả list basket (sắp theo t0). Mỗi basket: dict(id, sym, side, lev, fills[], closes[], t0, t1, bk_ids)."""
    byk = collections.defaultdict(list)
    for t in bot["trades"]:
        byk[(t["sym"], t["side"])].append(t)
    out = []
    for (sym, side), arr in byk.items():
        arr = sorted(arr, key=lambda x: x["o"])
        cur, end = [], -1
        groups = []
        for t in arr:
            if cur and t["o"] < end:
                cur.append(t); end = max(end, t["c"])
            else:
                if cur: groups.append(cur)
                cur, end = [t], t["c"]
        if cur: groups.append(cur)
        for g in groups:
            fills, closes = [], []
            for i, t in enumerate(g):
                notional = t["mg"] * t["lev"]
                fills.append(dict(t=t["o"], px=t["po"], notional=notional, qty=notional / t["po"], mg=t["mg"], lev=t["lev"]))
                closes.append(dict(t=t["c"], px=t["pc"], qty=notional / t["po"], fill=i, pnl=t["pnl"]))
            qty = sum(f["qty"] for f in fills)
            out.append(dict(sym=sym, side=side, lev=float(np.median([f["lev"] for f in fills])), fills=fills, closes=closes,
                            t0=g[0]["o"], t1=max(c["t"] for c in closes), bk_ids=sorted({t["bk"] for t in g}),
                            notional=sum(f["notional"] for f in fills), avg_px=sum(f["px"] * f["qty"] for f in fills) / qty,
                            pnl=sum(t["pnl"] for t in g)))
    out.sort(key=lambda b: (b["t0"], b["sym"]))
    for i, b in enumerate(out):
        b["id"] = i
        # lợi suất thực tế trên notional (đúng dấu): sum(pnl)/sum(notional)
        b["ret"] = b["pnl"] / b["notional"] * 100
        b["tranches"] = collapse(b["fills"])
    return out


def check_bk(bot, baskets):
    """Kiểm tra mỗi basket ứng đúng 1 bk id (định nghĩa khớp analyze.py)."""
    bad = sum(1 for b in baskets if len(b["bk_ids"]) != 1)
    ids = {b["bk_ids"][0] for b in baskets if len(b["bk_ids"]) == 1}
    return dict(n_baskets=len(baskets), n_bk_ids=len({t["bk"] for t in bot["trades"]}), mismatched=bad, ok=bad == 0 and len(ids) == len(baskets))


_CANDLES = {}


def load_candles(sym):
    """DataFrame 1m đầy đủ của sym (cache), hoặc None nếu thiếu file. Cột: open_time,open,high,low,close,volume."""
    if sym in _CANDLES:
        return _CANDLES[sym]
    p = os.path.join(CANDLE_DIR, sym, "perp", "1m.pkl")
    df = None
    if os.path.exists(p):
        df = pd.read_pickle(p).sort_values("open_time").reset_index(drop=True)
    _CANDLES[sym] = df
    return df


def candle_arrays(sym):
    """dict numpy (t,o,h,l,c,v) hoặc None. t = open_time ms của nến 1m."""
    df = load_candles(sym)
    if df is None:
        return None
    return dict(t=df.open_time.values.astype(np.int64), o=df.open.values, h=df.high.values, l=df.low.values,
                c=df.close.values, v=df.volume.values)


def coverage(bot):
    """Phủ nến theo symbol của bot: [(sym, n_baskets, có file, nến đầu, nến cuối, phủ hết basket?)]."""
    bs = build_baskets(bot)
    res = {}
    for b in bs:
        res.setdefault(b["sym"], []).append(b)
    rows = []
    for sym, arr in sorted(res.items(), key=lambda kv: -len(kv[1])):
        a = candle_arrays(sym)
        if a is None:
            rows.append(dict(sym=sym, baskets=len(arr), file=False)); continue
        rows.append(dict(sym=sym, baskets=len(arr), file=True, first=int(a["t"][0]), last=int(a["t"][-1]),
                         covered=sum(1 for b in arr if b["t0"] >= a["t"][0] and b["t1"] <= a["t"][-1] + MIN)))
    return rows


def window(a, t0, t1):
    """Cắt mảng nến [t0,t1] (ms), trả (slice_start_index, slice_end_index)."""
    i0 = int(np.searchsorted(a["t"], t0, side="left"))
    i1 = int(np.searchsorted(a["t"], t1, side="right"))
    return i0, i1
