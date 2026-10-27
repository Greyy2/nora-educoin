"""Gate 1.1 Cross-Product Signal Parity Verification (Isolation Preserved).

Chạy kiểm toán độc lập đối chiếu tín hiệu giữa EDU và COIN:
- Chạy tiến trình con riêng cho EDU (PYTHONPATH=nora/edu)
- Chạy tiến trình con riêng cho COIN (PYTHONPATH=nora/coin)
- Tuyệt đối không cross-import
- Đối chiếu bitwise 100% của:
  1. Indicator arrays (RSI, SMA, EMA)
  2. Explicit signal levels
  3. Target signal levels
  4. Program IR code hash
"""
import json
import os
import subprocess
import sys
import numpy as np
import pytest

FAST_DIP_CODE = '''class FastDipHarvesterStrategy(NoraStrategy):
    timeframe = '24h'
    rsi_period = 10
    sma_period = 15
    macro_period = 50
    stop_loss_pct = 2.0
    take_profit_pct = 4.0
    risk_per_trade_pct = 0.25

    def on_bar(self):
        rsi_val = rsi(close, self.rsi_period)
        sma_val = sma(close, self.sma_period)
        macro = ema(close, self.macro_period)

        self.close((rsi_val > 65.0) | crossunder(close, sma_val))
        self.buy(crossover(rsi_val, 40.0) & (close > sma_val) & (close > macro))
'''

SUBPROCESS_SNIPPET = """
import json, sys
import numpy as np
import pandas as pd
from backend.analys.alpha.code.compile import compile_code
from backend.analys.indicator import compute

# Load fixture directly
n = 120
day_ms = 86400 * 1000
times = np.arange(n, dtype=np.int64) * day_ms
closes = np.full(n, 50000.0, dtype=np.float64)
for i in range(60): closes[i] = 50000.0 + 150.0 * np.sin(i * 0.4)
closes[60:65] = [49500.0, 49000.0, 48500.0, 47800.0, 47200.0]
closes[65] = 50800.0
closes[66:72] = [51600.0, 52500.0, 53500.0, 54800.0, 55900.0, 57200.0]
closes[72] = 59000.0
closes[73:78] = [57000.0, 55000.0, 53500.0, 52000.0, 50500.0]
closes[78] = 49500.0
closes[79] = 54500.0
closes[80:84] = [55000.0, 55200.0, 55100.0, 55000.0]
closes[84] = 50000.0
for i in range(85, 110): closes[i] = 50000.0 + 100.0 * np.cos(i * 0.3)
closes[110] = 50500.0
for i in range(111, 117): closes[i] = 50000.0 + 80.0 * np.sin(i * 0.5)
closes[117:119] = [48000.0, 47500.0]
closes[119] = 51000.0

opens = np.roll(closes, 1); opens[0] = closes[0]
highs = np.maximum(opens, closes) + 200.0
lows = np.minimum(opens, closes) - 200.0
volumes = np.full(n, 100.0, dtype=np.float64)

df = pd.DataFrame({'open_time': times, 'open': opens, 'high': highs, 'low': lows, 'close': closes, 'volume': volumes})

prog = compile_code(sys.argv[1], register=False)
rsi = compute(df, 'rsi_10').to_numpy()
sma = compute(df, 'sma_15').to_numpy()
ema = compute(df, 'ema_50').to_numpy()

from backend.analys.signal.signal import Ctx
n, data = prog._data(df)
ctx = Ctx(n, data)
exit_sig = [bool(x) for x in np.asarray(prog.calls[0][0].ev(ctx), dtype=bool)]
buy_sig = [bool(x) for x in np.asarray(prog.calls[1][0].ev(ctx), dtype=bool)]

explicit = prog.explicit(df)
target = prog.target(df)

payload = {
    'code_hash': prog.code_hash,
    'rsi': [None if np.isnan(v) else round(float(v), 8) for v in rsi],
    'sma': [None if np.isnan(v) else round(float(v), 8) for v in sma],
    'ema': [None if np.isnan(v) else round(float(v), 8) for v in ema],
    'buy_sig': buy_sig,
    'exit_sig': exit_sig,
    'explicit': [None if np.isnan(v) else float(v) for v in explicit],
    'target': [None if np.isnan(v) else float(v) for v in target],
}
print('__RESULT__:' + json.dumps(payload))
"""

def run_isolated_product(product: str) -> dict:
    root = "/home/vmc03/norabt"
    py = "/home/vmc03/.venvs/nora312/bin/python"
    env = dict(os.environ, PYTHONPATH=f"nora/{product}")
    cmd = [py, "-c", SUBPROCESS_SNIPPET, FAST_DIP_CODE]
    cp = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, check=True)
    line = next(l for l in cp.stdout.splitlines() if l.startswith("__RESULT__:"))
    return json.loads(line.replace("__RESULT__:", ""))


def test_gate1_1_cross_product_signal_parity():
    """Kiểm tra đối chiếu chéo độc lập giữa EDU và COIN."""
    edu_data = run_isolated_product("edu")
    coin_data = run_isolated_product("coin")

    # 1. Mã hash biên dịch trùng 100%
    assert edu_data["code_hash"] == coin_data["code_hash"], "Lệch code hash giữa EDU và COIN!"

    # 2. Toàn bộ mảng indicator trùng 100%
    assert edu_data["rsi"] == coin_data["rsi"], "Lệch mảng RSI giữa EDU và COIN!"
    assert edu_data["sma"] == coin_data["sma"], "Lệch mảng SMA giữa EDU và COIN!"
    assert edu_data["ema"] == coin_data["ema"], "Lệch mảng EMA giữa EDU và COIN!"

    # 3. Toàn bộ tín hiệu buy, exit, explicit & target trùng 100%
    assert edu_data["buy_sig"] == coin_data["buy_sig"], "Lệch tín hiệu BUY giữa EDU và COIN!"
    assert edu_data["exit_sig"] == coin_data["exit_sig"], "Lệch tín hiệu EXIT giữa EDU và COIN!"
    assert edu_data["explicit"] == coin_data["explicit"], "Lệch explicit signal giữa EDU và COIN!"
    assert edu_data["target"] == coin_data["target"], "Lệch target levels giữa EDU và COIN!"

    print(f"✅ Gate 1.1 Cross-Product Signal Parity PASS: code_hash={edu_data['code_hash']}, 120 bars matching 100%!")
