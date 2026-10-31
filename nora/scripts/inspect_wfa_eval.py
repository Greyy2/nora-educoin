import json
from pathlib import Path

ROOT = Path("/home/vmc03/norabt").resolve()
with open(ROOT / "nora/check/edu_evolution_wfa_results.json") as f:
    wfa = json.load(f)

for aid, info in sorted(wfa.get("candidates_evaluated", {}).items()):
    best = info.get("best_variant") or {}
    print(f"{aid} | {info.get('name')[:30]} | disp={info.get('disposition')} | verdict={info.get('overall_verdict')} | best={best.get('candidate_id')} avg_ret={best.get('avg_return_pct')}% max_mdd={best.get('max_mdd_pct')}%")
