import json
from pathlib import Path

user_dir = Path("nora/edu/data/alpha/user")
files = sorted(user_dir.glob("*.json"))

with_res = []
without_res = []

for p in files:
    rec = json.loads(p.read_text(encoding="utf-8"))
    aid = p.stem
    name = rec.get("name", "Unknown")
    owner = rec.get("owner_id", "NoOwner")
    status = rec.get("metrics_status", "None")
    if rec.get("result"):
        with_res.append((aid, name, owner))
    else:
        without_res.append((aid, name, owner, status))

print(f"=== WITH ACTIVE RESULT ({len(with_res)}) ===")
for r in with_res[:5]:
    print(f"  {r[0]} | {r[1]} | owner={r[2]}")

print(f"\n=== WITHOUT ACTIVE RESULT ({len(without_res)}) ===")
for r in without_res:
    print(f"  {r[0]} | {r[1]} | owner={r[2]} | status={r[3]}")
