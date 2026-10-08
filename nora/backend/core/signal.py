"""Bộ dịch tín hiệu (P9.4 part 2): DSL Python (errors, program, parser, explain) + bộ thông dịch AST (evaluator) + ảnh chụp tín hiệu (snapshot)
+ kiểm tra tín hiệu (diagnostics) + API biên dịch (compile_code/compile_report/explain_report, từ pydsl/__init__).

Hợp nhất NGUYÊN VĂN từ core/strategy/pydsl/{errors,program,parser,explain,__init__}.py + core/signals/{evaluator,snapshot,diagnostics}.py
(xem docs/bmad/p9_review_log.md, mục P9.4 part 2). Đường dẫn cũ là shim. Chỉ import `params` và `indicator` (không import backtest ở đầu file;
snapshot/diagnostics còn import cục bộ trong hàm tới backtest/regime/book — vi phạm có từ trước, ghi ở log).
"""
import ast
import difflib
import hashlib
import math
import operator
from collections import OrderedDict
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np

from backend.core.indicator import FEATURES, OPS, REQUIRED, Spec, evaluate_feature, register_program
from backend.core.params import NORA_DEFAULTS


# ══════════════════════════════════════════════════════════════════════════
# P9.4 part 2 — nguyên văn từ core/strategy/pydsl/errors.py
#
# Lỗi biên dịch DSL chiến lược Python: luôn có số dòng + cột (1-based) để UI tô đúng chỗ.
# ══════════════════════════════════════════════════════════════════════════

class DslError(ValueError):
    """Lỗi biên dịch / chạy chương trình DSL. line, col (1-based) trỏ vào mã nguồn của người dùng (None nếu không gắn được vào dòng nào)."""

    def __init__(self, message: str, line: Optional[int] = None, col: Optional[int] = None):
        self.message = message
        self.line = line
        self.col = col
        where = f"dòng {line}, cột {col}: " if line is not None else ""
        super().__init__(f"{where}{message}")

    def to_dict(self):
        return {"line": self.line, "col": self.col, "message": self.message}


def at(node, message: str) -> DslError:
    """DslError gắn vào một nút ast (lineno, col_offset 0-based -> cột 1-based)."""
    line = getattr(node, "lineno", None)
    col = getattr(node, "col_offset", None)
    return DslError(message, line, None if col is None else col + 1)


def suggest(name: str, options: Iterable[str], n: int = 4) -> str:
    """' Gần đúng: a, b, c' (rỗng nếu không có tên nào gần)."""
    close: List[str] = difflib.get_close_matches(str(name), list(options), n=n, cutoff=0.5)
    return f" Gần đúng: {', '.join(close)}." if close else ""


# ══════════════════════════════════════════════════════════════════════════
# P9.4 part 2 — nguyên văn từ core/strategy/pydsl/program.py
#
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


# ══════════════════════════════════════════════════════════════════════════
# P9.4 part 2 — nguyên văn từ core/strategy/pydsl/parser.py
#
# Trình biên dịch DSL: `ast.parse` rồi thông dịch theo DANH SÁCH TRẮNG (docs/bmad/p7_python_strategies.md §3). KHÔNG exec/eval code người dùng.
#
# Chấp nhận đúng một `class X(SimpleAlgorithm)` gồm thuộc tính lớp hằng và `def __algorithm__(self)`; trong đó chỉ có gán (kể cả unpack tuple),
# `self.set_positions(mask, position=w)` và docstring. Không vòng lặp, không if, không import, không hàm lồng, không and/or/not của Python.
# Mọi lỗi là DslError có dòng + cột. Kết quả là `Program` (IR đã kiểm loại, hằng số đã gấp).
# ══════════════════════════════════════════════════════════════════════════

DSL_VERSION = "1"            # đổi khi ngữ nghĩa DSL đổi -> mã băm (và cột py_...) đổi, không dùng nhầm kết quả cũ
MAX_CODE_CHARS = 50_000
MAX_NODES = 20_000
BASE_CLASS = "SimpleAlgorithm"
DATA_ATTRS = {f"pv_{c}": c for c in DATA_COLUMNS}
TIMEFRAME_ALIASES = {"1d": "24h", "d": "24h", "1day": "24h", "daily": "24h", "60m": "1h", "240m": "4h", "1440m": "24h"}
SPECIAL_ATTRS = {"timeframe", "position_open_times", "position_open_ranges", "position_close_ranges"}
_CMP = {ast.Gt: ">", ast.GtE: ">=", ast.Lt: "<", ast.LtE: "<=", ast.Eq: "==", ast.NotEq: "!="}
_ARITH = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Pow: "**"}
_METHODS = {"fillna": "fillna", "shift": "shift", "abs": "abs"}
_NOT_SUPPORTED_STMT = {
    ast.If: "`if` (DSL không có rẽ nhánh: dùng mặt nạ & | ~ hoặc self.op.where(cond, a, b))",
    ast.For: "vòng lặp `for` (DSL là biểu thức vector hoá trên cả chuỗi)",
    ast.While: "vòng lặp `while` (DSL là biểu thức vector hoá trên cả chuỗi)",
    ast.Import: "`import` (không cần import: self.data / self.feat / self.op có sẵn)",
    ast.ImportFrom: "`import` (không cần import: self.data / self.feat / self.op có sẵn)",
    ast.FunctionDef: "hàm lồng `def`", ast.Return: "`return` (kết quả là các lệnh self.set_positions)",
    ast.With: "`with`", ast.Try: "`try`", ast.Assert: "`assert`", ast.Delete: "`del`", ast.Global: "`global`",
    ast.AugAssign: "toán tử gán rút gọn (+=, ...): viết x = x + ...",
}


def _position_attr_names() -> Set[str]:
    from backend.core.params import POSITION_KEYS
    return set(POSITION_KEYS)


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


