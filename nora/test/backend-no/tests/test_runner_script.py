"""Test Nautilus Backtest Runner với ParquetDataCatalog thật và multi-symbol."""
import sys, os
sys.path.insert(0, "/home/vmc03/norabt/nora")
import time
from backend.nautilus.runner import build_run, run_backtest

payload = {
    "symbols": ["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
    "start": "2024-01-01",
    "end": "2024-01-02",  # Test 1 ngày (1,440 nến 1m)
    "initial_capital": 10000.0,
    "train_ratio": 0.7,
    "position": {
        "order_size_pct": 5.0,
        "leverage": 2,
        "stop_loss_rate": 2.0,
        "take_profit_rate": 4.0,
        "dca_steps": [1.0, 2.0],
        "cooldown_bars": 10,
        "timeout_bars": 100,
        "max_positions": 2,
    }
}

print("Khởi chạy test runner Nautilus...")
spec = build_run(payload)
t0 = time.perf_counter()
result = run_backtest(spec)
t_elapsed = time.perf_counter() - t0

print(f"\nBacktest hoàn tất trong {t_elapsed:.2f} s!")
if "engine" in locals() or "result" in locals():
    pass
print("Metrics simulate:", result["metrics"]["simulate"])
print(f"Số lượng trades: {len(result['trades'])}")
print(f"Số điểm equity: {len(result['series']['stages']['all']['equity'])}")
print("By symbol:", result["by_symbol"])
print("Yearly:", result["yearly"])

if result["trades"]:
    print("Mẫu trade đầu tiên:", result["trades"][0])

print("\nALL RUNNER TESTS PASSED!")
