import json
from pathlib import Path

ROOT = Path("/home/vmc03/norabt").resolve()
CHECK_DIR = ROOT / "nora/check"
CACHE_DIR = ROOT / "nora/edu/data/cache/process/_mem"

with open(CHECK_DIR / "edu_alpha_baseline_results.json", "r") as f:
    base = json.load(f)["baseline_runs"]

for aid, info in sorted(base.items()):
    job_id = info.get("job_id")
    job_file = CACHE_DIR / f"{job_id}.json"
    oos_t = info.get("oos_trades")
    full_t = info.get("trades")
    oos_ret = info.get("oos_ret")
    cat = info.get("category")
    if job_file.exists():
        d = json.loads(job_file.read_text())
        m = d.get("result", {}).get("metrics", {})
        t_test = m.get("test", {}).get("trades")
        t_sim = m.get("simulate", {}).get("trades")
        ret_test = m.get("test", {}).get("ret_pct")
        print(f"{aid} | {info.get('name')[:30]} | oos_t={oos_t} (cache test={t_test}) | full_t={full_t} (cache sim={t_sim}) | oos_ret={oos_ret}% (cache={ret_test}%) | cat={cat}")
    else:
        print(f"{aid} | {info.get('name')[:30]} | oos_t={oos_t} | full_t={full_t} | NO CACHE FILE")
