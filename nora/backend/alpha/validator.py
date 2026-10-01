"""Safe validation for Alpha Studio strategy AST flows."""
import math
import re
from typing import Any, Dict, Iterable, List


class ASTValidationError(ValueError):
    pass


class ASTValidator:
    VALID_OPERATORS = {">", "<", ">=", "<=", "==", "!="}
    VALID_MATH_LOGIC = {"+", "-", "*", "/"}
    VALID_FRAMES = {"1m", "5m", "15m", "1h", "4h", "24h"}
    MAX_INDEX = 500  # số nến trễ tối đa (index) trên cùng khung
    BASE_COLUMNS = {"open_time", "open", "high", "low", "close", "volume"}
    FIELD_KEYS = {"type", "frame", "column", "index", "add", "subtract", "divide"}
    CALCULATE_KEYS = {"type", "number_1", "number_2", "logic", "multiply"}
    MIN_MAX_KEYS = {"type", "numbers"}
    KELTNER_RE = re.compile(r"^(?:kup|klo|kmid)\d+_[0-9]+$")
    ATR_RE = re.compile(r"^atr(?:\d+)?$")

    MAX_FLOWS = 8
    MAX_BLOCKS_PER_SECTION = 12
    MAX_OR_GROUPS = 24
    MAX_AND_CONDITIONS = 12
    MAX_VALUE_DEPTH = 8
    MAX_VALUE_NODES = 256
    MAX_NUMBERS_PER_NODE = 12

    @classmethod
    def validate_flows(cls, flows: List[Dict[str, Any]]) -> bool:
        try:
            cls.validate_flows_or_raise(flows)
            return True
        except ASTValidationError:
            return False

    @classmethod
    def validate_flows_or_raise(cls, flows: List[Dict[str, Any]]) -> None:
        if not isinstance(flows, list) or not flows:
            raise ASTValidationError("Cần ít nhất một flow AST để mô phỏng.")
        if len(flows) > cls.MAX_FLOWS:
            raise ASTValidationError(f"Studio chỉ cho phép tối đa {cls.MAX_FLOWS} flows mỗi lần chạy.")

        for index, flow in enumerate(flows):
            if not isinstance(flow, dict):
                raise ASTValidationError(f"Flow #{index + 1} phải là object JSON.")
            name = str(flow.get("name") or f"flow_{index + 1}")
            ast = flow.get("ast", flow)
            cls.validate_flow_or_raise(name, ast)

    @classmethod
    def validate_flow(cls, flow_name: str, flow_ast: Dict[str, Any]) -> bool:
        try:
            cls.validate_flow_or_raise(flow_name, flow_ast)
            return True
        except ASTValidationError:
            return False

    @classmethod
    def validate_flow_or_raise(cls, flow_name: str, flow_ast: Dict[str, Any]) -> None:
        if not isinstance(flow_ast, dict):
            raise ASTValidationError(f"{flow_name}: AST phải là object JSON.")

        pos_type = flow_ast.get("type")
        if pos_type not in ("LONG", "SHORT"):
            raise ASTValidationError(f"{flow_name}: type chỉ được là LONG hoặc SHORT.")

        match_blocks = flow_ast.get("match")
        if not isinstance(match_blocks, list) or not match_blocks:
            raise ASTValidationError(f"{flow_name}: match phải là danh sách block không rỗng.")
        cls._validate_blocks(flow_name, "match", match_blocks, required=True)

        stop_blocks = flow_ast.get("stop", [])
        if stop_blocks is None:
            stop_blocks = []
        if not isinstance(stop_blocks, list):
            raise ASTValidationError(f"{flow_name}: stop phải là danh sách block.")
        if stop_blocks:
            cls._validate_blocks(flow_name, "stop", stop_blocks, required=True)

    @classmethod
    def _validate_blocks(
        cls,
        flow_name: str,
        section: str,
        blocks: List[Dict[str, Any]],
        required: bool,
    ) -> None:
        if len(blocks) > cls.MAX_BLOCKS_PER_SECTION:
            raise ASTValidationError(
                f"{flow_name}: {section} vượt quá {cls.MAX_BLOCKS_PER_SECTION} blocks."
            )

        for block_index, block in enumerate(blocks):
            if not isinstance(block, dict):
                raise ASTValidationError(f"{flow_name}: {section}[{block_index}] phải là object JSON.")
            condition = block.get("condition")
            if condition is None:
                if required:
                    raise ASTValidationError(f"{flow_name}: {section}[{block_index}] thiếu condition.")
                continue
            cls._validate_condition_tree(flow_name, f"{section}[{block_index}].condition", condition)

    @classmethod
    def _validate_condition_tree(cls, flow_name: str, path: str, condition_tree: Any) -> None:
        if not isinstance(condition_tree, list) or not condition_tree:
            raise ASTValidationError(f"{flow_name}: {path} phải là OR-list không rỗng.")
        if len(condition_tree) > cls.MAX_OR_GROUPS:
            raise ASTValidationError(f"{flow_name}: {path} vượt quá {cls.MAX_OR_GROUPS} OR groups.")

        context = {"nodes": 0}
        for group_index, and_group in enumerate(condition_tree):
            if not isinstance(and_group, list) or not and_group:
                raise ASTValidationError(f"{flow_name}: {path}[{group_index}] phải là AND-list không rỗng.")
            if len(and_group) > cls.MAX_AND_CONDITIONS:
                raise ASTValidationError(
                    f"{flow_name}: {path}[{group_index}] vượt quá {cls.MAX_AND_CONDITIONS} điều kiện."
                )
            for triplet_index, triplet in enumerate(and_group):
                if not isinstance(triplet, list) or len(triplet) != 3:
                    raise ASTValidationError(
                        f"{flow_name}: {path}[{group_index}][{triplet_index}] phải là [left, operator, right]."
                    )
                left, operator, right = triplet
                if operator not in cls.VALID_OPERATORS:
                    raise ASTValidationError(f"{flow_name}: toán tử {operator!r} không được hỗ trợ.")
                cls._validate_value(flow_name, left, f"{path}[{group_index}][{triplet_index}].left", 0, context)
                cls._validate_value(flow_name, right, f"{path}[{group_index}][{triplet_index}].right", 0, context)

    @classmethod
    def _validate_value(
        cls,
        flow_name: str,
        value: Any,
        path: str,
        depth: int,
        context: Dict[str, int],
    ) -> None:
        context["nodes"] += 1
        if context["nodes"] > cls.MAX_VALUE_NODES:
            raise ASTValidationError(f"{flow_name}: AST vượt quá {cls.MAX_VALUE_NODES} value nodes.")
        if depth > cls.MAX_VALUE_DEPTH:
            raise ASTValidationError(f"{flow_name}: {path} vượt quá độ sâu {cls.MAX_VALUE_DEPTH}.")

        if cls._is_finite_number(value):
            return
        if isinstance(value, str):
            raise ASTValidationError(f"{flow_name}: {path} không nhận string literal, hãy dùng number hoặc field node.")
        if not isinstance(value, dict):
            raise ASTValidationError(f"{flow_name}: {path} phải là number hoặc object value node.")

        node_type = value.get("type")
        if node_type in ("min", "max"):
            cls._validate_min_max(flow_name, value, path, depth, context)
            return
        if node_type == "calculate":
            cls._validate_calculate(flow_name, value, path, depth, context)
            return
        if "frame" in value and "column" in value:
            cls._validate_field(flow_name, value, path, depth, context)
            return

        raise ASTValidationError(f"{flow_name}: {path} không phải value node hợp lệ.")

    @classmethod
    def _validate_field(
        cls,
        flow_name: str,
        value: Dict[str, Any],
        path: str,
        depth: int,
        context: Dict[str, int],
    ) -> None:
        extra_keys = set(value) - cls.FIELD_KEYS
        if extra_keys:
            raise ASTValidationError(f"{flow_name}: {path} có key chưa hỗ trợ: {sorted(extra_keys)}.")
        if value.get("type") not in (None, "frame"):
            raise ASTValidationError(f"{flow_name}: {path}.type chỉ được là frame.")

        frame = value.get("frame")
        column = value.get("column")
        if frame not in cls.VALID_FRAMES:
            raise ASTValidationError(f"{flow_name}: frame {frame!r} không được hỗ trợ trong Studio.")
        if not isinstance(column, str) or not cls._is_allowed_column(frame, column):
            raise ASTValidationError(f"{flow_name}: cột {frame}.{column} chưa được hỗ trợ.")

        index = value.get("index", 0)
        try:
            index_int = int(index) if index not in (None, "") else 0
        except (TypeError, ValueError):
            raise ASTValidationError(f"{flow_name}: {path}.index phải là số nguyên (số nến trước).")
        if isinstance(index, bool) or str(index_int) != str(index).strip() and index not in (None, "") \
                or not 0 <= index_int <= cls.MAX_INDEX:
            raise ASTValidationError(f"{flow_name}: {path}.index phải là số nguyên 0..{cls.MAX_INDEX}.")

        for modifier in ("add", "subtract", "divide"):
            if modifier in value:
                cls._validate_value(flow_name, value[modifier], f"{path}.{modifier}", depth + 1, context)

    @classmethod
    def _validate_calculate(
        cls,
        flow_name: str,
        value: Dict[str, Any],
        path: str,
        depth: int,
        context: Dict[str, int],
    ) -> None:
        extra_keys = set(value) - cls.CALCULATE_KEYS
        if extra_keys:
            raise ASTValidationError(f"{flow_name}: {path} có key chưa hỗ trợ: {sorted(extra_keys)}.")
        logic = value.get("logic")
        if logic not in cls.VALID_MATH_LOGIC:
            raise ASTValidationError(f"{flow_name}: phép tính {logic!r} không được hỗ trợ.")
        multiply = value.get("multiply", 1.0)
        if not cls._is_finite_number(multiply):
            raise ASTValidationError(f"{flow_name}: {path}.multiply phải là số hữu hạn.")
        cls._validate_value(flow_name, value.get("number_1"), f"{path}.number_1", depth + 1, context)
        cls._validate_value(flow_name, value.get("number_2"), f"{path}.number_2", depth + 1, context)

    @classmethod
    def _validate_min_max(
        cls,
        flow_name: str,
        value: Dict[str, Any],
        path: str,
        depth: int,
        context: Dict[str, int],
    ) -> None:
        extra_keys = set(value) - cls.MIN_MAX_KEYS
        if extra_keys:
            raise ASTValidationError(f"{flow_name}: {path} có key chưa hỗ trợ: {sorted(extra_keys)}.")
        numbers = value.get("numbers")
        if not isinstance(numbers, list) or not numbers:
            raise ASTValidationError(f"{flow_name}: {path}.numbers phải là danh sách không rỗng.")
        if len(numbers) > cls.MAX_NUMBERS_PER_NODE:
            raise ASTValidationError(f"{flow_name}: {path}.numbers vượt quá {cls.MAX_NUMBERS_PER_NODE} phần tử.")
        for index, number in enumerate(numbers):
            cls._validate_value(flow_name, number, f"{path}.numbers[{index}]", depth + 1, context)

    @classmethod
    def _is_allowed_column(cls, frame: str, column: str) -> bool:
        from backend.signals.kernels import is_kernel_column
        if column in cls.BASE_COLUMNS or is_kernel_column(column):
            return True
        if frame == "4h" and (cls.ATR_RE.fullmatch(column) or cls.KELTNER_RE.fullmatch(column)):
            return True
        return False

    @staticmethod
    def _is_finite_number(value: Any) -> bool:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return math.isfinite(float(value))

    @classmethod
    def supported_columns(cls, frame: str) -> List[str]:
        """Cột cố định + ví dụ kernel (kernel nhận mọi tham số hợp lệ, xem signals/kernels.py)."""
        from backend.signals.kernels import catalog
        base = ["open_time", "open", "high", "low", "close", "volume", *[k["example"] for k in catalog()]]
        if frame == "4h":
            return [*base, "atr", "atr14", "atr17", "atr20", "kup17_05", "kmid17_05", "klo17_05", "kup20_15", "kmid20_15", "klo20_15"]
        return base

    @classmethod
    def iter_field_nodes(cls, value: Any) -> Iterable[Dict[str, Any]]:
        if isinstance(value, list):
            for item in value:
                yield from cls.iter_field_nodes(item)
        elif isinstance(value, dict):
            if "frame" in value and "column" in value:
                yield value
            for key in ("number_1", "number_2", "add", "subtract", "divide"):
                if key in value:
                    yield from cls.iter_field_nodes(value[key])
            for item in value.get("numbers", []) if isinstance(value.get("numbers"), list) else []:
                yield from cls.iter_field_nodes(item)
