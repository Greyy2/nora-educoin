"""Lỗi biên dịch DSL chiến lược Python: luôn có số dòng + cột (1-based) để UI tô đúng chỗ."""
import difflib
from typing import Iterable, List, Optional


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
