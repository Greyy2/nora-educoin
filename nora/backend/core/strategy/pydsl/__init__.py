"""DSL chiến lược Python (cú pháp dạng `SimpleAlgorithm`) chạy trên engine Nora — docs/bmad/p7_python_strategies.md.

    from backend.core.strategy.pydsl import compile_code
    prog = compile_code(code)          # DslError (có dòng/cột) nếu sai; đăng ký chương trình vào signals.kernels để engine đọc cột py_<hash>_<le|lx|se|sx>
    plan = profiles.build_plan(prog, symbols, ...)
"""
from typing import Any, Dict, Optional

from backend.core.signals import kernels
from backend.core.strategy.pydsl.errors import DslError
from backend.core.strategy.pydsl.parser import compile_program
from backend.core.strategy.pydsl.program import Program

__all__ = ["compile_code", "compile_report", "explain_program", "explain_report", "DslError", "Program"]


def compile_code(code: str, register: bool = True) -> Program:
    """Biên dịch + (mặc định) đăng ký vào kernels để PortfolioEngine tính được cột py_<hash12>_*. Phải gọi trong CHÍNH tiến trình chạy engine."""
    prog = compile_program(code)
    if register:
        kernels.register_program(prog.code_hash, prog)
    return prog


def compile_report(code: str) -> Dict[str, Any]:
    """Dạng trả về của POST /api/studio/strategies/compile: {ok, program_hash, meta, warnings, error}."""
    try:
        prog = compile_code(code)
    except DslError as e:
        return {"ok": False, "program_hash": None, "meta": None, "warnings": [], "error": e.to_dict()}
    return {"ok": True, "program_hash": prog.code_hash, "meta": prog.meta(), "warnings": prog.warnings, "error": None}


def explain_program(prog: Program, position: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from backend.core.strategy.pydsl.explain import explain_program as _ep
    return _ep(prog, position=position)


def explain_report(code: str, position: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Dạng trả về của POST /api/studio/strategies/explain: {ok, indicators[], rules[], execution[], warnings[], error}."""
    try:
        prog = compile_code(code, register=False)
    except DslError as e:
        return {"ok": False, "indicators": [], "rules": [], "execution": [], "warnings": [], "error": e.to_dict()}
    return {"ok": True, "error": None, **explain_program(prog, position=position)}


