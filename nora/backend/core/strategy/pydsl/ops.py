"""`self.op.<tên>(...)` — 30 operator chuỗi thời gian của xnoquant, ngữ nghĩa CAUSAL (không shift âm, không bfill).

Quy ước: so sánh có NaN -> False (không có tín hiệu từ dữ liệu thiếu); chuỗi bool không có NaN; vô cực -> NaN.
Không có xnoquant để đối chiếu từng hàm: ngữ nghĩa lấy theo tên + TA-Lib/pandas; điểm chưa chắc ghi ở docs/bmad/p7_python_strategies.md §3.
"""
from typing import Dict

import numpy as np

from backend.core.strategy.pydsl.spec import A, B, F, I, S, Spec


def _num(x, n: int) -> np.ndarray:
    a = np.asarray(x, dtype="float64")
    return np.full(n, float(a)) if a.ndim == 0 else a


def _bool(x, n: int) -> np.ndarray:
    a = np.asarray(x, dtype=bool)
    return np.full(n, bool(a)) if a.ndim == 0 else a


def _shift_num(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full(x.shape[0], np.nan)
    if k < x.shape[0]:
        out[k:] = x[:x.shape[0] - k]
    return out


def _shift_bool(x: np.ndarray, k: int) -> np.ndarray:
    out = np.zeros(x.shape[0], dtype=bool)
    if k < x.shape[0]:
        out[k:] = x[:x.shape[0] - k]
    return out


def _fin(x: np.ndarray) -> np.ndarray:
    return np.where(np.isfinite(x), x, np.nan)


def _arange_last(mask: np.ndarray) -> np.ndarray:
    """Chỉ số nến gần nhất (<= t) mà mask đúng; -1 nếu chưa có."""
    return np.maximum.accumulate(np.where(mask, np.arange(mask.shape[0]), -1))


# ─── cắt / so sánh ──────────────────────────────────────────────────────────

def _above(a, b):
    return (a > b) & (_shift_num(a, 1) <= _shift_num(b, 1))


def _below(a, b):
    return (a < b) & (_shift_num(a, 1) >= _shift_num(b, 1))


def o_crossed_above(n, a, b):
    with np.errstate(invalid="ignore"):
        return _above(_num(a, n), _num(b, n))


def o_crossed_below(n, a, b):
    with np.errstate(invalid="ignore"):
        return _below(_num(a, n), _num(b, n))


def o_crossed(n, a, b):
    a, b = _num(a, n), _num(b, n)
    with np.errstate(invalid="ignore"):
        return _above(a, b) | _below(a, b)


def o_crossed_above_value(n, a, value):
    return o_crossed_above(n, a, value)


def o_crossed_below_value(n, a, value):
    return o_crossed_below(n, a, value)


# ─── dịch / thay đổi ────────────────────────────────────────────────────────

def o_current(n, x):
    return x


def o_shift(n, x, periods):
    if np.asarray(x).dtype == bool:
        return _shift_bool(_bool(x, n), int(periods))
    return _shift_num(_num(x, n), int(periods))


def o_diff(n, x, periods):
    x = _num(x, n)
    return x - _shift_num(x, int(periods))


def o_pct_change(n, x, periods):
    x = _num(x, n)
    with np.errstate(all="ignore"):
        return _fin(x / _shift_num(x, int(periods)) - 1.0)


def o_rising(n, x, periods):
    x = _num(x, n)
    out = np.ones(n, dtype=bool)
    with np.errstate(invalid="ignore"):
        for i in range(int(periods)):
            out &= _shift_num(x, i) > _shift_num(x, i + 1)
    return out


def o_falling(n, x, periods):
    x = _num(x, n)
    out = np.ones(n, dtype=bool)
    with np.errstate(invalid="ignore"):
        for i in range(int(periods)):
            out &= _shift_num(x, i) < _shift_num(x, i + 1)
    return out


# ─── làm sạch / biến đổi ────────────────────────────────────────────────────

def o_fillna(n, x, value):
    x = _num(x, n)
    return np.where(np.isnan(x), _num(value, n), x)


def o_ffill(n, x):
    x = _num(x, n)
    idx = _arr_valid(x)
    return np.where(idx >= 0, x[np.maximum(idx, 0)], np.nan)


def _arr_valid(x: np.ndarray) -> np.ndarray:
    return _arange_last(~np.isnan(x))


def o_abs(n, x):
    return np.abs(_num(x, n))


def o_clip(n, x, lower, upper):
    x = _num(x, n)
    out = x
    with np.errstate(invalid="ignore"):
        if lower is not None:
            out = np.where(out < lower, lower, out)
        if upper is not None:
            out = np.where(out > upper, upper, out)
    return out


def o_isna(n, x):
    return np.isnan(_num(x, n))


def o_notna(n, x):
    return ~np.isnan(_num(x, n))


def o_isfinite(n, x):
    return np.isfinite(_num(x, n))


def o_zero_ifna(n, x):
    x = _num(x, n)
    return np.where(np.isnan(x), 0.0, x)


def o_sign(n, x):
    x = _num(x, n)
    return np.where(np.isnan(x), np.nan, np.sign(x))


def o_replace(n, x, to_replace, value):
    x = _num(x, n)
    with np.errstate(invalid="ignore"):
        return np.where(x == to_replace, float(value), x)


def o_between(n, x, lower, upper):
    x = _num(x, n)
    with np.errstate(invalid="ignore"):
        return (x >= _num(lower, n)) & (x <= _num(upper, n))


def o_where(n, cond, a, b):
    ra, rb = np.asarray(a), np.asarray(b)
    if ra.dtype == bool and rb.dtype == bool:
        return np.where(_bool(cond, n), _bool(a, n), _bool(b, n))
    return np.where(_bool(cond, n), _num(a, n), _num(b, n))


# ─── trạng thái theo thời gian ──────────────────────────────────────────────

def o_value_when(n, cond, x):
    cond, x = _bool(cond, n), _num(x, n)
    idx = _arange_last(cond)
    return np.where(idx >= 0, x[np.maximum(idx, 0)], np.nan)


def o_bars_since(n, cond):
    cond = _bool(cond, n)
    idx = _arange_last(cond)
    return np.where(idx >= 0, np.arange(n) - idx, np.nan)


def o_hold_for(n, cond, periods):
    """True trong `periods` nến kể từ nến cond đúng gần nhất (gồm chính nến đó)."""
    c = np.cumsum(_bool(cond, n).astype("int64"))
    return _hold(c, int(periods)) > 0


def _hold(c: np.ndarray, k: int) -> np.ndarray:
    prev = np.zeros(c.shape[0], dtype="int64")
    if k < c.shape[0]:
        prev[k:] = c[:c.shape[0] - k]
    return c - prev


# ─── logic ──────────────────────────────────────────────────────────────────

def o_and_(n, a, b):
    return _bool(a, n) & _bool(b, n)


def o_or_(n, a, b):
    return _bool(a, n) | _bool(b, n)


def o_not_(n, a):
    return ~_bool(a, n)


def _ret_shift(p):
    return "bool" if p.get("x_kind") == "bool" else "num"


def _ret_where(p):
    return "bool" if p.get("a_kind") == "bool" and p.get("b_kind") == "bool" else "num"


def _op(name, params, fn, ret="num", warm=None, doc=""):
    from backend.core.strategy.pydsl.spec import OP_SPECS_DATA
    meta = OP_SPECS_DATA.get(name, {})
    return Spec(name=name, params=params, fn=fn, ret=ret, nout=1, warm=warm or (lambda p: 0),
                doc=doc or meta.get("meaning_vi", ""),
                label_vi=meta.get("label_vi", ""),
                formula=meta.get("formula", ""),
                meaning_vi=meta.get("meaning_vi", ""),
                read_vi=meta.get("read_vi", ""),
                warmup=meta.get("warmup", 0),
                category=meta.get("category", ""))


_PER = lambda d=1: I("periods", d, lo=1, hi=5000)   # noqa: E731  (periods >= 1: không nhìn tương lai)

OPS: Dict[str, Spec] = {s.name: s for s in [
    _op("crossed", [S("a"), S("b")], o_crossed, "bool", lambda p: 1, "a cắt b theo một trong hai chiều"),
    _op("crossed_above", [S("a"), S("b")], o_crossed_above, "bool", lambda p: 1, "a cắt LÊN b: a > b và a[-1] <= b[-1]"),
    _op("crossed_below", [S("a"), S("b")], o_crossed_below, "bool", lambda p: 1, "a cắt XUỐNG b: a < b và a[-1] >= b[-1]"),
    _op("current", [A("x")], o_current, _ret_shift, doc="giá trị nến hiện tại (đồng nhất)"),
    _op("previous", [A("x"), _PER()], o_shift, _ret_shift, lambda p: int(p.get("periods", 1)), "giá trị k nến trước"),
    _op("shift", [A("x"), _PER()], o_shift, _ret_shift, lambda p: int(p.get("periods", 1)), "dịch k >= 1 nến về quá khứ"),
    _op("diff", [S("x"), _PER()], o_diff, "num", lambda p: int(p.get("periods", 1))),
    _op("pct_change", [S("x"), _PER()], o_pct_change, "num", lambda p: int(p.get("periods", 1))),
    _op("rising", [S("x"), _PER()], o_rising, "bool", lambda p: int(p.get("periods", 1)), "tăng liên tục k nến"),
    _op("falling", [S("x"), _PER()], o_falling, "bool", lambda p: int(p.get("periods", 1)), "giảm liên tục k nến"),
    _op("fillna", [S("x"), S("value", 0.0)], o_fillna, "num", doc="thay NaN bằng value"),
    _op("ffill", [S("x")], o_ffill, "num", doc="điền NaN bằng giá trị hợp lệ gần nhất trước đó"),
    _op("abs", [S("x")], o_abs, "num"),
    _op("clip", [S("x"), F("lower", None), F("upper", None)], o_clip, "num", doc="kẹp trong [lower, upper]"),
    _op("isna", [S("x")], o_isna, "bool"),
    _op("notna", [S("x")], o_notna, "bool"),
    _op("isfinite", [S("x")], o_isfinite, "bool"),
    _op("zero_ifna", [S("x")], o_zero_ifna, "num", doc="NaN -> 0"),
    _op("sign", [S("x")], o_sign, "num"),
    _op("replace", [S("x"), F("to_replace"), F("value")], o_replace, "num", doc="thay giá trị to_replace bằng value"),
    _op("between", [S("x"), S("lower"), S("upper")], o_between, "bool", doc="lower <= x <= upper"),
    _op("where", [B("cond"), A("a"), A("b")], o_where, _ret_where, doc="cond ? a : b"),
    _op("value_when", [B("cond"), S("x")], o_value_when, "num", doc="giá trị x tại nến gần nhất cond đúng"),
    _op("bars_since", [B("cond")], o_bars_since, "num", doc="số nến kể từ lần cond đúng gần nhất (0 = nến này, NaN = chưa từng)"),
    _op("hold_for", [B("cond"), _PER()], o_hold_for, "bool", lambda p: int(p.get("periods", 1)), "giữ True k nến kể từ lần cond đúng gần nhất (gồm nến đó)"),
    _op("crossed_above_value", [S("a"), F("value")], o_crossed_above_value, "bool", lambda p: 1, "a cắt LÊN một mức hằng số"),
    _op("crossed_below_value", [S("a"), F("value")], o_crossed_below_value, "bool", lambda p: 1, "a cắt XUỐNG một mức hằng số"),
    _op("and_", [B("a"), B("b")], o_and_, "bool"),
    _op("or_", [B("a"), B("b")], o_or_, "bool"),
    _op("not_", [B("a")], o_not_, "bool"),
]}

assert len(OPS) == 30, len(OPS)


def evaluate(spec: Spec, n: int, **kw):
    return spec.fn(n, **kw)
