import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path("nora/edu").resolve()))
from backend.analys.alpha.code.compile import compile_code
from backend.analys.alpha.code.plan import build_plan

def audit_30():
    manifest_p = Path("nora/check/edu_frozen_inventory_manifest.json")
    manifest = json.loads(manifest_p.read_text(encoding="utf-8"))

    trivial_ids = {
        "026f43441cb2", "0bf936687964", "64b657c8de8e", "74f607263c5c", "7c1bf0a9686a", "a4d6826fbbc6", "d0518c0cca14",
        "138df68946ad", "1a1a4389a821", "2e41b2cfa24d", "bd234070bd7b", "be1174b24a44", "cb0b6e0f12e7",
        "1e4c0b9f84f7", "571474a18f55", "7f770ebe5ab5", "930294d28c45", "9eec3d61131d", "af2bf88426c4", "fd16df3d0a3f",
        "214ea8fdf3e6", "234e6df02e37", "616e1b8cbc88", "856ddc574ce7", "862e0c9eebbe", "e9a9a5b44d03", "ee0cf7f58f94"
    }

    remaining = [r for r in manifest["active_user_alphas"] if r["id"] not in trivial_ids]
    print(f"Total remaining alphas to audit: {len(remaining)}")

    for idx, r in enumerate(remaining, 1):
        aid = r["id"]
        raw = r["raw_record"]
        code = raw.get("code", "")
        cfg = raw.get("config", {})
        pos = cfg.get("position", {})
        prog = compile_code(code)
        plan = build_plan(prog, symbols=cfg.get("symbols", ["BTC"]), position=pos)
        
        is_vinh = (r.get("owner_id") == "aed197a5e968")
        
        print(f"\n[{idx:02d}] {aid} | Owner: {r.get('owner_id')} | Vinh: {is_vinh}")
        print(f"     Name: {r.get('name')}")
        print(f"     Timeframe: {prog.timeframe} | Legs: {prog.legs}")
        print(f"     Code overrides: {prog.position_overrides}")
        print(f"     Config position: exit_unit={pos.get('exit_unit')}, SL={pos.get('stop_loss_rate')}, TP={pos.get('take_profit_rate')}")
        print(f"     Plan warnings: {plan.warnings}")

if __name__ == "__main__":
    audit_30()
