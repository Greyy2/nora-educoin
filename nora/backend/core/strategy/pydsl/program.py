"""Chương trình DSL đã biên dịch: cây biểu thức (IR) đã kiểm loại + metadata; chạy trên DataFrame nến của MỘT tài sản.

`Program.explicit(df)` -> mức vị thế đặt tường minh tại từng nến (NaN = không quy tắc nào kích hoạt nến này).
`Program.target(df)`   -> mức mục tiêu target[t] ∈ [-1, 1]: giữ mức trước khi không quy tắc nào kích hoạt (ffill), đầu chuỗi = 0.
Cột tín hiệu cho engine (kernels.compute qua `py_<hash12>_<le|lx|se|sx>`):
    le = explicit > 0   (SỰ KIỆN vào long: quy tắc đặt mức > 0 ở nến này)     lx = target <= 0   (TRẠNG THÁI thoát long)
    se = explicit < 0   (vào short)                                            sx = target >= 0   (thoát short)
Vào lệnh theo sự kiện (không theo trạng thái target) để vị thế đã đóng bởi SL/TP/timeout/thanh lý KHÔNG tự vào lại ngay trên cùng
mức target cũ — giống cách chiến lược lõi dùng sự kiện cắt (cross_over).
"""
import hashlib
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from backend.core.strategy.pydsl import features as feat_mod
from backend.core.strategy.pydsl.errors import DslError
from backend.core.strategy.pydsl.spec import Spec

DATA_COLUMNS = ("open", "high", "low", "close", "volume")
TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "24h": 86_400_000}
KINDS = ("le", "lx", "se", "sx")
_CACHE_SIZE = 4


class Node:
    __slots__ = ("kind", "line", "col", "warm")

    def __init__(self, kind: str, line=None, col=None, warm: int = 0):
        self.kind, self.line, self.col, self.warm = kind, line, col, warm

    def ev(self, ctx: "Ctx"):
        key = id(self)
        if key not in ctx.memo:
            ctx.memo[key] = self._ev(ctx)
        return ctx.memo[key]

    def _ev(self, ctx: "Ctx"):
        raise NotImplementedError


class Ctx:
    def __init__(self, n: int, data: Dict[str, np.ndarray]):
        self.n, self.data, self.memo = n, data, {}


class Const(Node):
    __slots__ = ("value",)

    def __init__(self, value: float, line=None, col=None):
        super().__init__("num", line, col)
        self.value = float(value)

    def _ev(self, ctx):
        return np.float64(self.value)


class BoolConst(Node):
    __slots__ = ("value",)

    def __init__(self, value: bool, line=None, col=None):
        super().__init__("bool", line, col)
        self.value = bool(value)

    def _ev(self, ctx):
        return np.bool_(self.value)


class Data(Node):
    __slots__ = ("col_name",)

    def __init__(self, col_name: str, line=None, col=None):
        super().__init__("num", line, col)
        self.col_name = col_name

    def _ev(self, ctx):
        return ctx.data[self.col_name]


def _as_float(x):
    a = np.asarray(x)
    return a.astype("float64") if a.dtype == bool else a.astype("float64", copy=False)


class Bin(Node):
    __slots__ = ("op", "a", "b")

    def __init__(self, op, a, b, line=None, col=None):
        super().__init__("num", line, col, max(a.warm, b.warm))
        self.op, self.a, self.b = op, a, b

    def _ev(self, ctx):
        a, b = _as_float(self.a.ev(ctx)), _as_float(self.b.ev(ctx))
        with np.errstate(all="ignore"):
            if self.op == "+":
                r = a + b
            elif self.op == "-":
                r = a - b
            elif self.op == "*":
                r = a * b
            elif self.op == "/":
                r = a / b
            else:
                r = np.power(a, b)
        return np.where(np.isfinite(r), r, np.nan)


class Neg(Node):
    __slots__ = ("a",)

    def __init__(self, a, line=None, col=None):
        super().__init__("num", line, col, a.warm)
        self.a = a

    def _ev(self, ctx):
        return -_as_float(self.a.ev(ctx))


