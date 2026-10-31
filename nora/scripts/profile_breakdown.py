import sys, time, cProfile, pstats
from pathlib import Path

EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")
sys.path.insert(0, str(EDU_ROOT))

from backend.jobs.tasks import run_custom

code = """class DemoStrat(NoraStrategy):
    timeframe = "1h"
    def on_bar(self):
        rsi = self.feat.rsi(close, 14)
        self.buy(rsi < 30)
        self.close(rsi > 70)
"""

symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT",
           "DOGE-USDT", "ADA-USDT", "AVAX-USDT", "LINK-USDT", "TRX-USDT"]

params = {
    "code": code,
    "symbols": symbols,
    "start": "2024-01-01",
    "end": "2026-09-01",
    "train_ratio": 0.8,
    "initial_capital": 10000.0,
    "run_frame": "1h",
}

profiler = cProfile.Profile()
profiler.enable()
res = run_custom(params)
profiler.disable()

stats = pstats.Stats(profiler).sort_stats("cumulative")
print("\n--- TOP 30 CUMULATIVE TIME ---")
stats.print_stats(30)
