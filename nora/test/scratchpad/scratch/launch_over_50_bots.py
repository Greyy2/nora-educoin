import urllib.request
import json
import time

url = "http://127.0.0.1:18010/api/studio/live/bot"

# 1. Fetch live candidates
req = urllib.request.Request("http://127.0.0.1:18010/api/studio/live/candidates")
with urllib.request.urlopen(req) as r:
    data = json.loads(r.read().decode())
    candidates = data.get("candidates", [])

print(f"Fetched {len(candidates)} candidate strategies.")

# Coins with local fast cached data
coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "AVAX"]

# We will launch 40 distinct candidate bots
to_launch = []
coin_idx = 0
for c in candidates:
    alpha_id = c["id"]
    tf = c.get("timeframe", "24h")
    book = c.get("book")
    symbol = coins[coin_idx % len(coins)]
    coin_idx += 1
    
    payload = {
        "mode": "paper",
        "alpha_id": alpha_id,
        "symbols": [symbol],
        "capital": 1000.0,
        "base_frame": "1m",
        "signal_tf": tf,
        "enter_on_start": True,
        "confirm_live": False
    }
    if book:
        payload["book_source"] = book
    to_launch.append(payload)
    if len(to_launch) >= 40:
        break

print(f"Prepared {len(to_launch)} bots to launch.")

success = 0
for idx, p in enumerate(to_launch):
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(p).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode())
            success += 1
            print(f"[{idx+1}/{len(to_launch)}] Launched bot {res.get('bot_id')} ({p['alpha_id']} on {p['symbols']})")
    except Exception as e:
        print(f"[{idx+1}/{len(to_launch)}] Failed to launch {p['alpha_id']}: {e}")
    time.sleep(0.4)

print(f"\nSuccessfully launched {success}/{len(to_launch)} bots!")
