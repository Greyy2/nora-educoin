import sys, time
from pathlib import Path
import numpy as np

EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")
sys.path.insert(0, str(EDU_ROOT))

from backend.data import data
from backend.jobs.runner.backtest import run_benchmark
from backend.jobs.tasks import date_ms, DAY
from backend.analys.alpha.code.compile import compile_code
from backend.analys.alpha.code.plan import build_plan

code = """class DemoStrat(NoraStrategy):
    timeframe = "1h"
    def on_bar(self):
        self.buy(close > open)
        self.close(close < open)
"""
program = compile_code(code)
symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
plan = build_plan(program, symbols, run_frame="1h")

start, end = date_ms("2024-01-01"), date_ms("2024-06-01") + DAY
capital = 10000.0

res_nautilus = run_benchmark(program, type("Opts", (), {"position": None})(), plan, symbols, start, end, capital, {"source": "okx"})

print(f"Nautilus series length: {len(res_nautilus['equity'])}")
print(f"First 5 nautilus equity: {res_nautilus['equity'][:5]}")
print(f"Last 5 nautilus equity: {res_nautilus['equity'][-5:]}")
