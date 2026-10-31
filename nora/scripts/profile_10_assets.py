import sys, time
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

print(f"=== BẮT ĐẦU PROFILING 10 ASSETS (2024 - 2026, 1h) ===")
t0 = time.time()
res = run_custom(params)
total = time.time() - t0
print(f"=== TỔNG THỜI GIAN: {total:.2f}s ===")
print("Provenance / timing:", res.get("diagnostics", {}).get("timing") or res.get("provenance"))
