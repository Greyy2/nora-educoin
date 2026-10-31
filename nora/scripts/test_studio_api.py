#!/usr/bin/env python3
import requests
import json
import time
from pathlib import Path

payload = {
    "code": open("nora/edu/data/alpha/user/0d51ba8d2012.json").read(),
    "symbols": ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "TRX"],
    "start": "2023-10-06",
    "end": "2026-10-03",
    "train_ratio": 0.7,
    "initial_capital": 10000.0,
    "run_frame": "24h",
    "position": {
        "market": "perp", "leverage": 10, "exit_unit": "pct", "atr_frame": "24h", "atr_period": 14,
        "sizing": "risk", "risk_per_trade_pct": 0.5, "max_notional_pct": 300, "stop_fill": "level",
        "limit_through_pct": 0, "cooldown": 1440, "risk_profile": "legacy", "sl_anchor": "",
        "sl_beyond_last_pct": 0, "stop_loss_rate": 3.0, "take_profit_rate": 0, "trailing_stop": 0,
        "trailing_activation_pct": 0, "timeout": 0
    }
}
# Extract just the code string from json
data = json.loads(payload["code"])
payload["code"] = data["code"]

session = requests.Session()
r = session.post("http://127.0.0.1:18022/api/studio/custom/backtest", json=payload)
print("POST status:", r.status_code)
print("POST resp:", r.text)

if r.status_code == 200:
    res = r.json()
    job_id = res.get("job_id") or res.get("id")
    print("Submitted job:", job_id)
