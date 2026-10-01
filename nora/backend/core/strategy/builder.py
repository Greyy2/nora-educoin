"""Công cụ Xây dựng Cây cú pháp (AST Builder) cho Alpha.

Cung cấp các hàm tiện ích để tạo ra các khối JSON cấu trúc AST
mà không phải viết chuỗi JSON thủ công dễ gây lỗi.
"""
from typing import Any, Dict, List, Union


class ASTBuilder:
    """Hỗ trợ xây dựng các Node điều kiện (Condition Nodes)."""

    @staticmethod
    def field(frame: str, column: str, index: str = "0") -> Dict[str, str]:
        """Tạo một Node trỏ tới một cột dữ liệu (ví dụ: 1m low)."""
        return {
            "frame": frame,
            "column": column,
            "index": index
        }

    @staticmethod
    def calc_node(n1: Any, logic: str, n2: Any, multiply: float = 1.0) -> Dict[str, Any]:
        """Tạo một Node phép tính: (n1 logic n2) * multiply."""
        return {
            "type": "calculate",
            "number_1": n1,
            "logic": logic,
            "number_2": n2,
            "multiply": multiply
        }

    @staticmethod
    def min_node(*numbers: Any) -> Dict[str, Any]:
        """Tạo một Node hàm min(a, b, c...)."""
        return {
            "type": "min",
            "numbers": list(numbers)
        }

    @staticmethod
    def max_node(*numbers: Any) -> Dict[str, Any]:
        """Tạo một Node hàm max(a, b, c...)."""
        return {
            "type": "max",
            "numbers": list(numbers)
        }

    @staticmethod
    def compare(left: Any, operator: str, right: Any) -> List[Any]:
        """Tạo một phép so sánh (Triplet): [Left, Operator, Right]."""
        return [left, operator, right]

    @staticmethod
    def and_group(*comparisons: List[Any]) -> List[List[Any]]:
        """Nhóm nhiều phép so sánh bằng AND."""
        return list(comparisons)


class AlphaStrategyBuilder:
    """Xây dựng một khối chiến lược hoàn chỉnh chứa cả điều kiện MUA (match) và BÁN (stop)."""

    def __init__(self, pos_type: str = "LONG"):
        self.pos_type = pos_type
        self.match_conditions: List[List[List[Any]]] = []
        self.stop_conditions: List[List[List[Any]]] = []
        self.settings: Dict[str, Any] = {
            "enter_price": "market",
            "stoploss": False,
        }

    def add_match_or_condition(self, and_group: List[List[Any]]):
        """Thêm một cụm AND vào điều kiện kích hoạt vị thế (OR với các cụm trước)."""
        self.match_conditions.append(and_group)
        return self

    def add_stop_or_condition(self, and_group: List[List[Any]]):
        """Thêm một cụm AND vào điều kiện đóng vị thế (Stop/Exit)."""
        self.stop_conditions.append(and_group)
        return self

    def set_config(self, **kwargs):
        """Cấu hình các tham số phụ (như baseprofit, step_profit...)."""
        self.settings.update(kwargs)
        return self

    def build(self) -> Dict[str, Any]:
        """Xuất ra chuỗi JSON AST hoàn chỉnh để lưu vào DB."""
        match_block = self.settings.copy()
        match_block["condition"] = self.match_conditions
        
        stop_block = {
            "condition": self.stop_conditions
        }
        
        return {
            "type": self.pos_type,
            "match": [match_block] if self.match_conditions else [],
            "stop": [stop_block] if self.stop_conditions else []
        }
