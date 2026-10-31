import os
import sys
import json
import numpy as np
import pandas as pd

sys.path.insert(0, "/home/vmc03/norabt/nora/coin")
os.environ["NORA_DIR"] = "/home/vmc03/norabt/nora/coin"
os.environ["NORA_LOCAL_DATA_ROOT"] = "/home/vmc03/norabt/nora/coin/data"

from backend.analys.alpha.code.compile import compile_code
from backend.analys.signal.signal import Ctx

# Tạo fixture 365 nến daily (24h)
n_bars = 365
base_ts = 1672531200000  # 2023-01-01
t = base_ts + np.arange(n_bars, dtype=np.int64) * 86_400_000

np.random.seed(42)
trend = np.linspace(20000, 45000, n_bars)
noise = np.random.normal(0, 500, n_bars)
c = trend + noise + 2000 * np.sin(np.linspace(0, 4 * np.pi, n_bars))
h = c + np.abs(np.random.normal(300, 150, n_bars))
l = c - np.abs(np.random.normal(300, 150, n_bars))
o = c + np.random.normal(0, 100, n_bars)
v = np.random.uniform(1000, 5000, n_bars)

df = pd.DataFrame({
    "open_time": t,
    "open": o,
    "high": h,
    "low": l,
    "close": c,
    "volume": v,
})

user_alphas = ["efa90f74cd08", "18e87aa868ad", "33312a2f4dfc"]

print("=== ĐỐI SOÁT TÍN HIỆU V1 vs V2 TRÊN FIXTURE 365 NẾN DAILY ===")

for aid in user_alphas:
    v1_path = f"/home/vmc03/norabt/nora/coin/data/alpha/user/{aid}.json"
    with open(v1_path, "r", encoding="utf-8") as f:
        d1 = json.load(f)
    code_v1 = d1["code"]
    prog_v1 = compile_code(code_v1)
    
    v2_path = f"/home/vmc03/norabt/nora/coin/data/alpha/user/{aid}_v2.json"
    with open(v2_path, "r", encoding="utf-8") as f:
        d2 = json.load(f)
    code_v2 = d2["code"]
    prog_v2 = compile_code(code_v2)
    
    # Tính tín hiệu v1
    n1, data1 = prog_v1._data(df)
    ctx1 = Ctx(n1, data1)
    # prog.calls: list of (node, weight, action)
    v1_signals = [np.asarray(call[0].ev(ctx1), dtype=bool) for call in prog_v1.calls]
    
    # Tính tín hiệu v2
    n2, data2 = prog_v2._data(df)
    ctx2 = Ctx(n2, data2)
    v2_signals = [np.asarray(call[0].ev(ctx2), dtype=bool) for call in prog_v2.calls]
    
    match_count = 0
    total_calls = len(prog_v1.calls)
    for idx in range(total_calls):
        if np.array_equal(v1_signals[idx], v2_signals[idx]):
            match_count += 1
            
    all_identical = (match_count == total_calls)
    
    v1_active_bars = [int(np.sum(s)) for s in v1_signals]
    v2_active_bars = [int(np.sum(s)) for s in v2_signals]
    
    print(f"\n[{aid}] {d1['name']}:")
    print(f"  Số luật tín hiệu (calls): {total_calls}")
    print(f"  Số bar kích hoạt v1: {v1_active_bars}")
    print(f"  Số bar kích hoạt v2: {v2_active_bars}")
    print(f"  Tín hiệu thô (Entry & Signal Exit) trùng khớp bit-for-bit: {all_identical}")
    print(f"  Khác biệt vị thế (Position Parameters):")
    print(f"    - Code v1 suy ra: {prog_v1.position_overrides.get('exit_unit')} (SL={prog_v1.position_overrides.get('stop_loss_rate')})")
    print(f"    - Code v2 khai báo: {prog_v2.position_overrides.get('exit_unit')} (SL={prog_v2.position_overrides.get('stop_loss_rate')}, cooldown={prog_v2.position_overrides.get('cooldown')}m)")
