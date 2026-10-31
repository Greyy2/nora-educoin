"""Kiểm tra và in sizing hiệu lực (Effective Position Parameters) của:
1. Hai Canonical Templates EDU
2. Ba Top Agent Drafts COIN
3. Ba User Alphas V2 COIN
"""
import sys
import json
from pathlib import Path

REPO_ROOT = Path("/home/vmc03/norabt")
COIN_ROOT = REPO_ROOT / "nora" / "coin"
EDU_ROOT = REPO_ROOT / "nora" / "edu"

sys.path.insert(0, str(COIN_ROOT))
from backend.analys.alpha.code.compile import compile_code
from backend.analys.alpha.code.plan import build_plan

print("=" * 80)
print("1. KIỂM TRA EDU CANONICAL TEMPLATES")
print("=" * 80)
sys.path.insert(0, str(EDU_ROOT))
from data.alpha.education.canonical_templates import CANONICAL_TEMPLATES

for tmpl in CANONICAL_TEMPLATES:
    tid = tmpl["id"]
    code = tmpl["code"]
    prog = compile_code(code)
    plan = build_plan(prog, ["BTC"])
    eff = plan.strategies[0]["position"]
    
    print(f"\nTemplate ID: {tid}")
    print(f"  - Khai báo trong Code (AST position_overrides):")
    for k in ("sizing", "risk_per_trade_pct", "stop_loss_rate", "take_profit_rate", "exit_unit", "leverage", "trailing_stop"):
        if k in prog.position_overrides:
            print(f"      {k}: {prog.position_overrides[k]}")
    print(f"  - Tham số hiệu lực đưa vào Engine (Plan Effective):")
    for k in ("sizing", "risk_per_trade_pct", "stop_loss_rate", "take_profit_rate", "exit_unit", "leverage", "trailing_stop"):
        print(f"      {k}: {eff.get(k)} (nguồn: {'code' if k in prog.position_overrides else 'base/nora_default'})")

print("\n" + "=" * 80)
print("2. KIỂM TRA COIN TOP AGENTS")
print("=" * 80)
top_dir = COIN_ROOT / "data" / "alpha" / "strategies" / "top_agent"
for f in sorted(top_dir.glob("*.py")):
    if f.name == "__init__.py":
        continue
    code = f.read_text(encoding="utf-8")
    prog = compile_code(code)
    plan = build_plan(prog, ["BTC"])
    eff = plan.strategies[0]["position"]
    
    print(f"\nTop Agent File: {f.name}")
    print(f"  - Khai báo trong Code (AST position_overrides):")
    for k in ("sizing", "risk_per_trade_pct", "stop_loss_rate", "take_profit_rate", "exit_unit", "leverage", "cooldown"):
        if k in prog.position_overrides:
            print(f"      {k}: {prog.position_overrides[k]}")
    print(f"  - Tham số hiệu lực đưa vào Engine (Plan Effective):")
    for k in ("sizing", "risk_per_trade_pct", "stop_loss_rate", "take_profit_rate", "exit_unit", "leverage", "cooldown"):
        print(f"      {k}: {eff.get(k)} (nguồn: {'code' if k in prog.position_overrides else 'base/nora_default'})")

print("\n" + "=" * 80)
print("3. KIỂM TRA COIN USER ALPHAS V2")
print("=" * 80)
user_dir = COIN_ROOT / "data" / "alpha" / "user"
for v2_id in ["efa90f74cd08_v2", "18e87aa868ad_v2", "33312a2f4dfc_v2"]:
    p = user_dir / f"{v2_id}.json"
    if not p.exists():
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    code = d["code"]
    prog = compile_code(code)
    plan = build_plan(prog, d.get("config", {}).get("symbols", ["BTC"]))
    eff = plan.strategies[0]["position"]
    
    print(f"\nUser Alpha V2 ID: {v2_id}")
    print(f"  - Khai báo trong Code (AST position_overrides):")
    for k in ("sizing", "risk_per_trade_pct", "stop_loss_rate", "take_profit_rate", "exit_unit", "leverage", "timeframe"):
        if k in prog.position_overrides or k == "timeframe":
            val = getattr(prog, k, None) if k == "timeframe" else prog.position_overrides.get(k)
            print(f"      {k}: {val}")
    print(f"  - Symbols trong config json: {d.get('config', {}).get('symbols')}")
    print(f"  - Plan Symbols đưa vào engine: {plan.symbols}")
    print(f"  - Tham số hiệu lực đưa vào Engine (Plan Effective):")
    for k in ("sizing", "risk_per_trade_pct", "stop_loss_rate", "take_profit_rate", "exit_unit", "leverage"):
        print(f"      {k}: {eff.get(k)} (nguồn: {'code' if k in prog.position_overrides else 'base/nora_default'})")
print("\n" + "=" * 80)
