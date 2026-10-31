import sys
from pathlib import Path

EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")
sys.path.insert(0, str(EDU_ROOT))

from backend.data import data

print("Data paths & symbols:")
try:
    btc_1h = data.load_candles("BTC-USDT", "1h")
    print(f"BTC-USDT 1h: shape={btc_1h.shape}, index range: {btc_1h.index[0]} -> {btc_1h.index[-1]}")
except Exception as e:
    print(f"Error BTC 1h: {e}")

try:
    eth_15m = data.load_candles("ETH-USDT", "15m")
    print(f"ETH-USDT 15m: shape={eth_15m.shape}, index range: {eth_15m.index[0]} -> {eth_15m.index[-1]}")
except Exception as e:
    print(f"Error ETH 15m: {e}")
