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

snapshot_path = "nora/check/coin_alpha_snapshot_before_explicit.json"
with open(snapshot_path, "r", encoding="utf-8") as f:
    before = json.load(f)

loaded = load_system_strategies()
candidates = loaded["candidates"]
target_ids = ["kema_long", "kema_short", "sideway_long", "sideway_short"]

all_matched = True
print("=== VERIFYING EFFECTIVE POSITIONS MATCH SNAPSHOT 0.1 ===")
for c in candidates:
    cid = c["id"]
    if cid in target_ids:
        raw_pos = c.get("position", {})
        tf = "4h" if "kema" in cid else "1h"
        effective_after = resolve_position_auto({**BASE_POSITION, **NORA_DEFAULTS, **raw_pos}, tf)
        effective_before = before[cid]["effective_resolved"]

        # Check key by key
        diffs = []
        all_keys = sorted(set(effective_before.keys()) | set(effective_after.keys()))
        for k in all_keys:
            val_b = effective_before.get(k)
            val_a = effective_after.get(k)
            if val_b != val_a:
                diffs.append((k, val_b, val_a))

        print(f"\nCandidate: {cid}")
        print(f"  Explicit in code: {raw_pos}")
        if diffs:
            all_matched = False
            print(f"  FAILED: {len(diffs)} differences found with snapshot!")
            for k, vb, va in diffs:
                print(f"    Key '{k}': before={vb} != after={va}")
        else:
            print(f"  SUCCESS: 100% MATCH across all {len(all_keys)} effective position keys!")

if not all_matched:
    print("\nFAIL: Mismatch with snapshot! Halting as per plan condition 1.1/1.2.")
    sys.exit(1)
else:
    print("\nRESULT: PASS — Effective positions after explicit declaration are 100% IDENTICAL to snapshot!")
