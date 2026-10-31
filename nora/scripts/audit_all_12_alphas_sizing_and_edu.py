"""
In sizing, order_size_pct, risk_per_trade_pct, leverage hiệu lực của:
- 6 System legs
- 3 User Alphas v2
- 3 Top Agent Drafts
- Kiểm tra EDU params.py độc lập
"""
import sys
import json
from pathlib import Path

COIN_ROOT = Path("/home/vmc03/norabt/nora/coin")
EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")

# 1. COIN INSPECTION
sys.path.insert(0, str(COIN_ROOT))
from backend.analys.alpha.code.compile import compile_code, load_system_strategies
from backend.analys.param.params import build_params, BASE_POSITION, NORA_DEFAULTS, resolve_position_auto

print("=" * 80)
print("1. COIN: 6 SYSTEM LEGS")
print("=" * 80)
sys_loaded = load_system_strategies()
for c in sys_loaded["candidates"]:
    cid = c["id"]
    pos = c.get("position", {})
    # Xem position hiệu lực sau resolve
    eff_pos = resolve_position_auto({**BASE_POSITION, **NORA_DEFAULTS, **pos})
    bp = build_params(cid, {}, "entry", eff_pos, "cex")
    print(f"{cid:<16} | sizing={bp.sizing:<10} | order_size_pct={bp.order_size_pct:<6} | risk_pct={bp.risk_per_trade_pct:<5} | SL={bp.stop_loss_rate:<4} ({bp.exit_unit:<3}) | lev={bp.leverage}x")

print("\n" + "=" * 80)
print("2. COIN: 3 USER ALPHAS V2")
print("=" * 80)
for aid in ["efa90f74cd08_v2", "18e87aa868ad_v2", "33312a2f4dfc_v2"]:
    fpath = COIN_ROOT / "data" / "alpha" / "user" / f"{aid}.json"
    with open(fpath) as f:
        data = json.load(f)
    prog = compile_code(data["code"])
    pos_code = prog.position_overrides or {}
    pos_cfg = data.get("config", {}).get("position", {})
    merged = {**BASE_POSITION, **NORA_DEFAULTS, **pos_code, **pos_cfg}
    bp = build_params(aid, {}, "entry", merged, "cex")
    print(f"{aid:<16} | sizing={bp.sizing:<10} | order_size_pct={bp.order_size_pct:<6} | risk_pct={bp.risk_per_trade_pct:<5} | SL={bp.stop_loss_rate:<4} ({bp.exit_unit:<3}) | lev={bp.leverage}x")

print("\n" + "=" * 80)
print("3. COIN: 3 TOP AGENT DRAFTS")
print("=" * 80)
from scripts.top_agents_proxy_catalog import TOP_AGENT_PROXY_CODES
for tid, code in TOP_AGENT_PROXY_CODES.items():
    prog = compile_code(code)
    pos_code = prog.position_overrides or {}
    merged = {**BASE_POSITION, **NORA_DEFAULTS, **pos_code}
    bp = build_params(tid, {}, "entry", merged, "cex")
    print(f"{tid:<16} | sizing={bp.sizing:<10} | order_size_pct={bp.order_size_pct:<6} | risk_pct={bp.risk_per_trade_pct:<5} | SL={bp.stop_loss_rate:<4} ({bp.exit_unit:<3}) | lev={bp.leverage}x")

# Clean sys.modules for clean EDU inspection
del sys.path[0]
for m in list(sys.modules.keys()):
    if m.startswith("backend"):
        del sys.modules[m]

print("\n" + "=" * 80)
print("4. EDU: KIỂM TRA ĐỘC LẬP PARAMS VÀ BASE_POSITION")
print("=" * 80)
sys.path.insert(0, str(EDU_ROOT))
from backend.analys.param.params import BASE_POSITION as EDU_BASE, build_params as edu_build_params

print("EDU BASE_POSITION:")
for k in ["sizing", "order_size_pct", "risk_per_trade_pct", "max_notional_pct", "leverage"]:
    print(f"  {k}: {EDU_BASE.get(k)}")

p_edu_default = edu_build_params("test", {}, "entry", {"market": "perp"}, "cex")
print(f"EDU default build_params: sizing={p_edu_default.sizing}, order_size_pct={p_edu_default.order_size_pct}, risk_per_trade_pct={p_edu_default.risk_per_trade_pct}")
