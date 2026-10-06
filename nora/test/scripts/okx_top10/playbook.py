"""Phase 3 - PLAYBOOK: chien luoc cua tung bot viet thanh luat tuong minh (vao / them / thoat / khoi luong), moi tham so uoc luong
TRUC TIEP tu thong ke TRAIN cua chinh bot (khong grid-search theo diem khop), chay free-running tren nen 1m that.

Quy uoc khong look-ahead: quyet dinh o nen j DA DONG, khop tai OPEN nen j+1 (vao) hoac tai muc gia limit bi cham trong cac nen sau
(TP / add / stop; neu cung nen cham ca stop va TP -> stop truoc; nen vua khop xong khong xet them gi trong cung nen).
Funding bo qua (khong co du lieu) - dem so basket giu > 8h.
"""
import math
import numpy as np
import pandas as pd
import numba as nb

import load
import disc_stats as ST

MIN = 60_000
H1 = 3600_000
DAY = 86400_000

STOCK = {"AAOI", "AAPL", "AMD", "AMZN", "CBRS", "CRCL", "GOOGL", "INTC", "LITE", "META", "MRVL", "MSFT", "MSTR", "MU", "NBIS", "NVDA",
         "PLTR", "QCOM", "SAMSUNG", "SKHY", "SKHYNIX", "SNDK", "SOXL", "SPCX", "TSLA", "DRAM"}
COMMOD = {"XAU", "XAG", "CL"}
MAJOR = {"BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA"}
CLS_NAMES = {0: "cổ phiếu/ETF perp", 1: "hàng hóa", 2: "crypto lớn", 3: "crypto khác"}


def sym_class(sym):
    return 0 if sym in STOCK else 1 if sym in COMMOD else 2 if sym in MAJOR else 3


