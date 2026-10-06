"""Họ mô hình cho 3 bot "săn cú lớn / swing": Faithful-Punk-Fuse, Firsthand-ATL-Pansy, Physical-Epoch-Fuel.

Khác harness 01pp (rổ DCA hai chiều): ba bot này là LỆNH ĐỊNH HƯỚNG, thêm lệnh = nhồi/chia lệnh, thoát theo từng lệnh hoặc theo cụm.
Nên đơn vị so khớp là UNIT = một tranche vào lệnh (các sub-position cùng (mã,chiều) mở cách nhau <=15 phút) cùng các lệnh đóng của chính nó.
  - Level A (thoát): điều kiện hoá theo fill đầu thật của unit, mô phỏng luật thoát -> khớp giờ đóng/giá/PnL (match.level_a, schema như 01pp).
  - Level B (vào): tín hiệu vào lệnh sinh từ luật (không dùng nhãn) so với thời điểm vào thật (match.level_b + baseline ngẫu nhiên).
  - Add/nhồi: luật thêm lệnh khi đang có vị thế thật (điều kiện hoá theo trạng thái thật), baseline ngẫu nhiên TRONG cửa sổ đang mở.
Không look-ahead: mọi đặc trưng tính trên nến 5m/1h ĐÃ ĐÓNG tại thời điểm quyết định.
Giá trong nến 1m: O -> cực bất lợi -> cực có lợi -> C (worst-case, như sim.py). Phí 3.5 bps/chiều. Không funding.
"""
import os, sys, math
import numpy as np
import pandas as pd
from numba import njit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import load, match, sim

MIN = 60_000
H = 3_600_000
DAY = 24 * H


# ---------------------------------------------------------------- UNIT (tranche) baskets
def build_units(bot, gap_ms=15 * MIN):
    """Mỗi UNIT = tranche: các sub-position cùng (sym,side) mở liên tiếp cách <=gap_ms. Closes là của chính các sub-position đó.
    Cùng schema basket của load.build_baskets (fills/closes/tranches/ret/pnl...) để dùng lại match.basket_row/level_a."""
    byk = {}
    for t in bot["trades"]:
        byk.setdefault((t["sym"], t["side"]), []).append(t)
    units = []
    for (sym, side), arr in byk.items():
        arr = sorted(arr, key=lambda x: x["o"])
        grp = []
        for t in arr:
            if grp and t["o"] - grp[-1]["items"][-1]["o"] <= gap_ms:
                grp[-1]["items"].append(t)
            else:
                grp.append(dict(items=[t]))
        for g in grp:
            fills, closes = [], []
            for i, t in enumerate(g["items"]):
                notional = t["mg"] * t["lev"]
                if notional <= 0:
                    continue
                fills.append(dict(t=t["o"], px=t["po"], notional=notional, qty=notional / t["po"], mg=t["mg"], lev=t["lev"]))
                closes.append(dict(t=t["c"], px=t["pc"], qty=notional / t["po"], fill=len(fills) - 1, pnl=t["pnl"]))
            if not fills:
                continue
            qty = sum(f["qty"] for f in fills)
            notional = sum(f["notional"] for f in fills)
            pnl = sum(c["pnl"] for c in closes)
            u = dict(sym=sym, side=side, lev=float(np.median([f["lev"] for f in fills])), fills=fills, closes=closes, t0=fills[0]["t"],
                     t1=max(c["t"] for c in closes), notional=notional, avg_px=sum(f["px"] * f["qty"] for f in fills) / qty, pnl=pnl,
                     ret=pnl / notional * 100)
            u["tranches"] = load.collapse(fills)
            units.append(u)
    units.sort(key=lambda u: (u["t0"], u["sym"]))
    for i, u in enumerate(units):
        u["id"] = i
    return units


def mark_adds(units):
    """is_add: unit mở khi còn unit khác cùng (sym,side) đang mở (nhồi / thêm lệnh) -> khác 'vào mới' (flat -> mở).
    Gán thêm u['prior'] = list unit đang mở tại t0 và u['pos_t0'] = thời điểm mở của chuỗi vị thế (cluster overlap) chứa unit."""
    for u in units:
        op = [v for v in units if v is not u and v["sym"] == u["sym"] and v["side"] == u["side"] and v["t0"] < u["t0"] < v["t1"]]
        u["is_add"] = len(op) > 0
        u["n_open_before"] = len(op)
    return units


# ---------------------------------------------------------------- bảng đặc trưng (lưới 5m, chỉ nến đã đóng)
_PANEL = {}
M5 = 5 * MIN


