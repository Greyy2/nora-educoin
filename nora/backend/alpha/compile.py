"""Bộ chuyển đổi alpha -> IR (P9 alpha/): biên dịch DSL Python (compile_program/compile_code/explain), module chiến lược hệ thống (compile_strategy_module),
hàm dựng cây điều kiện, và nạp file data/alpha/strategies/*.py (cache theo mtime+size).

Chuyển từ core/signal.py + optimize/book/build.py (P9 alpha pass). Chỉ import core + alpha/contract; thư mục chiến lược tính từ vị trí mã (như NORA_DIR cũ).
"""
import ast
import hashlib
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from backend.alpha.contract import BASE_CLASS, MAX_CODE_CHARS, MAX_NODES, _position_attr_names, at, lifecycle_body, suggest
from backend.core.indicator import FEATURES, OPS, REQUIRED, Spec, register_program
from backend.core.params import DATA_COLUMNS, FRAME_MS, FRAMES as FRAME_TF, NORA_DEFAULTS
from backend.core.signal import (Bin, BoolConst, Call, Cmp, Const, Data, DslError, Inv, Logic, Neg, Node, Pick, Program, TupleVal, code_hash)

NORA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))   # = optimize/process/process.NORA_DIR (alpha không import optimize)


# ══════════════════════════════════════════════════════════════════════════
# Trình biên dịch DSL: `ast.parse` rồi thông dịch theo DANH SÁCH TRẮNG (docs/bmad/p7_python_strategies.md §3). KHÔNG exec/eval code người dùng.
#
# Chấp nhận đúng một `class X(SimpleAlgorithm)` gồm thuộc tính lớp hằng và `def __algorithm__(self)`; trong đó chỉ có gán (kể cả unpack tuple),
# `self.set_positions(mask, position=w)` và docstring. Không vòng lặp, không if, không import, không hàm lồng, không and/or/not của Python.
# Mọi lỗi là DslError có dòng + cột. Kết quả là `Program` (IR đã kiểm loại, hằng số đã gấp).
# ══════════════════════════════════════════════════════════════════════════

DATA_ATTRS = {f"pv_{c}": c for c in DATA_COLUMNS}
TIMEFRAME_ALIASES = {"1d": "24h", "d": "24h", "1day": "24h", "daily": "24h", "60m": "1h", "240m": "4h", "1440m": "24h"}
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