class _Compiler:
    def __init__(self, code: str):
        self.code = code
        self.consts: Dict[str, Any] = {}      # thuộc tính lớp hằng: tên -> số / chuỗi / list
        self.env: Dict[str, Any] = {}         # biến cục bộ: tên -> Node | TupleVal
        self.calls: List[Tuple[Node, float, int]] = []
        self.features: Set[str] = set()
        self.ops: Set[str] = set()
        self.columns: Set[str] = set()
        self.warnings: List[str] = []
        self.n_nodes = 0
        self.timeframe: Optional[str] = None
        self.open_times: List[int] = []
        self.open_ranges: List[Tuple[int, int]] = []
        self.close_ranges: List[Tuple[int, int]] = []
        self.position_overrides: Dict[str, Any] = {}
        self.name = ""

    # ─── cấp mô-đun / lớp ───────────────────────────────────────────────────
    def compile(self) -> Program:
        if len(self.code) > MAX_CODE_CHARS:
            raise DslError(f"Mã quá dài ({len(self.code)} ký tự > {MAX_CODE_CHARS})")
        try:
            tree = ast.parse(self.code)
        except SyntaxError as e:
            raise DslError(f"Lỗi cú pháp Python: {e.msg}", e.lineno, (e.offset or 1)) from None
        except (RecursionError, MemoryError, ValueError) as e:
            raise DslError(f"Không phân tích được mã: {type(e).__name__}") from None
        classes = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                classes.append(node)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                raise at(node, "Không dùng `import`: self.data / self.feat / self.op có sẵn, chỉ cần khai báo class X(SimpleAlgorithm)")
            else:
                raise at(node, "Ở cấp ngoài chỉ được có docstring và một class chiến lược")
        if len(classes) != 1:
            raise DslError(f"Cần đúng một class kế thừa {BASE_CLASS}, tìm thấy {len(classes)}", 1, 1)
        cls = classes[0]
        if not (len(cls.bases) == 1 and isinstance(cls.bases[0], ast.Name) and cls.bases[0].id == BASE_CLASS) or cls.keywords or cls.decorator_list:
            raise at(cls, f"Class phải có dạng `class {cls.name}({BASE_CLASS}):`")
        self.name = cls.name
        algo = None
        for stmt in cls.body:
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                continue
            if isinstance(stmt, ast.Pass):
                continue
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                self._class_attr(stmt)
            elif isinstance(stmt, ast.FunctionDef):
                if stmt.name != "__algorithm__":
                    raise at(stmt, f"Chỉ hỗ trợ hàm __algorithm__(self), không có `{stmt.name}`")
                if algo is not None:
                    raise at(stmt, "Chỉ được định nghĩa __algorithm__ một lần")
                if (len(stmt.args.args) != 1 or stmt.args.args[0].arg != "self" or stmt.args.vararg or stmt.args.kwarg or stmt.args.kwonlyargs
                        or stmt.args.defaults or stmt.decorator_list):
                    raise at(stmt, "Chữ ký phải đúng `def __algorithm__(self):`")
                algo = stmt
            else:
                raise at(stmt, f"Trong class chỉ được có thuộc tính hằng và __algorithm__ (gặp {type(stmt).__name__})")
        if algo is None:
            raise at(cls, "Thiếu `def __algorithm__(self):`")
        for st in algo.body:
            self._stmt(st)
        if not self.calls:
            raise at(algo, "__algorithm__ chưa gọi self.set_positions(mask, position=...) nên không có tín hiệu nào")
        if self.timeframe is None:
            self.timeframe = "24h"
            self.warnings.append("Không khai báo `timeframe`: dùng mặc định 24h.")
        return Program(name=self.name, code_hash=code_hash(tree), timeframe=self.timeframe, calls=self.calls, open_times=self.open_times,
                       open_ranges=self.open_ranges, close_ranges=self.close_ranges, position_overrides=self.position_overrides,
                       features=self.features, columns=self.columns, warnings=self.warnings, ops=self.ops)

    # ─── thuộc tính lớp ─────────────────────────────────────────────────────
    def _literal(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str, bool)):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)) and isinstance(node.operand, ast.Constant) \
                and isinstance(node.operand.value, (int, float)) and not isinstance(node.operand.value, bool):
            return -node.operand.value if isinstance(node.op, ast.USub) else node.operand.value
        if isinstance(node, (ast.List, ast.Tuple)):
            return [self._literal(e) for e in node.elts]
        raise at(node, "Thuộc tính lớp phải là hằng số / chuỗi / danh sách hằng (không có biểu thức hay lời gọi)")

    @staticmethod
    def _minutes(text: Any, node) -> int:
        try:
            hh, mm = str(text).strip().split(":")
            h, m = int(hh), int(mm)
            if not (0 <= h <= 24 and 0 <= m < 60) or (h == 24 and m):
                raise ValueError
            return (h * 60 + m) % 1440
        except ValueError:
            raise at(node, f"Giờ phải dạng \"HH:MM\" (UTC), nhận {text!r}") from None

    def _class_attr(self, stmt):
        target = stmt.targets[0] if isinstance(stmt, ast.Assign) else stmt.target
        if isinstance(stmt, ast.Assign) and len(stmt.targets) != 1:
            raise at(stmt, "Mỗi thuộc tính lớp một dòng: TÊN = hằng")
        if not isinstance(target, ast.Name):
            raise at(stmt, "Thuộc tính lớp phải có dạng TÊN = hằng")
        if stmt.value is None:
            raise at(stmt, "Thuộc tính lớp cần giá trị")
        name, value = target.id, self._literal(stmt.value)
        if name == "timeframe":
            tf = TIMEFRAME_ALIASES.get(str(value).strip().lower(), str(value).strip().lower())
            if tf not in TF_MS:
                raise at(stmt.value, f"timeframe {value!r} không hỗ trợ; có: {list(TF_MS)}")
            self.timeframe = tf
        elif name in ("position_open_times", "position_open_ranges", "position_close_ranges"):
            items = value if isinstance(value, list) else [value]
            for it in items:
                if not isinstance(it, str):
                    raise at(stmt.value, f"{name} là danh sách chuỗi giờ UTC")
            if name == "position_open_times":
                self.open_times = [self._minutes(i, stmt.value) for i in items]
            else:
                rng = []
                for it in items:
                    parts = it.split("-")
                    if len(parts) != 2:
                        raise at(stmt.value, f"{name}: khoảng giờ dạng \"HH:MM-HH:MM\", nhận {it!r}")
                    rng.append((self._minutes(parts[0], stmt.value), self._minutes(parts[1], stmt.value)))
                (self.open_ranges if name == "position_open_ranges" else self.close_ranges).extend(rng)
        elif name in _position_attr_names():
            self.position_overrides[name] = value
        else:
            self.consts[name] = value

    # ─── câu lệnh trong __algorithm__ ───────────────────────────────────────
    def _stmt(self, st):
        if isinstance(st, ast.Expr):
            if isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
                return
            if (isinstance(st.value, ast.Call) and isinstance(st.value.func, ast.Attribute) and st.value.func.attr == "set_positions"
                    and self._is_self(st.value.func.value)):
                return self._set_positions(st.value)
            raise at(st, "Câu lệnh biểu thức đứng riêng không có tác dụng; chỉ self.set_positions(...) được gọi như một lệnh")
        if isinstance(st, ast.Pass):
            return
        if isinstance(st, ast.Assign):
            if len(st.targets) != 1:
                raise at(st, "Chỉ gán một đích mỗi dòng (a = ... hoặc a, b = ...)")
            return self._assign(st.targets[0], st.value, st)
        if isinstance(st, ast.AnnAssign):
            if st.value is None:
                raise at(st, "Khai báo kiểu cần có giá trị")
            return self._assign(st.target, st.value, st)
        for t, what in _NOT_SUPPORTED_STMT.items():
            if isinstance(st, t):
                raise at(st, f"Chưa hỗ trợ {what}")
        raise at(st, f"Câu lệnh {type(st).__name__} chưa được hỗ trợ")

    def _assign(self, target, value_node, st):
        val = self._expr_multi(value_node)
        if isinstance(target, ast.Name):
            self._check_name(target)
            self.env[target.id] = val
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            names = []
            for e in target.elts:
                if not isinstance(e, ast.Name):
                    raise at(e, "Unpack chỉ nhận tên biến")
                self._check_name(e)
                names.append(e.id)
            if not isinstance(val, TupleVal):
                raise at(value_node, f"Vế phải chỉ có một giá trị, không unpack được thành {len(names)} biến")
            if len(val.items) != len(names):
                raise at(value_node, f"Vế phải có {len(val.items)} giá trị nhưng gán cho {len(names)} biến")
            for nm, it in zip(names, val.items):
                self.env[nm] = it
            return
        raise at(target, "Đích gán phải là tên biến (hoặc tuple tên)")

    @staticmethod
    def _check_name(node):
        if node.id == "self":
            raise at(node, "Không gán lại `self`")
        if node.id == "SimpleAlgorithm":
            raise at(node, "Tên này dành riêng")

    @staticmethod
    def _is_self(node) -> bool:
        return isinstance(node, ast.Name) and node.id == "self"

    def _set_positions(self, call: ast.Call):
        if len(call.args) > 2:
            raise at(call, "set_positions(mask, position=w) chỉ nhận mặt nạ và mức vị thế")
        pos_node = call.args[1] if len(call.args) == 2 else None
        for kw in call.keywords:
            if kw.arg != "position":
                raise at(kw.value, f"Đối số `{kw.arg}` không hỗ trợ trong set_positions; chỉ có mask và position")
            if pos_node is not None:
                raise at(kw.value, "position bị khai báo hai lần")
            pos_node = kw.value
        if not call.args:
            raise at(call, "Thiếu mặt nạ: self.set_positions(mask, position=w)")
        if pos_node is None:
            raise at(call, "Thiếu `position=` (mức vị thế mục tiêu trong [-1, 1])")
        mask = self._expr(call.args[0])
        if mask.kind != "bool":
            raise at(call.args[0], "Mặt nạ phải là chuỗi bool (kết quả của so sánh / & | ~), không phải chuỗi số")
        level = self._expr(pos_node)
        if not isinstance(level, Const):
            raise at(pos_node, "position phải là hằng số (không phụ thuộc dữ liệu)")
        if not -1.0 <= level.value <= 1.0:
            raise at(pos_node, f"position phải trong [-1, 1], nhận {level.value:g}")
        self.calls.append((mask, level.value, call.lineno))

    # ─── biểu thức ──────────────────────────────────────────────────────────
    def _tick(self, node):
        self.n_nodes += 1
        if self.n_nodes > MAX_NODES:
            raise at(node, "Biểu thức quá lớn")

    def _expr_multi(self, node):
        """Như _expr nhưng cho phép trả TupleVal (vế phải của phép gán)."""
        if isinstance(node, ast.Tuple):
            return TupleVal([self._expr(e) for e in node.elts], node.lineno, node.col_offset + 1)
        v = self._expr(node, allow_tuple=True)
        return v

    def _expr(self, node, allow_tuple: bool = False):
        self._tick(node)
        v = self._expr_inner(node)
        if isinstance(v, TupleVal) and not allow_tuple:
            raise at(node, f"Hàm trả {len(v.items)} giá trị: gán `a, b, ... = ...` hoặc lấy chỉ số [0]")
        return v

    def _expr_inner(self, node):
        line, col = node.lineno, node.col_offset + 1
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return BoolConst(node.value, line, col)
            if isinstance(node.value, (int, float)):
                return Const(node.value, line, col)
            raise at(node, f"Hằng {type(node.value).__name__} không dùng được trong biểu thức")
        if isinstance(node, ast.Name):
            if node.id in self.env:
                return self.env[node.id]
            if node.id in ("abs", "min", "max", "round", "len", "sum", "float", "int"):
                raise at(node, f"Hàm Python `{node.id}` không dùng được: dùng self.op.* hoặc phương thức .abs()/.shift()/.fillna()")
            if node.id in ("np", "pd", "numpy", "pandas", "math"):
                raise at(node, f"`{node.id}` không có sẵn trong DSL: dùng self.feat.* / self.op.*")
            raise at(node, f"Biến `{node.id}` chưa được gán." + suggest(node.id, self.env))
        if isinstance(node, ast.Attribute):
            return self._attribute(node)
        if isinstance(node, ast.Call):
            return self._call(node)
        if isinstance(node, ast.BinOp):
            return self._binop(node)
        if isinstance(node, ast.UnaryOp):
            return self._unary(node)
        if isinstance(node, ast.Compare):
            return self._compare(node)
        if isinstance(node, ast.BoolOp):
            word = "and" if isinstance(node.op, ast.And) else "or"
            sym = "&" if word == "and" else "|"
            raise at(node, f"`{word}` của Python không dùng được trên chuỗi: dùng `{sym}` (nhớ đặt ngoặc quanh từng so sánh) hoặc self.op.{word}_()")
        if isinstance(node, ast.Subscript):
            return self._subscript(node)
        if isinstance(node, ast.IfExp):
            raise at(node, "Biểu thức điều kiện `a if c else b` không dùng được: dùng self.op.where(cond, a, b)")
        raise at(node, f"Biểu thức {type(node).__name__} chưa được hỗ trợ")

    def _subscript(self, node: ast.Subscript):
        base = self._expr(node.value, allow_tuple=True)
        idx = node.slice
        if isinstance(base, TupleVal) and isinstance(idx, ast.Constant) and isinstance(idx.value, int) and not isinstance(idx.value, bool):
            if not 0 <= idx.value < len(base.items):
                raise at(node, f"Chỉ số {idx.value} ngoài phạm vi 0..{len(base.items) - 1}")
            return base.items[idx.value]
        raise at(node, "Không dùng được chỉ mục [...] trên chuỗi (nhìn lại quá khứ: .shift(k) / self.op.previous; tương lai bị cấm)")

    def _attribute(self, node: ast.Attribute):
        # self.data.pv_close | self.<thuộc tính lớp>
        if isinstance(node.value, ast.Attribute) and self._is_self(node.value.value) and node.value.attr == "data":
            if node.attr not in DATA_ATTRS:
                raise at(node, f"self.data.{node.attr} không có." + suggest(node.attr, DATA_ATTRS))
            self.columns.add(DATA_ATTRS[node.attr])
            return Data(DATA_ATTRS[node.attr], node.lineno, node.col_offset + 1)
        if self._is_self(node.value):
            if node.attr in ("data", "feat", "op"):
                raise at(node, f"self.{node.attr} phải được dùng tiếp: " + {"data": "self.data.pv_close", "feat": "self.feat.<tên>(...)", "op": "self.op.<tên>(...)"}[node.attr])
            if node.attr in self.consts and isinstance(self.consts[node.attr], (int, float)) and not isinstance(self.consts[node.attr], bool):
                return Const(self.consts[node.attr], node.lineno, node.col_offset + 1)
            if node.attr in self.consts:
                raise at(node, f"self.{node.attr} không phải số nên không dùng được trong biểu thức")
            raise at(node, f"self.{node.attr} chưa được khai báo ở cấp class." + suggest(node.attr, self.consts))
        raise at(node, "Truy cập thuộc tính này chưa được hỗ trợ (chỉ self.data.pv_*, self.<hằng>, self.feat.*, self.op.*)")

    def _binop(self, node: ast.BinOp):
        sym = _ARITH.get(type(node.op))
        left, right = self._expr(node.left), self._expr(node.right)
        line, col = node.lineno, node.col_offset + 1
        if isinstance(node.op, (ast.BitAnd, ast.BitOr)):
            if left.kind != "bool" or right.kind != "bool":
                raise at(node, f"`{'&' if isinstance(node.op, ast.BitAnd) else '|'}` chỉ dùng cho mặt nạ bool (kết quả so sánh); "
                               "đặt ngoặc quanh từng so sánh: (a > b) & (c < d)")
            return Logic("&" if isinstance(node.op, ast.BitAnd) else "|", left, right, line, col)
        if sym is None:
            raise at(node, f"Toán tử `{type(node.op).__name__}` chưa được hỗ trợ (có: + - * / ** và & | ~)")
        for side, nd in ((left, node.left), (right, node.right)):
            if side.kind not in ("num", "bool"):
                raise at(nd, "Toán hạng không hợp lệ")
        if isinstance(left, Const) and isinstance(right, Const):          # gấp hằng số
            try:
                val = {"+": left.value + right.value, "-": left.value - right.value, "*": left.value * right.value,
                       "/": left.value / right.value, "**": left.value ** right.value}[sym]
            except (ZeroDivisionError, OverflowError):
                raise at(node, "Phép tính hằng số không hợp lệ (chia 0 hoặc tràn số)") from None
            if isinstance(val, complex) or val != val or val in (float("inf"), float("-inf")):
                raise at(node, "Phép tính hằng số không hợp lệ")
            return Const(val, line, col)
        return Bin(sym, left, right, line, col)

    def _unary(self, node: ast.UnaryOp):
        v = self._expr(node.operand)
        line, col = node.lineno, node.col_offset + 1
        if isinstance(node.op, ast.Invert):
            if v.kind != "bool":
                raise at(node, "`~` chỉ dùng cho mặt nạ bool (phủ định); đảo dấu số dùng `-`")
            return Inv(v, line, col)
        if isinstance(node.op, ast.Not):
            raise at(node, "`not` của Python không dùng được trên chuỗi: dùng `~mask` hoặc self.op.not_(mask)")
        if isinstance(node.op, (ast.USub, ast.UAdd)):
            if v.kind != "num":
                raise at(node, "Dấu +/- chỉ dùng cho chuỗi số")
            if isinstance(node.op, ast.UAdd):
                return v
            return Const(-v.value, line, col) if isinstance(v, Const) else Neg(v, line, col)
        raise at(node, "Toán tử một ngôi chưa được hỗ trợ")

    def _compare(self, node: ast.Compare):
        if len(node.ops) != 1:
            raise at(node, "Không dùng so sánh nối chuỗi (a < b < c): tách thành (a < b) & (b < c) hoặc self.op.between(b, a, c)")
        sym = _CMP.get(type(node.ops[0]))
        if sym is None:
            raise at(node, f"Phép so sánh `{type(node.ops[0]).__name__}` chưa được hỗ trợ (có: > >= < <= == !=)")
        a, b = self._expr(node.left), self._expr(node.comparators[0])
        for side, nd in ((a, node.left), (b, node.comparators[0])):
            if side.kind != "num":
                raise at(nd, "So sánh cần hai vế là số (chuỗi bool dùng & | ~)")
        return Cmp(sym, a, b, node.lineno, node.col_offset + 1)

    # ─── lời gọi ────────────────────────────────────────────────────────────
    def _call(self, node: ast.Call):
        fn = node.func
        if not isinstance(fn, ast.Attribute):
            what = fn.id if isinstance(fn, ast.Name) else "hàm"
            if what in ("abs", "min", "max", "round", "float", "int", "len", "sum"):
                raise at(node, f"Hàm Python `{what}` không dùng được: dùng self.op.* (vd. self.op.abs(x)) hoặc phương thức .abs()/.shift()/.fillna()")
            raise at(node, f"Không gọi được `{what}(...)`: dùng self.feat.<tên>(...), self.op.<tên>(...) hoặc phương thức .shift()/.fillna()/.abs()")
        v = fn.value
        if isinstance(v, ast.Attribute) and self._is_self(v.value) and v.attr in ("feat", "op"):
            table, label = (FEATURES, "feat") if v.attr == "feat" else (OPS, "op")
            spec = table.get(fn.attr)
            if spec is None:
                raise at(fn, f"self.{label}.{fn.attr} chưa được hỗ trợ." + suggest(fn.attr, table)
                         + (" (xem danh sách tại tài liệu P7 §3)" if label == "feat" else ""))
            return self._bind_call(spec, label == "feat", node, [self._expr(a) for a in node.args], list(node.args),
                                   [(k.arg, k.value, self._expr(k.value)) for k in node.keywords])
        if self._is_self(v) and fn.attr == "set_positions":
            raise at(node, "self.set_positions(...) là một câu lệnh, không dùng trong biểu thức")
        if self._is_self(v):
            raise at(node, f"self.{fn.attr}(...) không hỗ trợ")
        if fn.attr in _METHODS:     # series.fillna(v) / .shift(k) / .abs()
            base = self._expr(v)
            return self._bind_call(OPS[_METHODS[fn.attr]], False, node, [base] + [self._expr(a) for a in node.args],
                                   [v] + list(node.args), [(k.arg, k.value, self._expr(k.value)) for k in node.keywords])
        raise at(fn, f"Phương thức .{fn.attr}() chưa được hỗ trợ (có: {', '.join('.' + m + '()' for m in _METHODS)})" + suggest(fn.attr, _METHODS))

    def _bind_call(self, spec: Spec, is_feature: bool, node: ast.Call, args: List[Node], arg_nodes: list,
                   kwargs: List[Tuple[str, Any, Node]]):
        params = spec.params
        if len(args) > len(params):
            raise at(node, f"{spec.name} nhận tối đa {len(params)} đối số ({', '.join(p.name for p in params)})")
        given: Dict[str, Tuple[Node, Any]] = {}
        for p, a, an in zip(params, args, arg_nodes):
            given[p.name] = (a, an)
        names = [p.name for p in params]
        for k, knode, kv in kwargs:
            if k is None:
                raise at(knode, "Không dùng **kwargs")
            if k not in names:
                raise at(knode, f"{spec.name} không có tham số `{k}`." + suggest(k, names) + f" Tham số: {', '.join(names)}.")
            if k in given:
                raise at(knode, f"Tham số `{k}` bị truyền hai lần")
            given[k] = (kv, knode)
        bound: Dict[str, Any] = {}
        kinds: Dict[str, str] = {}
        warm_in = 0
        for p in params:
            if p.name not in given:
                if p.default is REQUIRED:
                    raise at(node, f"{spec.name}: thiếu đối số `{p.name}`")
                if p.is_series:
                    bound[p.name] = Const(p.default) if not isinstance(p.default, bool) else BoolConst(p.default)
                    kinds[p.name] = bound[p.name].kind
                else:
                    bound[p.name] = p.default
                continue
            val, vnode = given[p.name]
            if p.is_series:
                if not isinstance(val, Node):
                    raise at(vnode, f"`{p.name}` cần một chuỗi / hằng số")
                if p.kind == "num" and val.kind != "num":
                    raise at(vnode, f"{spec.name}: `{p.name}` cần chuỗi số, nhận mặt nạ bool (mặt nạ dùng với & | ~ hoặc self.op.where)")
                if p.kind == "bool" and val.kind != "bool":
                    raise at(vnode, f"{spec.name}: `{p.name}` cần mặt nạ bool (kết quả so sánh), nhận chuỗi số")
                bound[p.name] = val
                kinds[p.name] = val.kind
                warm_in = max(warm_in, val.warm)
            else:
                if not isinstance(val, Const):
                    raise at(vnode, f"{spec.name}: `{p.name}` phải là hằng số (không phụ thuộc dữ liệu)")
                v = val.value
                if p.kind == "matype":
                    if v != 0:
                        raise at(vnode, f"{spec.name}: chỉ hỗ trợ {p.name}=0 (SMA)")
                    bound[p.name] = 0
                elif p.kind == "int":
                    if v != int(v):
                        raise at(vnode, f"{spec.name}: `{p.name}` phải là số nguyên, nhận {v:g}")
                    if not p.lo <= v <= p.hi:
                        raise at(vnode, f"{spec.name}: `{p.name}` phải trong [{int(p.lo)}, {int(p.hi)}], nhận {v:g}")
                    bound[p.name] = int(v)
                else:
                    if not p.lo <= v <= p.hi:
                        raise at(vnode, f"{spec.name}: `{p.name}` phải trong [{p.lo:g}, {p.hi:g}], nhận {v:g}")
                    bound[p.name] = float(v)
        consts = {k: v for k, v in bound.items() if not isinstance(v, Node)}
        kind = spec.ret({**consts, **{f"{k}_kind": v for k, v in kinds.items()}}) if callable(spec.ret) else spec.ret
        warm = warm_in + int(spec.warm(consts))
        (self.features if is_feature else self.ops).add(spec.name)
        call = Call(spec, is_feature, bound, kind, warm, node.lineno, node.col_offset + 1)
        self._tick(node)
        if spec.nout > 1:
            return TupleVal([Pick(call, i) for i in range(spec.nout)], node.lineno, node.col_offset + 1)
        return call


