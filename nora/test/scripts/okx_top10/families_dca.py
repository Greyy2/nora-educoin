"""Họ mô hình MỚI cho bot DCA (Sugary-PoH-GasCap, Scary-Merge-Llama, Auroraxwt, 01pp): simulator mở rộng + tín hiệu thoát/vào theo chỉ báo.
Không sửa sim.py/load.py/match.py/features.py/run_bot.py (chỉ import).

THOÁT (exit families) - chỉ báo tính trên nến ĐÓNG tf in {1,5,15,60} phút; sự kiện ở nến k -> khớp tại OPEN nến 1m kế tiếp (không look-ahead):
  rsi  : long thoát khi RSI(14,tf) vượt LÊN mức L (cạnh) / >= L (trạng thái); short đối xứng (xuống 100-L)
  ema  : long thoát khi close > EMA_n(tf) (cạnh = cắt lên); short khi close < EMA_n
  sma  : như ema nhưng SMA_n (n=20 -> đường giữa Bollinger)
  bbext: long thoát khi close > SMA20+2σ ; short khi < SMA20-2σ
  vwap : long thoát khi close > VWAP phiên UTC (reset 00:00); short khi <
  nbar : long thoát khi close phá đỉnh N nến trước (cực trị ĐỐI DIỆN của hướng vào); short phá đáy N nến
  macd : long thoát khi MACD(12,26,9) cắt lên đường tín hiệu; short cắt xuống
  time : giờ cố định (phút trong ngày UTC): funding 00/08/16, mở/đóng cửa Mỹ 13:30/20:00; cả hai chiều
  ngoài ra: x_after_add (đóng sau N phút kể từ add cuối), xsince (chỉ cho tín hiệu thoát sau >=N phút kể từ add cuối), xhold, cổng lãi xprof (% từ avg, hoặc bội ATR).
VÀO (Level B): hl_fade/hl_break (chạm đỉnh/đáy N giờ trước), round (mức tròn), vwap_band / ema_band (lệch khỏi VWAP/EMA theo σ),
  sigma (sau biến động N-sigma 1h/4h), session (cổng giờ UTC / mở cửa Mỹ), ghép cổng giờ.
Replay (replay=1): giữ NGUYÊN các fill thật (thời điểm/giá/notional) để tách riêng luật THOÁT khỏi luật ADD.
"""
import collections
import numpy as np
import pandas as pd
from numba import njit

import load
import sim
from load import MIN, candle_arrays

H = 3_600_000
XORDER = ["xk", "xprof", "xprof_scale", "xscope", "xaa", "xhold", "xsince", "replay", "ak", "amin", "acool"]
XDEFAULT = dict(xk=0, xprof=0.0, xprof_scale=0, xscope=0, xaa=0, xhold=0, xsince=0, replay=0, ak=0, amin=0.0, acool=1)
MAXL = sim.MAXL


def pvec2(params):
    base = sim.pvec(params)
    x = dict(XDEFAULT); x.update({k: params[k] for k in XORDER if k in params})
    return np.concatenate([base, np.array([float(x[k]) for k in XORDER])])