def _const_literal(node, msg: str):
    """Hằng số / chuỗi / bool / danh sách hằng (cho phép dấu +/- trước số) của một nút AST; ngược lại lỗi `msg` tại nút đó."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str, bool)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)) and isinstance(node.operand, ast.Constant) \
            and isinstance(node.operand.value, (int, float)) and not isinstance(node.operand.value, bool):
        return -node.operand.value if isinstance(node.op, ast.USub) else node.operand.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_const_literal(e, msg) for e in node.elts]
    raise at(node, msg)


class _Compiler:
    def __init__(self, code: str, tree: Optional[ast.Module] = None):
        self.code = code
        self.tree = tree        # AST đã dựng sẵn (bộ chuyển đổi alpha/adapters); None = ast.parse(code)
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
            tree = self.tree if self.tree is not None else ast.parse(self.code)
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
        for stmt in lifecycle_body(cls):
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                continue
            if isinstance(stmt, ast.Pass):
                continue
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                self._class_attr(stmt)
            elif isinstance(stmt, ast.FunctionDef):
                if stmt.name != "__algorithm__":
                    raise at(stmt, f"Chỉ hỗ trợ on_start/on_bar/on_stop hoặc __algorithm__(self), không có `{stmt.name}`" + suggest(stmt.name, ("on_start", "on_bar", "on_stop", "__algorithm__")))
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
        return _const_literal(node, "Thuộc tính lớp phải là hằng số / chuỗi / danh sách hằng (không có biểu thức hay lời gọi)")

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
            if tf not in FRAME_MS:
                raise at(stmt.value, f"timeframe {value!r} không hỗ trợ; có: {list(FRAME_MS)}")
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


def compile_program(code: str, tree: Optional[ast.Module] = None) -> Program:
    """Biên dịch mã nguồn -> Program. DslError (có dòng/cột) nếu sai. Không đăng ký vào kernels (xem signal.compile_code).
    `tree`: AST native đã dựng sẵn (bộ chuyển đổi alpha/adapters) thay cho ast.parse(code)."""
    if not isinstance(code, str):
        raise DslError("Mã chiến lược phải là chuỗi")
    try:
        return _Compiler(code, tree).compile()
    except RecursionError:
        raise DslError("Biểu thức lồng quá sâu") from None


# ══════════════════════════════════════════════════════════════════════════
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
# API biên dịch DSL (từ pydsl/__init__.py): compile_code -> compile_program + register_program; compile_report; explain_report.
# `explain_program(prog, position)` của __init__ là hàm bọc import cục bộ tới explain.explain_program (cùng chữ ký) -> bỏ, dùng chính explain_program ở trên.
# ══════════════════════════════════════════════════════════════════════════

def compile_code(code: str, register: bool = True) -> Program:
    """Biên dịch + (mặc định) đăng ký vào kernels để PortfolioEngine tính được cột py_<hash12>_*. Phải gọi trong CHÍNH tiến trình chạy engine."""
    try:
        prog = compile_program(code)
    except DslError as native_err:       # dạng ngoài hợp đồng native (hàm strategy(data) / JSON): bộ chuyển đổi -> cùng IR; không chuyển được -> lỗi gốc
        from backend.alpha.adapters import program_via_adapter
        prog = program_via_adapter(code, native_err)
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


# ══════════════════════════════════════════════════════════════════════════
# P9.9 — chiến lược hệ thống viết bằng DSL Python (file data/alpha/strategies/*.py)
#
# MỘT định dạng nguồn duy nhất cho mọi chiến lược: file Python kiểu SimpleAlgorithm. Cây AST ({"frame","column","index"}, {"param"}, "{tên}") chỉ là
# dạng ĐÃ BIÊN DỊCH nội bộ (sinh lại từ file, không sửa tay). Trình biên dịch này (`compile_strategy_module`) khác `compile_program` ở chỗ nó hạ
# thẳng sang cây khuôn của sổ chiến lược (nhiều khung nến, tham số `p(...)`, cổng DCA) thay vì cột `py_<hash>_*` một khung:
#
#   STRATEGY = {"id": "kema", "name": "KEMA", "kind": "...", "description": "...", "idea": "...", "order": 0}   # mô tả họ chiến lược
#   class KemaLong(SimpleAlgorithm):                  # mỗi chân LONG/SHORT một class
#       id = "kema_long"; family = "..."; description = "..."; position = {"atr_frame": "4h"}
#       def __algorithm__(self):
#           tf = self.frame(p('signal_tf', '4h', choices=('15m', '1h', '4h', '24h'), label="Khung tín hiệu", help="..."))
#           close, high, low = tf.pv_close, tf.pv_high, tf.pv_low
#           ema = self.feat.ema(close, timeperiod=p('ema_n', 30, lo=5, hi=200, step=1, unit="nến", label="...", help="...", grid=(20, 30, 50)))
#           ...
#           self.set_positions(self.op.crossed_above(close, kc_up), position=1)    # điều kiện VÀO (cây `tree`)
#           self.set_positions(self.op.crossed_below(close, kc_dn), position=0)    # điều kiện THOÁT (cây `stop`)
#           self.set_dca_gate(mask)                                                # (tuỳ chọn) cổng cho phép dồn tầng DCA (cây `dca_gate`)
#           p('stop_loss_rate', 3.0, grid=(2.0, 3.0, 4.0))                         # khoá vị thế: nhãn/khoảng lấy từ params.EXIT_RISK_SPEC
#
# `p(tên, mặc_định, lo=, hi=, step=, choices=, unit=, label=, help=, grid=, group=)`: khai báo MỘT tham số (không gian tối ưu "schema" = lo/hi/step,
# lưới nhỏ "grid" = `space`); dùng lại ở chỗ khác chỉ cần `p('tên')`. Tên thuộc POSITION_KEYS -> khoá vị thế (không tiền tố); còn lại -> "sig.<tên>".
# Chỉ báo `self.feat.*` ở chế độ này = cột KERNEL (indicator.REGISTRY) trên khung của dữ liệu truyền vào: ema sma rsi er atr adx bbands.
# ══════════════════════════════════════════════════════════════════════════

# tên feature -> (tiền tố cột kernel, danh sách đối số chuỗi, tham số số theo thứ tự tên cột)
_KERNEL_FEATURES = {
    "ema": ("ema", ("real",), ("timeperiod",)), "sma": ("sma", ("real",), ("timeperiod",)),
    "rsi": ("rsi", ("real",), ("timeperiod",)), "er": ("er", ("real",), ("timeperiod",)),
    "atr": ("atr", ("high", "low", "close"), ("timeperiod",)), "adx": ("adx", ("high", "low", "close"), ("timeperiod",)),
}
_SERIES_FOR_ARG = {"real": "close", "high": "high", "low": "low", "close": "close"}
_GROUP_ORDER = {"signal": 0, "dca": 1, "exit": 2, "risk": 3}
_STRATEGY_META_KEYS = ("id", "name", "kind", "doc", "description", "idea", "order")
_CLASS_ATTRS = ("id", "family", "description")
_NUMERIC = (int, float)


class _Prm:
    """Tham số p(...) đã khai báo: dùng trong biểu thức số -> node {"param"}, trong khung/tên cột -> "{tên}"."""
    __slots__ = ("name", "spec")

    def __init__(self, name: str, spec: Dict[str, Any]):
        self.name, self.spec = name, spec

    @property
    def kind(self) -> str:
        return self.spec["kind"]


class _Frame:
    __slots__ = ("tf",)

    def __init__(self, tf):
        self.tf = tf            # "4h" hoặc _Prm(choice)


class _Fld:
    __slots__ = ("frame", "column", "index", "mods")

    def __init__(self, frame, column: str, index: int = 0, mods: Optional[Tuple[Tuple[str, Any], ...]] = None):
        self.frame, self.column, self.index, self.mods = frame, column, index, mods or ()


class _Calc:
    __slots__ = ("a", "logic", "b")

    def __init__(self, a, logic: str, b):
        self.a, self.logic, self.b = a, logic, b


class _Cond:
    """Điều kiện: danh sách khối AND (hoặc OR giữa các khối) gồm bộ ba [trái, toán tử, phải] đã tuần tự hoá."""
    __slots__ = ("blocks",)

    def __init__(self, blocks: List[List[list]]):
        self.blocks = blocks


def _frame_text(fr) -> str:
    return "{%s}" % fr.name if isinstance(fr, _Prm) else fr


def _value(v, node=None):
    """Giá trị DSL -> nút cây AST (số, {"param"}, trường, calculate)."""
    if isinstance(v, bool):
        raise at(node, "Giá trị bool không dùng được trong so sánh số") if node is not None else DslError("giá trị bool không hợp lệ")
    if isinstance(v, _NUMERIC):
        return v
    if isinstance(v, _Prm):
        if v.kind == "choice":
            raise at(node, f"Tham số `{v.name}` là lựa chọn (khung/chuỗi), không dùng như số") if node is not None else DslError("tham số lựa chọn không phải số")
        return {"param": v.name, "default": v.spec["default"]}
    if isinstance(v, _Fld):
        out = {"frame": _frame_text(v.frame), "column": v.column, "index": v.index}
        for key, mod in v.mods:
            out[key] = _value(mod, node)
        return out
    if isinstance(v, _Calc):
        return {"type": "calculate", "number_1": _value(v.a, node), "logic": v.logic, "number_2": _value(v.b, node)}
    raise at(node, "Giá trị này không dùng được trong điều kiện") if node is not None else DslError("giá trị không hợp lệ")


def _lag(v, k: int = 1):
    """Giá trị của k nến TRƯỚC trên cùng khung (cộng k vào `index` của mọi trường; hằng / tham số giữ nguyên) — như lagged() (hàm dựng cây, cuối file)."""
    if isinstance(v, _Fld):
        return _Fld(v.frame, v.column, v.index + k, tuple((key, _lag(m, k)) for key, m in v.mods))
    if isinstance(v, _Calc):
        return _Calc(_lag(v.a, k), v.logic, _lag(v.b, k))
    return v


class _StrategyCompiler:
    def __init__(self, code: str, tree: Optional[ast.Module] = None):
        self.code = code
        self.tree = tree
        self.n_nodes = 0

    # ─── mô-đun ─────────────────────────────────────────────────────────────
    def compile(self) -> Dict[str, Any]:
        if len(self.code) > MAX_CODE_CHARS:
            raise DslError(f"Mã quá dài ({len(self.code)} ký tự > {MAX_CODE_CHARS})")
        try:
            tree = self.tree if self.tree is not None else ast.parse(self.code)
        except SyntaxError as e:
            raise DslError(f"Lỗi cú pháp Python: {e.msg}", e.lineno, (e.offset or 1)) from None
        meta: Optional[Dict[str, Any]] = None
        classes: List[ast.ClassDef] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                classes.append(node)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "STRATEGY":
                meta = self._meta(node)
            else:
                raise at(node, "Ở cấp ngoài chỉ được có docstring, `STRATEGY = {...}` và các class chiến lược")
        if meta is None:
            raise DslError("Thiếu `STRATEGY = {...}` (id, name, kind, description, idea)", 1, 1)
        if not classes:
            raise DslError(f"Cần ít nhất một class kế thừa {BASE_CLASS}", 1, 1)
        cands = [self._leg(c, meta["id"]) for c in classes]
        sides = [c["side"] for c in cands]
        if len(set(sides)) != len(sides):
            raise DslError(f"Mỗi chiến lược chỉ có tối đa một chân LONG và một chân SHORT, nhận {sides}", 1, 1)
        cands.sort(key=lambda c: 0 if c["side"] == "LONG" else 1)
        legs = {c["side"]: c["id"] for c in cands}
        strategy = {"id": meta["id"], "name": meta["name"], "kind": meta["kind"], **({"doc": meta["doc"]} if "doc" in meta else {}),
                    "legs": legs, "description": meta["description"], "idea": meta["idea"]}
        return {"strategy": strategy, "order": meta.get("order", 0), "candidates": cands, "code_hash": code_hash(tree)}

    def _meta(self, node: ast.Assign) -> Dict[str, Any]:
        if not isinstance(node.value, ast.Dict):
            raise at(node.value, "STRATEGY phải là một dict literal")
        out: Dict[str, Any] = {}
        for k, v in zip(node.value.keys, node.value.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                raise at(node.value, "Khoá của STRATEGY phải là chuỗi")
            if k.value not in _STRATEGY_META_KEYS:
                raise at(k, f"STRATEGY không có khoá `{k.value}`; có: {', '.join(_STRATEGY_META_KEYS)}")
            out[k.value] = self._literal(v)
        missing = [k for k in ("id", "name", "kind", "description", "idea") if k not in out]
        if missing:
            raise at(node, f"STRATEGY thiếu khoá {missing}")
        return out

    # ─── một chân (class) ───────────────────────────────────────────────────
    def _leg(self, cls: ast.ClassDef, strategy_id: str) -> Dict[str, Any]:
        if not (len(cls.bases) == 1 and isinstance(cls.bases[0], ast.Name) and cls.bases[0].id == BASE_CLASS) or cls.keywords or cls.decorator_list:
            raise at(cls, f"Class phải có dạng `class {cls.name}({BASE_CLASS}):`")
        attrs: Dict[str, Any] = {}
        position: Dict[str, Any] = {}
        algo = None
        for stmt in lifecycle_body(cls):
            if isinstance(stmt, ast.Pass) or (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)):
                continue
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                name = stmt.targets[0].id
                if name == "position":
                    position = self._literal_dict(stmt.value)
                    bad = sorted(set(position) - set(_position_attr_names()))
                    if bad:
                        raise at(stmt.value, f"position: khoá vị thế không hợp lệ {bad}")
                elif name in _CLASS_ATTRS or name == "side":
                    val = self._literal(stmt.value)
                    if not isinstance(val, str):
                        raise at(stmt.value, f"`{name}` phải là chuỗi")
                    if name == "side" and val not in ("LONG", "SHORT"):
                        raise at(stmt.value, "`side` phải là \"LONG\" hoặc \"SHORT\"")
                    attrs[name] = val
                else:
                    raise at(stmt, f"Thuộc tính lớp `{name}` không hỗ trợ; có: {', '.join(_CLASS_ATTRS)}, side, position" + suggest(name, _CLASS_ATTRS + ("side", "position")))
            elif isinstance(stmt, ast.FunctionDef):
                if stmt.name != "__algorithm__" or algo is not None:
                    raise at(stmt, "Chỉ hỗ trợ on_start/on_bar/on_stop hoặc một hàm __algorithm__(self)" + suggest(stmt.name, ("on_start", "on_bar", "on_stop", "__algorithm__")))
                if (len(stmt.args.args) != 1 or stmt.args.args[0].arg != "self" or stmt.args.vararg or stmt.args.kwarg or stmt.args.kwonlyargs
                        or stmt.args.defaults or stmt.decorator_list):
                    raise at(stmt, "Chữ ký phải đúng `def __algorithm__(self):`")
                algo = stmt
            else:
                raise at(stmt, f"Trong class chỉ được có {', '.join(_CLASS_ATTRS)}, position và __algorithm__")
        for need in _CLASS_ATTRS:
            if need not in attrs:
                raise at(cls, f"Class {cls.name} thiếu thuộc tính `{need}`")
        if algo is None:
            raise at(cls, "Thiếu `def on_bar(self):` (hoặc `def __algorithm__(self):`)")
        st = _LegState(self)
        for s in algo.body:
            st.stmt(s)
        return st.finish(cls, attrs, position, strategy_id)

    # ─── literal ────────────────────────────────────────────────────────────
    def _literal(self, node):
        return _const_literal(node, "Cần hằng số / chuỗi / danh sách hằng")

    def _literal_dict(self, node) -> Dict[str, Any]:
        if not isinstance(node, ast.Dict):
            raise at(node, "Cần dict literal")
        out = {}
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                raise at(node, "Khoá phải là chuỗi")
            out[k.value] = self._literal(v)
        return out


_P_KWARGS = ("lo", "hi", "step", "choices", "unit", "label", "help", "grid", "group")


class _LegState:
    """Trạng thái biên dịch một chân: biến cục bộ, tham số đã khai báo, các điều kiện vào/thoát/cổng DCA."""

    def __init__(self, comp: _StrategyCompiler):
        self.comp = comp
        self.env: Dict[str, Any] = {}
        self.params: Dict[str, Dict[str, Any]] = {}      # tên -> spec (theo thứ tự khai báo)
        self.used: set = set()                           # tham số được dùng trong cây
        self.entries: List[Tuple[_Cond, float]] = []
        self.dca_gate: Optional[_Cond] = None

    # ─── câu lệnh ───────────────────────────────────────────────────────────
    def stmt(self, st):
        if isinstance(st, ast.Pass):
            return
        if isinstance(st, ast.Expr):
            v = st.value
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                return
            if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "p":
                self.declare(v)
                return
            if isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and isinstance(v.func.value, ast.Name) and v.func.value.id == "self":
                if v.func.attr == "set_positions":
                    return self.set_positions(v)
                if v.func.attr == "set_dca_gate":
                    return self.set_dca_gate(v)
            raise at(st, "Câu lệnh biểu thức chỉ được là p(...), self.set_positions(...) hoặc self.set_dca_gate(...)")
        if isinstance(st, ast.Assign):
            if len(st.targets) != 1:
                raise at(st, "Chỉ gán một đích mỗi dòng")
            return self.assign(st.targets[0], st.value)
        raise at(st, f"Câu lệnh {type(st).__name__} chưa được hỗ trợ")

    def assign(self, target, value_node):
        val = self.expr(value_node, allow_tuple=True)
        if isinstance(target, ast.Name):
            if isinstance(val, tuple):
                raise at(value_node, "Vế phải có nhiều giá trị: gán `a, b, ... = ...`")
            if target.id in ("self", BASE_CLASS, "p"):
                raise at(target, "Tên này dành riêng")
            self.env[target.id] = val
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            names = []
            for e in target.elts:
                if not isinstance(e, ast.Name) or e.id in ("self", BASE_CLASS, "p"):
                    raise at(e, "Unpack chỉ nhận tên biến")
                names.append(e.id)
            items = val if isinstance(val, tuple) else None
            if items is None or len(items) != len(names):
                raise at(value_node, f"Vế phải không có đúng {len(names)} giá trị để unpack")
            for nm, it in zip(names, items):
                self.env[nm] = it
            return
        raise at(target, "Đích gán phải là tên biến (hoặc tuple tên)")

    def set_positions(self, call: ast.Call):
        if len(call.args) != 1 or len(call.keywords) != 1 or call.keywords[0].arg != "position":
            raise at(call, "Dạng duy nhất: self.set_positions(mask, position=w)")
        mask = self.expr(call.args[0])
        if not isinstance(mask, _Cond):
            raise at(call.args[0], "Mặt nạ phải là điều kiện (so sánh / self.op.crossed_above|below / & |)")
        lvl = self.comp._literal(call.keywords[0].value)
        if isinstance(lvl, bool) or not isinstance(lvl, _NUMERIC) or lvl not in (-1, 0, 1):
            raise at(call.keywords[0].value, "position phải là 1 (vào long), -1 (vào short) hoặc 0 (thoát)")
        self.entries.append((mask, float(lvl)))

    def set_dca_gate(self, call: ast.Call):
        if len(call.args) != 1 or call.keywords or self.dca_gate is not None:
            raise at(call, "Dạng duy nhất (một lần): self.set_dca_gate(mask)")
        mask = self.expr(call.args[0])
        if not isinstance(mask, _Cond):
            raise at(call.args[0], "Cổng DCA phải là điều kiện")
        self.dca_gate = mask

    # ─── p(...) ─────────────────────────────────────────────────────────────
    def declare(self, call: ast.Call) -> _Prm:
        if not call.args or not (isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)):
            raise at(call, "p(tên, mặc_định, ...): đối số đầu là tên (chuỗi)")
        name = call.args[0].value
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise at(call.args[0], f"Tên tham số {name!r} không hợp lệ")
        if len(call.args) > 2:
            raise at(call, "p(tên, mặc_định, lo=, hi=, step=, choices=, unit=, label=, help=, grid=, group=)")
        kw = {}
        for k in call.keywords:
            if k.arg not in _P_KWARGS:
                raise at(k.value, f"p() không có đối số `{k.arg}`; có: {', '.join(_P_KWARGS)}")
            kw[k.arg] = self.comp._literal(k.value)
        if len(call.args) == 1 and not kw:       # tham chiếu tới tham số đã khai báo
            if name not in self.params:
                raise at(call, f"Tham số `{name}` chưa được khai báo: p('{name}', mặc_định, ...)")
            return _Prm(name, self.params[name])
        if len(call.args) < 2:
            raise at(call, f"p('{name}', mặc_định, ...): thiếu giá trị mặc định")
        if name in self.params:
            raise at(call, f"Tham số `{name}` đã khai báo; dùng p('{name}') để tham chiếu")
        default = self.comp._literal(call.args[1])
        if isinstance(default, (list, bool)):
            raise at(call.args[1], "Mặc định phải là số hoặc chuỗi")
        spec = self._spec(call, name, default, kw)
        self.params[name] = spec
        return _Prm(name, spec)

    def _spec(self, call, name: str, default, kw: Dict[str, Any]) -> Dict[str, Any]:
        from backend.core.params import EXIT_RISK_SPEC, POSITION_KEYS, SIG_PREFIX
        is_pos = name in POSITION_KEYS
        base = EXIT_RISK_SPEC.get(name)
        if base is not None:
            kind0, group0, label0, _d, lo0, hi0, step0, unit0, help0 = base
            lo0, hi0, step0, choices0 = (None, None, None, list(lo0)) if kind0 == "choice" else (lo0, hi0, step0, None)
        else:
            group0 = "signal" if not is_pos else None
            label0 = unit0 = help0 = None
            lo0 = hi0 = step0 = choices0 = None
        group = kw.get("group", group0)
        if group not in _GROUP_ORDER:
            raise at(call, f"p('{name}'): thiếu `group` (một trong {list(_GROUP_ORDER)}) cho khoá vị thế ngoài bảng thoát/rủi ro chung")
        if (group == "signal") == is_pos:
            raise at(call, f"p('{name}'): nhóm 'signal' dành cho tham số tín hiệu (không trùng khoá vị thế {list(POSITION_KEYS)[:3]}…), khoá vị thế dùng nhóm dca/exit/risk")
        choices = kw.get("choices", choices0)
        lo, hi, step = kw.get("lo", lo0), kw.get("hi", hi0), kw.get("step", step0)
        label, unit, help_vi = kw.get("label", label0), kw.get("unit", unit0 if unit0 is not None else ""), kw.get("help", help0)
        if label is None or help_vi is None:
            raise at(call, f"p('{name}'): cần label= và help= (nhãn/trợ giúp tiếng Việt cho giao diện)")
        grid = kw.get("grid")
        if grid is not None and (not isinstance(grid, list) or not grid):
            raise at(call, f"p('{name}'): grid phải là danh sách giá trị không rỗng")
        if choices is not None:
            if not isinstance(choices, list) or default not in choices:
                raise at(call, f"p('{name}'): mặc định {default!r} phải thuộc choices {choices!r}")
            kind = "choice"
            if name not in ("atr_frame",) and set(choices) - set(FRAME_TF):
                raise at(call, f"p('{name}'): choices phải là khung nến trong {list(FRAME_TF)}")
        else:
            if isinstance(default, str):
                raise at(call, f"p('{name}'): mặc định chuỗi cần choices=")
            if lo is None or hi is None or step is None:
                raise at(call, f"p('{name}'): cần lo=, hi=, step= (khoảng tối ưu)")
            if not lo <= default <= hi:
                raise at(call, f"p('{name}'): mặc định {default} ngoài [{lo}, {hi}]")
            kind = "int" if all(isinstance(v, int) and not isinstance(v, bool) for v in (lo, hi, step, default)) else "float"
        if grid is not None:
            for g in grid:
                if choices is not None and g not in choices or choices is None and (isinstance(g, (str, bool)) or not lo <= g <= hi):
                    raise at(call, f"p('{name}'): giá trị lưới {g!r} ngoài khoảng/choices")
        key = name if is_pos else SIG_PREFIX + name
        return {"name": name, "key": key, "kind": kind, "group": group, "default": default, "lo": lo, "hi": hi, "step": step, "choices": choices,
                "unit": unit, "label": label, "help": help_vi, "grid": grid}

    # ─── biểu thức ──────────────────────────────────────────────────────────
    def expr(self, node, allow_tuple: bool = False):
        self.comp.n_nodes += 1
        if self.comp.n_nodes > MAX_NODES:
            raise at(node, "Biểu thức quá lớn")
        v = self._expr(node)
        if isinstance(v, tuple) and not allow_tuple:
            raise at(node, f"Hàm trả {len(v)} giá trị: gán `a, b, ... = ...` hoặc lấy chỉ số [i]")
        return v

    def _expr(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float, str)):
                raise at(node, "Hằng này không dùng được")
            return node.value
        if isinstance(node, ast.Name):
            if node.id in self.env:
                return self.env[node.id]
            raise at(node, f"Biến `{node.id}` chưa được gán." + suggest(node.id, self.env))
        if isinstance(node, ast.Attribute):
            base = self.expr(node.value)
            if isinstance(base, _Frame) and node.attr in DATA_ATTRS:
                return _Fld(base.tf, DATA_ATTRS[node.attr])
            raise at(node, "Chỉ hỗ trợ <khung>.pv_open|high|low|close|volume")
        if isinstance(node, ast.Call):
            return self.call(node)
        if isinstance(node, ast.BinOp):
            return self.binop(node)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = self.expr(node.operand)
            if isinstance(v, _NUMERIC) and not isinstance(v, bool):
                return -v if isinstance(node.op, ast.USub) else v
            raise at(node, "Dấu +/- chỉ dùng cho hằng số")
        if isinstance(node, ast.Compare):
            return self.compare(node)
        if isinstance(node, ast.Subscript):
            base = self.expr(node.value, allow_tuple=True)
            if isinstance(base, tuple) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int) and 0 <= node.slice.value < len(base):
                return base[node.slice.value]
            raise at(node, "Chỉ lấy chỉ số hằng của kết quả nhiều giá trị (vd. bbands(...)[2])")
        if isinstance(node, ast.BoolOp):
            raise at(node, "`and`/`or` không dùng được: dùng `&` / `|` (đặt ngoặc quanh từng so sánh)")
        raise at(node, f"Biểu thức {type(node).__name__} chưa được hỗ trợ")

    def numeric(self, v, node):
        if isinstance(v, (_Fld, _Calc)) or (isinstance(v, _NUMERIC) and not isinstance(v, bool)):
            return v
        if isinstance(v, _Prm):
            if v.kind == "choice":
                raise at(node, f"Tham số `{v.name}` là lựa chọn khung, không dùng như số")
            self.used.add(v.name)
            return v
        raise at(node, "Toán hạng phải là số, tham số số hoặc chỉ báo")

    def binop(self, node: ast.BinOp):
        if isinstance(node.op, (ast.BitAnd, ast.BitOr)):
            a, b = self.expr(node.left), self.expr(node.right)
            if not isinstance(a, _Cond) or not isinstance(b, _Cond):
                raise at(node, "`&` / `|` chỉ dùng cho điều kiện (đặt ngoặc quanh từng so sánh)")
            if isinstance(node.op, ast.BitOr):
                return _Cond(a.blocks + b.blocks)
            return _Cond([x + y for x in a.blocks for y in b.blocks])
        sym = _ARITH.get(type(node.op))
        if sym not in ("+", "-", "*", "/"):
            raise at(node, "Toán tử số chỉ có: + - * /")
        a, b = self.numeric(self.expr(node.left), node.left), self.numeric(self.expr(node.right), node.right)
        if isinstance(a, _NUMERIC) and isinstance(b, _NUMERIC):
            try:
                return {"+": a + b, "-": a - b, "*": a * b, "/": a / b}[sym]
            except ZeroDivisionError:
                raise at(node, "Chia cho 0") from None
        if isinstance(a, _Fld) and not a.mods and sym in ("+", "-", "/"):
            return _Fld(a.frame, a.column, a.index, ((("add", "subtract", "divide")[("+", "-", "/").index(sym)], b),))
        return _Calc(a, sym, b)

    def compare(self, node: ast.Compare):
        if len(node.ops) != 1:
            raise at(node, "Không dùng so sánh nối chuỗi: tách thành (a < b) & (b < c)")
        sym = _CMP.get(type(node.ops[0]))
        if sym is None:
            raise at(node, "Phép so sánh chưa được hỗ trợ (có: > >= < <= == !=)")
        a, b = self.numeric(self.expr(node.left), node.left), self.numeric(self.expr(node.comparators[0]), node.comparators[0])
        if isinstance(a, _NUMERIC) and isinstance(b, _NUMERIC):
            raise at(node, "So sánh hai hằng số vô nghĩa")
        return _Cond([[[_value(a, node.left), sym, _value(b, node.comparators[0])]]])

    # ─── lời gọi ────────────────────────────────────────────────────────────
    def call(self, node: ast.Call):
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == "p":
            return self.declare(node)
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "self" and fn.attr == "frame":
            if len(node.args) != 1 or node.keywords:
                raise at(node, "self.frame(khung): một đối số là khung nến hoặc p('khung', ..., choices=...)")
            tf = self.expr(node.args[0])
            if isinstance(tf, _Prm):
                if tf.kind != "choice":
                    raise at(node.args[0], f"Tham số `{tf.name}` phải là lựa chọn khung (choices=...)")
                self.used.add(tf.name)
            elif not (isinstance(tf, str) and tf in FRAME_TF):
                raise at(node.args[0], f"Khung phải thuộc {list(FRAME_TF)}")
            return _Frame(tf)
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Attribute) and isinstance(fn.value.value, ast.Name) and fn.value.value.id == "self":
            if fn.value.attr == "feat":
                return self.feature(node, fn.attr)
            if fn.value.attr == "op":
                return self.operator(node, fn.attr)
        raise at(node, "Chỉ gọi được p(...), self.frame(...), self.feat.<tên>(...), self.op.crossed_above|crossed_below(...)")

    def bind(self, node: ast.Call, name: str, positional: Sequence[str], kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Gán đối số vị trí/từ khoá -> {tên: giá trị}; thiếu/thừa -> DslError."""
        if len(node.args) > len(positional):
            raise at(node, f"{name} nhận tối đa {len(positional)} đối số vị trí ({', '.join(positional)})")
        given = {nm: self.expr(a) for nm, a in zip(positional, node.args)}
        for k in node.keywords:
            if k.arg not in kwargs and k.arg not in positional:
                raise at(k.value, f"{name} không có tham số `{k.arg}`; có: {', '.join(list(positional) + list(kwargs))}")
            if k.arg in given:
                raise at(k.value, f"Tham số `{k.arg}` bị truyền hai lần")
            given[k.arg] = self.expr(k.value)
        for nm in positional:
            if nm not in given:
                raise at(node, f"{name}: thiếu đối số `{nm}`")
        for nm, dflt in kwargs.items():
            given.setdefault(nm, dflt)
        return given

    def period_text(self, v, node, what: str) -> str:
        if isinstance(v, _Prm):
            if v.kind == "choice":
                raise at(node, f"`{what}` không thể là tham số lựa chọn")
            self.used.add(v.name)
            return "{%s}" % v.name
        if isinstance(v, _NUMERIC) and not isinstance(v, bool):
            from backend.core.params import _fmt_number
            return _fmt_number(v)
        raise at(node, f"`{what}` phải là số hoặc tham số số p(...)")

    def feature(self, node: ast.Call, name: str):
        if name == "bbands":
            g = self.bind(node, "bbands", ("real",), {"timeperiod": 20, "nbdevup": 2.0, "nbdevdn": 2.0, "matype": 0})
            if g["matype"] != 0:
                raise at(node, "bbands: chỉ hỗ trợ matype=0 (SMA)")
            up, dn = g["nbdevup"], g["nbdevdn"]
            if not ((isinstance(up, _Prm) and isinstance(dn, _Prm) and up.name == dn.name) or (isinstance(up, _NUMERIC) and up == dn)):
                raise at(node, "bbands: nbdevup và nbdevdn phải cùng một giá trị/tham số (cột kernel bbu_n_k / bbl_n_k đối xứng)")
            fld = self.series(g["real"], "real", node)
            n_txt, k_txt = self.period_text(g["timeperiod"], node, "timeperiod"), self.period_text(up, node, "nbdevup")
            return tuple(_Fld(fld.frame, f"{pre}_{n_txt}_{k_txt}") for pre in ("bbu", "bbm", "bbl"))
        spec = _KERNEL_FEATURES.get(name)
        if spec is None:
            raise at(node, f"self.feat.{name} chưa hỗ trợ trong file chiến lược hệ thống (cột kernel)." + suggest(name, list(_KERNEL_FEATURES) + ["bbands"])
                     + f" Có: {', '.join(list(_KERNEL_FEATURES) + ['bbands'])}.")
        prefix, series_args, num_args = spec
        g = self.bind(node, name, series_args, {nm: None for nm in num_args})
        flds = [self.series(g[a], a, node) for a in series_args]
        if any(_frame_text(f.frame) != _frame_text(flds[0].frame) for f in flds):
            raise at(node, f"{name}: các chuỗi đầu vào phải cùng một khung")
        if g.get("timeperiod") is None:
            raise at(node, f"{name}: thiếu timeperiod=")
        return _Fld(flds[0].frame, f"{prefix}_{self.period_text(g['timeperiod'], node, 'timeperiod')}")

    def series(self, v, arg: str, node) -> _Fld:
        want = _SERIES_FOR_ARG[arg]
        if not (isinstance(v, _Fld) and not v.mods and v.index == 0 and v.column == want):
            raise at(node, f"Đối số `{arg}` phải là cột giá gốc `{want}` của một khung (vd. khung.pv_{want})")
        return v

    def operator(self, node: ast.Call, name: str):
        if name not in ("crossed_above", "crossed_below"):
            raise at(node, f"self.op.{name} chưa hỗ trợ trong file chiến lược hệ thống; có: crossed_above, crossed_below")
        if len(node.args) != 2 or node.keywords:
            raise at(node, f"self.op.{name}(a, b)")
        a, b = self.numeric(self.expr(node.args[0]), node.args[0]), self.numeric(self.expr(node.args[1]), node.args[1])
        va, vb = _value(a, node.args[0]), _value(b, node.args[1])
        la, lb = _value(_lag(a), node), _value(_lag(b), node)
        # như cross_over / cross_under (hàm dựng cây, cuối file): sự kiện (đúng ở nến cắt), không phải trạng thái a > b
        if name == "crossed_above":
            return _Cond([[[va, ">", vb], [la, "<=", lb]]])
        return _Cond([[[va, "<", vb], [la, ">=", lb]]])

    # ─── kết quả ────────────────────────────────────────────────────────────
    def finish(self, cls: ast.ClassDef, attrs: Dict[str, str], position: Dict[str, Any], strategy_id: str) -> Dict[str, Any]:
        from backend.core.params import (EXIT_RISK_SPEC, exit_risk_entry, resolve_placeholders, schema_choice, schema_flt, schema_int,
                                         signal_defaults)
        long_ = [c for c, lv in self.entries if lv > 0]
        short = [c for c, lv in self.entries if lv < 0]
        exits = [c for c, lv in self.entries if lv == 0]
        if bool(long_) == bool(short):
            raise at(cls, "Mỗi chân phải có điều kiện vào ĐÚNG một chiều: self.set_positions(mask, position=1) cho LONG hoặc position=-1 cho SHORT")
        if "side" in attrs and attrs["side"] != ("LONG" if long_ else "SHORT"):
            raise at(cls, f"Class {cls.name}: side = {attrs['side']!r} không khớp self.set_positions (vào {'LONG' if long_ else 'SHORT'})")
        entry = [b for c in (long_ or short) for b in c.blocks]
        cand: Dict[str, Any] = {"id": attrs["id"], "strategy": strategy_id, "family": attrs["family"], "side": "LONG" if long_ else "SHORT",
                                "description": attrs["description"], "tree": entry}
        if exits:
            cand["stop"] = [b for c in exits for b in c.blocks]
        if self.dca_gate is not None:
            cand["dca_gate"] = self.dca_gate.blocks
        cand["position"] = dict(position)
        entries: Dict[str, Dict[str, Any]] = {}
        space: Dict[str, List[Any]] = {}
        for name, sp in self.params.items():
            if sp["group"] == "signal" and name not in self.used:
                raise at(cls, f"Tham số tín hiệu `{name}` đã khai báo nhưng không dùng trong điều kiện nào")
            if sp["kind"] == "choice":
                entry_ = schema_choice(sp["group"], sp["label"], sp["default"], sp["choices"], sp["help"])
            elif sp["kind"] == "int":
                entry_ = schema_int(sp["group"], sp["label"], sp["default"], sp["lo"], sp["hi"], sp["unit"], sp["help"], step=sp["step"])
            else:
                entry_ = schema_flt(sp["group"], sp["label"], float(sp["default"]), sp["lo"], sp["hi"], sp["step"], sp["unit"], sp["help"])
            entries[sp["key"]] = entry_
            if sp["grid"] is not None:
                space[sp["key"]] = list(sp["grid"])
        table = {key: entries.pop(key, None) or exit_risk_entry(key) for key in EXIT_RISK_SPEC}   # nhóm thoát/rủi ro luôn đủ khoá, theo thứ tự bảng chung
        entries.update(table)
        cand["space"] = space
        cand["params_schema"] = dict(sorted(entries.items(), key=lambda kv: _GROUP_ORDER[kv[1]["group"]]))
        try:      # kiểm tên cột/khung ở mặc định ngay lúc biên dịch (lỗi sớm, có tên chân)
            for key in ("tree", "stop", "dca_gate"):
                if key in cand:
                    resolve_placeholders(cand[key], {}, signal_defaults(cand))
        except ValueError as e:
            raise at(cls, f"Chân {attrs['id']}: {e}") from None
        return cand




