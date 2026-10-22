"""Bộ chuyển đổi alpha -> IR (P9 alpha/): biên dịch DSL Python (compile_program/compile_code/explain), module chiến lược hệ thống (compile_strategy_module),
hàm dựng cây điều kiện, và nạp file data/alpha/strategies/*.py (cache theo mtime+size).

Chuyển từ signal/nodes.py + strategies.py (P9 alpha pass). Chỉ import core + alpha/contract; thư mục chiến lược tính từ vị trí mã (như NORA_DIR cũ).
"""
import ast
import copy
import difflib
import hashlib
import io
import json
import os
import re
import time
import tokenize
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from .contract import (BASE_CLASS, BASE_CLASSES, KIND_ALPHA, KIND_MODULE, MAX_CODE_CHARS, MAX_NODES, METHOD_OPS, _fmt_range, _is_doc, _position_attr_names, at, classify, has_lifecycle,
                       lifecycle_body, native_tree, split_suggest, suggest)
from backend.analys.indicator import FEATURES, OPS, REQUIRED, Spec, register_program
from backend.analys.signal import GLOBAL_TA_FUNCS, OHLCV_COLUMNS, RISK_PARAM_MAP
from backend.analys.param import BASE_POSITION, DATA_COLUMNS, FRAME_MS, FRAMES as FRAME_TF, NORA_DEFAULTS, VENUE_COSTS, resolve_position_auto
from backend.analys.signal import (Bin, BoolConst, Call, Cmp, Const, Data, DslError, Inv, Logic, Neg, Node, Pick, Program, TupleVal, code_hash)

from backend.models.models import DATA_DIR  # noqa: E402  (DATA_DIR cố định theo mã, KHÔNG theo NORA_LOCAL_DATA_ROOT của test)


# ══════════════════════════════════════════════════════════════════════════
# Trình biên dịch DSL: `ast.parse` rồi thông dịch theo DANH SÁCH TRẮNG (docs/bmad/p7_python_strategies.md §3). KHÔNG exec/eval code người dùng.
#
# Chấp nhận đúng một `class X(SimpleAlgorithm)` gồm thuộc tính lớp hằng và `def __algorithm__(self)`; trong đó chỉ có gán (kể cả unpack tuple),
# `self.set_positions(mask, position=w)` và docstring. Không vòng lặp, không if, không import, không hàm lồng, không and/or/not của Python.
# Mọi lỗi là DslError có dòng + cột. Kết quả là `Program` (IR đã kiểm loại, hằng số đã gấp).
# ══════════════════════════════════════════════════════════════════════════