# ---------------------------------------------------------------- simulator mở rộng
@njit(cache=True)
def _run2(o, h, l, c, scale, xsig, asig, i0, i_end, s, p0, N0, P, f_bar, f_px, f_not, c_bar, c_px, c_qty, c_lay, r_bar, r_px, r_not, r_n):
    add_ref = int(P[0]); step = P[1]; grow = P[2]; maxL = min(int(P[3]), 40); smult = P[4]; sref = int(P[5])
    tp = P[6] / 100.0; tp_ref = int(P[7]); tp_mode = int(P[8]); sl = P[9] / 100.0; sl_ref = int(P[10])
    if int(P[16]) == 1: tp = tp * scale[i0]
    if int(P[17]) == 1: sl = sl * scale[i0]
    add_delay = max(1, int(P[15])); last_i = i0
    tr_act = P[11] / 100.0; tr_dist = P[12] / 100.0; maxhold = int(P[13]); use_scale = int(P[14])
    xk = int(P[18]); xprof = P[19] / 100.0; xps = int(P[20]); xscope = int(P[21]); xaa = int(P[22]); xhold = int(P[23]); xsince = int(P[24]); replay = int(P[25])
    ak = int(P[26]); amin = P[27] / 100.0; acool = max(1, int(P[28]))
    abit = 2 if s == 1 else 1
    sbit = 1 if s == 1 else 2
    if xps == 1: xprof = xprof * scale[i0]
    nf = 1; nc = 0
    f_bar[0] = i0; f_px[0] = p0; f_not[0] = N0
    qty = np.zeros(40); alive = np.zeros(40, dtype=np.bool_)
    qty[0] = N0 / p0; alive[0] = True
    sum_q = qty[0]; sum_pq = qty[0] * p0
    last_px = p0; cum_step = 0.0
    sc_ref = scale[i0] if use_scale == 1 else 1.0
    ext = p0; trail_on = False
    nr = 1   # chỉ số fill replay kế tiếp (fill 0 = fill đầu)
    for i in range(i0 + 1, i_end + 1):
        o_ = o[i]; h_ = h[i]; l_ = l[i]
        adv = l_ if s == 1 else h_
        fav = h_ if s == 1 else l_
        # ---- thoát theo tín hiệu chỉ báo (quyết định ở đóng nến i-1, khớp open nến i)
        do_x = False
        if xk == 1 and (xsig[i - 1] & sbit) != 0 and i - i0 >= xhold and i - last_i >= xsince:
            do_x = True
        if xaa > 0 and i - last_i >= xaa:
            do_x = True
        if do_x:
            if xscope == 0:
                avg0 = sum_pq / sum_q
                if s * (o_ / avg0 - 1.0) >= xprof:
                    for j in range(nf):
                        if alive[j]:
                            c_bar[nc] = i; c_px[nc] = o_; c_qty[nc] = qty[j]; c_lay[nc] = j; nc += 1; alive[j] = False
                    return nf, nc, 1
            else:
                nal = 0
                for j in range(nf):
                    if alive[j]:
                        if s * (o_ / f_px[j] - 1.0) >= xprof:
                            c_bar[nc] = i; c_px[nc] = o_; c_qty[nc] = qty[j]; c_lay[nc] = j; nc += 1; alive[j] = False
                            sum_q -= qty[j]; sum_pq -= qty[j] * f_px[j]
                        else:
                            nal += 1
                if nal == 0:
                    return nf, nc, 1
        if maxhold > 0 and i - i0 >= maxhold:
            for j in range(nf):
                if alive[j]:
                    c_bar[nc] = i; c_px[nc] = o_; c_qty[nc] = qty[j]; c_lay[nc] = j; nc += 1; alive[j] = False
            return nf, nc, 1
        if trail_on:
            stp = ext * (1.0 - s * tr_dist)
            if s * (adv - stp) <= 0:
                px = stp if s * (o_ - stp) > 0 else o_
                for j in range(nf):
                    if alive[j]:
                        c_bar[nc] = i; c_px[nc] = px; c_qty[nc] = qty[j]; c_lay[nc] = j; nc += 1; alive[j] = False
                return nf, nc, 1
        # ---- add theo tín hiệu chỉ báo (ak=1): quyết định ở đóng nến i-1, vào tại open nến i, cần đi ngược >= amin% so với fill gần nhất
        if ak == 1 and replay == 0 and nf < maxL and (asig[i - 1] & abit) != 0 and i - last_i >= acool and s * (o_ / last_px - 1.0) <= -amin:
            nn = smult * (f_not[nf - 1] if sref == 0 else N0)
            f_bar[nf] = i; f_px[nf] = o_; f_not[nf] = nn
            qty[nf] = nn / o_; alive[nf] = True
            sum_q += qty[nf]; sum_pq += qty[nf] * o_
            last_px = o_; nf += 1; last_i = i
        # ---- pha bất lợi: add / SL
        while True:
            avg = sum_pq / sum_q
            L_add = np.nan
            if replay == 1:
                if nr < r_n and r_bar[nr] <= i and nf < maxL:
                    L_add = r_px[nr]
            elif nf < maxL and step > 0 and ak == 0:
                st = step * (grow ** (nf - 1)) * sc_ref
                if add_ref == 3:
                    if i - last_i >= add_delay:
                        L_add = o_ * (1.0 + s * 1e-9)
                elif add_ref == 0:
                    L_add = last_px * (1.0 - s * st / 100.0)
                elif add_ref == 1:
                    L_add = p0 * (1.0 - s * (cum_step + st) / 100.0)
                else:
                    L_add = avg * (1.0 - s * st / 100.0)
            L_sl = np.nan
            if sl > 0:
                base = avg if sl_ref == 0 else p0
                L_sl = base * (1.0 - s * sl)
            if replay == 1:
                hit_add = not np.isnan(L_add)
            else:
                hit_add = (not np.isnan(L_add)) and s * (adv - L_add) <= 0
            hit_sl = (not np.isnan(L_sl)) and s * (adv - L_sl) <= 0
            if hit_add and hit_sl:
                if s * (L_add - L_sl) >= 0:
                    hit_sl = False
                else:
                    hit_add = False
            if hit_sl:
                px = L_sl if s * (o_ - L_sl) > 0 else o_
                for j in range(nf):
                    if alive[j]:
                        c_bar[nc] = i; c_px[nc] = px; c_qty[nc] = qty[j]; c_lay[nc] = j; nc += 1; alive[j] = False
                return nf, nc, 1
            if hit_add:
                if replay == 1:
                    px = L_add; nn = r_not[nr]; nr += 1
                else:
                    px = L_add if s * (o_ - L_add) > 0 else o_
                    nn = smult * (f_not[nf - 1] if sref == 0 else N0)
                f_bar[nf] = i; f_px[nf] = px; f_not[nf] = nn
                qty[nf] = nn / px; alive[nf] = True
                sum_q += qty[nf]; sum_pq += qty[nf] * px
                cum_step += step * (grow ** (nf - 1)) * sc_ref
                last_px = px; nf += 1; last_i = i
                if use_scale == 1:
                    sc_ref = scale[i]
                continue
            break
        # ---- pha có lợi: TP
        avg = sum_pq / sum_q
        if tp > 0:
            if tp_mode == 0:
                base = avg if tp_ref == 0 else p0
                T = base * (1.0 + s * tp)
                if s * (fav - T) >= 0:
                    px = o_ if (s * (o_ - T) >= 0 and f_bar[nf - 1] != i) else T
                    for j in range(nf):
                        if alive[j]:
                            c_bar[nc] = i; c_px[nc] = px; c_qty[nc] = qty[j]; c_lay[nc] = j; nc += 1; alive[j] = False
                    return nf, nc, 1
            else:
                nal = 0
                for j in range(nf):
                    if alive[j]:
                        T = f_px[j] * (1.0 + s * tp)
                        if s * (fav - T) >= 0:
                            px = o_ if (s * (o_ - T) >= 0 and f_bar[j] != i) else T
                            c_bar[nc] = i; c_px[nc] = px; c_qty[nc] = qty[j]; c_lay[nc] = j; nc += 1; alive[j] = False
                            sum_q -= qty[j]; sum_pq -= qty[j] * f_px[j]
                        else:
                            nal += 1
                if nal == 0:
                    return nf, nc, 1
        if tr_act > 0:
            if s * (fav - ext) > 0:
                ext = fav
            if s * (ext - sum_pq / sum_q) / (sum_pq / sum_q) >= tr_act:
                trail_on = True
    for j in range(nf):
        if alive[j]:
            c_bar[nc] = i_end; c_px[nc] = c[i_end]; c_qty[nc] = qty[j]; c_lay[nc] = j; nc += 1
    return nf, nc, 0


