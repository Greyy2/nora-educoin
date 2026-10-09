"""4H candles for every symbol with >=5 trades. Binance USDT-M futures first, OKX swap as fallback."""
import json, subprocess, time, sys, datetime as dt
START = int(dt.datetime(2025, 9, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
def curl(url):
    try:
        return json.loads(subprocess.run(["curl", "-s", "--max-time", "12", "-A", "Mozilla/5.0", url], capture_output=True, text=True, timeout=15).stdout)
    except Exception:
        return None
def binance(sym):
    out = []; start = START
    for _ in range(3):
        d = curl(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=4h&startTime={start}&limit=1500")
        if not isinstance(d, list) or not d: break
        out += [[int(k[0]), float(k[2]), float(k[3]), float(k[4])] for k in d]
        start = int(d[-1][0]) + 1
        if len(d) < 1500: break
        time.sleep(0.15)
    return out
def okx(sym):
    base = sym[:-4] if sym.endswith("USDT") else sym
    inst = f"{base}-USDT-SWAP"; out = []; after = ""
    for _ in range(30):
        d = curl(f"https://www.okx.com/api/v5/market/history-candles?instId={inst}&bar=4H&limit=100" + (f"&after={after}" if after else ""))
        rows = (d or {}).get("data") or []
        if not rows: break
        out += [[int(r[0]), float(r[2]), float(r[3]), float(r[4])] for r in rows]
        after = rows[-1][0]
        if int(after) < START: break
        time.sleep(0.12)
    return sorted(out)
need = json.load(open("symbols_needed.json")) + ["BTCUSDT"]
res = {}; src = {}
for i, s in enumerate(dict.fromkeys(need)):
    c = binance(s); where = "binance"
    if len(c) < 60:
        c = okx(s); where = "okx"
    if len(c) >= 60:
        res[s] = c; src[s] = where
    if i % 25 == 0: print(i, s, where, len(c), file=sys.stderr)
    time.sleep(0.1)
json.dump(res, open("candles_4h.json", "w")); json.dump(src, open("candles_src.json", "w"))
from collections import Counter
print("ok", len(res), "of", len(set(need)), Counter(src.values()))