DATA_ATTRS = {f"pv_{c}": c for c in DATA_COLUMNS}
DATA_ATTRS.update({c: c for c in DATA_COLUMNS})
TIMEFRAME_ALIASES = {"1d": "24h", "d": "24h", "1day": "24h", "daily": "24h", "60m": "1h", "240m": "4h", "1440m": "24h"}
_CMP = {ast.Gt: ">", ast.GtE: ">=", ast.Lt: "<", ast.LtE: "<=", ast.Eq: "==", ast.NotEq: "!="}
_ARITH = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Pow: "**"}
_METHODS = {"fillna": "fillna", "shift": "shift", "abs": "abs"}
_PANDAS_HINT = {      # phương thức kiểu pandas hay gặp -> chỉ báo/operator tương đương của DSL (gợi ý, không tự đổi)
    "rolling": ("self.feat.rolling_mean", "self.feat.rolling_max", "self.feat.rolling_min", "self.feat.rolling_std", "self.feat.rolling_sum"),
    "mean": ("self.feat.sma", "self.feat.rolling_mean"), "std": ("self.feat.rolling_std", "self.feat.stddev"),
    "max": ("self.feat.rolling_max",), "min": ("self.feat.rolling_min",), "sum": ("self.feat.rolling_sum",),
    "ewm": ("self.feat.ema",), "pct_change": ("self.op.pct_change", "self.feat.returns"), "diff": ("self.op.diff",),
    "ffill": ("self.op.ffill",), "clip": ("self.op.clip",), "isna": ("self.op.isna",), "notna": ("self.op.notna",), "where": ("self.op.where",),
}
_LIB_NAMES = ("np", "pd", "numpy", "pandas", "math", "talib", "ta")
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
        self.tree = tree        # AST đã dựng sẵn (bộ chuyển đổi trong alpha/compile); None = ast.parse(code)
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
        tree = native_tree(tree)
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
            raise DslError(f"Cần đúng một class kế thừa {' hoặc '.join(BASE_CLASSES)}, tìm thấy {len(classes)}", 1, 1)
        cls = classes[0]
        base_name = cls.bases[0].id if (len(cls.bases) == 1 and isinstance(cls.bases[0], ast.Name)) else None
        if not (base_name in BASE_CLASSES) or cls.keywords or cls.decorator_list:
            raise at(cls, f"Class phải có dạng `class {cls.name}({BASE_CLASS}):` (hoặc kế thừa: {', '.join(BASE_CLASSES)})")
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
        profile_name = self.position_overrides.get("risk_profile") or "legacy"
        if profile_name != "legacy":
            from backend.analys.position import validate_strategy_risk
            issues = validate_strategy_risk(self.position_overrides, profile_name)
            if issues:
                raise at(cls, f"Vi phạm quy tắc Risk Profile '{profile_name}': {issues[0].message_vi} (Gợi ý: {issues[0].suggestion})")
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
        elif name in RISK_PARAM_MAP:
            mapped_name = RISK_PARAM_MAP[name]
            self.position_overrides[mapped_name] = value
            if (name.endswith("_pct") or "pct" in name) and "exit_unit" not in self.position_overrides:
                self.position_overrides["exit_unit"] = "pct"
        else:
            self.consts[name] = value

    # ─── câu lệnh trong __algorithm__ ───────────────────────────────────────
    def _stmt(self, st):
        if isinstance(st, ast.Expr):
            if isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
                return
            if isinstance(st.value, ast.Call) and isinstance(st.value.func, ast.Attribute) and self._is_self(st.value.func.value):
                attr = st.value.func.attr
                if attr in ("set_positions", "set_position"):
                    return self._set_positions(st.value)
                if attr == "buy":
                    return self._order_action(st.value, 1.0)
                if attr == "sell":
                    return self._order_action(st.value, -1.0)
                if attr in ("close", "close_position"):
                    return self._order_action(st.value, 0.0)
            raise at(st, "Câu lệnh biểu thức đứng riêng không có tác dụng; chỉ self.set_position(...), self.buy(...), self.sell(...), self.close(...) được gọi như một lệnh")
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
        if node.id in ("self", "SimpleAlgorithm", "NoraStrategy", "Strategy", "AlphaStrategy"):
            raise at(node, f"Tên `{node.id}` dành riêng cho hệ thống")

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

    def _order_action(self, call: ast.Call, target_pos: float):
        func_name = getattr(call.func, "attr", "action")
        mask_node = None
        if call.args:
            mask_node = call.args[0]
        for kw in call.keywords:
            if kw.arg in ("mask", "condition", "when", "signal"):
                mask_node = kw.value
                break
        if mask_node is None:
            raise at(call, f"Thiếu điều kiện kích hoạt: self.{func_name}(condition)")
        mask = self._expr(mask_node)
        if mask.kind != "bool":
            raise at(mask_node, f"Điều kiện của self.{func_name} phải là biểu thức logic bool (ví dụ crossover(fast, slow))")
        self.calls.append((mask, target_pos, call.lineno))

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
            if node.id in OHLCV_COLUMNS:
                self.columns.add(node.id)
                return Data(node.id, line, col)
            if node.id in ("abs", "min", "max", "round", "len", "sum", "float", "int"):
                raise at(node, f"Hàm Python `{node.id}` không dùng được: dùng hàm ta.* hoặc phương thức .abs()/.shift()/.fillna()")
            if node.id in ("np", "pd", "numpy", "pandas", "math"):
                raise at(node, f"`{node.id}` không có sẵn trong DSL: dùng hàm ta.* hoặc chỉ báo trực tiếp")
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
        # ta.close / ta.high...
        if isinstance(node.value, ast.Name) and node.value.id == "ta" and node.attr in OHLCV_COLUMNS:
            self.columns.add(node.attr)
            return Data(node.attr, node.lineno, node.col_offset + 1)
        # self.data.pv_close | self.data.close | self.<thuộc tính lớp>
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
        raise at(node, "Truy cập thuộc tính này chưa được hỗ trợ (chỉ self.data.pv_*, self.<hằng>, self.feat.*, self.op.*, ta.*)")

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
        # 1. Gọi trực tiếp hàm toàn cầu (crossover, ema, rsi, atr...)
        if isinstance(fn, ast.Name) and fn.id in GLOBAL_TA_FUNCS:
            kind, real_name = GLOBAL_TA_FUNCS[fn.id]
            table, label = (FEATURES, "feat") if kind == "feat" else (OPS, "op")
            spec = table.get(real_name)
            if spec is not None:
                return self._bind_call(spec, kind == "feat", node, [self._expr(a) for a in node.args], list(node.args),
                                       [(k.arg, k.value, self._expr(k.value)) for k in node.keywords])

        # 2. Gọi qua namespace ta.* (ta.crossover, ta.ema, ta.rsi...)
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "ta":
            if fn.attr in GLOBAL_TA_FUNCS:
                kind, real_name = GLOBAL_TA_FUNCS[fn.attr]
                table, label = (FEATURES, "feat") if kind == "feat" else (OPS, "op")
                spec = table.get(real_name)
                if spec is not None:
                    return self._bind_call(spec, kind == "feat", node, [self._expr(a) for a in node.args], list(node.args),
                                           [(k.arg, k.value, self._expr(k.value)) for k in node.keywords])
            raise at(fn, f"ta.{fn.attr} chưa được hỗ trợ." + suggest(fn.attr, GLOBAL_TA_FUNCS))

        if not isinstance(fn, ast.Attribute):
            what = fn.id if isinstance(fn, ast.Name) else "hàm"
            if what in ("abs", "min", "max", "round", "float", "int", "len", "sum"):
                raise at(node, f"Hàm Python `{what}` không dùng được: dùng self.op.* (vd. self.op.abs(x)) hoặc phương thức .abs()/.shift()/.fillna()")
            raise at(node, f"Không gọi được `{what}(...)`: dùng chỉ báo/toán tử có sẵn (vd. ema, crossover) hoặc self.feat.<tên>, self.op.<tên>")
        v = fn.value
        if isinstance(v, ast.Attribute) and self._is_self(v.value) and v.attr in ("feat", "op"):
            table, label = (FEATURES, "feat") if v.attr == "feat" else (OPS, "op")
            spec = table.get(fn.attr)
            if spec is None:
                raise at(fn, f"self.{label}.{fn.attr} chưa được hỗ trợ." + suggest(fn.attr, table)
                         + (" (xem danh sách tại tài liệu P7 §3)" if label == "feat" else ""))
            return self._bind_call(spec, label == "feat", node, [self._expr(a) for a in node.args], list(node.args),
                                   [(k.arg, k.value, self._expr(k.value)) for k in node.keywords])
        if isinstance(v, ast.Name) and v.id in _LIB_NAMES:
            hint = _PANDAS_HINT.get(fn.attr) or tuple("self.feat." + n for n in difflib.get_close_matches(fn.attr.lower(), list(FEATURES), n=3, cutoff=0.6))
            raise at(v, f"`{v.id}` không có sẵn trong DSL: dùng self.feat.* / self.op.* (không gọi {v.id}.{fn.attr}(...))."
                     + (f" Gần đúng: {', '.join(hint)}." if hint else ""))
        if self._is_self(v) and fn.attr == "set_positions":
            raise at(node, "self.set_positions(...) là một câu lệnh, không dùng trong biểu thức")
        if self._is_self(v):
            raise at(node, f"self.{fn.attr}(...) không hỗ trợ")
        if fn.attr in _METHODS:     # series.fillna(v) / .shift(k) / .abs()
            base = self._expr(v)
            return self._bind_call(OPS[_METHODS[fn.attr]], False, node, [base] + [self._expr(a) for a in node.args],
                                   [v] + list(node.args), [(k.arg, k.value, self._expr(k.value)) for k in node.keywords])
        hint = _PANDAS_HINT.get(fn.attr)
        raise at(fn, f"Phương thức .{fn.attr}() chưa được hỗ trợ (có: {', '.join('.' + m + '()' for m in _METHODS)})"
                 + (f" Gần đúng: {', '.join(hint)}." if hint else suggest(fn.attr, _METHODS)))

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
    `tree`: AST native đã dựng sẵn (bộ chuyển đổi trong alpha/compile) thay cho ast.parse(code)."""
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
    if not hasattr(program, "calls") or getattr(program, "is_native", False):
        return {
            "indicators": getattr(program, "native_indicators", []),
            "rules": getattr(program, "native_rules", [
                {"index": 1, "line": 1, "level": 1.0, "type": "nautilus_native",
                 "condition_vi": f"Thực thi trực tiếp logic Strategy NautilusTrader ({getattr(program, 'name', 'Strategy')})",
                 "action_vi": "Vào lệnh & quản lý vị thế tự động qua Nautilus Engine",
                 "has_trigger": True}
            ]),
            "execution": getattr(program, "native_execution", [
                {"label_vi": "Hệ thống khớp lệnh", "desc_vi": "NautilusTrader 1.231.0 (OKX Netting Margin)"}
            ]),
            "warnings": list(getattr(program, "warnings", [])),
        }

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
    pos_cfg = resolve_position_auto({**BASE_POSITION, **NORA_DEFAULTS, **(program.position_overrides or {}), **(position or {})},
                                    program.timeframe)   # đúng như build_plan sẽ chạy (atr_frame / cooldown "auto" -> theo khung tín hiệu)
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
        risk_desc += f" ATR đo trên khung {pos_cfg['atr_frame']}, chu kỳ {int(pos_cfg.get('atr_period') or 0)}."
    taker, maker, slip = VENUE_COSTS[("cex", "perp" if pos_cfg.get("market") == "perp" else "spot")]
    taker = float(pos_cfg["fee_rate"]) if pos_cfg.get("fee_rate") is not None else taker
    maker = float(pos_cfg["maker_fee_rate"]) if pos_cfg.get("maker_fee_rate") is not None else maker
    slip = float(pos_cfg["slippage_rate"]) if pos_cfg.get("slippage_rate") is not None else slip
    sides = "Long" + (" và Short" if program.has_short else "") if program.has_long or program.has_short else "—"
    if pos_cfg.get("sizing") == "risk":
        size_desc = (f"Mỗi lệnh chịu rủi ro {_clean_num(pos_cfg.get('risk_per_trade_pct'))}% vốn tới mức cắt lỗ (định cỡ theo rủi ro), "
                     f"danh nghĩa tối đa {_clean_num(pos_cfg.get('max_notional_pct'))}% vốn.")
    else:
        size_desc = f"Mỗi lệnh dùng {_clean_num(pos_cfg.get('order_size_pct'))}% vốn."
    execution = [
        {"title": "Khớp lệnh", "desc": f"Lệnh vào gửi khi nến tín hiệu {program.timeframe} đóng, khớp ở giá đóng của nến đó; lệnh dừng khớp theo '{pos_cfg.get('stop_fill')}'."},
        {"title": "Thị trường & Đòn bẩy", "desc": f"{'Hợp đồng phái sinh vĩnh cửu (Perpetual)' if pos_cfg.get('market') == 'perp' else 'Thị trường spot'}, đòn bẩy trần {_clean_num(pos_cfg.get('leverage'))}x; chương trình này chỉ dùng chiều {sides}."},
        {"title": "Phân bổ vốn", "desc": size_desc},
        {"title": "Quản trị rủi ro", "desc": risk_desc},
        {"title": "Chi phí giao dịch", "desc": f"Phí taker {_clean_num(taker * 100)}%, maker {_clean_num(maker * 100)}%, trượt giá {_clean_num(slip * 100)}% mỗi chiều."},
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
# Native Nautilus Trader Support (P15 Native)
# ══════════════════════════════════════════════════════════════════════════

class NautilusNativeProgram:
    """Wrapper tương thích Program cho Native Nautilus Strategy."""

    def __init__(self, code: str, strategy_cls: Any, name: str, tree: Optional[ast.AST] = None, timeframe: str = "1h",
                 symbols: Optional[List[str]] = None, description: str = "", warnings: Optional[List[str]] = None):
        self.code = code
        self.tree = tree if tree is not None else ast.parse(code)
        self.code_hash = code_hash(self.tree)
        self.strategy_cls = strategy_cls
        self.name = name
        self.timeframe = timeframe
        self.symbols = symbols or ["BTC-USDT-SWAP"]
        self.description = description
        self.warnings = list(warnings or [])
        self.is_native = True
        self.calls: List[Tuple[Node, float, int]] = []
        self.open_times: List[int] = []
        self.open_ranges: List[Tuple[int, int]] = []
        self.close_ranges: List[Tuple[int, int]] = []
        self.position_overrides: Dict[str, Any] = {}
        self.features: List[str] = []
        self.ops: List[str] = []
        self.columns: List[str] = []
        self.levels = [1, -1]
        self.has_long = True
        self.has_short = True
        self.warmup_bars = 0
        self.legs = ["LONG", "SHORT"]
        self.native_indicators: List[Dict[str, Any]] = []
        self.native_rules = [
            {"index": 1, "line": 1, "level": 1.0, "type": "nautilus_native",
             "condition_vi": f"Chiến lược định lượng thuần NautilusTrader ({name})",
             "action_vi": "Vào lệnh & quản lý vị thế tự động qua Nautilus Engine", "has_trigger": True}
        ]
        self.native_execution = [
            {"label_vi": "Hệ thống khớp lệnh", "desc_vi": "NautilusTrader 1.231.0 (OKX Netting Margin)"}
        ]

    def meta(self) -> Dict[str, Any]:
        return {
            "timeframe": self.timeframe, "features": self.features, "ops": self.ops, "columns": self.columns,
            "legs": self.legs, "position_levels": self.levels, "warmup_bars": self.warmup_bars, "is_native": True,
            "name": self.name,
        }


def is_nautilus_native(code: str) -> bool:
    """Kiểm tra mã nguồn có phải là chiến lược Native Nautilus Trader (kế thừa Strategy) hay không."""
    if not isinstance(code, str) or not code.strip():
        return False
    try:
        tree = ast.parse(code)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id in ("Strategy", "NautilusStrategy"):
                        return True
                    if isinstance(base, ast.Attribute) and base.attr == "Strategy":
                        return True
    except Exception:
        pass
    return False


def compile_nautilus_strategy(code: str) -> NautilusNativeProgram:
    """Biên dịch và tải class Strategy của Nautilus Trader từ chuỗi code Python."""
    from .route import verify_native_sandbox
    verify_native_sandbox(code)
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise DslError(f"Lỗi cú pháp Python trong chiến lược Nautilus: {e.msg}", e.lineno, e.offset or 1) from None

    strat_cls_node = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if (isinstance(base, ast.Name) and base.id in ("Strategy", "NautilusStrategy")) or \
                   (isinstance(base, ast.Attribute) and base.attr == "Strategy"):
                    strat_cls_node = node
                    break
            if strat_cls_node:
                break

    if not strat_cls_node:
        raise DslError("Không tìm thấy class kế thừa Strategy của NautilusTrader trong mã nguồn", 1, 1)

    cls_name = strat_cls_node.name
    timeframe = "1h"
    symbols = ["BTC-USDT-SWAP"]
    desc = ast.get_docstring(strat_cls_node) or ""

    for item in strat_cls_node.body:
        if isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name):
                    if target.id == "timeframe" and isinstance(item.value, ast.Constant):
                        timeframe = str(item.value.value)
                    elif target.id == "symbols" and isinstance(item.value, ast.List):
                        symbols = [str(elt.value) for elt in item.value.elts if isinstance(elt, ast.Constant)]

    # Compile and execute code in isolated namespace
    ns: Dict[str, Any] = {"__name__": f"nautilus_user_{cls_name.lower()}"}
    try:
        exec(compile(tree, f"<nautilus_{cls_name}>", "exec"), ns)
    except Exception as e:
        raise DslError(f"Lỗi khi nạp module chiến lược Nautilus: {e}") from None

    strat_cls = ns.get(cls_name)
    if not strat_cls:
        raise DslError(f"Không thể khởi tạo class {cls_name}", 1, 1)

    return NautilusNativeProgram(
        code=code,
        strategy_cls=strat_cls,
        name=cls_name,
        tree=tree,
        timeframe=timeframe,
        symbols=symbols,
        description=desc,
    )


# ══════════════════════════════════════════════════════════════════════════
# API biên dịch DSL (từ pydsl/__init__.py): compile_code -> compile_program + register_program; compile_report; explain_report.
# `explain_program(prog, position)` của __init__ là hàm bọc import cục bộ tới explain.explain_program (cùng chữ ký) -> bỏ, dùng chính explain_program ở trên.
# ══════════════════════════════════════════════════════════════════════════

def compile_code(code: str, register: bool = True) -> Any:
    """Biên dịch + (mặc định) đăng ký vào kernels. Tự động nhận diện Native Nautilus và DSL."""
    if is_nautilus_native(code):
        return compile_nautilus_strategy(code)
    try:
        prog = compile_program(code)
    except DslError as native_err:       # dạng ngoài hợp đồng native (hàm strategy(data) / JSON): bộ chuyển đổi -> cùng IR; không chuyển được -> lỗi gốc
        prog = program_via_adapter(code, native_err)
    if register:
        register_program(prog.code_hash, prog)
    return prog


def compile_report(code: str) -> Dict[str, Any]:
    """Dạng trả về của POST /api/studio/strategies/compile: {ok, program_hash, meta, warnings, error, route}."""
    from .route import classify
    route_info = classify(code)
    try:
        prog = compile_code(code)
    except DslError as e:
        return {"ok": False, "program_hash": None, "meta": None, "warnings": [], "error": e.to_dict(), "route": route_info}
    return {"ok": True, "program_hash": prog.code_hash, "meta": prog.meta(), "warnings": prog.warnings, "error": None, "route": route_info}


def explain_report(code: str, position: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Dạng trả về của POST /api/studio/strategies/explain: {ok, indicators[], rules[], execution[], warnings[], error}."""
    try:
        prog = compile_code(code, register=False)
    except DslError as e:
        return {"ok": False, "indicators": [], "rules": [], "execution": [], "warnings": [], "error": e.to_dict()}
    return {"ok": True, "error": None, **explain_program(prog, position=position)}


