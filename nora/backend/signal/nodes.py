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
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from backend.signal.indicator import Spec, evaluate_feature, nan_nonfinite
from backend.models.params import DATA_COLUMNS, FRAME_MS, MINUTE_MS as MINUTE, REGIME_NAMES


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


# check_signals: ở nautilus/engine.py (cần BacktestEngine + nguồn dữ liệu; engine-API pass).
