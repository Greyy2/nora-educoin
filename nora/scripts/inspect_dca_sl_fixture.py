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

BASE_MS = 60_000
count = 420
open_time = np.arange(count, dtype=np.int64) * BASE_MS
minute = np.arange(count)
close = (
    100.0
    + minute * 0.01
    + 2.0 * np.sin(minute / 8.0)
    + np.where(minute % 70 >= 40, 3.0, 0.0)
)
for m in range(75, 115):
    close[m] = 101.9 - (m - 74) * 0.25

high = close + 0.35 + 0.15 * np.abs(np.sin(minute / 5.0))
low = close - 0.35 - 0.15 * np.abs(np.cos(minute / 7.0))
open_p = close - 0.08 * np.sin(minute / 4.0)
vol = 1000.0 + 200.0 * np.abs(np.sin(minute / 6.0))

symbol = "BTC-USDT-SWAP"
ds = SimpleStubDataSource(
    symbol, "1m", open_time.tolist(), open_p.tolist(), high.tolist(), low.tolist(), close.tolist(), vol.tolist()
)
candles = pd.DataFrame({
    "open_time": open_time,
    "open": open_p,
    "high": high,
    "low": low,
    "close": close,
    "volume": vol,
})

loaded = load_system_strategies()
cand = {c["id"]: c for c in loaded["candidates"]}["dca_long"]

p = schema_defaults(cand)
for k in list(p.keys()):
    if "tf" in k:
        p[k] = "1m"
p["atr_frame"] = "1m"
p["take_profit_rate"] = 5.0
p["dca_step_atr"] = 0.5
strat = materialize(cand, p, regime=False)
off = evaluate_signals(symbol, [strat], {"1m": candles}, "1m")
entry = off["entries"][0]

dca_mask = entry.get("dca")
dca_active_count = int(np.sum(dca_mask)) if dca_mask is not None else 0
print(f"Số lần mảng tín hiệu dca_gate / dca_trigger == True: {dca_active_count}")

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

orders = res.get("orders", [])
print(f"Tổng số orders sinh ra trong backtest: {len(orders)}")
for idx, o in enumerate(orders):
    print(f"  Order #{idx+1}: action/type={getattr(o, 'order_type', type(o))}, side={getattr(o, 'side', '')}, qty={getattr(o, 'qty', '')}, price={getattr(o, 'price', '')}, status={getattr(o, 'status', '')}")

positions = res.get("positions", [])
for p_idx, pos in enumerate(positions):
    print(f"Position #{p_idx+1}:")
    print(f"  qty = {pos.qty}")
    print(f"  status = {pos.status.name}")
    print(f"  enter_time = {pos.enter_time}, close_time = {pos.close_time}")
    print(f"  enter_price = {pos.enter_price}, close_price = {pos.close_price}")
    print(f"  real_pnl = {pos.real_pnl}")
    # Inspect orders/fills inside position if any
    if hasattr(pos, "orders"):
        print(f"  pos.orders count = {len(pos.orders)}")
    if hasattr(pos, "fills"):
        print(f"  pos.fills count = {len(pos.fills)}")
        for f_idx, fill in enumerate(pos.fills):
            print(f"    Fill #{f_idx+1}: qty={getattr(fill, 'qty', fill)}, price={getattr(fill, 'price', fill)}")