def compile_strategy_module(code: str, tree: Optional[ast.Module] = None) -> Dict[str, Any]:
    """Biên dịch một file chiến lược hệ thống (Python DSL, xem khối chú thích ở trên) -> {"strategy": {...}, "order": int, "candidates": [...], "code_hash"}.
    candidates[i] cùng dạng với phần tử CANDIDATES của sổ (id, strategy, family, side, description, tree, [stop], [dca_gate], position, space, params_schema)."""
    if not isinstance(code, str):
        raise DslError("Mã chiến lược phải là chuỗi")
    try:
        return _StrategyCompiler(code, tree).compile()
    except RecursionError:
        raise DslError("Mã lồng quá sâu") from None


# ══════════════════════════════════════════════════════════════════════════
# Hàm dựng cây (`p` tên là `tree_p` vì trùng p() của DSL)
#
# Hàm dựng cây điều kiện AST (f, cond, lagged, cross_over, cross_under, calc, tree_p) — dùng bởi test và định nghĩa chiến lược cũ.
#
# Chiến lược hệ thống nay viết bằng DSL Python (data/alpha/strategies/*.py, P9.9); SIGNALS / KERNEL_STRATEGIES (mẫu nghiên cứu) chuyển sang
# test/legacy_library.py, OPTIMIZATION_SPACES (không ai dùng) đã xoá. Ghi chú nghiên cứu gốc:
#
# Tham khảo lối đánh của 28 bot trade top OKX/Binance (okx-report.html, 28–29/09/2026):
#     Bắt hồi + DCA   12/28 bot, thắng 81%, 10x, giữ ~14h — bước DCA 0,25% / 0,74% / 1,72%, 2–4 tầng
#     Săn cú lớn       7/28, thắng 53%, lãi dồn vào vài lệnh
#     Theo đà          5/28, thắng 86%, vào cùng chiều biến động 24h
#     Lướt nhanh       4/28, thắng 97%, giữ ~6h, ít nhồi
# Khác biệt có chủ đích so với bot OKX: MỌI chiến lược ở đây có stop-loss cứng và/hoặc timeout.
# Báo cáo cho thấy 21/28 bot không cắt lỗ và 17/26 lead OKX đang ôm lỗ treo tổng −1,29M USDT;
# số tầng DCA tương quan +0,62 với cú lỗ lớn nhất. Không cắt lỗ = win rate đẹp, đuôi lỗ không giới hạn.
#
# Mỗi SIGNAL là một cây điều kiện AST trên kernel (core/indicator.py), được kiểm tra riêng
# bằng diagnostics (core/signal.py) trước khi ghép với tham số quản lý vị thế thành STRATEGY.
# ══════════════════════════════════════════════════════════════════════════