# ---------------------------------------------------------------- chỉ báo trên nến đóng
_TF = {}
_XS = {}
_ZERO = {}


def tf_bars(sym, tf):
    """Nến tf phút từ 1m: dict(ts, o,h,l,c, iend) ; iend = chỉ số nến 1m CUỐI của nến tf (nến đã đóng sau đó)."""
    k = (sym, tf)
    if k in _TF:
        return _TF[k]
    a = candle_arrays(sym)
    if tf == 1:
        d = dict(ts=a["t"], o=a["o"], h=a["h"], l=a["l"], c=a["c"], iend=np.arange(len(a["t"])))
        _TF[k] = d
        return d
    df = pd.DataFrame(dict(o=a["o"], h=a["h"], l=a["l"], c=a["c"]), index=pd.to_datetime(a["t"], unit="ms"))
    r = df.resample(f"{tf}min", label="left", closed="left").agg(dict(o="first", h="max", l="min", c="last")).dropna()
    ts = (r.index.astype("int64") // 10**6).astype(np.int64)
    iend = np.searchsorted(a["t"], ts + tf * MIN, side="left") - 1
    d = dict(ts=ts, o=r.o.values, h=r.h.values, l=r.l.values, c=r.c.values, iend=iend)
    _TF[k] = d
    return d


def _ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up = pd.Series(np.clip(d, 0, None)).ewm(alpha=1 / n, adjust=False).mean().values
    dn = pd.Series(np.clip(-d, 0, None)).ewm(alpha=1 / n, adjust=False).mean().values
    rs = up / np.where(dn == 0, np.nan, dn)
    r = 100 - 100 / (1 + rs)
    r[np.isnan(r)] = 100.0
    return r


def _vwap_daily(sym):
    a = candle_arrays(sym)
    tp = (a["h"] + a["l"] + a["c"]) / 3
    day = a["t"] // (24 * H)
    pv = pd.Series(tp * a["v"]).groupby(day).cumsum().values
    vv = pd.Series(a["v"]).groupby(day).cumsum().values
    return pv / np.where(vv == 0, np.nan, vv)


def exit_events(sym, spec):
    """int8[len(1m)]: bit0 = thoát long, bit1 = thoát short, đặt tại nến 1m cuối của nến tf đóng. spec=None -> không có."""
    a = candle_arrays(sym)
    if not spec:
        k = len(a["t"])
        if k not in _ZERO:
            _ZERO[k] = np.zeros(k, np.int8)
        return _ZERO[k]
    key = (sym, tuple(sorted(spec.items())))
    if key in _XS:
        return _XS[key]
    kind = spec["kind"]; out = np.zeros(len(a["t"]), np.int8)
    if kind == "time":
        mod = ((a["t"] // MIN) + 1) % 1440
        m = np.isin(mod, np.array(spec["times"]))
        if spec.get("wd") == "weekday":
            wd = (a["t"] // (24 * H) + 3) % 7   # 1970-01-01 = Thu -> (+3)%7: Mon=0
            m &= wd < 5
        out[m] = 3
        _XS[key] = out
        return out
    tf = spec.get("tf", 15)
    b = tf_bars(sym, tf); c = b["c"]; edge = spec.get("edge", 1)
    if kind == "rsi":
        r = _rsi(c, 14); L = spec["L"]
        cl = r >= L; cs = r <= 100 - L
    elif kind == "ema":
        e = _ema(c, spec["n"]); cl = c > e; cs = c < e
    elif kind == "sma":
        e = pd.Series(c).rolling(spec["n"]).mean().values; cl = c > e; cs = c < e
    elif kind == "bbext":
        s_ = pd.Series(c); m_ = s_.rolling(20).mean(); sd = s_.rolling(20).std()
        cl = c > (m_ + 2 * sd).values; cs = c < (m_ - 2 * sd).values
    elif kind == "vwap":
        vw = _vwap_daily(sym)[b["iend"]]; cl = c > vw; cs = c < vw
    elif kind == "nbar":
        n = spec["n"]
        hi = pd.Series(b["h"]).rolling(n).max().shift(1).values; lo = pd.Series(b["l"]).rolling(n).min().shift(1).values
        cl = c > hi; cs = c < lo
    elif kind == "macd":
        m_ = _ema(c, 12) - _ema(c, 26); sg = _ema(m_, 9); cl = m_ > sg; cs = m_ < sg
    else:
        raise ValueError(kind)
    cl = np.nan_to_num(cl.astype(float)) > 0 if cl.dtype != bool else cl
    cs = np.nan_to_num(cs.astype(float)) > 0 if cs.dtype != bool else cs
    if edge:
        cl = cl & ~np.r_[False, cl[:-1]]; cs = cs & ~np.r_[False, cs[:-1]]
    ie = b["iend"]
    ok = ie >= 0
    np.bitwise_or.at(out, ie[ok & cl], 1)
    np.bitwise_or.at(out, ie[ok & cs], 2)
    _XS[key] = out
    return out


# ---------------------------------------------------------------- simulate2
def simulate2(basket, params, horizon_min=60, a=None):
    sym = basket["sym"]
    a = a or candle_arrays(sym)
    if a is None:
        return None
    f0 = basket["fills"][0]
    i0 = int(np.searchsorted(a["t"], f0["t"], side="right")) - 1
    i_end = min(len(a["t"]) - 1, int(np.searchsorted(a["t"], basket["t1"] + horizon_min * MIN, side="right")) - 1)
    if i0 < 0 or i_end <= i0:
        return None
    P = pvec2(params)
    fee = float(params.get("fee_bps", sim.PARAM_DEFAULT["fee_bps"])) / 1e4
    s = 1 if basket["side"] == "long" else -1
    f_bar = np.zeros(MAXL, np.int64); f_px = np.zeros(MAXL); f_not = np.zeros(MAXL)
    c_bar = np.zeros(2 * MAXL, np.int64); c_px = np.zeros(2 * MAXL); c_qty = np.zeros(2 * MAXL); c_lay = np.zeros(2 * MAXL, np.int64)
    r_bar = np.zeros(MAXL, np.int64); r_px = np.zeros(MAXL); r_not = np.zeros(MAXL)
    fl = basket["fills"]
    # replay: dùng fill thô thật; fill đầu = tranche đầu (như sim.simulate)
    n0 = basket["tranches"][0]["notional"]
    rest = [f for f in fl[1:] if f["t"] > fl[0]["t"]]
    # các fill chia nhỏ trong 15 phút đầu đã gộp vào n0 -> bỏ khỏi replay
    t_first_tr_end = basket["tranches"][0]["t_last"]
    rest = [f for f in fl[1:] if f["t"] > t_first_tr_end]
    r_n = min(len(rest), MAXL - 1) + 1
    for k, f in enumerate(rest[:MAXL - 1]):
        r_bar[k + 1] = max(i0 + 1, int(np.searchsorted(a["t"], f["t"], side="right")) - 1)
        r_px[k + 1] = f["px"]; r_not[k + 1] = f["notional"]
    xs = exit_events(sym, params.get("xspec"))
    asg = exit_events(sym, params.get("aspec"))
    scale = sim.atr_scale(sym)
    nf, nc, closed = _run2(a["o"], a["h"], a["l"], a["c"], scale, xs, asg, i0, i_end, s, f0["px"], n0, P,
                           f_bar, f_px, f_not, c_bar, c_px, c_qty, c_lay, r_bar, r_px, r_not, r_n)
    fills = [dict(t=int(f0["t"]) if k == 0 else int(a["t"][f_bar[k]]), px=float(f_px[k]), notional=float(f_not[k]), layer=k) for k in range(nf)]
    closes = [dict(t=int(a["t"][c_bar[k]]), px=float(c_px[k]), qty=float(c_qty[k]), layer=int(c_lay[k])) for k in range(nc)]
    pnl = 0.0
    for cl in closes:
        fp = f_px[cl["layer"]]
        pnl += cl["qty"] * (cl["px"] - fp) * s - fee * cl["qty"] * (cl["px"] + fp)
    notional = float(f_not[:nf].sum())
    return dict(fills=fills, closes=closes, closed=bool(closed), pnl=pnl, notional=notional, ret=pnl / notional * 100)


# ---------------------------------------------------------------- tín hiệu VÀO (Level B)
_EF = {}


def entry_frame(sym):
    """Đặc trưng vào lệnh tại lưới 15m đóng: z biến động 1h/4h, lệch VWAP/EMA theo σ, hour/minute UTC. index = t_close ms."""
    if sym in _EF:
        return _EF[sym]
    a = candle_arrays(sym)
    if a is None:
        _EF[sym] = None; return None
    b = tf_bars(sym, 15); c = b["c"]
    f = pd.DataFrame(index=pd.Index(b["ts"] + 15 * MIN, name="t_close"))
    s = pd.Series(c, index=f.index)
    for nm, k in (("ret1h", 4), ("ret4h", 16)):
        r = (s / s.shift(k) - 1) * 100
        f[nm] = r / r.std()
    vw = _vwap_daily(sym)[b["iend"]]
    d = (c / vw - 1) * 100
    f["vwap_z"] = d / pd.Series(d).std()
    e = _ema(c, 50)
    d2 = (c / e - 1) * 100
    f["ema_z"] = d2 / pd.Series(d2).std()
    f["tmin"] = ((f.index.values // MIN) % 1440).astype(int)
    f["hour"] = f["tmin"] // 60
    f = f.dropna()
    _EF[sym] = f
    return f


def _edge_cool(cond, t, cool_ms):
    edge = cond & ~np.r_[False, cond[:-1]]
    tt = t[edge]; keep = []; last = -10**18
    for x in tt:
        if x - last >= cool_ms:
            keep.append(x); last = x
    return np.array(keep, np.int64)


def _hl_touch(sym, N, cool_ms, mode):
    """Chạm đỉnh/đáy N giờ trước (1m). fade: chạm đỉnh -> short, chạm đáy -> long; break: ngược lại."""
    a = candle_arrays(sym); n = N * 60
    hi = pd.Series(a["h"]).rolling(n).max().shift(1).values; lo = pd.Series(a["l"]).rolling(n).min().shift(1).values
    th = a["h"] >= hi; tl = a["l"] <= lo
    th[:n] = False; tl[:n] = False
    t = a["t"]
    up = _edge_cool(th, t, cool_ms); dn = _edge_cool(tl, t, cool_ms)
    return (dn, up) if mode == "fade" else (up, dn)   # (long_times, short_times)


def _round_cross(sym, rel, cool_ms, mode):
    """Giá cắt mức tròn (bội 1-2-5 x 10^k, bước ~ rel% giá). fade: cắt xuống qua mức -> long (hỗ trợ), cắt lên -> short."""
    a = candle_arrays(sym); c = a["c"]
    med = float(np.median(c)); raw = med * rel / 100
    e = 10 ** np.floor(np.log10(raw)); m = raw / e
    step = e * (1 if m < 1.5 else 2 if m < 3.5 else 5 if m < 7.5 else 10)
    lv = np.floor(c / step)
    up = np.r_[False, lv[1:] > lv[:-1]]; dn = np.r_[False, lv[1:] < lv[:-1]]
    u = _edge_cool(up, a["t"], cool_ms); d = _edge_cool(dn, a["t"], cool_ms)
    return (d, u) if mode == "fade" else (u, d)


_ES = {}


def entry_signals(sym, rule):
    """rule: dict(kind, ..., mode 'contra'|'mom'|'fade'|'break'|'both', hours (giờ UTC list|None), cool_h). Trả (long_times, short_times) ms hoặc None.
    Cổng giờ áp SAU khi phát hiện cạnh (cache phần không phụ thuộc giờ)."""
    if candle_arrays(sym) is None:
        return None
    key = (sym,) + tuple(sorted((k, tuple(v) if isinstance(v, (list, tuple)) else v) for k, v in rule.items() if k != "hours"))
    if key not in _ES:
        _ES[key] = _entry_base(sym, rule)
    r = _ES[key]
    if r is None:
        return None
    L, S = r
    if rule.get("hours") is not None:
        hh = lambda ts: np.isin((ts // H) % 24, rule["hours"])
        L = L[hh(L)]; S = S[hh(S)]
    return L, S


def _entry_base(sym, rule):
    cool = int(rule.get("cool_h", 6) * H); kind = rule["kind"]
    if kind == "hl":
        return _hl_touch(sym, rule["N"], cool, rule["mode"])
    if kind == "round":
        return _round_cross(sym, rule["rel"], cool, rule["mode"])
    f = entry_frame(sym)
    if f is None:
        return None
    t = f.index.values.astype(np.int64)
    if kind == "session":
        m = np.isin(f["tmin"].values, np.array(rule["tmins"]))
        x = f["ret4h"].values
        if rule["mode"] == "both":
            return t[m], t[m]
        if rule["mode"] == "contra":
            return t[m & (x < 0)], t[m & (x > 0)]
        return t[m & (x > 0)], t[m & (x < 0)]
    x = f[rule["feat"]].values; thr = rule["thr"]
    lo = x <= -thr; hi = x >= thr
    if rule["mode"] == "mom":
        lo, hi = hi, lo
    return _edge_cool(lo, t, cool), _edge_cool(hi, t, cool)


# ---------------------------------------------------------------- chẩn đoán (infer) bổ sung
def sigdigits(p, maxd=8):
    for d in range(1, maxd + 1):
        e = 10 ** (np.floor(np.log10(abs(p))) - (d - 1))
        if abs(p / e - round(p / e)) < 1e-7:
            return d
    return maxd


def _q(a, qs):
    a = np.asarray(a, float)
    return [] if len(a) == 0 else [round(float(x), 3) for x in np.percentile(a, qs)]


def _rcv(a):
    a = np.asarray(a, float)
    return round(float(np.median(np.abs(a - np.median(a))) / np.median(a)), 3) if len(a) > 3 and np.median(a) != 0 else None


def add_first_touch(baskets):
    """Mỗi add-tranche k>=1: lấy GIÁ add thật làm mức limit; hỏi lần ĐẦU giá chạm mức đó sau t_last của tranche trước (nến 1m) có sát giờ add thật không.
    Nếu bot đặt limit lưới thì độ trễ ~0; nếu add do quyết định thị trường/thủ công thì trễ phân tán. Trả phân vị trễ (phút) và % trong 1/5/15 phút."""
    d = []
    for B in baskets:
        a = candle_arrays(B["sym"]); s = 1 if B["side"] == "long" else -1
        tr = B["tranches"]
        for k in range(1, len(tr)):
            px = tr[k]["px"]; t_prev = tr[k - 1]["t_last"]
            if s * (px - tr[k - 1]["px"]) >= 0:       # add thuận chiều (không phải bắt hồi) -> bỏ
                continue
            i0 = int(np.searchsorted(a["t"], t_prev, side="right")); i1 = int(np.searchsorted(a["t"], tr[k]["t"], side="right"))
            if i1 <= i0: continue
            ext = a["l"][i0:i1 + 1] if s == 1 else a["h"][i0:i1 + 1]
            hit = (ext <= px) if s == 1 else (ext >= px)
            if not hit.any(): continue
            d.append((tr[k]["t"] - int(a["t"][i0 + int(np.argmax(hit))])) / MIN)
    d = np.array(d)
    return dict(n=len(d), delay_min_q=_q(d, [10, 25, 50, 75, 90]), within1=round(100 * float((d <= 1).mean()), 1) if len(d) else None,
                within5=round(100 * float((d <= 5).mean()), 1) if len(d) else None, within15=round(100 * float((d <= 15).mean()), 1) if len(d) else None)


def exit_first_touch(baskets):
    """Mỗi NHÓM đóng (cùng giây): giá đóng thật = mức TP/SL; lần đầu giá chạm mức đó sau fill cuối bị đóng -> trễ so với giờ đóng thật."""
    d = []; kinds = []
    for B in baskets:
        a = candle_arrays(B["sym"]); s = 1 if B["side"] == "long" else -1
        cl = sorted(B["closes"], key=lambda c: c["t"])
        groups = []
        for c in cl:
            if groups and abs(c["t"] - groups[-1][-1]["t"]) <= 3000: groups[-1].append(c)
            else: groups.append([c])
        for g in groups:
            q = sum(c["qty"] for c in g); pxc = sum(c["px"] * c["qty"] for c in g) / q
            tstart = max(B["fills"][c["fill"]]["t"] for c in g)
            avg = sum(B["fills"][c["fill"]]["px"] * c["qty"] for c in g) / q
            i0 = int(np.searchsorted(a["t"], tstart, side="right")); i1 = int(np.searchsorted(a["t"], g[-1]["t"], side="right"))
            if i1 <= i0: continue
            win = slice(i0, i1 + 1)
            win_gain = s * (pxc - avg) > 0
            reach = (a["h"][win] >= pxc) if (s == 1) == win_gain else (a["l"][win] <= pxc)
            if not reach.any(): continue
            d.append((g[-1]["t"] - int(a["t"][win][np.argmax(reach)])) / MIN); kinds.append(win_gain)
    d = np.array(d); k = np.array(kinds, bool)
    out = {}
    for nm, m in (("tp", k), ("sl", ~k)):
        x = d[m]
        out[nm] = dict(n=int(len(x)), within5=round(100 * float((x <= 5).mean()), 1) if len(x) else None, within15=round(100 * float((x <= 15).mean()), 1) if len(x) else None,
                       within60=round(100 * float((x <= 60).mean()), 1) if len(x) else None, delay_min_q=_q(x, [25, 50, 75, 90]))
    return out


EVENT_PROBE = [
    ("rsi50_15m", dict(kind="rsi", tf=15, L=50)), ("rsi60_15m", dict(kind="rsi", tf=15, L=60)), ("rsi70_15m", dict(kind="rsi", tf=15, L=70)),
    ("rsi50_5m", dict(kind="rsi", tf=5, L=50)), ("rsi50_60m", dict(kind="rsi", tf=60, L=50)),
    ("ema20_5m", dict(kind="ema", tf=5, n=20)), ("ema20_15m", dict(kind="ema", tf=15, n=20)), ("ema50_15m", dict(kind="ema", tf=15, n=50)), ("ema20_60m", dict(kind="ema", tf=60, n=20)),
    ("sma20_5m_bbmid", dict(kind="sma", tf=5, n=20)), ("sma20_15m_bbmid", dict(kind="sma", tf=15, n=20)),
    ("bbext_15m", dict(kind="bbext", tf=15)), ("vwap_5m", dict(kind="vwap", tf=5)), ("vwap_15m", dict(kind="vwap", tf=15)), ("vwap_60m", dict(kind="vwap", tf=60)),
    ("nbar10_5m", dict(kind="nbar", tf=5, n=10)), ("nbar20_15m", dict(kind="nbar", tf=15, n=20)), ("nbar12_60m", dict(kind="nbar", tf=60, n=12)),
    ("macd_5m", dict(kind="macd", tf=5)), ("macd_15m", dict(kind="macd", tf=15)), ("macd_60m", dict(kind="macd", tf=60)),
    ("time_funding", dict(kind="time", times=(0, 480, 960))), ("time_us_open", dict(kind="time", times=(810,))), ("time_us_close", dict(kind="time", times=(1200,))),
]


def event_lift(baskets, win_min=10, nrand=40, seed=0):
    """Với luật thoát E: P(có sự kiện E (đúng chiều thoát) trong win_min phút TRƯỚC lần đóng cuối thật) / P(cùng cửa sổ tại thời điểm ngẫu nhiên trong lúc giữ).
    lift>>1 -> thoát thật tập trung ngay sau sự kiện đó. Chỉ tính basket giữ >= 2*win phút."""
    rng = np.random.default_rng(seed); res = []
    bs = [B for B in baskets if (B["t1"] - B["fills"][-1]["t"]) >= 2 * win_min * MIN]
    for nm, spec in EVENT_PROBE:
        pa = []; pr = []
        for B in bs:
            a = candle_arrays(B["sym"]); xs = exit_events(B["sym"], spec); bit = 1 if B["side"] == "long" else 2
            ev = (xs & bit) != 0
            cs = np.cumsum(ev)
            def has(t):
                j = int(np.searchsorted(a["t"], t, side="right")) - 1
                lo = max(0, j - win_min)
                return (cs[j] - cs[lo]) > 0
            pa.append(has(B["t1"]))
            t_lo = B["fills"][-1]["t"] + win_min * MIN; t_hi = B["t1"] - win_min * MIN
            if t_hi > t_lo:
                pr.append(np.mean([has(x) for x in rng.uniform(t_lo, t_hi, nrand)]))
        if not pa or not pr: continue
        res.append(dict(event=nm, spec=spec, p_at_close=round(100 * float(np.mean(pa)), 1), p_random=round(100 * float(np.mean(pr)), 1),
                        lift=round(float(np.mean(pa)) / max(1e-9, float(np.mean(pr))), 2), n=len(pa)))
    return sorted(res, key=lambda r: -r["lift"])


def scale_diag(train):
    """TP và bước add có TỈ LỆ với biến động nào không? Spearman và robust-CV của tỉ số (thấp = cố định) theo ATR%(14) tf 1/5/15/60 phút tại lúc vào/fill trước.
    TP: nhóm đóng có lãi từ avg (tại fill đầu nếu rổ 1 fill). Bước: add tranche ngược chiều >0,02%. Kèm TP quy đổi: % giá, ROI trên ký quỹ (=% x lev), USDT."""
    cache = {}
    def atr(sym, tf):
        k = (sym, tf)
        if k not in cache:
            b = tf_bars(sym, tf); h, l, c = b["h"], b["l"], b["c"]; pc = np.r_[c[0], c[:-1]]
            cache[k] = (b["iend"], pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))) / c * 100).rolling(14).mean().values)
        return cache[k]
    def at(sym, tf, t, a):
        ie, v = atr(sym, tf); j = int(np.searchsorted(a["t"], t, side="right")) - 2; m = int(np.searchsorted(ie, j, side="right")) - 1
        return v[m] if m >= 0 else np.nan
    tp = []; st = []
    for B in train:
        s = 1 if B["side"] == "long" else -1; a = candle_arrays(B["sym"])
        cl = sorted(B["closes"], key=lambda c: c["t"]); groups = []
        for c in cl:
            if groups and abs(c["t"] - groups[-1][-1]["t"]) <= 3000: groups[-1].append(c)
            else: groups.append([c])
        for g in groups:
            q = sum(c["qty"] for c in g); pxc = sum(c["px"] * c["qty"] for c in g) / q
            fl = [B["fills"][c["fill"]] for c in g]; avg = sum(f["px"] * f["qty"] for f in fl) / q
            r = (pxc / avg - 1) * s * 100
            if r > 0.02:
                t0 = min(f["t"] for f in fl)
                tp.append(dict(r=r, roi=r * B["lev"], **{f"a{tf}": at(B["sym"], tf, t0, a) for tf in (1, 5, 15, 60)}))
        T = B["tranches"]
        for i in range(1, len(T)):
            x = -(T[i]["px"] / T[i - 1]["px"] - 1) * s * 100
            if x > 0.02:
                st.append(dict(r=x, **{f"a{tf}": at(B["sym"], tf, T[i - 1]["t_last"], a) for tf in (1, 5, 15, 60)}))
    out = {}
    for nm, rows in (("tp_from_avg", tp), ("step_vs_last", st)):
        d = pd.DataFrame(rows).dropna()
        if len(d) < 8:
            out[nm] = dict(n=len(d)); continue
        o = dict(n=int(len(d)), pct_q=_q(d.r, [10, 25, 50, 75, 90]), pct_robust_cv=_rcv(d.r))
        for tf in (1, 5, 15, 60):
            ratio = d.r / d[f"a{tf}"]
            o[f"atr{tf}m"] = dict(spearman=round(float(d.r.rank().corr(d[f"a{tf}"].rank())), 2), ratio_median=round(float(ratio.median()), 3), ratio_robust_cv=_rcv(ratio))
        if nm == "tp_from_avg":
            o["roi_on_margin_robust_cv"] = _rcv(d.roi)
        out[nm] = o
    return out


def infer_dca(train, bot=None):
    """Bằng chứng bổ sung từ TRAIN (không dùng test): độ tròn giá, size theo qty, đóng chung, giờ trong ngày, bước trong-basket, first-touch add/exit, lift sự kiện."""
    sg = lambda B: 1 if B["side"] == "long" else -1
    rng = np.random.default_rng(0)
    fs = [sigdigits(f["px"]) for B in train for f in B["fills"]]; cs = [sigdigits(c["px"]) for B in train for c in B["closes"]]
    base = []
    for B in train[::2]:
        a = candle_arrays(B["sym"]); base += [sigdigits(float(p)) for p in a["c"][rng.integers(0, len(a["c"]), 20)]]
    pct = lambda x, k: round(100 * float(np.mean(np.array(x) <= k)), 1)
    rnd = dict(fill_le4=pct(fs, 4), fill_le5=pct(fs, 5), close_le4=pct(cs, 4), close_le5=pct(cs, 5), candle_close_le4=pct(base, 4), candle_close_le5=pct(base, 5),
               fill_8digit=round(100 * float(np.mean(np.array(fs) >= 8)), 1), close_8digit=round(100 * float(np.mean(np.array(cs) >= 8)), 1))
    # size theo qty: các giá trị qty hay gặp nhất (3 chữ số có nghĩa) và tỉ lệ phủ
    qc = collections.Counter(float('%.3g' % (f["notional"] / f["px"])) for B in train for f in B["fills"])
    qtop = [[k, v] for k, v in qc.most_common(6)]; qcover = round(100 * sum(v for _, v in qc.most_common(6)) / max(1, sum(qc.values())), 1)
    # đóng chung
    sh = tot = 0; same_px = 0; stg = 0; multi = 0
    for B in train:
        if len(B["fills"]) > 1:
            multi += 1
            if len({round(c["t"] / 3000) for c in B["closes"]}) > 1: stg += 1
        if len(B["closes"]) > 1:
            ts = sorted(c["t"] for c in B["closes"]); tot += len(ts)
            sh += sum(1 for i, t in enumerate(ts) if any(abs(t - u) <= 3000 for j, u in enumerate(ts) if j != i))
            cc = collections.Counter(round(c["px"], 6) for c in B["closes"]); same_px += sum(v for v in cc.values() if v > 1)
    # bước trong-basket & so với avg
    cvs = []; steps_l = []; steps_a = []; steps_f = []; ratios_in = []
    for B in train:
        tr = B["tranches"]; s = sg(B)
        if len(tr) >= 3:
            st = [-(tr[i]["px"] / tr[i - 1]["px"] - 1) * s * 100 for i in range(1, len(tr))]
            if all(x > 0 for x in st): cvs.append(np.std(st) / np.mean(st))
            r = [st[i] / st[i - 1] for i in range(1, len(st))]; ratios_in += r
    # time of day (UTC) mở/đóng
    T = [(f["t"]) for B in train for f in B["fills"][:1]]; TC = [B["t1"] for B in train]
    ho = np.bincount(((np.array(T) // H) % 24).astype(int), minlength=24); hc = np.bincount(((np.array(TC) // H) % 24).astype(int), minlength=24)
    # gần mốc phiên (±3 phút) cho thời điểm đóng (mọi close) so baseline phân bố đều
    allc = np.array([c["t"] for B in train for c in B["closes"]]); mod = (allc // MIN) % 1440
    near = lambda m: round(100 * float(np.mean(np.min(np.abs(((mod[:, None] - np.array(m)[None, :]) + 720) % 1440 - 720), axis=1) <= 3)), 1)
    near_exp = lambda m: round(100 * len(m) * 7 / 1440, 1)
    sess = dict(close_near_funding_3m=near([0, 480, 960]), expected_if_uniform=near_exp([0, 480, 960]),
                close_near_us_open_1330_3m=near([810]), close_near_us_close_2000_3m=near([1200]), expected_per_mark=near_exp([0]))
    # khoảng thời gian từ add cuối đến lần đóng cuối
    d_after = [(B["t1"] - B["fills"][-1]["t"]) / MIN for B in train if len(B["fills"]) > 1]
    d_first = [(B["t1"] - B["t0"]) / MIN for B in train]
    return dict(
        roundness=rnd, qty_top6=qtop, qty_top6_cover_pct=qcover,
        pct_closes_sharing_time_with_sibling=round(100 * sh / max(1, tot), 1), pct_closes_sharing_exact_px=round(100 * same_px / max(1, tot), 1),
        pct_multifill_baskets_staged_closes=round(100 * stg / max(1, multi), 1),
        within_basket_step_cv_median=round(float(np.median(cvs)), 3) if cvs else None, n_within_basket_cv=len(cvs),
        step_ratio_consecutive_q=_q(ratios_in, [25, 50, 75]) if ratios_in else None,
        hour_utc_first_fill_pct=(100 * ho / max(1, ho.sum())).round(1).tolist(), hour_utc_last_close_pct=(100 * hc / max(1, hc.sum())).round(1).tolist(),
        session_proximity=sess, min_from_last_add_to_last_close_q=_q(d_after, [10, 25, 50, 75, 90]), min_hold_q=_q(d_first, [10, 25, 50, 75, 90]),
        scale_diag=scale_diag(train), add_first_touch=add_first_touch(train), exit_first_touch=exit_first_touch(train), event_lift_top=event_lift(train)[:12],
    )
