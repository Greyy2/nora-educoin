import urllib.request, json, time

API = "http://127.0.0.1:18010"

def get_bots():
    try:
        req = urllib.request.urlopen(f"{API}/api/studio/live/bots", timeout=10)
        data = json.loads(req.read().decode())
        return data.get("bots", [])
    except Exception as e:
        print("Error fetching bots:", e)
        return []

def get_candidates():
    req = urllib.request.urlopen(f"{API}/api/studio/live/candidates", timeout=10)
    data = json.loads(req.read().decode())
    return data.get("candidates", [])

current_bots = get_bots()
active_count = sum(1 for b in current_bots if b.get("status") in ("running", "starting"))
print(f"Current active bots: {active_count}")

candidates = get_candidates()
candidates.sort(key=lambda x: (x.get("ret_pct") or 0) * (x.get("sharpe") or 0), reverse=True)

symbols_pool = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX"]

targets = []

# 1. DCA candidates (high Sharpe) across symbols
dca_cands = [c for c in candidates if c["id"] in ("dca_short", "dca_long")]
for c in dca_cands:
    for sym in symbols_pool:
        targets.append({
            "alpha_id": c["id"],
            "symbols": [sym],
            "signal_tf": c.get("timeframe") or "15m",
            "book_source": c.get("book") or "explore",
            "name": f"{c.get('name')} {c.get('side','')} {sym}"
        })

# 2. Profitable alpha library strategies (including Sova / KEMA / Trend Rider / DEMA / ATR stops)
user_cands = [c for c in candidates if c["id"] not in ("dca_short", "dca_long") and (c.get("ret_pct") or 0) > 0]
for idx, uc in enumerate(user_cands):
    for offset in [0, 2, 4]:
        sym = symbols_pool[(idx + offset) % len(symbols_pool)]
        targets.append({
            "alpha_id": uc["id"],
            "symbols": [sym],
            "signal_tf": uc.get("timeframe") or "24h",
            "book_source": None,
            "name": f"{uc.get('name', '')[:20]} {sym}"
        })

print(f"Total target configurations ready: {len(targets)}")

TARGET_TOTAL_ACTIVE = 55
launched = 0

for i, bt in enumerate(targets):
    # Check if we reached 55 active bots
    current_bots = get_bots()
    active_now = sum(1 for b in current_bots if b.get("status") in ("running", "starting"))
    if active_now >= TARGET_TOTAL_ACTIVE:
        print(f"Reached {active_now} active bots! Goal achieved.")
        break

    body = {
        "mode": "paper",
        "alpha_id": bt["alpha_id"],
        "symbols": bt["symbols"],
        "capital": 1000.0,
        "base_frame": "1m",
        "signal_tf": bt["signal_tf"],
        "enter_on_start": True,
        "confirm_live": False,
        "book_source": bt["book_source"]
    }

    try:
        req = urllib.request.Request(
            f"{API}/api/studio/live/bot",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read().decode())
            bid = res.get("bot_id")
            launched += 1
            print(f"[{active_now + 1}/{TARGET_TOTAL_ACTIVE}] Started {bid} ({bt['name']})")
        time.sleep(0.4)
    except Exception as e:
        print(f"Failed to start {bt['name']}: {e}")
        time.sleep(0.5)

print("\nFinished launch cycle.")
current_bots = get_bots()
active_final = sum(1 for b in current_bots if b.get("status") in ("running", "starting"))
print(f"Final active bots running: {active_final}")
