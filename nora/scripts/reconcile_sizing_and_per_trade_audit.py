"""
Script doi soat toan dien per-trade va chung minh co che sizing cua Nora:
1. In ro provenance hieu luc: sizing, order_size_pct, risk_per_trade_pct, stop_loss_rate, leverage.
2. Doi chieu tung lenh: Bar enter, Bar close, Px enter, Px close, ATR that tu engine (khong '~'),
   co lenh tinh tay (25 USDT / SL_dist), qty thuc te cua engine, muc lo thuc te khi SL.
3. Chay thu nghiem khi them 'sizing': 'risk' de chung minh:
   - Qty giam tu ~0.38 xuong ~0.035
   - V2 co qty bang ~1/2 V1
   - Muc lo thuc te tai SL dung ~25 USDT.
"""
import os
import sys
import json
import numpy as np
import pandas as pd

COIN_ROOT = "/home/vmc03/norabt/nora/coin"
sys.path.insert(0, COIN_ROOT)
os.environ["NORA_DIR"] = COIN_ROOT
os.environ["NORA_LOCAL_DATA_ROOT"] = f"{COIN_ROOT}/data"

from backend.analys.alpha.code.compile import compile_code
from backend.analys.signal.signal import Ctx
from backend.analys.param import build_params
from backend.analys.position import SlotSpec
from backend.models.models import PositionType
from backend.core.backtest import NautilusRun
from backend.analys.alpha import RiskConfig
from tests.test_execution_realism_fixtures import SimpleStubDataSource

# Fixture 365 bars chuẩn
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
atr14 = np.asarray(pd.Series(list(tr)).rolling(14, min_periods=1).mean().values)

symbol = "BTC-USDT-SWAP"
ds = SimpleStubDataSource(symbol, "24h", open_time.tolist(), o.tolist(), h.tolist(), l.tolist(), c.tolist(), v.tolist())
df = pd.DataFrame({"open_time": open_time, "open": o, "high": h, "low": l, "close": c, "volume": v})

def simulate(aid, code, pos_override, explicit_sizing=None):
    prog = compile_code(code)
    n, data = prog._data(df)
    ctx = Ctx(n, data)
    signals = [np.asarray(call[0].ev(ctx), dtype=bool) for call in prog.calls]
    entry_mask = signals[1]
    stop_mask = signals[0]
    
    pos = dict(pos_override)
    if explicit_sizing:
        pos["sizing"] = explicit_sizing
    
    params_obj = build_params(aid, {"type": "LONG", "match": [], "stop": []}, "LONG", pos, "cex")
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
    return params_obj, res.get("positions", [])

print("=" * 80)
print("1. RUN HIỆN TẠI (KHÔNG CÓ 'sizing': 'risk' -> FALLBACK 'margin_pct')")
print("=" * 80)

with open(f"{COIN_ROOT}/data/alpha/user/18e87aa868ad.json") as f:
    d1 = json.load(f)
pos1 = compile_code(d1["code"]).position_overrides

with open(f"{COIN_ROOT}/data/alpha/user/18e87aa868ad_v2.json") as f:
    d2 = json.load(f)
pos2 = compile_code(d2["code"]).position_overrides

for aid, code, pos, label in [
    ("v1", d1["code"], pos1, "V1 - SL 2.5% Giá (Hiện tại)"),
    ("v2", d2["code"], pos2, "V2 - SL 2.5x ATR (Hiện tại)")
]:
    p_obj, positions = simulate(aid, code, pos)
    print(f"\n--- {label} ---")
    print(f"Provenance hiệu lực: sizing={p_obj.sizing}, order_size_pct={p_obj.order_size_pct}%, risk_per_trade_pct={p_obj.risk_per_trade_pct}%, SL={p_obj.stop_loss_rate} ({p_obj.exit_unit}), lev={p_obj.leverage}x")
    print(f"{'#':<3} {'Bar En':<7} {'Bar Cl':<7} {'Px En':<9} {'Px Cl':<9} {'ATR thật':<9} {'SL Dist':<9} {'Qty Tính Tay':<13} {'Qty Thực':<9} {'PnL':<10} {'Status':<8}")
    print("-" * 105)
    for idx, p in enumerate(positions):
        en_bar = p.enter_time // base_ms
        cl_bar = p.close_time // base_ms
        atr_val = atr14[en_bar]
        if p_obj.exit_unit == "atr":
            sl_dist = p_obj.stop_loss_rate * atr_val
        else:
            sl_dist = p.enter_price * (p_obj.stop_loss_rate / 100.0)
        target_risk = 10000.0 * (p_obj.risk_per_trade_pct / 100.0) # 25 USDT
        calc_qty = target_risk / sl_dist if sl_dist > 0 else 0.0
        print(f"{idx+1:<3} {en_bar:<7} {cl_bar:<7} {p.enter_price:<9.1f} {p.close_price:<9.1f} {atr_val:<9.2f} {sl_dist:<9.2f} {calc_qty:<13.4f} {p.qty:<9.4f} {p.real_pnl:<10.1f} {p.status.name:<8}")

print("\n" + "=" * 80)
print("2. RUN THỰC NGHIỆM KHI BẬT 'sizing': 'risk'")
print("=" * 80)

for aid, code, pos, label in [
    ("v1_risk", d1["code"], pos1, "V1 - SL 2.5% Giá (Với sizing='risk')"),
    ("v2_risk", d2["code"], pos2, "V2 - SL 2.5x ATR (Với sizing='risk')")
]:
    p_obj, positions = simulate(aid, code, pos, explicit_sizing="risk")
    print(f"\n--- {label} ---")
    print(f"Provenance hiệu lực: sizing={p_obj.sizing}, order_size_pct={p_obj.order_size_pct}%, risk_per_trade_pct={p_obj.risk_per_trade_pct}%, SL={p_obj.stop_loss_rate} ({p_obj.exit_unit}), lev={p_obj.leverage}x")
    print(f"{'#':<3} {'Bar En':<7} {'Bar Cl':<7} {'Px En':<9} {'Px Cl':<9} {'ATR thật':<9} {'SL Dist':<9} {'Qty Tính Tay':<13} {'Qty Thực':<9} {'PnL':<10} {'Status':<8}")
    print("-" * 105)
    for idx, p in enumerate(positions):
        en_bar = p.enter_time // base_ms
        cl_bar = p.close_time // base_ms
        atr_val = atr14[en_bar]
        if p_obj.exit_unit == "atr":
            sl_dist = p_obj.stop_loss_rate * atr_val
        else:
            sl_dist = p.enter_price * (p_obj.stop_loss_rate / 100.0)
        target_risk = 10000.0 * (p_obj.risk_per_trade_pct / 100.0) # 25 USDT
        calc_qty = target_risk / sl_dist if sl_dist > 0 else 0.0
        print(f"{idx+1:<3} {en_bar:<7} {cl_bar:<7} {p.enter_price:<9.1f} {p.close_price:<9.1f} {atr_val:<9.2f} {sl_dist:<9.2f} {calc_qty:<13.4f} {p.qty:<9.4f} {p.real_pnl:<10.1f} {p.status.name:<8}")