# ══════════════════════════════════════════════════════════════════════════
# annotate_report — giải thích TỪNG DÒNG mã bằng tiếng Việt (trang /education; không AI). Nguồn duy nhất: AST + IR đã biên dịch (expr_to_vi)
# + catalog của alpha/contract (doc_vi/read_vi/khoảng giá trị). Không có bảng câu chữ riêng: mọi mô tả chỉ ghép từ các nguồn trên.
# ══════════════════════════════════════════════════════════════════════════

class _TracedCompiler(_Compiler):
    """_Compiler ghi lại, sau mỗi câu lệnh, bản chụp biến cục bộ và các lệnh set_positions vừa thêm (để chú thích dòng khớp IR)."""

    def __init__(self, code: str, tree: Optional[ast.Module] = None):
        super().__init__(code, tree)
        self.trace: Dict[int, Tuple[Dict[str, Any], List[Tuple[Node, float, int]]]] = {}

    def _stmt(self, st):
        n0 = len(self.calls)
        super()._stmt(st)
        self.trace[id(st)] = (dict(self.env), list(self.calls[n0:]))


def _src(node) -> str:
    return ast.unparse(node)


def _num(node) -> Optional[float]:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _num(node.operand)
        return None if v is None else (-v if isinstance(node.op, ast.USub) else v)
    return None


def _call_kind(call: ast.Call) -> Tuple[str, str]:
    """('feat'|'op'|'method'|'p'|'frame'|'', tên) của một lời gọi."""
    f = call.func
    if isinstance(f, ast.Attribute):
        if isinstance(f.value, ast.Attribute) and isinstance(f.value.value, ast.Name) and f.value.value.id == "self" and f.value.attr in ("feat", "op"):
            return f.value.attr, f.attr
        if isinstance(f.value, ast.Name) and f.value.id == "self" and f.attr == "frame":
            return "frame", "frame"
        if f.attr in METHOD_OPS:
            return "method", f.attr
    if isinstance(f, ast.Name) and f.id == "p":
        return "p", "p"
    return "", ""


def _refs(node, local: Set[str]) -> List[str]:
    out: List[str] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id in local and n.id not in out:
            out.append(n.id)
    return out


def _arg_text(row: dict, call: ast.Call) -> str:
    """'timeperiod = 20 (hợp lệ [1, 5000], mặc định 30)' cho các đối số hằng số của lời gọi, theo thứ tự chữ ký catalog."""
    parts: List[str] = []
    args = row["args"]
    bound = list(zip([a for a in args], call.args)) + [(next((a for a in args if a["name"] == kw.arg), None), kw.value) for kw in call.keywords]
    for a, v in bound:
        val = _num(v)
        if a is None or val is None or a["type"] not in ("int", "float"):
            continue
        rng = _fmt_range(a)
        parts.append(f"{a['name']} = {val:g}" + (f" (hợp lệ {rng}, mặc định {a['default']:g})" if rng and a["default"] is not None else (f" (hợp lệ {rng})" if rng else "")))
    return "; ".join(parts)


def _catalog_docs(value, idx: Dict[str, Any]) -> List[str]:
    """Mô tả catalog (doc_vi + read_vi + tham số) của mọi self.feat.* / self.op.* / .shift… trong biểu thức, không lặp."""
    out: List[str] = []
    seen: Set[Tuple[str, str]] = set()
    for n in ast.walk(value):
        if not isinstance(n, ast.Call):
            continue
        k, name = _call_kind(n)
        row = idx.get({"feat": "feat", "op": "op", "method": "method"}.get(k, ""), {}).get(name) if k in ("feat", "op", "method") else None
        if row is None or (k, name) in seen:
            continue
        seen.add((k, name))
        txt = row["doc_vi"].rstrip(".") + "."
        if k != "method":
            at_ = _arg_text(row, n)
            if at_:
                txt += f" Tham số: {at_}."
            if row.get("read_vi"):
                txt += f" Cách đọc: {row['read_vi']}"
        out.append(txt)
    return out


def _vi(ir_node, ast_node) -> str:
    return expr_to_vi(ir_node) if ir_node is not None else _plain(ast_node)


def _bool_node(n) -> bool:
    return isinstance(n, (Cmp, Logic, Inv, BoolConst)) or (isinstance(n, Call) and not n.is_feature and n.kind == "bool")


def _p_text(name: str, call: ast.Call) -> str:
    """Mô tả khai báo tham số p('tên', mặc_định, lo=, hi=, label=, help=…) từ chính các đối số literal."""
    kw = {k.arg: k.value for k in call.keywords}
    default = call.args[1] if len(call.args) > 1 else kw.get("default")
    lit = lambda k: kw[k].value if k in kw and isinstance(kw[k], ast.Constant) else None   # noqa: E731
    head = f"Tham số `{name}`" + (f" ({lit('label')})" if lit("label") else "") + (f", mặc định {_src(default)}" if default is not None else "")
    if "lo" in kw and "hi" in kw:
        head += f", khoảng tối ưu [{_src(kw['lo'])}, {_src(kw['hi'])}]" + (f" {lit('unit')}" if lit("unit") else "")
    elif "choices" in kw:
        head += f", lựa chọn {_src(kw['choices'])}"
    return head + "." + (f" {lit('help')}" if lit("help") else "")


class _Plain(ast.NodeTransformer):
    """Bỏ tiền tố self./self.feat./self.op. và thay p('tên', …) bằng `tên` để câu mô tả (loại module) gọn, đọc được."""

    def visit_Call(self, node):
        k, _ = _call_kind(node)
        if k == "p" and node.args and isinstance(node.args[0], ast.Constant):
            return ast.copy_location(ast.Name(id=str(node.args[0].value), ctx=ast.Load()), node)
        return self.generic_visit(node)

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name) and node.value.value.id == "self" and node.value.attr in ("feat", "op"):
            return ast.copy_location(ast.Name(id=node.attr, ctx=ast.Load()), node)
        return self.generic_visit(node)


def _plain(node) -> str:
    import copy as _copy
    return ast.unparse(_Plain().visit(_copy.deepcopy(node)))


ANNOTATION_MARK = "# ▸ "      # tiền tố cố định của MỌI dòng chú thích tự sinh (để gỡ / sinh lại bất biến)
_ANNOTATION_WIDTH = 76


def strip_annotations(code: str) -> str:
    """Gỡ mọi dòng chú thích tự sinh (`# ▸ …`); không đụng chú thích của tác giả."""
    return "\n".join(ln for ln in code.split("\n") if not ln.lstrip().startswith(ANNOTATION_MARK.rstrip()))


_SHORT_MAX = 70      # tối đa ký tự cho nội dung một dòng chú thích `# ▸` (chú thích dài nằm ở hover / trợ lý, không nằm trong code)
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_CALL_RE = re.compile(r"\b([A-Z][A-Z0-9_]*)\(([^()]*)\)")


def _cap(text: str) -> str:
    text = " ".join(text.replace("`", "").split())
    return text if len(text) <= _SHORT_MAX else text[: _SHORT_MAX - 1].rstrip(" ,;(+-*/") + "…"


def _short_expr(text: str) -> str:
    """Rút gọn câu mô tả biểu thức: `EMA(giá đóng cửa, 20)` -> `EMA 20`."""
    for _ in range(3):
        text = _CALL_RE.sub(lambda m: m.group(1) + next((f" {a}" for a in (x.strip() for x in m.group(2).split(",")) if _NUM_RE.fullmatch(a)), ""), text)
    return text


def _short_feat(what: str, label: str) -> str:
    """`EMA(giá đóng cửa, 20)` + nhãn catalog -> `EMA 20 phiên của giá đóng cửa (đường trung bình động hàm mũ)`."""
    m = re.fullmatch(r"([A-Z][A-Z0-9_]*)\((.*)\)", what)
    if not m:
        return _cap(_short_expr(what))
    args = [a.strip() for a in m.group(2).split(", ")]
    nums = [a for a in args if _NUM_RE.fullmatch(a)]
    series = [a for a in args if not _NUM_RE.fullmatch(a)]
    head = m.group(1) + (f" {nums[0]} phiên" if nums else "")
    if len(series) == 1 and "(" not in series[0]:
        head += f" của {series[0]}"
    full = f"{head} ({label[:1].lower() + label[1:]})" if label else head
    return _cap(full if len(full) <= _SHORT_MAX else head)


def _comment_block(shorts: Dict[int, Tuple[str, str]], code: str) -> str:
    """Chèn MỘT dòng chú thích ngắn `# ▸ …` (<= ~70 ký tự) NGAY TRÊN dòng được giải thích (cùng thụt lề). Khối lặp (tham số, vị thế / rủi ro) chỉ chú thích một lần.
    Chỉ thêm dòng chú thích: IR không đổi. Giải thích đầy đủ (công thức, khoảng hợp lệ, cách đọc) nằm ở `lines[].text_vi` (hover), không nằm trong code."""
    src = code.split("\n")
    inline: Set[int] = set()      # dòng có chú thích cuối dòng của tác giả
    try:
        for tok in tokenize.generate_tokens(io.StringIO(code).readline):
            if tok.type == tokenize.COMMENT and src[tok.start[0] - 1][: tok.start[1]].strip():
                inline.add(tok.start[0])
    except (tokenize.TokenError, IndentationError):
        pass
    seen: Set[str] = set()
    out: List[str] = []
    prev = ""                     # dòng không trống ngay trước
    for i, text in enumerate(src, 1):
        sh = shorts.get(i)
        if sh and text.strip() and not (sh[1] and sh[1] in seen):
            if sh[1]:
                seen.add(sh[1])        # khối đã có chú thích tiêu đề của tác giả cũng coi như đã chú thích
            if i not in inline and not prev.startswith("#"):      # đã có chú thích của tác giả (ngay trên / cuối dòng): không lặp lại
                out.append(f"{text[: len(text) - len(text.lstrip())]}{ANNOTATION_MARK}{sh[0]}")
        out.append(text)
        if text.strip():
            prev = text.strip()
    return "\n".join(out)


