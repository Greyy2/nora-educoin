"""Module Alpha Code:
Xử lý logic từ mã nguồn Python sang chiến lược thực thi để run backtest,
chuyển đổi đa chiều giữa: Mã code <-> Ý tưởng diễn giải (Idea text) <-> Biểu thức công thức (Formula).

Thành phần:
- compile.py: Biên dịch Python AST & SimpleAlgorithm / Nautilus Strategy sang IR Program
- contract.py: Kiểm tra cú pháp, danh sách trắng chỉ báo / toán tử, hợp đồng chiến lược
- plan.py: Tạo kế hoạch thực thi (Plan, RiskConfig, build_plan, resolve_run_frame)
- route.py: Định tuyến và phân loại chiến lược (Nora DSL vs Nautilus Native)
"""
from typing import Any, Dict, List, Optional

from . import compile, contract, plan, route, spec
from .compile import compile_code, explain_program, is_nautilus_native
from .contract import check_contract, suggest, DslError
from .plan import Plan, RiskConfig, build_plan, aggregate_positions, display_name, resolve_run_frame
from .route import classify
from .spec import (
    ALL_SPEC_KEYS,
    OPTIONAL_SPEC_KEYS,
    REQUIRED_SPEC_KEYS,
    SCHEMA_VERSION,
    canonical_spec_dict,
    canonical_spec_hash,
    canonical_spec_json,
    validate_candidate_spec,
)


def code_to_plan(
    code: str,
    symbols: List[str],
    position: Optional[Dict[str, Any]] = None,
    strategy_id: Optional[str] = None,
    run_frame: Optional[str] = None,
) -> Plan:
    """Chuyển đổi trực tiếp từ mã code Python sang Plan hoàn chỉnh để run backtest."""
    prog = compile_code(code)
    return build_plan(
        program=prog,
        symbols=symbols,
        position=position,
        strategy_id=strategy_id,
        run_frame=run_frame,
    )


def code_to_idea(code: str, position: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Chuyển đổi từ mã code sang ý tưởng giao dịch (Idea text & Rules diễn giải tiếng Việt)."""
    prog = compile_code(code, register=False)
    exp = explain_program(prog, position=position)
    rules_vi = [r.get("action_vi", "") for r in exp.get("rules", [])]
    exec_vi = [e.get("desc", "") for e in exp.get("execution", [])]
    return {
        "timeframe": getattr(prog, "timeframe", "1h"),
        "legs": getattr(prog, "legs", []),
        "rules": rules_vi,
        "execution": exec_vi,
        "full_explanation": exp,
    }


def code_to_formula(code: str) -> Dict[str, Any]:
    """Chuyển đổi từ mã code sang dạng công thức logic."""
    prog = compile_code(code, register=False)
    formulas = {}
    for leg in getattr(prog, "legs", ["LONG"]):
        ent_col = prog.column("le" if leg == "LONG" else "se")
        ext_col = prog.column("lx" if leg == "LONG" else "sx")
        formulas[leg] = {
            "entry_signal": ent_col,
            "exit_signal": ext_col,
        }
    return {
        "timeframe": getattr(prog, "timeframe", "1h"),
        "code_hash": getattr(prog, "code_hash", ""),
        "formulas": formulas,
    }


def formula_to_code(
    entry_formula: str,
    exit_formula: Optional[str] = None,
    name: str = "FormulaStrategy",
    timeframe: str = "1h",
) -> str:
    """Tạo mã nguồn Python SimpleAlgorithm từ công thức logic."""
    exit_part = f"self.set_positions(~({entry_formula}), position=0)" if not exit_formula else f"self.set_positions({exit_formula}, position=0)"
    return f'''class {name}(SimpleAlgorithm):
    timeframe = "{timeframe}"

    def __algorithm__(self):
        long_cond = {entry_formula}
        self.set_positions(long_cond, position=1)
        {exit_part}
'''


__all__ = [
    "compile",
    "contract",
    "plan",
    "route",
    "compile_code",
    "explain_program",
    "is_nautilus_native",
    "check_contract",
    "suggest",
    "DslError",
    "Plan",
    "RiskConfig",
    "build_plan",
    "aggregate_positions",
    "display_name",
    "resolve_run_frame",
    "classify",
    "code_to_plan",
    "code_to_idea",
    "code_to_formula",
    "formula_to_code",
]
