import os
import sys
import json

sys.path.insert(0, "nora/coin")
os.environ["NORA_DIR"] = "nora/coin"
os.environ["NORA_LOCAL_DATA_ROOT"] = "nora/coin/data"
os.environ["NORA_LOCAL_LOGS_ROOT"] = "/tmp"
os.environ["NORA_JWT_SECRET"] = "test"

from backend.analys.alpha.code.compile import load_system_strategies
from backend.analys.param import resolve_position_auto, BASE_POSITION, NORA_DEFAULTS

loaded = load_system_strategies()
candidates = loaded["candidates"]
target_ids = ["kema_long", "kema_short", "sideway_long", "sideway_short"]

snapshot = {}
for c in candidates:
    if c["id"] in target_ids:
        raw_pos = c.get("position", {})
        # Note: kema tf is 4h, sideway is 1h/5m. Let's resolve with candidate timeframe
        tf = "4h" if "kema" in c["id"] else "1h"
        effective_pos = resolve_position_auto({**BASE_POSITION, **NORA_DEFAULTS, **raw_pos}, tf)
        snapshot[c["id"]] = {
            "declared_in_code": dict(raw_pos),
            "effective_resolved": dict(effective_pos),
        }

print("=== CANDIDATE POSITIONS SNAPSHOT BEFORE EDIT ===")
for cid, data in snapshot.items():
    print(f"\n--- {cid} ---")
    print(f"Declared: {data['declared_in_code']}")
    print(f"Effective exit_unit: {data['effective_resolved'].get('exit_unit')}")
    print(f"Effective atr_frame: {data['effective_resolved'].get('atr_frame')}")
    print(f"Effective cooldown: {data['effective_resolved'].get('cooldown')}")
    print(f"All effective keys ({len(data['effective_resolved'])}): {sorted(data['effective_resolved'].keys())}")

os.makedirs("nora/check", exist_ok=True)
out_path = "nora/check/coin_alpha_snapshot_before_explicit.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(snapshot, f, indent=2, ensure_ascii=False)
print(f"\nSUCCESS: Written snapshot to {out_path}")