def panel(sym):
    """DataFrame đặc trưng tại thời điểm ĐÓNG nến 5m, index = t_close (ms). Đặc trưng chuẩn hoá theo từng mã (không look-ahead:
    chỉ dùng cửa sổ quá khứ đã đóng). Cột:
      r1h,r4h,r24h  % thay đổi;  z1h,z4h,z24h = r / (std 5m-return rolling 7d x sqrt(n))   (đơn vị sigma)
      d_ema20,d_ema50,d_ema200 : (close - EMA1h)/ATR1h  (EMA/ATR trên nến 1h đã đóng, dịch 1h)
      rsi : RSI(14) nến 1h đã đóng
      pos24 : vị trí trong biên 24h [0,1];   brk24,brk72,brk168 : close vượt đỉnh N giờ TRƯỚC (đỉnh trước đó, không gồm hiện tại) -> 1/0 ;
      sweep24 : low 1h gần nhất < đáy 24h trước đó VÀ close>đáy đó (nhịp quét đáy) ; atr_pct : ATR1h/close %
      rd : khoảng cách tới mức tròn gần nhất (theo bội ATR1h)  [xem round_unit]
    """
    if sym in _PANEL:
        return _PANEL[sym]
    a = load.candle_arrays(sym)
    if a is None:
        _PANEL[sym] = None; return None
    idx = pd.to_datetime(a["t"], unit="ms")
    df = pd.DataFrame(dict(o=a["o"], h=a["h"], l=a["l"], c=a["c"], v=a["v"]), index=idx)
    b5 = df.resample("5min").agg(dict(o="first", h="max", l="min", c="last", v="sum")).dropna()
    f = pd.DataFrame(index=b5.index)
    c = b5.c
    f["c"] = c; f["h"] = b5.h; f["l"] = b5.l
    for nm, n in (("1h", 12), ("4h", 48), ("24h", 288)):
        f["r" + nm] = (c / c.shift(n) - 1) * 100
    r5 = np.log(c).diff()
    sd = r5.rolling(2016, min_periods=288).std()
    for nm, n in (("1h", 12), ("4h", 48), ("24h", 288)):
        f["z" + nm] = np.log(c / c.shift(n)) / (sd * math.sqrt(n))
    # 1h
    h1 = df.resample("1h").agg(dict(o="first", h="max", l="min", c="last")).dropna()
    pc = h1.c.shift(1)
    tr = pd.concat([h1.h - h1.l, (h1.h - pc).abs(), (h1.l - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14, min_periods=6).mean()
    # giá trị 1h dùng được từ 1h sau (đã đóng): dịch index +1h rồi ffill sang lưới 5m (t_close của 5m = index+5m)
    def to5(s):
        s = s.copy(); s.index = s.index + pd.Timedelta(hours=1)
        return s.reindex(f.index.union(s.index)).ffill().reindex(f.index)
    atr5 = to5(atr)
    for n in (20, 50, 200):
        ema = h1.c.ewm(span=n, adjust=False, min_periods=n // 2).mean()
        f[f"d_ema{n}"] = (c - to5(ema)) / atr5
    d = h1.c.diff(); up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    f["rsi"] = to5(100 - 100 / (1 + up / dn.replace(0, np.nan)))
    f["atr_pct"] = atr5 / c * 100
    # đỉnh/đáy N giờ trước (trên lưới 5m, loại nến hiện tại)
    hh = b5.h.shift(1); ll = b5.l.shift(1)
    for nm, n in (("24", 288), ("72", 864), ("168", 2016)):
        hi = hh.rolling(n, min_periods=n // 2).max(); lo = ll.rolling(n, min_periods=n // 2).min()
        f["hi" + nm] = hi; f["lo" + nm] = lo
        f["brk" + nm] = (c > hi).astype(float)
        f["pos" + nm] = (c - lo) / (hi - lo)
    # nhịp quét: trong 1h gần nhất có low < đáy 24h (tính đến 1h trước) mà close hiện tại > đáy đó
    lo_prev = b5.l.shift(12).rolling(288, min_periods=144).min()
    low1h = b5.l.rolling(12).min()
    f["sweep24"] = ((low1h < lo_prev) & (c > lo_prev)).astype(float)
    f["t_close"] = (f.index.astype("int64") // 10**6 + M5).astype(np.int64)
    f = f.dropna(subset=["z24h", "d_ema200", "rsi", "pos24"])
    f = f.set_index("t_close", drop=False)
    _PANEL[sym] = f
    return f


FEATS = ["z1h", "z4h", "z24h", "d_ema20", "d_ema50", "d_ema200", "rsi", "pos24", "pos72", "pos168", "brk24", "brk72", "brk168", "sweep24", "atr_pct"]


def feat_at(sym, t):
    """Hàng đặc trưng của nến 5m ĐÓNG gần nhất <= t (không look-ahead), hoặc None."""
    f = panel(sym)
    if f is None:
        return None
    i = int(np.searchsorted(f.index.values, t, side="right")) - 1
    return None if i < 0 else f.iloc[i]


# ---------------------------------------------------------------- mảng căn theo nến 1m cho thoát chỉ báo
_ALIGN = {}


def aligned(sym):
    """Mảng theo nến 1m (chỉ dùng giờ ĐÃ ĐÓNG): atr_pct, ema20, ema50, rsi (nến 1h), hour UTC, minute. Giá trị tại nến 1m i dùng các giờ <= giờ(i)-1."""
    if sym in _ALIGN:
        return _ALIGN[sym]
    a = load.candle_arrays(sym)
    if a is None:
        _ALIGN[sym] = None; return None
    idx = pd.to_datetime(a["t"], unit="ms")
    df = pd.DataFrame(dict(h=a["h"], l=a["l"], c=a["c"]), index=idx)
    h1 = df.resample("1h").agg(dict(h="max", l="min", c="last")).dropna()
    def m(s):
        return pd.Series(s.shift(1).reindex(idx.floor("1h")).values).ffill().bfill().values.astype(np.float64)
    pc = h1.c.shift(1)
    tr = pd.concat([h1.h - h1.l, (h1.h - pc).abs(), (h1.l - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14, min_periods=6).mean() / h1.c * 100
    d = h1.c.diff(); up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    out = dict(atr=m(atr), ema20=m(h1.c.ewm(span=20, adjust=False, min_periods=10).mean()), ema50=m(h1.c.ewm(span=50, adjust=False, min_periods=25).mean()),
               rsi=m(rsi), hr=idx.hour.values.astype(np.int64), mn=idx.minute.values.astype(np.int64))
    _ALIGN[sym] = out
    return out


# ---------------------------------------------------------------- kernel thoát (1 vị thế, đã vào)
EXIT_DEFAULT = dict(tp=0.0, tp_mode=0, sl=0.0, sl_mode=0, tr_act=0.0, tr_dist=0.0, tr_mode=0, hold_min=0, ema_mode=0, ema_buf=0.0, min_hold_min=0,
                    rsi_lvl=0.0, tp_abs=0.0, sess_hr=-1, sess_min_hold_h=0, sl_abs=0.0)
_EK = ["tp", "tp_mode", "sl", "sl_mode", "tr_act", "tr_dist", "tr_mode", "hold_min", "ema_mode", "ema_buf", "min_hold_min", "rsi_lvl", "tp_abs", "sess_hr",
       "sess_min_hold_h", "sl_abs"]


def evec(p):
    q = dict(EXIT_DEFAULT); q.update(p)
    return np.array([float(q[k]) for k in _EK], dtype=np.float64)


@njit(cache=True)
def _exit_run(o, h, l, c, atr, ema20, ema50, rsi, hr, mn, i0, i_end, s, p0, P):
    """Trả (bar_đóng, giá_đóng, closed). Thứ tự trong nến: thoát đầu nến (time-stop/chỉ báo/phiên) -> cực bất lợi (SL/trailing) -> cực có lợi (TP)."""
    tp = P[0]; tpm = int(P[1]); sl = P[2]; slm = int(P[3]); tra = P[4]; trd = P[5]; trm = int(P[6]); hold = int(P[7]); em = int(P[8]); ebuf = P[9]
    minh = int(P[10]); rl = P[11]; tpa = P[12]; sh = int(P[13]); shm = int(P[14]) * 60; sla = P[15]
    atr_abs = atr[i0] / 100.0 * p0
    pct_tp = 0.0; pct_sl = 0.0
    T = np.nan; Lsl = np.nan
    if tpm == 1: T = p0 * (1.0 + s * tp / 100.0)
    elif tpm == 2: T = p0 + s * tp * atr_abs
    if tpa > 0: T = tpa
    if slm == 1: Lsl = p0 * (1.0 - s * sl / 100.0)
    elif slm == 2: Lsl = p0 - s * sl * atr_abs
    if sla > 0: Lsl = sla
    ext = p0; trail_on = False
    for i in range(i0 + 1, i_end + 1):
        o_ = o[i]; adv = l[i] if s == 1 else h[i]; fav = h[i] if s == 1 else l[i]
        k = i - i0
        if hold > 0 and k >= hold: return i, o_, 1
        if k >= minh:
            if mn[i] == 0:
                if em > 0:
                    e = ema20[i] if em == 1 else ema50[i]
                    if s * (c[i - 1] - (e + s * 0.0)) < -ebuf * atr[i] / 100.0 * c[i - 1]: return i, o_, 1
                if rl > 0:
                    if s == 1 and rsi[i] >= rl: return i, o_, 1
                    if s == -1 and rsi[i] <= 100.0 - rl: return i, o_, 1
        if sh >= 0 and k >= shm and hr[i] == sh and mn[i] == 0: return i, o_, 1
        if trail_on:
            dist = trd / 100.0 * ext if trm == 1 else trd * atr_abs
            stp = ext - s * dist
            if s * (adv - stp) <= 0:
                return i, (stp if s * (o_ - stp) > 0 else o_), 1
        if not np.isnan(Lsl) and s * (adv - Lsl) <= 0:
            return i, (Lsl if s * (o_ - Lsl) > 0 else o_), 1
        if not np.isnan(T) and s * (fav - T) >= 0:
            return i, (o_ if s * (o_ - T) >= 0 else T), 1
        if trm > 0:
            if s * (fav - ext) > 0: ext = fav
            gain = s * (ext - p0)
            need = tra / 100.0 * p0 if trm == 1 else tra * atr_abs
            if gain >= need: trail_on = True
    return i_end, c[i_end], 0


def round_level(p0, s, atr_abs, k):
    """Mức tròn đầu tiên cách giá vào >= k x ATR theo chiều có lợi. Bước tròn = 1/2/5 x 10^n gần 0.5 x ATR nhất (mức 'đẹp' theo thang giá)."""
    raw = max(atr_abs * 0.5, p0 * 1e-4)
    e = 10 ** math.floor(math.log10(raw))
    step = min((1, 2, 5, 10), key=lambda m: abs(m * e - raw)) * e
    tgt = p0 + s * k * atr_abs
    return (math.ceil(tgt / step) * step) if s == 1 else (math.floor(tgt / step) * step)


def _unit_result(u, tcl, px, closed, fee_bps=3.5):
    s = 1 if u["side"] == "long" else -1
    fee = fee_bps / 1e4
    fills = [dict(t=int(f["t"]), px=float(f["px"]), notional=float(f["notional"]), layer=k) for k, f in enumerate(u["fills"])]
    closes = [dict(t=int(tcl), px=float(px), qty=float(f["qty"]), layer=k) for k, f in enumerate(u["fills"])]
    pnl = sum(f["qty"] * (px - f["px"]) * s - fee * f["qty"] * (px + f["px"]) for f in u["fills"])
    notional = float(sum(f["notional"] for f in u["fills"]))
    return dict(fills=fills, closes=closes, closed=bool(closed), pnl=float(pnl), notional=notional, ret=float(pnl / notional * 100))


def simulate_unit(u, params, horizon_min=60, a=None, al=None, fee_bps=3.5):
    """Mô phỏng thoát cho 1 unit, điều kiện hoá theo fill thật (tất cả fill của unit coi là 1 vị thế tại avg_px). Trả dict kiểu sim.simulate.
    params có 'pf_kind' -> thoát CẤP DANH MỤC (xem pf_*), ngược lại thoát theo từng lệnh (kernel _exit_run)."""
    if "pf_kind" in params:
        return _simulate_unit_pf(u, params, horizon_min, a, fee_bps)
    sym = u["sym"]; a = a or load.candle_arrays(sym); al = al or aligned(sym)
    if a is None:
        return None
    f0 = u["fills"][0]
    i0 = int(np.searchsorted(a["t"], f0["t"], side="right")) - 1
    i_end = min(len(a["t"]) - 1, int(np.searchsorted(a["t"], u["t1"] + horizon_min * MIN, side="right")) - 1)
    if i0 < 0 or i_end <= i0:
        return None
    s = 1 if u["side"] == "long" else -1
    p = dict(params)
    p0 = u["avg_px"]
    if p.pop("roi", 0):   # tp/sl cho theo ROI trên ký quỹ (%) -> đổi sang % giá = ROI / đòn bẩy
        for k_ in ("tp", "sl", "tr_act", "tr_dist"):
            if k_ in p: p[k_] = p[k_] / max(1.0, u["lev"])
    if p.get("round_k", 0) > 0:
        p["tp_abs"] = round_level(p0, s, al["atr"][i0] / 100 * p0, p["round_k"])
    P = evec(p)
    bar, px, closed = _exit_run(a["o"], a["h"], a["l"], a["c"], al["atr"], al["ema20"], al["ema50"], al["rsi"], al["hr"], al["mn"], i0, i_end, s, p0, P)
    return _unit_result(u, int(a["t"][bar]), px, closed, fee_bps)


# ---------------------------------------------------------------- suy luận từ dữ liệu (mô tả, không fit)
def _q(a, qs=(10, 25, 50, 75, 90)):
    a = np.asarray(a, float)
    return [] if len(a) == 0 else [round(float(x), 3) for x in np.percentile(a, qs)]


def unit_excursions(u):
    """MFE/MAE (% giá, theo chiều lệnh) từ fill đầu tới lần đóng cuối, trên nến 1m. Trả (mfe, mae(>=0 là bất lợi), thời điểm mae, thời điểm mfe)."""
    a = load.candle_arrays(u["sym"]); s = 1 if u["side"] == "long" else -1
    i0, i1 = load.window(a, u["t0"], u["t1"])
    if i1 <= i0:
        return 0.0, 0.0, u["t0"], u["t0"]
    adv = a["l"][i0:i1] if s == 1 else a["h"][i0:i1]
    fav = a["h"][i0:i1] if s == 1 else a["l"][i0:i1]
    mae = max(0.0, -s * (adv.min() if s == 1 else adv.max()) / u["avg_px"] * 1 + s * 1.0 * 0) if False else None
    if s == 1:
        mae = (1 - adv.min() / u["avg_px"]) * 100; mfe = (fav.max() / u["avg_px"] - 1) * 100
        tmae = int(a["t"][i0 + int(np.argmin(adv))]); tmfe = int(a["t"][i0 + int(np.argmax(fav))])
    else:
        mae = (adv.max() / u["avg_px"] - 1) * 100; mfe = (1 - fav.min() / u["avg_px"]) * 100
        tmae = int(a["t"][i0 + int(np.argmax(adv))]); tmfe = int(a["t"][i0 + int(np.argmin(fav))])
    return float(mfe), float(mae), tmae, tmfe


def exit_stats(u):
    """Lợi suất thoát (% từ avg, bội ATR1h tại vào, hold giờ) tính trên lần đóng cuối."""
    s = 1 if u["side"] == "long" else -1
    last = u["t1"]; cl = [c for c in u["closes"] if abs(c["t"] - last) <= 2000] or u["closes"]
    pxc = sum(c["px"] * c["qty"] for c in cl) / sum(c["qty"] for c in cl)
    ret = (pxc / u["avg_px"] - 1) * s * 100
    a = load.candle_arrays(u["sym"]); al = aligned(u["sym"])
    i0 = int(np.searchsorted(a["t"], u["t0"], side="right")) - 1
    atr = float(al["atr"][i0])
    return dict(ret_pct=ret, atr_pct=atr, ret_atr=ret / atr, hold_h=(u["t1"] - u["t0"]) / H, win=ret > 0)


def infer_units(units, sym_side_note=None):
    """Bằng chứng mô tả cho 1 danh sách unit (dùng trên TRAIN khi cần fit; trên toàn bộ khi chỉ mô tả)."""
    st = [exit_stats(u) for u in units]
    ex = [unit_excursions(u) for u in units]
    win = np.array([x["win"] for x in st]); ret = np.array([x["ret_pct"] for x in st]); ra = np.array([x["ret_atr"] for x in st])
    hold = np.array([x["hold_h"] for x in st]); lev = np.array([u["lev"] for u in units])
    mae = np.array([e[1] for e in ex]); mfe = np.array([e[0] for e in ex])
    # khoảng cách thanh lý nếu isolated ~ (1/lev - 0.5%/duy trì) xấp xỉ 100/lev - 0.4 (%)
    liq = 100.0 / lev - 0.4
    # PnL / ký quỹ danh nghĩa (mg): thua >100% => chắc chắn cross (vì mg chỉ là danh nghĩa)
    loss_over_mg = np.array([(-u["pnl"] / sum(f["mg"] for f in u["fills"]) * 100) for u in units])
    # đóng cùng giây giữa các unit khác nhau (batch)
    ends = sorted(u["t1"] for u in units)
    batch = sum(1 for u in units if sum(1 for v in units if v is not u and abs(v["t1"] - u["t1"]) <= 60_000) > 0)
    # giờ đóng (UTC)
    ch = np.bincount(((np.array([u["t1"] for u in units]) // H) % 24).astype(int), minlength=24).tolist()
    oh = np.bincount(((np.array([u["t0"] for u in units]) // H) % 24).astype(int), minlength=24).tolist()
    return dict(
        n_units=len(units), n_win=int(win.sum()), win_pct=round(100 * float(win.mean()), 1),
        win_ret_pct_q=_q(ret[win]), loss_ret_pct_q=_q(ret[~win]), win_ret_atr_q=_q(ra[win]), loss_ret_atr_q=_q(ra[~win]),
        hold_h_win_q=_q(hold[win]), hold_h_loss_q=_q(hold[~win]), hold_h_all_q=_q(hold),
        mae_pct_q=_q(mae), mfe_pct_q=_q(mfe), mae_win_pct_q=_q(mae[win]),
        n_mae_beyond_isolated_liq=int((mae > liq).sum()), n_win_mae_beyond_isolated_liq=int(((mae > liq) & win).sum()),
        liq_dist_pct_q=_q(liq), loss_over_margin_pct_q=_q(loss_over_mg[~win]) if (~win).any() else [], max_loss_over_margin_pct=round(float(loss_over_mg.max()), 1),
        n_loss_ge_100pct_margin=int((loss_over_mg >= 99).sum()),
        pct_units_closed_within60s_of_other_unit=round(100 * batch / len(units), 1),
        close_hour_utc=ch, open_hour_utc=oh, lev_q=_q(lev, (0, 50, 100)),
    )


# ---------------------------------------------------------------- LEVEL B: tín hiệu vào lệnh
def nice_step(atr_abs, k):
    raw = max(atr_abs * k, 1e-12)
    e = 10 ** math.floor(math.log10(raw))
    return min((1, 2, 5, 10), key=lambda m: abs(m * e - raw)) * e


_SIGCACHE = {}
SESS = {"SKHYNIX": list(range(0, 7)), "SNDK": list(range(13, 21)), "MU": list(range(13, 21)), "MSTR": list(range(13, 21)), "SPCX": list(range(13, 21)),
        "TSLA": list(range(13, 21)), "INTC": list(range(13, 21)), "SOXL": list(range(13, 21))}


def signals(sym, side, rule):
    """Thời điểm (ms, đóng nến 5m) luật `rule` bắn tín hiệu cho (sym, side). Cạnh lên + cooldown.
    rule: dict(kind, thr, n, cool_h, gate(list giờ UTC|None), up(ngưỡng xu hướng cho 'pull'))
      pull   : long khi d_ema200 > up (xu hướng lên) VÀ d_ema20 <= -thr (hồi về EMA20);  short đối xứng        [thuận xu hướng, mua nhịp hồi]
      contra : long khi z{n}h <= -thr (sau nhịp giảm thr sigma), short khi >= +thr                              [ngược đà]
      mom    : long khi z{n}h >= +thr, short khi <= -thr                                                         [theo đà]
      brk    : long khi close vượt đỉnh n giờ trước (n=24/72/168), short khi thủng đáy                          [phá vỡ]
      sweep  : long khi quét đáy 24h rồi đóng trên đáy (nhịp quét), short đối xứng                              [nhịp quét]
      rsi    : long khi RSI1h <= 50-thr; short khi >= 50+thr
      level  : long khi giá chạm XUỐNG mức tròn (bước = nice(thr x ATR1h)), short khi chạm LÊN                   [limit tại mức tròn]
      pos    : long khi vị trí trong biên 24h <= thr, short khi >= 1-thr
      hour   : chỉ cổng giờ (mỗi lần vào cửa sổ giờ, cooldown) - baseline 'chỉ giờ'
    """
    key = (sym, side, tuple(sorted((k, str(v)) for k, v in rule.items())))
    if key in _SIGCACHE:
        return _SIGCACHE[key]
    f = panel(sym)
    if f is None:
        return np.zeros(0, np.int64)
    k = rule["kind"]; thr = rule.get("thr", 0); L = side == "long"
    if k == "pull":
        up = rule.get("up", 0.0)
        cond = ((f["d_ema200"] > up) & (f["d_ema20"] <= -thr)) if L else ((f["d_ema200"] < -up) & (f["d_ema20"] >= thr))
    elif k in ("contra", "mom"):
        x = f["z%dh" % rule["n"]]
        lo, hi = (x <= -thr), (x >= thr)
        if k == "mom": lo, hi = hi, lo
        cond = lo if L else hi
    elif k == "brk":
        n = rule["n"]
        cond = (f["c"] > f["hi%d" % n]) if L else (f["c"] < f["lo%d" % n])
    elif k == "sweep":
        lo_prev = f["l"].shift(12).rolling(288, min_periods=144).min(); hi_prev = f["h"].shift(12).rolling(288, min_periods=144).max()
        if L: cond = (f["l"].rolling(12).min() < lo_prev) & (f["c"] > lo_prev)
        else: cond = (f["h"].rolling(12).max() > hi_prev) & (f["c"] < hi_prev)
    elif k == "rsi":
        cond = (f["rsi"] <= 50 - thr) if L else (f["rsi"] >= 50 + thr)
    elif k == "pos":
        cond = (f["pos24"] <= thr) if L else (f["pos24"] >= 1 - thr)
    elif k == "level":
        atr_abs = (f["atr_pct"] / 100 * f["c"]).values
        # bước tròn theo mã: lấy trung vị ATR toàn mẫu (ổn định, không look-ahead đáng kể) -> 1 bước cố định cho mã
        step = nice_step(float(np.nanmedian(atr_abs)), thr)
        c = f["c"].values; lo_ = f["l"].values; hi_ = f["h"].values
        pc = np.r_[np.nan, c[:-1]]
        if L: cond = pd.Series((np.floor(pc / step) * step <= pc) & (lo_ <= np.floor(pc / step) * step) & (pc > np.floor(pc / step) * step), index=f.index)
        else: cond = pd.Series((hi_ >= np.ceil(pc / step) * step) & (pc < np.ceil(pc / step) * step), index=f.index)
    elif k == "hour":
        cond = pd.Series(True, index=f.index)
    else:
        raise ValueError(k)
    cond = cond.values.astype(bool)
    if rule.get("and_contra") is not None:   # điều kiện phụ: sau nhịp giảm (long) / tăng (short) >= and_contra sigma trong 4h
        z4 = f["z%dh" % rule.get("and_n", 4)].values
        cond = cond & ((z4 <= -rule["and_contra"]) if L else (z4 >= rule["and_contra"]))
    if rule.get("vol") is not None:   # cổng biến động: ATR%(1h) >= phân vị `vol` của chính mã (đặc trưng chuẩn hoá theo mã, không dùng nhãn)
        cond = cond & (f["atr_pct"].values >= float(np.quantile(f["atr_pct"].values, rule["vol"])))
    g = rule.get("gate")
    if g == "sess":   # phiên giao dịch của tài sản cơ sở: cổ phiếu Mỹ 13-20h UTC (mở 13:30), SK Hynix (KRX) 0-6h UTC; crypto không cổng
        g = SESS.get(sym)
    if g is not None:
        hrs = ((f["t_close"].values // H) % 24).astype(int)
        cond = cond & np.isin(hrs, g)
    edge = cond & ~np.r_[False, cond[:-1]]
    t = f["t_close"].values[edge]
    cool = rule.get("cool_h", 6) * H
    keep = []; last = -10**18
    for ti in t:
        if ti - last >= cool:
            keep.append(ti); last = ti
    out = np.array(keep, dtype=np.int64)
    _SIGCACHE[key] = out
    return out


def sig_dict(keys, rule, lo, hi):
    out = {}
    for (sym, side) in keys:
        t = signals(sym, side, rule)
        t = t[(t >= lo) & (t <= hi)]
        if len(t):
            out[(sym, side)] = t
    return out


def act_dict(units, sel=None):
    d = {}
    for u in units:
        if sel is not None and not sel(u):
            continue
        d.setdefault((u["sym"], u["side"]), []).append(u["t0"])
    return {k: np.array(sorted(v), np.int64) for k, v in d.items()}


# ---------------------------------------------------------------- Level B: bảng luật + LOO + walk-forward
def _masks(events, sig, tol):
    """events: list[(key,t)] đã đánh số k. sig: {key: mảng t}. Trả hit_event bool[n], sig_t[], sig_mask uint64[] (bit k = tín hiệu nằm trong +-tol của event k)."""
    n = len(events)
    hit = np.zeros(n, bool)
    ts_, ms_ = [], []
    for key, s in sig.items():
        ev = [(k, t) for k, (kk, t) in enumerate(events) if kk == key]
        m = np.zeros(len(s), np.uint64)
        for k, t in ev:
            i0 = np.searchsorted(s, t - tol, side="left"); i1 = np.searchsorted(s, t + tol, side="right")
            if i1 > i0:
                hit[k] = True; m[i0:i1] |= np.uint64(1 << k)
        ts_.append(s); ms_.append(m)
    # event có key không có tín hiệu: hit False (đã mặc định)
    return hit, (np.concatenate(ts_) if ts_ else np.zeros(0, np.int64)), (np.concatenate(ms_) if ms_ else np.zeros(0, np.uint64))


def _f1(r, p):
    return 0.0 if r + p == 0 else 2 * r * p / (r + p)


def _analytic_base(act, sig, lo, hi, tol):
    """Kỳ vọng recall/precision nếu tín hiệu rải ĐỀU ngẫu nhiên trên [lo,hi] cho từng khoá: recall = TB_event (1-(1-2tol/W)^n_sig_khoá); precision = TB_tín_hiệu min(1, n_event_khoá x 2tol/W)."""
    W = float(hi - lo); p = min(1.0, 2.0 * tol / W)
    na = sum(len(v) for v in act.values()); ns = sum(len(v) for v in sig.values())
    rec = sum(len(v) * (1 - (1 - p) ** len(sig.get(k, ()))) for k, v in act.items()) / max(1, na)
    prec = sum(len(v) * min(1.0, len(act.get(k, ())) * p) for k, v in sig.items()) / max(1, ns)
    return rec, prec


def rule_table(keys, rules, units_all, lo, hi, hh, split_t, entries=None, reps=30, tols_mask=(15, 240)):
    """Với mỗi luật: chỉ số TRAIN (match.level_b) + TOÀN MẪU, mặt nạ cho LOO/walk-forward ở mỗi tol trong tols_mask.
    entries: lọc unit tính là 'sự kiện vào' (mặc định mọi unit)."""
    sel = units_all if entries is None else [u for u in units_all if entries(u)]
    ev_sorted = sorted((((u["sym"], u["side"]), u["t0"]) for u in sel), key=lambda x: x[1])
    act_all = {}
    for k, t in ev_sorted: act_all.setdefault(k, []).append(t)
    act_all = {k: np.array(v, np.int64) for k, v in act_all.items()}
    act_tr = {k: v[v < split_t] for k, v in act_all.items() if (v < split_t).any()}
    act_te = {k: v[v >= split_t] for k, v in act_all.items() if (v >= split_t).any()}
    TOLS = (15, 60, 240)
    table = []
    for r in rules:
        sg_all = sig_dict(keys, r, lo, hi)
        sg_tr = {k: v[v < split_t] for k, v in sg_all.items() if (v < split_t).any()}
        sg_te = {k: v[v >= split_t] for k, v in sg_all.items() if (v >= split_t).any()}
        m_tr = match.level_b(act_tr, sg_tr, lo, split_t, reps=reps, seed=1, tols=TOLS, hour_hist=hh) if act_tr else None
        m_all = match.level_b(act_all, sg_all, lo, hi, reps=reps, seed=4, tols=TOLS, hour_hist=hh)
        masks = {tol: _masks(ev_sorted, sg_all, tol * MIN) for tol in tols_mask}
        base = {}
        for tol in TOLS:   # baseline = max(MC khớp giờ, giải tích đều) - MC với ít tín hiệu hay cho 0 -> p-value giả
            ar, ap = _analytic_base(act_all, sg_all, lo, hi, tol * MIN)
            base[tol] = (max(m_all["rand_hour_recall_%d_mean" % tol], 100 * ar), max(m_all["rand_hour_precision_%d_mean" % tol], 100 * ap))
        table.append(dict(rule=r, train=m_tr, all=m_all, masks=masks, base=base, n_sig=int(sum(len(v) for v in sg_all.values())), _sg_te=sg_te))
    return table, ev_sorted, act_tr, act_te


def f1_excess_b(m, tol=15):
    """F1(+-tol) trừ F1 kỳ vọng của baseline ngẫu nhiên khớp giờ."""
    if m is None: return -9.0
    k = "rand_hour" if f"rand_hour_recall_{tol}_mean" in m else "rand"
    return _f1(m[f"recall_{tol}"], m[f"precision_{tol}"]) - _f1(m[f"{k}_recall_{tol}_mean"], m[f"{k}_precision_{tol}_mean"])


def loo_rules(table, ev_sorted, tol=15):
    """Leave-one-event-out: với mỗi event e chọn luật tối đa F1-excess(+-tol) trên các event còn lại (tín hiệu chỉ gần e bị bỏ), chấm hit(e).
    So với kỳ vọng ngẫu nhiên = recall baseline (khớp giờ / trong cửa sổ mở) của chính luật được chọn."""
    n = len(ev_sorted); picks = []
    for e in range(n):
        best = None; be = np.uint64(1 << e)
        for j, row in enumerate(table):
            hit, st, mk = row["masks"][tol]
            rec = (hit.sum() - hit[e]) / max(1, n - 1)
            only_e = int((mk == be).sum()); denom = len(mk) - only_e
            prec = (int(((mk & ~be) != 0).sum()) / denom) if denom > 0 else 0.0
            br, bp = row["base"][tol]
            sc = _f1(rec, prec) - _f1(br / 100, bp / 100)
            if best is None or sc > best[0]: best = (sc, j)
        picks.append(best[1])
    hits = np.array([table[j]["masks"][tol][0][e] for e, j in enumerate(picks)])
    pr = np.array([table[j]["base"][tol][0] / 100 for j in picks])
    rng = np.random.default_rng(0)
    sim_ = (rng.random((20000, n)) < pr).sum(1)
    return dict(tol_min=tol, n=n, hits=int(hits.sum()), recall_loo=round(100 * float(hits.mean()), 1), expected_by_chance=round(100 * float(pr.mean()), 1),
                p_value=round(float((sim_ >= hits.sum()).mean()), 4), n_distinct_rules=len(set(picks)),
                top_picks=[table[j]["rule"] for j in sorted(set(picks), key=picks.count, reverse=True)[:3]])


def walk_forward_rules(table, ev_sorted, tol=15, min_train=6):
    """Mở rộng dần: tại event k (k>=min_train) chọn luật theo các event <k và tín hiệu có t < t_k, chấm hit(k)."""
    n = len(ev_sorted); res = []; pr = []
    if n <= min_train + 1:
        return dict(tol_min=tol, n=0, hits=0, recall_wf=None, expected_by_chance=None, p_value=None, note="quá ít event (%d) cho walk-forward" % n)
    for k in range(min_train, n):
        tk = ev_sorted[k][1]; keep = np.uint64((1 << k) - 1); best = None
        for j, row in enumerate(table):
            hit, st, mk = row["masks"][tol]
            sel = st < tk; ns = int(sel.sum())
            rec = hit[:k].mean()
            prec = (int(((mk[sel] & keep) != 0).sum()) / ns) if ns else 0.0
            br, bp = row["base"][tol]
            sc = _f1(rec, prec) - _f1(br / 100, bp / 100)
            if best is None or sc > best[0]: best = (sc, j)
        res.append(bool(table[best[1]]["masks"][tol][0][k])); pr.append(table[best[1]]["base"][tol][0] / 100)
    res = np.array(res); pr = np.array(pr)
    rng = np.random.default_rng(1)
    sim_ = (rng.random((20000, len(pr))) < pr).sum(1)
    return dict(tol_min=tol, n=int(len(res)), hits=int(res.sum()), recall_wf=round(100 * float(res.mean()), 1), expected_by_chance=round(100 * float(pr.mean()), 1),
                p_value=round(float((sim_ >= res.sum()).mean()), 4))


def entry_rules(gate, vols=(None, 0.6), extra_gates=()):
    R = []
    for cool in (6, 24, 72):
      for vol in vols:
        for g in (None, gate) + tuple(extra_gates):
            base = dict(cool_h=cool, gate=g, **({} if vol is None else dict(vol=vol)))
            for up in (0.0, 1.0):
                for thr in (0.5, 1.0, 2.0):
                    R.append(dict(kind="pull", thr=thr, up=up, **base))
            for kind in ("contra", "mom"):
                for n in (1, 4, 24):
                    for thr in (1.0, 1.5, 2.0, 2.5):
                        R.append(dict(kind=kind, thr=thr, n=n, **base))
            for n in (24, 72, 168):
                R.append(dict(kind="brk", n=n, **base))
            R.append(dict(kind="sweep", **base))
            for thr in (10, 15, 20):
                R.append(dict(kind="rsi", thr=thr, **base))
            for thr in (0.1, 0.2):
                R.append(dict(kind="pos", thr=thr, **base))
            for thr in (0.5, 1.0, 2.0):
                R.append(dict(kind="level", thr=thr, **base))
            for thr in (1.0, 2.0, 4.0):
                for ac in (0.5, 1.0):
                    R.append(dict(kind="level", thr=thr, and_contra=ac, **base))
            for thr in (1.5, 2.0, 2.5):          # đảo chiều có xác nhận: xung 1h CÙNG chiều lệnh sau nhịp 24h NGƯỢC chiều
                for ac in (0.5, 1.0):
                    R.append(dict(kind="mom", n=1, thr=thr, and_contra=ac, and_n=24, **base))
            if g is not None or vol is not None:
                R.append(dict(kind="hour", **base))
    return R


def rule_name(r):
    p = [r["kind"]] + [f"{k}={r[k]}" for k in ("n", "thr", "up", "and_contra", "and_n") if k in r] + [f"cool{r['cool_h']}h"]
    if r.get("vol") is not None: p.append("vol>=q%g" % r["vol"])
    if r.get("gate") == "sess": p.append("gate=session")
    elif r.get("gate") is not None: p.append("gate" + "-".join(map(str, [r["gate"][0], r["gate"][-1]])))
    return " ".join(p)


def train_gate(units_train, width=4):
    """Khung `width` giờ UTC dày nhất của sự kiện vào trong TRAIN (liên tục theo vòng)."""
    hrs = np.bincount(((np.array([u["t0"] for u in units_train]) // H) % 24).astype(int), minlength=24).astype(float)
    best = max(range(24), key=lambda s: sum(hrs[(s + i) % 24] for i in range(width)))
    return [(best + i) % 24 for i in range(width)]


def hour_hist_vn(units_train):
    hh = np.bincount(((np.array([u["t0"] for u in units_train]) // H + 7) % 24).astype(int), minlength=24).astype(float) + 0.5
    return hh / hh.sum()


# ---------------------------------------------------------------- LEVEL A: họ luật thoát + chọn tham số + LOO
def _grid(spec):
    import itertools
    keys = list(spec)
    return [dict(zip(keys, v)) for v in itertools.product(*[spec[k] for k in keys])]


def uq(a, ps=(25, 50, 75)):
    a = [abs(x) for x in a if x is not None and not np.isnan(x)]
    return sorted({round(float(x), 3) for x in np.percentile(a, ps)}) if a else []


def exit_grids(train):
    """Lưới tham số có cơ sở từ TRAIN (phân vị quan sát). Mỗi họ -> (tên, ghi chú, danh sách tham số)."""
    st = [exit_stats(u) for u in train]
    w = [x for x in st if x["win"]]; l = [x for x in st if not x["win"]]
    wp = uq([x["ret_pct"] for x in w]); lp = uq([x["ret_pct"] for x in l]) if l else [1.0]
    wa = uq([x["ret_atr"] for x in w]); la = uq([x["ret_atr"] for x in l]) if l else [2.0]
    hold_h = np.array([x["hold_h"] for x in st])
    hq = [max(1, int(round(h * 60))) for h in np.percentile(hold_h, [25, 50, 75])]
    ch = np.bincount(((np.array([u["t1"] for u in train]) // H) % 24).astype(int), minlength=24)
    top_hours = [int(h) for h in np.argsort(-ch)[:3]]
    G = []
    G.append(("X0_time_stop", "Mốc: time-stop tại phân vị 25/50/75 thời gian giữ của train (không dùng giá).", _grid(dict(hold_min=hq))))
    G.append(("X1_fixed_pct", "TP/SL cố định % từ giá TB (TP = phân vị lãi của lệnh thắng, SL = phân vị lỗ của lệnh thua hoặc không SL).",
              _grid(dict(tp=wp, tp_mode=[1], sl=[0.0] + lp, sl_mode=[1]))))
    roi_w = uq([x["ret_pct"] * l_ for x, l_ in zip(st, [u["lev"] for u in train]) if x["win"]])
    roi_l = uq([x["ret_pct"] * l_ for x, l_ in zip(st, [u["lev"] for u in train]) if not x["win"]]) if l else [50.0]
    G.append(("X1b_roi_pct", "TP/SL theo ROI trên ký quỹ (%): % giá = ROI / đòn bẩy của lệnh (người trade 'chốt lãi X% ROI').",
              _grid(dict(tp=roi_w, tp_mode=[1], sl=[0.0] + roi_l, sl_mode=[1], roi=[1]))))
    G.append(("X2_atr_RR", "TP/SL theo bội ATR%(1h) tại lúc vào (R-multiple), phân vị từ train.",
              _grid(dict(tp=wa, tp_mode=[2], sl=[0.0] + la, sl_mode=[2]))))
    G.append(("X3_trail_atr", "Trailing stop theo ATR: kích hoạt khi lãi >= act x ATR, lùi dist x ATR từ đỉnh; (± time-stop 2x trung vị) ± SL ATR.",
              _grid(dict(tr_act=[0.0, 1.0, 2.0, 4.0], tr_dist=[1.0, 2.0, 3.0], tr_mode=[2], sl=[0.0] + la[:2], sl_mode=[2], hold_min=[0, 4 * hq[1]]))))
    G.append(("X3b_trail_pct", "Trailing stop theo %: kích hoạt act%, lùi dist% từ đỉnh.",
              _grid(dict(tr_act=[0.5, 1.0, 2.0, 4.0], tr_dist=[0.3, 0.6, 1.0, 2.0], tr_mode=[1], hold_min=[0, 4 * hq[1]]))))
    G.append(("X4_ema_exit", "Thoát khi nến 1h ĐÓNG dưới (long) / trên (short) EMA20 hoặc EMA50 (+/- buffer ATR), sau khi giữ tối thiểu; ± SL ATR.",
              _grid(dict(ema_mode=[1, 2], ema_buf=[0.0, 0.5, 1.0], min_hold_min=[0, 120, 720, 2880], sl=[0.0] + la[:2], sl_mode=[2]))))
    G.append(("X5_rsi_exit", "Thoát khi RSI(14, 1h) đạt vùng quá mua (long) / quá bán (short) sau khi giữ tối thiểu; ± SL ATR.",
              _grid(dict(rsi_lvl=[60.0, 65.0, 70.0, 80.0], min_hold_min=[0, 120, 720], sl=[0.0] + la[:2], sl_mode=[2], hold_min=[0, 4 * hq[1]]))))
    G.append(("X6_round_TP", "TP tại mức TRÒN đầu tiên cách giá vào >= k x ATR (limit TP tại số tròn); ± SL ATR ± time-stop.",
              _grid(dict(round_k=[1.0, 2.0, 4.0, 8.0], sl=[0.0] + la[:2], sl_mode=[2], hold_min=[0, 4 * hq[1]]))))
    G.append(("X7_session", "Thoát đúng phút 00 của giờ UTC h (giờ đóng dày nhất của train) sau khi giữ tối thiểu 6/24/72h.",
              _grid(dict(sess_hr=top_hours, sess_min_hold_h=[6, 24, 72]))))
    return G, dict(win_pct_q=wp, loss_pct_q=lp, win_atr_q=wa, loss_atr_q=la, hold_min_q=hq, top_close_hours_utc=top_hours)


def _unit_sim_stats(u, params, a, al):
    S = simulate_unit(u, params, a=a, al=al)
    if S is None:
        return None
    tcl = max(c["t"] for c in S["closes"])
    return dict(t=tcl, closed=S["closed"], ret=S["ret"], pnl=S["pnl"], S=S)


def J_rel(t_sim, closed, t_act, t0):
    """Độ gần thời điểm đóng, độ rộng tỉ lệ với thời gian giữ thật (>=2h x 0.25): exp(-|dt|/(0.25 x max(hold,2h)))."""
    scale = 0.25 * np.maximum((t_act - t0) / H, 2.0) * H
    return np.where(closed, np.exp(-np.abs(t_sim - t_act) / scale), 0.0)


def exit_family_matrix(units, grid, keep_S=False):
    """sim mọi (tham số x unit). Trả mảng t_sim[g,u], closed[g,u], ret_sim[g,u] (+ S nếu keep_S)."""
    G, Un = len(grid), len(units)
    T = np.zeros((G, Un), np.int64); C = np.zeros((G, Un), bool); R = np.zeros((G, Un)); P = np.zeros((G, Un))
    cache = {u["id"]: (load.candle_arrays(u["sym"]), aligned(u["sym"])) for u in units}
    for gi, prm in enumerate(grid):
        for ui, u in enumerate(units):
            a, al = cache[u["id"]]
            r = _unit_sim_stats(u, prm, a, al)
            if r is None:
                T[gi, ui] = u["t0"]; C[gi, ui] = False; R[gi, ui] = 0.0; P[gi, ui] = 0.0
            else:
                T[gi, ui] = r["t"]; C[gi, ui] = r["closed"]; R[gi, ui] = r["ret"]; P[gi, ui] = r["pnl"]
    return T, C, R, P


def shuffled_hold_baseline(units, reps=300, seed=0, tols=(15, 60)):
    """Kiểm chứng ngẫu nhiên: gán mỗi unit một thời gian giữ lấy từ unit KHÁC (hoán vị) -> tỉ lệ khớp giờ đóng +-tol phút kỳ vọng
    của một luật chỉ biết PHÂN PHỐI thời gian giữ (không biết unit). Trả mean/p95."""
    rng = np.random.default_rng(seed)
    hold = np.array([u["t1"] - u["t0"] for u in units], float); n = len(units)
    out = {m: [] for m in tols}
    for _ in range(reps):
        p = rng.permutation(n)
        d = np.abs(hold[p] - hold) / MIN
        for m in tols:
            out[m].append(float((d <= m).mean()))
    return {f"shuffle_hold_match_{m}_mean": round(100 * float(np.mean(v)), 2) for m, v in out.items()} | {f"shuffle_hold_match_{m}_p95": round(100 * float(np.percentile(v, 95)), 2) for m, v in out.items()}


def exit_selection(units, T, C, R, tr_idx, te_idx):
    """Chọn tham số tốt nhất trên TRAIN (J_rel trung bình; hoà -> |ret_sim-ret_thật| nhỏ hơn), trả chỉ số + vector J + LOO trên TOÀN mẫu."""
    t_act = np.array([u["t1"] for u in units]); t0 = np.array([u["t0"] for u in units]); ra = np.array([u["ret"] for u in units])
    J = np.stack([J_rel(T[g], C[g], t_act, t0) for g in range(T.shape[0])])           # [g,u]
    E = np.abs(R - ra[None, :])                                                       # lỗi lợi suất (điểm %)
    key_tr = J[:, tr_idx].mean(1) - 1e-6 * E[:, tr_idx].mean(1)
    g_best = int(np.argmax(key_tr))
    # LOO: chọn g trên mọi unit trừ i
    n = len(units); loo_g = []
    for i in range(n):
        m = np.ones(n, bool); m[i] = False
        loo_g.append(int(np.argmax(J[:, m].mean(1) - 1e-6 * E[:, m].mean(1))))
    loo_g = np.array(loo_g)
    d_min = np.array([abs(T[loo_g[i], i] - t_act[i]) / MIN if C[loo_g[i], i] else np.inf for i in range(n)])
    loo = dict(n=n, close_match_15=round(100 * float((d_min <= 15).mean()), 1), close_match_60=round(100 * float((d_min <= 60).mean()), 1),
               J_rel_mean=round(float(np.mean([J[loo_g[i], i] for i in range(n)])), 3),
               sign_agree=round(100 * float(np.mean([np.sign(R[loo_g[i], i]) == np.sign(ra[i]) for i in range(n)])), 1),
               med_abs_ret_err_pp=round(float(np.median([E[loo_g[i], i] for i in range(n)])), 3), n_distinct_params=int(len(set(loo_g.tolist()))))
    # walk-forward theo thời gian: chọn tham số trên unit <k, chấm unit k (k>=6)
    wf = []
    for k in range(6, n):
        g = int(np.argmax(J[:, :k].mean(1) - 1e-6 * E[:, :k].mean(1)))
        wf.append((abs(T[g, k] - t_act[k]) / MIN if C[g, k] else np.inf, J[g, k], np.sign(R[g, k]) == np.sign(ra[k])))
    if wf:
        d_ = np.array([x[0] for x in wf])
        loo["walk_forward"] = dict(n=len(wf), close_match_15=round(100 * float((d_ <= 15).mean()), 1), close_match_60=round(100 * float((d_ <= 60).mean()), 1),
                                   J_rel_mean=round(float(np.mean([x[1] for x in wf])), 3), sign_agree=round(100 * float(np.mean([x[2] for x in wf])), 1))
    return g_best, J, loo, float(J[g_best, tr_idx].mean()), float(J[g_best, te_idx].mean())


# ---------------------------------------------------------------- ADD / NHỒI LỆNH (điều kiện hoá theo vị thế thật đang mở)
def open_state(units, sym, side):
    """Trên lưới 5m của mã: open(bool), last(giá avg của unit mở GẦN NHẤT còn mở), avg (giá TB các unit đang mở) theo vị thế THẬT."""
    f = panel(sym); tc = f["t_close"].values
    n = len(tc); op = np.zeros(n, bool); last = np.full(n, np.nan); sq = np.zeros(n); spq = np.zeros(n)
    for u in sorted([x for x in units if x["sym"] == sym and x["side"] == side], key=lambda x: x["t0"]):
        i0 = int(np.searchsorted(tc, u["t0"], side="right")); i1 = int(np.searchsorted(tc, u["t1"], side="left"))
        if i1 <= i0: continue
        q = u["notional"] / u["avg_px"]
        op[i0:i1] = True; last[i0:i1] = u["avg_px"]; sq[i0:i1] += q; spq[i0:i1] += q * u["avg_px"]
    avg = np.where(sq > 0, spq / np.where(sq > 0, sq, 1), np.nan)
    return op, last, avg


def add_signals(units, sym, side, rule):
    """Tín hiệu NHỒI khi đang có vị thế thật cùng chiều. rule: kind in {pyr, avgdown, pull_profit, contra, any_open}.
      pyr         : giá >= giá fill gần nhất x (1+thr%) theo chiều lệnh (nhồi khi đang lãi), cạnh lên
      avgdown     : giá <= giá fill gần nhất x (1-thr%) (trung bình giá xuống), cạnh lên
      pull_profit : đang lãi so với avg VÀ hồi về dưới EMA20 (d_ema20 <= -thr ATR) (nhồi khi đang lãi nhưng có nhịp hồi)
      contra      : z4h <= -thr (sau nhịp giảm thr sigma) bất kể lãi/lỗ
      any_open    : mọi lúc đang mở (baseline cấu trúc) - cạnh lên khi mở vị thế
    """
    f = panel(sym); op, last, avg = open_state(units, sym, side)
    s = 1 if side == "long" else -1
    c = f["c"].values; thr = rule.get("thr", 0)
    k = rule["kind"]
    if k == "pyr": cond = op & (s * (c / last - 1) * 100 >= thr)
    elif k == "avgdown": cond = op & (s * (c / last - 1) * 100 <= -thr)
    elif k == "pull_profit": cond = op & (s * (c / avg - 1) > 0) & (s * f["d_ema20"].values <= -thr)
    elif k == "contra": cond = op & (s * f["z4h"].values <= -thr)
    elif k == "any_open": cond = op
    elif k == "ladder":
        # limit add tại MỨC TRÒN gần nhất cách giá fill gần nhất thr% (bước = nice(k x ATR trung vị)); chạm khi low<=mức (long) / high>=mức (short)
        step = nice_step(float(np.nanmedian(f["atr_pct"].values / 100 * c)), rule["k"])
        L = np.round(last * (1 - s * thr / 100.0) / step) * step
        cond = op & ((f["l"].values <= L) if s == 1 else (f["h"].values >= L))
    else: raise ValueError(k)
    cond = np.nan_to_num(cond.astype(float)).astype(bool)
    if rule.get("vol") is not None:
        cond = cond & (f["atr_pct"].values >= float(np.quantile(f["atr_pct"].values, rule["vol"])))
    # cạnh lên + cooldown
    edge = cond & ~np.r_[False, cond[:-1]]
    t = f["t_close"].values[edge]; cool = rule.get("cool_h", 6) * H; keep = []; lastt = -10**18
    for ti in t:
        if ti - lastt >= cool: keep.append(ti); lastt = ti
    return np.array(keep, np.int64), (f["t_close"].values[op], )


def add_rules():
    R = []
    for cool in (1, 6, 24):
        for vol in (None, 0.6):
            b = dict(cool_h=cool, **({} if vol is None else dict(vol=vol)))
            for thr in (0.5, 1.0, 2.0, 4.0): R.append(dict(kind="pyr", thr=thr, **b))
            for thr in (0.5, 1.0, 2.0, 3.0): R.append(dict(kind="avgdown", thr=thr, **b))
            for thr in (0.5, 1.0, 2.0): R.append(dict(kind="pull_profit", thr=thr, **b))
            for thr in (1.0, 1.5, 2.0): R.append(dict(kind="contra", thr=thr, **b))
            R.append(dict(kind="any_open", **b))
            for thr in (0.5, 1.0, 2.0):
                for k in (0.5, 1.0, 2.0): R.append(dict(kind="ladder", thr=thr, k=k, **b))
    return R


def add_rule_name(r):
    return r["kind"] + (" thr=%g" % r["thr"] if "thr" in r else "") + (" k=%g" % r["k"] if "k" in r else "") + " cool%dh" % r["cool_h"] + (" vol>=q%g" % r["vol"] if r.get("vol") else "")


def cond_table(events, keys, sig_func, wins_all, rules, split_t, reps=200, seed=0):
    """Bảng luật có ĐIỀU KIỆN (nhồi lệnh / thoát cấp danh mục): recall/precision tại +-15/60/240 phút so với `events` [(key,t)], baseline ngẫu nhiên
    TRONG cửa sổ `wins_all[key]` (các thời điểm lưới mà vị thế thật đang mở) + sàn giải tích; mặt nạ cho LOO/walk-forward."""
    rng = np.random.default_rng(seed)
    out = []
    for r in rules:
        sig = sig_func(r)
        row = dict(rule=r)
        for part, sel in (("train", lambda t: t < split_t), ("test", lambda t: t >= split_t), ("all", lambda t: t > 0)):
            act = {}
            for k, t in events:
                if sel(t): act.setdefault(k, []).append(t)
            act = {k: np.array(v, np.int64) for k, v in act.items()}
            sg = {k: v[sel(v)] for k, v in sig.items() if sel(v).any()}
            m = dict(n_actual=sum(len(v) for v in act.values()), n_sig=sum(len(v) for v in sg.values()))
            for tol in (15, 60, 240):
                rc, pr, na, ns = match._pr(act, sg, tol * MIN)
                m[f"recall_{tol}"] = round(100 * rc, 2); m[f"precision_{tol}"] = round(100 * pr, 2)
            base = {tol: ([], []) for tol in (15, 60, 240)}
            for _ in range(reps):
                rs = {}
                for k, v in sg.items():
                    pool = wins_all[k][sel(wins_all[k])]
                    if len(pool) == 0: continue
                    rs[k] = np.sort(rng.choice(pool, size=len(v)))
                for tol in (15, 60, 240):
                    rc, pr, _, _ = match._pr(act, rs, tol * MIN)
                    base[tol][0].append(rc); base[tol][1].append(pr)
            for tol in (15, 60, 240):
                for j, nm in enumerate(("recall", "precision")):
                    v = np.array(base[tol][j]) * 100
                    m[f"rand_{nm}_{tol}_mean"] = round(float(v.mean()), 2); m[f"rand_{nm}_{tol}_p95"] = round(float(np.percentile(v, 95)), 2)
            row[part] = m
        row["masks"] = {tol: _masks(events, sig, tol * MIN) for tol in (15, 240)}
        row["base"] = {}
        for tol in (15, 60, 240):
            ar = ap = 0.0; na_ = ns_ = 0
            for k in keys:
                pool = len(wins_all[k]); ev_k = sum(1 for kk, _ in events if kk == k)
                if pool == 0: continue
                pe = min(1.0, (2 * tol / 5 + 1) / pool)
                ar += ev_k * (1 - (1 - pe) ** len(sig.get(k, ()))); na_ += ev_k
                ap += len(sig.get(k, ())) * min(1.0, ev_k * pe); ns_ += len(sig.get(k, ()))
            ar = ar / max(1, na_); ap = ap / max(1, ns_)
            row["base"][tol] = (max(row["all"][f"rand_recall_{tol}_mean"], 100 * ar), max(row["all"][f"rand_precision_{tol}_mean"], 100 * ap))
        row["n_sig"] = int(sum(len(v) for v in sig.values()))
        out.append(row)
    return out


def add_table(units, rules, split_t, reps=200, seed=0):
    """Nhồi lệnh: events = unit is_add; baseline = ngẫu nhiên trong cửa sổ vị thế thật đang mở."""
    keys = sorted({(u["sym"], u["side"]) for u in units})
    adds = sorted((((u["sym"], u["side"]), u["t0"]) for u in units if u["is_add"]), key=lambda x: x[1])
    wins_all = {k: panel(k[0])["t_close"].values[open_state(units, *k)[0]] for k in keys}

    def sig_func(r):
        sig = {}
        for k in keys:
            t, _ = add_signals(units, k[0], k[1], r)
            if len(t): sig[k] = t
        return sig
    return cond_table(adds, keys, sig_func, wins_all, rules, split_t, reps, seed), adds


# ---------------------------------------------------------------- THOÁT CẤP DANH MỤC (đóng theo cụm)
def close_events(units, group="all", gap_ms=60_000, min_units=1):
    """Cụm lệnh đóng cách nhau <=gap_ms. group='all': mọi mã gộp một khoá 'PF'; group='sym': theo (mã,chiều). Trả [(key, t_đầu_cụm, n_unit)]."""
    cl = sorted(((c["t"], (u["sym"], u["side"]) if group == "sym" else "PF", u["id"]) for u in units for c in u["closes"]), key=lambda x: x[0])
    out = []; cur = {}
    for t, k, uid in cl:
        c = cur.get(k)
        if c and t - c["last"] <= gap_ms:
            c["last"] = t; c["ids"].add(uid)
        else:
            if c: out.append((k, c["t"], len(c["ids"])))
            cur[k] = dict(t=t, last=t, ids={uid})
    for k, c in cur.items(): out.append((k, c["t"], len(c["ids"])))
    out = [e for e in out if e[2] >= min_units]
    return sorted(out, key=lambda x: x[1])


PF = dict(units=None, state={}, sig={})


def pf_register(units):
    """Đăng ký danh sách unit THẬT làm trạng thái danh mục (điều kiện hoá) cho các luật thoát cấp danh mục."""
    PF["units"] = units; PF["state"] = {}; PF["sig"] = {}


def pf_state(units, group="all", basis="notional"):
    """Trên lưới 5m: ret_pf (%) = tổng lãi/lỗ CHƯA chốt của các unit THẬT đang mở / (tổng notional | tổng ký quỹ), open mask, theo nhóm ('PF' hoặc (mã,chiều))."""
    ref = max((panel(u["sym"]) for u in units), key=len)
    tc = ref["t_close"].values
    px = {}
    for sym in {u["sym"] for u in units}:
        px[sym] = panel(sym)["c"].reindex(ref.index).ffill().bfill().values
    st = {}
    for u in units:
        k = (u["sym"], u["side"]) if group == "sym" else "PF"
        d = st.setdefault(k, dict(pnl=np.zeros(len(tc)), notional=np.zeros(len(tc)), n=np.zeros(len(tc))))
        i0 = int(np.searchsorted(tc, u["t0"], side="right")); i1 = int(np.searchsorted(tc, u["t1"], side="left"))
        if i1 <= i0: continue
        s = 1 if u["side"] == "long" else -1; q = u["notional"] / u["avg_px"]
        base = u["notional"] if basis == "notional" else sum(f["mg"] for f in u["fills"])
        d["pnl"][i0:i1] += s * q * (px[u["sym"]][i0:i1] - u["avg_px"]); d["notional"][i0:i1] += base; d["n"][i0:i1] += 1
    res = {}
    for k, d in st.items():
        op = d["notional"] > 0
        ret = np.where(op, d["pnl"] / np.where(op, d["notional"], 1) * 100, 0.0)
        res[k] = dict(ret=ret, open=op, n=d["n"])
    return tc, res


def pf_get(group, basis):
    k = (group, basis)
    if k not in PF["state"]:
        PF["state"][k] = pf_state(PF["units"], group, basis)
    return PF["state"][k]


def pf_sig_cached(rule, group, basis):
    key = (group, basis, tuple(sorted(rule.items())))
    if key not in PF["sig"]:
        tc, state = pf_get(group, basis)
        PF["sig"][key] = pf_signals(tc, state, rule)
    return PF["sig"][key]


def _simulate_unit_pf(u, params, horizon_min, a, fee_bps):
    rule = dict(kind=params["pf_kind"], thr=params["thr"], **{k: params[k] for k in ("dist", "sl") if k in params})
    sig = pf_sig_cached(rule, params.get("group", "all"), params.get("basis", "notional"))
    key = "PF" if params.get("group", "all") == "all" else (u["sym"], u["side"])
    ts = sig.get(key, np.zeros(0, np.int64))
    a = a or load.candle_arrays(u["sym"])
    j = int(np.searchsorted(ts, u["t0"], side="right"))
    t_end = u["t1"] + horizon_min * MIN
    if j < len(ts) and ts[j] <= t_end:
        i = min(len(a["t"]) - 1, int(np.searchsorted(a["t"], ts[j], side="left")))
        return _unit_result(u, int(a["t"][i]), float(a["o"][i]), True, fee_bps)
    i = min(len(a["t"]) - 1, int(np.searchsorted(a["t"], t_end, side="right")) - 1)
    return _unit_result(u, int(a["t"][i]), float(a["c"][i]), False, fee_bps)


def pf_signals(tc, state, rule):
    """Tín hiệu thoát cấp danh mục. rule: kind in {pf_tp, pf_sl, pf_trail}; thr (%); dist (%) cho trail; cooldown 6h. Cạnh lên."""
    out = {}
    for k, d in state.items():
        ret, op = d["ret"], d["open"]
        if rule["kind"] == "pf_tp": cond = op & (ret >= rule["thr"])
        elif rule["kind"] == "pf_sl": cond = op & (ret <= -rule["thr"])
        elif rule["kind"] == "pf_trail":
            peak = np.zeros(len(ret)); cur = -1e9
            for i in range(len(ret)):
                cur = max(cur, ret[i]) if op[i] else -1e9
                peak[i] = cur
            cond = op & (peak >= rule["thr"]) & (ret <= peak - rule["dist"])
        elif rule["kind"] == "pf_ts":   # trailing danh mục HOẶC cắt lỗ danh mục (cái nào tới trước)
            peak = np.zeros(len(ret)); cur = -1e9
            for i in range(len(ret)):
                cur = max(cur, ret[i]) if op[i] else -1e9
                peak[i] = cur
            cond = op & (((peak >= rule["thr"]) & (ret <= peak - rule["dist"])) | (ret <= -rule["sl"]))
        else: raise ValueError(rule["kind"])
        edge = cond & ~np.r_[False, cond[:-1]]
        t = tc[edge]; keep = []; last = -10**18
        for ti in t:
            if ti - last >= 6 * H: keep.append(ti); last = ti
        if keep: out[k] = np.array(keep, np.int64)
    return out


def pf_rules(basis="notional"):
    """Lưới ngưỡng theo % notional (basis='notional') hoặc % ký quỹ = ROI (basis='margin', ngưỡng x10)."""
    k = 1.0 if basis == "notional" else 10.0
    R = []
    for thr in (0.5, 1.0, 2.0, 4.0, 8.0): R.append(dict(kind="pf_tp", thr=thr * k))
    for thr in (0.5, 1.0, 2.0, 4.0): R.append(dict(kind="pf_sl", thr=thr * k))
    for thr in (0.5, 1.0, 2.0, 4.0):
        for dist in (0.25, 0.5, 1.0, 2.0): R.append(dict(kind="pf_trail", thr=thr * k, dist=dist * k))
    for thr in (1.0, 2.0, 4.0):
        for dist in (0.5, 1.0, 2.0):
            for sl in (1.0, 2.0, 4.0): R.append(dict(kind="pf_ts", thr=thr * k, dist=dist * k, sl=sl * k))
    return R


def pf_rule_name(r):
    return r["kind"] + " thr=%g" % r["thr"] + (" dist=%g" % r["dist"] if "dist" in r else "") + (" sl=%g" % r["sl"] if "sl" in r else "")


def pf_exit_grid(group, basis):
    """Lưới tham số cho simulate_unit (thoát cấp danh mục)."""
    return [dict(pf_kind=r["kind"], group=group, basis=basis, **{k: v for k, v in r.items() if k != "kind"}) for r in pf_rules(basis)]


def pf_table(units, group, split_t, min_units, basis="notional", reps=200, seed=0):
    tc, state = pf_get(group, basis)
    events = [(k, t) for k, t, n in close_events(units, group, min_units=min_units) if k in state]
    keys = sorted(state, key=str)
    wins = {k: tc[state[k]["open"]] for k in keys}
    rules = pf_rules(basis)
    return cond_table(events, keys, lambda r: pf_signals_for(tc, state, r), wins, rules, split_t, reps, seed), events


def pf_signals_for(tc, state, r):
    return pf_signals(tc, state, r)


def feature_ranks(units):
    """Phân vị (rank) của mỗi đặc trưng tại thời điểm vào so với phân phối của CHÍNH mã (toàn mẫu lưới 5m). z = (mean_rank-0.5)/sqrt(1/12/n).
    side-flipped: với lệnh short rank được đảo (1-x) => rank THẤP = vào NGƯỢC đà/ở vùng bất lợi cho chiều lệnh (contrarian), CAO = thuận đà.
    Biến nhị phân (brk*, sweep24): tỉ lệ có tín hiệu lúc vào so với tỉ lệ nền (z nhị thức)."""
    out = {}
    for grp, sel in (("first", [u for u in units if not u["is_add"]]), ("add", [u for u in units if u["is_add"]]), ("all", units)):
        if len(sel) < 4: continue
        d = {}
        for f in FEATS:
            vals = []
            for u in sel:
                p = panel(u["sym"]); r = feat_at(u["sym"], u["t0"])
                if r is None or np.isnan(r[f]): continue
                col = p[f].values; x = r[f]
                vals.append((np.mean(col < x) + 0.5 * np.mean(col == x), 1 if u["side"] == "long" else -1, x, float(np.mean(col))))
            if len(vals) < 4: continue
            n = len(vals)
            if f.startswith("brk") or f == "sweep24":
                rate = float(np.mean([v[2] > 0.5 for v in vals])); base = float(np.mean([v[3] for v in vals]))
                z = (rate - base) / math.sqrt(max(base * (1 - base), 1e-9) / n)
                d[f] = dict(n=n, hit_rate=round(rate, 3), base_rate=round(base, 3), z=round(z, 2))
            else:
                a = np.array([v[0] for v in vals]); fl = np.array([v[0] if v[1] == 1 else 1 - v[0] for v in vals])
                sd = math.sqrt(1 / 12 / n)
                d[f] = dict(n=n, rank_mean=round(float(a.mean()), 3), z=round((a.mean() - .5) / sd, 2), side_flipped_rank_mean=round(float(fl.mean()), 3),
                            side_flipped_z=round((fl.mean() - .5) / sd, 2))
        out[grp] = d
    return out


def _step_bps(px):
    best = 0.0
    for e in range(-8, 8):
        for m in (1, 2, 5):
            st = m * 10 ** e
            if st / px * 1e4 > 300: continue
            r = px / st
            if abs(r - round(r)) < 1e-6 and round(r) != 0: best = max(best, st / px * 1e4)
    return best


def roundness(units, seed=0):
    """Độ 'tròn' của giá fill vào/ra: bước tròn lớn nhất (1/2/5 x 10^k, <=3% giá) chia hết giá, tính bằng bps của giá.
    Baseline = giá đóng nến 1m ngẫu nhiên của cùng mã làm tròn 2 chữ số thập phân (>=10) / 5 chữ số có nghĩa."""
    ent = [_step_bps(f["px"]) for u in units for f in u["fills"]]
    ext = [_step_bps(c["px"]) for u in units for c in u["closes"]]
    rng = np.random.default_rng(seed); base = []
    for u in units:
        a = load.candle_arrays(u["sym"]); px = a["c"][rng.integers(0, len(a["c"]), 40)]
        base += [_step_bps(round(float(p), 2) if p >= 10 else float("%.5g" % p)) for p in px]
    pct = lambda x, th: round(100 * float(np.mean(np.array(x) >= th)), 1)
    return {f"{nm}_ge_{th}bps": pct(v, th) for nm, v in (("entry", ent), ("exit", ext), ("baseline_candle_close", base)) for th in (5, 15, 40)} | dict(n_entry=len(ent), n_exit=len(ext))


def add_structure(units):
    """Mô tả các lệnh nhồi (unit is_add) so với vị thế thật đang mở cùng chiều."""
    rows = []
    for u in units:
        if not u["is_add"]: continue
        s = 1 if u["side"] == "long" else -1
        op = [v for v in units if v is not u and v["sym"] == u["sym"] and v["side"] == u["side"] and v["t0"] < u["t0"] < v["t1"]]
        q = sum(v["notional"] / v["avg_px"] for v in op); avg = sum(v["notional"] for v in op) / q
        last = max(op, key=lambda v: v["t0"]); px = u["fills"][0]["px"]
        rows.append(dict(vs_avg=s * (px / avg - 1) * 100, vs_last=s * (px / last["avg_px"] - 1) * 100, gap_h=(u["t0"] - last["t0"]) / H,
                         size_ratio=u["notional"] / sum(v["notional"] for v in op), n_open=len(op)))
    if not rows: return dict(n_adds=0)
    vl = np.array([r["vs_last"] for r in rows]); va = np.array([r["vs_avg"] for r in rows])
    return dict(n_adds=len(rows), pct_into_profit_vs_avg=round(100 * float((va > 0.05).mean()), 1), pct_against_vs_last=round(100 * float((vl < -0.05).mean()), 1),
                pct_same_price_abs_lt_0p05=round(100 * float((np.abs(vl) < 0.05).mean()), 1), vs_last_pct_q=_q(vl, (10, 25, 50, 75, 90)), vs_avg_pct_q=_q(va, (10, 25, 50, 75, 90)),
                gap_h_q=_q([r["gap_h"] for r in rows], (10, 25, 50, 75, 90)), size_ratio_q=_q([r["size_ratio"] for r in rows], (10, 25, 50, 75, 90)),
                pct_adverse_1_to_3pct_vs_last=round(100 * float(((vl <= -1) & (vl >= -3)).mean()), 1))


# ---------------------------------------------------------------- mô phỏng ĐẦY ĐỦ (luật vào + luật thoát, không điều kiện hoá theo fill thật)
def full_sim(keys, entry_rule, exit_params, notional, lo, hi, lev=10.0):
    """Mỗi tín hiệu vào của luật -> mở 1 lệnh tại open nến 1m kế tiếp, notional cố định, thoát theo exit_params; 1 vị thế / (mã,chiều) tại 1 thời điểm.
    Chưa đóng đến hết dữ liệu -> mark-to-market. Trả list lệnh sim."""
    out = []
    for (sym, side) in keys:
        a = load.candle_arrays(sym); al = aligned(sym)
        if a is None: continue
        busy = -1
        for t in signals(sym, side, entry_rule):
            if t < lo or t > hi or t <= busy: continue
            i = int(np.searchsorted(a["t"], t, side="left"))
            if i >= len(a["t"]) - 3: continue
            px = float(a["o"][i]); tt = int(a["t"][i])
            f = dict(t=tt, px=px, notional=notional, qty=notional / px, mg=notional / lev, lev=lev)
            u = dict(sym=sym, side=side, lev=lev, fills=[f], closes=[], avg_px=px, notional=notional, t0=tt, t1=int(a["t"][-1]) - 61 * MIN, id=-1)
            S = simulate_unit(u, exit_params, a=a, al=al)
            if S is None: continue
            tcl = max(c["t"] for c in S["closes"]); busy = tcl
            out.append(dict(sym=sym, side=side, t0=tt, t1=tcl, pnl=S["pnl"], ret=S["ret"], closed=S["closed"], px0=px))
    out.sort(key=lambda x: x["t1"])
    return out


def cum_series(pairs):
    """pairs: [(t, pnl)] -> [[t, cum]] theo thời gian."""
    ca = 0.0; res = []
    for t, p in sorted(pairs):
        ca += p; res.append([int(t), round(ca, 1)])
    return res


def trim_a(m):
    keep = ["n_baskets", "n_simulated", "close_match_5", "close_match_15", "close_match_60", "sim_closed_pct", "close_px_err_bps_med", "close_px_err_bps_p90",
            "layer_close_n", "layer_close_match5", "pnl_sign_agree", "pnl_corr", "pnl_med_abs_err_pp", "pnl_corr_usdt", "act_pnl_sum", "sim_pnl_sum", "act_win_pct", "sim_win_pct"]
    return {k: m.get(k) for k in keep if k in m}


def tranche_stats(units):
    """Chia lệnh trong 1 unit (tranche): số sub-position/unit, khoảng cách giờ, lệch giá (bps) giữa các fill liên tiếp, tỉ lệ size so với fill đầu."""
    n_sub = [len(u["fills"]) for u in units]
    gaps, dpx, sz = [], [], []
    for u in units:
        fs = u["fills"]
        for i in range(1, len(fs)):
            gaps.append((fs[i]["t"] - fs[i - 1]["t"]) / MIN); dpx.append(abs(fs[i]["px"] / fs[i - 1]["px"] - 1) * 1e4); sz.append(fs[i]["notional"] / fs[0]["notional"])
    return dict(n_units=len(units), n_units_split=int(sum(x > 1 for x in n_sub)), n_extra_fills_in_tranche=int(sum(x - 1 for x in n_sub)),
                fills_per_unit_q=_q(n_sub, (50, 75, 90, 100)), gap_min_q=_q(gaps, (10, 25, 50, 75, 90)), px_step_bps_q=_q(dpx, (10, 25, 50, 75, 90)),
                size_vs_first_q=_q(sz, (10, 25, 50, 75, 90)),
                note="tranche = sub-position cùng (mã,chiều) mở cách <=15 phút (chia lệnh vào); khoảng cách giá giữa các fill ~ vài bps => 1 lệnh vào khớp từng phần, không phải tầng DCA")


def timing_quality(units):
    """Chất lượng điểm vào/ra: xếp hạng giá vào/ra trong cửa sổ +-12h (1 = giá tốt nhất cho chiều lệnh) và hiệu suất thoát của lệnh thắng = lãi/MFE."""
    ex_r, en_r, eff = [], [], []
    for u in units:
        a = load.candle_arrays(u["sym"]); s = 1 if u["side"] == "long" else -1
        def rank(t, px, best_low):
            i = int(np.searchsorted(a["t"], t)); w = slice(max(0, i - 720), i + 720)
            hi = a["h"][w].max(); lo = a["l"][w].min()
            r = (px - lo) / (hi - lo) if hi > lo else 0.5
            return (1 - r) if best_low else r
        # vào: long tốt khi giá thấp; ra: long tốt khi giá cao
        en_r.append(rank(u["t0"], u["fills"][0]["px"], s == 1))
        ex_r.append(rank(u["t1"], u["closes"][-1]["px"], s == -1))
        st = exit_stats(u); mfe = unit_excursions(u)[0]
        if st["win"] and mfe > 0: eff.append(st["ret_pct"] / mfe)
    return dict(entry_price_rank_mean=round(float(np.mean(en_r)), 3), entry_price_rank_median=round(float(np.median(en_r)), 3),
                exit_price_rank_mean=round(float(np.mean(ex_r)), 3), exit_price_rank_median=round(float(np.median(ex_r)), 3),
                win_exit_efficiency_ret_over_mfe_q=_q(eff, (25, 50, 75)), note="rank 0.5 = ngẫu nhiên; 1 = giá tốt nhất trong +-12h")
