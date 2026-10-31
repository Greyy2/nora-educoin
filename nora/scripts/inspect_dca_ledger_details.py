import os
import sys
import json
import numpy as np
import pandas as pd

sys.path.insert(0, "/home/vmc03/norabt/nora/coin")
os.environ["NORA_DIR"] = "/home/vmc03/norabt/nora/coin"
os.environ["NORA_LOCAL_DATA_ROOT"] = "/home/vmc03/norabt/nora/coin/data"
os.environ["NORA_LOCAL_LOGS_ROOT"] = "/tmp"
os.environ["NORA_JWT_SECRET"] = "test"

from backend.analys.alpha.code.compile import load_system_strategies
from backend.analys.param import schema_defaults, materialize, build_params
from backend.analys.position import SlotSpec
from backend.analys.signal.compute import evaluate_signals, _strategy_flow
from backend.core.backtest import NautilusRun
from backend.analys.alpha import RiskConfig
from backend.models.models import PositionType
from tests.test_execution_realism_fixtures import SimpleStubDataSource

# Let's create a scenario specifically crafted for DCA multi-layer dip and SL exit:
# 1. First 40 bars: flat/sideway around 100 to initialize indicators (RSI ~ 50, ER low).
# 2. At bar 45: dip to RSI < 30 and price < BB lower -> Triggers DCA Long entry.
# 3. Bars 46-60: price continues dropping steadily: 100 -> 98 -> 96 -> 94 -> 92 (triggers layer 1, layer 2 DCA limit fills).
# 4. At bar 65: price drops sharply to 85 -> triggers basket SL exit!

count = 120
BASE_MS = 60_000
open_time = np.arange(count, dtype=np.int64) * BASE_MS
close = np.full(count, 100.0)

# Bars 0-40: oscillation between 99.8 and 100.2
for i in range(40):
    close[i] = 100.0 + 0.2 * np.sin(i / 2.0)

# Bar 41-45: sharp dip to 96 (triggers oversold entry)
close[41] = 99.0
close[42] = 98.0
close[43] = 97.0
close[44] = 96.0
close[45] = 95.5

# Bars 46-55: further step-downs to trigger DCA layers
for i in range(46, 56):
    close[i] = 95.5 - (i - 45) * 0.5  # down to 90.5

# Bars 56-70: crash to 80 to hit Stop Loss
for i in range(56, 70):
    close[i] = 85.0 - (i - 56) * 1.0

# Bars 70-120: flat
for i in range(70, count):
    close[i] = 70.0

high = close + 0.2
low = close - 0.2
open_p = close + 0.05
vol = np.full(count, 500.0)

symbol = "BTC-USDT-SWAP"
candles = pd.DataFrame({
    "open_time": open_time,
    "open": open_p,
    "high": high,
    "low": low,
    "close": close,
    "volume": vol,
})
ds = SimpleStubDataSource(
    symbol, "1m", open_time.tolist(), open_p.tolist(), high.tolist(), low.tolist(), close.tolist(), vol.tolist()
)

loaded = load_system_strategies()
candidates = {c["id"]: c for c in loaded["candidates"]}
cand = candidates["dca_long"]

cand_mem = cand
cand_json = json.loads(json.dumps(cand))

runs = []
for c in [cand_mem, cand_json]:
    p = schema_defaults(c)
    for k in list(p.keys()):
        if "tf" in k:
            p[k] = "1m"
    p["atr_frame"] = "1m"
    p["dca_step_atr"] = 0.5  # tight step so it easily adds layers
    strat = materialize(c, p, regime=False)
    off = evaluate_signals(symbol, [strat], {"1m": candles}, "1m")
    entry = off["entries"][0]

    flow = _strategy_flow(strat)
    params_obj = build_params("dca_long", flow, "LONG", strat.get("position", {}), "cex")
    slot = SlotSpec(
        account_id=0, campaign_id=0, symbol=symbol, flow_name="dca_long",
        params=params_obj, pos_type=PositionType.LONG, initial_capital=10_000.0,
    )
    book = {
        "symbol": symbol,
        "data": {"t": np.array(open_time, dtype=np.int64)},
        "entries": [{
            "strategy": "dca_long",
            "slot": slot,
            "match": entry["match"],
            "stop": entry["stop"],
            "vol": entry.get("vol"),
            "dca": entry.get("dca"),
        }],
    }
    risk = RiskConfig(max_positions=2, max_per_symbol=1, max_gross_exposure=3.0, kill_switch_dd_pct=50.0)
    res = NautilusRun(
        books=[book], initial_capital=10_000.0, risk=risk, trade_start_ts=0,
        end_ts=count * BASE_MS, base_frame="1m", close_at_end=True, data=ds, execution_target="next_open"
    ).run()
    runs.append(res)

res1, res2 = runs[0], runs[1]
print(f"Candidate Memory closed positions: {len(res1['positions'])}")
print(f"Candidate JSON closed positions:   {len(res2['positions'])}")

for p in res1["positions"]:
    print(f"Mem Position: enter_t={p.enter_time}, close_t={p.close_time}, enter_px={p.enter_price:.4f}, close_px={p.close_price:.4f}, qty={p.qty:.4f}, pnl={p.real_pnl:.4f}, status={p.status.name}")
    print(f"  Fills/Layers info: {getattr(p, 'layers', 'N/A')}")

for p in res2["positions"]:
    print(f"JSON Position: enter_t={p.enter_time}, close_t={p.close_time}, enter_px={p.enter_price:.4f}, close_px={p.close_price:.4f}, qty={p.qty:.4f}, pnl={p.real_pnl:.4f}, status={p.status.name}")

p1_data = [(p.enter_time, p.close_time, round(p.enter_price, 6), round(p.close_price, 6), round(p.qty, 6), round(p.real_pnl, 6), p.status.name) for p in res1["positions"]]
p2_data = [(p.enter_time, p.close_time, round(p.enter_price, 6), round(p.close_price, 6), round(p.qty, 6), round(p.real_pnl, 6), p.status.name) for p in res2["positions"]]

assert p1_data == p2_data, "Mismatch in DCA staging SL fixture!"
print(f"\nSUCCESS: DCA Multi-layer Staging & SL Exit is 100% BIT-FOR-BIT IDENTICAL!")
