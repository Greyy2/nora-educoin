"""P7 — DSL: MỌI feature và operator đều CAUSAL (prefix-invariance: f(df)[:t] == f(df[:t])), NaN ở giai đoạn khởi động, không inf.
Cùng mẫu với test_signals_strategies.test_kernel_is_causal_prefix_invariant."""
import numpy as np
import pandas as pd
import pytest

from backend.alpha.compile import compile_code
from backend.alpha.dsl import indicator as features, indicator as ops
from backend.alpha.dsl.indicator import REQUIRED

N = 700
CUTS = (120, 333, 520, 699)


def _df(n=N, seed=0):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    return {"open": open_, "high": high, "low": low, "close": close, "volume": rng.uniform(1, 100, n)}


def _args(spec, data, n, bools):
    kw = {}
    for p in spec.params:
        if p.kind in ("num", "any"):
            kw[p.name] = {"real": data["close"], "x": data["close"], "a": data["close"], "b": data["open"]}.get(p.name, data.get(p.name))
            if kw[p.name] is None:
                kw[p.name] = data["close"]
            if p.name == "value":
                kw[p.name] = 0.0
        elif p.kind == "bool":
            kw[p.name] = bools[0] if p.name in ("cond", "a") else bools[1]
        elif p.kind == "int":
            kw[p.name] = 3 if p.default is REQUIRED else min(int(p.default), 14)
        elif p.kind == "float":
            kw[p.name] = (100.0 if p.default is REQUIRED else p.default)
        else:
            kw[p.name] = 0
    return kw


def _cut(kw, t):
    return {k: (v[:t] if isinstance(v, np.ndarray) else v) for k, v in kw.items()}


def _same(a, b, msg):
    a, b = np.asarray(a), np.asarray(b)
    if a.dtype == bool:
        assert (a == b).all(), msg
    else:
        np.testing.assert_allclose(a, b, rtol=1e-9, atol=1e-12, equal_nan=True, err_msg=msg)


@pytest.mark.parametrize("name", sorted(features.FEATURES))
def test_feature_is_causal_prefix_invariant(name):
    spec = features.FEATURES[name]
    data = _df()
    bools = (data["close"] > data["open"], data["high"] > data["close"])
    kw = _args(spec, data, N, bools)
    full = features.evaluate_feature(spec, N, **kw)
    outs = full if spec.nout > 1 else (full,)
    for t in CUTS:
        part = features.evaluate_feature(spec, t, **_cut(kw, t))
        parts = part if spec.nout > 1 else (part,)
        for i, (f, p) in enumerate(zip(outs, parts)):
            _same(p, f[:t], f"{name}[{i}] dùng dữ liệu tương lai (khác khi cắt tại {t})")
    for f in outs:
        assert not np.isinf(f).any(), f"{name}: có vô cực"
        assert np.isnan(f[0]) or name in ("trange", "typprice", "hlc3", "ohlc4", "range_pct", "obv"), f"{name}: nến đầu phải là NaN (chưa đủ dữ liệu)"
        assert np.isfinite(f[-50:]).mean() > 0.9, f"{name}: sau khởi động phải có giá trị"


@pytest.mark.parametrize("name", sorted(ops.OPS))
def test_operator_is_causal_prefix_invariant(name):
    spec = ops.OPS[name]
    data = _df(seed=3)
    data["close"] = np.where(np.arange(N) % 37 == 0, np.nan, data["close"])     # có NaN giữa chuỗi: ffill/fillna/isna/bars_since phải xử lý
    bools = (np.nan_to_num(data["close"], nan=0) > np.nan_to_num(data["open"], nan=0), data["high"] > data["open"] * 1.001)
    kw = _args(spec, data, N, bools)
    if name in ("clip",):
        kw.update(lower=90.0, upper=110.0)
    if name == "replace":
        kw.update(to_replace=100.0, value=1.0)
    if name in ("where",):
        kw.update(a=data["high"], b=data["low"])
    full = np.asarray(spec.fn(N, **kw))
    for t in CUTS:
        part = np.asarray(spec.fn(t, **_cut(kw, t)))
        _same(part, full[:t], f"{name} dùng dữ liệu tương lai (khác khi cắt tại {t})")
    if spec.ret == "bool":
        assert full.dtype == bool
    elif full.dtype != bool:
        assert not np.isinf(full).any()


def test_prefix_check_detects_a_lookahead_feature():
    """Chính phép kiểm này phải bắt được hàm nhìn tương lai (như test_prefix_check_detects_a_lookahead_kernel)."""
    x = _df()["close"]
    lead = lambda a, n: np.r_[a[1:], np.nan][:n]  # noqa: E731  (dùng nến t+1)
    full = lead(x, N)
    with pytest.raises(AssertionError):
        _same(lead(x[:333], 333), full[:333], "lookahead")


def test_all_30_operators_present():
    assert sorted(ops.OPS) == sorted(
        "crossed crossed_above crossed_below current previous shift diff pct_change rising falling fillna ffill abs clip isna notna isfinite "
        "zero_ifna sign replace between where value_when bars_since hold_for crossed_above_value crossed_below_value and_ or_ not_".split())


CODE_MIX = '''
class Mix(SimpleAlgorithm):
    timeframe = "1h"
    def __algorithm__(self):
        close = self.data.pv_close
        high = self.data.pv_high
        low = self.data.pv_low
        vol = self.data.pv_volume
        macd, sig, hist = self.feat.macd(close, 12, 26, 9)
        up, mid, lo = self.feat.bbands(close, timeperiod=20)
        rsi = self.feat.rsi(close, timeperiod=14)
        slope = self.feat.linearreg_slope(close, timeperiod=10)
        enter = self.op.crossed_above(close, up) | (self.op.rising(hist, 2) & (rsi < 40))
        keep = self.op.hold_for(enter, 3)
        exit_ = (close < mid) | self.op.crossed_below(macd, sig)
        z = self.feat.zscore(vol, 20).fillna(0)
        self.set_positions(exit_, position=0)
        self.set_positions(keep & (slope > 0) & (z > -1), position=0.5)
        self.set_positions(self.op.crossed_below(close, lo), position=-1)
'''


def test_program_columns_are_causal():
    """Cả chương trình (cột py_*_le/lx/se/sx) cũng prefix-invariant."""
    prog = compile_code(CODE_MIX)
    d = _df(seed=5)
    df = pd.DataFrame({**d, "open_time": np.arange(N, dtype=np.int64) * 3_600_000})
    full = prog.columns_for(df)
    for t in CUTS:
        part = prog.columns_for(df.iloc[:t].reset_index(drop=True))
        for k in full:
            np.testing.assert_array_equal(part[k], full[k][:t], err_msg=f"{k} khác khi cắt tại {t}")
    assert full["le"].sum() > 0 and full["se"].sum() > 0
