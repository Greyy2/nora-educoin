#!/usr/bin/env python3
"""
Fast parallel OKX crawler: ThreadPoolExecutor + subprocess curl
No extra dependencies needed - uses only stdlib
Fetches 3yr 1H candles for all 50 assets in parallel
"""
import os, json, subprocess, time, sys
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

BASE_DIR = "/home/ubuntu/norabt/data"
CEX_DIR  = os.path.join(BASE_DIR, "cex")
DEX_DIR  = os.path.join(BASE_DIR, "dex")
START_TS = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

TOP_30_CEX = [
    "BTC","ETH","SOL","DOGE","XRP","PEPE","SUI","NEAR","BNB","ADA",
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

print_lock = Lock()

def log(msg):
    with print_lock:
        print(msg, flush=True)

def ts_str(ms):
    return datetime.fromtimestamp(ms/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def mk(*p):
    path = os.path.join(*p)
    os.makedirs(path, exist_ok=True)
    return path

def save(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def curl(url, retries=4):
    for i in range(retries):
        try:
            r = subprocess.run(
                ["curl","-s","-m","20","--compressed",
                 "-H","User-Agent: Mozilla/5.0",
                 "-H","Accept: application/json",
                 url],
                capture_output=True, text=True, timeout=25
            )
            if r.returncode == 0 and r.stdout.strip():
                return json.loads(r.stdout)
        except:
            pass
        time.sleep(0.5 * (i+1))
    return {"code":"-1","data":[]}

# ─── FETCH 3YR CANDLES (single-threaded per asset, called from thread pool) ──
def fetch_3yr_candles(inst_id):
    all_c = []
    r = curl(f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar=1H&limit=100")
    if r.get("code") == "0" and r.get("data"):
        all_c.extend(r["data"])
    
    oldest = int(all_c[-1][0]) if all_c else int(time.time()*1000)
    batches = 0
    while oldest > START_TS and batches < 280:
        r = curl(f"https://www.okx.com/api/v5/market/history-candles?instId={inst_id}&bar=1H&after={oldest}&limit=100")
        if r.get("code") != "0" or not r.get("data"):
            break
        b = r["data"]
        if not b: break
        all_c.extend(b)
        new = int(b[-1][0])
        if new >= oldest: break
        oldest = new
        batches += 1
        time.sleep(0.02)
    
    seen = set()
    result = []
    for c in all_c:
        ts = int(c[0])
        if ts >= START_TS and ts not in seen:
            seen.add(ts)
            result.append({
                "timestamp": ts, "datetime": ts_str(ts),
                "open": float(c[1]), "high": float(c[2]),
                "low": float(c[3]), "close": float(c[4]),
                "vol": float(c[5]), "volCcy": float(c[6]),
                "volCcyQuote": float(c[7]) if len(c)>7 else 0.0
            })
    result.sort(key=lambda x: x["timestamp"])
    log(f"  [{inst_id}] -> {len(result)} candles")
    return result

# ─── FETCH BOT DATA ──────────────────────────────────────────────────────────
def fetch_bot(unique_code, nick):
    r1 = curl(f"https://www.okx.com/api/v5/copytrading/public-weekly-pnl?uniqueCode={unique_code}&instType=SWAP")
    weekly = r1.get("data",[]) if r1.get("code")=="0" else []
    
    r2 = curl(f"https://www.okx.com/api/v5/copytrading/public-current-subpositions?uniqueCode={unique_code}&instType=SWAP")
    open_pos = r2.get("data",[]) if r2.get("code")=="0" else []
    
    history = []
    after_id = None
    for _ in range(25):
        url = f"https://www.okx.com/api/v5/copytrading/public-subpositions-history?uniqueCode={unique_code}&instType=SWAP&limit=100"
        if after_id: url += f"&after={after_id}"
        r3 = curl(url)
        if r3.get("code")!="0" or not r3.get("data"): break
        b = r3["data"]
        history.extend(b)
        if len(b)<100: break
        after_id = b[-1].get("subPosId")
        time.sleep(0.1)
    
    log(f"  Bot '{nick}': weekly={len(weekly)}, open={len(open_pos)}, history={len(history)}")
    return weekly, open_pos, history

def enrich_trade(raw):
    inst = raw.get("instId","")
    asset = inst.replace("-USDT-SWAP","").replace("-USD-SWAP","").replace("-USDT","")
    open_ts = int(raw.get("openTime",0)) if raw.get("openTime") else None
    ctime = raw.get("closeTime","")
    close_ts = int(ctime) if ctime and ctime.strip() and ctime!="0" else None
    
    opx = float(raw.get("openAvgPx",0))
    cpx = float(raw.get("closeAvgPx",0))
    side = raw.get("posSide","long")
    lever = raw.get("lever","1")
    margin = float(raw.get("margin",0))
    size = float(raw.get("subPos",0))
    pnl = float(raw.get("pnl",0))
    pnl_r = float(raw.get("pnlRatio",0))
    
    hold_h = round((close_ts-open_ts)/3_600_000,2) if open_ts and close_ts and close_ts>open_ts else None
    px_chg = f"{round((cpx-opx)/opx*100,3)}%" if opx else "n/a"
    
    return {
        "trade_id": raw.get("subPosId"),
        "asset": asset,
        "instId": inst,
        "direction": side.upper(),
        "entry_exit": f"{'BUY' if side=='long' else 'SHORT'} @ {opx} → {'SELL' if side=='long' else 'COVER'} @ {cpx}",
        "expected_move": "PRICE UP" if side=="long" else "PRICE DOWN",
        "leverage": lever,
        "margin_usdt": round(margin,4),
        "position_size": round(size,6),
        "entry_price": opx,
        "exit_price": cpx,
        "price_change_pct": px_chg,
        "open_time": ts_str(open_ts) if open_ts else None,
        "close_time": ts_str(close_ts) if close_ts else "STILL_OPEN",
        "hold_duration_hours": hold_h,
        "pnl_usdt": round(pnl,4),
        "pnl_pct_of_margin": f"{round(pnl_r*100,3)}%",
        "result": "WIN" if pnl>0 else ("LOSS" if pnl<0 else "BREAK_EVEN"),
        "ccy": raw.get("ccy","USDT"),
    }

def enrich_open(raw):
    inst = raw.get("instId","")
    asset = inst.replace("-USDT-SWAP","").replace("-USD-SWAP","")
    opx = float(raw.get("openAvgPx",0))
    mpx = float(raw.get("markPx",0))
    side = raw.get("posSide","long")
    upl = float(raw.get("upl",0))
    upl_r = float(raw.get("uplRatio",0))
    open_ts = int(raw.get("openTime",0))
    return {
        "status": "OPEN",
        "trade_id": raw.get("subPosId"),
        "asset": asset,
        "instId": inst,
        "direction": side.upper(),
        "leverage": raw.get("lever","1"),
        "margin_usdt": round(float(raw.get("margin",0)),4),
        "position_size": round(float(raw.get("subPos",0)),6),
        "entry_price": opx,
        "current_mark_price": mpx,
        "price_move_pct": f"{round((mpx-opx)/opx*100,3)}%" if opx else "n/a",
        "open_time": ts_str(open_ts),
        "unrealized_pnl_usdt": round(upl,4),
        "unrealized_pnl_pct": f"{round(upl_r*100,3)}%",
        "note": "Live position at crawl time",
    }

# ─── MAIN ────────────────────────────────────────────────────────────────────
t0 = time.time()
print("="*60, flush=True)
print("STEP 1: Fetching OKX lead traders...", flush=True)

all_traders = []
for pg in range(1,27):
    r = curl(f"https://www.okx.com/api/v5/copytrading/public-lead-traders?instType=SWAP&page={pg}")
    if r.get("code")=="0":
        ranks = r.get("data",[{}])[0].get("ranks",[])
        if not ranks: break
        all_traders.extend(ranks)
    time.sleep(0.1)

print(f"  Total traders: {len(all_traders)}", flush=True)
active = [t for t in all_traders if int(t.get("leadDays",0))>=30]
by_pnl = sorted(active, key=lambda x: float(x.get("pnl",0)), reverse=True)

TOP = by_pnl[0]
neg = [t for t in by_pnl if float(t.get("pnl",0))<0]
POOR = neg[0] if neg else by_pnl[-1]

print(f"  TOP : {TOP['nickName']} ({TOP['uniqueCode']}) PnL={float(TOP['pnl']):.0f}", flush=True)
print(f"  POOR: {POOR['nickName']} ({POOR['uniqueCode']}) PnL={float(POOR['pnl']):.0f}", flush=True)

print("\nSTEP 2: Fetching bot trade history...", flush=True)
top_weekly, top_open_raw, top_hist = fetch_bot(TOP["uniqueCode"], TOP["nickName"])
poor_weekly, poor_open_raw, poor_hist = fetch_bot(POOR["uniqueCode"], POOR["nickName"])

top_open   = [enrich_open(p) for p in top_open_raw]
top_trades = [enrich_trade(t) for t in top_hist]
poor_open  = [enrich_open(p) for p in poor_open_raw]
poor_trades= [enrich_trade(t) for t in poor_hist]

def fmt_w(w):
    return [{"week_start":ts_str(int(x["beginTs"])),"pnl_usdt":float(x["pnl"]),"roi_pct":f"{float(x['pnlRatio'])*100:.2f}%"} for x in w]

field_guide = {
    "direction":         "LONG = buy expecting UP | SHORT = sell expecting DOWN",
    "entry_exit":        "open→close price summary",
    "leverage":          "Multiplier applied to margin",
    "margin_usdt":       "Collateral deposited (USDT)",
    "entry_price":       "Price when position opened",
    "exit_price":        "Price when position closed",
    "hold_duration_hours":"Hours position was held",
    "pnl_usdt":          "Profit(+) or Loss(-) in USDT",
    "pnl_pct_of_margin": "Return on margin used (%)",
    "result":            "WIN | LOSS | BREAK_EVEN",
}

def top_ov(asset, extra=None):
    d = {
        "source":"OKX_PUBLIC_REST_API_REAL_DATA",
        "crawled_at": ts_str(int(time.time()*1000)),
        "tier":"TOP_PERFORMER",
        "exchange":"OKX","instType":"SWAP",
        "asset_context": asset,
        "nickName": TOP["nickName"],
        "uniqueCode": TOP["uniqueCode"],
        "pnl_usdt": float(TOP["pnl"]),
        "pnl_pct": f"{float(TOP['pnlRatio'])*100:.2f}%",
        "winRatio": float(TOP["winRatio"]),
        "win_pct": f"{float(TOP['winRatio'])*100:.1f}%",
        "aum_usdt": float(TOP["aum"]),
        "leadDays": int(TOP["leadDays"]),
        "copyTraderNum": int(TOP["copyTraderNum"]),
        "maxCopyTraderNum": int(TOP["maxCopyTraderNum"]),
        "traderInsts": TOP.get("traderInsts",[]),
        "weekly_pnl": fmt_w(top_weekly),
        "open_positions_now": len(top_open),
        "total_closed_trades": len(top_trades),
        "okx_profile_url": f"https://www.okx.com/copy-trading/trader/{TOP['uniqueCode']}",
    }
    if extra: d.update(extra)
    return d

def poor_ov(asset, extra=None):
    d = {
        "source":"OKX_PUBLIC_REST_API_REAL_DATA",
        "crawled_at": ts_str(int(time.time()*1000)),
        "tier":"POOR_PERFORMER",
        "exchange":"OKX","instType":"SWAP",
        "asset_context": asset,
        "nickName": POOR["nickName"],
        "uniqueCode": POOR["uniqueCode"],
        "pnl_usdt": float(POOR["pnl"]),
        "pnl_pct": f"{float(POOR['pnlRatio'])*100:.2f}%",
        "winRatio": float(POOR["winRatio"]),
        "win_pct": f"{float(POOR['winRatio'])*100:.1f}%",
        "aum_usdt": float(POOR["aum"]),
        "leadDays": int(POOR["leadDays"]),
        "copyTraderNum": int(POOR["copyTraderNum"]),
        "weekly_pnl": fmt_w(poor_weekly),
        "open_positions_now": len(poor_open),
        "total_closed_trades": len(poor_trades),
        "okx_profile_url": f"https://www.okx.com/copy-trading/trader/{POOR['uniqueCode']}",
    }
    if extra: d.update(extra)
    return d

def top_tl(asset):
    return {"source":"OKX_PUBLIC_REST_API","uniqueCode":TOP["uniqueCode"],"nickName":TOP["nickName"],
            "asset_context":asset,"field_guide":field_guide,
            "open_positions":top_open,"closed_trades_count":len(top_trades),"closed_trades":top_trades}

def poor_tl(asset):
    return {"source":"OKX_PUBLIC_REST_API","uniqueCode":POOR["uniqueCode"],"nickName":POOR["nickName"],
            "asset_context":asset,"field_guide":field_guide,
            "open_positions":poor_open,"closed_trades_count":len(poor_trades),"closed_trades":poor_trades}

# ─── PARALLEL CANDLE FETCH ────────────────────────────────────────────────────
print("\nSTEP 3: Fetching 3yr 1H candles in parallel (8 workers)...", flush=True)

all_jobs = []
for asset in TOP_30_CEX:
    all_jobs.append(("cex", asset, f"{asset}-USDT-SWAP", None))
for asset, meta in DEX_POOL_META.items():
    all_jobs.append(("dex", asset, meta["okx"], meta))

candle_map = {}  # key = (sector, asset) -> candles
done = 0
total = len(all_jobs)

with ThreadPoolExecutor(max_workers=8) as ex:
    futures = {ex.submit(fetch_3yr_candles, job[2]): job for job in all_jobs}
    for fut in as_completed(futures):
        sector, asset, inst_id, meta = futures[fut]
        candles = fut.result()
        candle_map[(sector, asset)] = candles
        done += 1
        log(f"  [{done}/{total}] {sector.upper()} {asset}: {len(candles)} candles ✓")

# ─── SAVE ALL FILES ───────────────────────────────────────────────────────────
print("\nSTEP 4: Saving CEX files...", flush=True)
for asset in TOP_30_CEX:
    candles = candle_map[("cex", asset)]
    inst_id = f"{asset}-USDT-SWAP"
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
    print(f"  [CEX] {asset} saved", flush=True)

print("\nSTEP 5: Saving DEX files...", flush=True)
for asset, meta in DEX_POOL_META.items():
    candles = candle_map[("dex", asset)]
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
    print(f"  [DEX] {asset} saved", flush=True)

elapsed = round(time.time()-t0,1)
save(os.path.join(BASE_DIR, "crawl_log.json"), {
    "crawl_time": ts_str(int(time.time()*1000)),
    "elapsed_seconds": elapsed,
    "top_bot":{"nickName":TOP["nickName"],"uniqueCode":TOP["uniqueCode"],
               "pnl_usdt":float(TOP["pnl"]),"winRatio":float(TOP["winRatio"]),"leadDays":int(TOP["leadDays"]),
               "open_positions":len(top_open),"closed_trades":len(top_trades),
               "verify_url":f"https://www.okx.com/copy-trading/trader/{TOP['uniqueCode']}"},
    "poor_bot":{"nickName":POOR["nickName"],"uniqueCode":POOR["uniqueCode"],
                "pnl_usdt":float(POOR["pnl"]),"winRatio":float(POOR["winRatio"]),"leadDays":int(POOR["leadDays"]),
                "open_positions":len(poor_open),"closed_trades":len(poor_trades),
                "verify_url":f"https://www.okx.com/copy-trading/trader/{POOR['uniqueCode']}"},
    "cex_assets":{a:len(candle_map[("cex",a)]) for a in TOP_30_CEX},
    "dex_assets":{a:len(candle_map[("dex",a)]) for a in DEX_POOL_META},
})

print(f"\n{'='*60}", flush=True)
print(f"ALL DONE! Elapsed: {elapsed}s", flush=True)
print(f"TOP BOT  : {TOP['nickName']} — https://www.okx.com/copy-trading/trader/{TOP['uniqueCode']}", flush=True)
print(f"POOR BOT : {POOR['nickName']} — https://www.okx.com/copy-trading/trader/{POOR['uniqueCode']}", flush=True)
print(f"CEX: {len(TOP_30_CEX)} assets | DEX: {len(DEX_POOL_META)} assets", flush=True)
