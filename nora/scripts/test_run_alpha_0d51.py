#!/usr/bin/env python3
import os
import sys
import json
import time
from pathlib import Path

ROOT = Path("/home/vmc03/norabt").resolve()
sys.path.insert(0, str(ROOT / "nora/edu"))
os.environ["NORA_DATA_ROOT"] = str(ROOT / "nora/edu/data")

from backend.jobs.tasks import run_custom

parent_json = json.loads((ROOT / "nora/edu/data/alpha/user/0d51ba8d2012.json").read_text(encoding="utf-8"))
code = parent_json["code"]
cfg = parent_json["config"]

params = {
    "code": code,
    "symbols": cfg.get("symbols", ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "TRX"]),
    "start": cfg.get("start", "2023-10-06"),
    "end": cfg.get("end", "2026-10-03"),
    "run_frame": cfg.get("run_frame", "24h"),
    "train_ratio": 0.7,
    "initial_capital": 10000.0,
    "position": cfg.get("position", {})
}

print("Running backtest for parent 0d51ba8d2012...")
t0 = time.time()
res = run_custom(params)
elapsed = time.time() - t0
print(f"Done in {elapsed:.2f}s")
metrics = res.get("metrics", {})
sim = metrics.get("simulate", {})
test = metrics.get("test", {})
print("Simulate (Full):", sim.get("ret_pct"), "% | trades:", sim.get("trades"), "| fees:", sim.get("fees_usd"))
print("Test (OOS):", test.get("ret_pct"), "% | trades:", test.get("trades"), "| fees:", test.get("fees_usd"), "| pf:", test.get("profit_factor_trades"))
