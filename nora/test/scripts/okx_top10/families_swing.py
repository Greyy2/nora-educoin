"""Họ luật SWING / SCALP cho Professor-Wang, M Power7, Dark-Wood-Dahlia (import load/sim/match/features; KHÔNG sửa chúng).

Gồm 3 phần:
  1. sim2: simulator basket (numba) mở rộng so với sim.py: thêm
       - time-stop CÓ ĐIỀU KIỆN (cắt nếu chưa có lãi sau T giờ; chốt nếu đang lãi sau T giờ),
       - thoát theo CHỈ BÁO trên nến ĐÓNG 5m/15m/1h (cắt qua EMA / VWAP ngày / BB mid / RSI qua 50), tuỳ chọn tham chiếu mã khác (BTC),
       - thoát theo PHIÊN (phút trong ngày UTC: 20:00 = đóng cửa Mỹ, 13:30 = mở cửa Mỹ) có cổng lãi/lỗ,
       - trailing / SL / TP theo % hoặc bội số ATR%(1h) tại fill đầu, add (như sim.py), tối đa 64 tầng.
     Quy ước đường giá trong nến, khớp lệnh, phí: như sim.py (nến chứa fill đầu bị bỏ; adverse trước favorable).
     Thoát theo thời gian/chỉ báo/phiên khớp ở giá OPEN nến 1m đầu tiên sau khi điều kiện đúng (chỉ dùng thông tin đã có).
  2. Level B entries: tín hiệu vào lệnh (ORB phiên Mỹ, N-sigma theo ATR, pullback về EMA/VWAP theo xu hướng, mức cao/thấp hôm trước)
     trên nến đóng; không look-ahead.
  3. tiện ích: diagnostics suy luận luật từ dữ liệu bot, chỉ số phụ (hold error, baseline thời gian giữ ngẫu nhiên).
"""
import numpy as np
import pandas as pd
from numba import njit

from load import MIN, candle_arrays
import sim

H = 3_600_000
DAY = 24 * H
MAXL2 = 64

# ------------------------------------------------------------------ tham số
_ORDER2 = ["add_ref", "step", "step_scale", "growth", "maxL", "size_mult", "size_ref",
           "tp", "tp_scale", "tp_ref", "sl", "sl_scale", "sl_ref",
           "tr_act", "tr_dist", "tr_scale", "maxhold", "tx_bars", "tx_gate", "tx_thr", "tx_once", "ty_bars", "ty_gate",
           "xgate", "xmin", "xthr", "sgate", "smin", "sthr", "be_act", "be_scale", "be_off"]
DEF2 = dict(add_ref=0, step=1.0, step_scale=0, growth=1.0, maxL=1, size_mult=0.33, size_ref=1, tp=0.0, tp_scale=0, tp_ref=0,
            sl=0.0, sl_scale=0, sl_ref=0, tr_act=0.0, tr_dist=0.0, tr_scale=0, maxhold=0, tx_bars=0, tx_gate=0, tx_thr=0.0, tx_once=0,
            ty_bars=0, ty_gate=0, xgate=0, xmin=0, xthr=0.0, sgate=0, smin=0, sthr=0.0, be_act=0.0, be_scale=0, be_off=0.0, fee_bps=3.5)
# gate: 0 = luôn, 1 = chỉ khi lãi treo > thr% (thr mặc định 0), 2 = chỉ khi lãi treo <= thr% (chưa có lãi)


_ROI_MAP = {"sl_roi": "sl", "tp_roi": "tp", "tr_act_roi": "tr_act", "tr_dist_roi": "tr_dist", "be_act_roi": "be_act"}


def roi_params(params, lev):
    """Tham số theo ROI trên ký quỹ (%) -> % giá = ROI / đòn bẩy của basket (đòn bẩy biết lúc vào). Vd sl_roi=27 với 20x -> SL giá 1.35%."""
    if not any(k in params for k in _ROI_MAP):
        return params
    p = dict(params)
    for k, v in _ROI_MAP.items():
        if k in p:
            x = p.pop(k)
            if x: p[v] = x / max(lev, 1.0); p[v + "_scale"] = 0 if v in ("sl", "tp") else p.get(v + "_scale", 0)
    return p


def pvec2(params):
    p = dict(DEF2); p.update({k: v for k, v in params.items() if k in DEF2})
    return np.array([float(p[k]) for k in _ORDER2], dtype=np.float64)


