"""Test cập nhật kết quả backtest vào 026f43441cb2.json và kiểm tra Market card"""
import sys, json
from pathlib import Path

EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")
sys.path.insert(0, str(EDU_ROOT))

from backend.jobs.tasks import run_custom
from backend.analys.alpha import store

alpha_file = EDU_ROOT / "data" / "alpha" / "user" / "026f43441cb2.json"
data = json.loads(alpha_file.read_text(encoding="utf-8"))

params = {
    "code": data["code"],
    "symbols": data["config"].get("symbols", ["BTC-USDT"]),
    "start": "2024-01-01",
    "end": "2026-09-01",
    "train_ratio": 0.8,
    "initial_capital": 10000.0,
    "run_frame": data["config"].get("run_frame", ""),
}

print("Đang chạy run_custom...")
res = run_custom(params)

# Cập nhật kết quả vào record
data["result"] = res
data["metrics"] = res.get("metrics", {})
data["final_equity"] = res.get("final_equity")
data["program_hash"] = res.get("program_hash")
data["backtest_status"] = "SUCCESS"
data["checklist"] = res.get("checklist", {})

alpha_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Đã ghi kết quả vào {alpha_file.name}!")

# Kiểm tra lại strategy_card
card = store.strategy_card(data)
print("\nCARD INDEX ĐÃ CẬP NHẬT:")
print(f"  ID: {card.get('id')}")
print(f"  Name: {card.get('name')}")
print(f"  Trades: {card.get('trades')}")
print(f"  Return: {card.get('ret_pct')}%")
print(f"  PnL USD: {card.get('pnl_usd')}")
print(f"  MDD: {card.get('mdd_pct')}%")
print(f"  Sharpe: {card.get('sharpe')}")
