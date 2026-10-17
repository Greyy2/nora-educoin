import time
from backend.jobs.tasks import run_custom

import json
with open("data/alpha/education/samples.json") as f:
    samples = json.load(f)
kema_sample = next(x for x in samples if x["key"] == "trend_kema_breakout")
code = kema_sample["code"]

# 1. Quick (24h)
t0 = time.time()
r_fast = run_custom({
    "code": code,
    "symbols": ["BTC"],
    "start": "2024-01-01",
    "end": "2025-01-01",
    "run_frame": "24h",
})
t_fast = time.time() - t0
print(f"KEMA Quick (24h): {t_fast:.2f}s, trades: {len(r_fast['trades'])}")

# 2. Standard (1m)
t0 = time.time()
r_std = run_custom({
    "code": code,
    "symbols": ["BTC"],
    "start": "2024-01-01",
    "end": "2025-01-01",
    "run_frame": "1m",
})
t_std = time.time() - t0
print(f"KEMA Standard (1m): {t_std:.2f}s, trades: {len(r_std['trades'])}")