# ======================================================================= luoi nen 1m chung
class Grid:
    """Ma tran [S,T] o/h/l/c (NaN neu thieu nen) tren luoi 1m chung, T0 can theo gio. cf = close ffill (cho dac trung)."""

    def __init__(self, syms, t_lo, t_hi, warm_days=5):
        self.syms = list(syms); self.S = len(syms)
        self.T0 = int((t_lo - warm_days * DAY) // H1 * H1)
        n = int((t_hi - self.T0) // MIN) + 2
        n = (n + 59) // 60 * 60
        self.T = n
        o = np.full((self.S, n), np.nan); h = o.copy(); l = o.copy(); c = o.copy()
        for k, s in enumerate(self.syms):
            a = load.candle_arrays(s)
            idx = (a["t"] - self.T0) // MIN
            m = (idx >= 0) & (idx < n)
            ii = idx[m]
            o[k, ii] = a["o"][m]; h[k, ii] = a["h"][m]; l[k, ii] = a["l"][m]; c[k, ii] = a["c"][m]
        self.o, self.h, self.l, self.c = o, h, l, c
        cf = pd.DataFrame(c.T).ffill().bfill().values.T
        self.cf = np.ascontiguousarray(cf)
        tms = self.T0 + np.arange(n, dtype=np.int64) * MIN
        self.tms = tms
        self.bucket = ((tms % DAY) // (15 * MIN)).astype(np.int16)
        self.wday = (((tms // DAY) + 3) % 7).astype(np.int8)
        self.sidx = {s: k for k, s in enumerate(self.syms)}
        self._z = {}; self._ret = {}; self._atr = None

    def bar(self, t_ms):
        return int((t_ms - self.T0) // MIN)

    def ret(self, H):
        """c[t]/c[t-H]-1 tai nen t (da dong)."""
        if H not in self._ret:
            r = np.zeros_like(self.cf)
            r[:, H:] = self.cf[:, H:] / self.cf[:, :-H] - 1
            self._ret[H] = r
        return self._ret[H]

    def z(self, H, win=3 * 1440):
        """|ret_H| / trung vi cuon (3 ngay) cua |ret_H| cua cung ma, tai nen t da dong."""
        if H not in self._z:
            r = np.abs(self.ret(H))
            z = np.zeros_like(r)
            for k in range(self.S):
                rm = pd.Series(r[k]).rolling(win, min_periods=720).median().values
                z[k] = np.where(rm > 1e-9, r[k] / rm, 0.0)
            self._z[H] = z.astype(np.float32)
        return self._z[H]

    def atr(self):
        """ATR14 cua nen 1H DA DONG (dang phan so gia), gan cho moi phut cua gio ke tiep."""
        if self._atr is None:
            S, T = self.S, self.T; nh = T // 60
            hh = np.nanmax(np.where(np.isnan(self.h), -np.inf, self.h).reshape(S, nh, 60), axis=2)
            ll = np.nanmin(np.where(np.isnan(self.l), np.inf, self.l).reshape(S, nh, 60), axis=2)
            cc = self.cf.reshape(S, nh, 60)[:, :, -1]
            bad = ~np.isfinite(hh) | ~np.isfinite(ll)
            hh = np.where(bad, cc, hh); ll = np.where(bad, cc, ll)
            pc = np.concatenate([cc[:, :1], cc[:, :-1]], axis=1)
            tr = np.maximum(hh - ll, np.maximum(np.abs(hh - pc), np.abs(ll - pc))) / np.maximum(pc, 1e-12)
            a = pd.DataFrame(tr.T).rolling(14, min_periods=6).mean().values.T
            a = np.concatenate([np.full((S, 1), np.nan), a[:, :-1]], axis=1)       # chi dung gio da dong
            a = np.where(np.isnan(a), np.nanmedian(a[np.isfinite(a)]) if np.isfinite(a).any() else 0.005, a)
            self._atr = np.repeat(a, 60, axis=1).astype(np.float64)
        return self._atr


# ======================================================================= dong co (numba)
@nb.njit(cache=True)
def _engine(o, h, l, c, sig, tstart, tend, N0, tpf0, tpc, use_atr, atr, stop, be_thr, be_tp, step, ratio, maxL, maxhold, cool, maxconc,
            hedge, tp_same_bar, cap_b, cap_f, rsamp, stop_layers, trail_gb, trail_act_mult):
    """Tra (n_baskets, n_fills, overflow, arrays...). Chieu: d=0 long, d=1 short."""
    S, T = o.shape
    nst = S * 2
    isopen = np.zeros(nst, np.int8)
    nl = np.zeros(nst, np.int32)
    qty = np.zeros(nst); cost = np.zeros(nst); lastpx = np.zeros(nst)
    ent_t = np.zeros(nst, np.int64); last_fill_t = np.zeros(nst, np.int64)
    tpf = np.zeros(nst); mae = np.zeros(nst); pend = np.zeros(nst, np.int8); peak = np.zeros(nst)
    bid = np.zeros(nst, np.int64)
    last_close = np.full(nst, -10 ** 9, np.int64)
    # dau ra
    bk_s = np.zeros(cap_b, np.int32); bk_d = np.zeros(cap_b, np.int8); bk_t0 = np.zeros(cap_b, np.int64); bk_t1 = np.full(cap_b, -1, np.int64)
    bk_px1 = np.zeros(cap_b); bk_why = np.zeros(cap_b, np.int8); bk_t1sub = np.zeros(cap_b, np.int8)
    f_bk = np.zeros(cap_f, np.int32); f_t = np.zeros(cap_f, np.int64); f_px = np.zeros(cap_f); f_nt = np.zeros(cap_f)
    nb_ = 0; nf = 0; nopen = 0; overflow = 0
    for t in range(tstart, tend):
        for s in range(S):
            ot = o[s, t]
            if ot != ot:
                continue
            hi = h[s, t]; lo = l[s, t]
            for d in range(2):
                k = s * 2 + d
                sd = 1.0 if d == 0 else -1.0
                closed_now = False
                if isopen[k] == 1 and last_fill_t[k] < t:
                    avg = cost[k] / qty[k]
                    px = 0.0; why = 0; doclose = False
                    if pend[k] == 1:
                        px = ot; why = 3; doclose = True
                    else:
                        if stop[s] > 0 and nl[k] >= stop_layers:
                            sp = avg * (1.0 - sd * stop[s])
                            if (sd > 0 and lo <= sp) or (sd < 0 and hi >= sp):
                                px = min(ot, sp) if sd > 0 else max(ot, sp); why = 2; doclose = True
                        added = False
                        if (not doclose) and step[s] > 0:
                            while nl[k] < maxL[s]:
                                lvl = lastpx[k] * (1.0 - sd * step[s])
                                if (sd > 0 and lo <= lvl) or (sd < 0 and hi >= lvl):
                                    fpx = min(ot, lvl) if sd > 0 else max(ot, lvl)
                                    ri = nl[k] if nl[k] < ratio.shape[0] else ratio.shape[0] - 1
                                    nt = N0[s] * ratio[ri]
                                    if rsamp.shape[0] > 0:
                                        nt = N0[s] * rsamp[(nf * 2654435761 + nl[k] * 40503 + s * 7919) % rsamp.shape[0]]
                                    if nf >= cap_f:
                                        overflow = 1; break
                                    f_bk[nf] = bid[k]; f_t[nf] = t; f_px[nf] = fpx; f_nt[nf] = nt; nf += 1
                                    qty[k] += nt / fpx; cost[k] += nt; lastpx[k] = fpx; nl[k] += 1
                                    last_fill_t[k] = t; added = True
                                    avg = cost[k] / qty[k]
                                else:
                                    break
                        if (not doclose) and (not added) and (last_fill_t[k] < t or tp_same_bar):
                            tp = tpf[k]
                            if trail_gb[s] > 0:
                                # trailing: kich hoat khi loi nhuan dinh >= act (= TP * mult), thoat khi gia lui gb tu dinh
                                act = tp * trail_act_mult
                                if be_thr[s] > 0 and mae[k] >= be_thr[s] and be_tp < act:
                                    act = be_tp
                                if peak[k] > 0 and ((peak[k] - avg) / avg * sd) >= act:
                                    lvl = peak[k] * (1.0 - sd * trail_gb[s])
                                    # khong bao gio thoat duoi hoa von + phi (bot that khong chot lo bang trailing)
                                    flo = avg * (1.0 + sd * be_tp)
                                    if (sd > 0 and lvl < flo) or (sd < 0 and lvl > flo):
                                        lvl = flo
                                    if (sd > 0 and lo <= lvl) or (sd < 0 and hi >= lvl):
                                        px = min(ot, lvl) if sd > 0 else max(ot, lvl); why = 1; doclose = True
                                if not doclose:
                                    ext = hi if sd > 0 else lo
                                    if peak[k] == 0.0 or (sd > 0 and ext > peak[k]) or (sd < 0 and ext < peak[k]):
                                        peak[k] = ext
                            else:
                                if be_thr[s] > 0 and mae[k] >= be_thr[s] and be_tp < tp:
                                    tp = be_tp
                                tpx = avg * (1.0 + sd * tp)
                                if (sd > 0 and hi >= tpx) or (sd < 0 and lo <= tpx):
                                    px = max(ot, tpx) if sd > 0 else min(ot, tpx); why = 1; doclose = True
                    if doclose:
                        bk_t1[bid[k]] = t; bk_px1[bid[k]] = px; bk_why[bid[k]] = why
                        isopen[k] = 0; nopen -= 1; last_close[k] = t; closed_now = True
                    else:
                        avg = cost[k] / qty[k]
                        adv = (avg - lo) / avg if sd > 0 else (hi - avg) / avg
                        if adv > mae[k]:
                            mae[k] = adv
                        if maxhold > 0 and (t - ent_t[k]) >= maxhold:
                            pend[k] = 1
                # vao lenh moi
                if isopen[k] == 0 and (not closed_now) and sig[s, d, t] == 1 and t >= tstart + 1:
                    if (t - last_close[k]) >= cool and nopen < maxconc and (hedge == 1 or isopen[s * 2 + 1 - d] == 0):
                        if nb_ >= cap_b or nf >= cap_f:
                            overflow = 1
                        else:
                            nt = N0[s]
                            bid[k] = nb_
                            bk_s[nb_] = s; bk_d[nb_] = d; bk_t0[nb_] = t
                            f_bk[nf] = nb_; f_t[nf] = t; f_px[nf] = ot; f_nt[nf] = nt; nf += 1
                            nb_ += 1
                            isopen[k] = 1; nopen += 1; nl[k] = 1; qty[k] = nt / ot; cost[k] = nt; lastpx[k] = ot
                            ent_t[k] = t; last_fill_t[k] = t; mae[k] = 0.0; pend[k] = 0; peak[k] = 0.0
                            if use_atr[s] == 1:
                                a = atr[s, t - 1]
                                tpf[k] = tpc[s] * a
                            else:
                                tpf[k] = tpf0[s]
    return nb_, nf, overflow, nopen, bk_s, bk_d, bk_t0, bk_t1, bk_px1, bk_why, f_bk, f_t, f_px, f_nt


class Params(dict):
    """Tham so engine theo ma (mang dai S) + tham so toan cuc."""


def run_engine(grid, sig, P, tstart, tend, cap_b=60000, cap_f=300000):
    S = grid.S
    if "allow" in P:
        sig = sig * P["allow"][:, :, None]
    for _ in range(4):
        res = _engine(grid.o, grid.h, grid.l, grid.c, sig, int(tstart), int(tend), P["N0"], P["tp"], P["tp_c"], P["use_atr"], grid.atr(),
                      P["stop"], P["be_thr"], float(P["be_tp"]), P["step"], P["ratio"], P["maxL"], int(P["maxhold"]), int(P["cool"]),
                      int(P["maxconc"]), int(P["hedge"]), int(P.get("tp_same_bar", 0)), cap_b, cap_f, P.get("rsamp", np.zeros(0)), int(P.get("stop_layers", 1)), P.get("trail_gb", np.zeros(P["N0"].shape[0])), float(P.get("trail_act_mult", 1.0)))
        if res[2] == 0:
            return res
        cap_b *= 2; cap_f *= 2
    return res


def decode(grid, res, P, fee_bps, seed=0):
    """Chuyen ket qua engine -> list trade (schema bots.json) theo sub-position (moi fill = 1 trade, dong cung luc voi basket).
    Basket chua dong het cua so -> bo (giong du lieu that chi gom lenh da dong). Tra (trades, info)."""
    nb_, nf, ovf, nopen, bk_s, bk_d, bk_t0, bk_t1, bk_px1, bk_why, f_bk, f_t, f_px, f_nt = res
    f_bk = f_bk[:nf]; f_t = f_t[:nf]; f_px = f_px[:nf]; f_nt = f_nt[:nf]
    order = np.argsort(f_bk, kind="stable")
    f_bk = f_bk[order]; f_t = f_t[order]; f_px = f_px[order]; f_nt = f_nt[order]
    starts = np.searchsorted(f_bk, np.arange(nb_), "left"); ends = np.searchsorted(f_bk, np.arange(nb_), "right")
    trades = []; n_open = 0; n_long = 0; why_ct = {1: 0, 2: 0, 3: 0}
    rng = np.random.default_rng(777 + seed)
    split = (P["split_sample"], P["split_off_sample"]) if P.get("do_split") else None
    fee = fee_bps / 1e4
    T0 = grid.T0
    for b in range(nb_):
        if bk_t1[b] < 0:
            n_open += 1; continue
        s = int(bk_s[b]); d = int(bk_d[b]); sd = 1 if d == 0 else -1
        sym = grid.syms[s]; lev = float(P["lev"][s])
        t1 = T0 + int(bk_t1[b]) * MIN
        why = int(bk_why[b]); why_ct[why] = why_ct.get(why, 0) + 1
        t1ms = t1 + (30_000 if why in (1, 2) else 0)
        px1 = float(bk_px1[b])
        if (t1ms - (T0 + int(bk_t0[b]) * MIN)) > 8 * H1:
            n_long += 1
        for i in range(starts[b], ends[b]):
            m_ = 1
            if split is not None:
                m_ = int(split[0][rng.integers(len(split[0]))])
            cum = 0.0
            for j in range(m_):
                nt_ = f_nt[i] / m_
                if split is not None and j > 0:
                    cum += float(split[1][rng.integers(len(split[1]))])
                pxj = f_px[i] * (1 - sd * cum / 1e4)
                q = nt_ / pxj
                gross = q * (px1 - pxj) * sd
                pnl = gross - fee * q * (px1 + pxj)
                mg = nt_ / lev
                ot = T0 + int(f_t[i]) * MIN + (0 if i == starts[b] else 30_000) + 1000 * j
                trades.append(dict(sym=sym, side="long" if d == 0 else "short", lev=lev, o=int(ot), c=int(t1ms), po=float(pxj), pc=px1,
                                   pnl=round(pnl, 2), pr=round(pnl / mg * 100, 1), mg=round(mg, 2), why=why,
                                   bt0=int(T0 + int(bk_t0[b]) * MIN)))
    info = dict(n_baskets=int(nb_ - n_open), n_open_at_end=int(n_open), n_hold_gt8h=int(n_long), exits=dict(tp=why_ct.get(1, 0), stop=why_ct.get(2, 0), time=why_ct.get(3, 0)),
                funding="không áp dụng (không có dữ liệu funding)")
    return trades, info


# ======================================================================= ho so phap y tren TRAIN
KS = (1, 3, 5, 15, 30, 60, 240, 1440)
HV = (1, 3, 5, 15, 30, 60)


def _q(a, p, default=None):
    a = [x for x in a if x is not None and np.isfinite(x)]
    return float(np.percentile(a, p)) if a else default


def _med(a, default=None):
    return _q(a, 50, default)


def _cv(a):
    a = np.array([x for x in a if np.isfinite(x)])
    return float(a.std() / abs(a.mean())) if len(a) > 2 and abs(a.mean()) > 1e-12 else float("inf")


def basket_measures(grid, B):
    """Cac phep do cua 1 basket tren nen 1m: gross ret, MAE/MFE (so voi gia TB), hold, buoc add (tranche), ..."""
    s = grid.sidx[B["sym"]]; sd = 1 if B["side"] == "long" else -1
    i0 = grid.bar(B["t0"]); i1 = grid.bar(B["t1"])
    notional = sum(f["notional"] for f in B["fills"])
    gross = sum(cl["qty"] * (cl["px"] - B["fills"][cl["fill"]]["px"]) * sd for cl in B["closes"])
    avg = B["avg_px"]
    seg_l = grid.l[s, max(i0, 0):i1 + 1]; seg_h = grid.h[s, max(i0, 0):i1 + 1]
    if len(seg_l) and np.isfinite(seg_l).any():
        lo = np.nanmin(seg_l); hi = np.nanmax(seg_h)
    else:
        lo = hi = avg
    mae = max(0.0, (avg - lo) / avg if sd > 0 else (hi - avg) / avg)
    mfe = max(0.0, (hi - avg) / avg if sd > 0 else (avg - lo) / avg)
    gret = gross / notional
    trs = B["tranches"]
    steps = []
    for a_, b_ in zip(trs[:-1], trs[1:]):
        adv = (a_["px"] - b_["px"]) / a_["px"] if sd > 0 else (b_["px"] - a_["px"]) / a_["px"]
        steps.append(adv)
    atr = grid.atr()[s, min(max(i0 - 1, 0), grid.T - 1)]
    return dict(sym=B["sym"], cls=sym_class(B["sym"]), sd=sd, gret=gret, mae=mae, mfe=mfe, hold=(B["t1"] - B["t0"]) / MIN, pnl=B["pnl"],
                n_tr=len(trs), n_fills=len(B["fills"]), steps=steps, n0=trs[0]["notional"], tr_ratio=[g["notional"] / trs[0]["notional"] for g in trs[1:]],
                atr=float(atr), lev=B["lev"], t0=B["t0"], t1=B["t1"], i0=i0, s=s, notional=notional)


def implied_fee_bps(trades):
    r = []
    for t in trades:
        sd = 1 if t["side"] == "long" else -1
        q = t["mg"] * t["lev"] / t["po"]; g = q * (t["pc"] - t["po"]) * sd
        r.append((g - t["pnl"]) / (t["mg"] * t["lev"]) * 1e4)
    return float(np.median(r)) if r else 0.0


def auc_vol(grid, train, Hs=HV, n_rand=30, seed=1):
    """AUC (entry vs ngau nhien cung ma, cung khung 15 phut, trong cua so TRAIN) cua z_H tai nen quyet dinh (nen truoc fill dau)."""
    rng = np.random.default_rng(seed)
    t_lo = min(B["t0"] for B in train); t_hi = max(B["t0"] for B in train)
    lo_i = max(grid.bar(t_lo), 1500); hi_i = grid.bar(t_hi)
    out = {}
    cand = {}
    for B in train:
        s = grid.sidx[B["sym"]]; j = grid.bar(B["t0"]) - 1
        if j < 1500: continue
        b = grid.bucket[j + 1]
        m = (grid.bucket[lo_i:hi_i + 1] == b) & np.isfinite(grid.c[s, lo_i:hi_i + 1])
        idx = np.flatnonzero(m) + lo_i
        if len(idx) < 5: continue
        cand[id(B)] = (s, j, rng.choice(idx, n_rand))
    for H in Hs:
        z = grid.z(H); a = []
        for (s, j, ri) in cand.values():
            ze = z[s, j]; zr = z[s, ri - 1]
            a.append((zr < ze).mean() + 0.5 * (zr == ze).mean())
        out[H] = float(np.mean(a)) if a else 0.5
    return out


def profile(grid, train, bot_trades_train):
    """Ho so tren TRAIN: chieu (share ret_k cung huong lenh), z AUC, thoat, add, sizing, re-entry, long/short, chong lenh."""
    M = [basket_measures(grid, B) for B in train]
    n = len(M)
    prof = dict(n_baskets=n, n_trades=len(bot_trades_train))
    # huong
    dirs = {}
    for k in KS:
        v = []
        for B, m in zip(train, M):
            j = m["i0"] - 1
            if j < 1500: continue
            r = grid.ret(k)[m["s"], j] * m["sd"]
            if r != 0: v.append(r > 0)
        dirs[k] = round(100 * float(np.mean(v)), 1) if v else None
    prof["dir_share_pct"] = dirs
    prof["vol_auc"] = {int(k): round(v, 3) for k, v in auc_vol(grid, train).items()}
    # long share, hedge
    prof["long_pct"] = round(100 * float(np.mean([m["sd"] > 0 for m in M])), 1)
    byk = {}
    for B in train:
        byk.setdefault((B["sym"], B["side"]), []).append(B)
    # chong lenh nguoc chieu cung ma
    ov = 0
    for B in train:
        opp = byk.get((B["sym"], "short" if B["side"] == "long" else "long"), [])
        if any(o["t0"] <= B["t0"] < o["t1"] for o in opp): ov += 1
    prof["opp_side_open_pct"] = round(100 * ov / n, 1)
    # re-entry gap (cung ma, cung chieu): phut tu dong -> mo ke tiep
    gaps = []
    for arr in byk.values():
        arr = sorted(arr, key=lambda x: x["t0"])
        for a_, b_ in zip(arr[:-1], arr[1:]):
            gaps.append((b_["t0"] - a_["t1"]) / MIN)
    gaps = [g for g in gaps if g >= 0]
    prof["reentry_gap_min"] = {p: round(_q(gaps, p, 0), 1) for p in (5, 10, 25, 50, 75)} if gaps else {}
    prof["reentry_within_5min_pct"] = round(100 * float(np.mean([g <= 5 for g in gaps])), 1) if gaps else None
    # thoat
    W = [m for m in M if m["pnl"] > 0]; L = [m for m in M if m["pnl"] <= 0]
    prof["win_pct"] = round(100 * len(W) / n, 1)
    prof["gret_win_pct"] = {p: round(100 * _q([m["gret"] for m in W], p, 0), 3) for p in (25, 50, 75)} if W else {}
    prof["gret_win_over_atr"] = {p: round(_q([m["gret"] / m["atr"] for m in W], p, 0), 3) for p in (25, 50, 75)} if W else {}
    prof["win_cv_fixed"] = round(_cv([m["gret"] for m in W]), 3); prof["win_cv_atr"] = round(_cv([m["gret"] / m["atr"] for m in W]), 3)
    prof["loser_n"] = len(L)
    if L:
        prof["gret_loser_pct_med"] = round(100 * _med([m["gret"] for m in L]), 3)
        prof["mae_loser_pct_med"] = round(100 * _med([m["mae"] for m in L]), 3)
        rr = [abs(m["gret"]) / m["mae"] for m in L if m["mae"] > 1e-9 and m["gret"] < 0]
        prof["loser_ret_over_mae"] = round(_med(rr, 1.0), 3) if rr else None
        prof["loser_hold_h_med"] = round(_med([m["hold"] for m in L]) / 60, 2)
    prof["mae_win_pct_p50_p90"] = [round(100 * _q([m["mae"] for m in W], 50, 0), 3), round(100 * _q([m["mae"] for m in W], 90, 0), 3)] if W else None
    holds = [m["hold"] for m in M]
    prof["hold_min"] = {p: round(_q(holds, p), 1) for p in (25, 50, 75, 95)}
    prof["hold_win_min_med"] = round(_med([m["hold"] for m in W], 0), 1); prof["hold_loser_min_med"] = round(_med([m["hold"] for m in L], 0), 1) if L else None
    # add
    prof["add_basket_pct"] = round(100 * float(np.mean([m["n_tr"] > 1 for m in M])), 1)
    prof["fills_per_tranche_mean"] = round(float(np.mean([m["n_fills"] / m["n_tr"] for m in M])), 2)
    st = [x for m in M for x in m["steps"] if x > 0]
    st_atr = [x / m["atr"] for m in M for x in m["steps"] if x > 0]
    prof["step_pct_med"] = round(100 * _med(st, 0), 3) if st else None
    prof["step_cv"] = round(_cv(st), 3) if st else None; prof["step_atr_cv"] = round(_cv(st_atr), 3) if st else None
    prof["step_atr_med"] = round(_med(st_atr, 0), 3) if st else None
    prof["n_tr_p95"] = int(_q([m["n_tr"] for m in M], 95, 1))
    prof["add_ratio_med"] = round(_med([r for m in M for r in m["tr_ratio"]], 1.0), 3)
    prof["n0_med"] = round(_med([m["n0"] for m in M], 0), 1)
    prof["lev_med"] = _med([m["lev"] for m in M])
    prof["fee_rt_bps_implied"] = round(implied_fee_bps(bot_trades_train), 2)
    prof["max_concurrent"] = max_concurrent(train)
    prof["per_class"] = {}
    for c_ in sorted({m["cls"] for m in M}):
        Mc = [m for m in M if m["cls"] == c_]
        Wc = [m for m in Mc if m["pnl"] > 0]
        prof["per_class"][CLS_NAMES[c_]] = dict(n=len(Mc), long_pct=round(100 * float(np.mean([m["sd"] > 0 for m in Mc])), 1),
                                                tp_pct_med=round(100 * _med([m["gret"] for m in Wc], 0), 3) if Wc else None,
                                                hold_med_min=round(_med([m["hold"] for m in Mc], 0), 1), n0_med=round(_med([m["n0"] for m in Mc], 0), 1))
    return prof, M


def max_concurrent(baskets):
    ev = sorted([(b["t0"], 1) for b in baskets] + [(b["t1"], -1) for b in baskets], key=lambda x: (x[0], x[1]))
    cur = mx = 0
    for _, d in ev:
        cur += d; mx = max(mx, cur)
    return mx


# ======================================================================= tham so tu thong ke TRAIN
def _bucket_gate(first_fills_ms, mass=0.8):
    """15-phut (UTC) nho nhat chua >= mass cac first fill; tra bool[96]."""
    cnt = np.zeros(96)
    for t in first_fills_ms:
        cnt[int((t % DAY) // (15 * MIN))] += 1
    if cnt.sum() == 0:
        return np.ones(96, bool)
    order = np.argsort(-cnt); cum = np.cumsum(cnt[order]) / cnt.sum()
    k = int(np.searchsorted(cum, mass) + 1)
    g = np.zeros(96, bool); g[order[:k]] = True
    return g


def _wd_gate(first_fills_ms, min_share=0.3):
    cnt = np.zeros(7)
    for t in first_fills_ms:
        cnt[int(((t // DAY) + 3) % 7)] += 1
    if cnt.sum() == 0:
        return np.ones(7, bool)
    return (cnt / cnt.sum()) >= min_share / 7


def derive(grid, train, M, prof, cfg=None):
    """Tham so engine + mo ta luat, ca hai suy ra tu TRAIN. cfg: ghi de co kiem soat (de lap luat), mac dinh theo spec."""
    cfg = dict(cfg or {})
    S = grid.S; syms = grid.syms
    cls_of = np.array([sym_class(s) for s in syms])
    P = Params(); R = {}
    # --- nhom lop: lop it hon min_cls basket dung chung thong ke gop
    min_cls = cfg.get("min_cls", 12)
    cls_n = {c_: sum(1 for m in M if m["cls"] == c_) for c_ in range(4)}
    def group_stats(fn, c_):
        Mc = [m for m in M if m["cls"] == c_]
        if len(Mc) >= min_cls: return fn(Mc)
        return fn(M)
    # --- session / weekday gate theo lop
    sess = {}; wday = {}
    for c_ in range(4):
        ff = [m["t0"] for m in M if m["cls"] == c_] if cls_n[c_] >= min_cls else [m["t0"] for m in M]
        sess[c_] = _bucket_gate(ff, cfg.get("sess_mass", 0.8)); wday[c_] = _wd_gate(ff)
    P["sess"] = sess; P["wday"] = wday
    # --- huong
    dsh = prof["dir_share_pct"]; n = prof["n_baskets"]
    best_k = max((k for k in dsh if dsh[k] is not None), key=lambda k: abs(dsh[k] - 50))
    bias = abs(dsh[best_k] - 50)
    thr = max(cfg.get("dir_min_bias", 10.0), 2.5 * 100 * math.sqrt(0.25 / max(n, 1)))
    if "dir" in cfg:
        mode, Hdir = cfg["dir"]
    elif bias >= thr:
        mode = "contrarian" if dsh[best_k] < 50 else "momentum"; Hdir = best_k
    else:
        mode, Hdir = "none", 1
    R["direction"] = dict(mode=mode, H=Hdir, share_pct=dsh[best_k], bias_pp=round(bias, 1), thr_pp=round(thr, 1))
    # --- hoat dong (vol) H, theo AUC cao nhat tren TRAIN
    auc = prof["vol_auc"]; Hvol = cfg.get("Hvol") or max(auc, key=lambda k: auc[k])
    R["activity"] = dict(H=int(Hvol), auc=auc[Hvol] if Hvol in auc else None)
    # --- sizing: N0 theo ma > lop > toan bo ; lev
    n0_all = float(np.median([m["n0"] for m in M])); lev_all = float(np.median([m["lev"] for m in M]))
    N0 = np.zeros(S); lev = np.zeros(S)
    for k, s in enumerate(syms):
        Ms = [m for m in M if m["sym"] == s]; Mc = [m for m in M if m["cls"] == cls_of[k]]
        src = Ms if len(Ms) >= 2 else (Mc if len(Mc) >= 3 else M)
        N0[k] = np.median([m["n0"] for m in src]); lev[k] = np.median([m["lev"] for m in (Ms if len(Ms) >= 1 else (Mc if Mc else M))])
    P["N0"] = N0; P["lev"] = lev
    # --- thoat
    W = [m for m in M if m["pnl"] > 0]; L = [m for m in M if m["pnl"] <= 0]
    use_atr_g = 1 if (cfg.get("tp_mode") == "atr" or (cfg.get("tp_mode") is None and prof["win_cv_atr"] < 0.9 * prof["win_cv_fixed"])) else 0
    tp = np.zeros(S); tpc = np.zeros(S)
    tp_cls = {}; tpc_cls = {}
    for c_ in range(4):
        Wc = [m for m in W if m["cls"] == c_]
        src = Wc if len(Wc) >= 6 else W
        tp_cls[c_] = float(np.median([m["gret"] for m in src])) if src else 0.005
        tpc_cls[c_] = float(np.median([m["gret"] / m["atr"] for m in src])) if src else 0.4
    # tp theo ma neu du mau (>=8 thang)
    for k, s in enumerate(syms):
        Ws = [m for m in W if m["sym"] == s]
        tp[k] = float(np.median([m["gret"] for m in Ws])) if (len(Ws) >= cfg.get("min_sym_tp", 10**9)) else tp_cls[int(cls_of[k])]
        tpc[k] = tpc_cls[int(cls_of[k])]
    tp_scale = cfg.get("tp_scale", 1.0); P["tp"] = tp * tp_scale; P["tp_c"] = tpc * tp_scale; P["use_atr"] = np.full(S, use_atr_g, np.int8)
    R["tp"] = dict(mode="atr" if use_atr_g else "fixed", per_class_pct={CLS_NAMES[c_]: round(100 * tp_cls[c_], 3) for c_ in range(4)},
                   per_class_atr={CLS_NAMES[c_]: round(tpc_cls[c_], 3) for c_ in range(4)}, cv_fixed=prof["win_cv_fixed"], cv_atr=prof["win_cv_atr"], scale=tp_scale)
    ratio_loser = prof.get("loser_ret_over_mae")
    lmode = cfg.get("loser_mode")
    if lmode is None:
        if not L or ratio_loser is None: lmode = "none"
        elif ratio_loser >= 0.8: lmode = "stop"
        elif ratio_loser <= 0.6: lmode = "hold_be"
        else: lmode = "both"
    stop = np.zeros(S); be = np.zeros(S)
    stop_cls = {}; be_cls = {}
    for c_ in range(4):
        Lc = [m for m in L if m["cls"] == c_]
        src = Lc if len(Lc) >= 6 else L
        stop_cls[c_] = float(np.median([abs(m["gret"]) for m in src])) if src else 0.0
        be_cls[c_] = float(np.median([m["mae"] for m in src])) if src else 0.0
    for k in range(S):
        c_ = int(cls_of[k])
        if lmode in ("stop", "both"): stop[k] = stop_cls[c_] * cfg.get("stop_scale", 1.0)
        if lmode in ("hold_be", "both"): be[k] = be_cls[c_]
    P["stop"] = stop; P["be_thr"] = be
    fee_rt = cfg.get("fee_rt_bps", prof["fee_rt_bps_implied"])
    P["fee_bps_side"] = fee_rt / 2
    P["be_tp"] = fee_rt / 1e4 + 1e-4
    R["loser"] = dict(mode=lmode, ret_over_mae=ratio_loser, stop_pct_per_class={CLS_NAMES[c_]: round(100 * stop_cls[c_], 3) for c_ in range(4)} if lmode in ("stop", "both") else None,
                      be_after_dd_pct_per_class={CLS_NAMES[c_]: round(100 * be_cls[c_], 3) for c_ in range(4)} if lmode in ("hold_be", "both") else None, fee_rt_bps=fee_rt)
    hold_q = cfg.get("maxhold_q", 95)
    P["maxhold"] = int(_q([m["hold"] for m in M], hold_q)) if lmode != "stop" or cfg.get("maxhold") else int(cfg.get("maxhold", 0))
    if "maxhold" in cfg: P["maxhold"] = int(cfg["maxhold"])
    # --- add
    has_add = prof["add_basket_pct"] >= cfg.get("add_min_pct", 8.0)
    step = np.zeros(S)
    if has_add:
        use_atr_step = (prof["step_atr_cv"] is not None and prof["step_cv"] is not None and prof["step_atr_cv"] < 0.8 * prof["step_cv"])
        for k in range(S):
            if use_atr_step:
                step[k] = prof["step_atr_med"] * float(np.median(grid.atr()[k, int(0.2 * grid.T):int(0.9 * grid.T)]))
            else:
                step[k] = (prof["step_pct_med"] or 1.0) / 100.0
        R["add"] = dict(on=True, step_mode="atr" if use_atr_step else "pct", step_pct=prof["step_pct_med"] or 1.0, step_atr=prof["step_atr_med"], ratio=prof["add_ratio_med"],
                        max_layers=max(2, prof["n_tr_p95"]))
    else:
        R["add"] = dict(on=False)
    step *= cfg.get("step_scale", 1.0)
    P["step"] = step
    maxL = max(2, prof["n_tr_p95"]) if has_add else 1
    P["maxL"] = np.full(S, maxL, np.int32)
    ratios = [1.0]
    for kk in range(1, maxL):
        v = [m["tr_ratio"][kk - 1] for m in M if len(m["tr_ratio"]) >= kk]
        ratios.append(float(np.median(v)) if len(v) >= 5 else ratios[-1] if kk > 1 else prof["add_ratio_med"])
    if "ratio" in cfg: ratios = [1.0] + [cfg["ratio"]] * (maxL - 1)
    P["ratio"] = np.array(ratios if len(ratios) > 1 else [1.0, 1.0])
    # --- vao / dong thoi
    gaps = prof["reentry_gap_min"]
    cq = cfg.get("cool_q", 50)
    cool = gaps.get(cq, gaps.get(50, 0)) if gaps else 0
    P["cool"] = int(max(1, round(cool))); P["maxconc"] = int(prof["max_concurrent"] * cfg.get("conc_scale", 1.0) + 0.5)
    P["hedge"] = 1 if prof["opp_side_open_pct"] >= 10 else 0
    P["tp_same_bar"] = 0
    P["cls_of"] = cls_of
    R["entry_cfg"] = dict(cooldown_min=P["cool"], cool_q=cq, max_concurrent=P["maxconc"], hedge=bool(P["hedge"]), hedge_train_pct=prof["opp_side_open_pct"])
    R["sizing"] = dict(n0_class_med={CLS_NAMES[c_]: round(float(np.median([m["n0"] for m in M if m["cls"] == c_])), 0) for c_ in range(4) if cls_n[c_] > 0},
                       lev_med=prof["lev_med"], max_layers=int(maxL), add_ratio=[round(x, 3) for x in P["ratio"]])
    R["session"] = {CLS_NAMES[c_]: dict(buckets_utc=_fmt_buckets(sess[c_]), weekdays=[("T2", "T3", "T4", "T5", "T6", "T7", "CN")[i] for i in range(7) if wday[c_][i]]) for c_ in range(4) if cls_n[c_] > 0}
    R["maxhold_min"] = P["maxhold"]
    # --- cat lo chi hieu luc tu tang thu K = trung vi so tang cua basket thua o TRAIN (de khong cat lo truoc khi them tang, vi gia TB doi theo tang)
    if cfg.get("stop_layers") == "median_loser" and L:
        P["stop_layers"] = int(max(1, min(maxL, round(float(np.median([m["n_tr"] for m in L]))))))
    elif cfg.get("stop_layers") == "last":
        P["stop_layers"] = int(maxL)
    else:
        P["stop_layers"] = 1
    R["stop_layers"] = P["stop_layers"]
    # --- trailing: thoat khi gia lui gb tu dinh (gb = trung vi (MFE - loi nhuan chot) cua basket thang TRAIN), kich hoat khi loi nhuan dinh >= TP
    if cfg.get("trail") and W:
        gb = max(3e-4, float(np.median([m["mfe"] - m["gret"] for m in W])))
        P["trail_gb"] = np.full(S, gb); P["trail_act_mult"] = float(cfg.get("trail_act_mult", 1.0))
        R["trail"] = dict(on=True, giveback_pct=round(100 * gb, 3), act_mult=P["trail_act_mult"])
    else:
        P["trail_gb"] = np.zeros(S); P["trail_act_mult"] = 1.0; R["trail"] = dict(on=False)
    # --- khoa chieu: ma (hoac ca bot) co >= 80% basket TRAIN cung 1 chieu -> chi vao chieu do
    allow = np.ones((S, 2), np.int8)
    if cfg.get("side_lock"):
        bot_ls = float(np.mean([m["sd"] > 0 for m in M]))
        for k, sname in enumerate(syms):
            Ms = [m for m in M if m["sym"] == sname]
            ls_ = float(np.mean([m["sd"] > 0 for m in Ms])) if len(Ms) >= 4 else (bot_ls if len(M) >= 8 else 0.5)
            if ls_ >= 0.75: allow[k, 1] = 0
            elif ls_ <= 0.25: allow[k, 0] = 0
        R["side_lock"] = dict(on=True, long_only=[syms[k] for k in range(S) if allow[k, 1] == 0], short_only=[syms[k] for k in range(S) if allow[k, 0] == 0])
    else:
        R["side_lock"] = dict(on=False)
    P["allow"] = allow
    P["mode"] = mode; P["Hdir"] = Hdir; P["Hvol"] = int(Hvol)
    P["long_share"] = {s: None for s in syms}
    ls_all = float(np.mean([m["sd"] > 0 for m in M]))
    P["p_long"] = np.zeros(S)
    for k, s in enumerate(syms):
        Ms = [m for m in M if m["sym"] == s]
        # co shrink ve ti le chung: (nL + a*ls)/(n + a)
        a = 5.0
        P["p_long"][k] = (sum(m["sd"] > 0 for m in Ms) + a * ls_all) / (len(Ms) + a)
    P["long_pct_all"] = ls_all
    # --- moi tranche (lenh vao) that duoc chia thanh m fill con cach nhau vai giay (xem fills_per_tranche) -> mau m va do lech gia TRAIN
    ms = []; offs = []
    for B in train:
        sd = 1 if B["side"] == "long" else -1
        for tr in B["tranches"]:
            ms.append(tr["n"])
        # do lech gia cua cac fill con trong cung tranche so voi fill truoc (bps, duong = bat loi cho bot)
        fl = B["fills"]; cur = None
        trs = B["tranches"]; ti = 0; cnt = 0
        for a_, b_ in zip(fl[:-1], fl[1:]):
            if b_["t"] - a_["t"] <= 30_000:
                offs.append((a_["px"] - b_["px"]) / a_["px"] * 1e4 * sd)
    P["split_sample"] = np.array(ms if ms else [1]); P["split_off_bps"] = float(np.median(offs)) if offs else 0.0
    P["split_off_sample"] = np.clip(np.array(offs), np.percentile(offs, 2), np.percentile(offs, 98)) if len(offs) > 10 else np.zeros(1)
    allr = [r for m in M for r in m["tr_ratio"]]
    P["rsamp"] = np.clip(np.array(allr), 0, np.percentile(allr, 99)) if (cfg.get("ratio_sample") and allr) else np.zeros(0)
    R["add_ratio_sampling"] = dict(on=bool(len(P["rsamp"])), n=len(allr), q50=round(_q(allr, 50, 0), 3) if allr else None, q90=round(_q(allr, 90, 0), 3) if allr else None, q99=round(_q(allr, 99, 0), 3) if allr else None)
    P["do_split"] = bool(cfg.get("split", False))
    R["split"] = dict(on=P["do_split"], mean_fills_per_order=round(float(np.mean(P["split_sample"])), 3), share_multi_pct=round(100 * float(np.mean(P["split_sample"] > 1)), 1), off_bps_med=round(P["split_off_bps"], 2), off_bps_q10_q90=[round(float(np.percentile(P["split_off_sample"], 10)), 2), round(float(np.percentile(P["split_off_sample"], 90)), 2)])
    return P, R


def _fmt_buckets(g):
    runs = []; i = 0
    while i < 96:
        if g[i]:
            j = i
            while j + 1 < 96 and g[j + 1]: j += 1
            runs.append("%02d:%02d-%02d:%02d" % (i * 15 // 60, i * 15 % 60, ((j + 1) * 15) // 60 % 24, ((j + 1) * 15) % 60)); i = j + 1
        else:
            i += 1
    return runs if len(runs) <= 8 else runs[:8] + ["..."]


# ======================================================================= tin hieu vao lenh
def gate_matrix(grid, P):
    """gate[s,t] = khung 15' UTC + thu trong tuan thuoc cong cua lop cua ma (danh gia tai thoi diem fill = open nen t)."""
    G = np.zeros((grid.S, grid.T), bool)
    for c_ in range(4):
        gm = P["sess"][c_][grid.bucket] & P["wday"][c_][grid.wday]
        for k in np.flatnonzero(P["cls_of"] == c_):
            G[k] = gm
    return G


def build_signals(grid, P, q_cls, mode=None, seed=0, window=None, restrict=None):
    """sig[s,d,t] = 1 neu quyet dinh tai nen t-1 da dong -> vao tai open nen t. d=0 long, 1 short.
    q_cls: dict lop -> nguong z. mode: contrarian|momentum|both|rand|opp1."""
    S, T = grid.S, grid.T
    mode = mode or P["mode"]
    rng = np.random.default_rng(seed)
    G = gate_matrix(grid, P)
    z = grid.z(P["Hvol"])
    if "vec" in q_cls:
        q = np.asarray(q_cls["vec"], float)[:, None]
    else:
        q = np.array([q_cls.get(int(c_), q_cls.get("all", 3.0)) for c_ in P["cls_of"]])[:, None]
    cand = np.zeros((S, T), bool)
    cand[:, 1:] = (z[:, :-1] >= q) & G[:, 1:]
    if window is not None:
        lo, hi = window; cand[:, :lo] = False; cand[:, hi:] = False
    if restrict is not None:
        cand &= restrict
    sig = np.zeros((S, 2, T), np.int8)
    if mode in ("contrarian", "momentum"):
        r = np.zeros((S, T)); r[:, 1:] = grid.ret(P["Hdir"])[:, :-1]
        up = r > 0; dn = r < 0
        longm = dn if mode == "contrarian" else up; shortm = up if mode == "contrarian" else dn
        sig[:, 0] = cand & longm; sig[:, 1] = cand & shortm
    elif mode == "opp1":
        r = np.zeros((S, T)); r[:, 1:] = grid.ret(1)[:, :-1]
        sig[:, 0] = cand & (r < 0); sig[:, 1] = cand & (r > 0)
    elif mode == "both":
        sig[:, 0] = cand; sig[:, 1] = cand
    elif mode == "rand":
        u = rng.random((S, T))
        sig[:, 0] = cand & (u < P["p_long"][:, None]); sig[:, 1] = cand & (u >= P["p_long"][:, None])
    else:
        raise ValueError(mode)
    return sig


def random_signals(grid, P, p_sym, seed, window):
    """Baseline vao ngau nhien: cung cong phien (khung 15' + thu), thinning deu theo p_sym[s] moi nen, chieu ngau nhien theo ti le long cua ma."""
    S, T = grid.S, grid.T
    rng = np.random.default_rng(10_000 + seed)
    G = gate_matrix(grid, P)
    cand = G & (rng.random((S, T)) < p_sym[:, None]) & np.isfinite(grid.o)
    cand[:, :window[0]] = False; cand[:, window[1]:] = False
    u = rng.random((S, T))
    sig = np.zeros((S, 2, T), np.int8)
    sig[:, 0] = cand & (u < P["p_long"][:, None]); sig[:, 1] = cand & (u >= P["p_long"][:, None])
    return sig


# ======================================================================= chay + so sanh
def sim_baskets(grid, res):
    nb_, nf, ovf, nopen, bk_s, bk_d, bk_t0, bk_t1, bk_px1, bk_why, *_ = res
    out = []
    for b in range(nb_):
        out.append((grid.syms[int(bk_s[b])], "long" if bk_d[b] == 0 else "short", grid.T0 + int(bk_t0[b]) * MIN, (grid.T0 + int(bk_t1[b]) * MIN) if bk_t1[b] >= 0 else None))
    return out


def counts_by_class(grid, res, P, lo_bar, hi_bar):
    nb_, nf, ovf, nopen, bk_s, bk_d, bk_t0 = res[:7]
    cnt = np.zeros(4)
    for b in range(nb_):
        if lo_bar <= bk_t0[b] < hi_bar:
            cnt[int(P["cls_of"][int(bk_s[b])])] += 1
    return cnt


def calibrate_rate(grid, P, train, split_t, mode=None, seed=0, iters=11, by_symbol=False, min_n=8, log=print):
    """q (nguong z) theo lop sao cho so first-fill/ngay trong TRAIN cua sim = cua bot that (bisect log-q; chi dung TAN SUAT, khong dung diem khop)."""
    t_lo = min(B["t0"] for B in train); lo = grid.bar(t_lo); hi = grid.bar(split_t)
    days = (split_t - t_lo) / DAY
    target = np.zeros(4)
    for B in train:
        target[sym_class(B["sym"])] += 1
    present = [c_ for c_ in range(4) if target[c_] > 0 and (P["cls_of"] == c_).any()]
    lo_q = {c_: math.log(0.3) for c_ in present}; hi_q = {c_: math.log(60.0) for c_ in present}
    q = {c_: math.exp(0.5 * (lo_q[c_] + hi_q[c_])) for c_ in present}
    hist = []
    for it in range(iters):
        sig = build_signals(grid, P, q, mode=mode, seed=seed, window=(lo, hi))
        res = run_engine(grid, sig, P, lo - 1, hi)
        cnt = counts_by_class(grid, res, P, lo, hi)
        hist.append(dict(it=it, q={CLS_NAMES[c_]: round(q[c_], 3) for c_ in present}, sim=[int(cnt[c_]) for c_ in present], real=[int(target[c_]) for c_ in present]))
        for c_ in present:
            if cnt[c_] > target[c_]: lo_q[c_] = math.log(q[c_])
            else: hi_q[c_] = math.log(q[c_])
            q[c_] = math.exp(0.5 * (lo_q[c_] + hi_q[c_]))
    others = [q[c_] for c_ in present]
    q["all"] = float(np.exp(np.mean(np.log(others)))) if others else 3.0
    extra = {}
    if by_symbol:
        # tinh chinh them theo ma (chi ma co >= min_n basket TRAIN): he so nhan nguong de so basket/ngay cua ma khop TRAIN
        cnt_s = np.zeros(grid.S)
        for B in train: cnt_s[grid.sidx[B["sym"]]] += 1
        tgt_s = cnt_s.copy()
        for c_ in present:                                    # ma hiem (< min_n basket TRAIN) cua lop: chia deu phan basket cua nhom hiem
            idx = np.flatnonzero(P["cls_of"] == c_); rare = idx[cnt_s[idx] < min_n]
            if len(rare): tgt_s[rare] = cnt_s[rare].sum() / len(rare)
        base = np.array([q.get(int(c_), q["all"]) for c_ in P["cls_of"]])
        sel = np.flatnonzero(np.isin(P["cls_of"], present))
        lo_f = np.full(grid.S, math.log(0.05)); hi_f = np.full(grid.S, math.log(20.0)); f = np.exp(0.5 * (lo_f + hi_f))
        for it in range(iters + 3):
            qv = base * f
            sig = build_signals(grid, P, {"vec": qv}, mode=mode, seed=seed, window=(lo, hi))
            res = run_engine(grid, sig, P, lo - 1, hi)
            nb_, nf, ovf, nopen, bk_s, bk_d, bk_t0 = res[:7]
            c_s = np.bincount(bk_s[:nb_][(bk_t0[:nb_] >= lo) & (bk_t0[:nb_] < hi)], minlength=grid.S)
            for k in sel:
                if c_s[k] > tgt_s[k]: lo_f[k] = math.log(f[k])
                else: hi_f[k] = math.log(f[k])
                f[k] = math.exp(0.5 * (lo_f[k] + hi_f[k]))
        qv = base.copy(); qv[sel] = base[sel] * f[sel]
        q = {"vec": qv, "all": q["all"]}
        extra = dict(per_symbol=True, n_symbols_calibrated=int(len(sel)), factor_range=[round(float(f[sel].min()), 3), round(float(f[sel].max()), 3)] if len(sel) else None)
    return q, dict(extra,target_per_day={CLS_NAMES[c_]: round(target[c_] / days, 3) for c_ in present}, hist=hist, q_final={str(k): round(v, 3) for k, v in q.items() if k != "vec"})


def real_trades_window(bot, baskets, lo, hi):
    bk = set()
    for B in baskets:
        if lo <= B["t0"] <= hi:
            bk.update(B["bk_ids"])
    return [dict(t) for t in bot["trades"] if t["bk"] in bk]


def overlap(real_b, sim_b, tols=(15, 60, 240)):
    """real_b, sim_b: list (sym, side, t0). Tra recall/precision cung chieu va bat ke chieu."""
    out = {}
    def idx(L, any_side):
        d = {}
        for sym, side, t0 in L:
            d.setdefault(sym if any_side else (sym, side), []).append(t0)
        return {k: np.array(sorted(v)) for k, v in d.items()}
    for any_side, nm in ((False, "same"), (True, "any")):
        R = idx(real_b, any_side); Sd = idx(sim_b, any_side)
        for tol in tols:
            ms = tol * MIN
            def hit(A_list, B_idx):
                h = 0
                for sym, side, t0 in A_list:
                    arr = B_idx.get(sym if any_side else (sym, side))
                    if arr is not None and len(arr):
                        j = np.searchsorted(arr, t0)
                        dmin = min(abs(arr[j] - t0) if j < len(arr) else 1e18, abs(arr[j - 1] - t0) if j > 0 else 1e18)
                        h += dmin <= ms
                return h
            out[f"recall_{nm}_{tol}"] = round(100 * hit(real_b, Sd) / max(1, len(real_b)), 2)
            out[f"precision_{nm}_{tol}"] = round(100 * hit(sim_b, R) / max(1, len(sim_b)), 2)
    out["n_real"] = len(real_b); out["n_sim"] = len(sim_b)
    return out


def level_s_eval(real_T, sim_T, real_b, sim_b, lo, hi):
    """Bang Level S: stats thuc vs sim (CUNG ham ST.stats), diem khop, tuong quan PnL ngay, ma tran ma, overlap episode."""
    real_st = ST.stats([dict(t) for t in real_T]) if real_T else dict(n=0)
    if not sim_T or not real_T:
        return dict(real=real_st, sim=dict(n=len(sim_T)), compare=None)
    sim_c = [{k: v for k, v in t.items() if k not in ("why", "bt0")} for t in sim_T]
    sim_st = ST.stats([dict(t) for t in sim_c])
    cmp_ = ST.compare(real_st, sim_st)
    real_T2 = [dict(t) for t in real_T]; ST.stats(real_T2)
    sim_T2 = [dict(t) for t in sim_c]; ST.stats(sim_T2)
    dly = ST.daily_corr(real_T2, sim_T2, lo, hi)
    return dict(real=real_st, sim=sim_st, compare=cmp_, mix_overlap=ST.mix_overlap(real_st, sim_st), daily=dly,
                overlap=overlap(real_b, sim_b))


# ======================================================================= entry theo HAZARD (xac suat theo do hoat dong), thay cho nguong cung
HZ_Q = (0.5, 0.75, 0.9, 0.97, 0.995)


def fit_hazard(grid, train, P, split_t):
    """Xac suat vao lenh moi nen = ti le entry/so nen trong tung bin cua z_H (z tai nen quyet dinh truoc fill), gop moi ma (z da chuan hoa theo ma)."""
    z = grid.z(P["Hvol"]); G = gate_matrix(grid, P)
    t_lo = min(B["t0"] for B in train); lo = grid.bar(t_lo); hi = grid.bar(split_t)
    ref = []
    for k in range(grid.S):
        m = G[k, lo + 1:hi] & np.isfinite(grid.o[k, lo + 1:hi])
        ref.append(z[k, lo:hi - 1][m])
    allref = np.concatenate(ref); edges = np.quantile(allref, HZ_Q)
    nref = np.bincount(np.digitize(allref, edges), minlength=len(edges) + 1).astype(float)
    ent = np.zeros(len(edges) + 1)
    for B in train:
        k = grid.sidx[B["sym"]]; j = grid.bar(B["t0"]) - 1
        if j < 1500: continue
        ent[np.digitize(z[k, j], edges)] += 1
    rate = (ent + 0.5) / (nref + 1.0)
    return dict(edges=edges, rate=rate, ent=ent.tolist(), nref=nref.tolist())


def build_signals_hz(grid, P, H, fvec, mode=None, seed=0, window=None):
    S, T = grid.S, grid.T
    mode = mode or P["mode"]
    rng = np.random.default_rng(seed)
    G = gate_matrix(grid, P)
    z = grid.z(P["Hvol"])
    zb = np.digitize(z[:, :-1], H["edges"])
    h = H["rate"][zb] * fvec[:, None]
    cand = np.zeros((S, T), bool)
    cand[:, 1:] = (rng.random((S, T - 1)) < h) & G[:, 1:] & np.isfinite(grid.o[:, 1:])
    if window is not None:
        lo, hi = window; cand[:, :lo] = False; cand[:, hi:] = False
    sig = np.zeros((S, 2, T), np.int8)
    if mode in ("contrarian", "momentum"):
        r = np.zeros((S, T)); r[:, 1:] = grid.ret(P["Hdir"])[:, :-1]
        up = r > 0; dn = r < 0
        sig[:, 0] = cand & (dn if mode == "contrarian" else up); sig[:, 1] = cand & (up if mode == "contrarian" else dn)
    elif mode == "opp1":
        r = np.zeros((S, T)); r[:, 1:] = grid.ret(1)[:, :-1]
        sig[:, 0] = cand & (r < 0); sig[:, 1] = cand & (r > 0)
    elif mode == "both":
        sig[:, 0] = cand; sig[:, 1] = cand
    elif mode == "rand":
        u = rng.random((S, T))
        sig[:, 0] = cand & (u < P["p_long"][:, None]); sig[:, 1] = cand & (u >= P["p_long"][:, None])
    return sig


def calibrate_hazard(grid, P, train, split_t, H, mode=None, min_n=8, iters=3, seeds=3):
    """He so f[s] sao cho so basket/ngay cua tung ma khop TRAIN (ma hiem -> chia deu phan cua nhom hiem trong lop). Chi dung TAN SUAT."""
    t_lo = min(B["t0"] for B in train); lo = grid.bar(t_lo); hi = grid.bar(split_t)
    cnt_s = np.zeros(grid.S)
    for B in train: cnt_s[grid.sidx[B["sym"]]] += 1
    tgt = cnt_s.copy()
    for c_ in range(4):
        idx = np.flatnonzero(P["cls_of"] == c_)
        if not len(idx) or cnt_s[idx].sum() == 0: continue
        rare = idx[cnt_s[idx] < min_n]
        if len(rare): tgt[rare] = cnt_s[rare].sum() / len(rare)
    # lop khong co trong TRAIN (ma moi): dung ti le trung binh moi ma cua cac lop co
    unseen = [k for k in range(grid.S) if tgt[k] == 0 and cnt_s[P["cls_of"] == P["cls_of"][k]].sum() == 0]
    mean_tgt = float(np.mean([tgt[k] for k in range(grid.S) if tgt[k] > 0])) if (tgt > 0).any() else 1.0
    for k in unseen: tgt[k] = mean_tgt * 0.5
    z = grid.z(P["Hvol"]); G = gate_matrix(grid, P)
    zb = np.digitize(z[:, :-1], H["edges"])
    hbase = H["rate"][zb]
    E = np.zeros(grid.S)
    for k in range(grid.S):
        m = G[k, lo + 1:hi] & np.isfinite(grid.o[k, lo + 1:hi])
        E[k] = hbase[k, lo:hi - 1][m].sum()
    f = np.where(E > 0, tgt / np.maximum(E, 1e-9), 0.0)
    hist = []
    for it in range(iters):
        got = np.zeros(grid.S)
        for sd in range(seeds):
            sig = build_signals_hz(grid, P, H, f, mode=mode, seed=sd, window=(lo, hi))
            res = run_engine(grid, sig, P, lo - 1, hi)
            nb_, nf, ovf, nopen, bk_s, bk_d, bk_t0 = res[:7]
            got += np.bincount(bk_s[:nb_][(bk_t0[:nb_] >= lo) & (bk_t0[:nb_] < hi)], minlength=grid.S) / seeds
        hist.append(dict(it=it, total_sim=round(float(got.sum()), 1), total_tgt=round(float(tgt.sum()), 1)))
        # hieu chinh: theo lop (on dinh) neu mau it, theo ma neu >= min_n
        for c_ in range(4):
            idx = np.flatnonzero(P["cls_of"] == c_)
            if not len(idx): continue
            big = idx[(cnt_s[idx] >= min_n)]; rest = np.setdiff1d(idx, big)
            for k in big:
                if got[k] > 0: f[k] *= (tgt[k] / got[k]) ** 0.8
            if len(rest) and got[rest].sum() > 0 and tgt[rest].sum() > 0:
                f[rest] *= (tgt[rest].sum() / got[rest].sum()) ** 0.8
    return f, dict(hist=hist, expected_per_day_total=round(float(tgt.sum() / ((split_t - t_lo) / DAY)), 3), n_unseen_symbols=len(unseen))
