"""DEX Tick Crawler: lấy swap/trade on-chain THẬT gần đây (GeckoTerminal /trades, ~24h)
và gộp dần vào data/dex/{SYMBOL}/ticks.parquet (khai báo trong manifest["ticks"]).

Không ghi nến: nến chỉ có một nguồn là 1m.pkl + core/resampler.py.
Chạy định kỳ (cron) để tích luỹ lịch sử tick thật theo thời gian.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import pandas as pd
import requests

try:
    from backend.db.tick_storage import default_data_root, save_ticks_and_sync_candles, symbol_dir
except ImportError:  # chạy từ thư mục gốc repo
    from nora.backend.db.tick_storage import default_data_root, save_ticks_and_sync_candles, symbol_dir

DEFAULT_BASE_URL = "https://api.geckoterminal.com/api/v2"
DEFAULT_TARGETS_FILE = os.path.abspath(os.path.join(default_data_root(), "_meta", "geckoterminal_targets.json"))
DEFAULT_LOOKBACK_DAYS = 90.0  # Chuẩn 3 tháng gần nhất cho dữ liệu DEX (90 ngày)

# Built-in fallback DEX Pools
CORE_DEX_POOLS: Dict[str, Dict[str, str]] = {
    "BTC": {
        "network": "eth",
        "pool_address": "0x4585fe77225b41b697c938b018e2ac67ac5a20c0",
        "name": "WBTC / WETH 0.05%",
    },
    "ETH": {
        "network": "eth",
        "pool_address": "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640",
        "name": "WETH / USDC 0.05%",
    },
    "SOL": {
        "network": "solana",
        "pool_address": "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE",
        "name": "SOL / USDC",
    },
    "FONE": {
        "network": "solana",
        "pool_address": "3dcwhqJp6JBTJPq8ga335HWgSQVS7uQmdmeX7iGjMNpj",
        "name": "fone / SOL",
    },
    "CATE": {
        "network": "solana",
        "pool_address": "HMzvsEEmtzHhvZNw9uwbaG85HCTmFnkbhzUx16cy7ca3",
        "name": "CATE / SOL",
    },
    "CYBERLEEK": {
        "network": "solana",
        "pool_address": "G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh",
        "name": "CYBERLEEK / SOL",
    },
    "PILL": {
        "network": "solana",
        "pool_address": "GsfjzLCn25qsZr1nZjc1ZigVjYcXGgjL1D2Mn9YYwXeo",
        "name": "PILL / SOL",
    },
    "ILLY": {
        "network": "solana",
        "pool_address": "9FFgJqghUvYJ5SPefo8Aum6j2NmueL9DW2uApbDFww1v",
        "name": "ILLY / SOL",
    },
}

_SESSION = requests.Session()
_SESSION.headers.update({
    "accept": "application/json",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
})


def load_all_targets(targets_file: str = DEFAULT_TARGETS_FILE) -> Dict[str, Dict[str, str]]:
    """Load targets from json file or fallback to CORE_DEX_POOLS."""
    pools = dict(CORE_DEX_POOLS)
    if os.path.isfile(targets_file):
        try:
            with open(targets_file, "r", encoding="utf-8") as f:
                items = json.load(f)
                for item in items:
                    asset = str(item.get("asset") or "").strip().upper()
                    if asset and item.get("pool_address"):
                        pools[asset] = {
                            "network": item.get("network", "solana"),
                            "pool_address": item.get("pool_address"),
                            "name": item.get("name", f"{asset} Pool"),
                        }
        except Exception as exc:
            print(f"[WARN] Failed to read {targets_file}: {exc}", flush=True)
    return pools


def fetch_pool_trades(network: str, pool_address: str, retries: int = 4) -> List[Dict]:
    """Fetch recent on-chain swaps/trades from GeckoTerminal DEX pool with robust retry."""
    url = f"{DEFAULT_BASE_URL}/networks/{network}/pools/{pool_address}/trades"
    all_trades = []
    raw_items = []
    
    for attempt in range(retries):
        try:
            r = _SESSION.get(url, timeout=15)
            if r.status_code == 429:
                wait_sec = 10.0 + attempt * 5.0
                print(f"  [WARN] Rate limit (429), waiting {wait_sec:.0f}s (attempt {attempt+1}/{retries})...", flush=True)
                time.sleep(wait_sec)
                continue
                
            if r.status_code != 200:
                print(f"  [ERROR] HTTP {r.status_code}: {r.text[:200]}", flush=True)
                return []
                
            data = r.json()
            raw_items = data.get("data", [])
            break
        except Exception as exc:
            if attempt == retries - 1:
                print(f"  [ERROR] Failed to fetch trades after {retries} attempts: {exc}", flush=True)
                return []
            time.sleep(3.0)
            
    for item in raw_items:
        attr = item.get("attributes", {})
        ts_str = attr.get("block_timestamp")
        if not ts_str:
            continue
        
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            ts_ms = int(dt.timestamp() * 1000)
        except Exception:
            ts_ms = int(time.time() * 1000)
            
        price_usd = float(attr.get("price_from_in_usd") or attr.get("price_to_in_usd") or 0.0)
        vol_usd = float(attr.get("volume_in_usd") or 0.0)
        amount = float(attr.get("from_token_amount") or attr.get("to_token_amount") or 0.0)
        kind = attr.get("kind", "buy")
        side = 1 if kind == "buy" else -1
        
        all_trades.append({
            "timestamp_ms": ts_ms,
            "price": price_usd,
            "volume_usd": vol_usd,
            "amount": amount,
            "side": side,
            "block_number": int(attr.get("block_number") or 0),
            "tx_hash": str(attr.get("tx_hash") or ""),
        })
        
    return all_trades


def crawl_and_sync_symbol(symbol: str, pool_info: Dict[str, str], data_root: Optional[str] = None) -> Optional[Dict]:
    target_dir = symbol_dir(symbol, data_root, create=True, venue="dex")
    print(f"\n=======================================================", flush=True)
    print(f"🔬 Crawling Tick Data for {symbol} ({pool_info['name']})", flush=True)
    print(f"📁 Target Folder: {target_dir}", flush=True)
    print(f"=======================================================", flush=True)
    
    trades = fetch_pool_trades(pool_info["network"], pool_info["pool_address"])
    if not trades:
        print(f"  [FAIL] No trades fetched for {symbol}", flush=True)
        return None
        
    df = pd.DataFrame(trades)
    
    # Save ticks.parquet (candles are resampled strictly via resampler.py)
    res = save_ticks_and_sync_candles(df, symbol, data_root=data_root, sync_all_timeframes=False)
    
    print(f"  ✅ Saved {res['total_ticks']:,} ticks -> {res['tick_path']}", flush=True)
    print(f"  📊 Synced {len(res['updated_frames'])} candle frames into {target_dir}/: {', '.join(res['updated_frames'][:8])}...", flush=True)
    print(f"  🕒 Time range: {datetime.fromtimestamp(df['timestamp_ms'].min()/1000, tz=timezone.utc)} -> {datetime.fromtimestamp(df['timestamp_ms'].max()/1000, tz=timezone.utc)}", flush=True)
    return res


def main():
    parser = argparse.ArgumentParser(description="Crawl DEX Trades/Ticks into data/{SYMBOL}/ and sync candle frames")
    parser.add_argument("--symbols", type=str, default="ALL", help="Comma-separated symbols or 'ALL'")
    parser.add_argument("--data-root", type=str, default=default_data_root(), help="Root data folder")
    parser.add_argument("--targets-file", type=str, default=DEFAULT_TARGETS_FILE, help="Path to geckoterminal_targets.json")
    args = parser.parse_args()
    
    all_pools = load_all_targets(args.targets_file)
    
    if args.symbols.upper() == "ALL":
        target_symbols = list(all_pools.keys())
    else:
        target_symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        
    print(f"🚀 Starting DEX Tick Sync for {len(target_symbols)} assets: {', '.join(target_symbols)}", flush=True)
    
    success_count = 0
    for sym in target_symbols:
        if sym in all_pools:
            res = crawl_and_sync_symbol(sym, all_pools[sym], data_root=args.data_root)
            if res:
                success_count += 1
            time.sleep(2.5)  # Respect rate limit
        else:
            print(f"[WARN] Unknown pool for {sym}. Skipped.", flush=True)
            
    print(f"\n=======================================================", flush=True)
    print(f"🎉 Completed! Successfully synced {success_count}/{len(target_symbols)} asset folders with ticks & candles.", flush=True)
    print(f"=======================================================", flush=True)


if __name__ == "__main__":
    main()