@njit(cache=True)
def _close_all(i, px, nf, alive, qty, c_bar, c_px, c_qty, c_lay, nc):
    for j in range(nf):
        if alive[j]:
            c_bar[nc] = i; c_px[nc] = px; c_qty[nc] = qty[j]; c_lay[nc] = j; nc += 1; alive[j] = False
    return nc


@njit(cache=True)
def _gate(g, u, thr):
    if g == 0: return True
    if g == 1: return u > thr
    return u <= thr


@njit(cache=True)
def _run2(o, h, l, c, scale, xf, sf, i0, i_end, s, p0, N0, P, f_bar, f_px, f_not, c_bar, c_px, c_qty, c_lay):
    add_ref = int(P[0]); step = P[1]; step_scale = int(P[2]); grow = P[3]; maxL = min(int(P[4]), 64); smult = P[5]; sref = int(P[6])
    sc0 = scale[i0]
    tp = P[7] / 100.0
    if int(P[8]) == 1: tp = tp * sc0
    tp_ref = int(P[9])
    sl = P[10] / 100.0
    if int(P[11]) == 1: sl = sl * sc0
    sl_ref = int(P[12])
    tr_act = P[13] / 100.0; tr_dist = P[14] / 100.0
    if int(P[15]) == 1:
        tr_act = tr_act * sc0; tr_dist = tr_dist * sc0
    maxhold = int(P[16]); tx_bars = int(P[17]); tx_gate = int(P[18]); tx_thr = P[19] / 100.0; tx_once = int(P[20])
    ty_bars = int(P[21]); ty_gate = int(P[22])
    xgate = int(P[23]); xmin = int(P[24]); xthr = P[25] / 100.0; sgate = int(P[26]); smin = int(P[27]); sthr = P[28] / 100.0
    be_act = P[29] / 100.0
    if int(P[30]) == 1: be_act = be_act * sc0
    be_off = P[31] / 100.0; be_on = False
    nf = 1; nc = 0
    f_bar[0] = i0; f_px[0] = p0; f_not[0] = N0
    qty = np.zeros(64); alive = np.zeros(64, dtype=np.bool_)
    qty[0] = N0 / p0; alive[0] = True
    sum_q = qty[0]; sum_pq = qty[0] * p0
    last_px = p0; cum_step = 0.0
    sc_ref = scale[i0] if step_scale == 1 else 1.0
    ext = p0; trail_on = False
    for i in range(i0 + 1, i_end + 1):
        o_ = o[i]; h_ = h[i]; l_ = l[i]
        adv = l_ if s == 1 else h_
        fav = h_ if s == 1 else l_
        avg = sum_pq / sum_q
        u = s * (o_ / avg - 1.0)
        k = i - i0
        # --- thoát theo thời gian / chỉ báo / phiên (khớp tại open nến)
        if maxhold > 0 and k >= maxhold:
            nc = _close_all(i, o_, nf, alive, qty, c_bar, c_px, c_qty, c_lay, nc); return nf, nc, 1
        if tx_bars > 0 and ((tx_once == 0 and k >= tx_bars) or (tx_once == 1 and k == tx_bars)) and _gate(tx_gate, u, tx_thr):
            nc = _close_all(i, o_, nf, alive, qty, c_bar, c_px, c_qty, c_lay, nc); return nf, nc, 1
        if ty_bars > 0 and k >= ty_bars and _gate(ty_gate, u, tx_thr):
            nc = _close_all(i, o_, nf, alive, qty, c_bar, c_px, c_qty, c_lay, nc); return nf, nc, 1
        if xf[i] != 0 and k >= xmin and _gate(xgate, u, xthr):
            nc = _close_all(i, o_, nf, alive, qty, c_bar, c_px, c_qty, c_lay, nc); return nf, nc, 1
        if sf[i] != 0 and k >= smin and _gate(sgate, u, sthr):
            nc = _close_all(i, o_, nf, alive, qty, c_bar, c_px, c_qty, c_lay, nc); return nf, nc, 1
        # --- trailing (đỉnh các nến trước)
        if trail_on:
            stp = ext * (1.0 - s * tr_dist)
            if s * (adv - stp) <= 0:
                px = stp if s * (o_ - stp) > 0 else o_
                nc = _close_all(i, px, nf, alive, qty, c_bar, c_px, c_qty, c_lay, nc); return nf, nc, 1
        # --- pha bất lợi: add / SL
        while True:
            avg = sum_pq / sum_q
            L_add = np.nan
            if nf < maxL and step > 0:
                st = step * (grow ** (nf - 1)) * sc_ref
                if add_ref == 0: L_add = last_px * (1.0 - s * st / 100.0)
                elif add_ref == 1: L_add = p0 * (1.0 - s * (cum_step + st) / 100.0)
                else: L_add = avg * (1.0 - s * st / 100.0)
            L_sl = np.nan
            if sl > 0:
                base = avg if sl_ref == 0 else p0
                L_sl = base * (1.0 - s * sl)
            if be_on:
                L_be = avg * (1.0 + s * be_off)
                if np.isnan(L_sl) or s * (L_be - L_sl) > 0: L_sl = L_be
            hit_add = (not np.isnan(L_add)) and s * (adv - L_add) <= 0
            hit_sl = (not np.isnan(L_sl)) and s * (adv - L_sl) <= 0
            if hit_add and hit_sl:
                if s * (L_add - L_sl) >= 0: hit_sl = False
                else: hit_add = False
            if hit_sl:
                px = L_sl if s * (o_ - L_sl) > 0 else o_
                nc = _close_all(i, px, nf, alive, qty, c_bar, c_px, c_qty, c_lay, nc); return nf, nc, 1
            if hit_add:
                px = L_add if s * (o_ - L_add) > 0 else o_
                nn = smult * (f_not[nf - 1] if sref == 0 else N0)
                f_bar[nf] = i; f_px[nf] = px; f_not[nf] = nn
                qty[nf] = nn / px; alive[nf] = True
                sum_q += qty[nf]; sum_pq += qty[nf] * px
                cum_step += step * (grow ** (nf - 1)) * sc_ref
                last_px = px; nf += 1
                if step_scale == 1: sc_ref = scale[i]
                continue
            break
        # --- pha có lợi: TP
        avg = sum_pq / sum_q
        if tp > 0:
            base = avg if tp_ref == 0 else p0
            T = base * (1.0 + s * tp)
            if s * (fav - T) >= 0:
                px = o_ if (s * (o_ - T) >= 0 and f_bar[nf - 1] != i) else T
                nc = _close_all(i, px, nf, alive, qty, c_bar, c_px, c_qty, c_lay, nc); return nf, nc, 1
        if tr_act > 0 or be_act > 0:
            if s * (fav - ext) > 0: ext = fav
            if tr_act > 0 and s * (ext - avg) / avg >= tr_act: trail_on = True
            if be_act > 0 and s * (ext - avg) / avg >= be_act: be_on = True
    for j in range(nf):
        if alive[j]:
            c_bar[nc] = i_end; c_px[nc] = c[i_end]; c_qty[nc] = qty[j]; c_lay[nc] = j; nc += 1
    return nf, nc, 0


