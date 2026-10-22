"""Kiến trúc Module Alpha (backend.analys.alpha):
- code: Xử lý logic từ mã nguồn Python sang strategies để run backtest, chuyển đổi giữa code - idea text - công thức
- prompt: Xử lý cho prompt text -> công thức + idea -> code để chạy backtest (gọn tương đương sova, có LLM chạy đơn giản)
- strategies.py: Đúng 1 file xử lý toàn diện các vấn đề chung của alpha (thư viện chiến lược, lưu trữ alpha người dùng, kiểm định tiêu chí, presets, gates)
"""
from . import code, prompt, strategies
store = strategies  # Alias chuyển tiếp: hợp nhất vào 1 file strategies.py
compile = code.compile  # Alias tương thích
plan = code.plan
contract = code.contract
llm = prompt.llm
research = prompt.research



# Re-exports từ code
from .code import (
    compile_code,
    explain_program,
    check_contract,
    classify,
    Plan,
    RiskConfig,
    build_plan,
    aggregate_positions,
    display_name,
    resolve_run_frame,
    code_to_plan,
    code_to_idea,
    code_to_formula,
    formula_to_code,
)

# Re-exports từ prompt
from .prompt import (
    prompt_to_code,
    prompt_to_plan,
    run_research,
    validate_prompt,
    generate_ideas,
    to_formula,
    to_code,
)

# Re-exports từ strategies
from .strategies import (
    BY_ID,
    CANDIDATES,
    STRATEGIES,
    save_user_alpha,
    get_user_alpha,
    list_user_alphas,
    generate_alpha_id,
    evaluate_checklist,
)

__all__ = [
    # 3 thành phần kiến trúc cốt lõi
    "code",
    "prompt",
    "strategies",
    "store",
    # Code & Execution Plan
    "compile_code",
    "explain_program",
    "check_contract",
    "classify",
    "Plan",
    "RiskConfig",
    "build_plan",
    "aggregate_positions",
    "display_name",
    "resolve_run_frame",
    "code_to_plan",
    "code_to_idea",
    "code_to_formula",
    "formula_to_code",
    # Prompt & LLM
    "prompt_to_code",
    "prompt_to_plan",
    "run_research",
    "validate_prompt",
    "generate_ideas",
    "to_formula",
    "to_code",
    # Strategies & User Alphas
    "BY_ID",
    "CANDIDATES",
    "STRATEGIES",
    "save_user_alpha",
    "get_user_alpha",
    "list_user_alphas",
    "generate_alpha_id",
    "evaluate_checklist",
]
