"""Simulator basket tổng quát trên nến 1m (numba). Điều kiện hoá theo fill đầu thật (thời điểm, giá, notional).

Đường giá trong 1 nến 1m: O -> cực BẤT LỢI (low với long, high với short) -> cực CÓ LỢI -> C  (worst-case cho stop/add:
phía bất lợi xảy ra TRƯỚC phía có lợi trong cùng 1 nến). Hệ quả:
  - trong cùng nến, add/SL chạm trước TP; add xong thì avg đổi và TP mới (tính từ avg mới) vẫn được xét ở phía có lợi.
  - nhiều mức add trong 1 nến khớp lần lượt từ mức gần giá mở cửa nhất; nếu add và SL cùng chạm thì mức gần open hơn xảy ra trước.
  - khớp kiểu limit: add khớp tại mức (hoặc giá mở cửa nếu gap vượt mức - tốt hơn); TP khớp tại mức (hoặc open nếu gap vượt);
    SL/trailing/time-stop khớp tại mức (hoặc open nếu gap qua mức - xấu hơn).
  - nến chứa fill đầu thật KHÔNG được xét (không biết thứ tự trong phút) -> mô phỏng bắt đầu từ nến kế tiếp.
Phí: fee_bps mỗi chiều trên notional (OKX thực tế ~ 7 bps khứ hồi theo đối chiếu pnl vs giá). Không tính funding.

Tham số (dict -> vector P, xem PARAM_DEFAULT):
  add_ref   0: bước tính từ fill GẦN NHẤT | 1: từ fill ĐẦU (thang lưới: mức k = p0 -/+ tổng bước 1..k) | 2: từ giá TRUNG BÌNH
  step_pct  bước add (%); nếu use_scale=1 thì step = step_pct x ATR%(1h,14) tại fill tham chiếu (bội số ATR)
  step_growth bước tầng k = step x growth^(k-1)
  max_layers tổng số fill tối đa (kể cả fill đầu)
  size_mult, size_ref  notional add = size_mult x (notional fill TRƯỚC nếu size_ref=0 | notional fill ĐẦU nếu size_ref=1)
  tp_pct (0=tắt), tp_ref 0=từ avg / 1=từ fill đầu, tp_mode 0=đóng cả basket / 1=mỗi tầng có TP riêng từ giá fill của nó
  sl_pct (0=tắt), sl_ref 0=từ avg / 1=từ fill đầu, đóng cả basket
  trail_act (%, 0=tắt) kích hoạt khi lãi từ avg >= act; trail_dist (%) lùi từ đỉnh lãi
  max_hold_bars (0=tắt) time stop, đóng cả basket ở giá open nến
  add_ref=3: add THEO THỜI GIAN (mỗi add_delay_min phút kể từ fill trước, giá open nến) - scale-in không phụ thuộc giá
  tp_use_scale/sl_use_scale=1: tp_pct/sl_pct là BỘI SỐ ATR%(1h,14) tại fill đầu
"""
import numpy as np
import pandas as pd
from numba import njit

from load import MIN, candle_arrays

PARAM_DEFAULT = dict(add_ref=0, step_pct=1.0, step_growth=1.0, max_layers=1, size_mult=0.33, size_ref=1, tp_pct=0.0, tp_ref=0,
                     tp_mode=0, sl_pct=0.0, sl_ref=0, trail_act=0.0, trail_dist=0.0, max_hold_bars=0, use_scale=0, add_delay_min=0, tp_use_scale=0, sl_use_scale=0, fee_bps=3.5)
_ORDER = ["add_ref", "step_pct", "step_growth", "max_layers", "size_mult", "size_ref", "tp_pct", "tp_ref", "tp_mode",
          "sl_pct", "sl_ref", "trail_act", "trail_dist", "max_hold_bars", "use_scale", "add_delay_min", "tp_use_scale", "sl_use_scale"]
MAXL = 40


def pvec(params):
    p = dict(PARAM_DEFAULT); p.update(params)
    return np.array([float(p[k]) for k in _ORDER], dtype=np.float64)


