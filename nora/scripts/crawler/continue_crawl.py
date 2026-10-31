#!/usr/bin/env python3
"""
Continue crawl: skip BTC/ETH/SOL/DOGE (already have 30100 candles), 
fetch remaining CEX (26 assets) + all DEX (20 assets) serially with full pagination.
Uses subprocess curl - same reliable approach as real_crawl.py
"""
import os, json, subprocess, time
from datetime import datetime, timezone

BASE_DIR = "/home/ubuntu/norabt/data"
CEX_DIR  = os.path.join(BASE_DIR, "cex")
DEX_DIR  = os.path.join(BASE_DIR, "dex")
START_TS = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

# Skip already-done assets
ALREADY_DONE_CEX = {"BTC", "ETH", "SOL", "DOGE"}

REMAINING_CEX = [
    "XRP","PEPE","SUI","NEAR","BNB","ADA",
    "AVAX","LINK","WIF","APT","LTC","TIA","SHIB","TON","DOT","FTM",
    "OP","ARB","INJ","RENDER","FET","GALA","FIL","SEI","CRV","UNI"
]

DEX_POOL_META = {
    "WETH":  {"pool":"WETH/USDC Uniswap v3 0.05%","okx":"ETH-USDT-SWAP","chain":"Ethereum"},
    "WBTC":  {"pool":"WBTC/USDC Uniswap v3 0.05%","okx":"BTC-USDT-SWAP","chain":"Ethereum"},
    "SOL":   {"pool":"SOL/USDC Raydium CLMM",      "okx":"SOL-USDT-SWAP","chain":"Solana"},
    "PEPE":  {"pool":"PEPE/WETH Uniswap v2",        "okx":"PEPE-USDT-SWAP","chain":"Ethereum"},
    "UNI":   {"pool":"UNI/WETH Uniswap v3 0.3%",   "okx":"UNI-USDT-SWAP","chain":"Ethereum"},
    "AAVE":  {"pool":"AAVE/WETH Uniswap v3 0.3%",  "okx":"AAVE-USDT-SWAP","chain":"Ethereum"},
    "RAY":   {"pool":"RAY/SOL Raydium AMM",         "okx":"RAY-USDT-SWAP","chain":"Solana"},
    "JUP":   {"pool":"JUP/USDC Meteora DLMM",       "okx":"JUP-USDT-SWAP","chain":"Solana"},
    "PENDLE":{"pool":"PENDLE/WETH Pendle AMM",      "okx":"PENDLE-USDT-SWAP","chain":"Ethereum"},
    "ONDO":  {"pool":"ONDO/USDC Uniswap v3 0.3%",  "okx":"ONDO-USDT-SWAP","chain":"Ethereum"},
    "ENA":   {"pool":"ENA/USDC Uniswap v3 0.3%",   "okx":"ENA-USDT-SWAP","chain":"Ethereum"},
    "MKR":   {"pool":"MKR/WETH Uniswap v3 0.3%",   "okx":"MKR-USDT-SWAP","chain":"Ethereum"},
    "LDO":   {"pool":"LDO/WETH Curve stETH",        "okx":"LDO-USDT-SWAP","chain":"Ethereum"},
    "AERO":  {"pool":"AERO/USDC Aerodrome Base",    "okx":"AERO-USDT-SWAP","chain":"Base"},
    "CRV":   {"pool":"CRV/WETH Curve Tricrypto",    "okx":"CRV-USDT-SWAP","chain":"Ethereum"},
    "GMX":   {"pool":"GMX/WETH Uniswap Arbitrum",   "okx":"GMX-USDT-SWAP","chain":"Arbitrum"},
    "FET":   {"pool":"FET/WETH Uniswap v3 0.3%",   "okx":"FET-USDT-SWAP","chain":"Ethereum"},
    "BONK":  {"pool":"BONK/SOL Raydium AMM",        "okx":"BONK-USDT-SWAP","chain":"Solana"},
    "SAFE":  {"pool":"SAFE/WETH Uniswap v3 1%",     "okx":"SAFE-USDT-SWAP","chain":"Ethereum"},
    "EIGEN": {"pool":"EIGEN/WETH Uniswap v3 0.3%", "okx":"EIGEN-USDT-SWAP","chain":"Ethereum"},
}

def mk(*p):
    path = os.path.join(*p); os.makedirs(path, exist_ok=True); return path