class Cmp(Node):
    __slots__ = ("op", "a", "b")

    def __init__(self, op, a, b, line=None, col=None):
        super().__init__("bool", line, col, max(a.warm, b.warm))
        self.op, self.a, self.b = op, a, b

    def _ev(self, ctx):
        a, b = _as_float(self.a.ev(ctx)), _as_float(self.b.ev(ctx))
        with np.errstate(invalid="ignore"):
            if self.op == ">":
                return a > b
            if self.op == ">=":
                return a >= b
            if self.op == "<":
                return a < b
            if self.op == "<=":
                return a <= b
            if self.op == "==":
                return a == b
            return (a != b) & ~np.isnan(a) & ~np.isnan(b)      # NaN -> False như các so sánh khác


class Logic(Node):
    __slots__ = ("op", "a", "b")

    def __init__(self, op, a, b, line=None, col=None):
        super().__init__("bool", line, col, max(a.warm, b.warm))
        self.op, self.a, self.b = op, a, b

    def _ev(self, ctx):
        a, b = np.asarray(self.a.ev(ctx), dtype=bool), np.asarray(self.b.ev(ctx), dtype=bool)
        return (a & b) if self.op == "&" else (a | b)


class Inv(Node):
    __slots__ = ("a",)

    def __init__(self, a, line=None, col=None):
        super().__init__("bool", line, col, a.warm)
        self.a = a

    def _ev(self, ctx):
        return ~np.asarray(self.a.ev(ctx), dtype=bool)


class Call(Node):
    """Gọi feature hoặc operator. bound: {tên tham số: Node (chuỗi) | số (hằng)}."""
    __slots__ = ("spec", "is_feature", "bound")

    def __init__(self, spec: Spec, is_feature: bool, bound: Dict[str, Any], kind: str, warm: int, line=None, col=None):
        super().__init__(kind, line, col, warm)
        self.spec, self.is_feature, self.bound = spec, is_feature, bound

    def _ev(self, ctx):
        kw = {k: (v.ev(ctx) if isinstance(v, Node) else v) for k, v in self.bound.items()}
        if self.is_feature:
            return feat_mod.evaluate(self.spec, ctx.n, **kw)
        out = self.spec.fn(ctx.n, **kw)
        if self.kind == "num":
            a = np.asarray(out, dtype="float64")
            return np.where(np.isfinite(a), a, np.nan)
        return np.asarray(out, dtype=bool)


class Pick(Node):
    __slots__ = ("call", "idx")

    def __init__(self, call: Call, idx: int):
        super().__init__("num", call.line, call.col, call.warm)
        self.call, self.idx = call, idx

    def _ev(self, ctx):
        return self.call.ev(ctx)[self.idx]


# ─── thời gian trong ngày ───────────────────────────────────────────────────

def _in_ranges(minutes: np.ndarray, ranges: Sequence[Tuple[int, int]]) -> np.ndarray:
    out = np.zeros(minutes.shape[0], dtype=bool)
    for a, b in ranges:
        out |= ((minutes >= a) & (minutes < b)) if a < b else ((minutes >= a) | (minutes < b))   # a >= b: vắt qua nửa đêm
    return out


