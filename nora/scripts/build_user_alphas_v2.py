import json
import sys
import os

sys.path.insert(0, "/home/vmc03/norabt/nora/coin")
os.environ["NORA_DIR"] = "/home/vmc03/norabt/nora/coin"
os.environ["NORA_LOCAL_DATA_ROOT"] = "/home/vmc03/norabt/nora/coin/data"

from backend.analys.alpha.code.compile import compile_code

# 1. efa90f74cd08_v2
v2_code_efa = """class DonchianTurtleStrategyV2(NoraStrategy):
    \"\"\"Donchian Channel Breakout (Turtle Trading) - Bản V2 Tường Minh.
    Khắc phục lỗi gán nhầm exit_unit: tường minh hóa exit_unit='atr', cooldown=1440m.
    \"\"\"
    timeframe = "24h"

    upper_period = 20
    lower_period = 10

    # Vị thế và rủi ro tường minh (khai báo sizing='risk')
    sizing = "risk"
    exit_unit = "atr"
    atr_frame = "24h"
    stop_loss_rate = 3.0
    take_profit_rate = 0.0
    trailing_stop = 0.0
    trailing_activation_pct = 0.0
    timeout = 0
    cooldown = 1440
    risk_per_trade_pct = 0.25

    def on_bar(self):
        upper = self.feat.donchian_upper(high, self.upper_period)
        lower = self.feat.donchian_lower(low, self.lower_period)

        breakout_entry = close > upper
        trailing_exit = close < lower

        self.close(trailing_exit)
        self.buy(breakout_entry)
"""

# 2. 18e87aa868ad_v2
v2_code_18e = """class FastDynamicChannelBreakoutV2(NoraStrategy):
    \"\"\"Fast Dynamic Channel Breakout (18D + Macro Trend) - Bản V2 Tường Minh.
    Tường minh hóa sizing='risk', exit_unit='atr', cooldown=1440m, bảo toàn logic macro EMA 100.
    \"\"\"
    timeframe = "24h"
    sma_period = 18
    std_period = 18
    std_nbdev = 1.5
    macro_period = 100

    # Vị thế và rủi ro tường minh
    sizing = "risk"
    exit_unit = "atr"
    atr_frame = "24h"
    stop_loss_rate = 2.5
    take_profit_rate = 0.0
    trailing_stop = 0.0
    cooldown = 1440
    timeout = 0
    risk_per_trade_pct = 0.25

    def on_bar(self):
        sma_val = sma(close, self.sma_period)
        std_val = stddev(close, self.std_period, self.std_nbdev)
        upper_band = sma_val + std_val
        macro = ema(close, self.macro_period)

        exit_sig = close < sma_val
        enter_sig = crossover(close, upper_band) & (close > macro)

        self.close(exit_sig)
        self.buy(enter_sig)
"""

# 3. 33312a2f4dfc_v2
v2_code_333 = """class StandardDeviationDynamicChannelBreakoutV2(NoraStrategy):
    \"\"\"Standard Deviation Dynamic Channel Breakout (v2.0) - Bản V2 Tường Minh.
    Tường minh hóa sizing='risk', exit_unit='atr', cooldown=1440m.
    \"\"\"
    timeframe = "24h"
    sma_period = 20
    std_period = 20
    std_nbdev = 1.5
    macro_period = 100

    # Vị thế và rủi ro tường minh
    sizing = "risk"
    exit_unit = "atr"
    atr_frame = "24h"
    stop_loss_rate = 2.5
    take_profit_rate = 0.0
    trailing_stop = 0.0
    cooldown = 1440
    timeout = 0
    risk_per_trade_pct = 0.25

    def on_bar(self):
        sma_val = sma(close, self.sma_period)
        std_val = stddev(close, self.std_period, self.std_nbdev)
        upper_band = sma_val + std_val
        macro = ema(close, self.macro_period)

        exit_sig = close < sma_val
        enter_sig = crossover(close, upper_band) & (close > macro)

        self.close(exit_sig)
        self.buy(enter_sig)
"""

configs = [
    {
        "id": "efa90f74cd08_v2",
        "name": "Donchian Channel Breakout V2 (Explicit ATR)",
        "note": "Bản fork v2 tường minh của efa90f74cd08, khắc phục gán nhầm exit_unit, khai báo sizing='risk', đồng bộ code và position.",
        "source": "alpha-fork-v2",
        "status": "SAVED",
        "code": v2_code_efa,
        "program_hash": compile_code(v2_code_efa).code_hash,
        "config": {
            "timeframe": "24h",
            "position": {
                "sizing": "risk",
                "exit_unit": "atr",
                "atr_frame": "24h",
                "stop_loss_rate": 3.0,
                "take_profit_rate": 0.0,
                "trailing_stop": 0.0,
                "trailing_activation_pct": 0.0,
                "timeout": 0,
                "cooldown": 1440,
                "risk_per_trade_pct": 0.25
            },
            "symbols": ["BTC", "ETH", "SOL"]
        }
    },
    {
        "id": "18e87aa868ad_v2",
        "name": "Fast Dynamic Channel Breakout V2 (Explicit ATR)",
        "note": "Bản fork v2 tường minh của 18e87aa868ad, khắc phục gán nhầm exit_unit, khai báo sizing='risk', đồng bộ code và position.",
        "source": "alpha-fork-v2",
        "status": "SAVED",
        "code": v2_code_18e,
        "program_hash": compile_code(v2_code_18e).code_hash,
        "config": {
            "timeframe": "24h",
            "position": {
                "sizing": "risk",
                "exit_unit": "atr",
                "atr_frame": "24h",
                "stop_loss_rate": 2.5,
                "take_profit_rate": 0.0,
                "trailing_stop": 0.0,
                "cooldown": 1440,
                "timeout": 0,
                "risk_per_trade_pct": 0.25
            },
            "symbols": ["BTC", "ETH", "SOL"]
        }
    },
    {
        "id": "33312a2f4dfc_v2",
        "name": "StdDev Dynamic Channel Breakout V2 (Explicit ATR)",
        "note": "Bản fork v2 tường minh của 33312a2f4dfc, khắc phục gán nhầm exit_unit, khai báo sizing='risk', đồng bộ code và position.",
        "source": "alpha-fork-v2",
        "status": "SAVED",
        "code": v2_code_333,
        "program_hash": compile_code(v2_code_333).code_hash,
        "config": {
            "timeframe": "24h",
            "position": {
                "sizing": "risk",
                "exit_unit": "atr",
                "atr_frame": "24h",
                "stop_loss_rate": 2.5,
                "take_profit_rate": 0.0,
                "trailing_stop": 0.0,
                "cooldown": 1440,
                "timeout": 0,
                "risk_per_trade_pct": 0.25
            },
            "symbols": ["BTC", "ETH", "SOL"]
        }
    }
]

for cfg in configs:
    out_file = f"/home/vmc03/norabt/nora/coin/data/alpha/user/{cfg['id']}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print(f"Generated {out_file} successfully.")