def annotate_report(code: str, as_comments: bool = False) -> Dict[str, Any]:
    """POST /api/studio/strategies/annotate: {lines:[{line,end_line,kind,text_vi,refs}], verdict, style, kind, normalized_code, diagnostics}.
    Với verdict ADAPT, `lines` đánh số theo `normalized_code` (dạng class tương đương), vì mã gốc không phải class.
    as_comments=True: gỡ chú thích `# ▸` cũ rồi trả thêm `annotated_code` (cùng mã, thêm dòng `# ▸` NGẮN (<= ~70 ký tự, tiếng Việt thường) trên dòng đáng chú ý; None nếu ADAPT/lỗi cú pháp)
    — `lines` khi đó đánh số theo mã đã gỡ chú thích cũ."""
    if as_comments:
        code = strip_annotations(code)
    out = _annotate_lines(code)
    shorts = out.pop("_short", {})
    if as_comments:
        out["annotated_code"] = None if out.get("normalized_code") or not out["lines"] else _comment_block(shorts, code)
    return out


def _annotate_lines(code: str) -> Dict[str, Any]:
    from .contract import _index, catalog
    res = analyze(code)
    src = res["normalized_code"] if res.get("normalized_code") else code
    out = {"verdict": res["verdict"], "style": res["style"], "kind": res["kind"], "normalized_code": res.get("normalized_code"),
           "diagnostics": res["diagnostics"], "lines": []}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    idx, cat = _index(), catalog()
    pos_rows = {r["name"]: r for r in cat["position_keys"]}
    tc: Optional[_TracedCompiler] = None
    if res["kind"] == KIND_ALPHA and res["verdict"] != "REJECT":
        try:
            tc = _TracedCompiler(src, tree)
            tc.compile()
        except DslError:
            tc = None
    attrs = idx["alpha" if res["kind"] == KIND_ALPHA else "module"]
    shorts: Dict[int, Tuple[str, str]] = {}      # dòng -> (chú thích ngắn `# ▸`, khoá "một lần")
    lines: List[Dict[str, Any]] = []
    local: Set[str] = set()

    def add(st, kind: str, text: str, refs: Optional[List[str]] = None, header_only: bool = False, short: str = "", once: str = ""):
        end = st.lineno if header_only else (getattr(st, "end_lineno", None) or st.lineno)
        if short:
            shorts[st.lineno] = (_cap(short), once)
        lines.append({"line": st.lineno, "end_line": end, "kind": kind, "text_vi": text, "refs": refs or []})

    def one_value(name: str, value, ir_node) -> Tuple[str, str, List[str], str, str]:
        """(kind, mô tả, tham chiếu, chú thích ngắn, khoá một-lần) cho `name = value`."""
        refs = _refs(value, local)
        if isinstance(value, ast.Attribute) and value.attr.startswith("pv_") and value.attr in idx["data"]:
            row = idx["data"][value.attr]
            return "data", f"`{name}` = {row['doc_vi'].lower()} của từng nến (cột {row['column']}).", refs, "", ""
        if isinstance(value, ast.Call):
            k, fn = _call_kind(value)
            if k == "p":
                return "param", _p_text(name, value), refs, "Tham số: đổi số này rồi chạy lại", "params"
            if k == "frame":
                return "data", f"`{name}` chọn khung nến ({_plain(value.args[0]) if value.args else ''}) để lấy dữ liệu và tính chỉ báo; các chuỗi dưới đây lấy từ khung này.", refs, "", ""
        num = _num(value)
        if num is not None:
            return "param", f"Hằng số `{name}` = {num:g}: giá trị cố định dùng làm hệ số hoặc ngưỡng ở các dòng sau.", refs, "Hằng số: đổi số này rồi chạy lại", "consts"
        docs = _catalog_docs(value, idx)
        what = _vi(ir_node, value)
        k0 = _call_kind(value)[0] if isinstance(value, ast.Call) else ""
        short = ""
        if k0 == "feat":
            kind, head = "feature", f"`{name}` = {what}."
            short = _short_feat(what, (idx["feat"].get(value.func.attr) or {}).get("label_vi", ""))
        elif ir_node is not None and _bool_node(ir_node) or isinstance(value, (ast.Compare, ast.BoolOp)) or (
                isinstance(value, ast.BinOp) and isinstance(value.op, (ast.BitAnd, ast.BitOr))):
            kind, head = "op", f"Điều kiện `{name}` đúng khi {what}."
        elif k0 == "op" or (isinstance(value, ast.Call) and k0):
            kind, head = "op", f"`{name}` = {what}."
        else:
            kind, head = "feature", f"Đại lượng `{name}` = {what}."
            if isinstance(value, ast.BinOp) and kind == "feature":
                short = f"{name} = {_plain(value).replace('self.', '')}"
        return kind, " ".join([head] + docs), refs, short, ""

    def assign(st, env: Optional[Dict[str, Any]]):
        target, value = (st.targets[0], st.value) if isinstance(st, ast.Assign) else (st.target, st.value)
        env = env or {}
        if isinstance(target, ast.Name):
            kind, txt, refs, sh, once = one_value(target.id, value, env.get(target.id))
            local.add(target.id)
            return add(st, kind, txt, refs, short=sh, once=once)
        names = [e.id for e in target.elts] if isinstance(target, (ast.Tuple, ast.List)) and all(isinstance(e, ast.Name) for e in target.elts) else []
        if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(names):
            parts = [one_value(n, v, env.get(n)) for n, v in zip(names, value.elts)]
            local.update(names)
            return add(st, parts[0][0] if len({p[0] for p in parts}) == 1 else "other", " ".join(p[1] for p in parts), sorted({r for p in parts for r in p[2]}),
                       short=parts[0][3], once=parts[0][4])
        docs = _catalog_docs(value, idx)
        outs = "; ".join(f"`{n}` = {_vi(env.get(n), value)}" for n in names)
        local.update(names)
        what = next((_vi(env.get(n), value) for n in names if env.get(n) is not None), "")
        fn = value.func.attr if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) else ""
        return add(st, "feature", f"Giải nén nhiều đầu ra: {outs or _src(target)}. " + " ".join(docs), _refs(value, local),
                   short=_short_feat(re.sub(r"^(Dải \w+|Đường \w+|Histogram) ", "", what), (idx["feat"].get(fn) or {}).get("label_vi", "")) if what else "")

    def rule(st, call: ast.Call, ir_calls):
        pos = call.keywords[0].value if call.keywords and call.keywords[0].arg == "position" else (call.args[1] if len(call.args) > 1 else None)
        lvl = _num(pos) if pos is not None else None
        if ir_calls:
            mask_ir, lvl, _ = ir_calls[0]
        else:
            mask_ir = None
        cond = _vi(mask_ir, call.args[0]) if call.args else "điều kiện"
        refs = _refs(call, local)
        ev = " (tín hiệu sự kiện: chỉ đúng ở nến xảy ra phép cắt)" if mask_ir is not None and _has_event_trigger(mask_ir) else ""
        cs = re.sub(r"\s*\(tín hiệu sự kiện[^)]*\)", "", _short_expr(cond))
        cs = re.sub(r"lớn hơn(?! hoặc)", "trên", re.sub(r"nhỏ hơn(?! hoặc)", "dưới", cs.replace("giá đóng cửa", "giá")))
        arg0 = call.args[0] if call.args else None
        by_name = f"{_src(arg0)} đúng" if isinstance(arg0, ast.Name) else "điều kiện đúng"

        def sr(prefix: str) -> str:
            t = f"{prefix} khi {cs}"
            return t if len(t) <= _SHORT_MAX else f"{prefix} khi {by_name}"
        later = " Nếu nhiều lệnh set_positions cùng đúng ở một nến, lệnh viết sau ghi đè lệnh trước."
        if lvl is None:
            return add(st, "rule_entry", f"Khi {cond}{ev} thì đặt vị thế theo `{_src(pos) if pos is not None else '?'}`." + later, refs, short=sr("Đặt vị thế"))
        if lvl == 0:
            return add(st, "rule_exit", f"Khi {cond}{ev} thì thoát vị thế (đưa về 0)." + later, refs, short=sr("Thoát vị thế"))
        side = "LONG" if lvl > 0 else "SHORT"
        size = "100% " if abs(lvl) == 1 else ""
        note = "" if abs(lvl) == 1 else f" (mức {lvl:g}: engine chỉ dùng dấu để chọn chiều, độ lớn lệnh do quản trị rủi ro quyết định)"
        return add(st, "rule_entry", f"Khi {cond}{ev} thì nắm giữ {size}vị thế {side}{note}." + later, refs,
                   short=sr(f"{'Mua' if lvl > 0 else 'Bán'} ({side}{' 100%' if abs(lvl) == 1 else ''})"))

    def stmt(st, trace):
        env, ir_calls = trace.get(id(st), (None, [])) if trace else (None, [])
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
            return add(st, "comment", "Chú thích (docstring) của tác giả: không ảnh hưởng đến kết quả chạy.")
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
            c = st.value
            if isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name) and c.func.value.id == "self":
                if c.func.attr == "set_positions":
                    return rule(st, c, ir_calls)
                if c.func.attr == "set_dca_gate":
                    return add(st, "rule_entry", f"Cổng dồn tầng DCA: chỉ cho phép dồn thêm khi {_vi(None, c.args[0]) if c.args else 'điều kiện'}. "
                               + idx["life"]["set_dca_gate"]["doc_vi"], _refs(c, local))
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) and _call_kind(st.value)[0] == "p" and st.value.args \
                and isinstance(st.value.args[0], ast.Constant) and st.value.args[0].value in pos_rows:
            pk, nm = pos_rows[st.value.args[0].value], st.value.args[0].value
            rng = f" Khoảng hợp lệ [{pk['lo']:g}, {pk['hi']:g}]{(' ' + pk['unit']) if pk['unit'] else ''}." if pk["lo"] is not None and pk["hi"] is not None else ""
            dflt = f", mặc định {_src(st.value.args[1])}" if len(st.value.args) > 1 else ""
            return add(st, "position", f"Khoá vị thế `{nm}`{dflt}: {pk['label_vi']}.{(' ' + pk['doc_vi']) if pk['doc_vi'] else ''}{rng}",
                       short="Vị thế và rủi ro: đổi số này rồi chạy lại", once="pos")
        if isinstance(st, ast.Pass):
            return add(st, "other", "Câu lệnh `pass`: không làm gì.")
        if isinstance(st, (ast.Assign, ast.AnnAssign)) and (isinstance(st, ast.AnnAssign) or len(st.targets) == 1) and st.value is not None:
            return assign(st, env)
        return add(st, "other", f"Câu lệnh Python `{_src(st).splitlines()[0][:80]}`.")

    def class_attr(st):
        t = st.targets[0] if isinstance(st, ast.Assign) else st.target
        if not isinstance(t, ast.Name):
            return add(st, "attr", f"Thuộc tính lớp `{_src(t)}`.")
        name, val = t.id, st.value
        pk = pos_rows.get(name)
        if name == "position" and isinstance(val, ast.Dict):
            keys = [k.value for k in val.keys if isinstance(k, ast.Constant)]
            det = "; ".join(f"{k}: {pos_rows[k]['label_vi']}" + (f" ({pos_rows[k]['doc_vi']})" if pos_rows[k]["doc_vi"] else "") for k in keys if k in pos_rows)
            return add(st, "position", "Khoá vị thế mặc định của chân này" + (f": {det}." if det else "."), short="Vị thế và rủi ro của chiến lược", once="pos")
        row = attrs.get(name)
        if name == "timeframe" and isinstance(val, ast.Constant) and isinstance(val.value, str) and res["kind"] == KIND_ALPHA:
            frame = TIMEFRAME_ALIASES.get(val.value.lower(), val.value)
            if frame in FRAME_MS:
                declared = {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
                declared |= {a.value.args[0].value for a in ast.walk(tree) if isinstance(a, ast.Expr) and isinstance(a.value, ast.Call)
                             and _call_kind(a.value)[0] == "p" and a.value.args and isinstance(a.value.args[0], ast.Constant)}
                auto = [(k, v) for k, v in (("atr_frame", f"ATR đo trên khung {frame}"), ("cooldown", f"nghỉ {FRAME_MS[frame] // 60_000} phút sau khi thoát")) if k not in declared]
                if auto:
                    note = "; ".join(v for _k, v in auto)
                    return add(st, "attr", f"`{name} = {_src(val)}`: {row['doc_vi']} Không khai báo {'/'.join(k for k, _v in auto)} nên engine dùng: {note}.",
                               short=f"Khung {frame}: ATR khung {frame}, nghỉ {FRAME_MS[frame] // 60_000} phút" if len(auto) == 2 else f"Khung {frame}: {note}")
        if pk is not None:
            extra = f" {pk['doc_vi']}" if pk["doc_vi"] else ""
            rng = f" Khoảng hợp lệ [{pk['lo']:g}, {pk['hi']:g}]{(' ' + pk['unit']) if pk['unit'] else ''}." if pk["lo"] is not None and pk["hi"] is not None else ""
            return add(st, "position", f"`{name} = {_src(val)}`: {pk['label_vi']}.{extra}{rng}", short="Vị thế và rủi ro: cắt lỗ, chốt lời, cỡ lệnh…", once="pos")
        if row is not None:
            return add(st, "attr", f"`{name} = {_src(val)}`: {row['doc_vi']}")
        used = sorted({n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == name and isinstance(n.value, ast.Name) and n.value.id == "self"})
        where = f"được dùng ở dòng {', '.join(map(str, used))} qua `self.{name}`" if used else "chưa được dòng nào dùng (self." + name + ")"
        return add(st, "attr", f"Tham số của chiến lược `{name} = {_src(val)}`: {where}; đổi giá trị này rồi chạy lại để có kết quả mới.",
                   short="Tham số: đổi số này rồi chạy lại", once="params")

    def func(fn: ast.FunctionDef):
        row = idx["life"].get(fn.name)
        add(fn, "lifecycle", (f"`def {fn.name}(self)`: " + row["doc_vi"]) if row else f"Hàm `{fn.name}`.", header_only=True)
        trace = tc.trace if tc is not None else None
        for st in fn.body:
            stmt(st, trace)

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            add(node, "class", f"Khai báo chiến lược `{node.name}`: lớp kế thừa {BASE_CLASS}; engine đọc các thuộc tính và luật bên trong để chạy backtest.", header_only=True,
                short="" if ast.get_docstring(node) else "Chiến lược: engine đọc tham số và luật bên dưới để chạy")
            for st in node.body:
                if isinstance(st, ast.FunctionDef):
                    func(st)
                elif isinstance(st, (ast.Assign, ast.AnnAssign)):
                    class_attr(st)
                else:
                    stmt(st, None)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "STRATEGY" for t in node.targets):
            add(node, "attr", "Khai báo thông tin họ chiến lược `STRATEGY` (id, tên, loại, mô tả, ý tưởng); chỉ để hiển thị.")
        elif isinstance(node, ast.FunctionDef):
            func(node)
        else:
            stmt(node, None)
    # chú thích `#` đứng riêng dòng
    covered = {ln for r in lines for ln in range(r["line"], r["end_line"] + 1)}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT and tok.start[0] not in covered:
                lines.append({"line": tok.start[0], "end_line": tok.start[0], "kind": "comment",
                              "text_vi": f"Ghi chú của tác giả: {tok.string.lstrip('#').strip()}", "refs": []})
                covered.add(tok.start[0])
    except (tokenize.TokenError, IndentationError):
        pass
    for i, text in enumerate(src.split("\n"), 1):      # dòng còn sót (đóng ngoặc, nối dòng…): phủ kín mọi dòng không trống
        if text.strip() and i not in covered:
            lines.append({"line": i, "end_line": i, "kind": "other", "text_vi": "Phần tiếp của câu lệnh phía trên.", "refs": []})
    out["lines"] = sorted(lines, key=lambda r: (r["line"], r["end_line"]))
    out["_short"] = shorts          # nội bộ: annotate_report lấy ra để dựng chú thích ngắn, KHÔNG nằm trong phản hồi
    return out


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
        tree = native_tree(tree)
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
            raise DslError(f"Cần ít nhất một class kế thừa {' hoặc '.join(BASE_CLASSES)}", 1, 1)
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
        base_name = cls.bases[0].id if (len(cls.bases) == 1 and isinstance(cls.bases[0], ast.Name)) else None
        if not (base_name in BASE_CLASSES) or cls.keywords or cls.decorator_list:
            raise at(cls, f"Class phải có dạng `class {cls.name}({BASE_CLASS}):` (hoặc kế thừa: {', '.join(BASE_CLASSES)})")
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
        prof = position.get("risk_profile") or "legacy"
        if prof != "legacy":
            from backend.analys.position import validate_strategy_risk
            issues = validate_strategy_risk(position, prof)
            if issues:
                raise at(cls, f"Vi phạm quy tắc Risk Profile '{prof}': {issues[0].message_vi} (Gợi ý: {issues[0].suggestion})")
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
        from backend.analys.param import EXIT_RISK_SPEC, POSITION_KEYS, SIG_PREFIX
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
            from backend.analys.param import _fmt_number
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
        from backend.analys.param import (EXIT_RISK_SPEC, exit_risk_entry, resolve_placeholders, schema_choice, schema_flt, schema_int,
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
# Mỗi SIGNAL là một cây điều kiện AST trên kernel (signal/indicator.py), được kiểm tra riêng
# bằng diagnostics (signal/nodes.py) trước khi ghép với tham số quản lý vị thế thành STRATEGY.
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
# MỘT định dạng nguồn duy nhất cho mọi chiến lược: file Python kiểu SimpleAlgorithm (cú pháp ở signal/nodes.py, khối "P9.9"). Cây AST / `params_schema` / `space`
# chỉ là dạng ĐÃ BIÊN DỊCH, sinh lại từ file mỗi lần nạp (nhớ theo mtime+size), không sửa tay. Core không đọc file: lớp này đọc rồi `signal/nodes.compile_strategy_module`
# biên dịch thuần; CANDIDATES / STRATEGIES / BY_ID (khối "Sổ chiến lược" bên dưới) chỉ là các góc nhìn trên kết quả nạp.
# ══════════════════════════════════════════════════════════════════════════

_cache: Dict[str, Any] = {"sig": None, "value": None}


def strategies_dir() -> str:
    """NORA_STRATEGIES_DIR > data/alpha/strategies."""
    env = os.environ.get("NORA_STRATEGIES_DIR")
    if env:
        return env
    return os.path.join(DATA_DIR, "alpha", "strategies")


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


# ═══ Bộ chuyển đổi đầu vào -> hợp đồng native (P10; gộp từ alpha/adapters) ═══

CLASS_NAME = "CustomStrategy"
IMPORT_WHITELIST = ("nora", "typing", "__future__")
_BASE_ALIASES = ("Strategy", "Algorithm", "BaseStrategy", "SimpleStrategy")
_COLS = ("open", "high", "low", "close", "volume")
_RETURN_KEYS = {"entry": (1.0, "entry"), "long_entry": (1.0, "entry"), "exit": (0.0, "exit"), "long_exit": (0.0, "exit"),
                "short_entry": (-1.0, "short_entry"), "short_exit": (0.0, "short_exit")}
_RETURN_ORDER = ("exit", "short_exit", "entry", "short_entry")      # thoát trước, vào sau (lệnh sau ghi đè lệnh trước)
_CONST_ATTRS = ("timeframe", "position_open_times", "position_open_ranges", "position_close_ranges")


# ─── nguồn + ghi chú ─────────────────────────────────────────────────────────

@dataclass
class Source:
    code: str                                   # văn bản gốc ("" nếu đầu vào là dict)
    tree: Optional[ast.Module] = None
    obj: Optional[dict] = None                  # JSON spec đã parse
    notes: List[dict] = field(default_factory=list)
    spans: List[Tuple[str, int, int, int]] = field(default_factory=list)     # json_spec: (đường dẫn trường, dòng, cột đầu, cột cuối) của từng biểu thức

    def note(self, code: str, message: str, node=None, line: Optional[int] = None, col: Optional[int] = None, path: Optional[str] = None):
        ln = getattr(node, "lineno", line)
        cl = getattr(node, "col_offset", None)
        cl = cl + 1 if cl is not None else col
        self.notes.append({"line": ln, "col": cl, "end_line": getattr(node, "end_lineno", None),
                           "end_col": (node.end_col_offset + 1) if getattr(node, "end_col_offset", None) is not None else None,
                           "severity": "info", "code": code, "message_vi": message, "suggest": [], "path": path})


@dataclass
class Adapter:
    style: str
    native: bool                                # True = RUN, False = ADAPT
    detect: Callable[[Source], bool]
    convert: Callable[[Source], ast.Module]     # có thể ném DslError
    kind: Optional[str] = None                  # None = suy từ cây (có STRATEGY -> module)


REGISTRY: List[Adapter] = []


def register(adapter: Adapter, first: bool = False) -> Adapter:
    """Thêm adapter (mặc định cuối danh sách = ưu tiên thấp nhất; first=True = ưu tiên cao nhất)."""
    REGISTRY.insert(0, adapter) if first else REGISTRY.append(adapter)
    return adapter


def _top_classes(tree) -> List[ast.ClassDef]:
    return [n for n in tree.body if isinstance(n, ast.ClassDef)]


def _has_strategy_dict(tree) -> bool:
    return any(isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "STRATEGY" for n in tree.body)


# ─── biên dịch theo kind ─────────────────────────────────────────────────────

def _compile(kind: str, code: str, tree: ast.Module):
    ast.fix_missing_locations(tree)
    return compile_program(code, tree) if kind == KIND_ALPHA else compile_strategy_module(code, tree)


def _kind_of(ad: Adapter, tree: ast.Module) -> str:
    return ad.kind or (KIND_MODULE if _has_strategy_dict(tree) else KIND_ALPHA)


# ─── chẩn đoán ───────────────────────────────────────────────────────────────

def _word_end(lines: List[str], line: int, col: int) -> int:
    """Cột kết thúc (1-based, loại trừ) của từ bắt đầu tại (line, col); tối thiểu col+1."""
    if line is None or col is None or not (1 <= line <= len(lines)):
        return (col or 1) + 1
    m = re.compile(r"[\w.]+").match(lines[line - 1], col - 1)
    return col + (len(m.group(0)) if m else 1)


def diag_from_error(e: DslError, lines: List[str], path: Optional[str] = None) -> dict:
    msg, sug = split_suggest(e.message)
    line, col = e.line or 1, e.col or 1
    end_line = getattr(e, "end_line", None)
    end_col = getattr(e, "end_col", None)
    if end_line is None or end_col is None:
        end_line, end_col = line, _word_end(lines, line, col)
    return {"line": line, "col": col, "end_line": end_line, "end_col": end_col, "severity": "error", "code": classify(e.message),
            "message_vi": msg, "suggest": sug, "path": path}


def _reject(style: str, kind: Optional[str], diags: List[dict]) -> dict:
    diags = [d for d in diags if not str(d.get("code", "")).startswith("ADAPTED_")]      # chưa chuyển được thì không báo "đã chuyển"
    return {"verdict": "REJECT", "style": style, "kind": kind, "diagnostics": diags, "normalized_code": None, "ir": None}


# ─── adapter: native (RUN) ───────────────────────────────────────────────────

def _convert_identity(src: Source) -> ast.Module:
    return src.tree


register(Adapter("strategy_module", True, lambda s: s.tree is not None and _has_strategy_dict(s.tree), _convert_identity, KIND_MODULE))
register(Adapter("lifecycle", True, lambda s: s.tree is not None and any(has_lifecycle(c) for c in _top_classes(s.tree)), _convert_identity))
register(Adapter("simple_algorithm", True, lambda s: s.tree is not None and bool(_top_classes(s.tree)), _convert_identity))


# ─── tên cột / namespace -> self.* ───────────────────────────────────────────

def _self(attr: Optional[str] = None, ctx=None):
    base = ast.Name(id="self", ctx=ast.Load())
    return base if attr is None else ast.Attribute(value=base, attr=attr, ctx=ast.Load())


def _data_col(name: str, node, src: Source, what: str):
    low = name.lower()
    if low.startswith("pv_"):
        low = low[3:]
    if low in _COLS:
        n = ast.copy_location(ast.Attribute(value=_self("data"), attr=f"pv_{low}", ctx=ast.Load()), node)
        return n
    raise at(node, f"{what} không có cột `{name}`." + suggest(low, _COLS) + f" Cột: {', '.join(_COLS)}.")


class _Names(ast.NodeTransformer):
    """Dùng chung function/json: data.X | data["X"] -> self.data.pv_X; feat/op -> self.feat/self.op; hằng thế thẳng; biến cục bộ giữ nguyên."""

    def __init__(self, src: Source, data_name: Optional[str], consts: Dict[str, Any], locals_: set, bare_cols: bool):
        self.src, self.data_name, self.consts, self.locals, self.bare_cols = src, data_name, consts, locals_, bare_cols

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and self.data_name and node.value.id == self.data_name and node.value.id not in self.locals:
            self.src.note("NORMALIZED_NAME", f"`{self.data_name}.{node.attr}` -> `self.data.pv_{node.attr.lower().removeprefix('pv_')}`", node)
            return _data_col(node.attr, node, self.src, f"`{self.data_name}`")
        return self.generic_visit(node)

    def visit_Subscript(self, node):
        if isinstance(node.value, ast.Name) and self.data_name and node.value.id == self.data_name and node.value.id not in self.locals:
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                self.src.note("NORMALIZED_NAME", f"`{self.data_name}[{node.slice.value!r}]` -> `self.data.pv_{node.slice.value.lower()}`", node)
                return _data_col(node.slice.value, node, self.src, f"`{self.data_name}[...]`")
            raise at(node, f"`{self.data_name}[...]` chỉ nhận tên cột dạng chuỗi: {self.data_name}['close']")
        return self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id not in self.locals:
            if node.id == self.data_name:
                raise at(node, f"`{node.id}` chỉ dùng dạng {node.id}.open|high|low|close|volume")
            if node.id in ("feat", "op"):
                return ast.copy_location(_self(node.id), node)
            if node.id in self.consts:
                return ast.copy_location(ast.Constant(value=self.consts[node.id]), node)
            if self.bare_cols and node.id in _COLS:
                return ast.copy_location(ast.Attribute(value=_self("data"), attr=f"pv_{node.id}", ctx=ast.Load()), node)
        return node


def _assigned_names(stmts) -> set:
    out = set()
    for st in stmts:
        for n in ast.walk(st):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                out.add(n.id)
    return out


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _build_class(attrs: List[ast.stmt], body: List[ast.stmt], returns: Dict[str, ast.expr], where_node) -> ast.Module:
    """class CustomStrategy(SimpleAlgorithm): <attrs>; def __algorithm__(self): <body>; set_positions theo _RETURN_ORDER."""
    stmts = list(body)
    levels = {"exit": 0.0, "short_exit": 0.0, "entry": 1.0, "short_entry": -1.0}
    for key in _RETURN_ORDER:
        mask = returns.get(key)
        if mask is None:
            continue
        call = ast.Call(func=ast.Attribute(value=_self(), attr="set_positions", ctx=ast.Load()), args=[mask],
                        keywords=[ast.keyword(arg="position", value=ast.Constant(value=levels[key]))])
        stmt = ast.Expr(value=call)
        for n in ast.walk(stmt):
            if "lineno" in n._attributes and not hasattr(n, "lineno"):
                ast.copy_location(n, mask)
        ast.copy_location(stmt, mask)
        stmts.append(stmt)
    algo = ast.FunctionDef(name="__algorithm__", args=ast.arguments(posonlyargs=[], args=[ast.arg(arg="self")], kwonlyargs=[], kw_defaults=[], defaults=[]),
                           body=stmts or [ast.Pass()], decorator_list=[], returns=None, type_comment=None)
    cls = ast.ClassDef(name=CLASS_NAME, bases=[ast.Name(id=BASE_CLASS, ctx=ast.Load())], keywords=[], body=attrs + [algo], decorator_list=[])
    for n in (algo, cls):
        ast.copy_location(n, where_node)
    mod = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(mod)
    return mod


# ─── adapter: function ───────────────────────────────────────────────────────

def _module_consts(tree: ast.Module, src: Source) -> Tuple[Dict[str, Any], List[ast.stmt], ast.FunctionDef]:
    consts: Dict[str, Any] = {}
    attrs: List[ast.stmt] = []
    fn: Optional[ast.FunctionDef] = None
    for node in tree.body:
        if _is_doc(node):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            if (mod or "").split(".")[0] in IMPORT_WHITELIST:
                src.note("NORMALIZED_IMPORT", f"Bỏ import `{mod}` (không cần: feat / op / data có sẵn)", node)
                continue
            raise at(node, f"Không dùng `import {mod}`: feat / op / data có sẵn. numpy/pandas/talib không dùng được (thay bằng feat.* / op.*)")
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            val = _const_literal(node.value, "Hằng cấp module phải là số / chuỗi / danh sách hằng")
            if name in _CONST_ATTRS or name in _position_names():
                attrs.append(node)
            elif _number(val):
                consts[name] = val
            else:
                raise at(node, f"Hằng cấp module `{name}` chỉ nhận số (hoặc timeframe / position_*); nhận {type(val).__name__}")
            continue
        if isinstance(node, ast.FunctionDef):
            if fn is not None:
                raise at(node, "Chỉ được định nghĩa một hàm `strategy(data)`")
            fn = node
            continue
        raise at(node, "Ở cấp ngoài chỉ được có docstring, hằng số, và đúng một hàm `def strategy(data):`")
    if fn is None:
        raise DslError("Thiếu `def strategy(data):`", 1, 1)
    return consts, attrs, fn


def _position_names() -> set:
    return _position_attr_names()


def _return_map(ret_value: ast.expr, src: Source) -> Dict[str, ast.expr]:
    out: Dict[str, ast.expr] = {}
    if isinstance(ret_value, ast.Dict):
        for k, v in zip(ret_value.keys, ret_value.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                raise at(k or ret_value, "Khoá của dict trả về phải là chuỗi")
            if k.value not in _RETURN_KEYS:
                raise at(k, f"Khoá `{k.value}` không hợp lệ; có: {', '.join(_RETURN_KEYS)}." + suggest(k.value, _RETURN_KEYS))
            if isinstance(v, ast.Constant) and v.value is None:
                continue
            canon = _RETURN_KEYS[k.value][1]
            if canon in out:
                raise at(k, f"Khoá `{k.value}` bị trùng (entry/long_entry, exit/long_exit là một)")
            out[canon] = v
    elif isinstance(ret_value, ast.Tuple) and 2 <= len(ret_value.elts) <= 4:
        for key, v in zip(("entry", "exit", "short_entry", "short_exit"), ret_value.elts):
            if not (isinstance(v, ast.Constant) and v.value is None):
                out[key] = v
    else:
        raise at(ret_value, 'Trả về {"entry": ..., "exit": ...} hoặc tuple (entry, exit[, short_entry, short_exit])')
    if not any(k in out for k in ("entry", "short_entry")):
        raise at(ret_value, "Cần ít nhất điều kiện vào: entry (long) hoặc short_entry")
    return out


def _convert_function(src: Source) -> ast.Module:
    consts, attrs, fn = _module_consts(src.tree, src)
    a = fn.args
    if (len(a.args) != 1 or a.vararg or a.kwarg or a.kwonlyargs or a.defaults or fn.decorator_list):
        raise at(fn, f"Chữ ký phải đúng `def {fn.name}(data):` (một đối số dữ liệu nến)")
    if fn.name != "strategy":
        raise at(fn, f"Tên hàm phải là `strategy`, nhận `{fn.name}`" + suggest(fn.name, ("strategy",)))
    data_name = a.args[0].arg
    body = [s for s in fn.body if not _is_doc(s)]
    if not body or not isinstance(body[-1], ast.Return) or body[-1].value is None:
        raise at(fn, 'Hàm phải kết thúc bằng `return {"entry": ..., "exit": ...}`')
    ret = body[-1]
    pre = body[:-1]
    locals_ = _assigned_names(pre)
    tr = _Names(src, data_name, consts, locals_, bare_cols=False)
    new_pre: List[ast.stmt] = []
    for st in pre:
        if isinstance(st, ast.Return):
            raise at(st, "`return` chỉ được đặt ở cuối hàm")
        new_pre.append(tr.visit(copy.deepcopy(st)))
    returns = {k: tr.visit(copy.deepcopy(v)) for k, v in _return_map(ret.value, src).items()}
    src.note("ADAPTED_FUNCTION", f"Hàm `{fn.name}({data_name})` được chuyển thành class {CLASS_NAME}(SimpleAlgorithm) với set_positions: thoát (0) rồi vào (1/-1)", fn)
    return _build_class(attrs, new_pre, returns, ret)


def _detect_function(s: Source) -> bool:
    return s.tree is not None and not _top_classes(s.tree) and any(isinstance(n, ast.FunctionDef) for n in s.tree.body)


# ─── adapter: JSON spec ──────────────────────────────────────────────────────

_JSON_KEYS = ("timeframe", "params", "indicators", "entry", "exit", "short_entry", "short_exit", "name", "description")


def _key_pos(raw: str, key: str) -> Tuple[Optional[int], Optional[int]]:
    """(dòng, cột 1-based) của giá trị chuỗi sau `"key":` trong văn bản JSON, hoặc (None, None)."""
    m = re.search(r'"%s"\s*:\s*' % re.escape(key), raw)
    if not m:
        return None, None
    line = raw.count("\n", 0, m.end()) + 1
    col = m.end() - (raw.rfind("\n", 0, m.end()) + 1) + 1
    return line, col


def _json_error(src: Source, path: str, key: str, message: str, line=None, col=None, end_col=None) -> DslError:
    ln, cl = _key_pos(src.code, key) if src.code else (None, None)
    e = DslError(message, ln if ln is not None else 1, (cl + 1 + (col - 1 if col else 0)) if cl is not None else (col or 1))
    e.end_line = e.line
    e.end_col = (e.col + (end_col - col if (end_col and col) else 1))
    e.path = path
    return e


def _parse_expr(src: Source, path: str, key: str, text: Any, names: Dict[str, Any], locals_: set) -> ast.expr:
    if not isinstance(text, str) or not text.strip():
        raise _json_error(src, path, key, f"`{path}` phải là biểu thức (chuỗi), nhận {type(text).__name__}")
    try:
        node = ast.parse(text.strip(), mode="eval").body
    except SyntaxError as e:
        raise _json_error(src, path, key, f"Lỗi cú pháp trong `{path}`: {e.msg}", col=(e.offset or 1)) from None
    ln, cl = _key_pos(src.code, key) if src.code else (None, None)
    if ln is None:
        ln = len(src.spans) + 1                  # đầu vào dict: dòng ảo theo thứ tự biểu thức
    src.spans.append((path, ln, (cl or 0) + 1, (cl or 0) + 1 + len(text.strip())))
    for n in ast.walk(node):
        if hasattr(n, "lineno"):
            n.lineno = n.end_lineno = ln
            n.col_offset += (cl if cl is not None else 0)       # +1 dấu nháy mở
            n.end_col_offset += (cl if cl is not None else 0)
    tr = _Names(src, None, names, locals_, bare_cols=True)
    try:
        return tr.visit(node)
    except DslError as e:
        e.path = path
        raise


def _convert_json(src: Source) -> ast.Module:
    obj = src.obj
    unknown = [k for k in obj if k not in _JSON_KEYS]
    if unknown:
        raise _json_error(src, unknown[0], unknown[0], f"Khoá `{unknown[0]}` không hợp lệ; có: {', '.join(_JSON_KEYS)}." + suggest(unknown[0], _JSON_KEYS))
    params = obj.get("params") or {}
    if not isinstance(params, dict):
        raise _json_error(src, "params", "params", "`params` phải là object {tên: số}")
    consts: Dict[str, Any] = {}
    for k, v in params.items():
        if not re.fullmatch(r"[A-Za-z_]\w*", str(k)) or k in _COLS or k in ("feat", "op", "self"):
            raise _json_error(src, f"params.{k}", k, f"Tên tham số {k!r} không hợp lệ (định danh, không trùng open/high/low/close/volume/feat/op)")
        if not _number(v):
            raise _json_error(src, f"params.{k}", k, f"Tham số `{k}` phải là số, nhận {v!r}")
        consts[k] = v
    inds = obj.get("indicators") or {}
    if not isinstance(inds, dict):
        raise _json_error(src, "indicators", "indicators", "`indicators` phải là object {tên: biểu thức}")
    attrs: List[ast.stmt] = []
    if "timeframe" in obj:
        if not isinstance(obj["timeframe"], str):
            raise _json_error(src, "timeframe", "timeframe", "`timeframe` phải là chuỗi, vd. \"4h\"")
        attrs.append(ast.Assign(targets=[ast.Name(id="timeframe", ctx=ast.Store())], value=ast.Constant(value=obj["timeframe"]), lineno=1))
    names = dict(consts)
    declared: set = set()
    body: List[ast.stmt] = []
    for name, text in inds.items():
        targets = [t.strip() for t in str(name).split(",")]
        if not all(re.fullmatch(r"[A-Za-z_]\w*", t) for t in targets) or any(t in _COLS or t in ("feat", "op", "self") for t in targets):
            raise _json_error(src, f"indicators.{name}", name, f"Tên chỉ báo {name!r} không hợp lệ (định danh; nhiều đầu ra: \"upper, mid, lower\")")
        value = _parse_expr(src, f"indicators.{name}", name, text, names, declared)
        tgt = ast.Name(id=targets[0], ctx=ast.Store()) if len(targets) == 1 else ast.Tuple(elts=[ast.Name(id=t, ctx=ast.Store()) for t in targets], ctx=ast.Store())
        st = ast.Assign(targets=[tgt], value=value)
        ast.copy_location(st, value)
        body.append(st)
        declared.update(targets)
    returns: Dict[str, ast.expr] = {}
    for key in ("exit", "short_exit", "entry", "short_entry"):
        if obj.get(key) is not None:
            returns[key] = _parse_expr(src, key, key, obj[key], names, declared)
    if not any(k in returns for k in ("entry", "short_entry")):
        raise _json_error(src, "entry", "entry", "Cần ít nhất điều kiện vào: `entry` (long) hoặc `short_entry`")
    anchor = next(iter(returns.values()))
    src.note("ADAPTED_JSON", "Bản mô tả JSON được chuyển thành class " + CLASS_NAME + "(SimpleAlgorithm): thoát (0) rồi vào (1/-1)", anchor)
    return _build_class(attrs, body, returns, anchor)


def _json_of(code) -> Optional[dict]:
    if isinstance(code, dict):
        return code
    if isinstance(code, str) and code.lstrip().startswith("{"):
        try:
            v = json.loads(code)
        except ValueError:
            return None
        return v if isinstance(v, dict) else None
    return None


register(Adapter("json_spec", False, lambda s: s.obj is not None, _convert_json, KIND_ALPHA), first=True)
register(Adapter("function", False, _detect_function, _convert_function, KIND_ALPHA), first=True)


# ─── adapter: ai_python (chuẩn hoá tất định mã class) ────────────────────────

class _Normalise(ast.NodeTransformer):
    def __init__(self, src: Source):
        self.src = src

    def _bin(self, op, values, node):
        out = values[0]
        for v in values[1:]:
            out = ast.copy_location(ast.BinOp(left=out, op=op, right=v), node)
        return out

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        word, sym, op = ("and", "&", ast.BitAnd()) if isinstance(node.op, ast.And) else ("or", "|", ast.BitOr())
        self.src.note("NORMALIZED_BOOL_OP", f"`{word}` -> `{sym}` (mặt nạ bool vector hoá)", node)
        return self._bin(op, node.values, node)

    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, ast.Not):
            self.src.note("NORMALIZED_BOOL_OP", "`not` -> `~` (phủ định mặt nạ bool)", node)
            return ast.copy_location(ast.UnaryOp(op=ast.Invert(), operand=node.operand), node)
        return node

    def visit_Compare(self, node):
        self.generic_visit(node)
        if len(node.ops) <= 1:
            return node
        parts = []
        left = node.left
        for op, right in zip(node.ops, node.comparators):
            parts.append(ast.copy_location(ast.Compare(left=left, ops=[op], comparators=[right]), node))
            left = right
        self.src.note("NORMALIZED_CHAINED_COMPARE", "So sánh nối chuỗi -> các so sánh nối bằng `&`", node)
        return self._bin(ast.BitAnd(), parts, node)

    def visit_Attribute(self, node):
        self.generic_visit(node)
        v = node.value
        if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id == "self":
            if v.attr == "data":
                low = node.attr.lower()
                canon = low if low.startswith("pv_") else f"pv_{low}"
                if canon[3:] in _COLS and canon != node.attr:
                    self.src.note("NORMALIZED_NAME", f"`self.data.{node.attr}` -> `self.data.{canon}`", node)
                    return ast.copy_location(ast.Attribute(value=v, attr=canon, ctx=node.ctx), node)
            elif v.attr in ("feat", "op"):
                from backend.analys.indicator import FEATURES, OPS
                table = FEATURES if v.attr == "feat" else OPS
                low = node.attr.lower()
                if node.attr not in table and low in table:
                    self.src.note("NORMALIZED_NAME", f"`self.{v.attr}.{node.attr}` -> `self.{v.attr}.{low}`", node)
                    return ast.copy_location(ast.Attribute(value=v, attr=low, ctx=node.ctx), node)
        return node

    def visit_Subscript(self, node):
        self.generic_visit(node)
        v = node.value
        if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id == "self" and v.attr == "data" \
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str) and node.slice.value.lower().removeprefix("pv_") in _COLS:
            col = node.slice.value.lower().removeprefix("pv_")
            self.src.note("NORMALIZED_NAME", f"`self.data[{node.slice.value!r}]` -> `self.data.pv_{col}`", node)
            return ast.copy_location(ast.Attribute(value=v, attr=f"pv_{col}", ctx=node.ctx), node)
        return node

    def visit_ClassDef(self, node):
        for i, b in enumerate(node.bases):
            if isinstance(b, ast.Name) and b.id in _BASE_ALIASES:
                self.src.note("NORMALIZED_BASE", f"Lớp cơ sở `{b.id}` -> `{BASE_CLASS}`", b)
                node.bases[i] = ast.copy_location(ast.Name(id=BASE_CLASS, ctx=ast.Load()), b)
        self.generic_visit(node)
        return node