class Program:
    """Kết quả biên dịch (bất biến sau khi dựng)."""

    def __init__(self, *, name: str, code_hash: str, timeframe: str, calls: List[Tuple[Node, float, int]], open_times: List[int],
                 open_ranges: List[Tuple[int, int]], close_ranges: List[Tuple[int, int]], position_overrides: Dict[str, Any],
                 features: Set[str], columns: Set[str], warnings: List[str], ops: Set[str]):
        self.name = name
        self.code_hash = code_hash
        self.timeframe = timeframe
        self.calls = calls                       # [(mặt nạ, mức, dòng)] theo thứ tự gọi: lệnh gọi sau ghi đè lệnh trước
        self.open_times = open_times             # phút trong ngày (UTC) của nhãn nến được phép MỞ vị thế
        self.open_ranges = open_ranges
        self.close_ranges = close_ranges         # khoảng giờ bắt buộc đóng (mức 0)
        self.position_overrides = position_overrides
        self.features = sorted(features)
        self.ops = sorted(ops)
        self.columns = sorted(columns)
        self.warnings = list(warnings)
        self.levels = sorted({lv for _, lv, _ in calls})
        self.has_long = any(lv > 0 for lv in self.levels)
        self.has_short = any(lv < 0 for lv in self.levels)
        self.warmup_bars = int(max([m.warm for m, _, _ in calls] + [0]))
        self._cache: "OrderedDict[bytes, Dict[str, np.ndarray]]" = OrderedDict()

    # ─── tên cột ────────────────────────────────────────────────────────────
    def column(self, kind: str) -> str:
        if kind not in KINDS:
            raise ValueError(f"kind phải thuộc {KINDS}")
        return f"py_{self.code_hash}_{kind}"

    @property
    def legs(self) -> List[str]:
        return (["LONG"] if self.has_long else []) + (["SHORT"] if self.has_short else [])

    def meta(self) -> Dict[str, Any]:
        return {"timeframe": self.timeframe, "features": self.features, "ops": self.ops, "columns": self.columns,
                "legs": self.legs, "position_levels": self.levels, "warmup_bars": self.warmup_bars}

    # ─── tính toán ──────────────────────────────────────────────────────────
    @staticmethod
    def _data(df) -> Tuple[int, Dict[str, np.ndarray]]:
        missing = [c for c in DATA_COLUMNS if c not in df.columns]
        if missing:
            raise DslError(f"DataFrame nến thiếu cột {missing}")
        return len(df), {c: np.asarray(df[c], dtype="float64") for c in DATA_COLUMNS}

    def _minutes(self, df, n: int) -> np.ndarray:
        if "open_time" not in df.columns:
            raise DslError("position_open_times / *_ranges cần cột open_time của nến")
        label = np.asarray(df["open_time"], dtype="int64") + TF_MS[self.timeframe]    # nhãn = giờ ĐÓNG nến
        return ((label // 60_000) % 1440).astype("int64")

    def explicit(self, df) -> np.ndarray:
        n, data = self._data(df)
        ctx = Ctx(n, data)
        out = np.full(n, np.nan)
        allow = None
        if self.open_times or self.open_ranges:
            minutes = self._minutes(df, n)
            allow = np.isin(minutes, np.asarray(self.open_times, dtype="int64")) | _in_ranges(minutes, self.open_ranges)
        for mask, level, _ in self.calls:
            m = np.broadcast_to(np.asarray(mask.ev(ctx), dtype=bool), (n,)).copy()
            if level != 0.0 and allow is not None:
                m &= allow
            out[m] = level
        if self.close_ranges:
            out[_in_ranges(self._minutes(df, n), self.close_ranges)] = 0.0
        return out

    @staticmethod
    def hold(explicit: np.ndarray) -> np.ndarray:
        """ffill mức đặt tường minh, đầu chuỗi = 0."""
        n = explicit.shape[0]
        idx = np.maximum.accumulate(np.where(~np.isnan(explicit), np.arange(n), -1))
        return np.where(idx >= 0, explicit[np.maximum(idx, 0)], 0.0)

    def target(self, df) -> np.ndarray:
        return self.hold(self.explicit(df))

    def columns_for(self, df) -> Dict[str, np.ndarray]:
        """{"le", "lx", "se", "sx"} -> mảng float64 0/1; cache theo nội dung df (bốn cột cùng tính một lần)."""
        _, data = self._data(df)
        h = hashlib.blake2b(digest_size=16)
        for c in DATA_COLUMNS:
            h.update(data[c].tobytes())
        if "open_time" in df.columns:
            h.update(np.asarray(df["open_time"], dtype="int64").tobytes())
        key = h.digest()
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return hit
        exp = self.explicit(df)
        tgt = self.hold(exp)
        with np.errstate(invalid="ignore"):
            out = {"le": (exp > 0).astype("float64"), "lx": (tgt <= 0).astype("float64"),
                   "se": (exp < 0).astype("float64"), "sx": (tgt >= 0).astype("float64")}
        self._cache[key] = out
        while len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)
        return out

    def compute_column(self, df, kind: str):
        import pandas as pd
        return pd.Series(self.columns_for(df)[kind], index=df.index)