# ------------------------------------------------------------------ chỉ báo trên nến đóng
_TF = {}
_EVT = {}
_VW = {}


def _tf_frame(sym, tf):
    k = (sym, tf)
    if k not in _TF:
        a = candle_arrays(sym)
        idx = pd.to_datetime(a["t"], unit="ms")
        df = pd.DataFrame(dict(o=a["o"], h=a["h"], l=a["l"], c=a["c"], v=a["v"]), index=idx)
        g = df.resample(f"{tf}min", label="left", closed="left").agg(dict(o="first", h="max", l="min", c="last", v="sum")).dropna()
        g["t_end"] = g.index.astype("int64") // 10**6 + tf * MIN
        _TF[k] = g
    return _TF[k]


def vwap_day(sym):
    """VWAP tích luỹ theo ngày UTC (typical price x volume) tại từng nến 1m (gồm nến đó)."""
    if sym not in _VW:
        a = candle_arrays(sym)
        tp = (a["h"] + a["l"] + a["c"]) / 3.0; v = np.maximum(a["v"], 1e-12)
        day = a["t"] // DAY
        s = pd.Series(tp * v).groupby(day).cumsum().values; w = pd.Series(v).groupby(day).cumsum().values
        _VW[sym] = s / w
    return _VW[sym]