def _convert_ai(src: Source) -> ast.Module:
    tree = copy.deepcopy(src.tree)
    body = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            if (mod or "").split(".")[0] in IMPORT_WHITELIST:
                src.note("NORMALIZED_IMPORT", f"Bỏ import `{mod}` (không cần: self.data / self.feat / self.op có sẵn)", node)
                continue
        body.append(node)
    tree.body = body
    return _Normalise(src).visit(tree)


_AI = Adapter("ai_python", False, lambda s: s.tree is not None and bool(_top_classes(s.tree)), _convert_ai)


# ─── điểm vào ────────────────────────────────────────────────────────────────

def _strip_fences(code: str, notes: List[dict]) -> str:
    """Bỏ hàng rào ```lang ... ``` (giữ số dòng: dòng hàng rào thành dòng trống)."""
    lines = code.split("\n")
    changed = False
    for i, ln in enumerate(lines):
        if ln.strip().startswith("```"):
            lines[i] = ""
            changed = True
    if changed:
        notes.append({"line": None, "col": None, "end_line": None, "end_col": None, "severity": "info", "code": "NORMALIZED_FENCE",
                      "message_vi": "Bỏ hàng rào markdown ```", "suggest": [], "path": None})
    return "\n".join(lines)


def _prepare(code) -> Tuple[Optional[Source], Optional[dict]]:
    """(Source, None) hoặc (None, kết quả REJECT)."""
    notes: List[dict] = []
    obj = _json_of(code)
    if obj is not None:
        return Source(code if isinstance(code, str) else "", obj=obj, notes=notes), None
    if not isinstance(code, str):
        return None, _reject("unknown", None, [{"line": 1, "col": 1, "end_line": 1, "end_col": 2, "severity": "error", "code": "BAD_STRUCTURE",
                                                 "message_vi": "Mã chiến lược phải là chuỗi (hoặc object JSON)", "suggest": [], "path": None}])
    if len(code) > MAX_CODE_CHARS:
        return None, _reject("unknown", None, [{"line": 1, "col": 1, "end_line": 1, "end_col": 2, "severity": "error", "code": "TOO_LARGE",
                                                 "message_vi": f"Mã quá dài ({len(code)} ký tự > {MAX_CODE_CHARS})", "suggest": [], "path": None}])
    text = _strip_fences(code, notes) if "```" in code else code
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        ln, cl = e.lineno or 1, e.offset or 1
        return None, _reject("unknown", None, [{"line": ln, "col": cl, "end_line": getattr(e, "end_lineno", None) or ln,
                                                 "end_col": (getattr(e, "end_offset", None) or cl + 1), "severity": "error", "code": "SYNTAX",
                                                 "message_vi": f"Lỗi cú pháp Python: {e.msg}", "suggest": [], "path": None}])
    except (RecursionError, MemoryError, ValueError) as e:
        return None, _reject("unknown", None, [{"line": 1, "col": 1, "end_line": 1, "end_col": 2, "severity": "error", "code": "SYNTAX",
                                                 "message_vi": f"Không phân tích được mã: {type(e).__name__}", "suggest": [], "path": None}])
    return Source(text, tree=tree, notes=notes), None


