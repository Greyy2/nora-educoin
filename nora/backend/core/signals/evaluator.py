"""Bộ thông dịch Logic Chiến lược (Strategy Logic Evaluator)."""
import math
import operator
from typing import Any, Callable, Dict, Optional

import numpy as np


def lag_key(column: str, lag: int) -> str:
    """Tên cột cho giá trị của `lag` nến trước trên cùng khung (index trong AST)."""
    return column if not lag else f"{column}__lag{int(lag)}"


class LogicEvaluator:
    """Đánh giá AST điều kiện chiến lược bằng interpreter an toàn (từng nến).

    Ngữ cảnh (ctx) là dict khung -> row, vd {"1m": {...}, "15m": {...}, "4h": {...}}.
    Trường AST {"frame": "15m", "column": "rsi_14", "index": 1} đọc ctx["15m"]["rsi_14__lag1"].
    API cũ (row_1m, row_4h, row_1h) vẫn được giữ.
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

    @staticmethod
    def _ctx(row_1m: Optional[Dict], row_4h: Optional[Dict], row_1h: Optional[Dict] = None) -> Dict[str, Dict]:
        return {k: v for k, v in (("1m", row_1m), ("4h", row_4h), ("1h", row_1h)) if v is not None}

    @staticmethod
    def compile_value_expr(item: Any) -> str:
        return str(item)

    @staticmethod
    def compile_condition_expr(condition_tree: Any) -> str:
        return str(condition_tree)

    @staticmethod
    def compile_ast(node: list) -> Callable[..., bool]:
        if not node:
            return lambda row_1m, row_4h=None, row_1h=None: False

        def _compiled(row_1m: Dict, row_4h: Optional[Dict] = None, row_1h: Optional[Dict] = None) -> bool:
            return LogicEvaluator.evaluate_condition_tree(node, row_1m, row_4h, row_1h)

        return _compiled

    @staticmethod
    def evaluate_condition_tree(condition_tree: Any, row_1m: Dict, row_4h: Optional[Dict] = None,
                                row_1h: Optional[Dict] = None) -> bool:
        return LogicEvaluator.evaluate_tree_ctx(condition_tree, LogicEvaluator._ctx(row_1m, row_4h, row_1h))

    @staticmethod
    def evaluate_value(item: Any, row_1m: Dict, row_4h: Optional[Dict] = None,
                       row_1h: Optional[Dict] = None) -> Optional[float]:
        return LogicEvaluator.value_ctx(item, LogicEvaluator._ctx(row_1m, row_4h, row_1h))

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
