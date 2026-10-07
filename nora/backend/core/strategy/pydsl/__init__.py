# P9-SHIM — P9.4 part 2 (ADR-P9): API biên dịch DSL đã chuyển sang backend.core.signal; gói này giữ để các module con cũ (alias) còn import được (gỡ ở P9.10).
"""DSL chiến lược Python (cú pháp dạng `SimpleAlgorithm`) chạy trên engine Nora — docs/bmad/p7_python_strategies.md.

    from backend.core.signal import compile_code        # (đường cũ `backend.core.strategy.pydsl` tái xuất cùng các tên này)
    prog = compile_code(code)          # DslError (có dòng/cột) nếu sai; đăng ký chương trình vào indicator để engine đọc cột py_<hash>_<le|lx|se|sx>
    plan = backend.core.backtest.build_plan(prog, symbols, ...)
"""
from backend.core.signal import DslError, Program, compile_code, compile_report, explain_program, explain_report

__all__ = ["compile_code", "compile_report", "explain_program", "explain_report", "DslError", "Program"]