def _rsi(c, n):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def cross_events(sym, ind, n, tf, level=50.0):
    """Trả (U, D): mảng int8 độ dài = số nến 1m của sym; =1 tại nến 1m đầu tiên SAU khi nến tf đóng mà giá (hoặc RSI) cắt LÊN (U) / XUỐNG (D) chỉ báo."""
    k = (sym, ind, n, tf, level)
    if k in _EVT:
        return _EVT[k]
    a = candle_arrays(sym); g = _tf_frame(sym, tf); cl = g["c"]
    if ind == "shock":     # cú sốc: lợi suất 1 nến tf đóng / (ATR%(1h) x sqrt(tf/60)) vượt +-n (n = ngưỡng sigma); U = tăng mạnh, D = giảm mạnh (sự kiện mức, không cần cắt)
        j0 = np.clip(np.searchsorted(a["t"], g.index.astype("int64").values // 10**6, side="left"), 0, len(a["t"]) - 1)
        z = ((g["c"] / g["o"] - 1) * 100).values / (sim.atr_scale(sym)[j0] * np.sqrt(tf / 60.0))
        U = np.zeros(len(a["t"]), np.int8); D = np.zeros(len(a["t"]), np.int8)
        te = g["t_end"].values
        for E, arr in ((z >= n, U), (z <= -n, D)):
            ii = np.searchsorted(a["t"], te[E], side="left"); ii = ii[ii < len(arr)]; arr[ii] = 1
        _EVT[k] = (U, D)
        return _EVT[k]
    if ind == "donch":     # Donchian: D = đóng dưới đáy n nến tf trước; U = đóng trên đỉnh n nến trước (sự kiện mức)
        lowest = g["l"].rolling(n).min().shift(1).values; highest = g["h"].rolling(n).max().shift(1).values
        cv = g["c"].values; te = g["t_end"].values
        U = np.zeros(len(a["t"]), np.int8); D = np.zeros(len(a["t"]), np.int8)
        with np.errstate(invalid="ignore"):
            for E, arr in ((cv > highest, U), (cv < lowest, D)):
                ii = np.searchsorted(a["t"], te[E], side="left"); ii = ii[ii < len(arr)]; arr[ii] = 1
        _EVT[k] = (U, D)
        return _EVT[k]
    if ind == "ema": x = cl; y = cl.ewm(span=n, adjust=False).mean()
    elif ind == "bb": x = cl; y = cl.rolling(n).mean()
    elif ind == "vwap":
        vw = vwap_day(sym)
        j = np.searchsorted(a["t"], g["t_end"].values, side="left") - 1
        j = np.clip(j, 0, len(vw) - 1)
        x = cl; y = pd.Series(vw[j], index=cl.index)
    elif ind == "rsi": x = _rsi(cl, n); y = pd.Series(level, index=cl.index)
    elif ind == "ema_x":      # EMA nhanh n cắt EMA chậm 3n
        x = cl.ewm(span=n, adjust=False).mean(); y = cl.ewm(span=3 * n, adjust=False).mean()
    else: raise ValueError(ind)
    d = (x - y).values
    prev = np.r_[np.nan, d[:-1]]
    with np.errstate(invalid="ignore"):
        Ue = (d > 0) & (prev <= 0); De = (d < 0) & (prev >= 0)
    U = np.zeros(len(a["t"]), np.int8); D = np.zeros(len(a["t"]), np.int8)
    te = g["t_end"].values
    for E, arr in ((Ue, U), (De, D)):
        ii = np.searchsorted(a["t"], te[E], side="left")
        ii = ii[ii < len(arr)]
        arr[ii] = 1
    _EVT[k] = (U, D)
    return _EVT[k]


def x_flags(sym, B_side, xspec):
    """xspec = (ind, n, tf, dir, ref[, level]); dir 'against' = cắt NGƯỢC chiều vị thế (long: cắt xuống); 'with' = cắt thuận chiều (chốt kiểu mean-reversion).
    ref = 'self' hoặc mã khác (vd BTC) - cắt của mã tham chiếu (thị trường chung) áp cho nến 1m của sym theo thời gian (khớp bằng t)."""
    if xspec is None:
        return None
    ind, n, tf, dr, ref = xspec[:5]
    lvl = xspec[5] if len(xspec) > 5 else 50.0
    long = B_side == "long"
    use_down = (dr == "against") == long      # long & against -> D ; long & with -> U ; short & against -> U ; short & with -> D
    rs = sym if ref == "self" else ref
    U, D = cross_events(rs, ind, n, tf, lvl)
    f = D if use_down else U
    if rs == sym:
        return f
    ar = candle_arrays(rs); a = candle_arrays(sym)
    out = np.zeros(len(a["t"]), np.int8)
    te = ar["t"][f.astype(bool)]
    ii = np.searchsorted(a["t"], te, side="left"); ii = ii[ii < len(out)]
    out[ii] = 1
    return out


_SESS = {}


def s_flags(sym, minute_of_day):
    if minute_of_day is None:
        return None
    k = (sym, minute_of_day)
    if k not in _SESS:
        a = candle_arrays(sym)
        _SESS[k] = (((a["t"] // MIN) % 1440) == minute_of_day).astype(np.int8)
    return _SESS[k]


_ZERO = {}


def simulate2(basket, params, xspec=None, smin_of_day=None, horizon_min=60, a=None):
    """Giống sim.simulate nhưng dùng _run2 (điều kiện hoá theo fill đầu thật; kết quả cùng định dạng cho match.basket_row)."""
    sym = basket["sym"]
    a = a or candle_arrays(sym)
    if a is None:
        return None
    f0 = basket["fills"][0]
    i0 = int(np.searchsorted(a["t"], f0["t"], side="right")) - 1
    i_end = min(len(a["t"]) - 1, int(np.searchsorted(a["t"], basket["t1"] + horizon_min * MIN, side="right")) - 1)
    if i0 < 0 or i_end <= i0:
        return None
    return _simulate_from(basket["sym"], basket["side"], i0, i_end, f0["px"], basket["tranches"][0]["notional"], f0["t"], roi_params(params, basket["lev"]), xspec, smin_of_day, a)


def _simulate_from(sym, side, i0, i_end, p0, n0, t0, params, xspec, smin_of_day, a):
    P = pvec2(params)
    fee = float(params.get("fee_bps", DEF2["fee_bps"])) / 1e4
    s = 1 if side == "long" else -1
    n = len(a["t"])
    if n not in _ZERO: _ZERO[n] = np.zeros(n, np.int8)
    xf = x_flags(sym, side, xspec); xf = _ZERO[n] if xf is None else xf
    sf = s_flags(sym, smin_of_day); sf = _ZERO[n] if sf is None else sf
    M = MAXL2
    f_bar = np.zeros(M, np.int64); f_px = np.zeros(M); f_not = np.zeros(M)
    c_bar = np.zeros(2 * M, np.int64); c_px = np.zeros(2 * M); c_qty = np.zeros(2 * M); c_lay = np.zeros(2 * M, np.int64)
    nf, nc, closed = _run2(a["o"], a["h"], a["l"], a["c"], sim.atr_scale(sym), xf, sf, i0, i_end, s, p0, n0, P, f_bar, f_px, f_not, c_bar, c_px, c_qty, c_lay)
    fills = [dict(t=int(t0) if k == 0 else int(a["t"][f_bar[k]]), px=float(f_px[k]), notional=float(f_not[k]), layer=k) for k in range(nf)]
    closes = [dict(t=int(a["t"][c_bar[k]]), px=float(c_px[k]), qty=float(c_qty[k]), layer=int(c_lay[k])) for k in range(nc)]
    pnl = 0.0
    for cl in closes:
        fp = f_px[cl["layer"]]
        pnl += cl["qty"] * (cl["px"] - fp) * s - fee * cl["qty"] * (cl["px"] + fp)
    notional = float(f_not[:nf].sum())
    return dict(fills=fills, closes=closes, closed=bool(closed), pnl=pnl, notional=notional, ret=pnl / notional * 100)


def free_run(sym, side, t_sig, notional, params, xspec, smin_of_day, max_days=14, lev=10.0):
    """Chạy tự do 1 lệnh từ tín hiệu (vào tại open nến 1m kế tiếp sau t_sig; horizon max_days)."""
    a = candle_arrays(sym)
    i0 = int(np.searchsorted(a["t"], t_sig, side="left"))
    if i0 >= len(a["t"]) - 2:
        return None
    i_end = min(len(a["t"]) - 1, i0 + max_days * 1440)
    # vào ở open nến i0 -> mô phỏng bắt đầu từ i0+1 (như quy ước)
    return _simulate_from(sym, side, i0, i_end, float(a["o"][i0]), notional, int(a["t"][i0]), roi_params(params, lev), xspec, smin_of_day, a)


# ------------------------------------------------------------------ Level B: tín hiệu vào lệnh (nến đóng, không look-ahead)
_EN = {}


def _edge_cool(cond, tclose, cool_h):
    """cạnh lên + cooldown (giờ). Trả mảng ms (thời điểm đóng nến)."""
    edge = cond & ~np.r_[False, cond[:-1]]
    t = tclose[edge]
    keep = []; last = -10**18; cool = cool_h * H
    for ti in t:
        if ti - last >= cool:
            keep.append(ti); last = ti
    return np.array(keep, np.int64)


def raw_entry(sym, fam, prm):
    """Điều kiện boolean (long, short) trên lưới nến + t_close. fam in orb | nsig | pull | pday. Cache theo (sym,fam,prm)."""
    key = (sym, fam, prm)
    if key in _EN:
        return _EN[key]
    a = candle_arrays(sym)
    if fam == "nsig":      # prm=(k nến 15m, thr, mode)  x = ret_k / (ATR%(1h) * sqrt(k*15/60))
        k, thr, mode = prm
        g = _tf_frame(sym, 15); cl = g["c"].values; te = g["t_end"].values
        j = np.clip(np.searchsorted(a["t"], te, side="left") - 1, 0, len(a["t"]) - 1)
        atr = sim.atr_scale(sym)[j]
        r = np.full(len(cl), np.nan); r[k:] = (cl[k:] / cl[:-k] - 1) * 100
        x = r / (atr * np.sqrt(k * 15 / 60.0))
        up = x >= thr; dn = x <= -thr
        lo, hi = (dn, up) if mode == "contra" else (up, dn)
        out = (lo & ~np.isnan(x), hi & ~np.isnan(x), te)
    elif fam == "pull":    # prm=(ind, n, trend_on)  trend 1h: close>EMA50(1h) ; chạm EMA/VWAP 15m rồi đóng thuận
        ind, n, trend = prm
        g = _tf_frame(sym, 15); cl = g["c"].values; lw = g["l"].values; hg = g["h"].values; te = g["t_end"].values
        if ind == "ema": y = g["c"].ewm(span=n, adjust=False).mean().values
        else:
            vw = vwap_day(sym); j = np.clip(np.searchsorted(a["t"], te, side="left") - 1, 0, len(vw) - 1); y = vw[j]
        if trend:
            g1 = _tf_frame(sym, 60); e50 = g1["c"].ewm(span=50, adjust=False).mean(); tr = (g1["c"] - e50).values
            t1 = g1["t_end"].values
            jj = np.searchsorted(t1, te, side="right") - 1      # giờ đã đóng gần nhất tại t_end của nến 15m
            ok = jj >= 0; tru = np.where(ok, tr[np.clip(jj, 0, len(tr) - 1)], np.nan)
            lt = tru > 0; st = tru < 0
        else:
            lt = st = np.ones(len(cl), bool)
        lo = (lw <= y) & (cl > y) & lt; hi = (hg >= y) & (cl < y) & st
        out = (lo, hi, te)
    elif fam == "dist":    # prm=(ind, thr, mode): giá 15m đóng cách VWAP ngày / EMA20(15m) >= thr x ATR%(1h); contra: dưới -> long (bắt hồi), mom: trên -> long
        ind, thr, mode = prm
        g = _tf_frame(sym, 15); cl = g["c"].values; te = g["t_end"].values
        j = np.clip(np.searchsorted(a["t"], te, side="left") - 1, 0, len(a["t"]) - 1); atr = sim.atr_scale(sym)[j]
        if ind == "vwap": y = vwap_day(sym)[j]
        else: y = g["c"].ewm(span=20, adjust=False).mean().values
        x = (cl / y - 1) * 100 / atr
        up = x >= thr; dn = x <= -thr
        lo, hi = (dn, up) if mode == "contra" else (up, dn)
        out = (lo, hi, te)
    elif fam == "pday":    # prm=(mode,)  mom: 15m đóng vượt đỉnh/đáy ngày UTC trước ; rev: quét đáy/đỉnh hôm trước rồi đóng lại trong biên
        mode = prm[0]
        g = _tf_frame(sym, 15); cl = g["c"].values; lw = g["l"].values; hg = g["h"].values; te = g["t_end"].values
        day = (g.index.astype("int64") // 10**6) // DAY
        dd = pd.DataFrame(dict(h=g["h"].values, l=g["l"].values, d=day)).groupby("d").agg(h=("h", "max"), l=("l", "min"))
        pdh = pd.Series(day).map(dd.h.shift(1)).values; pdl = pd.Series(day).map(dd.l.shift(1)).values
        if mode == "mom": lo = cl > pdh; hi = cl < pdl
        else: lo = (lw < pdl) & (cl > pdl); hi = (hg > pdh) & (cl < pdh)
        ok = ~(np.isnan(pdh) | np.isnan(pdl))
        out = (lo & ok, hi & ok, te)
    elif fam == "orb":     # prm=(open_min UTC, range_min, win_min) ORB: 5m đóng vượt biên độ [open, open+range) trong win phút sau đó
        om, rm, wm = prm
        g = _tf_frame(sym, 5); cl = g["c"].values; te = g["t_end"].values; ts = g.index.astype("int64") // 10**6
        day = ts // DAY; mod = (ts // MIN) % 1440
        lo = np.zeros(len(cl), bool); hi = np.zeros(len(cl), bool)
        gd = pd.DataFrame(dict(h=g["h"].values, l=g["l"].values, d=day, m=mod))
        inr = (gd.m >= om) & (gd.m < om + rm)
        rng = gd[inr].groupby("d").agg(rh=("h", "max"), rl=("l", "min"))
        rh = gd.d.map(rng.rh).values; rl = gd.d.map(rng.rl).values
        inw = (mod >= om + rm) & (mod < om + rm + wm)
        up = (cl > rh) & inw; dn = (cl < rl) & inw
        # chỉ lấy lần ĐẦU mỗi ngày mỗi chiều (cạnh lên theo ngày)
        for arr, src in ((lo, up), (hi, dn)):
            first = pd.Series(src).groupby(day).cumsum().values == 1
            arr[:] = src & first
        out = (lo, hi, te)
    else:
        raise ValueError(fam)
    _EN[key] = out
    return out


def entry_signals(sym, rule, lo_t, hi_t):
    """rule = dict(fam, prm, hours (list giờ VN hoặc None), us (bool: chỉ phiên Mỹ 13:30-20:00 UTC), cool_h). Trả (times_long, times_short) trong [lo_t,hi_t]."""
    lo, hi, te = raw_entry(sym, rule["fam"], rule["prm"])
    hr_vn = ((te // H + 7) % 24).astype(int)
    m = np.ones(len(te), bool)
    if rule.get("hours") is not None:
        m &= np.isin(hr_vn, rule["hours"])
    if rule.get("us"):
        mod = (te // MIN) % 1440
        m &= (mod >= 810) & (mod < 1200)
    out = []
    for cond in (lo & m, hi & m):
        t = _edge_cool(cond, te, rule.get("cool_h", 6))
        out.append(t[(t >= lo_t) & (t <= hi_t)])
    return out[0], out[1]


# ------------------------------------------------------------------ chỉ số phụ
def extra_metrics(rows, hold_train_min=None):
    """hold error + baseline thời gian giữ ngẫu nhiên (lấy mẫu từ phân bố giữ của TRAIN, độc lập với giá)."""
    ok = [r for r in rows if "sim_ret" in r and r.get("sim_closed")]
    out = {}
    if not ok:
        return out
    ha = np.array([(r["act_close"]["t"] - r["t0"]) / MIN for r in ok]); hs = np.array([(r["sim_close"]["t"] - r["t0"]) / MIN for r in ok])
    out["hold_med_abs_log_ratio"] = round(float(np.median(np.abs(np.log((hs + 1) / (ha + 1))))), 3)
    out["hold_spearman"] = round(float(pd.Series(ha).rank().corr(pd.Series(hs).rank())), 3) if len(ok) > 3 else None
    ar = np.array([r["act_ret"] for r in ok]); sr = np.array([r["sim_ret"] for r in ok])
    out["ret_spearman"] = round(float(pd.Series(ar).rank().corr(pd.Series(sr).rank())), 3) if len(ok) > 3 else None
    out["hold_act_med_h"] = round(float(np.median(ha) / 60), 2); out["hold_sim_med_h"] = round(float(np.median(hs) / 60), 2)
    if hold_train_min is not None and len(hold_train_min):
        allh = np.array([(r["act_close"]["t"] - r["t0"]) / MIN for r in rows if "sim_ret" in r])
        ht = np.asarray(hold_train_min)
        for tol in (15, 60):
            out[f"rand_hold_close_match_{tol}"] = round(100 * float(np.mean([np.mean(np.abs(ht - x) <= tol) for x in allh])), 2)
    return out


def hold_minutes(baskets):
    return [(B["t1"] - B["t0"]) / MIN for B in baskets]


def entry_features(sym, times):
    """Đặc trưng bối cảnh tại thời điểm vào (mảng ms) cho 1 mã, dùng nến 1m ĐÃ ĐÓNG trước đó: lợi suất k phút / (ATR%(1h) x sqrt(k/60)) (có dấu dương = tăng),
    khoảng cách tới VWAP ngày (/ATR%), tới EMA20 15m (/ATR%), vị trí trong biên độ 24h (0=đáy,1=đỉnh). Trả dict tên -> mảng."""
    a = candle_arrays(sym); t = np.asarray(times, np.int64)
    i = np.searchsorted(a["t"], t, side="right") - 2           # nến 1m đã đóng cuối cùng trước t (bỏ nến đang chạy)
    i = np.clip(i, 1500, len(a["t"]) - 1)
    atr = sim.atr_scale(sym)[i]; c = a["c"]
    out = {}
    for k in (15, 60, 240, 1440):
        out[f"ret{k}m"] = (c[i] / c[i - k] - 1) * 100 / (atr * np.sqrt(k / 60.0))
    vw = vwap_day(sym); out["dist_vwap"] = (c[i] / vw[i] - 1) * 100 / atr
    g = _tf_frame(sym, 15); e = g["c"].ewm(span=20, adjust=False).mean()
    j = np.clip(np.searchsorted(g["t_end"].values, a["t"][i], side="right") - 1, 0, len(e) - 1)
    out["dist_ema20_15m"] = (c[i] / e.values[j] - 1) * 100 / atr
    hi24 = pd.Series(a["h"]).rolling(1440, min_periods=200).max().values; lo24 = pd.Series(a["l"]).rolling(1440, min_periods=200).min().values
    out["pos_in_24h_range"] = (c[i] - lo24[i]) / np.maximum(hi24[i] - lo24[i], 1e-12)
    return out


def rand_exit_baseline(baskets, hold_train_min, reps=200, seed=0):
    """Baseline Level A: cùng fill đầu thật, thoát = time-stop tại thời gian giữ rút NGẪU NHIÊN từ phân bố giữ của TRAIN (độc lập với giá).
    Trả mean/p95 (qua reps lần) của close_match_15/60 (%), pnl_corr, sign_agree (%), sim_pnl_sum; cho biết 'điểm trùng hợp' khi chỉ biết phân bố thời gian giữ."""
    rng = np.random.default_rng(seed)
    ht = np.maximum(1, np.asarray(hold_train_min, float)).astype(int)
    ar = np.array([B["ret"] for B in baskets]); t1 = np.array([B["t1"] for B in baskets]); t0 = np.array([B["fills"][0]["t"] for B in baskets])
    res = []
    for _ in range(reps):
        c15 = c60 = 0; sr = []
        for k, B in enumerate(baskets):
            h = int(rng.choice(ht))
            S = simulate2(B, dict(maxhold=h))
            if S is None:
                sr.append(0.0); continue
            ct = max(c["t"] for c in S["closes"]); dt = abs(ct - t1[k]) / MIN if S["closed"] else np.inf
            c15 += dt <= 15; c60 += dt <= 60; sr.append(S["ret"])
        sr = np.array(sr)
        corr = float(np.corrcoef(ar, sr)[0, 1]) if sr.std() > 0 else 0.0
        res.append((100 * c15 / len(baskets), 100 * c60 / len(baskets), corr, 100 * float(np.mean(np.sign(ar) == np.sign(sr))), float(pd.Series(ar).rank().corr(pd.Series(sr).rank()))))
    res = np.array(res); nm = ["close_match_15", "close_match_60", "pnl_corr", "pnl_sign_agree", "ret_spearman"]
    return {k: dict(mean=round(float(res[:, i].mean()), 3), p95=round(float(np.percentile(res[:, i], 95)), 3)) for i, k in enumerate(nm)}
