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

print("1. Chạy run_benchmark gốc bằng Nautilus Engine:")
t0 = time.time()
res_nautilus = run_benchmark(program, type("Opts", (), {"position": None})(), plan, symbols, start, end, capital, {"source": "okx"})
t_nautilus = time.time() - t0
print(f"   -> Nautilus run_benchmark mất: {t_nautilus:.2f}s")
print(f"   -> Điểm đầu: {res_nautilus['equity'][0]}, Điểm cuối: {res_nautilus['equity'][-1]}")

print("\n2. Vectorized Benchmark bằng NumPy:")
t1 = time.time()
# Tính vectorized
weights = 1.0 / len(symbols)
fee_rate = 0.0005
curves = []
times = None

for sym in symbols:
    df = data.load_candles(sym, "1h")
    # Lọc theo start, end
    mask = (df["open_time"] >= start) & (df["open_time"] <= end)
    df_window = df[mask]
    if times is None:
        times = df_window["open_time"].to_numpy()
    c = df_window["close"].to_numpy(dtype=float)
    o0 = df_window["open"].iloc[0]
    pnl_ratio = (c - o0) / o0
    curves.append(pnl_ratio)

portfolio_ret = np.mean(curves, axis=0)
vec_equity = capital * (1.0 - fee_rate) * (1.0 + portfolio_ret)
t_vec = time.time() - t1
print(f"   -> Vectorized benchmark mất: {t_vec:.4f}s ({t_nautilus / t_vec:.0f}x nhanh hơn!)")
print(f"   -> Điểm đầu: {vec_equity[0]:.2f}, Điểm cuối: {vec_equity[-1]:.2f}")
