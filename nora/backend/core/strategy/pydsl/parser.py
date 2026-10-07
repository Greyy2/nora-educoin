"""Trình biên dịch DSL: `ast.parse` rồi thông dịch theo DANH SÁCH TRẮNG (docs/bmad/p7_python_strategies.md §3). KHÔNG exec/eval code người dùng.

Chấp nhận đúng một `class X(SimpleAlgorithm)` gồm thuộc tính lớp hằng và `def __algorithm__(self)`; trong đó chỉ có gán (kể cả unpack tuple),
`self.set_positions(mask, position=w)` và docstring. Không vòng lặp, không if, không import, không hàm lồng, không and/or/not của Python.
Mọi lỗi là DslError có dòng + cột. Kết quả là `Program` (IR đã kiểm loại, hằng số đã gấp).
"""
import ast
import hashlib
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.core.strategy.pydsl import features as feat_mod
from backend.core.strategy.pydsl import ops as ops_mod
from backend.core.strategy.pydsl.errors import DslError, at, suggest
from backend.core.strategy.pydsl.program import (DATA_COLUMNS, TF_MS, Bin, BoolConst, Call, Cmp, Const, Data, Inv, Logic, Neg, Node, Pick,
                                                 Program)
from backend.core.strategy.pydsl.spec import REQUIRED, Spec

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
    from backend.core.params.builder import POSITION_KEYS
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
            table, label = (feat_mod.FEATURES, "feat") if v.attr == "feat" else (ops_mod.OPS, "op")
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
            return self._bind_call(ops_mod.OPS[_METHODS[fn.attr]], False, node, [base] + [self._expr(a) for a in node.args],
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
