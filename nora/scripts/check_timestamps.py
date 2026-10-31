import sys
from pathlib import Path

EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")
sys.path.insert(0, str(EDU_ROOT))

from backend.data import data

btc = data.load_candles("BTC-USDT", "1h")
print("BTC 1h time column or index:")
if "time" in btc.columns:
    print(f"  time: {btc['time'].iloc[0]} -> {btc['time'].iloc[-1]}")
if "timestamp" in btc.columns:
    print(f"  timestamp: {btc['timestamp'].iloc[0]} -> {btc['timestamp'].iloc[-1]}")
if "open_time" in btc.columns:
    print(f"  open_time: {btc['open_time'].iloc[0]} -> {btc['open_time'].iloc[-1]}")
print("Columns:", list(btc.columns))
