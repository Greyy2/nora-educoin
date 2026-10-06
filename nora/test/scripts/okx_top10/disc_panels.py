"""Phase 2 — dựng PANEL điểm quyết định (exit / add / entry) cho từng bot, gộp mọi mã, đặc trưng chuẩn hoá theo chiều lệnh.

QUY ƯỚC THỜI GIAN (không look-ahead):
  - Ma trận đặc trưng giá của mã: hàng j = TRẠNG THÁI SAU KHI nến 1m j đóng, tức tại thời điểm tau_j = t[j] + 60s.
    Mọi đặc trưng ở hàng j chỉ dùng nến <= j (EMA/RSI đệ quy từ đầu, rolling nhân quả, nến khung lớn chỉ tính khi ĐÃ ĐÓNG hẳn <= tau_j).
  - Điểm quyết định là nến i (nhãn = sự kiện xảy ra TRONG nến i). Với LAG=1 (mặc định, chặt chẽ): đặc trưng = hàng j=i-1 (tau_j = đầu nến i),
    giá khớp sim = open nến i. LAG=0 (theo chữ spec "tại/trước nến quyết định"): đặc trưng gồm cả nến i -> nến đó chứa chính lệnh của bot
    (volume/range bị bot tự gây ra) nên LAG=1 là mặc định; LAG=0 chỉ dùng như 1 vòng lặp đo mức rò rỉ.
  - Entry: lưới 5m, tau = bội của 5 phút, đặc trưng = hàng j có tau_j = tau; nhãn = lệnh đầu vào trong [tau, tau+5m).
Đặc trưng có hướng được nhân dấu chiều lệnh (s=+1 long, -1 short) ở bước gom (signed_view), cực trị rolling đổi thành fav/adv.
"""
import os
import numpy as np
import pandas as pd

import load

MIN = 60_000
CACHE = os.environ.get("DISC_CACHE", os.path.expanduser("~/.cache/okx_disc"))
os.makedirs(CACHE, exist_ok=True)

STOCK = {"AAOI", "AAPL", "AMD", "AMZN", "CBRS", "CRCL", "GOOGL", "INTC", "LITE", "META", "MRVL", "MSFT", "MSTR", "MU", "NBIS", "NVDA",
         "PLTR", "QCOM", "SAMSUNG", "SKHY", "SKHYNIX", "SNDK", "SOXL", "SPCX", "TSLA", "DRAM"}
COMMOD = {"XAU", "XAG", "CL"}
MAJOR = {"BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA"}


def sym_class(sym):
    """0 cổ phiếu/ETF perp, 1 hàng hoá (vàng/bạc/dầu), 2 crypto lớn, 3 crypto khác."""
    return 0 if sym in STOCK else 1 if sym in COMMOD else 2 if sym in MAJOR else 3


CLASS_NAMES = {0: "stock", 1: "commodity", 2: "crypto_major", 3: "crypto_other"}


# ======================================================================= đặc trưng giá theo mã (không phụ thuộc bot)
def _rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def _tr(h, l, c):
    pc = c.shift(1)
    return pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)


