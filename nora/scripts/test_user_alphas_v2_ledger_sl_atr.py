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

# Fixture 365 nến daily từ compare_user_alphas_v1_v2.py
n_bars = 365
base_ms = 86_400_000
open_time = np.arange(n_bars, dtype=np.int64) * base_ms

np.random.seed(42)
trend = np.linspace(20000, 45000, n_bars)
noise = np.random.normal(0, 500, n_bars)
c = trend + noise + 2000 * np.sin(np.linspace(0, 4 * np.pi, n_bars))
# Tạo 1 đợt sập giá mạnh ở bar 100-130 để kích hoạt SL
for m in range(100, 130):
    c[m] = c[99] - (m - 99) * 400.0

o = c + np.random.normal(0, 50, n_bars)
h = np.maximum(o, c) + np.abs(np.random.normal(300, 100, n_bars))
l = np.minimum(o, c) - np.abs(np.random.normal(300, 100, n_bars))
v = np.random.uniform(1000, 5000, n_bars)

symbol = "BTC-USDT-SWAP"
ds = SimpleStubDataSource(symbol, "24h", open_time.tolist(), o.tolist(), h.tolist(), l.tolist(), c.tolist(), v.tolist())
df = pd.DataFrame({"open_time": open_time, "open": o, "high": h, "low": l, "close": c, "volume": v})

print("=== KIỂM TRA LEDGER THOÁT LỆNH THẬT SỰ CHO 3 ALPHA V2 (SL ATR) ===")

v2_alphas = ["efa90f74cd08_v2", "18e87aa868ad_v2", "33312a2f4dfc_v2"]

for aid in v2_alphas:
    v2_path = f"/home/vmc03/norabt/nora/coin/data/alpha/user/{aid}.json"
    with open(v2_path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    prog = compile_code(doc["code"])
    
    n, data = prog._data(df)
    ctx = Ctx(n, data)
    signals = [np.asarray(call[0].ev(ctx), dtype=bool) for call in prog.calls]
    entry_mask = signals[1]
    stop_mask = signals[0]
    
    pos_config = prog.position_overrides
    flow = {"type": "LONG", "match": [], "stop": []}
    params_obj = build_params(aid, flow, "LONG", pos_config, "cex")
    
    slot = SlotSpec(
        account_id=0, campaign_id=0, symbol=symbol, flow_name=aid,
        params=params_obj, pos_type=PositionType.LONG, initial_capital=10_000.0
    )
    # Tính ATR14 làm chuỗi volatility cho risk-based position sizing
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    atr14 = np.asarray(pd.Series(list(tr)).rolling(14, min_periods=1).mean().values)

    book = {
        "symbol": symbol,
        "data": {"t": np.array(open_time, dtype=np.int64)},
        "entries": [{
            "strategy": aid,
            "slot": slot,
            "match": entry_mask,
            "stop": stop_mask,
            "vol": atr14,
        }]
    }
    risk = RiskConfig(max_positions=2, max_per_symbol=1, max_gross_exposure=3.0, kill_switch_dd_pct=50.0)
    res = NautilusRun(
        books=[book], initial_capital=10_000.0, risk=risk, trade_start_ts=0,
        end_ts=n_bars * base_ms, base_frame="24h", close_at_end=True, data=ds, execution_target="next_open"
    ).run()
    
    trades = res.get("positions", [])
    print(f"\n[{aid}] SL ATR = {pos_config.get('stop_loss_rate')}x ATR, cooldown = {pos_config.get('cooldown')}m:")
    print(f"  Tổng số lệnh closed trades: {len(trades)}")
    for idx, tr in enumerate(trades):
        print(f"    Trade #{idx+1}: enter_bar={tr.enter_time // base_ms}, close_bar={tr.close_time // base_ms}, enter_px={tr.enter_price:.1f}, close_px={tr.close_price:.1f}, qty={tr.qty:.4f}, pnl={tr.real_pnl:.1f}, status={tr.status.name}")