def compile_program(code: str) -> Program:
    """Biên dịch mã nguồn -> Program. DslError (có dòng/cột) nếu sai. Không đăng ký vào kernels (xem pydsl.compile_code)."""
    if not isinstance(code, str):
        raise DslError("Mã chiến lược phải là chuỗi")
    try:
        return _Compiler(code).compile()
    except RecursionError:
        raise DslError("Biểu thức lồng quá sâu") from None


# ══════════════════════════════════════════════════════════════════════════
# P9.4 part 2 — nguyên văn từ core/strategy/pydsl/explain.py
#
# Giải thích cấu trúc chiến lược Python từ chương trình đã biên dịch (B2 — không dùng LLM).
#
# Dịch cây biểu thức AST sang tiếng Việt tự nhiên và trích xuất:
# - indicators[]: danh sách chỉ báo kỹ thuật với tham số thực tế, khung nến, warmup
# - rules[]: quy tắc vào/thoát lệnh theo thứ tự set_positions
# - execution[]: cơ chế thực thi của engine Nora (profiles.py)
# - warnings[]: cảnh báo cấu trúc (dạng sự kiện/trạng thái, thiếu chân thoát, warmup...)
# ══════════════════════════════════════════════════════════════════════════

DATA_VI = {
    "open": "giá mở cửa",
    "high": "giá cao nhất",
    "low": "giá thấp nhất",
    "close": "giá đóng cửa",
    "volume": "khối lượng",
}


