"""Test chạy backtest thử nghiệm 1 alpha fixture: 026f43441cb2"""
import sys, json
from pathlib import Path

EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")
sys.path.insert(0, str(EDU_ROOT))

from backend.jobs.tasks import run_custom

alpha_file = EDU_ROOT / "data" / "alpha" / "user" / "026f43441cb2.json"
data = json.loads(alpha_file.read_text(encoding="utf-8"))

print(f"Alpha ID: {data['id']}")
print(f"Name: {data['name']}")
print(f"Timeframe: {data['config'].get('timeframe')}")

params = {
    "code": data["code"],
    "symbols": data["config"].get("symbols", ["BTC-USDT"]),
    "start": "2024-01-01",
    "end": "2026-09-01",
    "train_ratio": 0.8,
    "initial_capital": 10000.0,
    "run_frame": data["config"].get("run_frame", ""),
}

print("Bắt đầu chạy run_custom...")
res = run_custom(params)
sim = res.get("metrics", {}).get("simulate", {})
print("KẾT QUẢ RUN_CUSTOM:")
print(f"  Trades: {sim.get('trades')}")
print(f"  Return: {sim.get('ret_pct')}%")
print(f"  MDD: {sim.get('mdd_pct')}%")
print(f"  Sharpe: {sim.get('sharpe')}")
print(f"  Final Equity: {res.get('final_equity')}")
