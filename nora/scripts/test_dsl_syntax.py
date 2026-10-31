#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path("/home/vmc03/norabt").resolve()
sys.path.insert(0, str(ROOT / "nora/edu"))

from backend.analys.alpha.code.compile import compile_code

code1 = """class ConfluenceObvRsiMomentumStrategy(NoraStrategy):
    timeframe = "24h"
    obv_sma_period = 20
    rsi_period = 14
    rsi_enter_level = 50.0
    rsi_exit_level = 45.0
    stop_loss_pct = 3.0
    take_profit_pct = 0.0
    trailing_stop_pct = 0.0
    trailing_activation_pct = 0.0
    timeout = 0
    risk_per_trade_pct = 0.5

    def on_bar(self):
        obv = self.feat.obv(close, volume)
        obv_sma = sma(obv, self.obv_sma_period)
        rsi = rsi(close, self.rsi_period)
        rsi_cross = self.op.crossed_above_value(rsi, self.rsi_enter_level)
        enter_sig = self.op.previous(rsi_cross, 1) & (rsi > self.rsi_enter_level) & (obv > obv_sma)
        exit_sig = rsi < self.rsi_exit_level
        self.close(exit_sig)
        self.buy(enter_sig)
"""

try:
    prog = compile_code(code1)
    print("Compilation SUCCESS: prog is", type(prog))
except Exception as e:
    print("Compilation FAILED:", e)
