import sys
from pathlib import Path

ROOT = Path("/home/vmc03/norabt").resolve()
sys.path.insert(0, str(ROOT / "nora/edu"))
from backend.analys.alpha.code.compile import compile_code

# Test 541c55834f56 C1
code_541 = """class RangePctStrategy(NoraStrategy):
    timeframe = "24h"
    sma_period = 20
    range_enter_level = 6.0
    stop_loss_pct = 3.0
    take_profit_pct = 0.0
    trailing_stop_pct = 0.0
    trailing_activation_pct = 0.0
    timeout = 0
    risk_per_trade_pct = 0.5

    def on_bar(self):
        open_p = open
        range_val = self.feat.range_pct(high, low, close)
        sma_val = sma(close, self.sma_period)
        bar_span = high - low
        top_quarter = close > (low + 0.75 * bar_span)
        enter_sig = (range_val > self.range_enter_level) & (close > open_p) & (close > sma_val) & top_quarter
        exit_sig = crossunder(close, sma_val)
        self.close(exit_sig)
        self.buy(enter_sig)
"""

try:
    p = compile_code(code_541)
    print("541 C1 compiled successfully! Name:", p.name)
except Exception as e:
    print("541 C1 compile error:", e)
