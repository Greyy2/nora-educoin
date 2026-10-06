"""Đặc trưng + sinh tín hiệu vào lệnh (LEVEL B) trên lưới 15 phút, không look-ahead (chỉ dùng nến 15m đã đóng).

Đặc trưng (đều tính tại thời điểm ĐÓNG nến 15m):
  ret24/ret4/ret1 = % thay đổi giá so với 24h/4h/1h trước, chuẩn hoá z = x / std theo từng mã (std trên toàn mẫu nến, không dùng nhãn)
  dma = % lệch khỏi SMA 24h (96 nến 15m), chuẩn hoá z như trên;  rsi = RSI(14) trên nến 1h đã đóng, trừ 50.
Luật tín hiệu: mode 'contra' (ngược đà): long khi x <= -thr, short khi x >= +thr; 'mom' (theo đà) ngược lại.
Cạnh lên (rising edge) + cooldown theo (mã, chiều). Cổng giờ (giờ VN) tuỳ chọn.
"""
import numpy as np
import pandas as pd

from load import candle_arrays

_FEAT = {}
H15 = 15 * 60_000


def feats(sym):
    """DataFrame đặc trưng tại thời điểm đóng nến 15m: index t_close (ms)."""
    if sym in _FEAT:
        return _FEAT[sym]
    a = candle_arrays(sym)
    if a is None:
        _FEAT[sym] = None; return None
    s = pd.Series(a["c"], index=pd.to_datetime(a["t"], unit="ms"))
    c15 = s.resample("15min").last().dropna()
    f = pd.DataFrame(index=c15.index)
    f["ret24"] = (c15 / c15.shift(96) - 1) * 100
    f["ret4"] = (c15 / c15.shift(16) - 1) * 100
    f["ret1"] = (c15 / c15.shift(4) - 1) * 100
    f["dma"] = (c15 / c15.rolling(96).mean() - 1) * 100
    c1h = s.resample("1h").last().dropna()
    d = c1h.diff(); up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100 - 100 / (1 + up / dn.replace(0, np.nan))) - 50
    # rsi của giờ đã đóng: bar giờ k hoàn tất ở k+1h -> dịch 1h rồi ffill theo nến 15m
    rsi = rsi.copy(); rsi.index = rsi.index + pd.Timedelta(hours=1)
    f["rsi"] = rsi.reindex(f.index, method="ffill")
    for k in ("ret24", "ret4", "ret1", "dma"):
        f["z_" + k] = f[k] / f[k].std()
    f["t_close"] = (f.index.astype("int64") // 10**6 + H15).astype(np.int64)
    f["hour_vn"] = ((f["t_close"] // 3_600_000 + 7) % 24).astype(int)
    f = f.dropna()
    _FEAT[sym] = f
    return f


FEATURES = ["z_ret24", "z_ret4", "z_ret1", "z_dma", "rsi"]


def signals(sym, rule):
    """Trả (times_long, times_short) mảng ms (đóng nến 15m) cho luật rule=dict(feat,thr,mode,hours,cool_h)."""
    f = feats(sym)
    if f is None:
        return None
    x = f[rule["feat"]].values
    thr = rule["thr"]
    lo = x <= -thr; hi = x >= thr
    if rule["mode"] == "mom":
        lo, hi = hi, lo  # long khi x>=thr
    hrs = rule.get("hours")
    if hrs is not None:
        m = np.isin(f["hour_vn"].values, hrs)
        lo = lo & m; hi = hi & m
    out = []
    cool = rule.get("cool_h", 6) * 3_600_000
    for cond in (lo, hi):
        edge = cond & ~np.r_[False, cond[:-1]]
        t = f["t_close"].values[edge]
        keep = []
        last = -10**18
        for ti in t:
            if ti - last >= cool:
                keep.append(ti); last = ti
        out.append(np.array(keep, dtype=np.int64))
    return out[0], out[1]
