import sys
from pathlib import Path
from decimal import Decimal
import numpy as np

EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")
sys.path.insert(0, str(EDU_ROOT))

from backend.analys.alpha.code.compile import compile_code
from backend.analys.alpha.code.plan import build_plan
from backend.core import catalog as cat
from backend.core.backtest import _open_quote_ticks
from backend.jobs.runner.backtest import run_benchmark, _BENCH_CACHE
from backend.jobs.tasks import date_ms, DAY

print("=== 1. TEST CODE-FIRST PRIORITY ===")
code_with_config = """class UserDualEma(NoraStrategy):
    timeframe = "1h"
    stop_loss_rate = 3.0
    cooldown = 60
    risk_per_trade_pct = 0.5
    
    def on_bar(self):
        self.buy(close > open)
        self.close(close < open)
"""
prog = compile_code(code_with_config)
print("Declared in code:", prog.position_overrides)
assert prog.position_overrides.get("stop_loss_rate") == 3.0
assert prog.position_overrides.get("cooldown") == 60
assert prog.position_overrides.get("risk_per_trade_pct") == 0.5

# UI attempts to send old defaults (2.5, 1440, 4) + take_profit_rate = 5.0 (which code didn't declare)
ui_settings = {
    "stop_loss_rate": 2.5,
    "cooldown": 1440,
    "risk_per_trade_pct": 4.0,
    "take_profit_rate": 5.0,
}

plan = build_plan(prog, ["BTC-USDT"], position=ui_settings, run_frame="1h")
pos = plan.strategies[0]["position"]

print("Effective pos stop_loss_rate:", pos["stop_loss_rate"], "(expected 3.0)")
print("Effective pos cooldown:", pos["cooldown"], "(expected 60)")
print("Effective pos risk_per_trade_pct:", pos["risk_per_trade_pct"], "(expected 0.5)")
print("Effective pos take_profit_rate:", pos["take_profit_rate"], "(expected 5.0 from UI)")

assert pos["stop_loss_rate"] == 3.0, f"Expected 3.0, got {pos['stop_loss_rate']}"
assert pos["cooldown"] == 60, f"Expected 60, got {pos['cooldown']}"
assert pos["risk_per_trade_pct"] == 0.5, f"Expected 0.5, got {pos['risk_per_trade_pct']}"
assert pos["take_profit_rate"] == 5.0, f"Expected 5.0, got {pos['take_profit_rate']}"

provenance = plan.echo["param_provenance"]
assert provenance["stop_loss_rate"]["source"] == "code"
assert provenance["cooldown"]["source"] == "code"
assert provenance["risk_per_trade_pct"]["source"] == "code"
assert provenance["take_profit_rate"]["source"] == "ui"
assert plan.echo["conflicts"] == []
print("--> Code-First Priority PASSED 100%!")

print("\n=== 2. TEST _OPEN_QUOTE_TICKS VECTORIZATION ===")
inst = cat.get_instrument("BTC-USDT")
arr = {
    "o": np.array([50000.12, 50100.45, 50200.78], dtype=np.float64),
    "t": np.array([1700000000, 1700003600, 1700007200], dtype=np.int64),
}
ticks = _open_quote_ticks("BTC-USDT", arr, inst, 0, len(arr["o"]), slippage_rate=0.0)
assert len(ticks) == 3
for tick in ticks:
    print(f"Tick {tick.bid_price} / {tick.ask_price} at ts={tick.ts_event}")
    assert tick.bid_price == tick.ask_price
print("--> _open_quote_ticks PASSED!")

print("\n=== 3. TEST BENCHMARK CANONICAL CACHE KEY ===")
names = ["BTC-USDT", "ETH-USDT"]
start, end = date_ms("2024-01-01"), date_ms("2024-01-07") + DAY
capital = 10000.0

# Strat 1 with SL=3.0, cooldown=60
res1 = run_benchmark(prog, type("Opts", (), {"position": None})(), plan, names, start, end, capital, {"source": "okx"})
assert res1 is not None

# Strat 2 with different code and different SL
code2 = """class UserStrat2(NoraStrategy):
    timeframe = "1h"
    stop_loss_rate = 1.5
    cooldown = 120
    def on_bar(self):
        self.buy(close < open)
"""
prog2 = compile_code(code2)
plan2 = build_plan(prog2, names, position={"stop_loss_rate": 1.5}, run_frame="1h")

# Must hit cache immediately because benchmark is independent of strategy!
cache_size_before = len(_BENCH_CACHE)
res2 = run_benchmark(prog2, type("Opts", (), {"position": {"stop_loss_rate": 1.5}})(), plan2, names, start, end, capital, {"source": "okx"})
cache_size_after = len(_BENCH_CACHE)

assert res1 is not None and res2 is not None, "Benchmark results must not be None"
assert np.array_equal(res2["equity"], res1["equity"]), "Benchmark equity curve must match exactly"
print(f"Cache hit verified: initial size {cache_size_before}, after size {cache_size_after}")
assert cache_size_after == cache_size_before, "Cache size should not grow on cache hit!"
print("--> Benchmark Canonical Cache PASSED!")

print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")
