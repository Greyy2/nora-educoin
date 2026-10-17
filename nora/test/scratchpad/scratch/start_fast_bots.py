import urllib.request, json, time

# Select the top profitable strategies from live candidates:
# 1. dca_long (System, Sharpe: 6.3)
# 2. dca_short (System, Sharpe: 7.5)
# 3. 270e6e28416f (EMA Trend Rider, Sharpe: 1.43, Ret: 41.9%)
# 4. bf519617d973 (Double Exponential Moving Average DEMA, Sharpe: 1.42, Ret: 33.1%)
# 5. 7f3beda7b859 (Fixed Multiple ATR Volatility Stop, Sharpe: 1.33, Ret: 48.0%)
# 6. efb1fbe2db86 (Keltner Channel Trend KEMA, Sharpe: 1.24, Ret: 30.5%)
# 7. f261549d9efa (ROC Momentum Surge, Sharpe: 1.32, Ret: 32.9%)

symbols_8 = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX"]

configs = [
    {"alpha_id": "dca_long", "mode": "paper", "signal_tf": "15m", "name": "DCA Long (Paper)"},
    {"alpha_id": "dca_short", "mode": "paper", "signal_tf": "15m", "name": "DCA Short (Paper)"},
    {"alpha_id": "270e6e28416f", "mode": "paper", "signal_tf": "1h", "name": "EMA Trend Rider (Paper)"},
    {"alpha_id": "bf519617d973", "mode": "paper", "signal_tf": "1h", "name": "DEMA Double EMA (Paper)"},
    {"alpha_id": "7f3beda7b859", "mode": "paper", "signal_tf": "1h", "name": "ATR Volatility Stop (Paper)"},
    {"alpha_id": "efb1fbe2db86", "mode": "paper", "signal_tf": "1h", "name": "Keltner Channel Trend (Paper)"},
    {"alpha_id": "dca_short", "mode": "testnet", "signal_tf": "15m", "name": "DCA Short Hedge (Testnet)"},
]

started = []
for cfg in configs:
    body = {
        "mode": cfg["mode"],
        "alpha_id": cfg["alpha_id"],
        "symbols": symbols_8,
        "capital": 1000.0,
        "base_frame": "1m",
        "signal_tf": cfg["signal_tf"],
        "enter_on_start": True,
        "confirm_live": False,
        "book_source": "explore" if "dca" in cfg["alpha_id"] else None
    }
    try:
        url = "http://127.0.0.1:18010/api/studio/live/bot"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode())
            print(f"Started {cfg['name']} -> {res.get('bot_id')} (status: {res.get('status')})")
            started.append(res)
            time.sleep(1) # stagger launch by 1s to avoid burst
    except Exception as e:
        print(f"Error starting {cfg['name']}: {e}")

total_slots = len(started) * len(symbols_8)
print(f"\nSuccessfully started {len(started)} bots across {len(symbols_8)} symbols = {total_slots} active slots!")
