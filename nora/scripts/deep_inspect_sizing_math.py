import os
import sys
import json
import numpy as np
import pandas as pd

sys.path.insert(0, "/home/vmc03/norabt/nora/coin")
os.environ["NORA_DIR"] = "/home/vmc03/norabt/nora/coin"
os.environ["NORA_LOCAL_DATA_ROOT"] = "/home/vmc03/norabt/nora/coin/data"

from backend.analys.alpha.code.compile import compile_code
from backend.analys.param import build_params
from backend.analys.position import SlotSpec, position_size as policy
from backend.models.models import PositionType

# Nạp 18e87aa868ad V1 và V2
with open("nora/coin/data/alpha/user/18e87aa868ad.json") as f:
    d1 = json.load(f)
pos1 = compile_code(d1["code"]).position_overrides

with open("nora/coin/data/alpha/user/18e87aa868ad_v2.json") as f:
    d2 = json.load(f)
pos2 = compile_code(d2["code"]).position_overrides

print("=== INSPECT POSITION PARAMS & SIZING CONFIG ===")
print("V1 pos_override:", pos1)
print("V2 pos_override:", pos2)

flow = {"type": "LONG", "match": [], "stop": []}
p_obj1 = build_params("18e_v1", flow, "LONG", pos1, "cex")
p_obj2 = build_params("18e_v2", flow, "LONG", pos2, "cex")

print("\nV1 build_params:")
print("  sizing:", getattr(p_obj1, "sizing", None))
print("  risk_per_trade_pct:", getattr(p_obj1, "risk_per_trade_pct", None))
print("  stop_loss_rate:", getattr(p_obj1, "stop_loss_rate", None))
print("  exit_unit:", getattr(p_obj1, "exit_unit", None))
print("  max_notional_pct:", getattr(p_obj1, "max_notional_pct", None))
print("  leverage:", getattr(p_obj1, "leverage", None))

print("\nV2 build_params:")
print("  sizing:", getattr(p_obj2, "sizing", None))
print("  risk_per_trade_pct:", getattr(p_obj2, "risk_per_trade_pct", None))
print("  stop_loss_rate:", getattr(p_obj2, "stop_loss_rate", None))
print("  exit_unit:", getattr(p_obj2, "exit_unit", None))
print("  max_notional_pct:", getattr(p_obj2, "max_notional_pct", None))
print("  leverage:", getattr(p_obj2, "leverage", None))

# Tính thử risk_margin với equity = 10,000 USDT
eq = 10000.0
print("\n=== TÍNH TOÁN THEO POLICY.RISK_MARGIN ===")
for label, p_obj in [("V1", p_obj1), ("V2", p_obj2)]:
    sl_rate = float(getattr(p_obj, "stop_loss_rate", 2.5))
    unit = getattr(p_obj, "exit_unit", "pct")
    # Giả sử ở bar 131, price = 27023.8, ATR = 550 => ATR% = 550 / 27023.8 * 100 = 2.035%
    sl_pct = sl_rate if unit == "pct" else sl_rate * (550.0 / 27023.8 * 100.0)
    risk_pct = float(getattr(p_obj, "risk_per_trade_pct", 0.25))
    max_notional_pct = float(getattr(p_obj, "max_notional_pct", 100.0) or 100.0)
    fee_rate = 0.0005
    slip_rate = 0.0003
    max_lev = float(getattr(p_obj, "leverage", 10.0))
    
    margin, lev, planned = policy.risk_margin(
        equity=eq, risk_pct=risk_pct, max_notional_pct=max_notional_pct,
        sl_pct=sl_pct, fee_rate=fee_rate, slippage_rate=slip_rate, impact_fn=None,
        is_perp=True, max_leverage=max_lev, mmr=0.01, pos_leverage=max_lev, total_mult=1.0
    )
    notional = margin * lev
    calc_qty = notional / 27023.8
    expected_loss = notional * (sl_pct / 100.0)
    print(f"\n{label}:")
    print(f"  sl_pct quy đổi: {sl_pct:.3f}% (khoảng cách SL = {sl_pct/100.0 * 27023.8:.1f} USDT)")
    print(f"  notional tính từ risk_margin: {notional:.2f} USDT")
    print(f"  leverage tính từ risk_margin: {lev}")
    print(f"  margin tính từ risk_margin: {margin:.2f} USDT")
    print(f"  planned risk: {planned:.2f} USDT")
    print(f"  qty tính toán lý thuyết: {calc_qty:.4f} BTC")
    print(f"  expected loss tại SL: {expected_loss:.2f} USDT")
