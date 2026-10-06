"""Phase 4 - IMPLIED EXIT FITTING (in-sample, mô tả).  Xem IMPLIED_SPEC.md.

Vào lệnh/add THẬT (replay đúng từng fill của bots.json); chỉ GIẢ THUYẾT luật thoát (TP / SL / trailing / hoà vốn / thời gian),
mức của luật = công thức khớp từ chính "sự kiện thoát ngầm" của bot (Bước 1-2), rồi tìm hệ số nhân + tuỳ chọn trên lưới (Bước 3).
Mọi kết quả là IN-SAMPLE (khớp mô tả trên toàn bộ dữ liệu), không phải dự báo ngoài mẫu.

Quy ước engine (không look-ahead):
  - fill thật k kích hoạt từ nến SAU nến chứa fill (không xét thoát trong nến vừa vào lệnh);
  - mỗi nến: kiểm tra luật bằng open/high/low của chính nến đó nhưng MỨC dừng/trailing chỉ dựa trên dữ liệu các nến ĐÃ ĐÓNG
    (đỉnh/đáy tính đến nến trước); stop kiểm tra TRƯỚC TP trong cùng nến (stop-first); gap qua mức -> khớp tại open;
  - thoát theo thời gian khớp tại close của nến; hết horizon (t1 thật + 60 phút) mà chưa thoát -> đóng cưỡng bức tại close, closed=False;
  - phí 3.5 bps/chiều (cùng match.py), funding bỏ qua.
"""
import math
import numpy as np
import pandas as pd
import numba as nb

import load
import match
import disc_stats as ST

MIN = 60_000
H1 = 3600_000
DAY = 86400_000
FEE = 3.5e-4            # mỗi chiều (cùng match.py)
HORIZON_MIN = 60

STOCK = {"AAOI", "AAPL", "AMD", "AMZN", "CBRS", "CRCL", "GOOGL", "INTC", "LITE", "META", "MRVL", "MSFT", "MSTR", "MU", "NBIS", "NVDA",
         "PLTR", "QCOM", "SAMSUNG", "SKHY", "SKHYNIX", "SNDK", "SOXL", "SPCX", "TSLA", "DRAM"}
COMMOD = {"XAU", "XAG", "CL"}
MAJOR = {"BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA"}
CLS_NAMES = {0: "cổ phiếu/ETF perp", 1: "hàng hóa", 2: "crypto lớn", 3: "crypto khác"}


def sym_class(sym):
    return 0 if sym in STOCK else 1 if sym in COMMOD else 2 if sym in MAJOR else 3


# ===================================================================== ATR theo khung (đã đóng nến)
_ATR = {}


def atr_arrays(sym, a):
    """ATR% (14 nến, SMA của true range / close * 100) cho 1m / 15m / 1h, căn theo từng hàng nến 1m: chỉ dùng nến khung lớn ĐÃ ĐÓNG
    tại open của hàng đó."""
    if sym in _ATR:
        return _ATR[sym]
    t = a["t"]
    df = pd.DataFrame(dict(o=a["o"], h=a["h"], l=a["l"], c=a["c"]), index=pd.to_datetime(t, unit="ms"))
    out = {}
    for name, tf in (("atr1", 1), ("atr15", 15), ("atr60", 60)):
        g = df if tf == 1 else df.resample(f"{tf}min").agg(dict(o="first", h="max", l="min", c="last")).dropna()
        pc = g.c.shift(1)
        tr = np.maximum(g.h - g.l, np.maximum((g.h - pc).abs(), (g.l - pc).abs()))
        tr = tr.fillna(g.h - g.l)
        atr = (tr.rolling(14, min_periods=3).mean() / g.c * 100).values
        avail = (g.index.values.astype("datetime64[ms]").astype(np.int64)) + tf * MIN
        idx = np.searchsorted(avail, t, side="right") - 1
        v = np.where(idx >= 0, atr[np.clip(idx, 0, None)], np.nan)
        out[name] = v
    _ATR[sym] = out
    return out