def _meta(ir, kind: str) -> Optional[dict]:
    if ir is None:
        return None
    if kind == KIND_ALPHA:
        return ir.meta()
    return {"strategy_id": ir["strategy"]["id"], "legs": [c["id"] for c in ir["candidates"]]}


def analyze(code) -> dict:
    """Thân của check_contract (alpha/contract): {verdict, style, kind, diagnostics, normalized_code, ir}."""
    src, bad = _prepare(code)
    if bad is not None:
        return bad
    lines = src.code.split("\n")
    ad = next((a for a in REGISTRY if a.detect(src)), None)
    if ad is None:
        return _reject("unknown", None, [{"line": 1, "col": 1, "end_line": 1, "end_col": 2, "severity": "error", "code": "NO_STRATEGY",
                                          "message_vi": "Không nhận ra dạng chiến lược. Dùng class X(SimpleAlgorithm) với on_start/on_bar, "
                                                        "hoặc def strategy(data):, hoặc bản mô tả JSON.", "suggest": ["lifecycle", "function", "json_spec"], "path": None}])

    def attempt(a: Adapter, s: Source):
        tree = a.convert(s)
        kind = _kind_of(a, tree)
        return kind, tree, _compile(kind, s.code, tree)

    try:
        kind, tree, ir = attempt(ad, src)
    except DslError as e:
        err_path = getattr(e, "path", None)
        if err_path is None and ad.style == "json_spec":
            err_path = next((sp[0] for sp in src.spans if sp[1] == e.line and (e.col is None or sp[2] <= e.col <= sp[3])), None)
        if ad.native:                         # dạng native hỏng: thử chuẩn hoá tất định (ai_python); không đổi được gì -> lỗi gốc
            src2 = Source(src.code, tree=src.tree, notes=list(src.notes))
            kind2 = KIND_MODULE if _has_strategy_dict(src.tree) else KIND_ALPHA
            try:
                tree2 = _AI.convert(src2)
                if len(src2.notes) > len(src.notes):
                    ir2 = _compile(kind2, src2.code, tree2)
                    return _adapt("ai_python", kind2, tree2, ir2, src2)
            except DslError as e2:
                if len(src2.notes) > len(src.notes):
                    return _reject(ad.style, kind2, src2.notes + [diag_from_error(e2, lines)])
        return _reject(ad.style, ad.kind or (KIND_MODULE if src.tree is not None and _has_strategy_dict(src.tree) else KIND_ALPHA),
                       src.notes + [diag_from_error(e, lines, err_path)])
    if ad.native:
        return {"verdict": "RUN", "style": ad.style, "kind": kind, "diagnostics": list(src.notes), "normalized_code": None, "ir": ir}
    return _adapt(ad.style, kind, tree, ir, src)


