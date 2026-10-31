import os
import sys
import numpy as np
import pandas as pd

COIN_ROOT = "/home/vmc03/norabt/nora/coin"
sys.path.insert(0, COIN_ROOT)
os.environ["NORA_DIR"] = COIN_ROOT
os.environ["NORA_LOCAL_DATA_ROOT"] = f"{COIN_ROOT}/data"

from backend.analys.alpha.strategies import BY_ID
from backend.analys.param import schema_defaults, materialize, build_params
from backend.analys.signal.compute import evaluate_signals
from backend.models.models import PositionType
from backend.analys.position import SlotSpec
from backend.core.backtest import NautilusRun
from backend.analys.alpha import RiskConfig
from tests.test_execution_realism_fixtures import SimpleStubDataSource

n_bars = 50
base_ms = 86_400_000 # 24h
open_time = np.arange(n_bars, dtype=np.int64) * base_ms

c = np.linspace(25000, 30000, n_bars)
o = c - 50
h = c + 100
l = c - 100
v = np.full(n_bars, 1000.0)
atr14 = np.full(n_bars, 500.0)

symbol = "BTC-USDT-SWAP"
ds = SimpleStubDataSource(symbol, "24h", open_time.tolist(), o.tolist(), h.tolist(), l.tolist(), c.tolist(), v.tolist(), lot_sz="0.001")

# Lấy candidate kema_long
candidate = BY_ID["kema_long"]
params = schema_defaults(candidate)
strategy = materialize(candidate, params, regime=False)

print("strategy['position']:", strategy["position"])

# Tạo slot params từ build_params
flow = {"type": "LONG", "match": [], "stop": []}
params_obj = build_params("kema_long", flow, "LONG", strategy["position"], "cex")
slot = SlotSpec(account_id=0, campaign_id=0, symbol=symbol, flow_name="kema_long", params=params_obj, pos_type=PositionType.LONG, initial_capital=10_000.0)

# Match ở bar 5, 15, 25
match_mask = np.zeros(n_bars, dtype=bool)
match_mask[5] = True
match_mask[15] = True
stop_mask = np.zeros(n_bars, dtype=bool)
stop_mask[10] = True
stop_mask[20] = True

book = {
    "symbol": symbol,
    "data": {"t": np.array(open_time, dtype=np.int64)},
    "entries": [{"strategy": "kema_long", "slot": slot, "match": match_mask, "stop": stop_mask, "vol": atr14}]
}
risk = RiskConfig(max_positions=2, max_per_symbol=1, max_gross_exposure=3.0, kill_switch_dd_pct=50.0)
runner = NautilusRun(books=[book], initial_capital=10_000.0, risk=risk, trade_start_ts=0, end_ts=n_bars * base_ms, base_frame="24h", close_at_end=True, data=ds, execution_target="next_open")
res = runner.run()

print("Positions:", len(res["positions"]))
for p in res["positions"]:
    en_bar = p.enter_time // base_ms
    cl_bar = p.close_time // base_ms
    print(f"Pos: enter={en_bar} cl={cl_bar} px={p.enter_price:.1f} qty={p.qty:.4f} pnl={p.real_pnl:.2f} status={p.status.name}")

orders = res["orders"]
print("Orders:", len(orders))
for o in orders:
    print(f"Order: type={o.order_type.name} t={o.order_time // base_ms} px={o.order_price:.1f} qty={o.qty:.4f}")
