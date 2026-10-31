"""
Kiem chung toan dien co che sizing cua Nora Coin Engine:
1. BASE_POSITION & build_params: sizing mode mac dinh la gi?
2. Doi stop_loss_rate gap doi: qty co giam mot nua khong o sizing='margin_pct' vs sizing='risk'?
3. Bang per-trade doi chieu co lenh tinh tay vs thuc te.
4. Doi chieu snapshot Sideway goc de xac minh stop_loss_rate.
"""
import sys
from pathlib import Path

WORKSPACE = Path("/home/vmc03/norabt")
COIN_ROOT = WORKSPACE / "nora" / "coin"
sys.path.insert(0, str(COIN_ROOT))

import json
import numpy as np
import pandas as pd
from backend.analys.param.params import BASE_POSITION, build_params
from backend.analys.position import position_size as policy

print("=" * 60)
print("1. KHẢO SÁT BASE_POSITION VÀ BUILD_PARAMS")
print("=" * 60)
for k in ["sizing", "order_size_pct", "risk_per_trade_pct", "max_notional_pct", "leverage"]:
    print(f"  BASE_POSITION[{k!r}] = {BASE_POSITION.get(k)!r}")

p_default = build_params("test", {}, "entry", {"market": "perp"}, "cex")
print("\nDefault build_params:")
print(f"  sizing: {p_default.sizing}")
print(f"  order_size_pct: {p_default.order_size_pct}")
print(f"  risk_per_trade_pct: {getattr(p_default, 'risk_per_trade_pct', None)}")
print(f"  risk_per_trade_pct: {p_default.risk_per_trade_pct}")
print(f"  max_notional_pct: {p_default.max_notional_pct}")

print("\n" + "=" * 60)
print("2. THỰC NGHIỆM ĐỔI GẤP ĐÔI STOP_LOSS_RATE (2.5% -> 5.0%)")
print("=" * 60)

# Kịch bản: Equity = 10,000 USDT, Price = 27,000 USDT
eq = 10000.0
price = 27000.0

print("\n--- A. CHẾ ĐỘ HIỆN TẠI CỦA USER ALPHA (chưa có key 'sizing' -> fallback margin_pct) ---")
for sl in [2.5, 5.0]:
    bp = build_params("test", {}, "entry", {"market": "perp", "stop_loss_rate": sl, "risk_per_trade_pct": 0.25}, "cex")
    if bp.sizing == "risk":
        margin, lev, planned = policy.risk_margin(eq, bp.risk_per_trade_pct, bp.max_notional_pct, sl, bp.fee_rate, 0.0, None, True, bp.leverage, bp.maintenance_margin_rate, bp.leverage, 1.0)
    else:
        margin = policy.flat_margin(eq, bp.order_size_pct)
        lev = float(bp.leverage)
        planned = policy.planned_risk_cap(margin, lev, sl, policy.round_trip_cost(bp.fee_rate, 0.0, None, margin * lev), 1.0)
    notional = margin * lev
    qty = notional / price
    actual_loss_at_sl = notional * (sl / 100.0)
    print(f"SL={sl}% | sizing={bp.sizing} | margin={margin:.2f} | notional={notional:.2f} | qty={qty:.4f} BTC | loss_at_SL={actual_loss_at_sl:.2f} USDT (kỳ vọng 25 USDT)")

print("\n--- B. CHẾ ĐỘ RỦI RO (khi thêm 'sizing': 'risk') ---")
for sl in [2.5, 5.0]:
    bp_risk = build_params("test", {}, "entry", {"market": "perp", "sizing": "risk", "stop_loss_rate": sl, "risk_per_trade_pct": 0.25}, "cex")
    if bp_risk.sizing == "risk":
        margin, lev, planned = policy.risk_margin(eq, bp_risk.risk_per_trade_pct, bp_risk.max_notional_pct, sl, bp_risk.fee_rate, 0.0, None, True, bp_risk.leverage, bp_risk.maintenance_margin_rate, bp_risk.leverage, 1.0)
    else:
        margin = policy.flat_margin(eq, bp_risk.order_size_pct)
        lev = float(bp_risk.leverage)
        planned = 0.0
    notional = margin * lev
    qty = notional / price
    actual_loss_at_sl = notional * (sl / 100.0)
    target_risk = eq * (0.25 / 100.0) # 25 USDT
    calc_qty = target_risk / (price * sl / 100.0)
    print(f"SL={sl}% | sizing={bp_risk.sizing} | margin={margin:.2f} | notional={notional:.2f} | qty={qty:.4f} BTC (tính tay: {calc_qty:.4f}) | loss_at_SL={actual_loss_at_sl:.2f} USDT (mục tiêu 25 USDT)")

print("\n" + "=" * 60)
print("3. ĐỐI SOÁT SNAPSHOT SIDEWAY GỐC")
print("=" * 60)
snapshot_path = WORKSPACE / "nora" / "coin" / "data" / "alpha" / "system_strategies_v1_snapshot.json"
if snapshot_path.exists():
    with open(snapshot_path, "r", encoding="utf-8") as f:
        snap = json.load(f)
    print("Các leg trong snapshot v1:")
    for leg in snap:
        if "sideway" in leg.lower() or "kema" in leg.lower():
            print(f"\n--- Strategy: {leg} ---")
            pos = snap[leg].get("position", {})
            for pk in sorted(pos.keys()):
                print(f"    {pk}: {pos[pk]}")
else:
    print("Không tìm thấy snapshot json")