def _tf_bars(a, tf):
    """Nến khung tf phút (nhãn trái) + thời điểm đóng (ms). Chỉ dùng cho gióng 'đã đóng hẳn'."""
    df = pd.DataFrame(dict(o=a["o"], h=a["h"], l=a["l"], c=a["c"], v=a["v"]), index=pd.to_datetime(a["t"], unit="ms"))
    g = df.resample(f"{tf}min", label="left", closed="left").agg(dict(o="first", h="max", l="min", c="last", v="sum")).dropna()
    end = (g.index.astype("int64") // 10**6 + tf * MIN).astype(np.int64)
    return g, end


def price_matrix(a):
    """-> (names, X float32 [n, F]) hàng j = trạng thái sau khi nến j đóng. Gồm cả nhóm 'ext' (dùng ở các vòng lặp sau)."""
    t = a["t"]; n = len(t)
    tau = t + MIN
    idx = pd.to_datetime(t, unit="ms")
    c = pd.Series(a["c"], index=idx); h = pd.Series(a["h"], index=idx); l = pd.Series(a["l"], index=idx)
    o = pd.Series(a["o"], index=idx); v = pd.Series(a["v"], index=idx)
    F = {}
    r1 = np.log(c).diff() * 100
    vol = r1.rolling(1440, min_periods=240).std()
    for k in (1, 3, 5, 15, 60, 240):
        r = (c / c.shift(k) - 1) * 100
        F[f"ret{k}"] = r
        F[f"zret{k}"] = r / (vol * np.sqrt(k))
    # ATR % (14 nến đã đóng) 1m / 15m / 1h
    atr1m = _tr(h, l, c).rolling(14, min_periods=14).mean() / c * 100
    F["atr1m"] = atr1m
    F["rsi1m"] = _rsi(c)
    for k in (9, 21, 50):
        F[f"ema{k}_1m"] = (c / c.ewm(span=k, adjust=False).mean() - 1) * 100
    # khung lớn: tính trên nến tf đã đóng rồi gióng sang hàng 1m theo thời điểm đóng <= tau_j
    for tf in (5, 15, 60):
        g, end = _tf_bars(a, tf)
        m = np.searchsorted(end, tau, side="right") - 1          # nến tf cuối cùng ĐÃ ĐÓNG tại tau_j
        ok = m >= 0; mm = np.where(ok, m, 0)
        tc, th, tl = g.c, g.h, g.l
        def pick(s):
            x = s.values[mm].astype(np.float64); x[~ok] = np.nan
            return pd.Series(x, index=idx)
        nm = {5: "5m", 15: "15m", 60: "1h"}[tf]
        F[f"rsi{nm}"] = pick(_rsi(tc))
        if tf in (5, 15):
            for k in (9, 21, 50):
                F[f"ema{k}_{nm}"] = (c / pick(tc.ewm(span=k, adjust=False).mean()) - 1) * 100
        mu = pick(tc.rolling(20).mean()); sd = pick(tc.rolling(20).std())
        F[f"bb{nm}"] = (c - (mu - 2 * sd)) / (4 * sd)               # %b (0..1), dùng giá 1m hiện tại so với dải của nến tf đã đóng
        if tf in (15, 60):
            F[f"atr{nm}"] = pick(_tr(th, tl, tc).rolling(14, min_periods=14).mean() / tc * 100)
        # ext: volume z của nến tf đã đóng
        F[f"vz{nm}"] = pick((g.v - g.v.rolling(288, min_periods=48).mean()) / g.v.rolling(288, min_periods=48).std())
    atr1h = F["atr1h"]
    for N in (15, 60, 240, 1440):
        mp = min(N, 60)
        F[f"dhi{N}"] = (c / h.rolling(N, min_periods=mp).max() - 1) * 100
        F[f"dlo{N}"] = (c / l.rolling(N, min_periods=mp).min() - 1) * 100
    cv = c.values
    for sig in (3, 4):
        mag = 10.0 ** (np.floor(np.log10(cv)) - (sig - 1))
        rp = np.round(cv / mag) * mag
        F[f"rnd{sig}"] = pd.Series((cv - rp) / cv * 100, index=idx)
    F["volz"] = (v - v.rolling(1440, min_periods=240).mean()) / v.rolling(1440, min_periods=240).std()
    rng = h - l
    F["rngx"] = rng / rng.rolling(60, min_periods=30).mean().replace(0, np.nan)
    # ---- lịch (tại tau_j)
    mod = ((tau // MIN) % 1440).astype(np.int64)
    cal = {}
    cal["mod"] = mod
    cal["since_open"] = (mod - 810) % 1440; cal["to_open"] = (810 - mod) % 1440
    cal["since_close"] = (mod - 1200) % 1440; cal["to_close"] = (1200 - mod) % 1440
    cal["wday"] = ((tau // (86400_000) + 3) % 7)           # 0=Thứ hai (epoch 1/1/1970 là Thứ năm)
    cal["to_fund"] = (480 - mod % 480) % 480
    # ---- ext (giá)
    hour = idx.floor("1h"); h4 = idx.floor("4h"); day = idx.floor("1D")
    for nm, key in (("h", hour), ("h4", h4), ("d", day)):
        F[f"x_ret_from_{nm}open"] = (c / o.groupby(key).transform("first") - 1) * 100
    dd = pd.DataFrame(dict(h=h, l=l, c=c)).groupby(day).agg(dict(h="max", l="min", c="last"))
    prev = dd.shift(1)
    dmap = lambda col: pd.Series(prev[col].reindex(day).values, index=idx)
    F["x_vs_prevd_close"] = (c / dmap("c") - 1) * 100
    F["x_vs_prevd_high"] = (c / dmap("h") - 1) * 100
    F["x_vs_prevd_low"] = (c / dmap("l") - 1) * 100
    # từ khi mở cửa Mỹ (13:30 UTC) trong ngày; trước 13:30 = NaN
    open_t = ((t // MIN) % 1440)
    us_o = pd.Series(np.where(open_t == 810, a["o"], np.nan), index=idx).groupby(day).transform("first")
    F["x_ret_from_usopen"] = np.where(mod >= 811, (c / us_o - 1) * 100, np.nan)
    body = (c - o) / rng.replace(0, np.nan)
    F["x_body"] = body
    F["x_upwick"] = (h - np.maximum(c, o)) / rng.replace(0, np.nan)
    F["x_lowwick"] = (np.minimum(c, o) - l) / rng.replace(0, np.nan)
    sg = np.sign(c.diff()).fillna(0).values
    chg = np.r_[True, sg[1:] != sg[:-1]]
    grp = np.cumsum(chg)
    streak = pd.Series(sg, index=idx) * (pd.Series(np.ones(n), index=idx).groupby(grp).cumsum())
    F["x_streak"] = streak
    F["x_rank60"] = c.rolling(60, min_periods=30).rank(pct=True)
    F["x_rank240"] = c.rolling(240, min_periods=60).rank(pct=True)
    F["x_atr_ratio"] = atr1m / atr1h
    # ATR-units copies cho khoảng cách (chia ATR 1h)
    for nm in list(F):
        if nm.startswith(("ret", "dhi", "dlo")) and not nm.startswith("rsi"):
            F[nm + "_a"] = F[nm] / atr1h
    for nm in [k for k in F if k.startswith("ema")]:
        F[nm + "_a"] = F[nm] / atr1h
    names = list(F) + ["cal_" + k for k in cal] + ["is_stock", "cls"]
    X = np.empty((n, len(names)), np.float32)
    for k, nm in enumerate(F):
        X[:, k] = np.asarray(F[nm], dtype=np.float64)
    k0 = len(F)
    for k, nm in enumerate(cal):
        X[:, k0 + k] = cal[nm]
    X[:, -2] = 0; X[:, -1] = 0   # is_stock / cls điền khi gom (phụ thuộc mã)
    return names, X


_MAT = {}


def sym_matrix(sym):
    """(names, X, t) của mã, cache đĩa (npy) + RAM; None nếu thiếu nến."""
    if sym in _MAT:
        return _MAT[sym]
    a = load.candle_arrays(sym)
    if a is None:
        _MAT[sym] = None; return None
    p = os.path.join(CACHE, f"mat_{sym}.npy"); pn = os.path.join(CACHE, f"mat_{sym}.names")
    if os.path.exists(p) and os.path.exists(pn):
        names = open(pn).read().split(); X = np.load(p, mmap_mode="r")
    else:
        names, X = price_matrix(a)
        np.save(p, X); open(pn, "w").write(" ".join(names))
        X = np.load(p, mmap_mode="r")
    _MAT[sym] = (names, X, a)
    return _MAT[sym]


DIR_PREFIX = ("ret", "zret", "ema", "rnd", "x_ret", "x_vs", "x_body", "x_streak")


def is_dir(nm):
    return nm.startswith(DIR_PREFIX) and not nm.startswith("rsi")


def signed_view(names, Xrows, s):
    """Hàng đặc trưng thô -> hàng theo chiều lệnh s. Trả (names2, X2 float32)."""
    nm = []; cols = []
    ix = {k: i for i, k in enumerate(names)}
    for k in names:
        if k.startswith(("cal_", "is_stock", "cls")):
            nm.append(k); cols.append(Xrows[:, ix[k]])
        elif k.startswith(("dhi", "dlo")):
            continue
        elif k.startswith("rsi"):
            nm.append("s_" + k); cols.append(s * (Xrows[:, ix[k]] - 50))
        elif k.startswith(("bb", "x_rank")):
            nm.append("s_" + k); cols.append(s * (Xrows[:, ix[k]] - 0.5))
        elif k in ("x_upwick", "x_lowwick"):
            sw = {"x_upwick": "x_lowwick", "x_lowwick": "x_upwick"}[k] if s == -1 else k   # short: râu trên/dưới đổi vai
            nm.append("w_" + k.split("_")[1][:3]); cols.append(Xrows[:, ix[sw]])
        elif is_dir(k):
            nm.append("s_" + k); cols.append(s * Xrows[:, ix[k]])
        else:
            nm.append(k); cols.append(Xrows[:, ix[k]])
    for N in (15, 60, 240, 1440):
        for suf in ("", "_a"):
            hi = Xrows[:, ix[f"dhi{N}{suf}"]]; lo = Xrows[:, ix[f"dlo{N}{suf}"]]
            fav, adv = (hi, lo) if s == 1 else (-lo, -hi)
            nm += [f"d_fav{N}{suf}", f"d_adv{N}{suf}"]; cols += [fav, adv]
    return nm, np.column_stack(cols).astype(np.float32)


# ======================================================================= ngữ cảnh bot (book)
class BotCtx:
    def __init__(self, bot, baskets):
        self.bot = bot; self.baskets = baskets
        self.t0 = np.array([b["t0"] for b in baskets]); self.t1 = np.array([b["t1"] for b in baskets])
        self.side = np.array([1 if b["side"] == "long" else -1 for b in baskets])
        self.sym = np.array([b["sym"] for b in baskets])
        self.o0 = np.sort(self.t0); self.o1 = np.sort(self.t1)
        self.o0s = {sd: np.sort(self.t0[self.side == sd]) for sd in (1, -1)}
        self.o1s = {sd: np.sort(self.t1[self.side == sd]) for sd in (1, -1)}
        tr = sorted(bot["trades"], key=lambda x: x["c"])
        self.tc = np.array([x["c"] for x in tr]); self.tcum = np.r_[0.0, np.cumsum([x["pnl"] for x in tr])]
        self.by_ss = {}
        for b in baskets:
            self.by_ss.setdefault((b["sym"], b["side"]), []).append(b)
        for k in self.by_ss:
            self.by_ss[k].sort(key=lambda b: b["t1"])

    def book(self, tau, sym, side_s, self_bid):
        """Đặc trưng sổ lệnh tại các thời điểm tau (mảng ms) cho (sym, chiều); loại chính basket self_bid."""
        tau = np.asarray(tau)
        n_all = np.searchsorted(self.o0, tau, "right") - np.searchsorted(self.o1, tau, "right")
        n_same = np.searchsorted(self.o0s[side_s], tau, "right") - np.searchsorted(self.o1s[side_s], tau, "right")
        if self_bid is not None:
            b = self.baskets[self_bid]
            alive = ((b["t0"] <= tau) & (tau < b["t1"])).astype(int)
            n_all = n_all - alive; n_same = n_same - alive
        d0 = (tau // 86400_000) * 86400_000
        pnl_day = self.tcum[np.searchsorted(self.tc, tau, "left")] - self.tcum[np.searchsorted(self.tc, d0, "left")]
        # basket đã đóng gần nhất cùng (mã, chiều) (không tính self)
        lst = [b for b in self.by_ss.get((sym, "long" if side_s == 1 else "short"), []) if b["id"] != self_bid]
        t1s = np.array([b["t1"] for b in lst]); rets = np.array([b["ret"] for b in lst])
        since = np.full(len(tau), np.nan); lret = np.full(len(tau), np.nan)
        if len(lst):
            k = np.searchsorted(t1s, tau, "right") - 1
            okk = k >= 0
            since[okk] = (tau[okk] - t1s[k[okk]]) / MIN; lret[okk] = rets[k[okk]]
        # cùng mã chiều ngược lại đang mở
        opp = [b for b in self.baskets if b["sym"] == sym and b["side"] != ("long" if side_s == 1 else "short") and b["id"] != self_bid]
        n_opp = np.zeros(len(tau))
        for b in opp:
            n_opp += ((b["t0"] <= tau) & (tau < b["t1"]))
        return dict(bk_n_open=n_all.astype(np.float32), bk_n_same_side=n_same.astype(np.float32), bk_pnl_day=pnl_day.astype(np.float32),
                    bk_since_last_close=since.astype(np.float32), bk_last_ret=lret.astype(np.float32), bk_n_opp_sym=n_opp.astype(np.float32))


# ======================================================================= đặc trưng vị thế (exit / add)
POS_NAMES = ["upnl", "upnl_a1h", "upnl_a15m", "upnl_a1m", "mfe_last", "mfe_last_a", "mfe_first", "mfe_first_a", "gb", "gb_a", "gb_ratio",
             "gb_first", "gb_first_a", "mae_last", "mae_last_a", "mae_first", "mae_first_a", "mins_first", "mins_last", "n_fill", "n_tr",
             "last_step", "notional_vs_first", "x_mins_since_peak", "x_px_vs_last", "x_px_vs_first", "x_avg_vs_first", "x_mins_since_peak_first",
             "x_upnl_per_step"]


def _seg_cummax(arr, jr, nfv, start_of, fn):
    """Với mỗi hàng (j), cummax của arr[start..j] trong đoạn nf hằng; start = start_of(nf). Trả (M, idx_peak) NaN khi cửa sổ rỗng."""
    R = len(jr); M = np.full(R, np.nan); P = np.full(R, np.nan)
    for nf in np.unique(nfv):
        rows = np.where(nfv == nf)[0]
        sb = start_of(int(nf))
        j = jr[rows]
        okm = j >= sb
        if not okm.any():
            continue
        jmax = j[okm].max()
        seg = fn(arr[sb: jmax + 1])
        cm = seg[1]; pk = seg[2]
        loc = j[okm] - sb
        M[rows[okm]] = cm[loc]; P[rows[okm]] = (pk[loc] + sb)
    return M, P


def _runmax(x):
    cm = np.maximum.accumulate(x)
    pos = np.where(x == cm, np.arange(len(x)), 0)
    return None, cm, np.maximum.accumulate(pos)


def _runmin(x):
    cm = np.minimum.accumulate(x)
    pos = np.where(x == cm, np.arange(len(x)), 0)
    return None, cm, np.maximum.accumulate(pos)


def pos_block(a, names, X, s, jr, ft, fp, fn):
    """Đặc trưng vị thế tại các hàng j=jr (mảng tăng dần). ft/fp/fn: thời điểm, giá, notional các fill (đã sắp). Trả dict mảng float32."""
    jr = np.asarray(jr)
    tau = a["t"][jr] + MIN
    nfv = np.searchsorted(ft, tau, "left")
    assert (nfv >= 1).all()
    cq = np.cumsum(fn / fp); cn = np.cumsum(fn)
    avg = cn[nfv - 1] / cq[nfv - 1]
    c = a["c"][jr].astype(np.float64)
    fbar = np.searchsorted(a["t"], ft, "right") - 1
    sh = s * (a["h"] if s == 1 else a["l"]); sa = s * (a["l"] if s == 1 else a["h"])
    sh = sh.astype(np.float64); sa = sa.astype(np.float64)
    ix = {k: i for i, k in enumerate(names)}
    atr1h = np.asarray(X[jr, ix["atr1h"]], np.float64); atr15 = np.asarray(X[jr, ix["atr15m"]], np.float64); atr1 = np.asarray(X[jr, ix["atr1m"]], np.float64)
    lfb = fbar[nfv - 1]
    # since last fill: reset mỗi lần có fill; since first: cửa sổ (f0, j]
    Mlast, Plast = _seg_cummax(sh, jr, nfv, lambda nf: fbar[nf - 1] + 1, _runmax)
    Alast, _ = _seg_cummax(-sa, jr, nfv, lambda nf: fbar[nf - 1] + 1, _runmax)
    Mfirst, Pfirst = _seg_cummax(sh, jr, nfv, lambda nf: fbar[0] + 1, _runmax)
    Afirst, _ = _seg_cummax(-sa, jr, nfv, lambda nf: fbar[0] + 1, _runmax)
    Alast = -Alast; Afirst = -Afirst
    upnl = (s * c / avg - s) * 100
    def mfe(M):
        x = (M / avg - s) * 100
        return np.where(np.isnan(x), 0.0, np.maximum(x, 0.0))
    def mae(A):
        x = (A / avg - s) * 100
        return np.where(np.isnan(x), 0.0, np.minimum(x, 0.0))
    mfl = np.maximum(mfe(Mlast), np.maximum(upnl, 0)); mff = np.maximum(mfe(Mfirst), np.maximum(upnl, 0))
    gb = mfl - upnl; gbf = mff - upnl
    mal = mae(Alast); maf = mae(Afirst)
    mal = np.minimum(mal, np.minimum(upnl, 0)); maf = np.minimum(maf, np.minimum(upnl, 0))
    ntr = np.ones(len(ft), int)
    gaps = np.diff(ft) > 15 * MIN
    ntr = np.r_[1, 1 + np.cumsum(gaps)]
    lstep = np.zeros(len(ft))
    if len(ft) > 1:
        lstep[1:] = (s * (fp[:-1] - fp[1:]) / fp[:-1]) * 100          # >0: add bình quân giá (đi ngược)
    nz = lambda x: np.where(x > 0, x, np.nan)
    atr1h, atr15, atr1 = (np.where(x > 0, x, np.nan) for x in (atr1h, atr15, atr1))
    d = dict(upnl=upnl, upnl_a1h=upnl / atr1h, upnl_a15m=upnl / atr15, upnl_a1m=upnl / atr1,
             mfe_last=mfl, mfe_last_a=mfl / atr1h, mfe_first=mff, mfe_first_a=mff / atr1h,
             gb=gb, gb_a=gb / atr1h, gb_ratio=np.where(mfl > 0, gb / np.where(mfl > 0, mfl, 1), 0.0),
             gb_first=gbf, gb_first_a=gbf / atr1h, mae_last=mal, mae_last_a=mal / atr1h, mae_first=maf, mae_first_a=maf / atr1h,
             mins_first=(tau - ft[0]) / MIN, mins_last=(tau - ft[nfv - 1]) / MIN, n_fill=nfv.astype(float), n_tr=ntr[nfv - 1].astype(float),
             last_step=lstep[nfv - 1], notional_vs_first=cn[nfv - 1] / fn[0],
             x_mins_since_peak=np.where(np.isnan(Plast), (tau - ft[nfv - 1]) / MIN, jr - Plast),
             x_px_vs_last=(s * (c / fp[nfv - 1] - 1)) * 100, x_px_vs_first=(s * (c / fp[0] - 1)) * 100,
             x_avg_vs_first=(s * (avg / fp[0] - 1)) * 100,
             x_mins_since_peak_first=np.where(np.isnan(Pfirst), (tau - ft[0]) / MIN, jr - Pfirst),
             x_upnl_per_step=upnl / np.where(np.abs(lstep[nfv - 1]) > 1e-9, np.abs(lstep[nfv - 1]), np.nan))
    return {k: np.asarray(v, np.float32) for k, v in d.items()}


# ======================================================================= panel
def bar_of(a, t):
    """Chỉ số nến chứa mốc t (ms)."""
    return int(np.searchsorted(a["t"], t, "right")) - 1


def static_block(ctx, B, a, names, X, s, jr, with_book=True):
    """Đặc trưng không phụ thuộc vị thế (giá + lịch + sổ lệnh) tại các hàng j=jr. DataFrame float32."""
    jr = np.asarray(jr)
    nm, Xs = signed_view(names, np.asarray(X[jr]), s)
    df = pd.DataFrame(Xs, columns=nm)
    df["is_stock"] = float(sym_class(B["sym"]) == 0); df["cls"] = float(sym_class(B["sym"]))
    df["side"] = float(s)
    if with_book:
        tau = a["t"][jr] + MIN
        for k, v in ctx.book(tau, B["sym"], s, B["id"] if B["id"] >= 0 and B["id"] < len(ctx.baskets) and B.get("real", True) else None).items():
            df[k] = v
    return df.replace([np.inf, -np.inf], np.nan)


def block_features(ctx, B, a, names, X, s, jr, ft, fp, fn, lag, with_pos=True):
    """Toàn bộ đặc trưng cho các hàng j=jr của basket B (hoặc entry nếu with_pos=False). Trả DataFrame float32."""
    df = static_block(ctx, B, a, names, X, s, jr, True)
    if with_pos:
        for k, v in pos_block(a, names, X, s, np.asarray(jr), ft, fp, fn).items():
            df[k] = v
    return df.replace([np.inf, -np.inf], np.nan)


def basket_rows(ctx, B, post_min=60, lag=1):
    """Hàng quyết định (nến i) của 1 basket: từ nến sau fill đầu đến nến chứa lần đóng đầu (+ post_min phút sau lần đóng CUỐI cho sim).
    Trả (meta DataFrame, feature DataFrame) hoặc None."""
    sm = sym_matrix(B["sym"])
    if sm is None:
        return None
    names, X, a = sm
    s = 1 if B["side"] == "long" else -1
    fl = B["fills"]
    ft = np.array([f["t"] for f in fl], np.int64); fp = np.array([f["px"] for f in fl]); fn = np.array([f["notional"] for f in fl])
    t_fc = min(c["t"] for c in B["closes"]); t_lc = B["t1"]
    i_f0 = bar_of(a, ft[0]); i_fc = bar_of(a, t_fc); i_lc = bar_of(a, t_lc); i_end_post = min(len(a["t"]) - 1, bar_of(a, B["t1"]) + post_min)
    n_before = int((ft < t_fc).sum())
    i_lf = bar_of(a, ft[n_before - 1])
    i_start = i_f0 + 1
    if i_fc < i_start or i_start - lag < 0:
        return None
    ii = np.arange(i_start, i_end_post + 1)
    jr = ii - lag
    if jr[0] < 0:
        return None
    feat = block_features(ctx, B, a, names, X, s, jr, ft, fp, fn, lag)
    tau_dec = a["t"][ii]                                   # đầu nến i
    nf = np.searchsorted(ft, a["t"][jr] + MIN, "left")
    # nhãn add: có fill (thô) / bắt đầu tranche trong nến i
    fbar = np.searchsorted(a["t"], ft, "right") - 1
    cnt = np.zeros(len(ii), int); sel = fbar[1:]; mk = (sel >= i_start) & (sel <= i_end_post)
    np.add.at(cnt, sel[mk] - i_start, 1)
    trs = [g["t"] for g in B["tranches"]][1:]
    trb = np.array([bar_of(a, t) for t in trs], int)
    cnt_tr = np.bincount((trb[(trb >= i_start) & (trb <= i_end_post)] - i_start), minlength=len(ii)) if len(trb) else np.zeros(len(ii), int)
    since_last = (a["t"][jr] + MIN - ft[np.maximum(nf - 1, 0)]) / MIN
    meta = pd.DataFrame(dict(bid=B["id"], sym=B["sym"], s=s, i=ii, tau=tau_dec, nf=nf,
                             exit_y=(ii == i_fc).astype(np.int8), exit_last_y=(ii == i_lc).astype(np.int8), pre_last=(ii <= i_lc).astype(np.int8), post=(ii > i_fc).astype(np.int8), after_last=(ii >= i_lf + 1).astype(np.int8),
                             add_y=(cnt > 0).astype(np.int8), add_tr_y=(cnt_tr > 0).astype(np.int8), tr_ok=(since_last > 15).astype(np.int8),
                             pre_close=(ii < i_fc).astype(np.int8)))
    return meta, feat


def entry_rows(ctx, sym, side_s, p_keep, rng, lo, hi, lag=1):
    """Hàng entry (lưới 5m) của (mã, chiều). Giữ toàn bộ dương + âm với xác suất p_keep (w=1/p)."""
    sm = sym_matrix(sym)
    if sm is None:
        return None
    names, X, a = sm
    side = "long" if side_s == 1 else "short"
    bs = ctx.by_ss.get((sym, side), [])
    t0 = np.array(sorted(b["t0"] for b in bs), np.int64)
    G = 5 * MIN
    first = max(lo, a["t"][0] + 1500 * MIN); last = min(hi, a["t"][-1])
    grid = np.arange(int(np.ceil(first / G)) * G, int(last // G) * G + 1, G, dtype=np.int64)
    if len(grid) == 0:
        return None
    # bỏ các mốc đang có basket mở trên (mã, chiều)
    op = np.zeros(len(grid), bool)
    for b in bs:
        op |= (grid >= b["t0"]) & (grid < b["t1"])
    pos = np.zeros(len(grid), bool)
    if len(t0):
        k = np.searchsorted(t0, grid, "left")
        nxt = np.where(k < len(t0), t0[np.minimum(k, len(t0) - 1)], np.iinfo(np.int64).max)
        pos = nxt < grid + G
    keep = ~op & (pos | (rng.random(len(grid)) < p_keep))
    grid = grid[keep]; pos = pos[keep]
    if len(grid) == 0:
        return None
    jr = np.searchsorted(a["t"], grid - MIN)                     # nến đóng ngay trước tau
    okj = (jr >= 0) & (a["t"][np.minimum(jr, len(a["t"]) - 1)] == grid - MIN)
    grid = grid[okj]; pos = pos[okj]; jr = jr[okj]
    if len(grid) == 0:
        return None
    B = dict(sym=sym, id=-1)
    feat = block_features(ctx, B, a, names, X, side_s, jr, None, None, None, lag, with_pos=False)
    meta = pd.DataFrame(dict(bid=-1, sym=sym, s=side_s, i=jr, tau=grid, entry_y=pos.astype(np.int8), w=np.where(pos, 1.0, 1.0 / p_keep)))
    return meta, feat


def entry_negative_count(ctx, syms, lo, hi):
    """Ước tính số hàng âm tổng (để chọn p_keep sao cho <=cap)."""
    n = 0
    for sym in syms:
        sm = sym_matrix(sym)
        if sm is None:
            continue
        a = sm[2]
        first = max(lo, a["t"][0] + 1500 * MIN); last = min(hi, a["t"][-1])
        n += 2 * max(0, int((last - first) // (5 * MIN)))
    return n


def split_info(bot_name):
    bot = load.get_bot(bot_name)
    allb = load.build_baskets(bot)
    baskets = [B for B in allb if load.candle_arrays(B["sym"]) is not None and B["t0"] >= load.candle_arrays(B["sym"])["t"][0]]
    n_tr = int(len(baskets) * 0.6)
    return bot, allb, baskets, baskets[n_tr]["t0"]


def build_panels(bot_name, lag=1, entry_cap=200_000, seed=0, post_min=60, force=False):
    """Dựng + cache 3 panel của bot. Trả dict(exit=(meta,feat), entry=(meta,feat), ctx, baskets, split_t)."""
    import pickle, time
    from load import slug
    path = os.path.join(CACHE, f"panels_{slug(bot_name)}_lag{lag}.pkl")
    bot, allb, baskets, split_t = split_info(bot_name)
    ctx = BotCtx(bot, allb)
    if os.path.exists(path) and not force:
        P = pickle.load(open(path, "rb"))
        P.update(ctx=ctx, baskets=baskets, split_t=split_t, bot=bot)
        return P
    t_start = time.time()
    rng = np.random.default_rng(seed)
    ms, fs = [], []
    for B in allb:
        r = basket_rows(ctx, B, post_min, lag)
        if r is not None:
            ms.append(r[0]); fs.append(r[1])
    ex_meta = pd.concat(ms, ignore_index=True); ex_feat = pd.concat(fs, ignore_index=True)
    print(f"[{bot_name}] exit/add rows {len(ex_meta)} ({time.time() - t_start:.0f}s)", flush=True)
    syms = sorted({B["sym"] for B in allb})
    lo = min(B["t0"] for B in allb) - 6 * 3600_000; hi = max(B["t0"] for B in allb) + 5 * MIN
    nneg = entry_negative_count(ctx, syms, lo, hi)
    p_keep = min(1.0, entry_cap / max(1, nneg))
    ems, efs = [], []
    for sym in syms:
        for sd in (1, -1):
            r = entry_rows(ctx, sym, sd, p_keep, rng, lo, hi, lag)
            if r is not None:
                ems.append(r[0]); efs.append(r[1])
    en_meta = pd.concat(ems, ignore_index=True); en_feat = pd.concat(efs, ignore_index=True)
    print(f"[{bot_name}] entry rows {len(en_meta)} pos {int(en_meta.entry_y.sum())} p_keep {p_keep:.3f} ({time.time() - t_start:.0f}s)", flush=True)
    P = dict(exit=(ex_meta, ex_feat), entry=(en_meta, en_feat), p_keep=p_keep, lag=lag)
    pickle.dump(P, open(path, "wb"), protocol=4)
    P.update(ctx=ctx, baskets=baskets, split_t=split_t, bot=bot)
    return P


# ======================================================================= tự kiểm tra look-ahead
def _pos_slow(at, s, ft, fp, fn, tau):
    """Tính lại đặc trưng vị thế bằng vòng lặp thuần trên dữ liệu CẮT tại tau (nến <= j)."""
    k = [x for x in range(len(ft)) if ft[x] < tau]
    q = sum(fn[x] / fp[x] for x in k); avg = sum(fn[x] for x in k) / q
    j = len(at["t"]) - 1
    c = at["c"][j]
    fb = lambda x: int(np.searchsorted(at["t"], ft[x], "right")) - 1
    def ext(start):
        hi = [s * (at["h"][b] if s == 1 else at["l"][b]) for b in range(start + 1, j + 1)]
        lo = [s * (at["l"][b] if s == 1 else at["h"][b]) for b in range(start + 1, j + 1)]
        return (max(hi) if hi else None), (min(lo) if lo else None)
    upnl = s * (c / avg - 1) * 100
    Ml, Al = ext(fb(k[-1])); Mf, Af = ext(fb(0))
    mfe = lambda M: max(0.0, (M / avg - s) * 100) if M is not None else 0.0
    mae = lambda A: min(0.0, (A / avg - s) * 100) if A is not None else 0.0
    mfl = max(mfe(Ml), upnl, 0); mff = max(mfe(Mf), upnl, 0)
    ntr = 1 + sum(1 for x in range(1, len(k)) if ft[x] - ft[x - 1] > 15 * MIN)
    return dict(upnl=upnl, mfe_last=mfl, mfe_first=mff, gb=mfl - upnl, mae_last=min(mae(Al), upnl, 0), mae_first=min(mae(Af), upnl, 0),
                n_fill=len(k), n_tr=ntr, mins_last=(tau - ft[k[-1]]) / MIN)


def selfcheck(bot_name, n=6, seed=1, lag=1):
    """Kiểm tra không look-ahead: với vài hàng ngẫu nhiên, tính lại đặc trưng từ dữ liệu cắt tại thời điểm quyết định và so với panel."""
    rng = np.random.default_rng(seed)
    Pn = build_panels(bot_name, lag=lag)
    bad = 0; res = []
    for kind in ("exit", "entry"):
        meta, feat = Pn[kind]
        for r in rng.choice(len(meta), n, replace=False):
            row = meta.iloc[r]; sym = row.sym; s = int(row.s)
            names, X, a = sym_matrix(sym)
            j = int(row.i) - (lag if kind == "exit" else 0)
            at = {k: v[: j + 1] for k, v in a.items()}
            names2, Xt = price_matrix(at)
            ref = np.asarray(Xt[-1], np.float64); got = np.asarray(X[j], np.float64)
            m = ~(np.isnan(ref) & np.isnan(got))
            err = np.abs(ref - got)[m]
            ok_price = bool(np.all(err <= 1e-4 + 1e-4 * np.abs(got[m]))) and not (np.isnan(ref) ^ np.isnan(got)).any()
            ok_pos = True; dev = 0.0
            if kind == "exit":
                B = Pn["ctx"].baskets[int(row.bid)]
                ft = np.array([f["t"] for f in B["fills"]], np.int64); fp = np.array([f["px"] for f in B["fills"]]); fn = np.array([f["notional"] for f in B["fills"]])
                slow = _pos_slow(at, s, ft, fp, fn, a["t"][j] + MIN)
                for k, v in slow.items():
                    g = float(feat.iloc[r][k])
                    dev = max(dev, abs(g - v) / (1 + abs(v)))
                ok_pos = dev < 1e-3
            res.append(dict(kind=kind, sym=sym, tau=int(row.tau), price_ok=ok_price, price_maxerr=float(err.max()) if len(err) else 0.0, pos_ok=ok_pos, pos_dev=dev))
            bad += (not ok_price) + (not ok_pos)
    return dict(n_checked=len(res), n_bad=bad, rows=res)
