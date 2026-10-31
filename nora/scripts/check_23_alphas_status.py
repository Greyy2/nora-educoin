#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path("/home/vmc03/norabt").resolve()
CHECK_DIR = ROOT / "nora/check"

with open(CHECK_DIR / "edu_evolution_charter_manifest.json", "r") as f:
    charter = json.load(f)
queue = charter["investigation_queue"]

with open(CHECK_DIR / "edu_alpha_baseline_results.json", "r") as f:
    base = json.load(f)["baseline_runs"]

with open(CHECK_DIR / "edu_evolution_cost_attribution.json", "r") as f:
    cost = json.load(f)["alphas"]

print(f"Total alphas in queue: {len(queue)}")
for item in queue:
    aid = item["aid"]
    b = base.get(aid, {})
    c = cost.get(aid, {})
    print(f"{aid}: {b.get('name')} | OOS trades: {b.get('oos_trades')} | Full trades: {b.get('trades')} | OOS ret: {b.get('oos_ret')}% | Class: {c.get('classification')}")
