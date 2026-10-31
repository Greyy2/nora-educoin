import sys
from pathlib import Path
import json

WORKSPACE = Path("/home/vmc03/norabt")
COIN_ROOT = WORKSPACE / "nora" / "coin"
sys.path.insert(0, str(COIN_ROOT))

from backend.analys.alpha.code.compile import compile_code
from backend.analys.alpha.code.plan import build_plan

with open(COIN_ROOT / "data" / "alpha" / "user" / "18e87aa868ad.json") as f:
    v1_raw = json.load(f)
with open(COIN_ROOT / "data" / "alpha" / "user" / "18e87aa868ad_v2.json") as f:
    v2_raw = json.load(f)

p1 = compile_code(v1_raw["code"])
p2 = compile_code(v2_raw["code"])

plan1 = build_plan(p1, ["BTC"], position=v1_raw.get("config", {}).get("position", {}), run_frame="24h")
plan2 = build_plan(p2, ["BTC"], position=v2_raw.get("config", {}).get("position", {}), run_frame="24h")

print("=== PLAN 1 POSITION ===")
pos1 = plan1.strategies[0]["position"]
for k in ["sizing", "order_size_pct", "risk_per_trade_pct", "max_notional_pct", "stop_loss_rate", "exit_unit", "leverage"]:
    print(f"  {k}: {pos1.get(k)}")

print("\n=== PLAN 2 POSITION ===")
pos2 = plan2.strategies[0]["position"]
for k in ["sizing", "order_size_pct", "risk_per_trade_pct", "max_notional_pct", "stop_loss_rate", "exit_unit", "leverage"]:
    print(f"  {k}: {pos2.get(k)}")
