"""Module Alpha Prompt:
Xử lý chuyển đổi từ ý tưởng người dùng (Prompt text) -> Công thức (Formula) + Ý tưởng giao dịch (Idea) -> Mã nguồn Python (Code) để chạy backtest.
Tích hợp LLM đơn giản, gọn gàng, chuẩn xác tương đương sova.

Thành phần:
- llm.py: Giao tiếp tập trung với LLM (Claude API / Mock LLM)
- research.py: Pipeline nghiên cứu 6 bước từ Prompt -> Idea -> Formula -> Code -> Backtest -> Synthesize
- prompts/: Mẫu prompt markdown định hướng tài chính và cấu trúc chiến lược
"""
from typing import Any, Dict, List, Optional

from . import llm, research, sources
from .llm import complete, extract_json_from_text, set_mock_completer, load_api_key
from .research import (
    validate_prompt,
    generate_ideas,
    to_formula,
    to_code,
    synthesize,
    PROMPTS_DIR,
)
from ..code import code_to_plan, Plan


def prompt_to_code(prompt_text: str, opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Chuyển đổi từ câu nhắc người dùng (Prompt text) -> Ý tưởng -> Công thức -> Mã code chuẩn để chạy backtest."""
    opts = opts or {}

    # Bước 1: Thẩm định prompt
    val = validate_prompt(prompt_text, opts=opts)
    if not val.get("valid"):
        return {
            "success": False,
            "error": val.get("reason", "Prompt không hợp lệ"),
            "stage": "validation",
            "validation": val,
        }

    # Bước 2: Sinh ý tưởng giao dịch
    norm_prompt = val.get("normalized_prompt") or prompt_text
    ideas = generate_ideas(norm_prompt, opts=opts)
    if not ideas:
        return {
            "success": False,
            "error": "Không thể sinh ý tưởng giao dịch từ prompt",
            "stage": "ideas",
        }
    primary_idea = ideas[0]

    # Bước 3: Chuyển ý tưởng sang công thức chỉ báo Nora
    formula_res = to_formula(primary_idea, opts=opts)

    # Bước 4: Chuyển công thức sang mã nguồn Python Nora DSL
    code_res = to_code(formula_res, opts=opts)
    if not code_res.get("compiled"):
        return {
            "success": False,
            "error": code_res.get("error", "Lỗi biên dịch mã nguồn sinh ra từ prompt"),
            "stage": "code_generation",
            "idea": primary_idea,
            "formula": formula_res,
            "code": code_res.get("code", ""),
        }

    return {
        "success": True,
        "idea": primary_idea,
        "formula": formula_res,
        "code": code_res.get("code", ""),
        "route": code_res.get("route", "dsl"),
    }


def prompt_to_plan(
    prompt_text: str,
    symbols: List[str],
    position: Optional[Dict[str, Any]] = None,
    run_frame: Optional[str] = None,
    opts: Optional[Dict[str, Any]] = None,
) -> Plan:
    """Từ prompt text người dùng -> tự động sinh ý tưởng, công thức, mã code và đóng gói thành Plan để run backtest ngay."""
    res = prompt_to_code(prompt_text, opts=opts)
    if not res.get("success"):
        raise ValueError(f"Không thể tạo Plan từ prompt: {res.get('error')}")
    return code_to_plan(
        code=res["code"],
        symbols=symbols,
        position=position,
        run_frame=run_frame,
    )


def run_research(prompt_text: str, opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Chạy quy trình nghiên cứu từ Prompt -> Idea -> Formula -> Code."""
    opts = opts or {}
    val = validate_prompt(prompt_text, opts=opts)
    if not val.get("valid"):
        return {"step": 1, "passed": False, "error": val.get("reason"), "validation": val}

    ideas = generate_ideas(val.get("normalized_prompt") or prompt_text, opts=opts)
    if not ideas:
        return {"step": 2, "passed": False, "error": "Không thể sinh ý tưởng", "ideas": []}

    idea = ideas[0]
    formula = to_formula(idea, opts=opts)
    code_res = to_code(formula, opts=opts)
    if not code_res.get("compiled"):
        return {"step": 4, "passed": False, "error": code_res.get("error"), "code_res": code_res}

    return {
        "step": 4,
        "passed": True,
        "idea": idea,
        "formula": formula,
        "code": code_res["code"],
        "route": code_res.get("route", "dsl"),
    }


__all__ = [
    "llm",
    "research",
    "PROMPTS_DIR",
    "complete",
    "extract_json_from_text",
    "set_mock_completer",
    "load_api_key",
    "validate_prompt",
    "generate_ideas",
    "to_formula",
    "to_code",
    "synthesize",
    "prompt_to_code",
    "prompt_to_plan",
    "run_research",
]
