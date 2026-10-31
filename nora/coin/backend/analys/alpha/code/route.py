"""Bộ định tuyến và phân loại chiến lược (P17 T4): Nora DSL ↔ Nautilus native.

Quyết định hoàn toàn bằng luật tất định AST (không dùng LLM):
1. Có class kế thừa Nautilus Strategy -> 'native'
2. Khớp hợp đồng Nora DSL (RUN | ADAPT) -> 'dsl'
3. Ngoài hợp đồng DSL (REJECT): kiểm tra dấu hiệu chiến lược sự kiện phức tạp -> 'native' nếu có dấu hiệu, ngược lại 'dsl' (báo lỗi DSL)
"""
import ast
from typing import Any, Dict, List, Set, Tuple

from .compile import is_nautilus_native
from .contract import check_contract
from backend.analys.signal import DslError

_ENGINE_PKG = "nautilus" + "_trader"

# Danh sách trắng các thư viện được phép import trong mã Native
ALLOWED_MODULE_ROOTS = {
    _ENGINE_PKG,
    "numpy",
    "pandas",
    "math",
    "statistics",
    "collections",
    "dataclasses",
    "typing",
    "decimal",
    "datetime",
    "enum",
}
ALLOWED_NATIVE_MODULES = {"backend.core.strategy_proxima"}

# Các hàm builtin nguy hiểm bị cấm tuyệt đối
BANNED_BUILTINS = {
    "open", "exec", "eval", "compile", "__import__",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "input", "exit", "quit", "breakpoint"
}

ALLOWED_DUNDERS = {"__init__", "__name__", "__class__", "__doc__"}

# Các dấu hiệu chiến lược sự kiện phức tạp (AST pattern -> lý do tiếng Việt)
EVENT_CALLBACKS = {
    "on_order_filled": "xử lý sự kiện khớp lệnh (on_order_filled)",
    "on_order_rejected": "xử lý sự kiện từ chối lệnh (on_order_rejected)",
    "on_order_canceled": "xử lý sự kiện huỷ lệnh (on_order_canceled)",
    "on_trade_tick": "giao dịch theo từng tick giá (on_trade_tick)",
    "on_quote_tick": "giao dịch theo sổ lệnh / quote tick (on_quote_tick)",
    "on_order_book_depth": "truy cập độ sâu sổ lệnh L2 (on_order_book_depth)",
    "on_order_book_deltas": "theo dõi delta sổ lệnh (on_order_book_deltas)",
    "on_data": "xử lý luồng dữ liệu tuỳ biến (on_data)",
}

ORDER_METHODS = {
    "submit_order": "đặt lệnh chủ động (submit_order)",
    "cancel_order": "huỷ lệnh có chọn lọc (cancel_order)",
    "modify_order": "sửa lệnh đang chờ (modify_order)",
    "close_position": "quản lý vị thế chi tiết (close_position)",
    "close_all_positions": "đóng toàn bộ vị thế khẩn cấp (close_all_positions)",
}

PORTFOLIO_ATTRS = {
    "portfolio": "quản trị danh mục động (self.portfolio)",
    "cache": "truy xuất bộ đệm thị trường (self.cache)",
    "clock": "quản lý đồng hồ thời gian thực (self.clock)",
    "msgbus": "truyền thông điệp nội bộ (self.msgbus)",
}


def scan_native_signs(tree: ast.AST) -> List[str]:
    """Quét AST tìm các dấu hiệu của chiến lược sự kiện phức tạp."""
    reasons: List[str] = []
    seen: Set[str] = set()

    for node in ast.walk(tree):
        # 1. Định nghĩa các callback sự kiện
        if isinstance(node, ast.FunctionDef) and node.name in EVENT_CALLBACKS:
            msg = EVENT_CALLBACKS[node.name]
            if msg not in seen:
                seen.add(msg)
                reasons.append(msg)

        # 2. Gọi các hàm quản lý lệnh / portfolio
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr in ORDER_METHODS:
                msg = ORDER_METHODS[node.func.attr]
                if msg not in seen:
                    seen.add(msg)
                    reasons.append(msg)

        # 3. Truy cập các thuộc tính hệ thống
        elif isinstance(node, ast.Attribute) and node.attr in PORTFOLIO_ATTRS:
            msg = PORTFOLIO_ATTRS[node.attr]
            if msg not in seen:
                seen.add(msg)
                reasons.append(msg)

        # 4. Vòng lặp phức tạp (for / while) hoặc try/except bên trong logic
        elif isinstance(node, (ast.For, ast.While)):
            msg = "cấu trúc lặp tính toán tuỳ ý (for/while)"
            if msg not in seen:
                seen.add(msg)
                reasons.append(msg)

    return reasons


