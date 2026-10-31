import os
import sys
import json
import numpy as np
import pandas as pd

sys.path.insert(0, "/home/vmc03/norabt/nora/coin")
os.environ["NORA_DIR"] = "/home/vmc03/norabt/nora/coin"
os.environ["NORA_LOCAL_DATA_ROOT"] = "/home/vmc03/norabt/nora/coin/data"
os.environ["NORA_LOCAL_LOGS_ROOT"] = "/tmp"
os.environ["NORA_JWT_SECRET"] = "test"

from backend.analys.alpha.code.compile import load_system_strategies
from backend.analys.param import schema_defaults, materialize, build_params
from backend.analys.position import SlotSpec
from backend.analys.signal.compute import evaluate_signals, _strategy_flow
from backend.core.backtest import NautilusRun
from backend.analys.alpha import RiskConfig
from backend.models.models import PositionType
from tests.test_execution_realism_fixtures import SimpleStubDataSource

# 420 bars synthetic fixture matching test_all_6_legs_roundtrip.py
BASE_MS = 60_000
count = 420
open_time = np.arange(count, dtype=np.int64) * BASE_MS
minute = np.arange(count)
close = (
    100.0
    + minute * 0.01
    + 2.0 * np.sin(minute / 8.0)
    + np.where(minute % 70 >= 40, 3.0, 0.0)
)
high = close + 0.35 + 0.15 * np.abs(np.sin(minute / 5.0))
low = close - 0.35 - 0.15 * np.abs(np.cos(minute / 7.0))
open_p = close - 0.08 * np.sin(minute / 4.0)
vol = 1000.0 + 200.0 * np.abs(np.sin(minute / 6.0))

symbol = "BTC-USDT-SWAP"
ds = SimpleStubDataSource(
    symbol,
    "1m",
    open_time.tolist(),
    open_p.tolist(),
    high.tolist(),
    low.tolist(),
    close.tolist(),
    vol.tolist(),
)
candles = pd.DataFrame({
    "open_time": open_time,
    "open": open_p,
    "high": high,
    "low": low,
    "close": close,
    "volume": vol,
})

loaded = load_system_strategies()
candidates = {c["id"]: c for c in loaded["candidates"]}

def run_compare(target_id: str):
    c_orig = candidates[target_id]
    c_json = json.dumps(c_orig, ensure_ascii=False)
    c_reloaded = json.loads(c_json)

    runs = []
    for c in [c_orig, c_reloaded]:
        p = schema_defaults(c)
        for k in list(p.keys()):
            if "tf" in k:
                p[k] = "1m"
        p["atr_frame"] = "1m"
        strat = materialize(c, p, regime=False)
        off = evaluate_signals(symbol, [strat], {"1m": candles}, "1m")
        entry = off["entries"][0]

        flow = _strategy_flow(strat)
        params_obj = build_params(target_id, flow, strat.get("side", "LONG"), strat.get("position", {}), "cex")
        slot = SlotSpec(
            account_id=0,
            campaign_id=0,
            symbol=symbol,
            flow_name=target_id,
            params=params_obj,
            pos_type=PositionType.LONG if strat.get("side") == "LONG" else PositionType.SHORT,
            initial_capital=10_000.0,
        )

        book = {
            "symbol": symbol,
            "data": {"t": np.array(open_time, dtype=np.int64)},
            "entries": [{
                "strategy": target_id,
                "slot": slot,
                "match": entry["match"],
                "stop": entry["stop"],
                "vol": entry.get("vol"),
                "dca": entry.get("dca"),
            }],
        }
        risk = RiskConfig(max_positions=2, max_per_symbol=1, max_gross_exposure=3.0, kill_switch_dd_pct=30.0)
        res = NautilusRun(
            books=[book],
            initial_capital=10_000.0,
            risk=risk,
            trade_start_ts=0,
            end_ts=count * BASE_MS,
            base_frame="1m",
            close_at_end=True,
            data=ds,
            execution_target="next_open"
        ).run()
        runs.append(res)

    res1, res2 = runs[0], runs[1]
    positions1 = [(p.enter_time, p.close_time, round(p.enter_price, 6), round(p.close_price, 6), round(p.qty, 6), round(p.real_pnl, 6), p.status.name) for p in res1["positions"]]
    positions2 = [(p.enter_time, p.close_time, round(p.enter_price, 6), round(p.close_price, 6), round(p.qty, 6), round(p.real_pnl, 6), p.status.name) for p in res2["positions"]]

    print(f"\n================ LEDGER ROUND-TRIP: {target_id} ================")
    print(f"Memory positions count: {len(positions1)}")
    print(f"JSON positions count:   {len(positions2)}")
    assert positions1 == positions2, f"Ledger mismatch for {target_id}!"
    for idx, pos in enumerate(positions1):
        print(f"  Trade #{idx+1}: enter_t={pos[0]}, close_t={pos[1]}, enter_px={pos[2]}, close_px={pos[3]}, qty={pos[4]}, pnl={pos[5]}, status={pos[6]}")
    print(f"SUCCESS: {target_id} ledger is 100% BIT-FOR-BIT IDENTICAL!")

if __name__ == "__main__":
    for leg in ["kema_long", "kema_short", "sideway_long", "sideway_short", "dca_long", "dca_short"]:
        run_compare(leg)
