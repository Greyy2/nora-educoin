import time
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
import numpy as np

lo = 0
hi = 24000  # 1 asset ~24k bars 1h
o = np.random.uniform(50000, 60000, hi)
t = np.arange(1700000000000, 1700000000000 + hi * 3600000, 3600000, dtype=np.int64)

rate = Decimal("0.0")
increment = Decimal("0.1")

t0 = time.time()
ticks = []
for idx in range(lo, hi):
    mid = Decimal(str(float(o[idx])))
    bid = (mid * (Decimal(1) - rate) / increment).to_integral_value(rounding=ROUND_FLOOR) * increment
    ask = (mid * (Decimal(1) + rate) / increment).to_integral_value(rounding=ROUND_CEILING) * increment
    ts = int(t[idx]) * 1000000 + 2
    # simulate QuoteTick creation
dur = time.time() - t0
print(f"1 asset (24k bars) Python Decimal loop took: {dur:.3f}s")
print(f"10 assets * 4 runs (main, test, bench, test_bench) = 40 times = {dur * 40:.2f}s!")
