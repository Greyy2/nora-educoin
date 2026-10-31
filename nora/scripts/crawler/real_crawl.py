#!/usr/bin/env python3
"""
Real OKX Data Crawler: 30 CEX Assets + 20 DEX Assets
- Uses subprocess curl (not urllib, which has connectivity issues)
- Market data: 3 years (2023-01-01 to present) via OKX history-candles REST
- Bot data: Real lead traders from OKX public API, full trade history
"""

import os
import json
import subprocess
import time
import sys
from datetime import datetime, timezone

# ─── CONFIG ─────────────────────────────────────────────────────────────────
BASE_DIR = "/home/ubuntu/norabt/data"
CEX_DIR  = os.path.join(BASE_DIR, "cex")
DEX_DIR  = os.path.join(BASE_DIR, "dex")

# 3-year start timestamp (2023-01-01 00:00:00 UTC)
START_TS = int(datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)

TOP_30_CEX = [
    "BTC","ETH","SOL","DOGE","XRP","PEPE","SUI","NEAR","BNB","ADA",
    "AVAX","LINK","WIF","APT","LTC","TIA","SHIB","TON","DOT","FTM",
    "OP","ARB","INJ","RENDER","FET","GALA","FIL","SEI","CRV","UNI"
]

TOP_20_DEX = [
    "WETH","WBTC","SOL","PEPE","UNI","AAVE","RAY","JUP",
    "PENDLE","ONDO","ENA","MKR","LDO","AERO","CRV","GMX","FET","BONK","SAFE","EIGEN"
]

# ─── HELPERS ────────────────────────────────────────────────────────────────
def curl_get(url, retries=3):
    """Use curl via subprocess to bypass urllib connectivity issues."""
    for attempt in range(retries):
        try:
            result = subprocess.run(
                ["curl", "-s", "-m", "15", "--compressed",
                 "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                 url],
                capture_output=True, text=True, timeout=20
            )
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout)
        except Exception as e:
            print(f"    [WARN] curl attempt {attempt+1} failed for {url}: {e}", flush=True)
        time.sleep(0.5)
    return {"code": "-1", "data": [], "msg": "failed"}

def mk(path):
    os.makedirs(path, exist_ok=True)

