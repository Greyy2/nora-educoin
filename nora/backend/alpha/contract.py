"""Strategy Contract (P9 alpha/): giới hạn + lỗi + gợi ý cho chiến lược do người dùng/AI viết. Chỉ import core (DslError ở core/signal vì Program ném nó).

Chuyển từ core/signal.py (P9 alpha pass): MAX_CODE_CHARS, MAX_NODES, BASE_CLASS, at, suggest, _position_attr_names.
"""
import ast
import difflib
from typing import Iterable, List, Optional, Set

from backend.core.signal import DslError

MAX_CODE_CHARS = 50_000
MAX_NODES = 20_000
BASE_CLASS = "SimpleAlgorithm"

def at(node, message: str) -> DslError:
    """DslError gắn vào một nút ast (lineno, col_offset 0-based -> cột 1-based)."""
    line = getattr(node, "lineno", None)
    col = getattr(node, "col_offset", None)
    err = DslError(message, line, None if col is None else col + 1)
    end_line, end_col = getattr(node, "end_lineno", None), getattr(node, "end_col_offset", None)
    if end_line is not None and end_col is not None:
        err.end_line, err.end_col = end_line, end_col + 1
    return err


def suggest(name: str, options: Iterable[str], n: int = 4) -> str:
    """' Gần đúng: a, b, c' (rỗng nếu không có tên nào gần)."""
    close: List[str] = difflib.get_close_matches(str(name), list(options), n=n, cutoff=0.5)
    return f" Gần đúng: {', '.join(close)}." if close else ""


def _position_attr_names() -> Set[str]:
    from backend.core.params import POSITION_KEYS
    return set(POSITION_KEYS)


# ══════════════════════════════════════════════════════════════════════════
# Vòng đời hợp đồng (NautilusTrader-style): on_start (khai báo) -> on_bar (luật) -> on_stop (tuỳ chọn, no-op).
# Biên dịch ĐỒNG NGHĨA với `def __algorithm__(self)` có thân = thân on_start + thân on_bar (cùng IR, cùng program_hash).
# Hàm thuần trên AST; cả hai trình biên dịch (alpha, module) dùng chung `lifecycle_body`.
# ══════════════════════════════════════════════════════════════════════════

LIFECYCLE = ("on_start", "on_bar", "on_stop")
_ACTIONS = ("set_positions", "set_dca_gate")


def _is_doc(stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def _calls_action(stmts) -> Optional[ast.Call]:
    for st in stmts:
        for n in ast.walk(st):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _ACTIONS \
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "self":
                return n
    return None


def has_lifecycle(cls: ast.ClassDef) -> bool:
    return any(isinstance(s, ast.FunctionDef) and s.name in LIFECYCLE for s in cls.body)


def lifecycle_body(cls: ast.ClassDef) -> List[ast.stmt]:
    """Thân class với on_start/on_bar/on_stop thay bằng MỘT `__algorithm__` tổng hợp (giữ nguyên dòng/cột các câu lệnh gốc).
    Class không dùng vòng đời: trả nguyên `cls.body`. Sai hợp đồng -> DslError có dòng/cột."""
    if not has_lifecycle(cls):
        return list(cls.body)
    found: dict = {}
    for st in cls.body:
        if isinstance(st, ast.FunctionDef) and st.name == "__algorithm__":
            raise at(st, "Không trộn `__algorithm__` với on_start/on_bar: chọn một dạng (khuyên dùng on_start + on_bar)")
    for st in cls.body:
        if isinstance(st, ast.FunctionDef) and st.name in LIFECYCLE:
            if st.name in found:
                raise at(st, f"`{st.name}` được định nghĩa hai lần")
            if (len(st.args.args) != 1 or st.args.args[0].arg != "self" or st.args.vararg or st.args.kwarg or st.args.kwonlyargs
                    or st.args.defaults or st.decorator_list):
                raise at(st, f"Chữ ký phải đúng `def {st.name}(self):`")
            found[st.name] = st
    if "on_bar" not in found:
        raise at(cls, "Thiếu `def on_bar(self):` chứa các luật self.set_positions(mask, position=...)")
    start, bar, stop = found.get("on_start"), found["on_bar"], found.get("on_stop")
    if start is not None:
        bad = _calls_action(start.body)
        if bad is not None:
            raise at(bad, "on_start chỉ KHAI BÁO tham số và chỉ báo; đặt self.set_positions / set_dca_gate trong on_bar")
    if stop is not None and not all(_is_doc(s) or isinstance(s, ast.Pass) for s in stop.body):
        raise at(stop, "on_stop chỉ được có docstring hoặc pass: engine tính vector hoá cả chuỗi nên không có sự kiện dừng để xử lý")
    if _calls_action(bar.body) is None:
        raise at(bar, "on_bar chưa gọi self.set_positions(mask, position=...) nên không có luật nào")
    algo = ast.FunctionDef(name="__algorithm__", args=bar.args, body=(list(start.body) if start is not None else []) + list(bar.body),
                           decorator_list=[], returns=None, type_comment=None)
    ast.copy_location(algo, bar)
    out: List[ast.stmt] = []
    for st in cls.body:
        if isinstance(st, ast.FunctionDef) and st.name in LIFECYCLE:
            if st is bar:
                out.append(algo)
            continue
        out.append(st)
    return out
