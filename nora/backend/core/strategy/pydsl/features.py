"""`self.feat.<tên>(...)` — chỉ báo kỹ thuật, tên và chữ ký theo TA-Lib / xnoquant.

Chỉ báo trùng với kernel Nora (sma ema rsi atr natr adx roc bbands donchian volume_z zscore trange) GỌI THẲNG hàm trong
backend/core/signals/kernels.py trên một DataFrame dựng từ các chuỗi đầu vào: đầu vào là cột giá gốc thì ra đúng từng bit giá trị kernel Nora,
đầu vào là chuỗi bất kỳ thì cùng công thức trên chuỗi đó. Mọi hàm CAUSAL: giá trị tại nến t chỉ dùng nến <= t (test_pydsl_causal.py).
Giai đoạn khởi động trả NaN; vô cực đổi thành NaN.
"""
from typing import Dict

import numpy as np
import pandas as pd
from numba import njit

from backend.core.signals import kernels as K
from backend.core.strategy.pydsl.spec import A, F, I, MA, S, Spec  # noqa: F401


def _arr(x, n: int) -> np.ndarray:
    """Chuỗi / hằng số -> mảng float64 dài n."""
    a = np.asarray(x, dtype="float64")
    return np.full(n, float(a)) if a.ndim == 0 else a


def _clean(x) -> np.ndarray:
    a = np.asarray(x, dtype="float64")
    return np.where(np.isfinite(a), a, np.nan)


def _frame(n: int, **cols) -> pd.DataFrame:
    return pd.DataFrame({k: _arr(v, n) for k, v in cols.items()})


def _roll(x: np.ndarray, n: int, how: str, ddof: int = 0) -> np.ndarray:
    r = pd.Series(x).rolling(int(n), min_periods=int(n))
    return getattr(r, how)(ddof=ddof).to_numpy() if how in ("std", "var") else getattr(r, how)().to_numpy()