def _clean_num(v: float) -> str:
    if isinstance(v, (int, float)):
        s = f"{float(v):.4f}".rstrip("0").rstrip(".")
        return s if s else "0"
    return str(v)


def _format_feat_call(call: Call) -> str:
    """Định dạng cuộc gọi chỉ báo dạng toán học: EMA(close, 20), RSI(close, 14)..."""
    spec = call.spec
    name = spec.name.upper()
    args: List[str] = []
    for p in spec.params:
        if p.name in call.bound:
            val = call.bound[p.name]
            if isinstance(val, Node):
                args.append(expr_to_vi(val))
            elif isinstance(val, (int, float)):
                args.append(_clean_num(val))
            elif val != 0 and str(val):
                args.append(str(val))
    return f"{name}({', '.join(args)})"


def expr_to_vi(node: Node, parent_prec: int = 0) -> str:
    """Dịch cây biểu thức Node sang tiếng Việt có nghĩa."""
    if isinstance(node, Const):
        return _clean_num(node.value)
    if isinstance(node, BoolConst):
        return "Đúng" if node.value else "Sai"
    if isinstance(node, Data):
        return DATA_VI.get(node.col_name, f"giá {node.col_name}")
    if isinstance(node, Neg):
        return f"-{expr_to_vi(node.a, 8)}"
    if isinstance(node, Bin):
        prec_map = {"+": 4, "-": 4, "*": 6, "/": 6}
        prec = prec_map.get(node.op, 5)
        op_sym = {"+": " + ", "-": " - ", "*": " × ", "/": " / "}.get(node.op, f" {node.op} ")
        sa = expr_to_vi(node.a, prec)
        sb = expr_to_vi(node.b, prec)
        res = f"{sa}{op_sym}{sb}"
        return f"({res})" if prec < parent_prec else res
    if isinstance(node, Cmp):
        cmp_vi = {
            ">": "lớn hơn",
            ">=": "lớn hơn hoặc bằng",
            "<": "nhỏ hơn",
            "<=": "nhỏ hơn hoặc bằng",
            "==": "bằng",
            "!=": "khác",
        }
        sa = expr_to_vi(node.a, 2)
        sb = expr_to_vi(node.b, 2)
        phrase = cmp_vi.get(node.op, node.op)
        return f"{sa} {phrase} {sb}"
    if isinstance(node, Logic):
        sa = expr_to_vi(node.a, 1)
        sb = expr_to_vi(node.b, 1)
        conj = "VÀ" if node.op == "&" else "HOẶC"
        return f"{sa} {conj} {sb}"
    if isinstance(node, Inv):
        return f"KHÔNG PHẢI ({expr_to_vi(node.a, 1)})"
    if isinstance(node, Pick):
        parent_call = _format_feat_call(node.call)
        fn_name = node.call.spec.name
        if fn_name == "bbands":
            sub_names = ["Dải trên", "Dải giữa", "Dải dưới"]
            sub = sub_names[node.idx] if node.idx < len(sub_names) else f"Đầu ra {node.idx}"
            return f"{sub} {parent_call}"
        if fn_name == "macd":
            sub_names = ["Đường MACD", "Đường Signal", "Histogram"]
            sub = sub_names[node.idx] if node.idx < len(sub_names) else f"Đầu ra {node.idx}"
            return f"{sub} {parent_call}"
        if fn_name == "stoch":
            sub_names = ["%K", "%D"]
            sub = sub_names[node.idx] if node.idx < len(sub_names) else f"Đầu ra {node.idx}"
            return f"{sub} {parent_call}"
        return f"Đầu ra {node.idx + 1} của {parent_call}"
    if isinstance(node, Call):
        if node.is_feature:
            return _format_feat_call(node)
        op_name = node.spec.name
        b = node.bound
        if op_name == "crossed_above":
            return f"{expr_to_vi(b['a'])} cắt lên {expr_to_vi(b['b'])}"
        if op_name == "crossed_below":
            return f"{expr_to_vi(b['a'])} cắt xuống {expr_to_vi(b['b'])}"
        if op_name == "crossed":
            return f"{expr_to_vi(b['a'])} cắt {expr_to_vi(b['b'])}"
        if op_name == "crossed_above_value":
            return f"{expr_to_vi(b['a'])} cắt lên mức {_clean_num(b['value'])}"
        if op_name == "crossed_below_value":
            return f"{expr_to_vi(b['a'])} cắt xuống mức {_clean_num(b['value'])}"
        if op_name == "hold_for":
            p = b.get("periods", 1)
            return f"duy trì ({expr_to_vi(b['cond'])}) trong {p} nến"
        if op_name == "rising":
            p = b.get("periods", 1)
            return f"{expr_to_vi(b['x'])} tăng liên tục {p} nến"
        if op_name == "falling":
            p = b.get("periods", 1)
            return f"{expr_to_vi(b['x'])} giảm liên tục {p} nến"
        if op_name == "previous":
            p = b.get("periods", 1)
            return f"{expr_to_vi(b['x'])} của {p} nến trước"
        if op_name == "shift":
            p = b.get("periods", 1)
            return f"{expr_to_vi(b['x'])} lùi {p} nến"
        if op_name == "diff":
            p = b.get("periods", 1)
            return f"chênh lệch {expr_to_vi(b['x'])} so với {p} nến trước"
        if op_name == "pct_change":
            p = b.get("periods", 1)
            return f"% thay đổi của {expr_to_vi(b['x'])} sau {p} nến"
        if op_name == "between":
            return f"{expr_to_vi(b['x'])} nằm trong khoảng [{expr_to_vi(b['lower'])}, {expr_to_vi(b['upper'])}]"
        if op_name == "where":
            return f"nếu ({expr_to_vi(b['cond'])}) thì {expr_to_vi(b['a'])}, ngược lại {expr_to_vi(b['b'])}"
        if op_name == "and_":
            return f"({expr_to_vi(b['a'])}) VÀ ({expr_to_vi(b['b'])})"
        if op_name == "or_":
            return f"({expr_to_vi(b['a'])}) HOẶC ({expr_to_vi(b['b'])})"
        if op_name == "not_":
            return f"KHÔNG PHẢI ({expr_to_vi(b['a'])})"
        # Các op khác
        parts = [f"{k}={expr_to_vi(v) if isinstance(v, Node) else _clean_num(v)}" for k, v in b.items()]
        return f"{op_name}({', '.join(parts)})"
    return str(node)