def f(frame: str, column: str, index: int = 0) -> Dict[str, Any]:
    return {"frame": frame, "column": column, "index": index}


def cond(*triplets) -> List[List[List[Any]]]:
    """Một khối AND gồm các (trái, toán tử, phải)."""
    return [[list(t) for t in triplets]]


def lagged(item: Any, k: int = 1) -> Any:
    """Biểu thức giá trị của k nến TRƯỚC trên cùng khung (cộng k vào `index` của mọi trường; hằng / tham số giữ nguyên)."""
    if not isinstance(item, dict):
        return item
    if "frame" in item and "column" in item:
        out = {**item, "index": int(item.get("index", 0) or 0) + k}
        for key in ("add", "subtract", "divide"):
            if key in out:
                out[key] = lagged(out[key], k)
        return out
    if item.get("type") == "calculate":
        return {**item, "number_1": lagged(item.get("number_1"), k), "number_2": lagged(item.get("number_2"), k)}
    if item.get("type") in ("min", "max"):
        return {**item, "numbers": [lagged(x, k) for x in item.get("numbers", [])]}
    return item


def cross_over(a: Any, b: Any) -> tuple:
    """a CẮT LÊN b ở nến vừa đóng của khung (như ta.crossover của TradingView / KEMA của sova): a > b và a[1] <= b[1].
    Là SỰ KIỆN (chỉ đúng ở nến cắt), khác trạng thái a > b — tránh vào lại liên tục suốt cả đoạn xu hướng."""
    return (a, ">", b), (lagged(a), "<=", lagged(b))


