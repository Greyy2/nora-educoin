import sys
from pathlib import Path

EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")
sys.path.insert(0, str(EDU_ROOT))

from backend.analys.alpha.code.compile import compile_code
from backend.analys.alpha.code.plan import build_plan

code = """class TestPriorityStrat(NoraStrategy):
    timeframe = "1h"
    stop_loss_rate = 3.0
    cooldown = 60
    risk_per_trade_pct = 0.5

    def on_bar(self):
        self.buy(close > open)
        self.close(close < open)
"""

prog = compile_code(code)
print(f"Code position overrides: {getattr(prog, 'position_overrides', {})}")

ui_pos = {
    "stop_loss_rate": 2.5,
    "cooldown": 1440,
    "risk_per_trade_pct": 4.0,
    "take_profit_rate": 5.0,  # Code không nêu -> phải nhận từ UI
}

plan = build_plan(prog, ["BTC-USDT"], position=ui_pos)
eff_pos = plan.strategies[0]["position"]

print("\n--- KẾT QUẢ KIỂM TRA THỨ TỰ ƯU TIÊN ---")
print(f"stop_loss_rate: {eff_pos.get('stop_loss_rate')} (kỳ vọng: 3.0)")
print(f"cooldown: {eff_pos.get('cooldown')} (kỳ vọng: 60)")
print(f"risk_per_trade_pct: {eff_pos.get('risk_per_trade_pct')} (kỳ vọng: 0.5)")
print(f"take_profit_rate: {eff_pos.get('take_profit_rate')} (kỳ vọng: 5.0 - lấy từ bánh răng)")

assert eff_pos.get("stop_loss_rate") == 3.0, f"Sai: {eff_pos.get('stop_loss_rate')}"
assert eff_pos.get("cooldown") == 60, f"Sai: {eff_pos.get('cooldown')}"
assert eff_pos.get("risk_per_trade_pct") == 0.5, f"Sai: {eff_pos.get('risk_per_trade_pct')}"
assert eff_pos.get("take_profit_rate") == 5.0, f"Sai: {eff_pos.get('take_profit_rate')}"

print("✅ TẤT CẢ ASSERTION ĐỀU PASS HOÀN HẢO!")