def _find_calls(node: Node, out: List[Call]) -> None:
    if isinstance(node, Call):
        out.append(node)
        for v in node.bound.values():
            if isinstance(v, Node):
                _find_calls(v, out)
    elif isinstance(node, Pick):
        _find_calls(node.call, out)
    elif isinstance(node, (Bin, Cmp, Logic)):
        _find_calls(node.a, out)
        _find_calls(node.b, out)
    elif isinstance(node, (Neg, Inv)):
        _find_calls(node.a, out)


def _has_event_trigger(node: Node) -> bool:
    calls: List[Call] = []
    _find_calls(node, calls)
    event_ops = {"crossed", "crossed_above", "crossed_below", "crossed_above_value", "crossed_below_value"}
    return any(c.spec.name in event_ops for c in calls if not c.is_feature)


def explain_program(program: Program, position: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Phân tích chương trình đã biên dịch và trả về bộ giải thích có cấu trúc."""

    # 1. Chỉ báo sử dụng
    all_calls: List[Call] = []
    for mask, _, _ in program.calls:
        _find_calls(mask, all_calls)

    feat_calls = [c for c in all_calls if c.is_feature]
    indicators: List[Dict[str, Any]] = []
    seen_feat_keys: Set[str] = set()

    for fc in feat_calls:
        signature = _format_feat_call(fc)
        if signature in seen_feat_keys:
            continue
        seen_feat_keys.add(signature)
        indicators.append({
            "name": fc.spec.name,
            "call": signature,
            "label_vi": fc.spec.label_vi or fc.spec.name.upper(),
            "meaning_vi": fc.spec.meaning_vi or fc.spec.doc or "",
            "formula": fc.spec.formula or "",
            "timeframe": program.timeframe,
            "warmup": int(fc.warm),
            "category": fc.spec.category or "trend",
        })

    # 2. Quy tắc vào / thoát lệnh
    rules: List[Dict[str, Any]] = []
    has_exit_rule = False

    for idx, (mask, level, line) in enumerate(program.calls, start=1):
        cond_str = expr_to_vi(mask)
        if level > 0:
            action_vi = f"Vào LONG khi {cond_str}"
            rule_type = "entry_long"
        elif level < 0:
            action_vi = f"Vào SHORT khi {cond_str}"
            rule_type = "entry_short"
        else:
            action_vi = f"Thoát vị thế (đưa về 0) khi {cond_str}"
            rule_type = "exit"
            has_exit_rule = True

        rules.append({
            "index": idx,
            "line": line,
            "level": float(level),
            "type": rule_type,
            "condition_vi": cond_str,
            "action_vi": action_vi,
            "is_event": _has_event_trigger(mask),
        })

    # 3. Cơ chế thực thi (engine Nora)
    execution: List[Dict[str, str]] = []
    pos_cfg = {**NORA_DEFAULTS, "cooldown": 60, **(program.position_overrides or {}), **(position or {})}
    risk_parts = []   # chỉ nhắc cơ chế thực sự bật (giá trị > 0) — đúng như build_plan sẽ chạy
    if float(pos_cfg.get("stop_loss_rate") or 0) > 0:
        risk_parts.append(f"Stop-Loss {_clean_num(pos_cfg['stop_loss_rate'])}×ATR tính từ giá trung bình")
    if float(pos_cfg.get("take_profit_rate") or 0) > 0:
        risk_parts.append(f"Take-Profit {_clean_num(pos_cfg['take_profit_rate'])}×ATR")
    if float(pos_cfg.get("trailing_stop") or 0) > 0:
        act = float(pos_cfg.get("trailing_activation_pct") or 0)
        risk_parts.append(f"trailing stop {_clean_num(pos_cfg['trailing_stop'])}×ATR" + (f" (bật khi lãi ≥ {_clean_num(act)}×ATR)" if act > 0 else ""))
    if int(pos_cfg.get("timeout") or 0) > 0:
        risk_parts.append(f"giữ tối đa {int(pos_cfg['timeout'])} phút")
    if int(pos_cfg.get("cooldown") or 0) > 0:
        risk_parts.append(f"nghỉ {int(pos_cfg['cooldown'])} phút sau khi thoát")
    risk_desc = ("Ngoài tín hiệu thoát: " + ", ".join(risk_parts) + ".") if risk_parts else "Chỉ thoát theo tín hiệu; không có Stop-Loss / Take-Profit."
    if pos_cfg.get("atr_frame"):
        risk_desc += f" ATR đo trên khung {pos_cfg['atr_frame']}."
    execution = [
        {"title": "Khớp lệnh", "desc": "Khớp ở giá mở cửa nến tiếp theo (Next Open) theo quy chuẩn của engine."},
        {"title": "Thị trường & Đòn bẩy", "desc": "Hợp đồng phái sinh vĩnh cửu (Perpetual), hỗ trợ đòn bẩy và cả hai chiều Long/Short."},
        {"title": "Phân bổ vốn", "desc": "Chia khối lượng theo ngân sách rủi ro (Risk-based sizing) từng lệnh."},
        {"title": "Quản trị rủi ro", "desc": risk_desc},
        {"title": "Chi phí giao dịch", "desc": "Tính phí sàn theo mô hình Maker/Taker thực tế kèm mô phỏng trượt giá bảo thủ."},
    ]

    # 4. Cảnh báo cấu trúc
    warnings: List[str] = list(program.warnings)

    # Kiểm tra tín hiệu sự kiện vs trạng thái
    for r in rules:
        if r["level"] != 0 and not r["is_event"]:
            warnings.append(
                f"Quy tắc {r['index']} (dòng {r['line']}): Tín hiệu dạng trạng thái (điều kiện so sánh liên tục); "
                "khi điều kiện duy trì đúng qua nhiều nến, lệnh chỉ được kích hoạt lại nếu vị thế trước đó đã đóng."
            )

    if not has_exit_rule and len(rules) > 0:
        warnings.append("Chiến lược không có quy tắc thoát lệnh tường minh (set_positions(0)); vị thế chỉ đóng khi đổi chiều hoặc kết thúc kỳ backtest.")

    if program.has_long and not program.has_short:
        warnings.append("Chiến lược chỉ kích hoạt vị thế LONG (mua/nắm giữ), không tham gia chiều SHORT khi thị trường giảm.")

    if any(abs(r["level"]) not in (0.0, 1.0) for r in rules):
        warnings.append("Độ lớn của mức position (khác 1) không đổi khối lượng lệnh: engine định cỡ theo rủi ro; mức chỉ phân biệt vào / thoát và chiều.")

    if program.warmup_bars >= 60:
        warnings.append(f"Số nến khởi động khá lớn ({program.warmup_bars} nến); chiến lược cần đủ dữ liệu lịch sử trước khi bắt đầu sinh tín hiệu.")

    return {
        "indicators": indicators,
        "rules": rules,
        "execution": execution,
        "warnings": list(dict.fromkeys(warnings)),
    }


# ══════════════════════════════════════════════════════════════════════════
# P9.4 part 2 — nguyên văn từ core/signals/evaluator.py
#
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
            return self._finite(fn.reduce(np.vstack(arrays), axis=0))
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
        return self._finite(res * float(multiply))

    def _field(self, item):
        lag = int(item.get("index", 0) or 0)
        value = np.asarray(self.get(item.get("frame"), item.get("column"), lag), dtype="float64").copy()
        value = self._finite(value)
        with np.errstate(all="ignore"):
            for key, sign in (("subtract", -1.0), ("add", 1.0)):
                if key in item:
                    value = value + sign * self.value(item[key])
            if "divide" in item:
                div = self.value(item["divide"])
                value = np.where(div == 0, 0.0, value / np.where(div == 0, 1.0, div))
                value = np.where(np.isnan(div), np.nan, value)
        return self._finite(value)

    @staticmethod
    def _finite(arr):
        arr = np.asarray(arr, dtype="float64")
        return np.where(np.isfinite(arr), arr, np.nan)


# ══════════════════════════════════════════════════════════════════════════
# P9.4 part 2 — nguyên văn từ core/signals/snapshot.py
#
# Ảnh chụp TÍN HIỆU thị trường tại nến 1m ĐÃ ĐÓNG mới nhất — cùng một đường tính với backtest (không có bản tính thứ hai).
#
# signal_snapshot(symbol, strategies, end_ts) dựng engine của tài sản y như PortfolioEngine (_make_trackers -> load_data -> _build_matrix ->
# VectorEvaluator), nên giá trị chỉ báo / điều kiện / tín hiệu vào-thoát ở phút t TRÙNG với thứ engine dùng ở phút t (test_signal_snapshot).
# Khung lớn chỉ dùng nến đã đóng (avail_time = open + độ dài khung); phút cuối là phút có giao dịch thật (bỏ nến điền).
#
# Dùng cho: trang Tổng quan (dữ liệu backtest), và sau này Live/Testnet — chỉ cần nạp nến mới nhất của sàn vào cùng bố cục dữ liệu rồi gọi lại hàm này.
# Kết quả mỗi chiến lược: entry/exit (tín hiệu ở nến đã đóng cuối), `entry_since` (từ phút nào tín hiệu vào giữ trạng thái hiện tại),
# và từng điều kiện (giá trị trái/phải, toán tử, đạt/không) để biết vì sao có / không có tín hiệu.
# ══════════════════════════════════════════════════════════════════════════

MINUTE = 60_000
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


def signal_snapshot(symbol: str, strategies: List[Dict[str, Any]], end_ts: int, lookback_minutes: int = DEFAULT_LOOKBACK_MIN,
                    venue: str = "cex") -> Dict[str, Any]:
    """Tín hiệu của `strategies` (dạng chiến lược của PortfolioEngine) trên `symbol` tại nến 1m đã đóng cuối cùng <= end_ts."""
    from backend.core.backtest import PortfolioEngine
    start = int(end_ts) - int(lookback_minutes) * MINUTE
    pe = PortfolioEngine([symbol], strategies, start, int(end_ts), trade_start_ts=start, venue=venue, use_cache=True)
    eng, pairs = pe._make_slots(symbol, pe.ledger)
    out: Dict[str, Any] = {"symbol": symbol, "bar_open_time": None, "as_of": None, "close": None, "regime": None, "strategies": []}
    if not pairs:
        return out
    from backend.core.regime import classifier as rg
    eng.extra_refs = rg.REFS                         # regime luôn hiển thị, cùng cột đặc trưng với backtest bật regime
    eng.load_data()
    if eng.df_base is None or eng.df_base.empty:
        return out
    df1, cols = eng._build_matrix()
    n = len(df1)
    real = np.flatnonzero(df1["is_filled"].to_numpy() == 0)
    t_all = df1["open_time"].to_numpy(dtype="int64")
    real = real[t_all[real] < int(end_ts)]          # chỉ nến đã ĐÓNG trước end_ts
    if real.size == 0:
        return out
    i = int(real[-1])

    def get(frame, column, lag):
        return cols.get(f"{frame}|{lag_key(column, lag)}", np.full(n, np.nan))

    vec = VectorEvaluator(n, get)
    t_real = t_all[real]
    out.update(bar_open_time=int(t_all[i]), as_of=int(t_all[i]) + MINUTE, close=_num(df1["close"].to_numpy()[i]))
    labels = rg.classify(lambda fr, c: cols.get(f"{fr}|{c}", np.full(n, np.nan)), t_all)
    raw = rg.raw_states(lambda fr, c: cols.get(f"{fr}|{c}", np.full(n, np.nan)), n)
    name = rg.NAMES[int(labels[i])]
    out["regime"] = {"state": name, "label": rg.LABEL_VI[name], "raw": rg.NAMES[int(raw[i])],
                     "since": _since(labels[real], t_real, len(real) - 1),
                     "features": {f"{fr} {c}": _num(cols.get(f"{fr}|{c}", np.full(n, np.nan))[i])
                                  for fr, refs in sorted(rg.REFS.items()) for c, _ in sorted(refs)}}
    for st, tr in pairs:
        match, stop = vec.tree(tr.match_tree), vec.tree(tr.stop_tree)
        entry_raw = bool(match[i])
        if st.get("regime"):                          # cùng mặt nạ với PortfolioEngine.load_data
            allowed, fuse = rg.masks_for(st, st["side"], labels)
            match = match & allowed
            if fuse is not None:
                stop = stop | fuse
        m_real = match[real]
        out["strategies"].append({
            "id": st["id"], "side": st["side"], "entry": bool(match[i]), "exit": bool(stop[i]), "entry_raw": entry_raw,
            "entry_since": _since(m_real, t_real, len(real) - 1),
            "entry_minutes_in_window": int(m_real.sum()),
            "entry_blocks": _explain(vec, tr.match_tree, i), "exit_blocks": _explain(vec, tr.stop_tree, i),
            "regime_allowed": (st.get("regime") or {}).get("allowed"),
            "regime_ok": bool(not st.get("regime") or labels[i] in [rg.CODE[x] for x in st["regime"].get("allowed") or rg.NAMES]),
        })
    return out


def book_strategies(ids: Optional[List[str]] = None, regime: bool = True) -> List[Dict[str, Any]]:
    """Mọi chiến lược lõi của sổ với bộ tham số tốt nhất (presets.json) — tham số khác vẫn là cùng chiến lược.
    regime=True: kèm bảng regime cho phép (entry = tín hiệu thô VÀ regime cho phép; entry_raw = tín hiệu thô)."""
    from backend.core.params.presets import load_presets
    from backend.core.strategy.book import CANDIDATES, materialize
    presets = load_presets()
    return [materialize(c, presets[c["id"]]["params"], regime=regime) for c in CANDIDATES if not ids or c["id"] in ids]


# ══════════════════════════════════════════════════════════════════════════
# P9.4 part 2 — nguyên văn từ core/signals/diagnostics.py
#
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


def check_signals(symbol: str, signals: Dict[str, Dict[str, Any]], start_ts: Optional[int] = None,
                  end_ts: Optional[int] = None, horizons_min: Iterable[int] = HORIZONS_MIN,
                  baseline_step: int = 7) -> Dict[str, Any]:
    """Kiểm tra nhiều tín hiệu trên một tài sản (nạp dữ liệu + tính kernel một lần)."""
    from backend.core.backtest import BacktestEngine
    from backend.core.params import VENUE_COSTS, build_params, venue_of_symbol
    from backend.db.local_pkl import read_manifest

    manifest = read_manifest(symbol) or {}
    venue = venue_of_symbol(symbol)
    start_ts = int(start_ts or manifest.get("start_ts"))
    end_ts = int(end_ts or manifest.get("end_ts"))

    engine = BacktestEngine(0, 0, symbol, start_ts, end_ts)
    names = list(signals)
    for name in names:  # flow LONG giả chỉ để engine biết cần tính kernel nào
        engine.add_strategy_flow(f"LONG_{name}", build_params(
            f"LONG_{name}", {"match": [{"condition": signals[name]["tree"]}], "stop": []}, "LONG", {}, venue))
    engine.load_data()
    df1, cols = engine._build_matrix()
    n = len(df1)
    vec = VectorEvaluator(n, lambda fr, c, lag: cols.get(f"{fr}|{lag_key(c, lag)}", np.full(n, np.nan)))

    real = df1["is_filled"].to_numpy() == 0
    in_range = df1["open_time"].to_numpy() >= start_ts
    times = df1["open_time"].to_numpy(dtype="int64")[real]
    opens = df1["open"].to_numpy(dtype="float64")[real]
    closes = df1["close"].to_numpy(dtype="float64")[real]
    pos_of_row = np.cumsum(real) - 1  # vị trí trong mảng phút-thật của mỗi dòng
    base_idx = np.arange(0, len(times) - 1, baseline_step)
    base_idx = base_idx[times[base_idx] >= start_ts]

    results: Dict[str, Any] = {}
    for name in names:
        sig = signals[name]
        sign = 1.0 if sig.get("side", "LONG") == "LONG" else -1.0
        fire = vec.tree(sig["tree"]) & real & in_range
        entry = pos_of_row[np.nonzero(fire)[0]] + 1           # vào ở phút thật kế tiếp
        entry = np.unique(entry[entry < len(times)])
        costs = VENUE_COSTS[(venue, "spot" if sign > 0 else ("perp" if venue == "cex" else "spot"))]
        cost_bps = 2 * (costs[0] + costs[2]) * 1e4  # taker + trượt, hai chiều
        by_h = {}
        for h in horizons_min:
            ev_idx = entry[_thin(times[entry], h * 60_000)] if len(entry) else entry
            ev = _forward_bps(times, opens, closes, ev_idx, h * 60_000, sign) if len(ev_idx) else np.array([])
            base = _forward_bps(times, opens, closes, base_idx, h * 60_000, sign)
            by_h[h] = _stats(ev, base, cost_bps)
        results[name] = {
            "side": sig.get("side", "LONG"),
            "family": sig.get("family"),
            "raw_signal_minutes": int(fire.sum()),
            "cost_bps_round_trip": round(cost_bps, 1),
            "horizons": by_h,
            **_verdict(by_h),
        }
    return {"symbol": symbol, "venue": venue, "start_ts": start_ts, "end_ts": end_ts, "signals": results}


# ══════════════════════════════════════════════════════════════════════════
# P9.4 part 2 — nguyên văn từ core/strategy/pydsl/__init__.py
#
# API biên dịch DSL (từ pydsl/__init__.py): compile_code -> compile_program + register_program; compile_report; explain_report.
# `explain_program(prog, position)` của __init__ là hàm bọc import cục bộ tới explain.explain_program (cùng chữ ký) -> bỏ, dùng chính explain_program ở trên.
# ══════════════════════════════════════════════════════════════════════════

def compile_code(code: str, register: bool = True) -> Program:
    """Biên dịch + (mặc định) đăng ký vào kernels để PortfolioEngine tính được cột py_<hash12>_*. Phải gọi trong CHÍNH tiến trình chạy engine."""
    prog = compile_program(code)
    if register:
        register_program(prog.code_hash, prog)
    return prog


def compile_report(code: str) -> Dict[str, Any]:
    """Dạng trả về của POST /api/studio/strategies/compile: {ok, program_hash, meta, warnings, error}."""
    try:
        prog = compile_code(code)
    except DslError as e:
        return {"ok": False, "program_hash": None, "meta": None, "warnings": [], "error": e.to_dict()}
    return {"ok": True, "program_hash": prog.code_hash, "meta": prog.meta(), "warnings": prog.warnings, "error": None}


def explain_report(code: str, position: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Dạng trả về của POST /api/studio/strategies/explain: {ok, indicators[], rules[], execution[], warnings[], error}."""
    try:
        prog = compile_code(code, register=False)
    except DslError as e:
        return {"ok": False, "indicators": [], "rules": [], "execution": [], "warnings": [], "error": e.to_dict()}
    return {"ok": True, "error": None, **explain_program(prog, position=position)}
