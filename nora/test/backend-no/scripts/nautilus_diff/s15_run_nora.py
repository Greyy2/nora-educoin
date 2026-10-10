"""Run Nora side of S15 matching engine parity tests.
Executes pure kernel slots on synthetic bar data across all cases and path modes (ohlc, adaptive).
Outputs to out/s15/nora_<case>_<mode>.json.
"""
import json
import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))

from s15_common import CAPITAL, MAKER, OUT, SYM, TAKER
from s15_cases import CASES
from backend.core.models import PositionType
from backend.core.params import StrategyParams
from backend.core.position_size import SlotSpec
from backend.core.backtest import SlotDriver


def run_case_nora(case_name, case, mode="ohlc"):
    bars = case["bars"]
    is_long = case["side"] == "LONG"
    lev = float(case["lev"])
    mmr = float(case.get("mmr", 0.005))
    sl = float(case["sl"])
    tp = float(case["tp"])
    dca = case["dca"]
    trail = case["trail"]

    dca_steps = list(dca["steps"]) if dca else []
    dca_mults = list(dca["mults"]) if dca else []
    trail_offset = float(trail["offset"]) if trail else 0.0
    trail_act = float(trail["act"]) if trail else 0.0

    # 1.0 contract size @ 100.0 price = 100 notional. With CAPITAL=10000, 100 notional = 1% of capital.
    # Order size: 1.0 contract -> order_size_pct = 1.0 * 100 / CAPITAL * 100 = 1.0% (at lev 1, margin=100)
    osp = 100.0 / CAPITAL * 100.0

    params = StrategyParams(
        market="perp",
        leverage=lev,
        maintenance_margin_rate=mmr,
        fee_rate=TAKER,
        maker_fee_rate=MAKER,
        slippage_rate=0.0,
        order_size_pct=osp,
        sizing="margin_pct",
        stop_loss_rate=sl,
        take_profit_rate=tp,
        trailing_stop=trail_offset,
        trailing_activation_pct=trail_act,
        dca_steps=dca_steps,
        dca_multipliers=dca_mults,
        intrabar_path=mode,
        limit_through_pct=0.0,
    )

    spec = SlotSpec(
        account_id=0,
        campaign_id=0,
        symbol=SYM,
        flow_name=case_name,
        params=params,
        pos_type=PositionType.LONG if is_long else PositionType.SHORT,
        initial_capital=CAPITAL,
    )

    drv = SlotDriver([spec])
    slot = drv[0]

    for i in range(len(bars)):
        row = bars.iloc[i]
        # Bar 0: emit entry signal (to fill at open of Bar 1)
        entry_sig = (i == 0)
        slot.on_bar(
            int(row.open_time),
            float(row.open),
            float(row.high),
            float(row.low),
            float(row.close),
            entry_signal=entry_sig,
            can_open=True,
            dca_gate=True,
        )

    # Extract executed orders / fills
    drv.refresh_open()
    raw_orders = slot.orders
    pos_open = slot.position

    ncl = int(drv.G[3]) # G_NCL
    p_closed = drv._closed_since(0) if ncl > 0 else None

    fills = []
    n_ord = len(raw_orders)
    for idx, o in enumerate(raw_orders):
        is_entry = (idx == 0)
        is_last = (idx == n_ord - 1) and not slot.is_open
        
        kind = "ENTRY"
        if is_entry:
            kind = "ENTRY"
        elif is_last:
            reason = p_closed.close_reason if p_closed else ""
            if "Stop-loss" in reason:
                kind = "SL"
            elif "Take-profit" in reason:
                kind = "TP"
            elif "Trailing" in reason:
                kind = "TRAIL"
            elif "Liquidation" in reason:
                kind = "LIQ"
            else:
                kind = "EXIT"
        else:
            kind = "DCA"

        fills.append({
            "t": int(o.order_time),
            "side": "BUY" if o.order_type.name == "BUY" else "SELL",
            "px": float(o.order_price),
            "qty": float(o.qty),
            "fee": float(o.fee_usd),
            "liq": str(o.liquidity),
            "kind": kind,
        })

    open_at_end = []
    if slot.is_open and float(slot.qty) > 0:
        open_at_end.append({
            "sym": SYM,
            "enter_time": int(slot.entry_time),
            "avg_price": float(slot.avg),
            "qty": float(slot.qty),
        })

    # Deduct fees_paid from open positions to match balance_total convention of Nautilus
    fees_open = float(slot.fees_paid) if slot.is_open else 0.0
    realized_equity = float(drv.LG[0]) - fees_open

    return {
        "case": case_name,
        "mode": mode,
        "fills": fills,
        "n_fills": len(fills),
        "open_at_end": open_at_end,
        "realized_equity": realized_equity,
    }


def main():
    only_case = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] not in ("all", "ohlc", "adaptive") else None
    modes = ["ohlc", "adaptive"]
    if len(sys.argv) > 1 and sys.argv[1] in ("ohlc", "adaptive"):
        modes = [sys.argv[1]]

    cases_to_run = [only_case] if only_case else list(CASES.keys())

    for case_name in cases_to_run:
        for mode in modes:
            case = CASES[case_name]
            res = run_case_nora(case_name, case, mode)
            out_file = os.path.join(OUT, f"nora_{case_name}_{mode}.json")
            with open(out_file, "w") as f:
                json.dump(res, f, indent=2)
            print(f"Nora {case_name} [{mode}]: {res['n_fills']} fills, eq={res['realized_equity']:.2f}")


if __name__ == "__main__":
    main()
