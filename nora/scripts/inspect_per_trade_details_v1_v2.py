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
from backend.analys.param import build_params
from backend.analys.position import SlotSpec
from backend.models.models import PositionType
from backend.core.backtest import NautilusRun
from backend.analys.alpha import RiskConfig
from tests.test_execution_realism_fixtures import SimpleStubDataSource

# Fixture 365 nến daily
n_bars = 365
base_ms = 86_400_000
open_time = np.arange(n_bars, dtype=np.int64) * base_ms

np.random.seed(42)
trend = np.linspace(20000, 45000, n_bars)
noise = np.random.normal(0, 500, n_bars)
c = trend + noise + 2000 * np.sin(np.linspace(0, 4 * np.pi, n_bars))
for m in range(100, 130):
    c[m] = c[99] - (m - 99) * 400.0

o = c + np.random.normal(0, 50, n_bars)
h = np.maximum(o, c) + np.abs(np.random.normal(300, 100, n_bars))
l = np.minimum(o, c) - np.abs(np.random.normal(300, 100, n_bars))
v = np.random.uniform(1000, 5000, n_bars)

tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
tr[0] = h[0] - l[0]
atr14 = pd.Series(tr).rolling(14, min_periods=1).mean().to_numpy()

symbol = "BTC-USDT-SWAP"
ds = SimpleStubDataSource(symbol, "24h", open_time.tolist(), o.tolist(), h.tolist(), l.tolist(), c.tolist(), v.tolist())
df = pd.DataFrame({"open_time": open_time, "open": o, "high": h, "low": l, "close": c, "volume": v})

def run_simulation_detailed(aid, code, pos_override, label):
    prog = compile_code(code)
    n, data = prog._data(df)
    ctx = Ctx(n, data)
    signals = [np.asarray(call[0].ev(ctx), dtype=bool) for call in prog.calls]
    entry_mask = signals[1]
    stop_mask = signals[0]
    
    flow = {"type": "LONG", "match": [], "stop": []}
    params_obj = build_params(aid, flow, "LONG", pos_override, "cex")
    slot = SlotSpec(
        account_id=0, campaign_id=0, symbol=symbol, flow_name=aid,
        params=params_obj, pos_type=PositionType.LONG, initial_capital=10_000.0
    )
    book = {
        "symbol": symbol,
        "data": {"t": np.array(open_time, dtype=np.int64)},
        "entries": [{"strategy": aid, "slot": slot, "match": entry_mask, "stop": stop_mask, "vol": atr14}]
    }
    risk = RiskConfig(max_positions=2, max_per_symbol=1, max_gross_exposure=3.0, kill_switch_dd_pct=50.0)
    res = NautilusRun(
        books=[book], initial_capital=10_000.0, risk=risk, trade_start_ts=0,
        end_ts=n_bars * base_ms, base_frame="24h", close_at_end=True, data=ds, execution_target="next_open"
    ).run()
    
    positions = res.get("positions", [])
    print(f"\n========================================================")
    print(f"Chi tiết giao dịch: {aid} ({label})")
    print(f"Tổng số lệnh: {len(positions)} | Sizing method: {pos_override.get('sizing', 'risk')} | Risk per trade: {pos_override.get('risk_per_trade_pct')}%")
    print(f"SL Rate: {pos_override.get('stop_loss_rate')} ({pos_override.get('exit_unit')})")
    print(f"{'#':<3} {'Enter':<6} {'Close':<6} {'Enter Px':<10} {'Close Px':<10} {'Qty':<8} {'PnL (USDT)':<12} {'Status':<8}")
    print("-" * 75)
    for idx, p in enumerate(positions):
        en_bar = p.enter_time // base_ms
        cl_bar = p.close_time // base_ms
        print(f"{idx+1:<3} {en_bar:<6} {cl_bar:<6} {p.enter_price:<10.1f} {p.close_price:<10.1f} {p.qty:<8.4f} {p.real_pnl:<12.2f} {p.status.name:<8}")

# Chạy cho 18e87aa868ad V1 và V2
with open("nora/coin/data/alpha/user/18e87aa868ad.json") as f:
    d1 = json.load(f)
pos1 = compile_code(d1["code"]).position_overrides
run_simulation_detailed("18e87aa868ad_v1", d1["code"], pos1, "V1 - SL 2.5% Giá")

with open("nora/coin/data/alpha/user/18e87aa868ad_v2.json") as f:
    d2 = json.load(f)
pos2 = compile_code(d2["code"]).position_overrides
run_simulation_detailed("18e87aa868ad_v2", d2["code"], pos2, "V2 - SL 2.5x ATR")
