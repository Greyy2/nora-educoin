import json
from pathlib import Path

user_dir = Path("nora/edu/data/alpha/user")
files = sorted(user_dir.glob("*.json"))

total = len(files)
with_result = 0
without_result = 0
with_metrics_snapshot = 0
card_has_metrics_no_result = 0
mismatch_list = []

for p in files:
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error reading {p}: {e}")
        continue

    alpha_id = rec.get("id")
    has_res = bool(rec.get("result"))
    has_metrics = bool((rec.get("metrics") or {}).get("simulate"))
    ch = rec.get("contract_history") or []
    has_snap = any(bool((item.get("result_snapshot") or {}).get("metrics")) for item in ch if isinstance(item, dict))

    if has_res:
        with_result += 1
    else:
        without_result += 1
        if has_metrics or has_snap:
            card_has_metrics_no_result += 1
            mismatch_list.append({
                "id": alpha_id,
                "name": rec.get("name"),
                "owner_id": rec.get("owner_id"),
                "status": rec.get("status"),
                "metrics_status": rec.get("metrics_status"),
                "has_metrics": has_metrics,
                "has_snapshot": has_snap,
            })

print(f"Total user alphas: {total}")
print(f"With result: {with_result}")
print(f"Without result: {without_result}")
print(f"Mismatches (card extracts metrics from history/metrics, but result is None): {card_has_metrics_no_result}")
if mismatch_list:
    print("\nSample mismatches:")
    for item in mismatch_list[:10]:
        print(f"  - {item['id']} ({item['name']}): metrics_status={item['metrics_status']}, has_metrics={item['has_metrics']}, has_snapshot={item['has_snapshot']}")
