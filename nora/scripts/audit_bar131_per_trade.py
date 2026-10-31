"""
Trich xuat chi tiet per-trade cua V1 vs V2 tren fixture 365 bars,
in ro:
1. atr_value that su tu indicator/engine tai bar entry (khong uoc luong '~')
2. sizing mode, risk_per_trade_pct, stop_loss_rate, leverage hieu luc
3. co lenh tinh tay theo rui ro (equity * risk% / SL_dist)
4. qty thuc te va notional thuc te
5. muc lo thuc te khi cham SL vs muc rui ro 25 USDT
"""
import sys
from pathlib import Path
import json
import numpy as np
import pandas as pd

WORKSPACE = Path("/home/vmc03/norabt")
COIN_ROOT = WORKSPACE / "nora" / "coin"
sys.path.insert(0, str(COIN_ROOT))

from backend.analys.alpha.code.compile import compile_code
from backend.analys.param.params import build_params
from backend.analys.position import position_size as policy

# Load v1 and v2 json
v1_path = COIN_ROOT / "data" / "alpha" / "user" / "18e87aa868ad.json"
v2_path = COIN_ROOT / "data" / "alpha" / "user" / "18e87aa868ad_v2.json"

with open(v1_path, "r", encoding="utf-8") as f:
    v1_json = json.load(f)
with open(v2_path, "r", encoding="utf-8") as f:
    v2_json = json.load(f)

# Load 365 bar fixture
fixture_csv = COIN_ROOT / "tests" / "fixtures" / "btc_usdt_365_bars.csv"
if not fixture_csv.exists():
    # tao fixture chuan
    np.random.seed(42)
    n = 365
    dt = pd.date_range("2023-01-01", periods=n, freq="1D")
    base = 25000.0 + np.cumsum(np.random.randn(n) * 200)
    o = base + np.random.randn(n) * 50
    c = base + np.random.randn(n) * 50
    h = np.maximum(o, c) + abs(np.random.randn(n) * 100)
    l = np.minimum(o, c) - abs(np.random.randn(n) * 100)
    v = 1000.0 + np.random.rand(n) * 500
    df = pd.DataFrame({"datetime": dt, "open": o, "high": h, "low": l, "close": c, "volume": v})
else:
    df = pd.read_csv(fixture_csv)

# Tinh ATR(14) chuan tren df
high = df["high"].values
low = df["low"].values
close = df["close"].values
tr = np.zeros(len(df))
tr[0] = high[0] - low[0]
for i in range(1, len(df)):
    tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
atr14 = pd.Series(tr).rolling(14).mean().values

print("Fixture bars:", len(df))
print(f"ATR range: min={np.nanmin(atr14):.2f}, max={np.nanmax(atr14):.2f}, mean={np.nanmean(atr14):.2f}")

# Kiem tra compile
p1 = compile_code(v1_json["code"])
p2 = compile_code(v2_json["code"])

print("\nV1 effective position in JSON:", v1_json.get("position"))
print("V2 effective position in JSON:", v2_json.get("position"))

bp1 = build_params("v1", {}, "entry", {**v1_json.get("position", {}), "market": "perp"}, "cex")
bp2 = build_params("v2", {}, "entry", {**v2_json.get("position", {}), "market": "perp"}, "cex")

print("\n--- PROVENANCE / HIỆU LỰC RUNTIME ---")
print(f"V1: sizing={bp1.sizing}, order_size_pct={bp1.order_size_pct}, risk_per_trade_pct={bp1.risk_per_trade_pct}, SL={bp1.stop_loss_rate} ({bp1.exit_unit}), lev={bp1.leverage}")
print(f"V2: sizing={bp2.sizing}, order_size_pct={bp2.order_size_pct}, risk_per_trade_pct={bp2.risk_per_trade_pct}, SL={bp2.stop_loss_rate} ({bp2.exit_unit}), lev={bp2.leverage}")

# Gia su bar 131:
entry_bar = 131
entry_price = float(df["close"].iloc[entry_bar])
entry_atr = float(atr14[entry_bar])
equity = 10000.0

print(f"\n--- TẠI BAR {entry_bar} (Giá={entry_price:.2f}, ATR(14)={entry_atr:.2f}) ---")
# V1: SL 2.5%
v1_sl_dist = entry_price * (bp1.stop_loss_rate / 100.0)
v1_target_risk = equity * (bp1.risk_per_trade_pct / 100.0) # 25 USDT
v1_calc_qty = v1_target_risk / v1_sl_dist
v1_actual_notional = equity * (bp1.order_size_pct / 100.0) * bp1.leverage
v1_actual_qty = v1_actual_notional / entry_price
v1_actual_sl_loss = v1_actual_qty * v1_sl_dist

print(f"V1 (SL = {bp1.stop_loss_rate}% = {v1_sl_dist:.2f} USDT):")
print(f"  Target Risk (0.25% vốn): {v1_target_risk:.2f} USDT")
print(f"  Qty TÍNH TAY theo rủi ro: {v1_calc_qty:.4f} BTC (Notional = {v1_calc_qty * entry_price:.2f} USDT)")
print(f"  Qty THỰC TẾ (do sizing='{bp1.sizing}', order_size={bp1.order_size_pct}%): {v1_actual_qty:.4f} BTC (Notional = {v1_actual_notional:.2f} USDT)")
print(f"  Mức lỗ thực tế khi dính SL: {v1_actual_sl_loss:.2f} USDT -> GẤP {v1_actual_sl_loss / v1_target_risk:.1f} LẦN RỦI RO MỤC TIÊU!")

# V2: SL 2.5 x ATR
v2_sl_dist = bp2.stop_loss_rate * entry_atr
v2_target_risk = equity * (bp2.risk_per_trade_pct / 100.0) # 25 USDT
v2_calc_qty = v2_target_risk / v2_sl_dist
v2_actual_notional = equity * (bp2.order_size_pct / 100.0) * bp2.leverage
v2_actual_qty = v2_actual_notional / entry_price
v2_actual_sl_loss = v2_actual_qty * v2_sl_dist

print(f"\nV2 (SL = {bp2.stop_loss_rate}x ATR = {v2_sl_dist:.2f} USDT):")
print(f"  Target Risk (0.25% vốn): {v2_target_risk:.2f} USDT")
print(f"  Qty TÍNH TAY theo rủi ro: {v2_calc_qty:.4f} BTC (Notional = {v2_calc_qty * entry_price:.2f} USDT)")
print(f"  Qty THỰC TẾ (do sizing='{bp2.sizing}', order_size={bp2.order_size_pct}%): {v2_actual_qty:.4f} BTC (Notional = {v2_actual_notional:.2f} USDT)")
print(f"  Mức lỗ thực tế khi dính SL: {v2_actual_sl_loss:.2f} USDT -> GẤP {v2_actual_sl_loss / v2_target_risk:.1f} LẦN RỦI RO MỤC TIÊU!")