@njit(cache=True)
def _run(o, h, l, c, scale, i0, i_end, s, p0, N0, P, f_bar, f_px, f_not, c_bar, c_px, c_qty, c_lay):
    add_ref = int(P[0]); step = P[1]; grow = P[2]; maxL = min(int(P[3]), 40); smult = P[4]; sref = int(P[5])
    tp = P[6] / 100.0; tp_ref = int(P[7]); tp_mode = int(P[8]); sl = P[9] / 100.0; sl_ref = int(P[10])
    if int(P[16]) == 1: tp = tp * scale[i0]   # tp_pct = bội số ATR%(1h) tại fill đầu (scale đã ở đơn vị %, tp đã chia 100)
    if int(P[17]) == 1: sl = sl * scale[i0]
    add_delay = max(1, int(P[15])); last_i = i0
    tr_act = P[11] / 100.0; tr_dist = P[12] / 100.0; maxhold = int(P[13]); use_scale = int(P[14])
    nf = 1; nc = 0
    f_bar[0] = i0; f_px[0] = p0; f_not[0] = N0
    qty = np.zeros(40); alive = np.zeros(40, dtype=np.bool_)
    qty[0] = N0 / p0; alive[0] = True
    sum_q = qty[0]; sum_pq = qty[0] * p0
    last_px = p0; cum_step = 0.0
    sc_ref = scale[i0] if use_scale == 1 else 1.0
    ext = p0; trail_on = False
    for i in range(i0 + 1, i_end + 1):
        o_ = o[i]; h_ = h[i]; l_ = l[i]
        adv = l_ if s == 1 else h_
        fav = h_ if s == 1 else l_
        # time stop (đầu nến)
        if maxhold > 0 and i - i0 >= maxhold:
            for j in range(nf):
                if alive[j]:
                    c_bar[nc] = i; c_px[nc] = o_; c_qty[nc] = qty[j]; c_lay[nc] = j; nc += 1; alive[j] = False
            return nf, nc, 1
        # trailing stop dựa trên đỉnh các nến trước
        if trail_on:
            stp = ext * (1.0 - s * tr_dist)
            if s * (adv - stp) <= 0:
                px = stp if s * (o_ - stp) > 0 else o_
                for j in range(nf):
                    if alive[j]:
                        c_bar[nc] = i; c_px[nc] = px; c_qty[nc] = qty[j]; c_lay[nc] = j; nc += 1; alive[j] = False
                return nf, nc, 1
        # pha bất lợi: add / SL
        while True:
            avg = sum_pq / sum_q
            L_add = np.nan
            if nf < maxL and step > 0:
                st = step * (grow ** (nf - 1)) * sc_ref
                if add_ref == 3:
                    # add THEO THỜI GIAN: sau add_delay phút kể từ fill trước, vào thêm tại giá open nến (scale-in), không cần giá đi ngược
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
        # pha có lợi: TP
        avg = sum_pq / sum_q
        if tp > 0:
            if tp_mode == 0:
                base = avg if tp_ref == 0 else p0
                T = base * (1.0 + s * tp)
                if s * (fav - T) >= 0:
                    # gap-fill tại open chỉ khi mức TP đã tồn tại từ đầu nến (chưa add trong nến); nếu vừa add thì giá đi xuống rồi hồi lên qua T -> khớp tại T
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
    # chưa đóng hết trong horizon -> mark-to-market tại close nến cuối
    for j in range(nf):
        if alive[j]:
            c_bar[nc] = i_end; c_px[nc] = c[i_end]; c_qty[nc] = qty[j]; c_lay[nc] = j; nc += 1
    return nf, nc, 0


_SCALE = {}


def atr_scale(sym):
    """ATR%(1h,14) theo từng nến 1m, chỉ dùng giờ đã ĐÓNG (không look-ahead)."""
    if sym in _SCALE:
        return _SCALE[sym]
    a = candle_arrays(sym)
    if a is None:
        _SCALE[sym] = None; return None
    df = pd.DataFrame(dict(h=a["h"], l=a["l"], c=a["c"]), index=pd.to_datetime(a["t"], unit="ms"))
    hr = df.resample("1h").agg(dict(h="max", l="min", c="last")).dropna()
    pc = hr.c.shift(1)
    tr = pd.concat([hr.h - hr.l, (hr.h - pc).abs(), (hr.l - pc).abs()], axis=1).max(axis=1)
    atr = (tr.rolling(14, min_periods=6).mean() / hr.c * 100).shift(1)  # giá trị dùng được từ giờ kế tiếp
    idx = pd.to_datetime(a["t"], unit="ms").floor("1h")
    sc = atr.reindex(idx).values
    sc = pd.Series(sc).ffill().bfill().values.astype(np.float64)
    _SCALE[sym] = sc
    return sc


def simulate(basket, params, horizon_min=60, a=None):
    """Mô phỏng 1 basket điều kiện hoá theo fill đầu thật. Horizon = t1 thật + horizon_min phút.
    Trả dict: fills[{t,px,notional,layer}], closes[{t,px,qty,layer}], closed(bool), pnl (USDT, đã trừ phí), notional, ret (% / notional)."""
    sym = basket["sym"]
    a = a or candle_arrays(sym)
    if a is None:
        return None
    f0 = basket["fills"][0]
    i0 = int(np.searchsorted(a["t"], f0["t"], side="right")) - 1
    i_end = min(len(a["t"]) - 1, int(np.searchsorted(a["t"], basket["t1"] + horizon_min * MIN, side="right")) - 1)
    if i0 < 0 or i_end <= i0:
        return None
    P = pvec(params)
    fee = float(params.get("fee_bps", PARAM_DEFAULT["fee_bps"])) / 1e4
    s = 1 if basket["side"] == "long" else -1
    f_bar = np.zeros(MAXL, np.int64); f_px = np.zeros(MAXL); f_not = np.zeros(MAXL)
    c_bar = np.zeros(2 * MAXL, np.int64); c_px = np.zeros(2 * MAXL); c_qty = np.zeros(2 * MAXL); c_lay = np.zeros(2 * MAXL, np.int64)
    scale = atr_scale(sym)
    n0 = basket["tranches"][0]["notional"]  # notional tranche đầu (gồm các fill chia nhỏ trong 15 phút đầu)
    nf, nc, closed = _run(a["o"], a["h"], a["l"], a["c"], scale, i0, i_end, s, f0["px"], n0, P,
                          f_bar, f_px, f_not, c_bar, c_px, c_qty, c_lay)
    fills = [dict(t=int(f0["t"]) if k == 0 else int(a["t"][f_bar[k]]), px=float(f_px[k]), notional=float(f_not[k]), layer=k) for k in range(nf)]
    closes = [dict(t=int(a["t"][c_bar[k]]), px=float(c_px[k]), qty=float(c_qty[k]), layer=int(c_lay[k])) for k in range(nc)]
    pnl = 0.0
    for cl in closes:
        fp = f_px[cl["layer"]]
        pnl += cl["qty"] * (cl["px"] - fp) * s - fee * cl["qty"] * (cl["px"] + fp)
    notional = float(f_not[:nf].sum())
    return dict(fills=fills, closes=closes, closed=bool(closed), pnl=pnl, notional=notional, ret=pnl / notional * 100)
