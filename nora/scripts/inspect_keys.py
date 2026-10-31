import json
from pathlib import Path

p = Path("nora/edu/data/alpha/user/026f43441cb2.json")
d = json.loads(p.read_text(encoding="utf-8"))

print("Top keys in 026f43441cb2.json:")
for k in d.keys():
    if k in ("code", "contract_history", "result"):
        print(f"  {k}: <len={len(str(d[k]))}>")
    else:
        print(f"  {k}: {type(d[k]).__name__} = {d[k] if not isinstance(d[k], (dict, list)) else f'len={len(d[k])}'}")

print("\nMetrics keys:")
print(list(d.get("metrics", {}).keys()) if d.get("metrics") else "None")

print("\nResult keys:")
print(list(d.get("result", {}).keys()) if d.get("result") else "None")

if d.get("result", {}).get("metrics"):
    print("\nResult['metrics'] keys:")
    print(list(d["result"]["metrics"].keys()))
