"""
Chay ledger thuc te cua kema_long tren NautilusRun de xac minh:
1. kema_long thuc su chay sizing='risk' hay 'margin_pct'?
2. Qty thuc te trong orders/positions co khop voi cong thuc tinh tay (equity * risk% / SL_dist)?
3. Muc lo thuc te khi dính SL la bao nhieu?
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

from backend.analys.alpha.strategies import BY_ID
from backend.analys.param import schema_defaults, materialize, build_params
from backend.analys.signal.compute import evaluate_signals
from backend.models.models import PositionType
from backend.core.backtest import NautilusRun
from backend.analys.alpha import RiskConfig
from tests.test_execution_realism_fixtures import SimpleStubDataSource

# 1. Khởi tạo fixture 365 nến 4h
n_bars = 365
base_ms = 4 * 3600_000 # 4h frame
open_time = np.arange(n_bars, dtype=np.int64) * base_ms

np.random.seed(42)
trend = np.linspace(20000, 45000, n_bars)
noise = np.random.normal(0, 500, n_bars)
c = trend + noise + 2000 * np.sin(np.linspace(0, 4 * np.pi, n_bars))
# Tạo đợt sụt giá để ép chạm SL
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
ds = SimpleStubDataSource(symbol, "4h", open_time.tolist(), o.tolist(), h.tolist(), l.tolist(), c.tolist(), v.tolist(), lot_sz="0.001")
df_4h = pd.DataFrame({"open_time": open_time, "open": o, "high": h, "low": l, "close": c, "volume": v})

# 2. Materialize kema_long chuẩn từ hệ thống
candidate = BY_ID["kema_long"]
params = schema_defaults(candidate)
strategy = materialize(candidate, params, regime=False)

print("=" * 80)
print("1. PROVENANCE CỦA KEMA_LONG TỪ MATERIALIZE")
print("=" * 80)
pos = strategy["position"]
for k in ["sizing", "order_size_pct", "risk_per_trade_pct", "stop_loss_rate", "exit_unit", "leverage"]:
    print(f"  {k}: {pos.get(k)}")

# 3. Đánh giá tín hiệu qua evaluate_signals
signals = evaluate_signals(symbol, [strategy], {"4h": df_4h}, "4h")
entry_entry = signals["entries"][0]
match_mask = entry_entry["match"]
stop_mask = entry_entry["stop"]
slot = entry_entry["slot"]

print(f"\nTín hiệu: match={match_mask.sum()} bars, stop={stop_mask.sum()} bars")
print(f"Slot params: sizing={slot.params.sizing}, order_size_pct={slot.params.order_size_pct}, risk_per_trade_pct={slot.params.risk_per_trade_pct}")

# 4. Chạy NautilusRun
book = {
    "symbol": symbol,
    "data": {"t": np.array(open_time, dtype=np.int64)},
    "entries": [{"strategy": "kema_long", "slot": slot, "match": match_mask, "stop": stop_mask, "vol": atr14}]
}
risk = RiskConfig(max_positions=2, max_per_symbol=1, max_gross_exposure=3.0, kill_switch_dd_pct=50.0)
runner = NautilusRun(
    books=[book], initial_capital=10_000.0, risk=risk, trade_start_ts=0,
    end_ts=n_bars * base_ms, base_frame="4h", close_at_end=True, data=ds, execution_target="next_open"
)
res = runner.run()
positions = res.get("positions", [])
orders = res.get("orders", [])
open_pos = res.get("open_positions", [])

print(f"\nKết quả Nautilus: {len(positions)} vị thế đóng, {len(open_pos)} vị thế mở, {len(orders)} lệnh")
events = res.get("events", [])
print(f"Tổng số events: {len(events)}")
for ev in events[:20]:
    print(f"  Event: {ev}")

print("\n" + "=" * 80)
print("2. BẢNG PER-TRADE KEMA_LONG: QTY TÍNH TAY VS QTY THỰC TẾ")
print("=" * 80)
equity = 10_000.0
target_risk_pct = slot.params.risk_per_trade_pct # 0.5%
target_risk_usd = equity * (target_risk_pct / 100.0) # 50 USDT

print(f"Vốn: {equity:.1f} USDT | Rủi ro khai báo: {target_risk_pct}% ({target_risk_usd:.1f} USDT/lệnh)")
print(f"SL Rate: {slot.params.stop_loss_rate}x ATR (khung 4h)")
print(f"{'#':<3} {'Bar En':<7} {'Bar Cl':<7} {'Px En':<9} {'Px Cl':<9} {'ATR thật':<9} {'SL Dist':<9} {'Qty Tính Tay':<13} {'Qty Thực':<9} {'PnL (USDT)':<12} {'Status':<8}")
print("-" * 105)

for idx, p in enumerate(positions):
    en_bar = p.enter_time // base_ms
    cl_bar = p.close_time // base_ms
    atr_val = atr14[en_bar]
    sl_dist = slot.params.stop_loss_rate * atr_val
    calc_qty = target_risk_usd / sl_dist if sl_dist > 0 else 0.0
    print(f"{idx+1:<3} {en_bar:<7} {cl_bar:<7} {p.enter_price:<9.1f} {p.close_price:<9.1f} {atr_val:<9.2f} {sl_dist:<9.2f} {calc_qty:<13.4f} {p.qty:<9.4f} {p.real_pnl:<12.2f} {p.status.name:<8}")