def cross_under(a: Any, b: Any) -> tuple:
    """a CẮT XUỐNG b: a < b và a[1] >= b[1] (ta.crossunder)."""
    return (a, "<", b), (lagged(a), ">=", lagged(b))


def calc(a: Any, logic: str, b: Any) -> Dict[str, Any]:
    """Nút tính toán a (+ - *) b."""
    return {"type": "calculate", "number_1": a, "logic": logic, "number_2": b}


def tree_p(name: str, default: float) -> dict:
    """Node tham số tín hiệu {"param", "default"} (tối ưu được, khoá "sig.<tên>")."""
    return {"param": name, "default": default}



# ══════════════════════════════════════════════════════════════════════════
# Nạp chiến lược hệ thống từ file Python DSL (P9.9): data/alpha/strategies/*.py.
#
# MỘT định dạng nguồn duy nhất cho mọi chiến lược: file Python kiểu SimpleAlgorithm (cú pháp ở core/signal.py, khối "P9.9"). Cây AST / `params_schema` / `space`
# chỉ là dạng ĐÃ BIÊN DỊCH, sinh lại từ file mỗi lần nạp (nhớ theo mtime+size), không sửa tay. Core không đọc file: lớp này đọc rồi `core/signal.compile_strategy_module`
# biên dịch thuần; CANDIDATES / STRATEGIES / BY_ID (khối "Sổ chiến lược" bên dưới) chỉ là các góc nhìn trên kết quả nạp.
# ══════════════════════════════════════════════════════════════════════════

