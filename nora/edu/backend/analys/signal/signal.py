"""Bộ dịch tín hiệu (P9.4 part 2): IR của DSL (lỗi DslError, Node…Program) + bộ thông dịch AST (evaluator) + ảnh chụp tín hiệu (snapshot)
+ kiểm tra tín hiệu (diagnostics). Trình biên dịch (compile_code/compile_report/explain_*/compile_strategy_module/hàm dựng cây f, cond, ...) đã chuyển sang alpha/compile.py;
hợp đồng (at, suggest, giới hạn) ở alpha/contract.py.

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.4 part 2). Chỉ import `params` và `indicator`. signal_snapshot / check_signals (cần engine + nguồn dữ liệu) nằm ở nautilus/engine.py;
phần phân loại regime thuần (classify, masks_for, REFS, ...) nằm ở đây (metrics/regime.py import lại).
"""
import ast
import hashlib
import math
import operator
import os
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd
import requests

from backend.analys import indicator as kernels
from backend.analys.indicator import Spec, evaluate_feature, nan_nonfinite
from backend.analys.param import DATA_COLUMNS, FRAME_MS, MINUTE_MS as MINUTE, REGIME_NAMES
from backend.data import data as dat

MINUTE_MS = 60_000
_COLS = ["open_time", "open", "high", "low", "close", "volume"]



# ══════════════════════════════════════════════════════════════════════════
# Lỗi biên dịch DSL chiến lược Python: luôn có số dòng + cột (1-based) để UI tô đúng chỗ.
# ══════════════════════════════════════════════════════════════════════════

class DslError(ValueError):
    """Lỗi biên dịch / chạy chương trình DSL. line, col (1-based) trỏ vào mã nguồn của người dùng (None nếu không gắn được vào dòng nào)."""

    def __init__(self, message: str, line: Optional[int] = None, col: Optional[int] = None):
        self.message = message
        self.line = line
        self.col = col
        self.end_line: Optional[int] = None      # vị trí kết thúc (1-based, tuỳ chọn; alpha/contract.at điền từ nút AST) — không nằm trong to_dict()
        self.end_col: Optional[int] = None
        where = f"dòng {line}, cột {col}: " if line is not None else ""
        super().__init__(f"{where}{message}")

    def to_dict(self):
        return {"line": self.line, "col": self.col, "message": self.message}


# ══════════════════════════════════════════════════════════════════════════
# Chương trình DSL đã biên dịch: cây biểu thức (IR) đã kiểm loại + metadata; chạy trên DataFrame nến của MỘT tài sản.
#
# `Program.explicit(df)` -> mức vị thế đặt tường minh tại từng nến (NaN = không quy tắc nào kích hoạt nến này).
# `Program.target(df)`   -> mức mục tiêu target[t] ∈ [-1, 1]: giữ mức trước khi không quy tắc nào kích hoạt (ffill), đầu chuỗi = 0.
# Cột tín hiệu cho engine (kernels.compute qua `py_<hash12>_<le|lx|se|sx>`):
#     le = explicit > 0   (SỰ KIỆN vào long: quy tắc đặt mức > 0 ở nến này)     lx = target <= 0   (TRẠNG THÁI thoát long)
#     se = explicit < 0   (vào short)                                            sx = target >= 0   (thoát short)
# Vào lệnh theo sự kiện (không theo trạng thái target) để vị thế đã đóng bởi SL/TP/timeout/thanh lý KHÔNG tự vào lại ngay trên cùng
# mức target cũ — giống cách chiến lược lõi dùng sự kiện cắt (cross_over).
# ══════════════════════════════════════════════════════════════════════════

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
            return evaluate_feature(self.spec, ctx.n, **kw)
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
                "legs": self.legs, "position_levels": self.levels, "warmup_bars": self.warmup_bars,
                "position_overrides": getattr(self, "position_overrides", {}) or {},
                "declared_params": getattr(self, "position_overrides", {}) or {}}

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
        label = np.asarray(df["open_time"], dtype="int64") + FRAME_MS[self.timeframe]    # nhãn = giờ ĐÓNG nến
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


DSL_VERSION = "1"            # đổi khi ngữ nghĩa DSL đổi -> mã băm (và cột py_...) đổi, không dùng nhầm kết quả cũ


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                node.body = node.body[1:] or [ast.Pass()]
    return tree


def code_hash(tree: ast.AST) -> str:
    """12 ký tự hex của mã đã chuẩn hoá (bỏ chú thích, khoảng trắng, docstring) + phiên bản DSL."""
    norm = ast.dump(_strip_docstrings(ast.parse(ast.unparse(tree))), annotate_fields=True, include_attributes=False)
    return hashlib.sha1(f"{DSL_VERSION}|{norm}".encode("utf-8")).hexdigest()[:12]


class TupleVal:
    """Giá trị nhiều thành phần (đầu ra feature nhiều đầu ra / tuple viết tay) — chỉ để unpack hoặc lấy chỉ số hằng."""

    def __init__(self, items: List[Node], line=None, col=None):
        self.items, self.line, self.col = items, line, col


# ══════════════════════════════════════════════════════════════════════════
# Bộ thông dịch Logic Chiến lược (Strategy Logic Evaluator).
# ══════════════════════════════════════════════════════════════════════════

def lag_key(column: str, lag: int) -> str:
    """Tên cột cho giá trị của `lag` nến trước trên cùng khung (index trong AST)."""
    return column if not lag else f"{column}__lag{int(lag)}"