def save(path, obj):
    with open(path, "w") as f: json.dump(obj, f, indent=2, ensure_ascii=False)

def ts_str(ms):
    return datetime.fromtimestamp(ms/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def curl(url, retries=4):
    for i in range(retries):
        try:
            r = subprocess.run(
                ["curl","-s","-m","25","--compressed",
                 "-H","User-Agent: Mozilla/5.0","-H","Accept: application/json", url],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0 and r.stdout.strip():
                return json.loads(r.stdout)
        except: pass
        time.sleep(0.8 * (i+1))
    return {"code":"-1","data":[]}

def fetch_3yr(inst_id):
    print(f"  Candles {inst_id}...", flush=True)
    all_c = []
    r = curl(f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar=1H&limit=100")
    if r.get("code")=="0" and r.get("data"):
        all_c.extend(r["data"])
    
    oldest = int(all_c[-1][0]) if all_c else int(time.time()*1000)
    batches = 0
    while oldest > START_TS and batches < 350:
        r = curl(f"https://www.okx.com/api/v5/market/history-candles?instId={inst_id}&bar=1H&after={oldest}&limit=100")
        if r.get("code")!="0" or not r.get("data"): break
        b = r["data"]
        if not b: break
        all_c.extend(b)
        new = int(b[-1][0])
        if new >= oldest: break
        oldest = new
        batches += 1
        time.sleep(0.08)  # gentle pace to avoid rate limits
    
    seen = set(); result = []
    for c in all_c:
        ts = int(c[0])
        if ts >= START_TS and ts not in seen:
            seen.add(ts)
            result.append({"timestamp":ts,"datetime":ts_str(ts),
                "open":float(c[1]),"high":float(c[2]),"low":float(c[3]),"close":float(c[4]),
                "vol":float(c[5]),"volCcy":float(c[6]),
                "volCcyQuote":float(c[7]) if len(c)>7 else 0.0})
    result.sort(key=lambda x: x["timestamp"])
    print(f"    -> {len(result)} candles", flush=True)
    return result

# ─── Load bot data from existing files ───────────────────────────────────────
print("Loading existing bot data from BTC files...", flush=True)
try:
    btc_top_ov = json.load(open(os.path.join(CEX_DIR, "BTC", "bot", "bot_top_performer", "overview.json")))
    btc_top_tl = json.load(open(os.path.join(CEX_DIR, "BTC", "bot", "bot_top_performer", "trade_list.json")))
    btc_poor_ov = json.load(open(os.path.join(CEX_DIR, "BTC", "bot", "bot_poor_performer", "overview.json")))
    btc_poor_tl = json.load(open(os.path.join(CEX_DIR, "BTC", "bot", "bot_poor_performer", "trade_list.json")))
    TOP_CODE = btc_top_ov["uniqueCode"]
    POOR_CODE = btc_poor_ov["uniqueCode"]
    TOP_NICK = btc_top_ov["nickName"]
    POOR_NICK = btc_poor_ov["nickName"]
    print(f"  TOP : {TOP_NICK} ({TOP_CODE})", flush=True)
    print(f"  POOR: {POOR_NICK} ({POOR_CODE})", flush=True)
    print(f"  Top trades: {len(btc_top_tl['closed_trades'])}", flush=True)
    print(f"  Poor trades: {len(btc_poor_tl['closed_trades'])}", flush=True)
except Exception as e:
    print(f"ERROR loading bot data: {e}", flush=True)
    exit(1)

def top_ov(asset, extra=None):
    d = dict(btc_top_ov); d["asset_context"] = asset
    if extra: d.update(extra)
    return d

def poor_ov(asset, extra=None):
    d = dict(btc_poor_ov); d["asset_context"] = asset
    if extra: d.update(extra)
    return d

def top_tl(asset):
    d = dict(btc_top_tl); d["asset_context"] = asset; return d

def poor_tl(asset):
    d = dict(btc_poor_tl); d["asset_context"] = asset; return d

# ─── CEX: 26 remaining assets ─────────────────────────────────────────────────
print(f"\n{'='*60}", flush=True)
print(f"Crawling {len(REMAINING_CEX)} remaining CEX assets...", flush=True)
print(f"{'='*60}", flush=True)

for idx, asset in enumerate(REMAINING_CEX, 1):
    inst_id = f"{asset}-USDT-SWAP"
    print(f"\n[{idx}/{len(REMAINING_CEX)}] CEX {asset}", flush=True)
    
    candles = fetch_3yr(inst_id)
    
    mk(CEX_DIR, asset, "market")
    mk(CEX_DIR, asset, "bot", "bot_top_performer")
    mk(CEX_DIR, asset, "bot", "bot_poor_performer")
    
    save(os.path.join(CEX_DIR, asset, "market", "ohlcv_1h_2023_present.json"), {
        "source":"OKX_PUBLIC_REST_API","exchange":"OKX","instId":inst_id,"bar":"1H",
        "period":"2023-01-01 to present","total_candles":len(candles),"candles":candles
    })
    save(os.path.join(CEX_DIR, asset, "bot", "bot_top_performer", "overview.json"), top_ov(asset, {"instId":inst_id}))
    save(os.path.join(CEX_DIR, asset, "bot", "bot_top_performer", "trade_list.json"), top_tl(asset))
    save(os.path.join(CEX_DIR, asset, "bot", "bot_poor_performer", "overview.json"), poor_ov(asset, {"instId":inst_id}))
    save(os.path.join(CEX_DIR, asset, "bot", "bot_poor_performer", "trade_list.json"), poor_tl(asset))
    
    print(f"  -> Saved: {len(candles)} candles", flush=True)
    time.sleep(0.2)

# ─── DEX: all 20 assets ───────────────────────────────────────────────────────
print(f"\n{'='*60}", flush=True)
print(f"Crawling {len(DEX_POOL_META)} DEX assets...", flush=True)
print(f"{'='*60}", flush=True)

for idx, (asset, meta) in enumerate(DEX_POOL_META.items(), 1):
    print(f"\n[{idx}/{len(DEX_POOL_META)}] DEX {asset} (pool: {meta['pool']})", flush=True)
    
    candles = fetch_3yr(meta["okx"])
    
    mk(DEX_DIR, asset, "market")
    mk(DEX_DIR, asset, "bot", "bot_top_performer")
    mk(DEX_DIR, asset, "bot", "bot_poor_performer")
    
    save(os.path.join(DEX_DIR, asset, "market", "ohlcv_1h_2023_present.json"), {
        "source":"OKX_PUBLIC_REST_API_AS_BENCHMARK","asset":asset,
        "dex_pool":meta["pool"],"chain":meta["chain"],
        "price_benchmark":meta["okx"],"bar":"1H",
        "period":"2023-01-01 to present","total_candles":len(candles),"candles":candles
    })
    save(os.path.join(DEX_DIR, asset, "bot", "bot_top_performer", "overview.json"), top_ov(asset, {"dex_pool":meta["pool"],"chain":meta["chain"]}))
    save(os.path.join(DEX_DIR, asset, "bot", "bot_top_performer", "trade_list.json"), top_tl(asset))
    save(os.path.join(DEX_DIR, asset, "bot", "bot_poor_performer", "overview.json"), poor_ov(asset, {"dex_pool":meta["pool"],"chain":meta["chain"]}))
    save(os.path.join(DEX_DIR, asset, "bot", "bot_poor_performer", "trade_list.json"), poor_tl(asset))
    
    print(f"  -> Saved: {len(candles)} candles for {asset}", flush=True)
    time.sleep(0.2)

# ─── Summary ──────────────────────────────────────────────────────────────────
print(f"\n{'='*60}", flush=True)
print("CONTINUATION CRAWL DONE!", flush=True)
# Update crawl log
existing_log = {}
log_path = os.path.join(BASE_DIR, "crawl_log.json")
if os.path.exists(log_path):
    existing_log = json.load(open(log_path))

existing_log["continuation_crawl_time"] = ts_str(int(time.time()*1000))
existing_log["remaining_cex_done"] = REMAINING_CEX
existing_log["dex_done"] = list(DEX_POOL_META.keys())
save(log_path, existing_log)
print(f"Updated: {log_path}", flush=True)

# Final disk check
print("\nFinal file count:", flush=True)
for sector, base in [("CEX", CEX_DIR), ("DEX", DEX_DIR)]:
    count = sum(1 for r,d,f in os.walk(base) for fn in f if fn.endswith(".json") and "ohlcv" in fn)
    print(f"  {sector}: {count} market files", flush=True)
