import json
import hashlib
from pathlib import Path

user_dir = Path("nora/edu/data/alpha/user")
files = sorted(user_dir.glob("*.json"))

mismatches = []
for p in files:
    rec = json.loads(p.read_text(encoding="utf-8"))
    if not rec.get("result"):
        ch = rec.get("contract_history") or []
        snaps = [item.get("result_snapshot") for item in ch if isinstance(item, dict) and item.get("result_snapshot")]
        mismatches.append((p.stem, rec.get("name"), len(snaps), rec.get("metrics_status")))

print(f"Total without result: {len(mismatches)}")
for aid, name, snap_count, status in mismatches:
    print(f"{aid} | {name[:40]} | snaps={snap_count} | status={status}")