class LogicEvaluator:
    """Đánh giá AST điều kiện chiến lược bằng interpreter an toàn (từng nến).

    Ngữ cảnh (ctx) là dict khung -> row, vd {"1m": {...}, "15m": {...}, "4h": {...}}.
    Trường AST {"frame": "15m", "column": "rsi_14", "index": 1} đọc ctx["15m"]["rsi_14__lag1"].
    Là bản tham chiếu từng nến cho VectorEvaluator (test_signals_strategies) và nguồn bảng toán tử dùng chung.
    """

    COMPARATORS = {
        ">": operator.gt,
        "<": operator.lt,
        ">=": operator.ge,
        "<=": operator.le,
        "==": operator.eq,
        "=": operator.eq,
        "!=": operator.ne,
    }

    MATH_OPERATORS = {
        "+": operator.add,
        "-": operator.sub,
        "*": operator.mul,
    }

    # ─── Lõi theo ngữ cảnh nhiều khung ──────────────────────────────────────
    @staticmethod
    def evaluate_tree_ctx(condition_tree: Any, ctx: Dict[str, Dict]) -> bool:
        if not isinstance(condition_tree, list):
            return False
        for and_block in condition_tree:
            if not isinstance(and_block, list) or not and_block:
                continue
            if all(LogicEvaluator._triplet_ctx(triplet, ctx) for triplet in and_block):
                return True
        return False

    @staticmethod
    def _triplet_ctx(triplet: Any, ctx: Dict[str, Dict]) -> bool:
        if not isinstance(triplet, list) or len(triplet) != 3:
            return False
        left = LogicEvaluator.value_ctx(triplet[0], ctx)
        right = LogicEvaluator.value_ctx(triplet[2], ctx)
        comparator = LogicEvaluator.COMPARATORS.get(triplet[1])
        if comparator is None or left is None or right is None:
            return False
        try:
            return bool(comparator(left, right))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def value_ctx(item: Any, ctx: Dict[str, Dict]) -> Optional[float]:
        if isinstance(item, bool):
            return None
        if isinstance(item, (int, float)):
            return LogicEvaluator._finite_or_none(float(item))
        if isinstance(item, list) or not isinstance(item, dict):
            return None
        node_type = item.get("type")
        if node_type == "calculate":
            n1 = LogicEvaluator.value_ctx(item.get("number_1"), ctx)
            n2 = LogicEvaluator.value_ctx(item.get("number_2"), ctx)
            if n1 is None or n2 is None:
                return None
            op = item.get("logic")
            if op == "/":
                result = 0.0 if n2 == 0 else n1 / n2
            else:
                fn = LogicEvaluator.MATH_OPERATORS.get(op)
                if fn is None:
                    return None
                result = fn(n1, n2)
            multiply = item.get("multiply", 1.0)
            if isinstance(multiply, bool) or not isinstance(multiply, (int, float)):
                return None
            return LogicEvaluator._finite_or_none(result * float(multiply))
        if node_type in ("min", "max"):
            values = [LogicEvaluator.value_ctx(x, ctx) for x in item.get("numbers", [])]
            clean = [v for v in values if v is not None]
            if not clean:
                return None
            return LogicEvaluator._finite_or_none(min(clean) if node_type == "min" else max(clean))
        if "frame" in item and "column" in item:
            row = ctx.get(item.get("frame"))
            lag = int(item.get("index", 0) or 0)
            key = lag_key(item.get("column"), lag)
            if row is None or key not in row:
                return None
            value = LogicEvaluator._coerce_float(row.get(key))
            if value is None:
                return None
            for key_mod, sign in (("subtract", -1.0), ("add", 1.0)):
                if key_mod in item:
                    modifier = LogicEvaluator.value_ctx(item[key_mod], ctx)
                    if modifier is None:
                        return None
                    value += sign * modifier
            if "divide" in item:
                divider = LogicEvaluator.value_ctx(item["divide"], ctx)
                if divider is None:
                    return None
                value = 0.0 if divider == 0 else value / divider
            return LogicEvaluator._finite_or_none(value)
        return None

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if isinstance(value, bool) or value is None:
            return None
        try:
            return LogicEvaluator._finite_or_none(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _finite_or_none(value: float) -> Optional[float]:
        return value if math.isfinite(value) else None


class VectorEvaluator:
    """Đánh giá AST điều kiện trên TOÀN BỘ chuỗi nến cùng lúc (numpy), cùng ngữ nghĩa với LogicEvaluator.

    `get(frame, column, lag)` trả mảng float (NaN = không có giá trị). Quy tắc giống bản từng nến:
    - giá trị thiếu/không hữu hạn -> NaN; so sánh có NaN -> False;
    - phép chia cho 0 -> 0.0; min/max bỏ qua NaN (toàn NaN -> NaN);
    - OR giữa các khối AND; cây rỗng/không hợp lệ -> toàn False.
    Test test/test_signals_strategies.py đối chiếu từng phần tử với LogicEvaluator.
    """

    COMPARATORS = LogicEvaluator.COMPARATORS

    def __init__(self, n: int, get: Callable[[str, str, int], "np.ndarray"]):
        self.n = n
        self.get = get

    def _nan(self):
        return np.full(self.n, np.nan)

    def tree(self, condition_tree: Any) -> "np.ndarray":
        result = np.zeros(self.n, dtype=bool)
        if not isinstance(condition_tree, list):
            return result
        for and_block in condition_tree:
            if not isinstance(and_block, list) or not and_block:
                continue
            block = np.ones(self.n, dtype=bool)
            for triplet in and_block:
                block &= self._triplet(triplet)
            result |= block
        return result

    def _triplet(self, triplet: Any) -> "np.ndarray":
        if not isinstance(triplet, list) or len(triplet) != 3:
            return np.zeros(self.n, dtype=bool)
        comparator = self.COMPARATORS.get(triplet[1])
        if comparator is None:
            return np.zeros(self.n, dtype=bool)
        left, right = self.value(triplet[0]), self.value(triplet[2])
        valid = np.isfinite(left) & np.isfinite(right)
        with np.errstate(invalid="ignore"):
            out = comparator(left, right)
        return np.asarray(out, dtype=bool) & valid

    def value(self, item: Any) -> "np.ndarray":
        if isinstance(item, bool) or isinstance(item, list) or item is None:
            return self._nan()
        if isinstance(item, (int, float)):
            v = float(item)
            return np.full(self.n, v) if math.isfinite(v) else self._nan()
        if not isinstance(item, dict):
            return self._nan()
        node_type = item.get("type")
        if node_type == "calculate":
            return self._calculate(item)
        if node_type in ("min", "max"):
            arrays = [self.value(x) for x in item.get("numbers", [])]
            if not arrays:
                return self._nan()
            fn = np.fmin if node_type == "min" else np.fmax
            return nan_nonfinite(fn.reduce(np.vstack(arrays), axis=0))
        if "frame" in item and "column" in item:
            return self._field(item)
        return self._nan()

    def _calculate(self, item):
        n1, n2 = self.value(item.get("number_1")), self.value(item.get("number_2"))
        op = item.get("logic")
        with np.errstate(all="ignore"):
            if op == "/":
                res = np.where(n2 == 0, 0.0, n1 / np.where(n2 == 0, 1.0, n2))
                res = np.where(np.isnan(n1) | np.isnan(n2), np.nan, res)
            elif op in LogicEvaluator.MATH_OPERATORS:
                res = LogicEvaluator.MATH_OPERATORS[op](n1, n2)
            else:
                return self._nan()
        multiply = item.get("multiply", 1.0)
        if isinstance(multiply, bool) or not isinstance(multiply, (int, float)):
            return self._nan()
        return nan_nonfinite(res * float(multiply))

    def _field(self, item):
        lag = int(item.get("index", 0) or 0)
        value = np.asarray(self.get(item.get("frame"), item.get("column"), lag), dtype="float64").copy()
        value = nan_nonfinite(value)
        with np.errstate(all="ignore"):
            for key, sign in (("subtract", -1.0), ("add", 1.0)):
                if key in item:
                    value = value + sign * self.value(item[key])
            if "divide" in item:
                div = self.value(item["divide"])
                value = np.where(div == 0, 0.0, value / np.where(div == 0, 1.0, div))
                value = np.where(np.isnan(div), np.nan, value)
        return nan_nonfinite(value)


# ══════════════════════════════════════════════════════════════════════════
# Ảnh chụp TÍN HIỆU thị trường tại nến 1m ĐÃ ĐÓNG mới nhất — cùng một đường tính với backtest (không có bản tính thứ hai).
#
# signal_snapshot(symbol, strategies, end_ts) dựng engine của tài sản y như PortfolioEngine (_make_slots -> load_data -> _build_matrix ->
# VectorEvaluator), nên giá trị chỉ báo / điều kiện / tín hiệu vào-thoát ở phút t TRÙNG với thứ engine dùng ở phút t (test_signal_snapshot).
# Khung lớn chỉ dùng nến đã đóng (avail_time = open + độ dài khung); phút cuối là phút có giao dịch thật (bỏ nến điền).
#
# Dùng cho: trang Tổng quan (dữ liệu backtest), và sau này Live/Testnet — chỉ cần nạp nến mới nhất của sàn vào cùng bố cục dữ liệu rồi gọi lại hàm này.
# Kết quả mỗi chiến lược: entry/exit (tín hiệu ở nến đã đóng cuối), `entry_since` (từ phút nào tín hiệu vào giữ trạng thái hiện tại),
# và từng điều kiện (giá trị trái/phải, toán tử, đạt/không) để biết vì sao có / không có tín hiệu.
# ══════════════════════════════════════════════════════════════════════════

DEFAULT_LOOKBACK_MIN = 3 * 24 * 60     # 3 ngày 1m (chỉ báo khung lớn có warmup riêng do engine tự nạp thêm)


def _label(item: Any) -> str:
    if isinstance(item, bool) or item is None:
        return "?"
    if isinstance(item, (int, float)):
        return f"{item:g}"
    if isinstance(item, dict):
        if "frame" in item and "column" in item:
            lag = int(item.get("index", 0) or 0)
            base = f"{item['frame']} {item['column']}" + (f"[-{lag}]" if lag else "")
            for key, sign in (("subtract", " − "), ("add", " + "), ("divide", " ÷ ")):
                if key in item:
                    base = f"({base}{sign}{_label(item[key])})"
            return base
        if item.get("type") == "calculate":
            s = f"({_label(item.get('number_1'))} {item.get('logic')} {_label(item.get('number_2'))})"
            mult = item.get("multiply", 1.0)
            return s if mult in (1, 1.0) else f"{s} × {mult:g}"
        if item.get("type") in ("min", "max"):
            return f"{item['type']}(" + ", ".join(_label(x) for x in item.get("numbers", [])) + ")"
    return "?"


def _num(x) -> Optional[float]:
    x = float(x)
    return x if np.isfinite(x) else None


def _explain(vec: VectorEvaluator, tree: Any, i: int) -> List[Dict[str, Any]]:
    """Mỗi khối AND của cây (OR giữa các khối): điều kiện + giá trị tại vị trí i."""
    blocks = []
    if not isinstance(tree, list):
        return blocks
    for block in tree:
        if not isinstance(block, list) or not block:
            continue
        conds = []
        for trip in block:
            ok = bool(vec._triplet(trip)[i])
            if isinstance(trip, list) and len(trip) == 3:
                conds.append({"left": _label(trip[0]), "left_value": _num(vec.value(trip[0])[i]), "op": trip[1],
                              "right": _label(trip[2]), "right_value": _num(vec.value(trip[2])[i]), "pass": ok})
            else:
                conds.append({"left": "?", "left_value": None, "op": "?", "right": "?", "right_value": None, "pass": False})
        blocks.append({"pass": all(c["pass"] for c in conds), "conditions": conds})
    return blocks


def _since(arr: np.ndarray, t: np.ndarray, i: int) -> Optional[int]:
    """open_time của phút đầu tiên trong chuỗi liên tiếp hiện tại có cùng giá trị với arr[i] (None nếu chuỗi kéo dài hết cửa sổ)."""
    v = arr[i]
    j = i
    while j > 0 and arr[j - 1] == v:
        j -= 1
    return int(t[j]) if j > 0 else None


# signal_snapshot: ở nautilus/engine.py (cần PortfolioEngine; engine-API pass).


# ══════════════════════════════════════════════════════════════════════════
# Phần phân loại thuần nằm ở core vì engine lọc tín hiệu theo regime; metrics/regime.py import lại từ đây, giữ series/learn). MINUTE dùng chung với ảnh chụp tín hiệu bên dưới.
#
# Regime thị trường theo phút — causal, cùng bộ máy căn khung với tín hiệu (chỉ nến 1h/4h ĐÃ ĐÓNG), dùng chung cho backtest / WFA / phễu /
# tín hiệu thị trường / live.
#
# Đặc trưng (cột kernel, signal/indicator.py):
#   4h er_20 (độ hiệu quả xu hướng), 4h adx_14 (độ mạnh), 4h ema_50 / ema_200 (chiều), 1h roc_24 (lợi suất 24h, %), 1h roc_1 (nến 1h cuối, %),
#   1h bbwp_20_2_720 (phân vị độ rộng Bollinger trong 30 ngày 1h, 0..100).
# Trạng thái thô (ưu tiên từ trên xuống):
#   CRASH  roc_24 <= -crash_24h_pct  hoặc  roc_1 <= -shock_1h_pct      SURGE  roc_24 >= surge_24h_pct  hoặc  roc_1 >= shock_1h_pct
#   VOL_EXPANSION  bbwp >= vol_pct
#   TREND_UP / TREND_DOWN  er >= er_min và adx >= adx_min, chiều theo ema_50 so với ema_200
#   RANGE  còn lại;  UNKNOWN  thiếu đặc trưng (đang khởi động)
# Chống nhảy: trạng thái thường phải giữ liên tục >= confirm_min phút mới được nhận; CRASH/SURGE nhận ngay và giữ ít nhất shock_hold_min phút
# kể từ lần cuối còn tín hiệu sốc.
# ══════════════════════════════════════════════════════════════════════════

UNKNOWN, RANGE, TREND_UP, TREND_DOWN, VOL_EXPANSION, SURGE, CRASH = range(7)
NAMES = REGIME_NAMES
LABEL_VI = {"UNKNOWN": "Chưa đủ dữ liệu", "RANGE": "Đi ngang", "TREND_UP": "Xu hướng tăng", "TREND_DOWN": "Xu hướng giảm",
            "VOL_EXPANSION": "Biến động bùng nổ", "SURGE": "Tăng thẳng đứng", "CRASH": "Sập mạnh"}
CODE = {n: i for i, n in enumerate(NAMES)}

DEFAULTS: Dict[str, Any] = {"er_min": 0.30, "adx_min": 20.0, "vol_pct": 90.0, "crash_24h_pct": 12.0, "surge_24h_pct": 12.0,
                            "shock_1h_pct": 5.0, "confirm_min": 180, "shock_hold_min": 360, "trend_frame": "4h"}
# Hồ sơ ngưỡng (P2 khắc phục): "slow" = mặc định (xu hướng 4h, xác nhận 180 phút); "fast" = xu hướng đo trên 1h, xác nhận 60 phút — nhãn đến sớm
# hơn, gần điểm phá vỡ mà chiến lược 15m/1h vào lệnh. Chọn hồ sơ bằng khoá "classifier" trong cấu hình regime của chiến lược.
PROFILES: Dict[str, Dict[str, Any]] = {"slow": dict(DEFAULTS), "fast": {**DEFAULTS, "trend_frame": "1h", "confirm_min": 60}}

# (khung, cột kernel, độ trễ) — thêm vào refs của engine khi có chiến lược bật regime / khi cần hiển thị regime
REFS: Dict[str, Set[Tuple[str, int]]] = {
    "4h": {("er_20", 0), ("adx_14", 0), ("ema_50", 0), ("ema_200", 0)},
    "1h": {("roc_24", 0), ("roc_1", 0), ("bbwp_20_2_720", 0), ("er_20", 0), ("adx_14", 0), ("ema_50", 0), ("ema_200", 0)},
}


def profile_cfg(spec: Any) -> Optional[Dict[str, Any]]:
    """Khoá "classifier" của cấu hình regime -> cfg: None (mặc định) | tên hồ sơ trong PROFILES | dict ngưỡng."""
    if spec is None or isinstance(spec, dict):
        return spec
    if spec not in PROFILES:
        raise ValueError(f"hồ sơ regime không có: {spec!r} (có {sorted(PROFILES)})")
    return PROFILES[spec]


def raw_states(get: Callable[[str, str], np.ndarray], n: int, cfg: Optional[Dict[str, float]] = None) -> np.ndarray:
    """Trạng thái thô từng phút từ các cột đặc trưng đã căn (get(frame, column) -> mảng float độ dài n, NaN = chưa có)."""
    c = {**DEFAULTS, **(cfg or {})}
    tf = c["trend_frame"]
    er, adx = get(tf, "er_20"), get(tf, "adx_14")
    e50, e200 = get(tf, "ema_50"), get(tf, "ema_200")
    r24, r1, bw = get("1h", "roc_24"), get("1h", "roc_1"), get("1h", "bbwp_20_2_720")
    out = np.full(n, UNKNOWN, dtype=np.int8)
    with np.errstate(invalid="ignore"):
        trend_ok = np.isfinite(er) & np.isfinite(adx) & np.isfinite(e50) & np.isfinite(e200)
        out[trend_ok] = RANGE
        strong = trend_ok & (er >= c["er_min"]) & (adx >= c["adx_min"])
        out[strong & (e50 > e200)] = TREND_UP
        out[strong & (e50 < e200)] = TREND_DOWN
        out[np.isfinite(bw) & (bw >= c["vol_pct"])] = VOL_EXPANSION
        surge = (np.isfinite(r24) & (r24 >= c["surge_24h_pct"])) | (np.isfinite(r1) & (r1 >= c["shock_1h_pct"]))
        crash = (np.isfinite(r24) & (r24 <= -c["crash_24h_pct"])) | (np.isfinite(r1) & (r1 <= -c["shock_1h_pct"]))
    out[surge] = SURGE
    out[crash] = CRASH
    return out


def smooth(raw: np.ndarray, t: np.ndarray, cfg: Optional[Dict[str, float]] = None) -> np.ndarray:
    """Áp luật chống nhảy lên chuỗi thô (t = open_time từng phút, tăng dần). Chỉ duyệt các điểm đổi trạng thái thô (vài nghìn) nên nhanh."""
    c = {**DEFAULTS, **(cfg or {})}
    n = len(raw)
    out = np.empty(n, dtype=np.int8)
    if n == 0:
        return out
    confirm = int(c["confirm_min"]) * MINUTE
    hold = int(c["shock_hold_min"]) * MINUTE
    cur = int(raw[0])
    shock_until = -1
    pending, pending_since = None, None
    cuts = np.flatnonzero(np.diff(raw.astype(np.int16))) + 1
    bounds = np.concatenate(([0], cuts, [n]))
    for s, e in zip(bounds[:-1], bounds[1:]):
        r = int(raw[s])
        if r in (SURGE, CRASH):
            cur, pending = r, None
            out[s:e] = r
            shock_until = int(t[e - 1]) + hold
            continue
        # đoạn [s, e) có trạng thái thô thường r
        i = s
        if cur in (SURGE, CRASH) and shock_until >= int(t[s]):      # còn trong thời gian giữ sốc
            j = int(np.searchsorted(t, shock_until, side="right", sorter=None))
            j = min(max(j, s), e)
            out[s:j] = cur
            i = j
            if i >= e:
                continue
            cur, pending = r, None          # hết thời gian giữ sốc: nhận ngay trạng thái nền (đã ổn định trong suốt thời gian giữ)
            out[i:e] = cur
            continue
        if cur in (SURGE, CRASH):           # khoảng trống dữ liệu vượt quá thời gian giữ
            cur, pending = r, None
            out[i:e] = cur
            continue
        if r == cur:
            out[i:e] = cur
            pending = None
            continue
        if pending != r:
            pending, pending_since = r, int(t[i])
        k = int(np.searchsorted(t, pending_since + confirm, side="left"))
        k = min(max(k, i), e)
        out[i:k] = cur
        if k < e:
            cur, pending = r, None
            out[k:e] = cur
    return out


def classify(get: Callable[[str, str], np.ndarray], t: np.ndarray, cfg: Optional[Dict[str, float]] = None) -> np.ndarray:
    """Mã regime (int8, xem NAMES) từng phút."""
    return smooth(raw_states(get, len(t), cfg), np.asarray(t, dtype=np.int64), cfg)


def masks_for(strategy: Dict[str, Any], side: str, labels: np.ndarray) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """(cho phép vào lệnh, cầu chì thoát) theo cấu hình strategy["regime"] = {"allowed": [tên...], "fuse": bool}.
    Cầu chì: LONG gặp CRASH / SHORT gặp SURGE -> tín hiệu thoát (đóng ở nến sau), cắt cả thang DCA trước khi bị thanh lý."""
    rg = strategy.get("regime") or {}
    if not rg:
        return None, None
    allowed = np.isin(labels, [CODE[x] for x in rg.get("allowed") or NAMES])
    fuse = None
    if rg.get("fuse", True):
        fuse = labels == (CRASH if side == "LONG" else SURGE)
    return allowed, fuse


# ══════════════════════════════════════════════════════════════════════════
# Kiểm tra tín hiệu: tín hiệu có mang THÔNG TIN về giá tương lai không — trước khi ghép thành chiến lược.
#
# Với mỗi tín hiệu (cây điều kiện AST trên kernel) và mỗi tài sản:
# - Sự kiện = nến 1m (có giao dịch) mà tín hiệu đúng; vào ở OPEN của phút có giao dịch kế tiếp
#   (giống engine, không nhìn trước).
# - Lợi suất tương lai ở các mốc h (15m, 1h, 4h, 24h) = close của nến đóng muộn nhất trong h phút.
# - Mỗi mốc h chỉ giữ các sự kiện CÁCH NHAU >= h (không chồng lấp) để t-stat không bị thổi phồng.
# - Đối chứng = vào ở MỌI phút (lấy mẫu đều) trong cùng khoảng thời gian: edge = TB sự kiện − TB đối chứng.
# - Ổn định = edge cùng dấu ở 60% sự kiện đầu và 40% sau.
# - Sau phí = TB sự kiện − chi phí khứ hồi theo venue (CEX spot ~24 bps, DEX ~80 bps).
#
# Kết luận mỗi tín hiệu (mốc h tốt nhất theo |t|):
#     CO_THONG_TIN   |t| >= 3 và ổn định
#     YEU            2 <= |t| < 3 hoặc không ổn định
#     KHONG          |t| < 2 hoặc quá ít sự kiện
# Ngưỡng |t| >= 3 (không phải 2) vì kiểm nhiều tín hiệu × nhiều tài sản × nhiều mốc cùng lúc.
# ══════════════════════════════════════════════════════════════════════════

HORIZONS_MIN = (15, 60, 240, 1440)
MIN_EVENTS = 30


def _thin(entry_times: np.ndarray, gap_ms: int) -> np.ndarray:
    """Giữ các sự kiện cách nhau >= gap (tham lam theo thời gian)."""
    keep, last = [], None
    for idx, t in enumerate(entry_times):
        if last is None or t - last >= gap_ms:
            keep.append(idx)
            last = t
    return np.asarray(keep, dtype=int)


def _forward_bps(times, opens, closes, entry_idx, horizon_ms, sign):
    """Lợi suất (bps) từ open của nến entry tới close nến cuối cùng đóng trong horizon."""
    t_entry = times[entry_idx]
    k = np.searchsorted(times, t_entry + horizon_ms - 60_000, side="right") - 1
    valid = (k > entry_idx) & (t_entry + horizon_ms <= times[-1] + 60_000)
    ret = np.full(len(entry_idx), np.nan)
    ret[valid] = sign * (closes[k[valid]] / opens[entry_idx[valid]] - 1.0) * 1e4
    return ret


def _stats(ev: np.ndarray, base: np.ndarray, cost_bps: float) -> Dict[str, Any]:
    ev = ev[np.isfinite(ev)]
    base = base[np.isfinite(base)]
    n = len(ev)
    if n < 2 or len(base) < 2:
        return {"n": int(n)}
    edge = ev.mean() - base.mean()
    se = ev.std(ddof=1) / np.sqrt(n)
    split = int(n * 0.6)
    first, last = ev[:split], ev[split:]
    edge_first = first.mean() - base.mean() if len(first) else np.nan
    edge_last = last.mean() - base.mean() if len(last) else np.nan
    return {
        "n": int(n),
        "mean_bps": round(float(ev.mean()), 2),
        "median_bps": round(float(np.median(ev)), 2),
        "hit_rate": round(float((ev > 0).mean() * 100), 1),
        "baseline_mean_bps": round(float(base.mean()), 2),
        "baseline_hit_rate": round(float((base > 0).mean() * 100), 1),
        "edge_bps": round(float(edge), 2),
        "t_stat": round(float(edge / se), 2) if se > 0 else 0.0,
        "edge_first60_bps": round(float(edge_first), 2),
        "edge_last40_bps": round(float(edge_last), 2),
        "stable": bool(np.sign(edge_first) == np.sign(edge_last) and np.sign(edge_first) != 0),
        "net_after_cost_bps": round(float(ev.mean() - cost_bps), 2),
    }


def _verdict(by_h: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    usable = {h: s for h, s in by_h.items() if s.get("n", 0) >= MIN_EVENTS and "t_stat" in s}
    if not usable:
        return {"verdict": "KHONG", "reason": f"ít hơn {MIN_EVENTS} sự kiện không chồng lấp", "best_horizon_min": None}
    h, s = max(usable.items(), key=lambda kv: abs(kv[1]["t_stat"]))
    t = s["t_stat"]
    if abs(t) >= 3 and s["stable"]:
        verdict = "CO_THONG_TIN"
    elif abs(t) >= 2:
        verdict = "YEU"
    else:
        verdict = "KHONG"
    direction = "đúng chiều" if t > 0 else "NGƯỢC chiều (tín hiệu báo sai hướng)"
    return {
        "verdict": verdict,
        "best_horizon_min": h,
        "t_stat": t,
        "direction": direction,
        "covers_cost": bool(t >= 3 and s["net_after_cost_bps"] > 0),
        "reason": f"mốc {h} phút: edge {s['edge_bps']} bps, t={t}, {'ổn định' if s['stable'] else 'KHÔNG ổn định'} "
                  f"giữa 60% đầu/40% sau, sau phí {s['net_after_cost_bps']} bps",
    }


# ══════════════════════════════════════════════════════════════════════════
# SignalProvider cho NautilusTrader (P17 T5): giao diện tín hiệu dùng chung giữa Backtest và Live.
#
# - SignalProvider: giao diện cơ sở cho strategy tại mỗi nến đóng.
# - ArraySignals: bọc mảng tính sẵn toàn kỳ cho backtest (bảo toàn bit-identical).
# - LiveSignals: bộ đệm nến đa khung nạp từ catalog/REST, tính tín hiệu từng nến đã đóng
#   qua backend.signal.compute.evaluate_signals trên cửa sổ [t - warmup, t].
# ══════════════════════════════════════════════════════════════════════════

from .compute import evaluate_signals, collect_field_refs


class SignalProvider(ABC):
    """Giao diện cung cấp tín hiệu cho NoraSlotStrategy tại mỗi nến đóng."""

    @abstractmethod
    def at(self, bar_close_ms: int) -> Optional[Dict[str, Any]]:
        """Trả về dict {'match': bool, 'stop': bool, 'vol': float, 'dca': bool} cho nến đóng tại bar_close_ms,

        hoặc None nếu không có tín hiệu ở nến này (ví dụ nến chạy nhỏ hơn khung tín hiệu chưa đóng).
        """
        raise NotImplementedError

    def on_base_bar(self, close_ms: int, o: float, h: float, l: float, c: float, v: float) -> None:
        """Strategy báo nến chạy vừa đóng (live nạp vào bộ đệm; backtest dùng mảng tính sẵn nên bỏ qua)."""
        return None


class ArraySignals(SignalProvider):
    """Cung cấp tín hiệu từ mảng tính sẵn toàn kỳ (dùng cho backtest)."""

    def __init__(self, sig: Dict[str, Any], frame_ms: int):
        self.sig_t: List[int] = sig["t"]
        self.sig_match: List[bool] = sig["match"]
        self.sig_stop: List[bool] = sig["stop"]
        self.sig_vol: Optional[List[float]] = sig.get("vol")
        self.sig_dca: Optional[List[bool]] = sig.get("dca")
        self.frame_ms = frame_ms
        self._p = 0
        self._n = len(self.sig_t)
        self.match_close_ts = {t + self.frame_ms for t, m in zip(self.sig_t, self.sig_match) if m}
        self.stop_close_ts = {t + self.frame_ms for t, s in zip(self.sig_t, self.sig_stop) if s}

    def at(self, bar_close_ms: int) -> Optional[Dict[str, Any]]:
        open_ms = bar_close_ms - self.frame_ms
        p, t, n = self._p, self.sig_t, self._n
        while p < n and t[p] < open_ms:
            p += 1
        self._p = p
        if p < n and t[p] == open_ms:
            v = self.sig_vol[p] if self.sig_vol is not None else float("nan")
            vol_val = float(v) if v is not None and not (isinstance(v, float) and math.isnan(v)) else float("nan")
            return {
                "match": self.sig_match[p],
                "stop": self.sig_stop[p],
                "vol": vol_val,
                "dca": self.sig_dca[p] if self.sig_dca is not None else True,
            }
        return None



class LiveSignals(SignalProvider):
    """Bộ đệm nến tính tín hiệu trực tiếp trên từng nến đã đóng (cùng evaluate_signals với backtest).

    Khung chạy (base) nhận nến đóng từ Nautilus; khung lớn hơn (khung tín hiệu / ATR) được dựng từ nến khung chạy khi nến của chúng đóng.
    Lịch sử: catalog (load_candles) + lấp đoạn thiếu tới hiện tại bằng REST OKX (crawl.fetch_rest_candles, chỉ nến confirm=1)."""

    def __init__(self, symbol: str, strategy: Dict[str, Any], base_frame: str,
                 frames: Optional[Dict[str, pd.DataFrame]] = None,
                 warmup_ms: Optional[int] = None):
        self.symbol = symbol
        self.strategy = strategy
        self.base_frame = base_frame
        self.base_ms = FRAME_MS[base_frame]
        self.frames: Dict[str, pd.DataFrame] = {}
        if frames:
            for fr, df in frames.items():
                self.frames[fr] = df.copy()

        # Xác định các khung cần thiết từ AST và position
        self.signal_frames = self._signal_frames()
        extra_4h = {"4h"} if ("4h" in self.frames or "4h" in self.signal_frames) else set()
        self.required_frames = {self.base_frame} | set(self.signal_frames) | extra_4h
        self.warmup_ms = int(warmup_ms if warmup_ms is not None else self._calc_warmup_ms())
        self.other_max_ms = max([FRAME_MS[f] for f in self.required_frames if f != self.base_frame] + [0])
        self.base_referenced = self.base_frame in self.signal_frames
        self.keep_ms = int(4 * self.warmup_ms if self.base_referenced else max(2 * self.other_max_ms + 3 * self.base_ms, 300 * self.base_ms))
        self.trim = False

    def _extract_all_refs(self) -> Set[Tuple[str, str, int]]:
        refs: Set[Tuple[str, str, int]] = set()
        for key in ("tree", "match_root", "dca_root"):
            root = self.strategy.get(key)
            if root:
                refs.update(collect_field_refs(root))
        for key in ("stop", "dca"):
            items = self.strategy.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and "condition" in item:
                        refs.update(collect_field_refs(item["condition"]))
                    else:
                        refs.update(collect_field_refs(item))
            elif items:
                refs.update(collect_field_refs(items))
        if self.strategy.get("stop_root"):
            refs.update(collect_field_refs(self.strategy["stop_root"]))
        return refs

    def _signal_frames(self) -> Set[str]:
        frames = {ref[0] for ref in self._extract_all_refs()}
        pos = self.strategy.get("position") or {}
        atr_tf = pos.get("atr_frame") or pos.get("sl_atr_timeframe") or pos.get("tp_atr_timeframe") or pos.get("dca_atr_timeframe")
        if atr_tf:
            frames.add(atr_tf)
        return {f for f in frames if f in FRAME_MS}

    def _calc_warmup_ms(self) -> int:
        by_frame: Dict[str, Set[Tuple[str, int]]] = {}
        for fr, col, lag in self._extract_all_refs():
            by_frame.setdefault(fr, set()).add((col, lag))
        pos = self.strategy.get("position") or {}
        atr_tf = pos.get("atr_frame") or pos.get("sl_atr_timeframe") or pos.get("tp_atr_timeframe") or pos.get("dca_atr_timeframe")
        atr_p = pos.get("atr_period") or pos.get("sl_atr_period", 14)
        if atr_tf:
            by_frame.setdefault(atr_tf, set()).add((f"natr_{atr_p}", 0))

        max_ms = 0
        for fr, refs in by_frame.items():
            if fr in FRAME_MS:
                bars = max([kernels.warmup_bars(c) + lag for c, lag in refs] + [0])
                max_ms = max(max_ms, (bars + 2) * FRAME_MS[fr])
        for fr in self.signal_frames:
            max_ms = max(max_ms, 200 * FRAME_MS[fr])
        return max(max_ms, 200 * self.base_ms)

    def is_warmed_up(self, end_ms: int) -> bool:
        start_ms = end_ms - self.warmup_ms
        for fr in self.required_frames:
            df = self.frames.get(fr)
            if df is None or df.empty:
                return False
            if df["open_time"].iloc[0] > start_ms:
                return False
        return True

    def at(self, bar_close_ms: int) -> Optional[Dict[str, Any]]:
        # Phải có dữ liệu cho các khung yêu cầu
        for fr in self.required_frames:
            df = self.frames.get(fr)
            if df is None or df.empty:
                return None

        # Lấy các nến đã đóng tính đến bar_close_ms
        window_frames = {}
        for fr in self.required_frames:
            df = self.frames[fr]
            df_cut = df[df["open_time"] + FRAME_MS[fr] <= bar_close_ms]
            if df_cut.empty:
                return None
            window_frames[fr] = df_cut

        # Sử dụng evaluate_signals dùng chung với backtest
        sig = evaluate_signals(self.symbol, [self.strategy], window_frames, self.base_frame)
        if not sig or not sig.get("entries"):
            return None
        entry = sig["entries"][0]
        t_arr = sig.get("t")
        if t_arr is None or len(t_arr) == 0:
            return None

        # Tra nến tại open_ms của nến đóng
        open_ms = bar_close_ms - self.base_ms
        for i in range(len(t_arr) - 1, -1, -1):
            if t_arr[i] == open_ms:
                vol = entry["vol"][i] if entry.get("vol") is not None else float("nan")
                dca = entry["dca"][i] if entry.get("dca") is not None else True
                return {
                    "match": bool(entry["match"][i]),
                    "stop": bool(entry["stop"][i]),
                    "vol": float(vol),
                    "dca": bool(dca),
                }
        return None

    def latest_event(self, now_ms: int) -> Optional[Dict[str, Any]]:
        """Lấy sự kiện tín hiệu gần nhất tại thời điểm now_ms (nến tín hiệu đóng gần nhất <= now_ms)."""
        primary_fr = next(iter(self.signal_frames), self.base_frame)
        fr_ms = FRAME_MS[primary_fr]
        df = self.frames.get(primary_fr)
        if df is None or df.empty:
            df = self.frames.get(self.base_frame)
            if df is None or df.empty:
                return None
            fr_ms = self.base_ms

        closed = df[df["open_time"] + fr_ms <= now_ms]
        if closed.empty:
            return None
        last_open_time = int(closed["open_time"].iloc[-1])
        close_ts = last_open_time + fr_ms

        sig = self.at(close_ts)
        match_val = bool(sig["match"]) if sig else False
        stop_val = bool(sig["stop"]) if sig else False
        vol_val = float(sig["vol"]) if sig and sig.get("vol") is not None else float("nan")
        dca_val = bool(sig["dca"]) if sig and sig.get("dca") is not None else True

        return {
            "match": match_val,
            "stop": stop_val,
            "vol": vol_val,
            "dca": dca_val,
            "open_time": last_open_time if match_val else None,
            "signal_open_time": last_open_time,
            "last_open_time": last_open_time,
        }

    # ─── Nạp lịch sử (bootstrap) ────────────────────────────────────────────
    def rest_1m(self, start_ms: int, end_ms: int) -> pd.DataFrame:
        """Đọc nến 1m REST từ cache/catalog (nếu có pkl) hoặc tải qua OKX REST (crawl.fetch_rest_candles, confirm=1)."""
        from backend.data import crawl
        from backend.models.storage import data_home
        path = os.path.join(data_home(), "candles", "1m", f"{self.symbol}.pkl")
        if os.path.isfile(path):
            try:
                st = os.stat(path)
                if st.st_size > 0:
                    df = pd.read_pickle(path)
                    sub = df[(df["open_time"] >= start_ms) & (df["open_time"] <= end_ms)]
                    if not sub.empty and sub["open_time"].iloc[-1] >= end_ms - 2 * MINUTE_MS:
                        return sub.reset_index(drop=True)
            except Exception:
                pass
        base_coin = self.symbol.split("@")[0].split("-")[0].split("/")[0].upper()
        with requests.Session() as s:
            return crawl.fetch_rest_candles(s, base_coin, start_ms, end_ms)

    @staticmethod
    def _aggregate(df_1m: pd.DataFrame, frame: str, frame_ms: int) -> pd.DataFrame:
        """Gộp nến 1m thành khung lớn hơn (open: đầu, high: max, low: min, close: cuối, vol: sum). Chỉ nến ĐÃ ĐỦ chu kỳ."""
        if df_1m.empty or frame_ms <= MINUTE_MS:
            return df_1m
        df = df_1m.copy()
        df["group"] = df["open_time"] // frame_ms * frame_ms
        res = df.groupby("group").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).reset_index().rename(columns={"group": "open_time"})
        return res

    def bootstrap(self, start_ms: int, now_ms: Optional[int] = None) -> Dict[str, Any]:
        """Nạp catalog nến cho mọi khung cần thiết (>= start_ms - warmup_ms), lấp đoạn thiếu đến now_ms qua REST 1m."""
        now_ms = now_ms or int(pd.Timestamp.now().timestamp() * 1000)
        warm_start = start_ms - self.warmup_ms
        cat_end_close = 0
        for fr in self.required_frames:
            df = dat.load_candles(self.symbol, fr, warm_start, now_ms)
            if not df.empty:
                self.frames[fr] = df[_COLS].copy()
                cat_end_close = max(cat_end_close, int(df["open_time"].iloc[-1]) + FRAME_MS[fr])
            else:
                self.frames[fr] = pd.DataFrame(columns=_COLS)

        rest_start = cat_end_close if cat_end_close > 0 else warm_start
        rest = self.rest_1m(rest_start, now_ms - MINUTE_MS)
        if not rest.empty:
            for fr in self.required_frames:
                df = self.frames[fr]
                ext = self._aggregate(rest, fr, FRAME_MS[fr])
                nxt = int(df["open_time"].iloc[-1]) + FRAME_MS[fr] if not df.empty else 0
                self.frames[fr] = pd.concat([df[_COLS], ext[ext["open_time"] >= nxt]], ignore_index=True)
        self.trim = True
        self._trim()
        return {"catalog_end_close": cat_end_close, "rest_rows": int(len(rest)), "frames": {fr: len(df) for fr, df in self.frames.items()}}

    def warm_start(self, now_ms: Optional[int] = None) -> Dict[str, Any]:
        """Nạp lịch sử tín hiệu tới nến hiện tại (gọi bootstrap từ now_ms)."""
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        return self.bootstrap(now, now)

    # ─── Nến mới ────────────────────────────────────────────────────────────
    def _trim(self) -> None:
        df = self.frames.get(self.base_frame)
        if df is not None and not df.empty and (self.trim or self.keep_ms):
            cut = int(df["open_time"].iloc[-1]) - self.keep_ms
            if int(df["open_time"].iloc[0]) < cut and self.trim_enabled():
                self.frames[self.base_frame] = df[df["open_time"] >= cut].reset_index(drop=True)

    def trim_enabled(self) -> bool:
        return True

    def on_base_bar(self, close_ms: int, o: float, h: float, l: float, c: float, v: float) -> None:
        self.on_bar(self.base_frame, {"open_time": close_ms - self.base_ms, "open": o, "high": h, "low": l, "close": c, "volume": v})

    def on_bar(self, frame: str, candle_dict: Dict[str, Any]) -> None:
        """Nhận nến đã đóng từ WS hoặc adapter.

        candle_dict phải có ít nhất: open_time, open, high, low, close, volume.
        ts_event nếu có phải là giờ đóng nến (open_time + FRAME_MS[frame]).
        """
        fr_ms = FRAME_MS[frame]
        open_time = candle_dict.get("open_time")
        if open_time is None and "ts_event" in candle_dict:
            open_time = candle_dict["ts_event"] - fr_ms
        if open_time is None:
            return

        row = {
            "open_time": int(open_time),
            "open": float(candle_dict["open"]),
            "high": float(candle_dict["high"]),
            "low": float(candle_dict["low"]),
            "close": float(candle_dict["close"]),
            "volume": float(candle_dict.get("volume", 0.0)),
        }
        if frame == self.base_frame and self.trim:
            self._fill_gap(row["open_time"])
        self._put(frame, row)
        if frame == self.base_frame:
            self._derive(row["open_time"] + fr_ms)
            self._trim()

    def _put(self, frame: str, row: Dict[str, Any]) -> None:
        if frame in self.frames and not self.frames[frame].empty:
            df = self.frames[frame]
            if "is_filled" in df.columns:
                row = {**row, "is_filled": 0}
            df_row = pd.DataFrame([row])
            if (df["open_time"] == row["open_time"]).any():
                df.loc[df["open_time"] == row["open_time"], list(row.keys())] = list(row.values())
            else:
                self.frames[frame] = pd.concat([df, df_row], ignore_index=True)
        else:
            self.frames[frame] = pd.DataFrame([row])

    def _fill_gap(self, open_time: int) -> None:
        """Mất kết nối / thiếu nến: lấp các nến khung chạy giữa nến cuối đã có và nến vừa tới bằng REST."""
        df = self.frames.get(self.base_frame)
        if df is None or df.empty:
            return
        last = int(df["open_time"].iloc[-1])
        if open_time - last <= self.base_ms:
            return
        try:
            m1 = self.rest_1m(last + self.base_ms, open_time - MINUTE_MS)
            if not m1.empty:
                ext = self._aggregate(m1, self.base_frame, self.base_ms)
                for _, r in ext.iterrows():
                    self._put(self.base_frame, r.to_dict())
        except Exception:
            pass

    def _derive(self, close_ms: int) -> None:
        """Từ các nến khung chạy đã nhận, dựng các nến khung lớn hơn khi chúng vừa đóng."""
        df_base = self.frames.get(self.base_frame)
        if df_base is None or df_base.empty:
            return
        for fr in self.signal_frames:
            if fr == self.base_frame:
                continue
            fr_ms = FRAME_MS[fr]
            if close_ms % fr_ms != 0:
                continue
            open_fr = close_ms - fr_ms
            sub = df_base[(df_base["open_time"] >= open_fr) & (df_base["open_time"] < close_ms)]
            if sub.empty:
                continue
            agg_row = {
                "open_time": open_fr,
                "open": float(sub["open"].iloc[0]),
                "high": float(sub["high"].max()),
                "low": float(sub["low"].min()),
                "close": float(sub["close"].iloc[-1]),
                "volume": float(sub["volume"].sum()),
            }
            self._put(fr, agg_row)


# ── TradingView Standard & Global TA Mappings ──
GLOBAL_TA_FUNCS: Dict[str, Tuple[str, str]] = {
    # ── 1. Tín hiệu giao cắt & quan hệ (TradingView ta.cross*) ──
    "crossover": ("op", "crossed_above"),
    "crossunder": ("op", "crossed_below"),
    "cross": ("op", "crossed"),
    "crossed_above": ("op", "crossed_above"),
    "crossed_below": ("op", "crossed_below"),
    "crossed": ("op", "crossed"),

    # ── 2. Chỉ báo kỹ thuật phổ biến (TradingView ta.*) ──
    "ema": ("feat", "ema"),
    "sma": ("feat", "sma"),
    "rsi": ("feat", "rsi"),
    "atr": ("feat", "atr"),
    "macd": ("feat", "macd"),
    "bbands": ("feat", "bollinger_bands"),
    "bollinger": ("feat", "bollinger_bands"),
    "bollinger_bands": ("feat", "bollinger_bands"),
    "stoch": ("feat", "stochastic"),
    "stochastic": ("feat", "stochastic"),
    "adx": ("feat", "adx"),
    "cci": ("feat", "cci"),
    "vwap": ("feat", "vwap"),
    "williams_r": ("feat", "williams_r"),
    "mfi": ("feat", "mfi"),
    "supertrend": ("feat", "supertrend"),
    "keltner": ("feat", "keltner_channels"),
    "donchian": ("feat", "donchian_channels"),

    # ── 3. Thống kê & Chuỗi thời gian ──
    "highest": ("feat", "rolling_max"),
    "lowest": ("feat", "rolling_min"),
    "rolling_max": ("feat", "rolling_max"),
    "rolling_min": ("feat", "rolling_min"),
    "rolling_mean": ("feat", "rolling_mean"),
    "rolling_std": ("feat", "rolling_std"),
    "rolling_sum": ("feat", "rolling_sum"),
    "stddev": ("feat", "stddev"),
    "returns": ("feat", "returns"),
    "zscore": ("feat", "zscore"),

    # ── 4. Toán tử chuỗi (TradingView ta.change, ta.barssince...) ──
    "change": ("op", "diff"),
    "diff": ("op", "diff"),
    "pct_change": ("op", "pct_change"),
    "previous": ("op", "previous"),
    "shift": ("op", "shift"),
    "bars_since": ("op", "bars_since"),
    "barssince": ("op", "bars_since"),
    "value_when": ("op", "value_when"),
    "valuewhen": ("op", "value_when"),
    "rising": ("op", "rising"),
    "falling": ("op", "falling"),
    "where": ("op", "where"),
    "fillna": ("op", "fillna"),
    "ffill": ("op", "ffill"),
    "clip": ("op", "clip"),
}

OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")

RISK_PARAM_MAP = {
    "stop_loss_pct": "stop_loss_rate",
    "stop_loss": "stop_loss_rate",
    "take_profit_pct": "take_profit_rate",
    "take_profit": "take_profit_rate",
    "trailing_stop_pct": "trailing_stop",
    "trailing_pct": "trailing_stop",
    "trailing_activation": "trailing_activation_pct",
    "risk_pct": "risk_per_trade_pct",
    "risk_per_trade": "risk_per_trade_pct",
}


# ══════════════════════════════════════════════════════════════════════════
# Proxima Alpha Signal & Decision Engine (Bộ Não Tín Hiệu & Quyết Định Chiến Lược)
# ══════════════════════════════════════════════════════════════════════════

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SignalDecision:
    """Quyết định chiến lược phát ra từ signal.py gửi sang execution.py."""
    signal: str                             # "LONG", "SHORT", "FLAT"
    intent: str                             # "ENTRY", "CENTER_EXIT", "OPPOSITE_BAND", "PARTIAL_TP", "HOLD"
    side: str                               # "BUY", "SELL", "HOLD"
    signal_price: float                     # Giá nến 1m hiện tại
    sl_reference: Optional[float] = None    # Mức giá Stop Loss đề xuất theo logic chiến lược
    tp_reference: Optional[float] = None    # Mức giá Take Profit đề xuất theo logic chiến lược
    exit_reason: str = "none"               # "none", "center_exit", "opposite_band", "partial_tp"
    atr: float = 0.0                        # ATR(14) nến 1h
    k_delta: float = 0.0                    # F * ATR
    z_score: float = 0.0                    # Độ lệch cực trị trên (High - Upper) / K_delta
    w_score: float = 0.0                    # Độ lệch cực trị dưới (Lower - Low) / K_delta
    regime_context: Dict[str, Any] = field(default_factory=dict)


class ProximaSignalEngine:
    """Bộ tính toán chỉ báo và sinh quyết định tín hiệu Alpha Proxima (Anchor 1h, Execution 1m)."""

    def __init__(
        self,
        ema_k: int = 20,
        atr_period: int = 14,
        f_multiplier: float = 1.0,
        tp_mult: float = 0.8,
        warmup_required: Optional[int] = None,
    ):
        self.ema_k = ema_k
        self.atr_period = atr_period
        self.f_multiplier = f_multiplier
        self.tp_mult = tp_mult
        self.warmup_required = warmup_required if warmup_required is not None else max(ema_k, atr_period)

        self._ema_val: Optional[float] = None
        self._atr_val: Optional[float] = None
        self._last_processed_fingerprint: Optional[Tuple[Any, ...]] = None
        self.locked_reentry: bool = False

    @property
    def is_warmed_up(self) -> bool:
        return self._ema_val is not None and self._atr_val is not None

    def update_anchor_indicators(self, closed_1h_bars: List[Dict[str, float]]) -> None:
        """Cập nhật EMA(20) và ATR(14) chỉ từ các nến 1h đã đóng hoàn toàn và đủ warmup.
        
        Hỗ trợ tự động tính lại chỉ báo khi có nến đến muộn (Late Bar) làm cập nhật lại Anchor Bar cũ.
        """
        if not closed_1h_bars or len(closed_1h_bars) < self.warmup_required:
            self._ema_val = None
            self._atr_val = None
            return

        # Dấu vân tay kiểm tra thay đổi dữ liệu (kể cả khi nến cũ được recompute)
        fingerprint = (
            len(closed_1h_bars),
            closed_1h_bars[-1]["timestamp"],
            closed_1h_bars[-1]["high"],
            closed_1h_bars[-1]["low"],
            closed_1h_bars[-1]["close"],
        )
        if fingerprint == self._last_processed_fingerprint:
            return

        # Tính toán chuỗi EMA trên toàn bộ lịch sử nến 1h đã đóng
        alpha_ema = 2.0 / (self.ema_k + 1.0)
        ema = closed_1h_bars[0]["close"]
        for b in closed_1h_bars[1:]:
            ema = (b["close"] * alpha_ema) + (ema * (1.0 - alpha_ema))
        self._ema_val = ema

        # ATR(14) chuẩn theo Wilder (chỉ xác nhận khi đủ atr_period True Range)
        trs = []
        for idx, b in enumerate(closed_1h_bars):
            if idx == 0:
                trs.append(b["high"] - b["low"])
            else:
                prev_c = closed_1h_bars[idx - 1]["close"]
                trs.append(max(b["high"] - b["low"], abs(b["high"] - prev_c), abs(b["low"] - prev_c)))

        if len(trs) >= self.atr_period:
            atr = sum(trs[:self.atr_period]) / self.atr_period
            for tr in trs[self.atr_period:]:
                atr = (atr * (self.atr_period - 1) + tr) / self.atr_period
            self._atr_val = atr
        else:
            self._atr_val = None  # Chưa đủ 14 True Range -> không phát tín hiệu giả định
            return

        self._last_processed_fingerprint = fingerprint

    def detect_regime(self, current_1m_close: float) -> Dict[str, Any]:
        """Phân loại bối cảnh thị trường nhẹ nhàng để tham khảo."""
        if not self._ema_val or not self._atr_val or self._atr_val <= 0:
            return {"regime": "RANGE", "strength": 0.0}

        dist_from_ema = (current_1m_close - self._ema_val) / self._atr_val
        atr_pct = (self._atr_val / self._ema_val) * 100.0

        if atr_pct > 2.0:
            regime = "VOL_EXPANSION"
        elif dist_from_ema > 0.8:
            regime = "TREND_UP"
        elif dist_from_ema < -0.8:
            regime = "TREND_DOWN"
        else:
            regime = "RANGE"

        return {
            "regime": regime,
            "dist_from_ema_atr": round(dist_from_ema, 3),
            "atr_pct": round(atr_pct, 3),
        }

    def evaluate(
        self,
        bar_1m: Dict[str, float],
        position_context: Optional[Dict[str, Any]] = None,
    ) -> SignalDecision:
        """Đánh giá tín hiệu và quyết định hành động (Entry, Center Exit, Opposite Band, Partial TP).
        
        Quy tắc Cách A (Đặc tả Proxima Reference gốc):
        - Upper = EMA + F * ATR
        - Lower = EMA - F * ATR
        - K_delta = 2 * F * ATR (độ rộng toàn dải Upper - Lower)
        - z = (High_1m - Upper) / K_delta
        - w = (Lower - Low_1m) / K_delta
        - LONG khi z > F (High_1m > EMA + (1 + 2F) * F * ATR = EMA + 3 * ATR với F=1)
        - SHORT khi w > F (Low_1m < EMA - 3 * ATR với F=1)
        """
        px = bar_1m["close"]
        high_1m = bar_1m["high"]
        low_1m = bar_1m["low"]

        if not self.is_warmed_up or self._ema_val is None or self._atr_val is None:
            return SignalDecision(
                signal="FLAT", intent="HOLD", side="HOLD", signal_price=px,
            )

        ema: float = self._ema_val
        atr: float = self._atr_val
        # Định nghĩa Cách A: Upper/Lower dùng F * ATR, K_delta = 2 * F * ATR
        k_half: float = self.f_multiplier * atr
        k_delta: float = 2.0 * k_half
        upper_band: float = ema + k_half
        lower_band: float = ema - k_half

        z_score = (high_1m - upper_band) / k_delta if k_delta > 1e-8 else 0.0
        w_score = (lower_band - low_1m) / k_delta if k_delta > 1e-8 else 0.0
        regime_ctx = self.detect_regime(px)

        pos_ctx = position_context or {}
        qty_contracts = float(pos_ctx.get("qty_contracts", 0.0))
        entry_price = float(pos_ctx.get("entry_price", 0.0))
        already_partial_tp = bool(pos_ctx.get("already_partial_tp", False))

        # ─── 1. KHI ĐANG CÓ VỊ THẾ -> XÉT CÁC ĐIỀU KIỆN THOÁT LỆNH ──────
        if abs(qty_contracts) > 1e-9 and entry_price > 0:
            is_long = qty_contracts > 0

            # Bước 1.1: Opposite Band (Giá xuyên thủng biên đối diện - Intrabar)
            opposite_hit = (is_long and low_1m <= lower_band) or (not is_long and high_1m >= upper_band)
            if opposite_hit:
                return SignalDecision(
                    signal="FLAT",
                    intent="OPPOSITE_BAND",
                    side="SELL" if is_long else "BUY",
                    signal_price=lower_band if is_long else upper_band,
                    exit_reason="opposite_band",
                    atr=atr,
                    k_delta=k_delta,
                    z_score=z_score,
                    w_score=w_score,
                    regime_context=regime_ctx,
                )

            # Bước 1.2: Center Exit (Giá đóng nến 1m quay về chạm EMA_K)
            center_hit = (is_long and px <= ema) or (not is_long and px >= ema)
            if center_hit:
                self.locked_reentry = True
                return SignalDecision(
                    signal="FLAT",
                    intent="CENTER_EXIT",
                    side="SELL" if is_long else "BUY",
                    signal_price=ema,
                    exit_reason="center_exit",
                    atr=atr,
                    k_delta=k_delta,
                    z_score=z_score,
                    w_score=w_score,
                    regime_context=regime_ctx,
                )

            # Bước 1.3: Partial TP (Đạt mục tiêu 5% * TP)
            best_px = high_1m if is_long else low_1m
            ret = (best_px - entry_price) / entry_price if is_long else (entry_price - best_px) / entry_price
            target_tp = 0.05 * self.tp_mult

            if not already_partial_tp and ret >= target_tp:
                tp_ref_price = entry_price * (1.0 + target_tp) if is_long else entry_price * (1.0 - target_tp)
                return SignalDecision(
                    signal="FLAT",
                    intent="PARTIAL_TP",
                    side="SELL" if is_long else "BUY",
                    signal_price=tp_ref_price,
                    exit_reason="partial_tp",
                    atr=atr,
                    k_delta=k_delta,
                    z_score=z_score,
                    w_score=w_score,
                    regime_context=regime_ctx,
                )

            return SignalDecision(
                signal="FLAT", intent="HOLD", side="HOLD", signal_price=px,
                atr=atr, k_delta=k_delta, z_score=z_score, w_score=w_score,
                regime_context=regime_ctx,
            )

        # ─── 2. KHI ĐANG FLAT -> XÉT MỞ VỊ THẾ MỚI (BREAKOUT CHUẨN PROXIMA) ──────────
        # Mở khóa re-entry khi giá đi hẳn ra ngoài dải
        if self.locked_reentry:
            if px >= upper_band or px <= lower_band:
                self.locked_reentry = False

        if not self.locked_reentry:
            # Chuẩn Proxima Reference: z > F (với F = f_multiplier)
            if z_score > self.f_multiplier and high_1m > upper_band:
                tp_pct = 0.05 * self.tp_mult
                sl_ref = px - (1.5 * atr)
                tp_ref = px * (1.0 + tp_pct)
                return SignalDecision(
                    signal="LONG",
                    intent="ENTRY",
                    side="BUY",
                    signal_price=px,
                    sl_reference=sl_ref,
                    tp_reference=tp_ref,
                    exit_reason="none",
                    atr=atr,
                    k_delta=k_delta,
                    z_score=z_score,
                    w_score=w_score,
                    regime_context=regime_ctx,
                )
            # Chuẩn Proxima Reference: w > F (với F = f_multiplier)
            elif w_score > self.f_multiplier and low_1m < lower_band:
                tp_pct = 0.05 * self.tp_mult
                sl_ref = px + (1.5 * atr)
                tp_ref = px * (1.0 - tp_pct)
                return SignalDecision(
                    signal="SHORT",
                    intent="ENTRY",
                    side="SELL",
                    signal_price=px,
                    sl_reference=sl_ref,
                    tp_reference=tp_ref,
                    exit_reason="none",
                    atr=atr,
                    k_delta=k_delta,
                    z_score=z_score,
                    w_score=w_score,
                    regime_context=regime_ctx,
                )

        return SignalDecision(
            signal="FLAT", intent="HOLD", side="HOLD", signal_price=px,
            atr=atr, k_delta=k_delta, z_score=z_score, w_score=w_score,
            regime_context=regime_ctx,
        )



