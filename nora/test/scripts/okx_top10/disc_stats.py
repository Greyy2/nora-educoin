"""Chỉ số báo cáo của bot — SAO CHÉP khối tính chỉ số từ /home/vmc03/norabt/none/okx-top10/analyze.py (không suy diễn lại công thức).
stats(trades) nhận danh sách trade theo schema bots.json {sym, side, lev, o, c, po, pc, pnl, pr, mg, mae?, add?, bk?}; tự tính lại
mae/mom (từ nến 1H dựng từ 1m), add/bk theo chuỗi chồng lấn, rồi các chỉ số y như analyze.py. So sánh thật vs sim dùng CÙNG hàm này."""
import bisect, statistics as S
from collections import Counter, defaultdict
import numpy as np
import pandas as pd

import load

H = 3600_000


def med(a):
    return S.median(a) if a else None


_H1 = {}


def hourly(sym):
    """Nến 1H [t, o, h, l, c] dựng từ 1m (cùng cấu trúc candles/<sym>.json của analyze.py: [ts, o, h, l, c])."""
    if sym in _H1:
        return _H1[sym]
    a = load.candle_arrays(sym)
    if a is None:
        _H1[sym] = []; return []
    df = pd.DataFrame(dict(o=a["o"], h=a["h"], l=a["l"], c=a["c"]), index=pd.to_datetime(a["t"], unit="ms"))
    g = df.resample("1h").agg(dict(o="first", h="max", l="min", c="last")).dropna()
    k = [[int(t.value // 10**6), r.o, r.h, r.l, r.c] for t, r in zip(g.index, g.itertuples())]
    _H1[sym] = k
    return k


def enrich(T):
    """mae (% giá, xấu nhất so với giá vào) và mom (động lượng 24h tại lúc vào) y như analyze.py (nến 1H)."""
    for t in T:
        k = hourly(t["sym"]); t["mae"] = None; t["mom"] = None
        if not k:
            continue
        ts = [x[0] for x in k]
        i0 = bisect.bisect_right(ts, t["o"]) - 1; i1 = bisect.bisect_right(ts, t["c"]) - 1
        if i0 >= 0 and i1 >= i0:
            seg = k[i0:i1 + 1]
            if t["side"] == "long":
                t["mae"] = min(0, (min(x[3] for x in seg) / t["po"] - 1) * 100)
            else:
                t["mae"] = min(0, (1 - max(x[2] for x in seg) / t["po"]) * 100)
        j = i0 - 1; j24 = j - 24
        if j24 >= 0:
            mv = k[j][4] / k[j24][4] - 1
            t["mom"] = (mv > 0) == (t["side"] == "long") if abs(mv) > 0.002 else None


def stats(T, with_mae=True):
    """T: list trade (sẽ được gán add/bk/mae/mom). Trả dict chỉ số báo cáo (cùng tên khoá analyze.py / bots.json)."""
    T = sorted(T, key=lambda x: x["o"])
    if with_mae:
        enrich(T)
    adds = 0; down = 0; steps = []; baskets = []; byk = defaultdict(list)
    for t in T:
        byk[(t["sym"], t["side"])].append(t)
    for key, arr in byk.items():
        cur = []; end = -1
        for t in arr:
            if cur and t["o"] < end:
                adds += 1; t["add"] = True; prev = cur[-1]
                adv = (prev["po"] - t["po"]) / prev["po"] * 100 if t["side"] == "long" else (t["po"] - prev["po"]) / prev["po"] * 100
                if adv > 0:
                    down += 1; steps.append(adv)
                cur.append(t); end = max(end, t["c"])
            else:
                if cur:
                    baskets.append(cur)
                cur = [t]; end = t["c"]; t["add"] = False
        if cur:
            baskets.append(cur)
    bid = {id(t): i for i, bk in enumerate(sorted(baskets, key=lambda bk: bk[0]["o"])) for t in bk}
    for t in T:
        t["bk"] = bid[id(t)]
    n = len(T)
    if n == 0:
        return dict(n=0)
    W = [t for t in T if t["pnl"] > 0]; L = [t for t in T if t["pnl"] <= 0]
    gw = sum(t["pnl"] for t in W); gl = -sum(t["pnl"] for t in L)
    hold = lambda a: [(t["c"] - t["o"]) / H for t in a]
    wins_mae = [t["mae"] for t in W if t["mae"] is not None]
    moms = [t["mom"] for t in T if t["mom"] is not None]
    top5 = sum(sorted([t["pnl"] for t in W], reverse=True)[:5])
    symc = Counter(t["sym"] for t in T)
    return dict(
        n=n, first=T[0]["o"], last=max(t["c"] for t in T), perDay=n / max(1, (max(t["c"] for t in T) - T[0]["o"]) / 86400000),
        win=len(W) / n * 100, realized=gw - gl, pf=gw / gl if gl else None, payoff=(gw / len(W)) / (gl / len(L)) if W and L and gl else None,
        longPct=sum(t["side"] == "long" for t in T) / n * 100, levMed=med([t["lev"] for t in T]), levMax=max(t["lev"] for t in T),
        holdMed=med(hold(T)), holdWin=med(hold(W)), holdLoss=med(hold(L)),
        maxLoss=min(t["pnl"] for t in T), maxWin=max(t["pnl"] for t in T), top5Share=top5 / gw * 100 if gw else None,
        addPct=adds / n * 100, addDownPct=down / n * 100, stepMed=med(steps), maxLayers=max(len(bk) for bk in baskets), baskets=len(baskets),
        winMaeMed=med(wins_mae), winMaeP90=sorted(wins_mae)[int(len(wins_mae) * 0.1)] if wins_mae else None,
        momPct=sum(moms) / len(moms) * 100 if moms else None, syms=symc.most_common())


# 12 chỉ số lõi cho "stats match score" (loại: n tuyệt đối vì phụ thuộc cửa sổ; dùng perDay) — % so với % (+-5 điểm), còn lại tương đối +-20%
CORE = ["perDay", "win", "pf", "payoff", "longPct", "holdMed", "top5Share", "addPct", "addDownPct", "stepMed", "maxLayers", "baskets"]
PCT = {"win", "longPct", "top5Share", "addPct", "addDownPct"}


def compare(real, sim):
    """Bảng real | sim | sai số tương đối, + stats match score (chia sẻ trong 12 chỉ số lõi nằm trong +-20% hoặc +-5 điểm %)."""
    rows = {}; ok = 0
    allk = CORE + ["levMed", "holdWin", "holdLoss", "maxLoss", "maxWin", "realized", "momPct", "winMaeMed", "n"]
    for k in allk:
        r, s = real.get(k), sim.get(k)
        if r is None or s is None:
            rows[k] = dict(real=r, sim=s, rel_err=None, ok=False); continue
        rel = (s - r) / abs(r) if r else None
        good = (abs(s - r) <= 5) if k in PCT else (rel is not None and abs(rel) <= 0.20)
        rows[k] = dict(real=round(r, 3), sim=round(s, 3), rel_err=None if rel is None else round(rel, 3), ok=bool(good))
        if k in CORE:
            ok += bool(good)
    return dict(rows=rows, stats_match_score=round(ok / len(CORE), 3), n_core=len(CORE), n_ok=ok)


def mix_overlap(real, sim):
    """1 - total variation distance giữa 2 phân phối mã (theo số sub-position)."""
    a = dict(real.get("syms") or []); b = dict(sim.get("syms") or [])
    na = sum(a.values()) or 1; nb = sum(b.values()) or 1
    return round(1 - 0.5 * sum(abs(a.get(k, 0) / na - b.get(k, 0) / nb) for k in set(a) | set(b)), 3)


def daily_corr(real_T, sim_T, lo, hi):
    """Tương quan chuỗi PnL thực hiện theo NGÀY đóng (UTC) và đường cộng dồn hai bên."""
    days = np.arange(lo // 86400_000, hi // 86400_000 + 1)
    def series(T):
        d = np.zeros(len(days))
        for t in T:
            k = t["c"] // 86400_000 - days[0]
            if 0 <= k < len(days):
                d[k] += t["pnl"]
        return d
    a, b = series(real_T), series(sim_T)
    corr = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else None
    # tương quan có chuẩn hoá theo vốn: dùng dấu ngày (cùng lãi/lỗ)
    sign = float(np.mean(np.sign(a) == np.sign(b)))
    return dict(daily_corr=None if corr is None else round(corr, 3), day_sign_agree=round(sign, 3), n_days=len(days),
                days=[int(x) for x in days], real_cum=[round(float(x), 1) for x in np.cumsum(a)], sim_cum=[round(float(x), 1) for x in np.cumsum(b)])


def basket_overlap(real_T, sim_T, tols=(15, 60)):
    """% basket thật có basket sim cùng (mã, chiều) mở trong +-tol phút (recall) và ngược lại (precision). Basket = fill đầu của chuỗi (add=False)."""
    ra = defaultdict(list); sa = defaultdict(list)
    for t in real_T:
        if not t.get("add"):
            ra[(t["sym"], t["side"])].append(t["o"])
    for t in sim_T:
        if not t.get("add"):
            sa[(t["sym"], t["side"])].append(t["o"])
    out = {}
    for tol in tols:
        ms = tol * 60_000
        def hit(A, B):
            h = n = 0
            for k, v in A.items():
                b = np.array(sorted(B.get(k, [])))
                for x in v:
                    n += 1
                    if len(b) and np.abs(b - x).min() <= ms:
                        h += 1
            return h, n
        h1, n1 = hit(ra, sa); h2, n2 = hit(sa, ra)
        out[f"recall_{tol}"] = round(100 * h1 / n1, 2) if n1 else None
        out[f"precision_{tol}"] = round(100 * h2 / n2, 2) if n2 else None
    out["n_real_baskets"] = sum(len(v) for v in ra.values()); out["n_sim_baskets"] = sum(len(v) for v in sa.values())
    return out