def _adapt(style: str, kind: str, tree: ast.Module, ir, src: Source) -> dict:
    return {"verdict": "ADAPT", "style": style, "kind": kind, "diagnostics": list(src.notes), "normalized_code": ast.unparse(tree) + "\n", "ir": ir}


def program_via_adapter(code, native_err: DslError):
    """compile_code: mã ngoài hợp đồng class (hàm strategy(data) / JSON) -> Program qua adapter; mã khác -> ném lại lỗi native gốc."""
    src, bad = _prepare(code)
    if bad is not None:
        raise native_err
    ad = next((a for a in REGISTRY if a.detect(src)), None)
    if ad is None or ad.native or ad.style == "ai_python":
        raise native_err
    tree = ad.convert(src)
    return _compile(KIND_ALPHA, src.code, tree)


# ═══ Sửa chiến lược hệ thống tại chỗ (P10; gộp từ strategies.py/strategy_files) ═══

MAX_BACKUPS = 20
BACKUP_DIRNAME = ".versions"


class StrategyEditError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra

    def detail(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def resolve(strategy_or_leg_id: str) -> Dict[str, Any]:
    """{id (chiến lược), file, legs[]} theo id chiến lược hoặc id chân."""
    loaded = load_system_strategies()
    srcs = loaded["sources"]
    for st in loaded["strategies"]:
        legs = [c["id"] for c in loaded["candidates"] if c["strategy"] == st["id"]]
        if strategy_or_leg_id == st["id"] or strategy_or_leg_id in legs:
            return {"id": st["id"], "file": srcs[legs[0]]["file"], "legs": legs}
    raise StrategyEditError(404, "NOT_FOUND", f"Không có chiến lược '{strategy_or_leg_id}'",
                            available=[s["id"] for s in loaded["strategies"]])


def read_source(strategy_or_leg_id: str) -> Dict[str, Any]:
    info = resolve(strategy_or_leg_id)
    with open(os.path.join(strategies_dir(), info["file"]), "rb") as fh:
        raw = fh.read()
    return {"id": info["id"], "file": info["file"], "code": raw.decode("utf-8"), "sha256": _sha(raw), "legs": info["legs"]}


def _prune_backups(directory: str, stem: str) -> None:
    mine = sorted(n for n in os.listdir(directory) if n.startswith(stem + ".") and n.endswith(".py"))
    for old in mine[:-MAX_BACKUPS]:
        try:
            os.remove(os.path.join(directory, old))
        except OSError:
            pass


def write_source(strategy_or_leg_id: str, code: str, sha256: str, backup_root: Optional[str] = None,
                 guard: Optional[Callable[[List[str]], None]] = None) -> Dict[str, Any]:
    """Ghi file chiến lược (thuần alpha). `backup_root`: thư mục cha của BACKUP_DIRNAME (mặc định: strategies_dir). `guard(removed_ids)`: tầng gọi chèn kiểm tra
    ngoài alpha (vd bot live) — ném StrategyEditError để chặn trước khi ghi. Nạp lại sổ ở tầng trên (strategies.py.reload_system_strategies)."""
    info = resolve(strategy_or_leg_id)
    path = os.path.join(strategies_dir(), info["file"])
    with open(path, "rb") as fh:
        old_raw = fh.read()
    if sha256 != _sha(old_raw):
        raise StrategyEditError(409, "SHA_CONFLICT", "File đã đổi từ lúc bạn mở (sha256 không khớp): tải lại rồi sửa tiếp.", current_sha256=_sha(old_raw))
    res = analyze(code)
    diags: List[Dict[str, Any]] = res["diagnostics"]
    if res["verdict"] == "REJECT":
        raise StrategyEditError(422, "CONTRACT_REJECTED", "Mã không đạt hợp đồng chiến lược", diagnostics=diags, style=res["style"])
    if res["kind"] != KIND_MODULE:
        raise StrategyEditError(422, "WRONG_KIND", "File chiến lược hệ thống phải có STRATEGY = {...} và class có id/family/description (loại module)",
                                diagnostics=diags, style=res["style"])
    new_code = res["normalized_code"] if res["verdict"] == "ADAPT" else code
    ir = res["ir"]
    new_legs = [c["id"] for c in ir["candidates"]]
    new_ids = set(new_legs) | {ir["strategy"]["id"]}
    srcs = load_system_strategies()["sources"]
    for cid in new_legs:
        if cid in srcs and srcs[cid]["file"] != info["file"]:
            raise StrategyEditError(409, "DUPLICATE_ID", f"Id chân '{cid}' đã dùng ở file {srcs[cid]['file']}", diagnostics=diags)
    clash = [s["id"] for s in load_system_strategies()["strategies"] if s["id"] == ir["strategy"]["id"] and ir["strategy"]["id"] != info["id"]]
    if clash:
        raise StrategyEditError(409, "DUPLICATE_ID", f"Id chiến lược '{clash[0]}' đã dùng ở file khác", diagnostics=diags)
    removed = sorted(({info["id"]} | set(info["legs"])) - new_ids)
    if guard is not None:
        guard(removed)
    # sao lưu -> ghi nguyên tử -> nạp lại
    bdir = os.path.join(backup_root or strategies_dir(), BACKUP_DIRNAME)
    os.makedirs(bdir, exist_ok=True)
    stem = info["file"][:-3]
    ns = time.time_ns()
    ts = time.strftime("%Y%m%dT%H%M%S", time.gmtime(ns // 10**9)) + f"{ns % 10**9:09d}Z"      # tên sắp xếp được theo thời gian, không trùng
    backup_path = os.path.join(bdir, f"{stem}.{ts}.py")
    with open(backup_path, "wb") as fh:
        fh.write(old_raw)
    _prune_backups(bdir, stem)
    new_raw = new_code.encode("utf-8")
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "wb") as fh:
        fh.write(new_raw)
    os.replace(tmp, path)
    try:
        load_system_strategies()
    except (DslError, FileNotFoundError) as e:      # không xảy ra nếu check đã qua; an toàn: khôi phục bản cũ
        with open(tmp, "wb") as fh:
            fh.write(old_raw)
        os.replace(tmp, path)
        load_system_strategies()
        raise StrategyEditError(422, "RELOAD_FAILED", f"Nạp lại sổ chiến lược lỗi, đã khôi phục bản cũ: {e}") from None
    return {"ok": True, "sha256": _sha(new_raw), "legs": new_legs, "normalized": res["verdict"] == "ADAPT", "diagnostics": diags,
            "backup": backup_path, "reloaded": True}
