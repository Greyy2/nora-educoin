import json
from pathlib import Path
from collections import Counter

user_dir = Path("nora/edu/data/alpha/user")
alphas = list(user_dir.glob("*.json"))

owner_cnt = Counter()
missing_cnt = 0
alphas_info = []

for p in alphas:
    d = json.loads(p.read_text(encoding="utf-8"))
    oid = d.get("owner_id")
    m = d.get("metrics") or {}
    has_m = bool(m and m.get("return_pct") is not None)
    owner_cnt[oid] += 1
    if not has_m:
        missing_cnt += 1
    alphas_info.append({
        "id": p.stem,
        "name": d.get("name"),
        "owner_id": oid,
        "has_metrics": has_m,
        "status": d.get("backtest_status"),
        "symbols": d.get("config", {}).get("symbols", ["BTC-USDT"]),
        "timeframe": d.get("config", {}).get("run_frame") or d.get("config", {}).get("timeframe", "1h"),
    })

print(f"Total: {len(alphas)}, Missing metrics: {missing_cnt}")
print(f"Distinct owner_ids ({len(owner_cnt)}):")
for o, count in sorted(owner_cnt.items(), key=lambda x: str(x[0])):
    user_alphas = [a for a in alphas_info if a["owner_id"] == o]
    with_m = [a for a in user_alphas if a["has_metrics"]]
    print(f"  {str(o):30s}: {count:2d} alphas (with_metrics={len(with_m)}, missing={count-len(with_m)})")

print("\nSample missing alphas:")
missing_alphas = [a for a in alphas_info if not a["has_metrics"]]
for a in missing_alphas[:10]:
    print(f"  {a['id']} | owner={a['owner_id']} | name={a['name']} | status={a['status']}")
