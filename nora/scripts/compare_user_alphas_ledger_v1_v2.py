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

print("=== SO SÁNH LEDGER THỰC THI V1 (SL %) vs V2 (SL ATR) ===")

def run_sim(aid, code, pos_override):
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
    return NautilusRun(
        books=[book], initial_capital=10_000.0, risk=risk, trade_start_ts=0,
        end_ts=n_bars * base_ms, base_frame="24h", close_at_end=True, data=ds, execution_target="next_open"
    ).run()["positions"]

for aid in ["18e87aa868ad", "33312a2f4dfc"]:
    # V1 (từ code v1: exit_unit='pct', SL=2.5% giá)
    with open(f"/home/vmc03/norabt/nora/coin/data/alpha/user/{aid}.json") as f:
        d1 = json.load(f)
    trades_v1 = run_sim(aid, d1["code"], compile_code(d1["code"]).position_overrides)
    
    # V2 (từ code v2: exit_unit='atr', SL=2.5x ATR)
    with open(f"/home/vmc03/norabt/nora/coin/data/alpha/user/{aid}_v2.json") as f:
        d2 = json.load(f)
    trades_v2 = run_sim(f"{aid}_v2", d2["code"], compile_code(d2["code"]).position_overrides)
    
    print(f"\n[{aid}]:")
    print(f"  V1 (SL 2.5% giá): {len(trades_v1)} trades, PnL tổng = {sum(t.real_pnl for t in trades_v1):.2f} USD")
    print(f"  V2 (SL 2.5x ATR): {len(trades_v2)} trades, PnL tổng = {sum(t.real_pnl for t in trades_v2):.2f} USD")
    print(f"  Số lệnh SL kích hoạt: V1 = {sum(1 for t in trades_v1 if t.status.name == 'SL')}, V2 = {sum(1 for t in trades_v2 if t.status.name == 'SL')}")