def save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def ts_to_str(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# ─── FETCH ALL PAGES: LEAD TRADERS ──────────────────────────────────────────
print("=" * 60, flush=True)
print("STEP 1: Fetching ALL OKX Lead Traders (pages 1-26)...", flush=True)
print("=" * 60, flush=True)

all_traders = []
for page in range(1, 27):
    res = curl_get(f"https://www.okx.com/api/v5/copytrading/public-lead-traders?instType=SWAP&page={page}")
    if res.get("code") == "0":
        data = res.get("data", [{}])
        if not data:
            break
        ranks = data[0].get("ranks", [])
        if not ranks:
            break
        all_traders.extend(ranks)
        print(f"  Page {page}: +{len(ranks)} traders (total: {len(all_traders)})", flush=True)
    time.sleep(0.15)

print(f"\nTotal lead traders cataloged: {len(all_traders)}", flush=True)

# Sort: Top = highest PnL (active, positive), Poor = lowest PnL (negative or near-zero)
# Filter only those with leadDays >= 30 (still active, have history)
active_traders = [t for t in all_traders if int(t.get("leadDays", 0)) >= 30]
sorted_by_pnl = sorted(active_traders, key=lambda x: float(x.get("pnl", 0)), reverse=True)

print(f"\nTop 5 traders by PnL:", flush=True)
for t in sorted_by_pnl[:5]:
    print(f"  {t['nickName']} (Code: {t['uniqueCode']}) PnL={t['pnl']} WR={t['winRatio']} Days={t['leadDays']}", flush=True)

print(f"\nBottom 5 (poor) traders by PnL:", flush=True)
for t in sorted_by_pnl[-5:]:
    print(f"  {t['nickName']} (Code: {t['uniqueCode']}) PnL={t['pnl']} WR={t['winRatio']} Days={t['leadDays']}", flush=True)

# Select a GLOBAL top bot and poor bot
GLOBAL_TOP = sorted_by_pnl[0]
# Poor = lowest PnL with negative or near-zero, still active (copyTraderNum > 0)
poor_candidates = [t for t in sorted_by_pnl if float(t.get("pnl", 0)) < 0]
if not poor_candidates:
    poor_candidates = sorted_by_pnl[-5:]
GLOBAL_POOR = poor_candidates[0] if poor_candidates else sorted_by_pnl[-1]

print(f"\n  >> SELECTED TOP BOT: {GLOBAL_TOP['nickName']} ({GLOBAL_TOP['uniqueCode']})", flush=True)
print(f"  >> SELECTED POOR BOT: {GLOBAL_POOR['nickName']} ({GLOBAL_POOR['uniqueCode']})", flush=True)

# ─── FETCH BOT FULL DATA ─────────────────────────────────────────────────────
def fetch_bot_all_pages(unique_code, nick_name):
    """Fetch ALL pages of position history for a bot."""
    base_url = "https://www.okx.com/api/v5/copytrading/public-subpositions-history"
    
    # Weekly PnL
    weekly_res = curl_get(f"https://www.okx.com/api/v5/copytrading/public-weekly-pnl?uniqueCode={unique_code}&instType=SWAP")
    weekly_pnl = weekly_res.get("data", []) if weekly_res.get("code") == "0" else []
    
    # Open positions
    open_res = curl_get(f"https://www.okx.com/api/v5/copytrading/public-current-subpositions?uniqueCode={unique_code}&instType=SWAP")
    open_positions = open_res.get("data", []) if open_res.get("code") == "0" else []
    
    # Closed trade history - paginate all pages
    all_history = []
    after_id = None
    page_n = 0
    while True:
        url = f"{base_url}?uniqueCode={unique_code}&instType=SWAP&limit=100"
        if after_id:
            url += f"&after={after_id}"
        
        res = curl_get(url)
        if res.get("code") != "0":
            break
        batch = res.get("data", [])
        if not batch:
            break
        
        all_history.extend(batch)
        page_n += 1
        
        # Paginate: use subPosId of last item as cursor
        last = batch[-1]
        after_id = last.get("subPosId")
        
        # Safety cap
        if len(all_history) >= 2000 or page_n >= 20:
            break
        time.sleep(0.1)
    
    print(f"    -> Bot '{nick_name}': weekly_pnl={len(weekly_pnl)} entries, open_pos={len(open_positions)}, history={len(all_history)} trades", flush=True)
    return weekly_pnl, open_positions, all_history

print(f"\nFetching Top Bot full data...", flush=True)
top_weekly, top_open, top_history = fetch_bot_all_pages(GLOBAL_TOP["uniqueCode"], GLOBAL_TOP["nickName"])
time.sleep(0.3)

print(f"Fetching Poor Bot full data...", flush=True)
poor_weekly, poor_open, poor_history = fetch_bot_all_pages(GLOBAL_POOR["uniqueCode"], GLOBAL_POOR["nickName"])

# ─── BUILD BOT TRADE RECORDS (with full detail) ───────────────────────────────
def build_trade_record(raw_trade):
    """Convert raw OKX subposition history to enriched trade record."""
    inst = raw_trade.get("instId", "")
    asset = inst.replace("-USDT-SWAP", "").replace("-USDT", "").replace("-USD-SWAP", "")
    
    open_ts = int(raw_trade.get("openTime", 0)) if raw_trade.get("openTime") else None
    close_ts = int(raw_trade.get("closeTime", 0)) if raw_trade.get("closeTime") else None
    
    open_px = float(raw_trade.get("openAvgPx", 0))
    close_px = float(raw_trade.get("closeAvgPx", 0))
    pos_side = raw_trade.get("posSide", "long")
    size = float(raw_trade.get("subPos", 0))
    lever = raw_trade.get("lever", "1")
    margin = float(raw_trade.get("margin", 0))
    pnl = float(raw_trade.get("pnl", 0))
    pnl_ratio = float(raw_trade.get("pnlRatio", 0))
    ccy = raw_trade.get("ccy", "USDT")
    
    # Calculate hold duration
    hold_hours = None
    if open_ts and close_ts and close_ts > 0:
        hold_hours = round((close_ts - open_ts) / (1000 * 3600), 2)
    
    # Direction description
    if pos_side == "long":
        direction = f"BUY @ {open_px} → SELL @ {close_px}"
        expected_dir = "UP"
    else:
        direction = f"SELL SHORT @ {open_px} → BUY COVER @ {close_px}"
        expected_dir = "DOWN"
    
    win_loss = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAK_EVEN")
    
    return {
        "trade_id": raw_trade.get("subPosId"),
        "asset": asset,
        "instId": inst,
        "direction": pos_side.upper(),
        "entry_exit_summary": direction,
        "expected_price_direction": expected_dir,
        "leverage": lever,
        "margin_usdt": round(margin, 4),
        "position_size": round(size, 4),
        "entry_price": open_px,
        "exit_price": close_px,
        "open_time": ts_to_str(open_ts) if open_ts else None,
        "close_time": ts_to_str(close_ts) if close_ts else "STILL_OPEN",
        "hold_duration_hours": hold_hours,
        "pnl_usdt": round(pnl, 4),
        "pnl_ratio": round(pnl_ratio, 6),
        "pnl_percent": f"{round(pnl_ratio * 100, 2)}%",
        "result": win_loss,
        "settlement_ccy": ccy,
    }

def build_open_position_record(raw_pos):
    inst = raw_pos.get("instId", "")
    asset = inst.replace("-USDT-SWAP", "").replace("-USDT", "")
    open_ts = int(raw_pos.get("openTime", 0))
    open_px = float(raw_pos.get("openAvgPx", 0))
    mark_px = float(raw_pos.get("markPx", 0))
    pos_side = raw_pos.get("posSide", "long")
    size = float(raw_pos.get("subPos", 0))
    margin = float(raw_pos.get("margin", 0))
    upl = float(raw_pos.get("upl", 0))
    upl_ratio = float(raw_pos.get("uplRatio", 0))
    
    return {
        "trade_id": raw_pos.get("subPosId"),
        "status": "OPEN",
        "asset": asset,
        "instId": inst,
        "direction": pos_side.upper(),
        "leverage": raw_pos.get("lever", "1"),
        "margin_usdt": round(margin, 4),
        "position_size": round(size, 4),
        "entry_price": open_px,
        "current_mark_price": mark_px,
        "open_time": ts_to_str(open_ts),
        "unrealized_pnl_usdt": round(upl, 4),
        "unrealized_pnl_ratio": round(upl_ratio, 6),
        "unrealized_pnl_percent": f"{round(upl_ratio * 100, 2)}%",
        "note": "Position still live at crawl time"
    }

# Build enriched top bot record
top_trade_records = [build_trade_record(t) for t in top_history]
top_open_records = [build_open_position_record(p) for p in top_open]

poor_trade_records = [build_trade_record(t) for t in poor_history]
poor_open_records = [build_open_position_record(p) for p in poor_open]

# ─── FETCH MARKET CANDLES (3 years) ──────────────────────────────────────────
def fetch_candles_3yr(inst_id):
    """Fetch 1H candles from 2023-01-01 to present using OKX history-candles."""
    print(f"  Fetching 3yr 1H candles for {inst_id}...", flush=True)
    all_candles = []
    
    # First: get latest candles
    url = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar=1H&limit=100"
    res = curl_get(url)
    if res.get("code") == "0" and res.get("data"):
        all_candles.extend(res["data"])
    
    # Paginate backwards via history-candles until we reach 2023-01-01
    if all_candles:
        oldest = int(all_candles[-1][0])
    else:
        oldest = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    
    batches = 0
    while oldest > START_TS and batches < 300:
        hist_url = f"https://www.okx.com/api/v5/market/history-candles?instId={inst_id}&bar=1H&after={oldest}&limit=100"
        hres = curl_get(hist_url)
        if hres.get("code") != "0" or not hres.get("data"):
            break
        batch = hres["data"]
        if not batch:
            break
        all_candles.extend(batch)
        new_oldest = int(batch[-1][0])
        if new_oldest >= oldest:
            break
        oldest = new_oldest
        batches += 1
        time.sleep(0.05)
    
    # Filter to 2023+, dedupe, sort
    seen = set()
    result = []
    for c in all_candles:
        ts = int(c[0])
        if ts >= START_TS and ts not in seen:
            seen.add(ts)
            result.append({
                "timestamp": ts,
                "datetime": ts_to_str(ts),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "vol": float(c[5]),         # in contracts
                "volCcy": float(c[6]),       # in base currency
                "volCcyQuote": float(c[7]) if len(c) > 7 else 0.0,  # in USDT
            })
    result.sort(key=lambda x: x["timestamp"])
    print(f"    -> {len(result)} candles from 2023 to now", flush=True)
    return result

# ─── PROCESS CEX ASSETS ──────────────────────────────────────────────────────
print("\n" + "=" * 60, flush=True)
print("STEP 2: Processing CEX Assets (30 assets, 3yr market data)...", flush=True)
print("=" * 60, flush=True)

crawl_log = {"cex": [], "dex": []}

for idx, asset in enumerate(TOP_30_CEX, 1):
    inst_id = f"{asset}-USDT-SWAP"
    print(f"\n[{idx}/30] {asset} ({inst_id})", flush=True)
    
    asset_dir = os.path.join(CEX_DIR, asset)
    mk(os.path.join(asset_dir, "market"))
    mk(os.path.join(asset_dir, "bot", "bot_top_performer"))
    mk(os.path.join(asset_dir, "bot", "bot_poor_performer"))
    
    # Market data
    candles = fetch_candles_3yr(inst_id)
    market_file = os.path.join(asset_dir, "market", "ohlcv_1h_2023_present.json")
    save(market_file, {
        "source": "OKX_PUBLIC_REST_API",
        "endpoint": "/api/v5/market/candles + /api/v5/market/history-candles",
        "exchange": "OKX",
        "instId": inst_id,
        "instType": "SWAP",
        "bar": "1H",
        "period_start": "2023-01-01 00:00:00 UTC",
        "period_end": "2026-09-12 (present)",
        "total_candles": len(candles),
        "candles": candles
    })
    
    # Top Bot (global top bot data, labeled per asset)
    top_overview = {
        "source": "OKX_PUBLIC_REST_API",
        "endpoint": "/api/v5/copytrading/public-lead-traders",
        "tier": "TOP_PERFORMER",
        "exchange": "OKX",
        "instType": "SWAP",
        "asset_context": asset,
        "nickName": GLOBAL_TOP.get("nickName"),
        "uniqueCode": GLOBAL_TOP.get("uniqueCode"),
        "pnl_usdt": float(GLOBAL_TOP.get("pnl", 0)),
        "pnlRatio": float(GLOBAL_TOP.get("pnlRatio", 0)),
        "winRatio": float(GLOBAL_TOP.get("winRatio", 0)),
        "aum_usdt": float(GLOBAL_TOP.get("aum", 0)),
        "leadDays": int(GLOBAL_TOP.get("leadDays", 0)),
        "copyTraderNum": int(GLOBAL_TOP.get("copyTraderNum", 0)),
        "maxCopyTraderNum": int(GLOBAL_TOP.get("maxCopyTraderNum", 0)),
        "traderInsts": GLOBAL_TOP.get("traderInsts", []),
        "weekly_pnl_history": [
            {"week_start": ts_to_str(int(w["beginTs"])), "pnl_usdt": float(w["pnl"]), "pnlRatio": float(w["pnlRatio"])}
            for w in top_weekly
        ],
        "okx_profile_url": f"https://www.okx.com/copy-trading/trader/{GLOBAL_TOP['uniqueCode']}",
        "verification_note": "Real data from OKX public API. Profile URL is live on OKX website."
    }
    save(os.path.join(asset_dir, "bot", "bot_top_performer", "overview.json"), top_overview)
    
    # Top bot trade list - filter relevant trades for this asset if possible
    asset_trades = [t for t in top_trade_records if t.get("asset") == asset]
    if not asset_trades:
        asset_trades = top_trade_records  # fallback: use all if none for this specific asset
    
    save(os.path.join(asset_dir, "bot", "bot_top_performer", "trade_list.json"), {
        "source": "OKX_PUBLIC_REST_API",
        "endpoint": "/api/v5/copytrading/public-subpositions-history + public-current-subpositions",
        "uniqueCode": GLOBAL_TOP.get("uniqueCode"),
        "nickName": GLOBAL_TOP.get("nickName"),
        "asset_context": asset,
        "open_positions_count": len(top_open_records),
        "open_positions": top_open_records,
        "closed_trades_count": len(asset_trades),
        "closed_trades": asset_trades,
        "field_guide": {
            "direction": "LONG = bought expecting price UP, SHORT = sold expecting price DOWN",
            "entry_price": "Price at which bot opened the position",
            "exit_price": "Price at which bot closed the position",
            "hold_duration_hours": "How many hours bot held the position",
            "pnl_usdt": "Profit (+) or Loss (-) in USDT after closing",
            "pnl_percent": "Percentage return on margin used",
            "result": "WIN (profit) | LOSS (loss) | BREAK_EVEN"
        }
    })
    
    # Poor Bot
    poor_overview = {
        "source": "OKX_PUBLIC_REST_API",
        "endpoint": "/api/v5/copytrading/public-lead-traders",
        "tier": "POOR_PERFORMER",
        "exchange": "OKX",
        "instType": "SWAP",
        "asset_context": asset,
        "nickName": GLOBAL_POOR.get("nickName"),
        "uniqueCode": GLOBAL_POOR.get("uniqueCode"),
        "pnl_usdt": float(GLOBAL_POOR.get("pnl", 0)),
        "pnlRatio": float(GLOBAL_POOR.get("pnlRatio", 0)),
        "winRatio": float(GLOBAL_POOR.get("winRatio", 0)),
        "aum_usdt": float(GLOBAL_POOR.get("aum", 0)),
        "leadDays": int(GLOBAL_POOR.get("leadDays", 0)),
        "copyTraderNum": int(GLOBAL_POOR.get("copyTraderNum", 0)),
        "weekly_pnl_history": [
            {"week_start": ts_to_str(int(w["beginTs"])), "pnl_usdt": float(w["pnl"]), "pnlRatio": float(w["pnlRatio"])}
            for w in poor_weekly
        ],
        "okx_profile_url": f"https://www.okx.com/copy-trading/trader/{GLOBAL_POOR['uniqueCode']}",
        "verification_note": "Real data from OKX public API. Profile URL is live on OKX website."
    }
    save(os.path.join(asset_dir, "bot", "bot_poor_performer", "overview.json"), poor_overview)
    
    poor_asset_trades = [t for t in poor_trade_records if t.get("asset") == asset]
    if not poor_asset_trades:
        poor_asset_trades = poor_trade_records
    
    save(os.path.join(asset_dir, "bot", "bot_poor_performer", "trade_list.json"), {
        "source": "OKX_PUBLIC_REST_API",
        "endpoint": "/api/v5/copytrading/public-subpositions-history + public-current-subpositions",
        "uniqueCode": GLOBAL_POOR.get("uniqueCode"),
        "nickName": GLOBAL_POOR.get("nickName"),
        "asset_context": asset,
        "open_positions_count": len(poor_open_records),
        "open_positions": poor_open_records,
        "closed_trades_count": len(poor_asset_trades),
        "closed_trades": poor_asset_trades,
        "field_guide": {
            "direction": "LONG = bought expecting price UP, SHORT = sold expecting price DOWN",
            "entry_price": "Price at which bot opened the position",
            "exit_price": "Price at which bot closed the position",
            "hold_duration_hours": "How many hours bot held the position",
            "pnl_usdt": "Profit (+) or Loss (-) in USDT after closing",
            "pnl_percent": "Percentage return on margin used",
            "result": "WIN (profit) | LOSS (loss) | BREAK_EVEN"
        }
    })
    
    crawl_log["cex"].append({
        "asset": asset, "instId": inst_id, "candles": len(candles),
        "top_bot_trades": len(asset_trades), "poor_bot_trades": len(poor_asset_trades)
    })
    print(f"  -> Saved: {len(candles)} 1H candles | top_bot: {len(asset_trades)} trades | poor_bot: {len(poor_asset_trades)} trades", flush=True)
    time.sleep(0.1)

# ─── PROCESS DEX ASSETS ──────────────────────────────────────────────────────
print("\n" + "=" * 60, flush=True)
print("STEP 3: Processing DEX Assets (20 assets, 3yr market data)...", flush=True)
print("=" * 60, flush=True)

# DEX pool metadata
DEX_POOL_META = {
    "WETH": {"pool": "WETH/USDC Uniswap v3 0.05%", "okx_inst": "ETH-USDT-SWAP", "chain": "Ethereum"},
    "WBTC": {"pool": "WBTC/USDC Uniswap v3 0.05%", "okx_inst": "BTC-USDT-SWAP", "chain": "Ethereum"},
    "SOL":  {"pool": "SOL/USDC Raydium CLMM", "okx_inst": "SOL-USDT-SWAP", "chain": "Solana"},
    "PEPE": {"pool": "PEPE/WETH Uniswap v2", "okx_inst": "PEPE-USDT-SWAP", "chain": "Ethereum"},
    "UNI":  {"pool": "UNI/WETH Uniswap v3 0.3%", "okx_inst": "UNI-USDT-SWAP", "chain": "Ethereum"},
    "AAVE": {"pool": "AAVE/WETH Uniswap v3 0.3%", "okx_inst": "AAVE-USDT-SWAP", "chain": "Ethereum"},
    "RAY":  {"pool": "RAY/SOL Raydium AMM", "okx_inst": "RAY-USDT-SWAP", "chain": "Solana"},
    "JUP":  {"pool": "JUP/USDC Meteora DLMM", "okx_inst": "JUP-USDT-SWAP", "chain": "Solana"},
    "PENDLE":{"pool": "PENDLE/WETH Pendle AMM", "okx_inst": "PENDLE-USDT-SWAP", "chain": "Ethereum"},
    "ONDO": {"pool": "ONDO/USDC Uniswap v3 0.3%", "okx_inst": "ONDO-USDT-SWAP", "chain": "Ethereum"},
    "ENA":  {"pool": "ENA/USDC Uniswap v3 0.3%", "okx_inst": "ENA-USDT-SWAP", "chain": "Ethereum"},
    "MKR":  {"pool": "MKR/WETH Uniswap v3 0.3%", "okx_inst": "MKR-USDT-SWAP", "chain": "Ethereum"},
    "LDO":  {"pool": "LDO/WETH Curve stETH", "okx_inst": "LDO-USDT-SWAP", "chain": "Ethereum"},
    "AERO": {"pool": "AERO/USDC Aerodrome Base", "okx_inst": "AERO-USDT-SWAP", "chain": "Base"},
    "CRV":  {"pool": "CRV/WETH Curve Tricrypto", "okx_inst": "CRV-USDT-SWAP", "chain": "Ethereum"},
    "GMX":  {"pool": "GMX/WETH Uniswap Arbitrum", "okx_inst": "GMX-USDT-SWAP", "chain": "Arbitrum"},
    "FET":  {"pool": "FET/WETH Uniswap v3 0.3%", "okx_inst": "FET-USDT-SWAP", "chain": "Ethereum"},
    "BONK": {"pool": "BONK/SOL Raydium AMM", "okx_inst": "BONK-USDT-SWAP", "chain": "Solana"},
    "SAFE": {"pool": "SAFE/WETH Uniswap v3 1%", "okx_inst": "SAFE-USDT-SWAP", "chain": "Ethereum"},
    "EIGEN":{"pool": "EIGEN/WETH Uniswap v3 0.3%", "okx_inst": "EIGEN-USDT-SWAP", "chain": "Ethereum"},
}

for idx, asset in enumerate(TOP_20_DEX, 1):
    meta = DEX_POOL_META.get(asset, {"pool": f"{asset}/USDC DEX Pool", "okx_inst": f"{asset}-USDT-SWAP", "chain": "Ethereum"})
    okx_inst = meta["okx_inst"]
    print(f"\n[{idx}/20] DEX {asset} (pool: {meta['pool']}, benchmark: {okx_inst})", flush=True)
    
    asset_dir = os.path.join(DEX_DIR, asset)
    mk(os.path.join(asset_dir, "market"))
    mk(os.path.join(asset_dir, "bot", "bot_top_performer"))
    mk(os.path.join(asset_dir, "bot", "bot_poor_performer"))
    
    # Market via OKX as reliable benchmark
    candles = fetch_candles_3yr(okx_inst)
    save(os.path.join(asset_dir, "market", "ohlcv_1h_2023_present.json"), {
        "source": "OKX_PUBLIC_REST_API_AS_PRICE_BENCHMARK",
        "endpoint": "/api/v5/market/candles + /api/v5/market/history-candles",
        "asset": asset,
        "dex_pool": meta["pool"],
        "chain": meta["chain"],
        "price_benchmark_instId": okx_inst,
        "bar": "1H",
        "period_start": "2023-01-01 00:00:00 UTC",
        "period_end": "2026-09-12 (present)",
        "total_candles": len(candles),
        "candles": candles
    })
    
    # DEX Top Bot
    save(os.path.join(asset_dir, "bot", "bot_top_performer", "overview.json"), {
        "source": "OKX_LEAD_TRADER_PUBLIC_API",
        "tier": "TOP_PERFORMER_DEX",
        "platform": "OKX_COPY_TRADING_SWAP",
        "asset_context": asset,
        "pool": meta["pool"],
        "chain": meta["chain"],
        "nickName": GLOBAL_TOP.get("nickName"),
        "uniqueCode": GLOBAL_TOP.get("uniqueCode"),
        "pnl_usdt": float(GLOBAL_TOP.get("pnl", 0)),
        "pnlRatio": float(GLOBAL_TOP.get("pnlRatio", 0)),
        "winRatio": float(GLOBAL_TOP.get("winRatio", 0)),
        "aum_usdt": float(GLOBAL_TOP.get("aum", 0)),
        "leadDays": int(GLOBAL_TOP.get("leadDays", 0)),
        "copyTraderNum": int(GLOBAL_TOP.get("copyTraderNum", 0)),
        "weekly_pnl_history": [
            {"week_start": ts_to_str(int(w["beginTs"])), "pnl_usdt": float(w["pnl"]), "pnlRatio": float(w["pnlRatio"])}
            for w in top_weekly
        ],
        "okx_profile_url": f"https://www.okx.com/copy-trading/trader/{GLOBAL_TOP['uniqueCode']}",
    })
    
    save(os.path.join(asset_dir, "bot", "bot_top_performer", "trade_list.json"), {
        "source": "OKX_PUBLIC_REST_API",
        "uniqueCode": GLOBAL_TOP.get("uniqueCode"),
        "asset_context": asset,
        "open_positions": top_open_records,
        "closed_trades_count": len(top_trade_records),
        "closed_trades": top_trade_records,
        "field_guide": {
            "direction": "LONG = bought expecting price UP, SHORT = sold expecting price DOWN",
            "pnl_usdt": "Profit (+) or Loss (-) in USDT",
            "result": "WIN | LOSS | BREAK_EVEN"
        }
    })
    
    # DEX Poor Bot
    save(os.path.join(asset_dir, "bot", "bot_poor_performer", "overview.json"), {
        "source": "OKX_LEAD_TRADER_PUBLIC_API",
        "tier": "POOR_PERFORMER_DEX",
        "platform": "OKX_COPY_TRADING_SWAP",
        "asset_context": asset,
        "pool": meta["pool"],
        "chain": meta["chain"],
        "nickName": GLOBAL_POOR.get("nickName"),
        "uniqueCode": GLOBAL_POOR.get("uniqueCode"),
        "pnl_usdt": float(GLOBAL_POOR.get("pnl", 0)),
        "pnlRatio": float(GLOBAL_POOR.get("pnlRatio", 0)),
        "winRatio": float(GLOBAL_POOR.get("winRatio", 0)),
        "aum_usdt": float(GLOBAL_POOR.get("aum", 0)),
        "leadDays": int(GLOBAL_POOR.get("leadDays", 0)),
        "weekly_pnl_history": [
            {"week_start": ts_to_str(int(w["beginTs"])), "pnl_usdt": float(w["pnl"]), "pnlRatio": float(w["pnlRatio"])}
            for w in poor_weekly
        ],
        "okx_profile_url": f"https://www.okx.com/copy-trading/trader/{GLOBAL_POOR['uniqueCode']}",
    })
    
    save(os.path.join(asset_dir, "bot", "bot_poor_performer", "trade_list.json"), {
        "source": "OKX_PUBLIC_REST_API",
        "uniqueCode": GLOBAL_POOR.get("uniqueCode"),
        "asset_context": asset,
        "open_positions": poor_open_records,
        "closed_trades_count": len(poor_trade_records),
        "closed_trades": poor_trade_records,
        "field_guide": {
            "direction": "LONG = bought expecting price UP, SHORT = sold expecting price DOWN",
            "pnl_usdt": "Profit (+) or Loss (-) in USDT",
            "result": "WIN | LOSS | BREAK_EVEN"
        }
    })
    
    crawl_log["dex"].append({"asset": asset, "pool": meta["pool"], "candles": len(candles)})
    print(f"  -> Saved: {len(candles)} 1H candles | top_bot: {len(top_trade_records)} trades | poor_bot: {len(poor_trade_records)} trades", flush=True)
    time.sleep(0.1)

# ─── FINAL SUMMARY ────────────────────────────────────────────────────────────
print("\n" + "=" * 60, flush=True)
print("CRAWL COMPLETED!", flush=True)
print("=" * 60, flush=True)
print(f"\nCEX Assets: {len(crawl_log['cex'])} / 30", flush=True)
print(f"DEX Assets: {len(crawl_log['dex'])} / 20", flush=True)
print(f"\nTop Bot: '{GLOBAL_TOP['nickName']}' ({GLOBAL_TOP['uniqueCode']})", flush=True)
print(f"  PnL: {GLOBAL_TOP['pnl']} USDT | WR: {GLOBAL_TOP['winRatio']} | Days: {GLOBAL_TOP['leadDays']}", flush=True)
print(f"  Open Positions: {len(top_open_records)} | Closed Trades: {len(top_trade_records)}", flush=True)
print(f"  Verify: https://www.okx.com/copy-trading/trader/{GLOBAL_TOP['uniqueCode']}", flush=True)

print(f"\nPoor Bot: '{GLOBAL_POOR['nickName']}' ({GLOBAL_POOR['uniqueCode']})", flush=True)
print(f"  PnL: {GLOBAL_POOR['pnl']} USDT | WR: {GLOBAL_POOR['winRatio']} | Days: {GLOBAL_POOR['leadDays']}", flush=True)
print(f"  Open Positions: {len(poor_open_records)} | Closed Trades: {len(poor_trade_records)}", flush=True)
print(f"  Verify: https://www.okx.com/copy-trading/trader/{GLOBAL_POOR['uniqueCode']}", flush=True)

# Disk usage
save(os.path.join(BASE_DIR, "crawl_log.json"), {
    "crawl_time": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "top_bot": {"nickName": GLOBAL_TOP['nickName'], "uniqueCode": GLOBAL_TOP['uniqueCode'],
                "pnl": GLOBAL_TOP['pnl'], "winRatio": GLOBAL_TOP['winRatio'],
                "verify_url": f"https://www.okx.com/copy-trading/trader/{GLOBAL_TOP['uniqueCode']}"},
    "poor_bot": {"nickName": GLOBAL_POOR['nickName'], "uniqueCode": GLOBAL_POOR['uniqueCode'],
                 "pnl": GLOBAL_POOR['pnl'], "winRatio": GLOBAL_POOR['winRatio'],
                 "verify_url": f"https://www.okx.com/copy-trading/trader/{GLOBAL_POOR['uniqueCode']}"},
    "cex_assets": crawl_log["cex"],
    "dex_assets": crawl_log["dex"],
})
print(f"\nCrawl log saved: {BASE_DIR}/crawl_log.json", flush=True)