_DATA_HOME = os.path.join(NORA_DIR, "data")      # cố định theo mã (KHÔNG theo NORA_LOCAL_DATA_ROOT của test): định nghĩa chiến lược là một phần của mã
_cache: Dict[str, Any] = {"sig": None, "value": None}


def strategies_dir() -> str:
    """NORA_STRATEGIES_DIR > data/alpha/strategies."""
    env = os.environ.get("NORA_STRATEGIES_DIR")
    if env:
        return env
    return os.path.join(_DATA_HOME, "alpha", "strategies")


def strategy_files(directory: Optional[str] = None) -> List[str]:
    d = directory or strategies_dir()
    if not os.path.isdir(d):
        raise FileNotFoundError(f"Không thấy thư mục chiến lược hệ thống: {d}")
    return [os.path.join(d, n) for n in sorted(os.listdir(d)) if n.endswith(".py") and not n.startswith("_")]


def load_system_strategies(directory: Optional[str] = None) -> Dict[str, Any]:
    """{"candidates": [...], "strategies": [...], "sources": {candidate_id: {"file", "sha256", "code_hash"}}}.
    Thứ tự: theo `order` của STRATEGY rồi tên file; trong họ: chân LONG trước SHORT (đúng thứ tự CANDIDATES/STRATEGIES cũ)."""
    files = strategy_files(directory)
    if not files:
        raise FileNotFoundError(f"Thư mục chiến lược hệ thống rỗng: {directory or strategies_dir()}")
    sig = tuple((p, os.stat(p).st_mtime_ns, os.stat(p).st_size) for p in files)
    if _cache["sig"] == sig:
        return _cache["value"]
    parsed = []
    for path in files:
        with open(path, "rb") as fh:
            raw = fh.read()
        try:
            out = compile_strategy_module(raw.decode("utf-8"))
        except DslError as e:
            raise DslError(f"{os.path.basename(path)}: {e.message}", e.line, e.col) from None
        parsed.append((out["order"], os.path.basename(path), out, hashlib.sha256(raw).hexdigest()))
    parsed.sort(key=lambda t: (t[0], t[1]))
    candidates: List[Dict[str, Any]] = []
    strategies: List[Dict[str, Any]] = []
    sources: Dict[str, Dict[str, str]] = {}
    for _, name, out, sha in parsed:
        if any(s["id"] == out["strategy"]["id"] for s in strategies):
            raise DslError(f"{name}: trùng id chiến lược {out['strategy']['id']!r}")
        strategies.append(out["strategy"])
        for c in out["candidates"]:
            if c["id"] in sources:
                raise DslError(f"{name}: trùng id chân {c['id']!r}")
            candidates.append(c)
            sources[c["id"]] = {"file": name, "sha256": sha, "code_hash": out["code_hash"]}
    value = {"candidates": candidates, "strategies": strategies, "sources": sources}
    _cache.update(sig=sig, value=value)
    return value