def verify_native_sandbox(code: str) -> None:
    """Kiểm tra tĩnh AST của mã nguồn Native để đảm bảo tính an toàn sandbox trước khi thực thi.
    
    Cấm truy cập file hệ thống, mạng, tiến trình con, và các builtin nguy hiểm.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise DslError(f"Lỗi cú pháp Python: {e.msg}", e.lineno, e.offset or 1) from None

    for node in ast.walk(tree):
        # 1. Kiểm tra import
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_pkg = alias.name.split(".")[0]
                if root_pkg not in ALLOWED_MODULE_ROOTS:
                    raise DslError(
                        f"Cấm import '{alias.name}' trong sandbox. Các thư viện hợp lệ: {', '.join(sorted(ALLOWED_MODULE_ROOTS))}",
                        node.lineno,
                        node.col_offset + 1,
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_pkg = node.module.split(".")[0]
                if root_pkg not in ALLOWED_MODULE_ROOTS and node.module not in ALLOWED_NATIVE_MODULES:
                    raise DslError(
                        f"Cấm import từ '{node.module}' trong sandbox. Các thư viện hợp lệ: {', '.join(sorted(ALLOWED_MODULE_ROOTS))}",
                        node.lineno,
                        node.col_offset + 1,
                    )

        # 2. Kiểm tra gọi hàm builtin cấm
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BANNED_BUILTINS:
                raise DslError(
                    f"Cấm gọi hàm nguy hiểm '{node.func.id}' trong sandbox",
                    node.lineno,
                    node.col_offset + 1,
                )

        # 3. Cấm truy cập thuộc tính dunder nguy hiểm
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("__") and attr.endswith("__") and attr not in ALLOWED_DUNDERS:
                raise DslError(
                    f"Cấm truy cập thuộc tính nội bộ '{attr}'",
                    node.lineno,
                    node.col_offset + 1,
                )


def classify(code: str) -> Dict[str, Any]:
    """Phân loại mã nguồn theo luật tất định AST: Nora DSL hay Nautilus native."""
    if not isinstance(code, str) or not code.strip():
        return {
            "engine": "dsl",
            "reasons": ["mã nguồn trống"],
            "confidence": "rule",
        }

    # 1. Có class kế thừa Nautilus Strategy -> native
    if is_nautilus_native(code):
        return {
            "engine": "native",
            "reasons": ["class Strategy Nautilus"],
            "confidence": "rule",
        }

    # 2. Kiểm tra AST và hợp đồng Nora DSL
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Nếu lỗi cú pháp Python cơ bản -> để DSL xử lý báo lỗi
        return {
            "engine": "dsl",
            "reasons": ["lỗi cú pháp Python"],
            "confidence": "rule",
        }

    res = check_contract(code)
    verdict = res.get("verdict")

    if verdict in ("RUN", "ADAPT"):
        return {
            "engine": "dsl",
            "reasons": ["khớp hợp đồng Nora DSL"],
            "confidence": "rule",
        }

    # 3. REJECT bởi DSL: quét xem có dấu hiệu chiến lược sự kiện phức tạp không
    signs = scan_native_signs(tree)
    if signs:
        return {
            "engine": "native",
            "reasons": signs,
            "confidence": "rule",
        }

    # Không có dấu hiệu native -> giữ nguyên là DSL (báo lỗi không khớp DSL)
    return {
        "engine": "dsl",
        "reasons": ["ngoài hợp đồng Nora DSL"],
        "confidence": "rule",
    }