def _shift(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full(x.shape[0], np.nan)
    if k < x.shape[0]:
        out[k:] = x[:x.shape[0] - k]
    return out


# ─── numba: cửa sổ trượt cần vòng lặp riêng ─────────────────────────────────

@njit(cache=True)
def _wma(x, n):
    out = np.full(x.shape[0], np.nan)
    wsum = n * (n + 1) / 2.0
    for i in range(n - 1, x.shape[0]):
        s = 0.0
        ok = True
        for j in range(n):
            v = x[i - n + 1 + j]
            if v != v:
                ok = False
                break
            s += v * (j + 1)
        if ok:
            out[i] = s / wsum
    return out


@njit(cache=True)
def _meandev(x, n):
    out = np.full(x.shape[0], np.nan)
    for i in range(n - 1, x.shape[0]):
        s = 0.0
        ok = True
        for j in range(n):
            v = x[i - n + 1 + j]
            if v != v:
                ok = False
                break
            s += v
        if not ok:
            continue
        m = s / n
        d = 0.0
        for j in range(n):
            d += abs(x[i - n + 1 + j] - m)
        out[i] = d / n
    return out


@njit(cache=True)
def _linreg(x, n):
    slope = np.full(x.shape[0], np.nan)
    end = np.full(x.shape[0], np.nan)
    sx = n * (n - 1) / 2.0
    sxx = (n - 1) * n * (2 * n - 1) / 6.0
    den = n * sxx - sx * sx
    for i in range(n - 1, x.shape[0]):
        sy = 0.0
        sxy = 0.0
        ok = True
        for j in range(n):
            v = x[i - n + 1 + j]
            if v != v:
                ok = False
                break
            sy += v
            sxy += j * v
        if not ok:
            continue
        m = (n * sxy - sx * sy) / den
        b = (sy - m * sx) / n
        slope[i] = m
        end[i] = b + m * (n - 1)
    return slope, end


# ─── hàm tính (đối số: mảng đã căn độ dài n, hằng số) ────────────────────────

def f_sma(n, real, timeperiod):
    return K.sma(_frame(n, close=real), timeperiod).to_numpy()


def f_ema(n, real, timeperiod):
    return K.ema(_frame(n, close=real), timeperiod).to_numpy()


def f_dema(n, real, timeperiod):
    e1 = K.ema(_frame(n, close=real), timeperiod).to_numpy()
    e2 = K.ema(_frame(n, close=e1), timeperiod).to_numpy()
    return 2.0 * e1 - e2


def f_tema(n, real, timeperiod):
    e1 = K.ema(_frame(n, close=real), timeperiod).to_numpy()
    e2 = K.ema(_frame(n, close=e1), timeperiod).to_numpy()
    e3 = K.ema(_frame(n, close=e2), timeperiod).to_numpy()
    return 3.0 * e1 - 3.0 * e2 + e3


def f_wma(n, real, timeperiod):
    return _wma(_arr(real, n), int(timeperiod))


def f_rsi(n, real, timeperiod):
    return K.rsi(_frame(n, close=real), timeperiod).to_numpy()


def f_atr(n, high, low, close, timeperiod):
    return K.atr(_frame(n, high=high, low=low, close=close), timeperiod).to_numpy()


def f_natr(n, high, low, close, timeperiod):
    return K.natr(_frame(n, high=high, low=low, close=close), timeperiod).to_numpy()


def f_adx(n, high, low, close, timeperiod):
    return K.adx(_frame(n, high=high, low=low, close=close), timeperiod).to_numpy()


def _di(n, high, low, close, timeperiod):
    df = _frame(n, high=high, low=low, close=close)
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr_n = K._rma(K._true_range(df), int(timeperiod))
    return 100 * K._rma(plus_dm, int(timeperiod)) / atr_n, 100 * K._rma(minus_dm, int(timeperiod)) / atr_n


def f_plus_di(n, high, low, close, timeperiod):
    return _di(n, high, low, close, timeperiod)[0].to_numpy()


def f_minus_di(n, high, low, close, timeperiod):
    return _di(n, high, low, close, timeperiod)[1].to_numpy()


def f_macd(n, real, fastperiod, slowperiod, signalperiod):
    fast = K.ema(_frame(n, close=real), fastperiod).to_numpy()
    slow = K.ema(_frame(n, close=real), slowperiod).to_numpy()
    line = fast - slow
    sig = K.ema(_frame(n, close=line), signalperiod).to_numpy()
    return line, sig, line - sig


def f_bbands(n, real, timeperiod, nbdevup, nbdevdn, matype):
    df = _frame(n, close=real)
    return (K.bbu(df, timeperiod, nbdevup).to_numpy(), K.bbm(df, timeperiod, 1.0).to_numpy(),
            K.bbl(df, timeperiod, nbdevdn).to_numpy())


def f_roc(n, real, timeperiod):
    return K.roc(_frame(n, close=real), timeperiod).to_numpy()


def f_rocp(n, real, timeperiod):
    x = _arr(real, n)
    return x / _shift(x, int(timeperiod)) - 1.0


def f_momentum(n, real, timeperiod):
    x = _arr(real, n)
    return x - _shift(x, int(timeperiod))


def f_stddev(n, real, timeperiod, nbdev):
    return _roll(_arr(real, n), timeperiod, "std", ddof=0) * float(nbdev)


def f_var(n, real, timeperiod, nbdev):
    return _roll(_arr(real, n), timeperiod, "var", ddof=0) * float(nbdev)


def f_cci(n, high, low, close, timeperiod):
    tp = (_arr(high, n) + _arr(low, n) + _arr(close, n)) / 3.0
    ma = _roll(tp, timeperiod, "mean")
    return (tp - ma) / (0.015 * _meandev(tp, int(timeperiod)))


def f_willr(n, high, low, close, timeperiod):
    hh = _roll(_arr(high, n), timeperiod, "max")
    ll = _roll(_arr(low, n), timeperiod, "min")
    return -100.0 * (hh - _arr(close, n)) / (hh - ll)


def f_mfi(n, high, low, close, volume, timeperiod):
    tp = (_arr(high, n) + _arr(low, n) + _arr(close, n)) / 3.0
    mf = tp * _arr(volume, n)
    prev = _shift(tp, 1)
    pos = np.where(tp > prev, mf, 0.0)
    neg = np.where(tp < prev, mf, 0.0)
    pos[0] = neg[0] = np.nan   # nến đầu chưa có thay đổi giá
    ps, ns = _roll(pos, timeperiod, "sum"), _roll(neg, timeperiod, "sum")
    return 100.0 * ps / (ps + ns)


def f_obv(n, real, volume):
    c, v = _arr(real, n), _arr(volume, n)
    step = np.zeros(n)
    step[1:] = np.sign(c[1:] - c[:-1]) * v[1:]
    step[0] = v[0]
    return np.cumsum(step)


def f_stoch(n, high, low, close, fastk_period, slowk_period, slowk_matype, slowd_period, slowd_matype):
    hh = _roll(_arr(high, n), fastk_period, "max")
    ll = _roll(_arr(low, n), fastk_period, "min")
    fastk = 100.0 * (_arr(close, n) - ll) / (hh - ll)
    slowk = _roll(fastk, slowk_period, "mean")
    return slowk, _roll(slowk, slowd_period, "mean")


def f_donchian_upper(n, high, timeperiod):
    return K.dch(_frame(n, high=high), timeperiod).to_numpy()


def f_donchian_lower(n, low, timeperiod):
    return K.dcl(_frame(n, low=low), timeperiod).to_numpy()


def f_linearreg_slope(n, real, timeperiod):
    return _linreg(_arr(real, n), int(timeperiod))[0]


def f_linearreg(n, real, timeperiod):
    return _linreg(_arr(real, n), int(timeperiod))[1]


def f_rolling_mean(n, real, window):
    return _roll(_arr(real, n), window, "mean")


def f_rolling_std(n, real, window):
    return _roll(_arr(real, n), window, "std", ddof=1)


def f_rolling_max(n, real, window):
    return _roll(_arr(real, n), window, "max")


def f_rolling_min(n, real, window):
    return _roll(_arr(real, n), window, "min")


def f_rolling_sum(n, real, window):
    return _roll(_arr(real, n), window, "sum")


def f_zscore(n, real, window):
    return K.bbz(_frame(n, close=real), window).to_numpy()


def f_returns(n, real, periods):
    x = _arr(real, n)
    return x / _shift(x, int(periods)) - 1.0


def f_log_returns(n, real, periods):
    x = _arr(real, n)
    with np.errstate(all="ignore"):
        return np.log(x / _shift(x, int(periods)))


def f_trange(n, high, low, close):
    return K._true_range(_frame(n, high=high, low=low, close=close)).to_numpy()


def f_typprice(n, high, low, close):
    return (_arr(high, n) + _arr(low, n) + _arr(close, n)) / 3.0


def f_ohlc4(n, open, high, low, close):
    return (_arr(open, n) + _arr(high, n) + _arr(low, n) + _arr(close, n)) / 4.0


def f_range_pct(n, high, low, close):
    return (_arr(high, n) - _arr(low, n)) / _arr(close, n) * 100.0


def f_volume_z(n, volume, timeperiod):
    return K.volz(_frame(n, volume=volume), timeperiod).to_numpy()


# ─── đăng ký ────────────────────────────────────────────────────────────────
_TP = lambda d=14: I("timeperiod", d)   # noqa: E731
_HLC = [S("high"), S("low"), S("close")]


def _w(mult=1.0, extra=1, key="timeperiod"):
    """Ước lượng số nến khởi động: mult × chu kỳ + extra (cùng kiểu kernels._w)."""
    return lambda p: int(float(p.get(key, 0)) * mult) + extra


def _sum_w(*keys, extra=1):
    return lambda p: int(sum(float(p.get(k, 0)) for k in keys)) + extra


def _spec(name, params, fn, nout=1, warm=None, doc=""):
    from backend.core.strategy.pydsl.spec import FEATURE_SPECS_DATA
    meta = FEATURE_SPECS_DATA.get(name, {})
    return Spec(name=name, params=params, fn=fn, ret="num", nout=nout, warm=warm or _w(),
                doc=doc or meta.get("meaning_vi", ""),
                label_vi=meta.get("label_vi", ""),
                formula=meta.get("formula", ""),
                meaning_vi=meta.get("meaning_vi", ""),
                read_vi=meta.get("read_vi", ""),
                warmup=meta.get("warmup", 0),
                category=meta.get("category", ""))


FEATURES: Dict[str, Spec] = {s.name: s for s in [
    _spec("sma", [S("real"), _TP(30)], f_sma, warm=_w(1, 0), doc="Trung bình cộng n nến"),
    _spec("ema", [S("real"), _TP(30)], f_ema, warm=_w(3, 0), doc="Trung bình mũ (seed SMA như TradingView)"),
    _spec("dema", [S("real"), _TP(30)], f_dema, warm=_w(6, 0), doc="Double EMA"),
    _spec("tema", [S("real"), _TP(30)], f_tema, warm=_w(9, 0), doc="Triple EMA"),
    _spec("wma", [S("real"), _TP(30)], f_wma, warm=_w(1, 0), doc="Trung bình trọng số tuyến tính"),
    _spec("rsi", [S("real"), _TP(14)], f_rsi, warm=_w(4, 1), doc="RSI Wilder"),
    _spec("atr", _HLC + [_TP(14)], f_atr, warm=_w(4, 1), doc="ATR Wilder"),
    _spec("natr", _HLC + [_TP(14)], f_natr, warm=_w(4, 1), doc="ATR theo % giá"),
    _spec("adx", _HLC + [_TP(14)], f_adx, warm=_w(4, 1), doc="ADX Wilder"),
    _spec("plus_di", _HLC + [_TP(14)], f_plus_di, warm=_w(4, 1), doc="+DI Wilder"),
    _spec("minus_di", _HLC + [_TP(14)], f_minus_di, warm=_w(4, 1), doc="-DI Wilder"),
    _spec("macd", [S("real"), I("fastperiod", 12), I("slowperiod", 26), I("signalperiod", 9)], f_macd, nout=3,
          warm=lambda p: int(3 * p.get("slowperiod", 26) + 3 * p.get("signalperiod", 9)), doc="MACD -> (macd, signal, hist)"),
    _spec("bbands", [S("real"), I("timeperiod", 5), F("nbdevup", 2.0, 0.0, 10.0), F("nbdevdn", 2.0, 0.0, 10.0), MA("matype")], f_bbands,
          nout=3, warm=_w(1, 0), doc="Bollinger -> (upper, middle, lower); độ lệch chuẩn tổng thể (ddof=0)"),
    _spec("roc", [S("real"), _TP(10)], f_roc, doc="% thay đổi so với n nến trước"),
    _spec("rocp", [S("real"), _TP(10)], f_rocp, doc="Tỉ lệ thay đổi so với n nến trước"),
    _spec("momentum", [S("real"), _TP(10)], f_momentum, doc="Chênh lệch so với n nến trước"),
    _spec("stddev", [S("real"), _TP(5), F("nbdev", 1.0, 0.0, 100.0)], f_stddev, warm=_w(1, 0), doc="Độ lệch chuẩn (ddof=0) × nbdev"),
    _spec("var", [S("real"), _TP(5), F("nbdev", 1.0, 0.0, 100.0)], f_var, warm=_w(1, 0), doc="Phương sai (ddof=0) × nbdev"),
    _spec("cci", _HLC + [_TP(14)], f_cci, warm=_w(1, 0), doc="Commodity Channel Index"),
    _spec("willr", _HLC + [_TP(14)], f_willr, warm=_w(1, 0), doc="Williams %R"),
    _spec("mfi", _HLC + [S("volume"), _TP(14)], f_mfi, doc="Money Flow Index"),
    _spec("obv", [S("real"), S("volume")], f_obv, warm=lambda p: 1, doc="On Balance Volume"),
    _spec("stoch", _HLC + [I("fastk_period", 5), I("slowk_period", 3), MA("slowk_matype"), I("slowd_period", 3), MA("slowd_matype")], f_stoch,
          nout=2, warm=_sum_w("fastk_period", "slowk_period", "slowd_period"), doc="Stochastic chậm -> (slowk, slowd)"),
    _spec("donchian_upper", [S("high"), _TP(20)], f_donchian_upper, doc="Đỉnh n nến TRƯỚC (không gồm nến hiện tại) — như kernel dch"),
    _spec("donchian_lower", [S("low"), _TP(20)], f_donchian_lower, doc="Đáy n nến TRƯỚC (không gồm nến hiện tại) — như kernel dcl"),
    _spec("linearreg_slope", [S("real"), _TP(14)], f_linearreg_slope, warm=_w(1, 0), doc="Độ dốc hồi quy tuyến tính n nến"),
    _spec("linearreg", [S("real"), _TP(14)], f_linearreg, warm=_w(1, 0), doc="Giá trị cuối đường hồi quy tuyến tính n nến"),
    _spec("rolling_mean", [S("real"), I("window", 20)], f_rolling_mean, warm=_w(1, 0, "window")),
    _spec("rolling_std", [S("real"), I("window", 20, lo=2)], f_rolling_std, warm=_w(1, 0, "window"), doc="Độ lệch chuẩn mẫu (ddof=1) như pandas"),
    _spec("rolling_max", [S("real"), I("window", 20)], f_rolling_max, warm=_w(1, 0, "window")),
    _spec("rolling_min", [S("real"), I("window", 20)], f_rolling_min, warm=_w(1, 0, "window")),
    _spec("rolling_sum", [S("real"), I("window", 20)], f_rolling_sum, warm=_w(1, 0, "window")),
    _spec("rolling_zscore", [S("real"), I("window", 20)], f_zscore, warm=_w(1, 0, "window"), doc="(x - TB) / độ lệch chuẩn n nến (như kernel bbz)"),
    _spec("zscore", [S("real"), I("window", 20)], f_zscore, warm=_w(1, 0, "window"), doc="Như rolling_zscore"),
    _spec("returns", [S("real"), I("periods", 1)], f_returns, warm=_w(1, 0, "periods"), doc="x / x[-k] - 1"),
    _spec("log_returns", [S("real"), I("periods", 1)], f_log_returns, warm=_w(1, 0, "periods"), doc="ln(x / x[-k])"),
    _spec("trange", _HLC, f_trange, warm=lambda p: 1, doc="True range"),
    _spec("typprice", _HLC, f_typprice, warm=lambda p: 0, doc="(H+L+C)/3"),
    _spec("hlc3", _HLC, f_typprice, warm=lambda p: 0, doc="(H+L+C)/3"),
    _spec("ohlc4", [S("open"), S("high"), S("low"), S("close")], f_ohlc4, warm=lambda p: 0, doc="(O+H+L+C)/4"),
    _spec("range_pct", _HLC, f_range_pct, warm=lambda p: 0, doc="(H-L)/C × 100"),
    _spec("volume_z", [S("volume"), _TP(20)], f_volume_z, warm=_w(1, 0), doc="Z-score khối lượng n nến (như kernel volz)"),
]}


def evaluate(spec: Spec, n: int, **kw):
    """Chạy một feature: mảng float64 (hoặc tuple mảng) dài n, vô cực -> NaN."""
    out = spec.fn(n, **kw)
    return tuple(_clean(o) for o in out) if spec.nout > 1 else _clean(out)