# ===================================================================== dữ liệu bot đã chuẩn bị (mảng phẳng cho numba)
class Data:
    """Baskets đủ nến 1m + mảng phẳng nến [off[b]:off[b+1]] (từ nến SAU nến fill đầu đến t1 thật + 60 phút) + fill (kích hoạt)."""

    def __init__(self, bot, verbose=True):
        self.bot = bot; self.name = bot["name"]
        allb = load.build_baskets(bot)
        keep = []; self.dropped = []
        arr = {}
        for b in allb:
            a = arr.get(b["sym"]) or load.candle_arrays(b["sym"])
            if a is None:
                self.dropped.append((b["id"], b["sym"], "thiếu file nến")); continue
            arr[b["sym"]] = a
            if b["t0"] < a["t"][0] or b["t1"] > a["t"][-1] + MIN:
                self.dropped.append((b["id"], b["sym"], "nến không phủ hết basket")); continue
            keep.append(b)
        self.B = keep; self.n = len(keep)
        self.cand = arr
        T = []; O = []; Hh = []; Ll = []; C = []; off = [0]
        FT = []; FPX = []; FNOT = []; FACT = []; foff = [0]
        sidx0 = []; self.i0 = []; self.i1 = []
        self.s = np.array([1 if b["side"] == "long" else -1 for b in keep], np.int64)
        self.lev = np.array([b["lev"] for b in keep], float)
        self.cls = np.array([sym_class(b["sym"]) for b in keep], np.int64)
        self.t0 = np.array([b["t0"] for b in keep], np.int64)
        self.t1 = np.array([b["t1"] for b in keep], np.int64)
        self.real_px = np.zeros(self.n); self.real_pnl = np.array([b["pnl"] for b in keep]); self.real_not = np.array([b["notional"] for b in keep])
        self.real_ret = np.array([b["ret"] for b in keep])
        for k, b in enumerate(keep):
            a = arr[b["sym"]]
            i0 = int(np.searchsorted(a["t"], (b["t0"] // MIN + 1) * MIN, side="left"))
            i1 = int(np.searchsorted(a["t"], b["t1"] + HORIZON_MIN * MIN, side="right"))
            i1 = max(i1, i0 + 1)
            self.i0.append(i0); self.i1.append(i1)
            base = off[-1]
            ts = a["t"][i0:i1]
            T.append(ts); O.append(a["o"][i0:i1]); Hh.append(a["h"][i0:i1]); Ll.append(a["l"][i0:i1]); C.append(a["c"][i0:i1])
            off.append(base + len(ts))
            for f in b["fills"]:
                act = int(np.searchsorted(ts, (f["t"] // MIN + 1) * MIN, side="left"))
                FT.append(f["t"]); FPX.append(f["px"]); FNOT.append(f["notional"]); FACT.append(base + min(act, len(ts) - 1))
            foff.append(len(FT))
            cl_last = [c for c in b["closes"] if abs(c["t"] - b["t1"]) <= 2000]
            self.real_px[k] = sum(c["px"] * c["qty"] for c in cl_last) / sum(c["qty"] for c in cl_last)
        self.T = np.concatenate(T); self.O = np.concatenate(O); self.H = np.concatenate(Hh); self.L = np.concatenate(Ll); self.C = np.concatenate(C)
        self.off = np.array(off, np.int64)
        self.FT = np.array(FT, np.int64); self.FPX = np.array(FPX); self.FNOT = np.array(FNOT); self.FACT = np.array(FACT, np.int64)
        self.foff = np.array(foff, np.int64)
        self.nlay = np.diff(self.foff)
        self.hold_min = (self.t1 - self.t0) / MIN
        self.vn_hour = ((self.t0 // H1 + 7) % 24).astype(int)
        self.wday = ((self.t0 // DAY + 3) % 7).astype(int)
        # tỉ lệ staged (đóng từng tầng lệch giờ)
        self.staged = np.array([len({round(c["t"] / 2000) for c in b["closes"]}) > 1 for b in keep])
        self.basket_ids = np.array([b["id"] for b in keep])
        if verbose:
            print(f"[{self.name}] baskets {self.n}/{len(allb)} (bỏ {len(self.dropped)}), nến phẳng {len(self.T)}, fill {len(self.FT)}, staged {int(self.staged.sum())}")

    def real_trades(self):
        """Danh sách sub-position THẬT (schema bots.json) của các basket đang dùng."""
        out = []
        for b in self.B:
            for f, c in zip(b["fills"], b["closes"]):
                out.append(dict(sym=b["sym"], side=b["side"], lev=f["lev"], o=int(f["t"]), c=int(c["t"]), po=f["px"], pc=c["px"], pnl=c["pnl"],
                                pr=c["pnl"] / f["mg"] * 100, mg=f["mg"]))
        return out


# ===================================================================== Bước 1: sự kiện thoát ngầm của từng basket
THR = dict(lag=2.0, band_bps=10.0, atr_mult=1.0, dd_pct=0.30, tol_bps=3.0)


def _path(D, k, anchor_mode="run"):
    """Đường lợi suất cho basket k từ nến đầu (sau fill đầu) đến nến chứa lần đóng cuối: giá vốn chạy (avg theo fill đã kích hoạt)."""
    o0, o1 = D.off[k], D.off[k + 1]
    s = D.s[k]
    te = int(np.searchsorted(D.T[o0:o1], D.t1[k], side="right")) - 1
    te = max(te, 0)
    sl = slice(o0, o0 + te + 1)
    n = te + 1
    cn = np.zeros(n); cq = np.zeros(n)
    for j in range(D.foff[k], D.foff[k + 1]):
        a = min(D.FACT[j] - o0, n - 1)
        cn[a:] += D.FNOT[j]; cq[a:] += D.FNOT[j] / D.FPX[j]
    # nến trước kích hoạt fill đầu (nếu fill đầu kích hoạt sau nến thoát): lấy avg của fill đầu
    cn = np.where(cn == 0, D.FNOT[D.foff[k]], cn); cq = np.where(cq == 0, D.FNOT[D.foff[k]] / D.FPX[D.foff[k]], cq)
    avg = cn / cq
    h = D.H[sl]; l = D.L[sl]
    fav = s * ((h if s > 0 else l) / avg - 1) * 100
    adv = s * ((l if s > 0 else h) / avg - 1) * 100
    return dict(te=te, n=n, avg=avg, fav=fav, adv=adv, T=D.T[sl], h=h, l=l, o0=o0)


def facts(D, thr=THR):
    """DataFrame facts theo basket. Mọi lợi suất là % GIÁ (gồm dấu theo chiều, TRƯỚC phí)."""
    rows = []
    for k in range(D.n):
        b = D.B[k]; s = int(D.s[k]); P = _path(D, k)
        a = D.cand[b["sym"]]; F = atr_arrays(b["sym"], a)
        avg = b["avg_px"]; fp = b["fills"][0]["px"]; lp = b["fills"][-1]["px"]; xpx = float(D.real_px[k])
        ret = s * (xpx / avg - 1) * 100
        ret_first = s * (xpx / fp - 1) * 100; ret_last = s * (xpx / lp - 1) * 100
        mfe_i = int(np.argmax(P["fav"])); mae_i = int(np.argmin(P["adv"]))
        mfe = max(0.0, float(P["fav"][mfe_i])); mae = min(0.0, float(P["adv"][mae_i]))
        # lần chạm đầu của mức thoát kể từ fill cuối kích hoạt
        act_last = int(min(D.FACT[D.foff[k + 1] - 1] - P["o0"], P["te"]))
        hh = P["h"][act_last:]; ll = P["l"][act_last:]
        tol = thr["tol_bps"] * 1e-4
        if ret > 0:   # TP: chạm mức lợi nhuận lần đầu
            hit = (hh >= xpx * (1 - tol)) if s > 0 else (ll <= xpx * (1 + tol))
        else:         # SL: chạm mức lỗ lần đầu
            hit = (ll <= xpx * (1 + tol)) if s > 0 else (hh >= xpx * (1 - tol))
        j = int(np.argmax(hit)) if hit.any() else len(hh) - 1
        lag = (P["T"][-1] - P["T"][act_last + j]) / MIN
        # đóng từng tầng
        clos = b["closes"]
        iT0 = int(np.searchsorted(a["t"], D.t0[k], side="right")) - 1
        iTx = int(np.searchsorted(a["t"], D.t1[k], side="right")) - 1
        mid = lambda arr, i: float(arr[i]) if 0 <= i < len(arr) else float("nan")
        rows.append(dict(
            id=int(b["id"]), k=k, sym=b["sym"], side=b["side"], s=s, lev=float(b["lev"]), cls=int(D.cls[k]), n_layers=int(D.nlay[k]),
            notional=float(b["notional"]), t0=int(D.t0[k]), t1=int(D.t1[k]), hold_min=float(D.hold_min[k]), staged=bool(D.staged[k]),
            ret=ret, ret_first=ret_first, ret_last=ret_last, net_ret=float(D.real_ret[k]),
            mfe=mfe, mfe_t_min=float((P["T"][mfe_i] - D.t0[k]) / MIN), mae=mae, mae_t_min=float((P["T"][mae_i] - D.t0[k]) / MIN),
            giveback=mfe - ret, touch_lag_min=float(lag),
            atr1_0=mid(F["atr1"], iT0), atr15_0=mid(F["atr15"], iT0), atr60_0=mid(F["atr60"], iT0),
            atr1_x=mid(F["atr1"], iTx), atr15_x=mid(F["atr15"], iTx), atr60_x=mid(F["atr60"], iTx),
            hour=int(D.vn_hour[k]), wday=int(D.wday[k]), mfe_before_mae=bool(P["T"][mfe_i] < P["T"][mae_i]),
        ))
    df = pd.DataFrame(rows)
    for c in ("atr1_0", "atr15_0", "atr60_0", "atr1_x", "atr15_x", "atr60_x"):
        df[c] = df[c].fillna(df[c].median())
    return df


CLASSES = ["TP-limit", "trailing/pullback", "SL", "hoà vốn (hồi về)", "hoà vốn (stop)", "khác"]


def classify(df, thr=THR):
    """Gán lớp thoát theo ngưỡng thr (xem THR). Ưu tiên: hoà vốn > TP-limit > trailing > SL > khác."""
    band = thr["band_bps"] / 100.0  # % giá
    ret = df.ret.values; lag = df.touch_lag_min.values
    cls = np.full(len(df), "khác", dtype=object)
    scr_rec = (np.abs(ret) < band) & (df.mae.values <= -thr["dd_pct"])
    scr_stop = (np.abs(ret) < band) & ~scr_rec & (df.mfe.values >= thr["dd_pct"])
    tp = (ret > 0) & (lag <= thr["lag"])
    trail = (ret > 0) & ~tp & (df.giveback.values > thr["atr_mult"] * df.atr1_x.values)
    sl = (ret < 0) & (lag <= thr["lag"])
    cls[sl] = "SL"; cls[trail] = "trailing/pullback"; cls[tp] = "TP-limit"
    cls[scr_stop] = "hoà vốn (stop)"; cls[scr_rec] = "hoà vốn (hồi về)"
    return cls


def class_mix(df, thr=THR):
    c = classify(df, thr)
    return {k: int((c == k).sum()) for k in CLASSES}


def sensitivity(df):
    """Tỉ lệ từng lớp khi đổi từng ngưỡng (so với THR gốc)."""
    out = []
    variants = [("gốc", {})] + [(f"lag={v}", dict(lag=v)) for v in (1.0, 5.0)] + [(f"band={v}bps", dict(band_bps=v)) for v in (5.0, 20.0)] + \
               [(f"atr_mult={v}", dict(atr_mult=v)) for v in (0.5, 2.0)] + [(f"dd={v}%", dict(dd_pct=v)) for v in (0.15, 0.6)]
    for name, ch in variants:
        thr = dict(THR); thr.update(ch)
        m = class_mix(df, thr)
        out.append(dict(variant=name, **{k: round(100 * v / len(df), 1) for k, v in m.items()}))
    return out


def layer_facts(D, thr=THR):
    """Mức sub-position (từng tầng đóng riêng): lợi suất so với giá vào CỦA TẦNG, hold, chạm đầu của mức thoát."""
    rows = []
    for k in range(D.n):
        b = D.B[k]; s = int(D.s[k]); a = D.cand[b["sym"]]; F = atr_arrays(b["sym"], a)
        tol = thr["tol_bps"] * 1e-4
        for fi, (f, c) in enumerate(zip(b["fills"], b["closes"])):
            ret = s * (c["px"] / f["px"] - 1) * 100
            ia = int(np.searchsorted(a["t"], (f["t"] // MIN + 1) * MIN, side="left")); ie = int(np.searchsorted(a["t"], c["t"], side="right")) - 1
            ie = max(ie, ia)
            h = a["h"][ia:ie + 1]; l = a["l"][ia:ie + 1]
            if len(h) == 0:
                continue
            xpx = c["px"]
            if ret > 0:
                hit = (h >= xpx * (1 - tol)) if s > 0 else (l <= xpx * (1 + tol))
            else:
                hit = (l <= xpx * (1 + tol)) if s > 0 else (h >= xpx * (1 - tol))
            j = int(np.argmax(hit)) if hit.any() else len(h) - 1
            lag = (ie - (ia + j))
            fav = s * ((h if s > 0 else l) / f["px"] - 1) * 100; adv = s * ((l if s > 0 else h) / f["px"] - 1) * 100
            iT0 = max(0, ia - 1)
            rows.append(dict(k=k, layer=fi, sym=b["sym"], s=s, lev=float(f["lev"]), cls=int(D.cls[k]), notional=float(f["notional"]), n_layers=len(b["fills"]),
                             ret=ret, hold_min=(c["t"] - f["t"]) / MIN, mfe=max(0.0, float(fav.max())), mae=min(0.0, float(adv.min())), touch_lag_min=float(lag),
                             giveback=max(0.0, float(fav.max())) - ret, atr60_0=float(F["atr60"][iT0]), atr15_0=float(F["atr15"][iT0]),
                             atr1_0=float(F["atr1"][iT0]), atr1_x=float(F["atr1"][min(ie, len(a["t"]) - 1)])))
    ld = pd.DataFrame(rows)
    for c in ("atr1_0", "atr15_0", "atr60_0", "atr1_x"):
        ld[c] = ld[c].fillna(ld[c].median())
    return ld


# ===================================================================== Bước 2: công thức mức thoát (hồi quy robust)
from sklearn.linear_model import HuberRegressor
from sklearn.model_selection import KFold

FORMS = ["const", "atr60", "atr15", "atr1", "atr60+lớp", "roi_const", "roi_atr60", "usd_const", "atr60+lev+tầng"]
FORM_DESC = {
    "const": "hằng số (% giá)", "atr60": "a + b·ATR1h%", "atr15": "a + b·ATR15m%", "atr1": "a + b·ATR1m%",
    "atr60+lớp": "a + b·ATR1h% + hệ số theo lớp mã", "roi_const": "ROI/ký quỹ = hằng số (mức giá = ROI/đòn bẩy)",
    "roi_atr60": "ROI/ký quỹ = a + b·ATR1h%·đòn bẩy", "usd_const": "PnL USDT = hằng số (mức giá = USDT/notional)",
    "atr60+lev+tầng": "a + b·ATR1h% + c·đòn bẩy + d·(số tầng-1)"}


def _design(form, df):
    """Trả (X, div, kind): X ma trận đặc trưng; mục tiêu biến đổi y_t = y*mult; mult theo kind: 'px' 1, 'roi' lev, 'usd' notional/100."""
    n = len(df)
    A = lambda c: df[c].values.astype(float)
    if form == "const":
        return np.zeros((n, 0)), "px"
    if form == "atr60":
        return A("atr60_0")[:, None], "px"
    if form == "atr15":
        return A("atr15_0")[:, None], "px"
    if form == "atr1":
        return A("atr1_0")[:, None], "px"
    if form == "atr60+lớp":
        cl = A("cls")
        return np.column_stack([A("atr60_0")] + [(cl == c).astype(float) for c in (0, 1, 2)]), "px"
    if form == "roi_const":
        return np.zeros((n, 0)), "roi"
    if form == "roi_atr60":
        return (A("atr60_0") * A("lev"))[:, None], "roi"
    if form == "usd_const":
        return np.zeros((n, 0)), "usd"
    if form == "atr60+lev+tầng":
        return np.column_stack([A("atr60_0"), A("lev"), A("n_layers") - 1]), "px"
    raise KeyError(form)


def _mult(kind, df):
    return {"px": np.ones(len(df)), "roi": df.lev.values.astype(float), "usd": df.notional.values.astype(float) / 100.0}[kind]


def _huber(X, y):
    """Hồi quy Huber trên X chuẩn hoá -> (intercept, coefs) theo thang gốc. X rỗng -> trung vị."""
    if X.shape[1] == 0:
        return float(np.median(y)), np.zeros(0)
    mu = X.mean(0); sd = X.std(0); sd[sd == 0] = 1.0
    Z = (X - mu) / sd
    try:
        m = HuberRegressor(epsilon=1.35, alpha=1e-4, max_iter=500).fit(Z, y)
        b = m.coef_ / sd; a = m.intercept_ - float((m.coef_ * mu / sd).sum())
    except Exception:
        b = np.zeros(X.shape[1]); a = float(np.median(y))
    return float(a), b


def fit_forms(df, y, min_n=12, seed=0, forms=None):
    """Khớp các dạng công thức cho mức y (% giá, dương) trên các hàng df. Trả list ứng viên đã sắp theo CV robust
    (rcv = median|resid giá| / median(y), 5-fold x2). Chọn: dạng đơn giản nhất trong 3% của rcv tốt nhất."""
    y = np.asarray(y, float); n = len(y)
    if n < min_n:
        return []
    cands = []
    for form in (forms or FORMS):
        X, kind = _design(form, df); mult = _mult(kind, df); yt = y * mult
        if n < 10 * (X.shape[1] + 1) and form != "const":   # chống quá khớp: cần >= 10 quan sát / tham số
            if not (X.shape[1] == 0):
                continue
        errs = np.zeros(n); cnt = np.zeros(n)
        for rep in range(2):
            for tr, te in KFold(5, shuffle=True, random_state=seed + rep).split(X):
                a, b = _huber(X[tr], yt[tr])
                pred = (a + X[te] @ b) / mult[te]
                errs[te] += np.abs(y[te] - pred); cnt[te] += 1
        res = errs / cnt
        rcv = float(np.median(res) / max(np.median(y), 1e-9))
        a, b = _huber(X, yt)
        pred_in = (a + X @ b) / mult
        cands.append(dict(form=form, desc=FORM_DESC[form], a=a, b=[float(v) for v in b], kind=kind, rcv=rcv,
                          resid_med_abs=float(np.median(np.abs(y - pred_in))), r2_spearman=_spear(y, pred_in), n=n))
    cands.sort(key=lambda c: c["rcv"])
    best = cands[0]["rcv"]
    order = {f: i for i, f in enumerate(FORMS)}
    ok = [c for c in cands if c["rcv"] <= best * 1.03 + 1e-12]
    pick = sorted(ok, key=lambda c: (order[c["form"]], c["rcv"]))[0]
    return dict(chosen=pick, table=[{k: (round(v, 5) if isinstance(v, float) else v) for k, v in c.items() if k != "b"} | {"b": [round(x, 6) for x in c["b"]]} for c in cands])


def _spear(a, b):
    try:
        if np.std(a) == 0 or np.std(b) == 0:
            return None
        from scipy.stats import spearmanr
        r = spearmanr(a, b).correlation
        return None if r is None or np.isnan(r) else round(float(r), 3)
    except Exception:
        return None


def eval_form(ch, df):
    """Giá trị công thức đã chọn trên df: trả (base %giá hoặc USDT nếu kind='usd', lay %giá/tầng)."""
    X, kind = _design(ch["form"], df)
    a = ch["a"]; b = np.array(ch["b"])
    if ch["form"] == "atr60+lev+tầng":
        base = a + X[:, :2] @ b[:2]; lay = float(b[2])
        return base, lay, "px"
    v = a + X @ b
    if kind == "roi":
        return v / df.lev.values, 0.0, "px"
    if kind == "usd":
        return np.full(len(df), v if np.isscalar(v) else float(np.median(v))), 0.0, "usd"
    return v, 0.0, "px"


def formula_text(ch, what):
    """Chuỗi công thức dễ đọc (tiếng Việt) cho mức `what`."""
    f = ch["form"]; a = ch["a"]; b = ch["b"]
    if f == "const":
        return f"{what} = {a:.3f}% giá"
    if f in ("atr60", "atr15", "atr1"):
        nm = {"atr60": "ATR1h", "atr15": "ATR15m", "atr1": "ATR1m"}[f]
        return f"{what} = {a:.3f}% + {b[0]:.3f}·{nm}%"
    if f == "atr60+lớp":
        return f"{what} = {a:.3f}% + {b[0]:.3f}·ATR1h% + lớp[cổ phiếu {b[1]:+.3f}, hàng hóa {b[2]:+.3f}, crypto lớn {b[3]:+.3f}]"
    if f == "roi_const":
        return f"{what} = {a:.2f}% ROI/ký quỹ (= {a:.2f}/đòn bẩy % giá)"
    if f == "roi_atr60":
        return f"{what} = ({a:.2f} + {b[0]:.3f}·ATR1h%·đòn bẩy)% ROI/ký quỹ"
    if f == "usd_const":
        return f"{what} = {a:.1f} USDT PnL"
    return f"{what} = {a:.3f}% + {b[0]:.3f}·ATR1h% + {b[1]:.4f}·đòn bẩy + {b[2]:.3f}·(số tầng-1)"


ELEMS = {  # phần tử -> (tên VN, hàm lấy mục tiêu y từ df/cls, điều kiện lớp)
    "tp": "TP", "sl": "SL", "gb": "giveback trailing", "act": "kích hoạt trailing", "bes": "kích hoạt hoà vốn (stop)", "brd": "độ sâu để hoà vốn (hồi về)"}


def fit_elements(df, cl, anchor, min_n=12):
    """Khớp công thức cho các phần tử ở neo `anchor` ('avg','first','last' hoặc 'layer' dùng df = layer_facts).
    Trả dict elem -> {src, n, fit(chosen/table) | fallback}. Lớp nhỏ (<min_n) -> dùng hằng fallback có nhãn."""
    rc = {"avg": "ret", "first": "ret_first", "last": "ret_last", "layer": "ret"}[anchor]
    r = df[rc].values
    out = {}
    def mk(name, mask, y, fb_mask, fb_y, fb_default):
        n = int(mask.sum())
        if n >= min_n:
            fit = fit_forms(df[mask], y[mask], forms=FORMS if name in ("tp", "sl") else [f for f in FORMS if f != "usd_const"])
            if fit:
                out[name] = dict(src="lớp", n=n, **fit); return
        n2 = int(fb_mask.sum())
        v = float(np.median(fb_y[fb_mask])) if n2 >= 3 else fb_default
        out[name] = dict(src="fallback", n=n, n_fallback=n2, chosen=dict(form="const", desc=FORM_DESC["const"], a=v, b=[], kind="px", rcv=None, n=n2), table=[])
    mk("tp", cl == "TP-limit", r, r > 0, r, 0.3)
    mk("sl", cl == "SL", -r, r < 0, -r, 1.0)
    trail = cl == "trailing/pullback"
    mk("gb", trail, df.giveback.values, trail | (r > 0), df.giveback.values, 0.2)
    mk("act", trail, df.mfe.values, trail | (r > 0), df.mfe.values, 0.5)
    mk("bes", cl == "hoà vốn (stop)", df.mfe.values, r > 0, df.mfe.values, 0.3)
    mk("brd", cl == "hoà vốn (hồi về)", -df.mae.values, r < 0, -df.mae.values, 0.5)
    return out


# ===================================================================== Bước 3: engine thoát với fill thật (numba)
# mã lý do: 1 TP, 2 SL, 3 trailing, 4 hoà vốn (stop), 5 hoà vốn (hồi về), 6 thời gian, 7 hết horizon (cưỡng bức)
WHY = {0: "chưa", 1: "TP", 2: "SL", 3: "trailing", 4: "hoà vốn-stop", 5: "hoà vốn-hồi về", 6: "thời gian", 7: "hết horizon"}
INF = np.inf


@nb.njit(cache=True, parallel=True)
def engine(T, O, H, L, C, off, FPX, FNOT, FACT, foff, S, tp, tpl, sl, sll, gb, act, bes, bes_off, brd, brd_off, tcap, flags, fl2, fee,
           o_ct, o_cp, o_why, o_closed, o_pnl, o_not, o_nused, f_ct, f_cp, f_why, o_mtm):
    nbk = len(off) - 1
    anchor = flags[0]; tcap_ref = flags[1]; tcap_loss = flags[2]; tp_usd = flags[3]; sl_usd = flags[4]
    layer = anchor == 3
    for b in nb.prange(nbk):
        s = float(S[b]); j0 = foff[b]; j1 = foff[b + 1]; nf = j1 - j0
        i_start = off[b]; i_end = off[b + 1]
        nu = nf if layer else 1
        ua = np.zeros(nu); upk = np.zeros(nu); utr = np.zeros(nu); un = np.zeros(nu)
        ual = np.zeros(nu, np.int8); utref = np.zeros(nu, np.int64)
        nextf = 0; nact = 0; sum_n = 0.0; sum_q = 0.0; first_px = 0.0; last_px = 0.0
        ncl = 0
        for j in range(j0, j1):
            f_ct[j] = -1; f_cp[j] = 0.0; f_why[j] = 0
        for i in range(i_start, i_end):
            while nextf < nf and FACT[j0 + nextf] <= i:
                j = j0 + nextf; px = FPX[j]; nt = FNOT[j]
                if layer:
                    ua[nextf] = px; upk[nextf] = px; utr[nextf] = px; un[nextf] = nt; ual[nextf] = 1; utref[nextf] = T[i]
                else:
                    if nact == 0:
                        first_px = px; upk[0] = px; utr[0] = px; utref[0] = T[i]; ual[0] = 1
                    sum_n += nt; sum_q += nt / px; last_px = px
                    un[0] = sum_n
                    if anchor == 0:
                        ua[0] = sum_n / sum_q
                    elif anchor == 1:
                        ua[0] = first_px
                    else:
                        ua[0] = last_px
                    if tcap_ref == 1:
                        utref[0] = T[i]
                nact += 1; nextf += 1
            allclosed = False
            for u in range(nu):
                if ual[u] != 1:
                    continue
                a = ua[u]
                nfe = 1 if layer else nact
                if tp_usd == 1:
                    tpp = tp[b] / un[u]
                else:
                    tpp = tp[b] + tpl[b] * (nfe - 1)
                if sl_usd == 1:
                    slp = sl[b] / un[u]
                else:
                    slp = sl[b] + sll[b] * (nfe - 1)
                ro = s * (O[i] / a - 1.0)
                if s > 0:
                    rf = H[i] / a - 1.0; ra = L[i] / a - 1.0
                else:
                    rf = -(L[i] / a - 1.0); ra = -(H[i] / a - 1.0)
                rc = s * (C[i] / a - 1.0)
                rpk = s * (upk[u] / a - 1.0); rtr = s * (utr[u] / a - 1.0)
                stop_r = -INF; why = 0
                if slp < INF:
                    v = -slp
                    if v > stop_r:
                        stop_r = v; why = 2
                if gb[b] < INF and rpk >= act[b]:
                    v = s * (upk[u] * (1.0 - s * gb[b]) / a - 1.0)
                    if v > stop_r:
                        stop_r = v; why = 3
                if bes[b] < INF and rpk >= bes[b]:
                    v = bes_off[b]
                    if v > stop_r:
                        stop_r = v; why = 4
                tp_r = tpp + fl2[0] * (-rtr if rtr < 0.0 else 0.0); tw = 1
                if brd[b] < INF and rtr <= -brd[b]:
                    v = brd_off[b]
                    if v < tp_r:
                        tp_r = v; tw = 5
                hit = 0; xr = 0.0; mid = 30000
                if stop_r > -INF:
                    if ro <= stop_r:
                        hit = why; xr = ro
                    elif ra <= stop_r:
                        hit = why; xr = stop_r
                if hit == 0 and tp_r < INF:
                    if ro >= tp_r:
                        hit = tw; xr = ro
                    elif rf >= tp_r:
                        hit = tw; xr = tp_r
                if hit == 0 and tcap[b] < INF:
                    held = (T[i] + 60000 - utref[u]) / 60000.0
                    if held >= tcap[b] and (tcap_loss == 0 or rc <= 0.0):
                        hit = 6; xr = rc; mid = 60000
                if hit == 0 and i == i_end - 1:
                    hit = 7; xr = rc; mid = 60000
                if hit > 0:
                    xp = a * (1.0 + s * xr)
                    ct = T[i] + mid
                    if layer:
                        j = j0 + u
                        f_ct[j] = ct; f_cp[j] = xp; f_why[j] = hit
                    else:
                        for j in range(j0, j0 + nact):
                            f_ct[j] = ct; f_cp[j] = xp; f_why[j] = hit
                    ual[u] = 0; ncl += 1
                else:
                    if s > 0:
                        if H[i] > upk[u]:
                            upk[u] = H[i]
                        if L[i] < utr[u]:
                            utr[u] = L[i]
                    else:
                        if L[i] < upk[u]:
                            upk[u] = L[i]
                        if H[i] > utr[u]:
                            utr[u] = H[i]
            if layer:
                if nextf == nf and ncl == nf:
                    break
            else:
                if ncl == 1:
                    break
        # tổng hợp basket
        pnl = 0.0; mtm = 0.0; nt_sum = 0.0; lastc = -1; lastp = 0.0; lastw = 0; nused = 0; allc = 1
        for j in range(j0, j1):
            if f_ct[j] < 0:
                continue
            nused += 1
            xp = f_cp[j]; nt = FNOT[j]
            gj = s * (xp / FPX[j] - 1.0) * nt - fee * (nt + nt * xp / FPX[j])
            mtm += gj
            if f_why[j] != 7:
                pnl += gj
            nt_sum += nt
            if f_ct[j] > lastc:
                lastc = f_ct[j]; lastp = xp; lastw = f_why[j]
            if f_why[j] == 7:
                allc = 0
        o_ct[b] = lastc; o_cp[b] = lastp; o_why[b] = lastw; o_closed[b] = allc; o_pnl[b] = pnl; o_mtm[b] = mtm; o_not[b] = nt_sum; o_nused[b] = nused


class Out:
    def __init__(self, D):
        n = D.n; m = len(D.FPX)
        self.ct = np.zeros(n, np.int64); self.cp = np.zeros(n); self.why = np.zeros(n, np.int64); self.closed = np.zeros(n, np.int64)
        self.pnl = np.zeros(n); self.mtm = np.zeros(n); self.notional = np.zeros(n); self.nused = np.zeros(n, np.int64)
        self.f_ct = np.zeros(m, np.int64); self.f_cp = np.zeros(m); self.f_why = np.zeros(m, np.int64)


def run(D, L, out=None):
    """L: dict các mảng mức (đơn vị PHÂN SỐ giá) + flags. Trả Out."""
    if out is None:
        out = Out(D)
    engine(D.T, D.O, D.H, D.L, D.C, D.off, D.FPX, D.FNOT, D.FACT, D.foff, D.s, L["tp"], L["tpl"], L["sl"], L["sll"], L["gb"], L["act"], L["bes"],
           L["bes_off"], L["brd"], L["brd_off"], L["tcap"], L["flags"], L["fl2"], FEE, out.ct, out.cp, out.why, out.closed, out.pnl, out.notional, out.nused,
           out.f_ct, out.f_cp, out.f_why, out.mtm)
    return out


# ===================================================================== chỉ số + mục tiêu
def metrics(D, o, scale_bps, idx=None):
    """Chỉ số nhanh (numpy). idx: mặt nạ basket (bool) hoặc None."""
    sel = np.ones(D.n, bool) if idx is None else idx
    closed = o.closed[sel] == 1
    dt = np.abs(o.ct[sel] - D.t1[sel]) / MIN
    dt = np.where((o.nused[sel] > 0) & closed, dt, np.inf)
    m5, m15, m60 = [float(np.mean(dt <= m)) for m in (5, 15, 60)]
    pe = np.abs(o.cp[sel] / D.real_px[sel] - 1) * 1e4
    pe = np.where((o.nused[sel] > 0) & closed, pe, 1e4)
    med_pe = float(np.median(pe))
    sr = np.where(o.notional[sel] > 0, o.pnl[sel] / np.where(o.notional[sel] > 0, o.notional[sel], 1) * 100, 0.0)
    ar = D.real_ret[sel]
    sign = float(np.mean(np.sign(sr) == np.sign(ar)))
    cr = _corr(ar, sr); cu = _corr(D.real_pnl[sel], o.pnl[sel])
    pxs = max(0.0, 1.0 - min(1.0, med_pe / scale_bps))
    obj = float(np.mean([m15, pxs, sign, max(0.0, cu)]))
    return dict(obj=obj, m5=m5, m15=m15, m60=m60, px_med=med_pe, px_score=pxs, sign=sign, corr_ret=cr, corr_usdt=cu)


def _corr(a, b):
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


# ===================================================================== tìm kiếm luật (coordinate descent có ablation)
G_TP = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.35, 1.5, 1.7, 2.0, 2.4, 3.0, 4.0, 6.0, INF]
G_SL = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 6.0, 8.0, 12.0, 20.0, INF]
G_GB = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 6.0, INF]
G_TPK = [0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0]
G_ACT = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0]
G_BM = [0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, INF]
G_OFF = [0.0, 5.0, 10.0, 20.0]
G_TCMIN = [3, 5, 8, 12, 20, 30, 45, 60, 90, 120, 180, 240, 360, 480, 720, 1080, 1440, 2160, 2880, 4320, 7200, INF]
ANCHORS = ["avg", "first", "last", "layer"]
MIN_GAIN = 0.004   # phần tử chỉ giữ trong luật tốt nhất nếu tăng mục tiêu >= ngưỡng này


class Searcher:
    def __init__(self, D, df, fits, scale_bps=None):
        """D: Data; df: facts(D) (cùng thứ tự basket); fits: {anchor: fit_elements(...)} (đã khớp)."""
        self.D = D; self.df = df; self.fits = fits
        self.out = Out(D)
        self.scale_bps = scale_bps or max(30.0, 2 * float(np.median(np.abs(df.ret.values))) * 100)
        self.n_eval = 0; self.log = []
        self._base = {}
        for an in fits:
            self._base[an] = self._bases(an)
        self.grp = np.zeros(D.n, np.int64); self.G = 1

    # ---- mảng mức nền (phân số giá) cho từng anchor
    def _bases(self, an):
        f = self.fits[an]; df = self.df; B = {}
        for e in ("tp", "sl", "gb", "act"):
            ch = f[e]["chosen"]; base, lay, unit = eval_form(ch, df)
            base = np.asarray(base, float)
            if unit == "usd":
                B[e] = (np.full(self.D.n, abs(float(base.flat[0]))), 0.0, "usd")
            else:
                B[e] = (np.maximum(base, 0.02) / 100.0, lay / 100.0, "px")
        for e in ("bes", "brd"):
            if f[e]["src"] == "lớp":
                base, lay, unit = eval_form(f[e]["chosen"], df)
                B[e] = (np.maximum(np.asarray(base, float), 0.02) / 100.0, 0.0, "px")
            else:
                B[e] = (np.maximum(df.atr60_0.values, 0.05) / 100.0, 0.0, "atr")
        return B

    def levels(self, cfg):
        D = self.D; n = D.n; B = self._base[ANCHORS[cfg["anchor"]]]; g = self.grp
        inf = np.full(n, INF); z = np.zeros(n)
        tp = inf; tpl = z; sl = inf; sll = z; gb = inf; act = z; bes = inf; bo = z; brd = inf; do = z; tcap = inf
        flags = np.zeros(5, np.int64); flags[0] = cfg["anchor"]
        fl2 = np.array([float(cfg.get("tpk") or 0.0)])
        if cfg.get("tp") is not None:
            base, lay, unit = B["tp"]; m = np.asarray(cfg["tp"])[g]
            tp = base * m; tpl = np.where(np.isinf(m), 0.0, lay * m); flags[3] = 1 if unit == "usd" else 0
        if cfg.get("sl") is not None:
            base, lay, unit = B["sl"]; m = np.asarray(cfg["sl"])[g]
            sl = base * m; sll = np.where(np.isinf(m), 0.0, lay * m); flags[4] = 1 if unit == "usd" else 0
        if cfg.get("tr") is not None:
            tr = cfg["tr"]
            gb = B["gb"][0] * np.asarray(tr["gb"])[g]
            act = B["act"][0] * np.asarray(tr["act"], float)[g]
            if B["gb"][2] == "usd":
                gb = np.full(n, 0.003) * np.asarray(tr["gb"])[g]; act = np.full(n, 0.004) * np.asarray(tr["act"], float)[g]
        if cfg.get("bes") is not None:
            bes = B["bes"][0] * cfg["bes"]["m"]; bo = np.full(n, cfg["bes"]["off"] * 1e-4)
        if cfg.get("brd") is not None:
            brd = B["brd"][0] * cfg["brd"]["m"]; do = np.full(n, cfg["brd"]["off"] * 1e-4)
        if cfg.get("tc") is not None:
            tcap = np.full(n, float(cfg["tc"]["min"])); flags[1] = cfg["tc"]["ref"]; flags[2] = cfg["tc"]["loss"]
        return dict(tp=tp, tpl=tpl, sl=sl, sll=sll, gb=gb, act=act, bes=bes, bes_off=bo, brd=brd, brd_off=do, tcap=tcap, flags=flags, fl2=fl2)

    def score(self, cfg, idx=None, keep=False):
        L = self.levels(cfg)
        o = run(self.D, L, self.out if not keep else None)
        m = metrics(self.D, o, self.scale_bps, idx)
        self.n_eval += 1
        if idx is None:
            self.log.append((m["obj"], _cfg_key(cfg), m["m15"], m["corr_usdt"], m["sign"], m["px_med"], _cp(cfg), self.G))
        return (m, o) if keep else m

    # ---- tối ưu 1 tham số trên lưới + tinh chỉnh cục bộ
    def _best_scalar(self, cfg, getset, grid, cur, idx=None, refine=True):
        best_v, best_o = cur, self.score(getset(cfg, cur), idx)["obj"]
        for v in grid:
            o = self.score(getset(cfg, v), idx)["obj"]
            if o > best_o + 1e-9:
                best_v, best_o = v, o
        if refine and best_v not in (0, None) and np.isfinite(best_v) and best_v > 0:
            for step in (0.1, 0.05, 0.02):
                for v in (best_v * (1 - step), best_v * (1 + step)):
                    o = self.score(getset(cfg, v), idx)["obj"]
                    if o > best_o + 1e-9:
                        best_v, best_o = v, o
        return best_v, best_o

    def tune(self, cfg, passes=2, idx=None, groups=True):
        """Coordinate descent trên mọi phần tử đang bật. Sửa cfg tại chỗ (sao chép trước nếu cần). Trả mục tiêu."""
        o = self.score(cfg, idx)["obj"]
        for _ in range(passes):
            o0 = o
            for gi in range(self.G):
                if cfg.get("tp") is not None:
                    def gs(c, v, gi=gi):
                        c2 = _cp(c); c2["tp"][gi] = v; return c2
                    v, o = self._best_scalar(cfg, gs, G_TP, cfg["tp"][gi], idx); cfg["tp"][gi] = v
                if cfg.get("sl") is not None:
                    def gs(c, v, gi=gi):
                        c2 = _cp(c); c2["sl"][gi] = v; return c2
                    v, o = self._best_scalar(cfg, gs, G_SL, cfg["sl"][gi], idx); cfg["sl"][gi] = v
                if cfg.get("tr") is not None:
                    def gs(c, v, gi=gi):
                        c2 = _cp(c); c2["tr"]["gb"][gi] = v; return c2
                    v, o = self._best_scalar(cfg, gs, G_GB, cfg["tr"]["gb"][gi], idx); cfg["tr"]["gb"][gi] = v
                    if np.isfinite(cfg["tr"]["gb"][gi]):
                        def gs(c, v, gi=gi):
                            c2 = _cp(c); c2["tr"]["act"][gi] = v; return c2
                        v, o = self._best_scalar(cfg, gs, G_ACT, cfg["tr"]["act"][gi], idx, refine=False); cfg["tr"]["act"][gi] = v
            if cfg.get("tpk") is not None:
                def gs(c, v):
                    c2 = _cp(c); c2["tpk"] = v; return c2
                v, o = self._best_scalar(cfg, gs, G_TPK, cfg["tpk"], idx, refine=False); cfg["tpk"] = v
            for key, grid in (("bes", G_BM), ("brd", G_BM)):
                if cfg.get(key) is not None:
                    def gs(c, v, key=key):
                        c2 = _cp(c); c2[key]["m"] = v; return c2
                    v, o = self._best_scalar(cfg, gs, grid, cfg[key]["m"], idx); cfg[key]["m"] = v
                    for off in G_OFF:
                        c2 = _cp(cfg); c2[key]["off"] = off
                        oo = self.score(c2, idx)["obj"]
                        if oo > o + 1e-9:
                            o = oo; cfg[key]["off"] = off
            if cfg.get("tc") is not None:
                for ref in (0, 1):
                    for loss in (0, 1):
                        for mn in G_TCMIN:
                            c2 = _cp(cfg); c2["tc"] = dict(min=mn, ref=ref, loss=loss)
                            oo = self.score(c2, idx)["obj"]
                            if oo > o + 1e-9:
                                o = oo; cfg["tc"] = dict(min=mn, ref=ref, loss=loss)
            if o - o0 < 1e-5:
                break
        return o

    def init_elem(self, cfg, name):
        """Đặt giá trị khởi đầu cho phần tử (nhân 1.0 / mặc định) rồi tìm grid."""
        G = self.G
        if name == "tp":
            cfg["tp"] = np.ones(G)
        elif name == "sl":
            cfg["sl"] = np.ones(G)
        elif name == "tr":
            cfg["tr"] = dict(gb=np.ones(G), act=np.ones(G))
        elif name == "tpk":
            cfg["tpk"] = 0.1
        elif name == "bes":
            cfg["bes"] = dict(m=1.0, off=5.0)
        elif name == "brd":
            cfg["brd"] = dict(m=1.0, off=5.0)
        elif name == "tc":
            cfg["tc"] = dict(min=240, ref=0, loss=0)
        return cfg


def _cp(c):
    d = dict(c)
    for k in ("tp", "sl"):
        if d.get(k) is not None:
            d[k] = np.array(d[k], float)
    if d.get("tr") is not None:
        d["tr"] = dict(gb=np.array(d["tr"]["gb"], float), act=np.array(d["tr"]["act"], float))
    for k in ("bes", "brd", "tc"):
        if d.get(k) is not None:
            d[k] = dict(d[k])
    return d


def _cfg_key(c):
    r = lambda v: tuple(np.round(np.asarray(v, float), 3).tolist())
    return (c["anchor"], r(c["tp"]) if c.get("tp") is not None else None, r(c["sl"]) if c.get("sl") is not None else None,
            (r(c["tr"]["gb"]), r(c["tr"]["act"])) if c.get("tr") is not None else None, round(float(c.get("tpk") or 0), 3),
            (round(c["bes"]["m"], 3), c["bes"]["off"]) if c.get("bes") is not None else None,
            (round(c["brd"]["m"], 3), c["brd"]["off"]) if c.get("brd") is not None else None,
            (c["tc"]["min"], c["tc"]["ref"], c["tc"]["loss"]) if c.get("tc") is not None else None)


# ===================================================================== phân đoạn chế độ (regime) + nhóm lớp mã
def changepoints(y, min_size, max_seg=6):
    """Binary segmentation trên trung bình (chi phí bình phương), phạt BIC ~ 2*var*log n. Trả danh sách điểm cắt (chỉ số)."""
    y = np.asarray(y, float); n = len(y)
    if n < 2 * min_size:
        return []
    cs = np.concatenate([[0], np.cumsum(y)]); cs2 = np.concatenate([[0], np.cumsum(y * y)])
    cost = lambda i, j: (cs2[j] - cs2[i]) - (cs[j] - cs[i]) ** 2 / (j - i)
    pen = 2.0 * float(np.var(y)) * math.log(n)
    segs = [(0, n)]; cuts = []
    while len(segs) < max_seg:
        best = (0.0, None, None)
        for (i, j) in segs:
            if j - i < 2 * min_size:
                continue
            c0 = cost(i, j)
            for k in range(i + min_size, j - min_size + 1):
                g = c0 - cost(i, k) - cost(k, j)
                if g > best[0]:
                    best = (g, (i, j), k)
        if best[1] is None or best[0] < pen:
            break
        i, j = best[1]; k = best[2]
        segs.remove((i, j)); segs += [(i, k), (k, j)]; cuts.append(k)
    return sorted(cuts)


def group_cp(D, df):
    """Nhóm theo điểm đổi chế độ (đổi phân phối |lợi suất thoát|) theo thời điểm đóng."""
    order = np.argsort(D.t1, kind="stable")
    y = np.log(np.abs(df.ret.values[order]) + 0.02)
    cuts = changepoints(y, min_size=max(20, D.n // 12))
    g = np.zeros(D.n, np.int64)
    rank = np.empty(D.n, np.int64); rank[order] = np.arange(D.n)
    g = np.searchsorted(np.array(cuts), rank, side="right") if cuts else g
    t_cut = [int(D.t1[order[c]]) for c in cuts]
    return g.astype(np.int64), dict(method="điểm đổi chế độ (binary segmentation trên log|lợi suất thoát|)", cuts_t=t_cut, n_groups=len(cuts) + 1)


def group_week(D, min_n=12, max_groups=14):
    """Theo tuần lịch (UTC) của thời điểm đóng; tuần < min_n basket gộp vào tuần trước; tối đa max_groups bằng cách gộp tuần liền kề."""
    wk = (D.t1 // (7 * DAY)).astype(np.int64)
    uw = np.unique(wk)
    cnt = {w: int((wk == w).sum()) for w in uw}
    mp = {}; cur = None; acc = 0; groups = []
    for w in uw:
        if cur is None or acc >= min_n:
            cur = len(groups); groups.append([w]); acc = 0
        else:
            groups[cur].append(w)
        acc += cnt[w]; mp[w] = cur
    if len(groups) > 1 and sum(cnt[w] for w in groups[-1]) < min_n:
        for w in groups[-1]:
            mp[w] = len(groups) - 2
        groups[-2] += groups[-1]; groups.pop()
    while len(groups) > max_groups:   # gộp cặp liền kề nhỏ nhất
        sz = [sum(cnt[w] for w in g) for g in groups]
        k = int(np.argmin([sz[i] + sz[i + 1] for i in range(len(groups) - 1)]))
        groups[k] += groups[k + 1]; groups.pop(k + 1)
    for gi, g in enumerate(groups):
        for w in g:
            mp[w] = gi
    return np.array([mp[w] for w in wk], np.int64), dict(method="theo tuần lịch (UTC, gộp tuần ít basket)", n_groups=len(groups),
                                                        cuts_t=[int(min(D.t1[wk == g[0]])) for g in groups[1:]])


def group_class(D, min_n=15):
    c = D.cls.copy()
    cnt = np.bincount(c, minlength=4)
    big = int(np.argmax(cnt))
    for k in range(4):
        if cnt[k] < min_n:
            c[c == k] = big
    u = np.unique(c); mp = {v: i for i, v in enumerate(u)}
    return np.array([mp[v] for v in c], np.int64), dict(method="theo lớp mã", n_groups=len(u), classes=[[CLS_NAMES[int(v)] for v in [x for x in range(4) if (c == u[i]).any() and (D.cls[c == u[i]] == x).any()]] for i in range(len(u))])


def group_sym(D, min_n=25, max_groups=9):
    """Mỗi mã có >= min_n basket (tối đa max_groups mã lớn nhất) một nhóm riêng; còn lại gộp 'mã khác'."""
    syms = np.array([b["sym"] for b in D.B])
    u, c = np.unique(syms, return_counts=True)
    big = [s for s, k in sorted(zip(u, c), key=lambda x: -x[1]) if k >= min_n][:max_groups - 1]
    g = np.zeros(D.n, np.int64)
    for i, sname in enumerate(big):
        g[syms == sname] = i + 1
    return g, dict(method="theo từng mã lớn + 'mã khác'", n_groups=int(g.max()) + 1, syms=["mã khác"] + big)


# ===================================================================== diễn giải luật + xuất
def _jr(x):
    if isinstance(x, dict):
        return {str(k): _jr(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jr(v) for v in x]
    if isinstance(x, np.ndarray):
        return _jr(x.tolist())
    if isinstance(x, (np.floating, float)):
        return None if (math.isnan(x) or math.isinf(x)) else round(float(x), 6)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def clean(cfg):
    """Bỏ các phần tử không hoạt động (toàn bộ nhân = tắt)."""
    c = _cp(cfg); st = structure(c)
    for k in ("tp", "sl", "tr", "bes", "brd", "tc"):
        if k not in st:
            c[k] = None
    if "tp" not in st:
        c["tpk"] = None
    return c


def structure(cfg):
    out = []
    for k in ("tp", "sl", "tr", "bes", "brd", "tc"):
        v = cfg.get(k)
        if v is None:
            continue
        if k in ("tp", "sl") and not np.isfinite(np.asarray(v, float)).any():
            continue
        if k == "tr" and not np.isfinite(np.asarray(v["gb"], float)).any():
            continue
        if k in ("bes", "brd") and not np.isfinite(v["m"]):
            continue
        if k == "tc" and not np.isfinite(v["min"]):
            continue
        out.append(k)
        if k == "tp" and (cfg.get("tpk") or 0) > 0:
            out.append("tpk")
    return tuple(out)


def cfg_params(cfg):
    p = dict(anchor=ANCHORS[cfg["anchor"]])
    if cfg.get("tp") is not None:
        p["tp_mult"] = [None if not np.isfinite(v) else round(float(v), 4) for v in cfg["tp"]]
    if cfg.get("tpk"):
        p["tp_mae_coupling_k"] = round(float(cfg["tpk"]), 3)
    if cfg.get("sl") is not None:
        p["sl_mult"] = [None if not np.isfinite(v) else round(float(v), 4) for v in cfg["sl"]]
    if cfg.get("tr") is not None:
        p["trail_giveback_mult"] = [None if not np.isfinite(v) else round(float(v), 4) for v in cfg["tr"]["gb"]]; p["trail_activation_mult"] = [round(float(v), 4) for v in cfg["tr"]["act"]]
    if cfg.get("bes") is not None:
        p["be_stop"] = dict(trigger_mult_atr_or_fit=round(cfg["bes"]["m"], 4), offset_bps=cfg["bes"]["off"])
    if cfg.get("brd") is not None:
        p["be_recover"] = dict(depth_mult_atr_or_fit=round(cfg["brd"]["m"], 4), offset_bps=cfg["brd"]["off"])
    if cfg.get("tc") is not None:
        p["time_cap"] = dict(minutes=cfg["tc"]["min"], from_="fill cuối" if cfg["tc"]["ref"] == 1 else "fill đầu", only_if_loss=bool(cfg["tc"]["loss"]))
    return p


def level_summary(S, cfg):
    """Mức trung vị thực tế (sau nhân) của từng phần tử, đơn vị % giá và % ROI ký quỹ (nhân đòn bẩy)."""
    L = S.levels(cfg); D = S.D; out = {}
    for k, nm in (("tp", "tp"), ("sl", "sl"), ("gb", "trail_giveback"), ("act", "trail_activation"), ("bes", "be_trigger"), ("brd", "be_depth")):
        v = L[k]
        if k == "act" and cfg.get("tr") is None:
            continue
        v = v[np.isfinite(v)]
        if len(v) == 0:
            continue
        lev = D.lev[np.isfinite(L[k])]
        if (k == "tp" and L["flags"][3] == 1) or (k == "sl" and L["flags"][4] == 1):
            out[nm] = dict(usdt_med=round(float(np.median(v)), 2)); continue
        out[nm] = dict(px_pct_med=round(float(np.median(v) * 100), 4), px_pct_p10=round(float(np.percentile(v, 10) * 100), 4),
                       px_pct_p90=round(float(np.percentile(v, 90) * 100), 4), roi_pct_med=round(float(np.median(v * lev) * 100), 3))
    return out


def text_vi(S, cfg, fits_a, lv, anchor_name, groups_info=None):
    an = {"avg": "giá vốn trung bình của các fill đang mở", "first": "giá fill đầu tiên", "last": "giá fill gần nhất", "layer": "giá vào của từng tầng (mỗi tầng có TP/SL riêng)"}[anchor_name]
    parts = [f"Neo mức tại {an}."]
    G = S.G
    def mult_txt(arr):
        arr = ["tắt" if not np.isfinite(v) else str(round(float(v), 2)) for v in arr]
        return f"{arr[0]}" if len(arr) == 1 else "theo nhóm " + "/".join(arr)
    if cfg.get("tp") is not None:
        ch = fits_a["tp"]["chosen"]; nm = lv.get("tp", {})
        t = f"Chốt lời (limit, chạm trong nến): {mult_txt(cfg['tp'])} × [{formula_text(ch, 'TP')}]" + (f" + {cfg['tpk']:.2f} × (độ sâu lỗ tối đa đã qua so với giá neo)" if cfg.get("tpk") else "")
        if "px_pct_med" in nm:
            t += f" -> trung vị {nm['px_pct_med']:.2f}% giá (≈ {nm['roi_pct_med']:.1f}% ROI ký quỹ; p10-p90: {nm['px_pct_p10']:.2f}-{nm['px_pct_p90']:.2f}%)"
        elif "usdt_med" in nm:
            t += f" -> trung vị {nm['usdt_med']:.0f} USDT"
        parts.append(t + ".")
    if cfg.get("sl") is not None:
        ch = fits_a["sl"]["chosen"]; nm = lv.get("sl", {})
        t = f"Cắt lỗ (stop, stop-first): {mult_txt(cfg['sl'])} × [{formula_text(ch, 'SL')}]"
        if "px_pct_med" in nm:
            t += f" -> trung vị {nm['px_pct_med']:.2f}% giá (≈ {nm['roi_pct_med']:.1f}% ROI ký quỹ)"
        elif "usdt_med" in nm:
            t += f" -> trung vị {nm['usdt_med']:.0f} USDT"
        parts.append(t + ".")
    if cfg.get("tr") is not None:
        g = fits_a["gb"]["chosen"]; a = fits_a["act"]["chosen"]; nm = lv.get("trail_giveback", {}); na = lv.get("trail_activation", {})
        t = (f"Trailing: sau khi lãi tối đa đạt {mult_txt(cfg['tr']['act'])} × [{formula_text(a, 'kích hoạt')}]"
             + (f" (trung vị {na['px_pct_med']:.2f}% giá)" if "px_pct_med" in na else "")
             + f", đặt stop dưới đỉnh {mult_txt(cfg['tr']['gb'])} × [{formula_text(g, 'giveback')}]"
             + (f" (trung vị {nm['px_pct_med']:.2f}% giá)" if "px_pct_med" in nm else ""))
        parts.append(t + ".")
    if cfg.get("bes") is not None:
        nm = lv.get("be_trigger", {})
        parts.append(f"Hoà vốn (kéo stop): khi lãi tối đa ≥ {cfg['bes']['m']:.2f} × mức cơ sở" + (f" (trung vị {nm['px_pct_med']:.2f}% giá)" if "px_pct_med" in nm else "")
                     + f", dời stop về giá neo {cfg['bes']['off']:+.0f} bps.")
    if cfg.get("brd") is not None:
        nm = lv.get("be_depth", {})
        parts.append(f"Hoà vốn (hồi về): khi từng lỗ ≥ {cfg['brd']['m']:.2f} × mức cơ sở" + (f" (trung vị {nm['px_pct_med']:.2f}% giá)" if "px_pct_med" in nm else "")
                     + f", đặt limit thoát tại giá neo {cfg['brd']['off']:+.0f} bps.")
    if cfg.get("tc") is not None:
        tc = cfg["tc"]
        parts.append(f"Giới hạn thời gian: thoát market sau {tc['min']} phút kể từ {'fill cuối' if tc['ref'] == 1 else 'fill đầu'}" + (" (chỉ khi đang lỗ)." if tc["loss"] else "."))
    if len(parts) == 1:
        parts.append("Không có phần tử thoát nào cải thiện đủ ngưỡng.")
    if groups_info and S.G > 1:
        parts.append("Nhóm tham số: " + "; ".join(f"{i} = {t}" for i, t in enumerate(groups_info)) + ".")
    return " ".join(parts)


def label_groups(key, info, D, grp):
    G = int(grp.max()) + 1; out = []
    for g in range(G):
        m = grp == g
        if key == "lớp mã":
            out.append(" + ".join(CLS_NAMES[int(c)] for c in sorted(set(D.cls[m].tolist()))))
        elif key == "từng mã":
            out.append(info["syms"][g] if g < len(info.get("syms", [])) else str(g))
        else:
            d0 = pd.Timestamp(int(D.t1[m].min()), unit="ms").strftime("%Y-%m-%d"); d1 = pd.Timestamp(int(D.t1[m].max()), unit="ms").strftime("%Y-%m-%d")
            out.append(f"{d0} → {d1} (đóng lệnh)")
    return out


def verdict(m15, corr_min, beats_shuffle):
    if m15 >= 60 and corr_min >= 0.7:
        v = "tiệm cận tốt"
    elif (m15 >= 35 or (m15 >= 20 and corr_min >= 0.5)) and beats_shuffle:
        v = "tiệm cận một phần"
    else:
        v = "không tiệm cận được"
    return v


# ===================================================================== đường ablation chuẩn + lựa chọn luật
ELEM_ORDER = [("tp", "chỉ TP"), ("tpk", "+ TP gắn với độ sâu lỗ đã qua"), ("sl", "+ SL"), ("tr", "+ trailing"), ("bes", "+ hoà vốn (kéo stop)"), ("brd", "+ hoà vốn (hồi về)"), ("tc", "+ giới hạn thời gian")]
ELEM_NAME = dict(ELEM_ORDER)


def _row(S, cfg, step, prev_obj=None, accepted=None):
    m = S.score(cfg)
    r = dict(step=step, structure=list(structure(cfg)), obj=round(m["obj"], 4), m5=round(100 * m["m5"], 1), m15=round(100 * m["m15"], 1), m60=round(100 * m["m60"], 1),
             px_med_bps=round(m["px_med"], 1), sign=round(100 * m["sign"], 1), corr_ret=round(m["corr_ret"], 3), corr_usdt=round(m["corr_usdt"], 3))
    if prev_obj is not None:
        r["gain"] = round(m["obj"] - prev_obj, 4)
    if accepted is not None:
        r["accepted"] = bool(accepted)
    return r


def canonical(S, ai, verbose=False):
    """Đường ablation chuẩn ở neo ai: không luật -> TP -> +SL -> +trailing -> +BE -> +thời gian (phần tử chỉ giữ nếu gain >= MIN_GAIN),
    rồi loại ngược từng phần tử (backward elimination). Trả (cfg, steps, drops)."""
    S.grp = np.zeros(S.D.n, np.int64); S.G = 1
    cfg = dict(anchor=ai)
    steps = [_row(S, cfg, "không luật (đóng cưỡng bức cuối horizon)")]
    prev = steps[0]["obj"]
    for name, label in ELEM_ORDER:
        if name == "tpk" and cfg.get("tp") is None:
            continue
        trial = _cp(cfg); S.init_elem(trial, name)
        S.tune(trial)
        r = _row(S, trial, label, prev, None)
        r["accepted"] = bool(r["obj"] - prev >= MIN_GAIN)
        steps.append(r)
        if r["accepted"]:
            cfg = trial; prev = r["obj"]
    # loại ngược
    drops = []
    changed = True
    while changed:
        changed = False
        for name in list(structure(cfg)):
            if len(structure(cfg)) == 1:
                break
            trial = _cp(cfg); trial[name] = None
            if name == "tp":
                trial["tpk"] = None
            S.tune(trial)
            o = S.score(trial)["obj"]; o_full = S.score(cfg)["obj"]
            drops.append(dict(bỏ=ELEM_NAME[name].replace("+ ", ""), obj_sau_khi_bỏ=round(o, 4), mất=round(o_full - o, 4), giữ=bool(o_full - o >= MIN_GAIN)))
            if o_full - o < MIN_GAIN:
                cfg = trial; changed = True; break
    S.tune(cfg)
    # tìm kiếm ngẫu nhiên cấu trúc+tham số: nhận nếu hơn đường tham lam >= MIN_GAIN
    o_g = S.score(cfg)["obj"]
    jr = joint_random(S, ai)
    if jr is not None and jr[0] - o_g >= MIN_GAIN:
        cfg = jr[1]
        steps.append(_row(S, cfg, "tìm kiếm ngẫu nhiên cả cấu trúc (thay đường tham lam)", o_g, True))
        changed = True
        while changed:
            changed = False
            for name in list(structure(cfg)):
                if len(structure(cfg)) == 1:
                    break
                trial = _cp(cfg); trial[name] = None
                if name == "tp":
                    trial["tpk"] = None
                S.tune(trial)
                o = S.score(trial)["obj"]; o_full = S.score(cfg)["obj"]
                drops.append(dict(bỏ=ELEM_NAME[name].replace("+ ", ""), obj_sau_khi_bỏ=round(o, 4), mất=round(o_full - o, 4), giữ=bool(o_full - o >= MIN_GAIN)))
                if o_full - o < MIN_GAIN:
                    cfg = trial; changed = True; break
        S.tune(cfg)
    return clean(cfg), steps, drops


def joint_random(S, ai, n=3000, seed=0, top=4):
    """Tìm kiếm ngẫu nhiên CẢ cấu trúc lẫn tham số (thoát khỏi cực trị cục bộ của đường tham lam), rồi tinh chỉnh `top` ứng viên tốt nhất."""
    S.grp = np.zeros(S.D.n, np.int64); S.G = 1
    rng = np.random.default_rng(seed + ai); cands = []
    lu = lambda a, b: float(np.exp(rng.uniform(np.log(a), np.log(b))))
    for _ in range(n):
        c = dict(anchor=ai)
        if rng.random() < 0.85:
            c["tp"] = np.array([lu(0.3, 3.0)])
        if rng.random() < 0.4:
            c["sl"] = np.array([lu(0.3, 6.0)])
        if rng.random() < 0.55:
            c["tr"] = dict(gb=np.array([lu(0.3, 3.0)]), act=np.array([float(rng.choice(G_ACT))]))
        if "tp" in c and rng.random() < 0.3:
            c["tpk"] = float(rng.choice(G_TPK))
        if rng.random() < 0.3:
            c["bes"] = dict(m=lu(0.3, 4.0), off=float(rng.choice(G_OFF)))
        if rng.random() < 0.3:
            c["brd"] = dict(m=lu(0.3, 5.0), off=float(rng.choice(G_OFF)))
        if rng.random() < 0.3:
            c["tc"] = dict(min=float(rng.choice(G_TCMIN)), ref=int(rng.integers(0, 2)), loss=int(rng.integers(0, 2)))
        if not structure(c):
            continue
        cands.append((S.score(c)["obj"], c))
    cands.sort(key=lambda x: -x[0])
    best = None
    for o, c in cands[:top]:
        c2 = _cp(c); o2 = S.tune(c2, passes=3)
        if best is None or o2 > best[0]:
            best = (o2, c2)
    return best


def single_elem_rows(S, ai):
    """Mỗi phần tử đứng một mình (không kèm phần tử khác) để thấy phần tử nào có sức giải thích riêng."""
    rows = []
    for name, label in ELEM_ORDER:
        cfg = dict(anchor=ai); S.init_elem(cfg, name); S.tune(cfg)
        r = _row(S, cfg, "chỉ " + label.replace("+ ", "").replace("chỉ ", ""))
        rows.append(r)
    return rows


def split_tune(S, cfg, grp, G):
    """Tách tham số theo nhóm: khởi tạo từ nghiệm chung rồi tune lại từng nhóm. Trả (cfg2, obj)."""
    S.grp = grp; S.G = G
    c2 = _cp(cfg)
    for k in ("tp", "sl"):
        if c2.get(k) is None:
            c2[k] = np.full(G, INF)
        else:
            c2[k] = np.full(G, float(c2[k][0]))
    if c2.get("tr") is None:
        c2["tr"] = dict(gb=np.full(G, INF), act=np.ones(G))
    else:
        c2["tr"] = dict(gb=np.full(G, float(c2["tr"]["gb"][0])), act=np.full(G, float(c2["tr"]["act"][0])))
    o = S.tune(c2, passes=3)
    return c2, o


def oos_check(S, cfg, grp, G, seeds=4):
    """Kiểm tra quá khớp: khớp trên 1 nửa basket ngẫu nhiên, đo trên nửa còn lại. Trả (global_test, split_test, global_train, split_train)."""
    rng = np.random.default_rng(7); n = S.D.n
    res = dict(g_te=[], s_te=[], g_tr=[], s_tr=[])
    for sd in range(seeds):
        msk = rng.random(n) < 0.5
        # chung
        S.grp = np.zeros(n, np.int64); S.G = 1
        c = _cp(cfg)
        for k in ("tp", "sl"):
            if c.get(k) is not None:
                c[k] = np.array([float(cfg[k][0])])
        if c.get("tr") is not None:
            c["tr"] = dict(gb=np.array([float(cfg["tr"]["gb"][0])]), act=np.array([float(cfg["tr"]["act"][0])]))
        S.tune(c, passes=2, idx=msk)
        res["g_tr"].append(S.score(c, msk)["obj"]); res["g_te"].append(S.score(c, ~msk)["obj"])
        # tách
        S.grp = grp; S.G = G
        c2 = _cp(cfg)
        for k in ("tp", "sl"):
            c2[k] = np.full(G, float(c[k][0])) if c.get(k) is not None else np.full(G, INF)
        c2["tr"] = dict(gb=np.full(G, float(c["tr"]["gb"][0])), act=np.full(G, float(c["tr"]["act"][0]))) if c.get("tr") is not None else dict(gb=np.full(G, INF), act=np.ones(G))
        c2["tpk"] = c.get("tpk")
        S.tune(c2, passes=2, idx=msk)
        res["s_tr"].append(S.score(c2, msk)["obj"]); res["s_te"].append(S.score(c2, ~msk)["obj"])
    S.grp = np.zeros(n, np.int64); S.G = 1
    return {k: round(float(np.mean(v)), 4) for k, v in res.items()}


def set_form(S, an, elem, cand):
    S.fits[an][elem]["chosen"] = dict(form=cand["form"], desc=cand["desc"], a=cand["a"], b=cand["b"], kind=cand["kind"], rcv=cand["rcv"], n=cand["n"])
    S._base[an] = S._bases(an)


# ===================================================================== dựng sim (schema bots.json / match)
def sim_structs(D, o):
    Ss = []; trades = []
    for k, b in enumerate(D.B):
        j0, j1 = D.foff[k], D.foff[k + 1]
        fills = []; closes = []
        s = int(D.s[k])
        for li, j in enumerate(range(j0, j1)):
            if o.f_ct[j] < 0:
                continue
            f = b["fills"][li]
            fills.append(dict(t=int(f["t"]), px=float(f["px"]), notional=float(f["notional"])))
            closes.append(dict(t=int(o.f_ct[j]), px=float(o.f_cp[j]), qty=float(f["qty"]), layer=li))
            nt = f["notional"]; xp = o.f_cp[j]
            gross = s * (xp / f["px"] - 1) * nt; fee = FEE * (nt + nt * xp / f["px"]); pnl = gross - fee
            if o.f_why[j] == 7:      # chưa đóng trong horizon: không tính PnL đã thực hiện, không đưa vào danh sách trade
                continue
            trades.append(dict(sym=b["sym"], side=b["side"], lev=f["lev"], o=int(f["t"]), c=int(o.f_ct[j]), po=float(f["px"]), pc=float(xp), pnl=float(pnl),
                               pr=float(pnl / f["mg"] * 100), mg=f["mg"], why=int(o.f_why[j])))
        ret = o.pnl[k] / o.notional[k] * 100 if o.notional[k] > 0 else 0.0
        Ss.append(dict(fills=fills, closes=closes, ret=float(ret), pnl=float(o.pnl[k]), closed=bool(o.closed[k] == 1)))
    return Ss, trades


def _stats_light(st):
    keep = ["n", "perDay", "win", "realized", "pf", "payoff", "longPct", "levMed", "holdMed", "holdWin", "holdLoss", "maxLoss", "maxWin", "top5Share", "addPct",
            "addDownPct", "stepMed", "maxLayers", "baskets", "winMaeMed", "momPct"]
    return {k: st.get(k) for k in keep}


def top_alternatives(S, best_cfg, k=5):
    """Top-k cấu hình khác (khác cấu trúc/neo trước, rồi khác tham số) từ nhật ký đánh giá G=1."""
    seen = set(); out = []
    bk = (best_cfg["anchor"], structure(best_cfg))
    cand = sorted([x for x in S.log if x[7] == 1], key=lambda x: -x[0])
    for rank in (0, 1):
        for x in cand:
            cfg = x[6]; sk = (cfg["anchor"], structure(cfg))
            key = x[1]
            if key in seen:
                continue
            if rank == 0 and (sk == bk or sk in {o["_sk"] for o in out}):
                continue
            if rank == 1 and sk == bk and abs(x[0] - S.score(best_cfg)["obj"]) < 1e-6:
                continue
            seen.add(key)
            out.append(dict(_sk=sk, obj=round(x[0], 4), m15=round(100 * x[2], 1), corr_usdt=round(x[3], 3), sign=round(100 * x[4], 1), px_med_bps=round(x[5], 1),
                            structure=list(structure(cfg)), params=cfg_params(cfg)))
            if len(out) >= k:
                break
        if len(out) >= k:
            break
    for o in out:
        o.pop("_sk")
    return out


# ===================================================================== pipeline cho 1 bot
def fit_bot(name, out_dir="out", verbose=True):
    import time, json, copy, os
    t_start = time.time()
    P = (lambda *a: print(f"[{name}]", *a, flush=True)) if verbose else (lambda *a: None)
    bot = load.get_bot(name)
    D = Data(bot, verbose=verbose)
    df = facts(D); cl = classify(df); df["cl"] = cl
    mix = class_mix(df)
    ld = layer_facts(D); lcl = classify(ld); ld["cl"] = lcl
    layer_mix = {k: int((lcl == k).sum()) for k in CLASSES}
    P("lớp thoát:", mix)
    fits = {an: fit_elements(df, cl, an) for an in ("avg", "first", "last")}
    fits["layer"] = fit_elements(ld, lcl, "layer")
    S = Searcher(D, df, fits)
    P("fit công thức xong; scale_bps=%.1f" % S.scale_bps)

    # ---- đường ablation chuẩn ở từng neo
    per_anchor = {}
    for ai, an in enumerate(ANCHORS):
        cfg, steps, drops = canonical(S, ai)
        per_anchor[an] = dict(cfg=cfg, steps=steps, drops=drops, obj=S.score(cfg)["obj"], tp_only=[s for s in steps if s["step"] == "chỉ TP"][0]["obj"])
        P(f"neo {an}: TP-only={per_anchor[an]['tp_only']:.4f} final={per_anchor[an]['obj']:.4f} cấu trúc={structure(cfg)} evals={S.n_eval}")
    best_an = max(per_anchor, key=lambda a: per_anchor[a]["obj"])
    ai = ANCHORS.index(best_an); cfg = per_anchor[best_an]["cfg"]; steps = per_anchor[best_an]["steps"]; drops = per_anchor[best_an]["drops"]

    # ---- kiểm tra dạng công thức TP/SL bằng engine (ngoài CV): thử từng dạng ở neo tốt nhất
    form_check = {}
    for elem in ("tp", "sl"):
        if cfg.get(elem) is None:
            continue
        orig = dict(fits[best_an][elem]["chosen"]); rows = []
        tab = fits[best_an][elem]["table"]
        if not tab:
            continue
        bestf = (S.score(cfg)["obj"], orig["form"], orig)
        for cand in tab:
            set_form(S, best_an, elem, cand)
            c2 = _cp(cfg); o = S.tune(c2, passes=1)
            rows.append(dict(form=cand["form"], rcv=cand["rcv"], obj=round(o, 4)))
            if o > bestf[0] + 1e-9:
                bestf = (o, cand["form"], cand)
        set_form(S, best_an, elem, orig)
        adopt = bestf[0] - S.score(cfg)["obj"] >= 0.005 and bestf[1] != orig["form"]
        form_check[elem] = dict(cv_chosen=orig["form"], engine_best=bestf[1], rows=rows, adopted=bool(adopt))
        if adopt:
            set_form(S, best_an, elem, bestf[2]); S.tune(cfg, passes=2)
            P(f"dạng {elem} đổi theo engine: {orig['form']} -> {bestf[1]}")
    obj_main = S.score(cfg)["obj"]
    P(f"luật tốt nhất: neo={best_an} cấu trúc={structure(cfg)} obj={obj_main:.4f}")
    base_cfg = _cp(cfg)

    # ---- ablation phần tử đơn lẻ (ở neo tốt nhất)
    singles = single_elem_rows(S, ai)

    # ---- tách theo lớp mã / chế độ
    splits = {}
    sp_defs = [("lớp mã", group_class(D)), ("từng mã", group_sym(D)), ("tuần lịch", group_week(D)), ("điểm đổi chế độ", group_cp(D, df))]
    best_split = None
    for key, (grp, info) in sp_defs:
        pass
    for key, (grp, info) in sp_defs:
        G = int(grp.max()) + 1
        if G < 2:
            splits[key] = dict(skipped=True, **{k: v for k, v in info.items() if k != "n_groups"}, n_groups=G); continue
        c2, o2 = split_tune(S, base_cfg, grp, G)
        n_par = (G - 1) * sum(1 for k in ("tp", "sl", "tr") if base_cfg.get(k) is not None)
        oos = oos_check(S, base_cfg, grp, G)
        info = dict(info); info["group_labels"] = label_groups(key, info, D, grp)
        splits[key] = dict(**{k: v for k, v in info.items() if k != "n_groups"}, n_groups=G, obj=round(o2, 4), gain=round(o2 - obj_main, 4), extra_params=n_par,
                           gain_per_param=round((o2 - obj_main) / max(1, n_par), 5), params=cfg_params(c2),
                           group_sizes=[int((grp == g).sum()) for g in range(G)], oos=oos,
                           oos_gain_heldout=round(oos["s_te"] - oos["g_te"], 4))
        splits[key]["_cfg"] = c2; splits[key]["_grp"] = grp; splits[key]["_G"] = G
        P(f"tách {key}: G={G} obj={o2:.4f} (+{o2 - obj_main:.4f}) | OOS giữ-lại: chung {oos['g_te']:.4f} vs tách {oos['s_te']:.4f}")
    S.grp = np.zeros(D.n, np.int64); S.G = 1
    # chọn tách: chỉ nhận nếu gain >= 0.01 VÀ cải thiện trên nửa giữ lại > 0
    chosen_split = None
    for key, v in splits.items():
        if v.get("skipped"):
            continue
        if v["gain"] >= 0.01 and v["oos_gain_heldout"] > 0 and (chosen_split is None or v["oos_gain_heldout"] > splits[chosen_split]["oos_gain_heldout"]):
            chosen_split = key
    ablation = list(steps)
    for key, v in splits.items():
        if v.get("skipped"):
            continue
        ablation.append(dict(step="+ tách tham số theo " + key, structure=list(structure(base_cfg)), obj=v["obj"], gain=v["gain"], extra_params=v["extra_params"],
                             oos_gain_heldout=v["oos_gain_heldout"], accepted=bool(key == chosen_split)))
    if chosen_split:
        final_cfg = clean(splits[chosen_split]["_cfg"]); S.grp = splits[chosen_split]["_grp"]; S.G = splits[chosen_split]["_G"]
    else:
        final_cfg = clean(base_cfg)
    m_final, o_final = S.score(final_cfg, keep=True)
    P(f"cuối cùng: obj={m_final['obj']:.4f} m15={100*m_final['m15']:.1f}% corr_usdt={m_final['corr_usdt']:.3f} chọn tách={chosen_split}")

    # ---- baselines
    rng = np.random.default_rng(0)
    med_hold = float(np.median(D.hold_min))
    save_grp, save_G = S.grp, S.G
    S.grp = np.zeros(D.n, np.int64); S.G = 1
    null_cfg = dict(anchor=0, tc=dict(min=round(med_hold, 1), ref=0, loss=0))
    null_m = S.score(null_cfg)
    tc_cfg = dict(anchor=0); S.init_elem(tc_cfg, "tc"); S.tune(tc_cfg); tc_m = S.score(tc_cfg)
    S.grp, S.G = save_grp, save_G
    Lf = S.levels(final_cfg); sh = []
    for sd in range(20):
        perm = np.random.default_rng(100 + sd).permutation(D.n)
        L2 = {k: (v[perm] if isinstance(v, np.ndarray) and len(v) == D.n else v) for k, v in Lf.items()}
        sh.append(metrics(D, run(D, L2, Out(D)), S.scale_bps))
    shuf = {k: dict(mean=round(float(np.mean([x[k] for x in sh])), 4), p95=round(float(np.percentile([x[k] for x in sh], 95)), 4)) for k in ("obj", "m15", "corr_usdt", "sign", "px_med")}
    baselines = dict(
        null_time_stop_median_hold=dict(minutes=round(med_hold, 1), **{k: round(float(v), 4) for k, v in null_m.items()}),
        best_time_cap_only=dict(params=cfg_params(tc_cfg), **{k: round(float(v), 4) for k, v in tc_m.items()}),
        shuffled_levels_20seeds=shuf,
        note="shuffled: giữ nguyên toàn bộ bộ mức của luật tốt nhất nhưng gán hoán vị ngẫu nhiên cho các basket (20 seed)")

    # ---- chỉ số chi tiết (level_a), thống kê báo cáo OKX thật vs sim
    Ss, sim_T = sim_structs(D, o_final)
    rows = [match.basket_row(D.B[k], Ss[k]) for k in range(D.n)]
    la = match.level_a(rows)
    real_T = D.real_trades()
    st_real = ST.stats(copy.deepcopy(real_T)); st_sim = ST.stats(copy.deepcopy(sim_T))
    cmp = ST.compare(st_real, st_sim)
    lo, hi = min(t["o"] for t in real_T), max(t["c"] for t in real_T)
    dc = ST.daily_corr(real_T, sim_T, lo, hi)
    why_cnt = {WHY[int(w)]: int((o_final.why == w).sum()) for w in np.unique(o_final.why)}
    corr_min = min(la.get("pnl_corr") or 0, la.get("pnl_corr_usdt") or 0)
    beats = bool(m_final["obj"] > shuf["obj"]["p95"] and m_final["obj"] > null_m["obj"])
    vd = verdict(la["close_match_15"], corr_min, beats)

    # ---- basket tiêu biểu
    dt = np.where((o_final.closed == 1) & (o_final.nused > 0), np.abs(o_final.ct - D.t1) / MIN, np.inf)
    order = np.argsort(dt, kind="stable")
    finite = [i for i in order if np.isfinite(dt[i])]
    pick = dict(khớp_nhất=int(finite[0]) if finite else int(order[0]), khớp_trung_vị=int(order[len(order) // 2]), khớp_tệ_nhất=int(order[-1]),
                lãi_lớn_nhất=int(np.argmax(D.real_pnl)), lỗ_lớn_nhất=int(np.argmin(D.real_pnl)))
    reps = {}
    for nm, k in pick.items():
        r = dict(rows[k]); r["real_class"] = str(cl[k]); r["sim_why"] = WHY[int(o_final.why[k])]; r["dt_phút"] = None if not np.isfinite(dt[k]) else round(float(dt[k]), 1)
        r["sym_cls"] = CLS_NAMES[int(D.cls[k])]
        reps[nm] = r

    # ---- công thức xuất ra (neo tốt nhất)
    lv = level_summary(S, final_cfg)
    fa = fits[best_an]
    def fm(elem):
        e = fa[elem]; ch = e["chosen"]
        return dict(src=e["src"], n_class=e["n"], form=ch["form"], desc=ch["desc"], a=round(ch["a"], 5), b=[round(x, 5) for x in ch["b"]], rcv=None if ch["rcv"] is None else round(ch["rcv"], 4),
                    text_vi=formula_text(ch, {"tp": "TP", "sl": "SL", "gb": "giveback", "act": "kích hoạt trailing", "bes": "kích hoạt hoà vốn", "brd": "độ sâu hoà vốn"}[elem]),
                    cv_table=e["table"])
    formulas = {e: fm(e) for e in ("tp", "sl", "gb", "act", "bes", "brd")}
    formulas["neo_so_sánh"] = {an: {e: dict(form=fits[an][e]["chosen"]["form"], rcv=fits[an][e]["chosen"]["rcv"], n=fits[an][e]["n"], src=fits[an][e]["src"]) for e in ("tp", "sl", "gb", "act", "bes", "brd")}
                               for an in fits}
    formulas["kiểm_tra_dạng_bằng_engine"] = form_check
    txt = text_vi(S, final_cfg, fa, lv, best_an, splits[chosen_split]["group_labels"] if chosen_split else None)
    res = dict(
        bot=name, in_sample=True, caveat="IN-SAMPLE: tham số khớp trên toàn bộ dữ liệu bot, mô tả tiệm cận luật thoát, KHÔNG phải kiểm định ngoài mẫu",
        n_baskets=D.n, n_dropped=len(D.dropped), n_sub_positions=int(len(real_T)), staged_baskets=int(D.staged.sum()),
        facts=facts_summary(df),
        class_mix=dict(counts=mix, pct={k: round(100 * v / D.n, 1) for k, v in mix.items()}, thresholds=THR, sensitivity=sensitivity(df),
                       sub_position_level=dict(counts=layer_mix, n=int(len(ld)))),
        formulas=formulas,
        best_rule=dict(text_vi=txt, params=cfg_params(final_cfg), split_labels=(splits[chosen_split]["group_labels"] if chosen_split else None), anchor=best_an, structure=list(structure(final_cfg)), levels=lv, split=chosen_split,
                       exit_reasons=why_cnt, objective=round(m_final["obj"], 4), objective_def="trung bình(exit±15, 1-median sai số giá/scale, đồng dấu PnL, max(0,corr PnL USDT)); scale=%.0f bps" % S.scale_bps),
        top5_alternatives=top_alternatives(S, base_cfg),
        anchors={an: dict(final_obj=round(v["obj"], 4), tp_only_obj=round(v["tp_only"], 4), structure=list(structure(v["cfg"])), params=cfg_params(v["cfg"])) for an, v in per_anchor.items()},
        ablation=ablation, ablation_drop_one=drops, ablation_single_element=singles,
        regimes=dict(chosen=chosen_split, options={k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in splits.items()},
                     note="chỉ nhận tách khi gain>=0.01 và cải thiện trên nửa giữ lại (OOS split-half) > 0"),
        metrics=dict(
            exit_match_5=la.get("close_match_5"), exit_match_15=la.get("close_match_15"), exit_match_60=la.get("close_match_60"),
            exit_px_err_bps_med=la.get("close_px_err_bps_med"), exit_px_err_bps_p90=la.get("close_px_err_bps_p90"), sim_closed_pct=la.get("sim_closed_pct"),
            layer_close_match5=la.get("layer_close_match5"), layer_close_n=la.get("layer_close_n"),
            pnl_sign_agree=la.get("pnl_sign_agree"), pnl_corr=la.get("pnl_corr"), pnl_corr_usdt=la.get("pnl_corr_usdt"), pnl_med_abs_err_pp=la.get("pnl_med_abs_err_pp"),
            real_pnl_sum=la.get("act_pnl_sum"), sim_pnl_sum=la.get("sim_pnl_sum"), real_win_pct=la.get("act_win_pct"), sim_win_pct=la.get("sim_win_pct"),
            level_a=la, cum_curve=match.cum_curve(rows),
            report_stats=dict(real=_stats_light(st_real), sim=_stats_light(st_sim), compare=cmp, daily=dc),
            unclosed=dict(n=int((o_final.closed == 0).sum()), mtm_pnl_at_horizon=round(float(o_final.mtm[o_final.closed == 0].sum()), 1),
                          real_pnl_of_those=round(float(D.real_pnl[o_final.closed == 0].sum()), 1),
                          note="basket sim chưa đóng trước t1 thật + 60 phút: tính là KHÔNG khớp, PnL đã thực hiện = 0 (mtm chỉ để tham khảo, tránh rò rỉ thời điểm thoát thật)"),
            note_fees="PnL sim = gộp - phí 3.5 bps/chiều (funding bỏ qua); PnL thật = số liệu OKX (đã gồm phí+funding)"),
        baselines=baselines, representative_baskets=reps,
        verdict=dict(label=vd, exit15=la["close_match_15"], corr_min=round(corr_min, 3), beats_baselines=beats,
                     text_vi=(f"{vd}: thoát ±15 phút {la['close_match_15']:.1f}% (±5: {la['close_match_5']:.1f}%, ±60: {la['close_match_60']:.1f}%), tương quan PnL {la.get('pnl_corr')} (%), {la.get('pnl_corr_usdt')} (USDT), "
                              f"đồng dấu PnL {la.get('pnl_sign_agree'):.1f}%, sai số giá thoát trung vị {la.get('close_px_err_bps_med')} bps; null time-stop ±15 = {100*null_m['m15']:.1f}%, "
                              f"hoán vị mức ±15 = {100*shuf['m15']['mean']:.1f}%. Đây là khớp IN-SAMPLE (tham số chỉnh trên chính dữ liệu), không phải dự báo." + (f" CẢNH BÁO mẫu nhỏ: chỉ {D.n} basket, tham số dễ quá khớp." if D.n < 30 else ""))),
        sim_trades=sim_trades_json(sim_T),
        runtime_sec=round(time.time() - t_start, 1), n_engine_evals=S.n_eval)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"implied_{load.slug(name)}.json")
    json.dump(_jr(res), open(path, "w"), ensure_ascii=False)
    P(f"xong {res['runtime_sec']}s -> {path}; verdict={vd}")
    return res


def facts_summary(df):
    """Tóm tắt sự kiện thoát ngầm (Bước 1): phân vị chung + hồ sơ theo lớp + phân phối giờ/thứ của lúc đóng."""
    q = lambda c: {f"p{p}": round(float(np.percentile(df[c], p)), 4) for p in (10, 25, 50, 75, 90)}
    over = {c: q(c) for c in ("ret", "mfe", "mae", "giveback", "hold_min", "n_layers", "lev", "atr1_0", "atr15_0", "atr60_0", "atr1_x", "atr60_x", "touch_lag_min")}
    prof = {}
    for k, g in df.groupby("cl"):
        prof[k] = dict(n=int(len(g)), **{f"{c}_med": round(float(g[c].median()), 4) for c in ("ret", "mfe", "mae", "giveback", "hold_min", "touch_lag_min", "atr60_0", "lev", "n_layers")},
                       ret_p10=round(float(g.ret.quantile(.1)), 4), ret_p90=round(float(g.ret.quantile(.9)), 4))
    hx = ((df.t1 // H1 + 7) % 24).astype(int); wx = ((df.t1 // DAY + 3) % 7).astype(int)
    return dict(overall=over, per_class=prof, exit_hour_vn_hist=np.bincount(hx, minlength=24).tolist(), exit_weekday_hist=np.bincount(wx, minlength=7).tolist(),
                side_long_pct=round(float((df.s > 0).mean() * 100), 1), cls_mix_symbol={CLS_NAMES[k]: int((df.cls == k).sum()) for k in range(4)},
                note="ret/mfe/mae/giveback: % giá so với giá vốn trung bình, trước phí; atr: % giá")


def sim_trades_json(sim_T):
    return [{k: v for k, v in t.items() if k != "why"} | {"exit_why": WHY.get(t.get("why"), "")} for t in sim_T]
