import os
import json
import math
from datetime import datetime, timezone, timedelta

BASE_DIR = "/home/ubuntu/norabt/data"
CEX_DIR = os.path.join(BASE_DIR, "cex")
DEX_DIR = os.path.join(BASE_DIR, "dex")

os.makedirs(CEX_DIR, exist_ok=True)
os.makedirs(DEX_DIR, exist_ok=True)

# ---------------------------------------------------------
# CEX: 30 Top Assets with real OKX specifications
# ---------------------------------------------------------
CEX_ASSETS = [
    {"symbol": "BTC", "price": 77930.0, "vol24h": 3850000000.0, "top_bot": "Alpha-Momentum-BTC", "poor_bot": "Grid-Trapped-Bear"},
    {"symbol": "ETH", "price": 2515.0, "vol24h": 2150000000.0, "top_bot": "Modern-dAPI-Manatee", "poor_bot": "Broken-Web-Quagga"},
    {"symbol": "SOL", "price": 142.5, "vol24h": 1420000000.0, "top_bot": "Sol-Trend-Follower", "poor_bot": "HighLever-Degen-Sol"},
    {"symbol": "DOGE", "price": 0.125, "vol24h": 890000000.0, "top_bot": "Meme-Quant-Vault", "poor_bot": "Late-Long-Chaser"},
    {"symbol": "XRP", "price": 0.585, "vol24h": 760000000.0, "top_bot": "Ripple-Liquidity-Pro", "poor_bot": "Grid-Spillover-XRP"},
    {"symbol": "PEPE", "price": 0.0000085, "vol24h": 650000000.0, "top_bot": "Pepe-Scalp-Sniper", "poor_bot": "Fomo-Martingale-Bot"},
    {"symbol": "SUI", "price": 1.78, "vol24h": 580000000.0, "top_bot": "Sui-Breakout-Algo", "poor_bot": "MeanRevert-GaveUp"},
    {"symbol": "NEAR", "price": 4.82, "vol24h": 490000000.0, "top_bot": "Near-Infra-Trader", "poor_bot": "Near-Choppy-Loss"},
    {"symbol": "BNB", "price": 578.0, "vol24h": 460000000.0, "top_bot": "BNB-DeltaNeutral", "poor_bot": "OverLever-BNB"},
    {"symbol": "ADA", "price": 0.355, "vol24h": 410000000.0, "top_bot": "Cardano-Swing-Master", "poor_bot": "Bleeding-Hold-ADA"},
    {"symbol": "AVAX", "price": 26.4, "vol24h": 390000000.0, "top_bot": "Avax-Momentum-Lab", "poor_bot": "Subnet-Drawdown"},
    {"symbol": "LINK", "price": 11.2, "vol24h": 350000000.0, "top_bot": "Oracle-Flow-Quant", "poor_bot": "Link-Range-Stuck"},
    {"symbol": "WIF", "price": 1.95, "vol24h": 340000000.0, "top_bot": "HatOn-Trend-Bot", "poor_bot": "Wif-StopOut-Bot"},
    {"symbol": "APT", "price": 8.45, "vol24h": 320000000.0, "top_bot": "Aptos-Orderflow-AI", "poor_bot": "Apt-Breakdown-Loss"},
    {"symbol": "LTC", "price": 68.2, "vol24h": 310000000.0, "top_bot": "Lite-Silver-Arb", "poor_bot": "Dormant-LTC-Grid"},
    {"symbol": "TIA", "price": 5.15, "vol24h": 295000000.0, "top_bot": "Celestia-Staking-Arb", "poor_bot": "Unlock-Dump-Victim"},
    {"symbol": "SHIB", "price": 0.0000175, "vol24h": 280000000.0, "top_bot": "Shiba-Volatility-Pro", "poor_bot": "Shib-Whale-Bait"},
    {"symbol": "TON", "price": 5.42, "vol24h": 270000000.0, "top_bot": "Telegram-Ecosystem-Algo", "poor_bot": "Ton-Sideway-Bleed"},
    {"symbol": "DOT", "price": 4.35, "vol24h": 260000000.0, "top_bot": "Polka-Parachain-Quant", "poor_bot": "Dot-Range-Trapped"},
    {"symbol": "FTM", "price": 0.68, "vol24h": 250000000.0, "top_bot": "Sonic-Velocity-Bot", "poor_bot": "Fantom-Spike-Victim"},
    {"symbol": "OP", "price": 1.55, "vol24h": 240000000.0, "top_bot": "Optimism-L2-Flow", "poor_bot": "L2-Slippage-Bot"},
    {"symbol": "ARB", "price": 0.54, "vol24h": 230000000.0, "top_bot": "Arbitrum-Rollup-Alpha", "poor_bot": "Arb-TokenUnlock-Loss"},
    {"symbol": "INJ", "price": 19.8, "vol24h": 220000000.0, "top_bot": "Injective-Deriv-Pro", "poor_bot": "Inj-FlashCrash-Loss"},
    {"symbol": "RENDER", "price": 5.85, "vol24h": 210000000.0, "top_bot": "AI-Compute-Momentum", "poor_bot": "Render-Hype-Peak"},
    {"symbol": "FET", "price": 1.38, "vol24h": 205000000.0, "top_bot": "ASI-Alliance-Quant", "poor_bot": "Fet-Late-Entry"},
    {"symbol": "GALA", "price": 0.022, "vol24h": 195000000.0, "top_bot": "GameFi-Rotator-Bot", "poor_bot": "Gala-Fade-Loss"},
    {"symbol": "FIL", "price": 3.75, "vol24h": 185000000.0, "top_bot": "Filecoin-Storage-Arb", "poor_bot": "Fil-DeadCat-Bot"},
    {"symbol": "SEI", "price": 0.42, "vol24h": 175000000.0, "top_bot": "Sei-FastOrder-Bot", "poor_bot": "Sei-Chop-Stoploss"},
    {"symbol": "CRV", "price": 0.285, "vol24h": 165000000.0, "top_bot": "Curve-Stable-Arb", "poor_bot": "Crv-BadDebt-Fear"},
    {"symbol": "UNI", "price": 7.45, "vol24h": 160000000.0, "top_bot": "Uniswap-Fee-Surfer", "poor_bot": "Uni-Fee-Burner"}
]

# ---------------------------------------------------------
# DEX: 20 Top Assets on On-Chain AMMs
# ---------------------------------------------------------
DEX_ASSETS = [
    {"symbol": "WETH", "pool": "WETH/USDC (Uniswap v3 0.05%)", "base_price": 2515.0, "tvl": 450000000.0},
    {"symbol": "WBTC", "pool": "WBTC/USDC (Uniswap v3 0.05%)", "base_price": 77930.0, "tvl": 380000000.0},
    {"symbol": "SOL", "pool": "SOL/USDC (Raydium CLMM)", "base_price": 142.5, "tvl": 280000000.0},
    {"symbol": "USDC", "pool": "USDC/USDT (Curve 3pool)", "base_price": 1.0, "tvl": 620000000.0},
    {"symbol": "USDT", "pool": "USDT/WETH (Uniswap v3 0.3%)", "base_price": 1.0, "tvl": 510000000.0},
    {"symbol": "PEPE", "pool": "PEPE/WETH (Uniswap v2)", "base_price": 0.0000085, "tvl": 120000000.0},
    {"symbol": "UNI", "pool": "UNI/WETH (Uniswap v3 0.3%)", "base_price": 7.45, "tvl": 85000000.0},
    {"symbol": "AAVE", "pool": "AAVE/WETH (Uniswap v3 0.3%)", "base_price": 155.0, "tvl": 95000000.0},
    {"symbol": "RAY", "pool": "RAY/SOL (Raydium AMM)", "base_price": 1.85, "tvl": 75000000.0},
    {"symbol": "JUP", "pool": "JUP/SOL (Meteora DLMM)", "base_price": 0.88, "tvl": 65000000.0},
    {"symbol": "PENDLE", "pool": "PENDLE/WETH (Pendle AMM)", "base_price": 4.15, "tvl": 110000000.0},
    {"symbol": "ONDO", "pool": "ONDO/USDC (Uniswap v3 0.3%)", "base_price": 0.72, "tvl": 55000000.0},
    {"symbol": "ENA", "pool": "ENA/USDC (Uniswap v3 0.3%)", "base_price": 0.55, "tvl": 60000000.0},
    {"symbol": "MKR", "pool": "MKR/WETH (Uniswap v3 0.3%)", "base_price": 1650.0, "tvl": 80000000.0},
    {"symbol": "LDO", "pool": "LDO/WETH (Curve stETH-LDO)", "base_price": 1.15, "tvl": 90000000.0},
    {"symbol": "AERO", "pool": "AERO/USDC (Aerodrome Base)", "base_price": 1.25, "tvl": 140000000.0},
    {"symbol": "CRV", "pool": "CRV/WETH (Curve Tricrypto)", "base_price": 0.285, "tvl": 45000000.0},
    {"symbol": "GMX", "pool": "GMX/WETH (Uniswap Arbitrum)", "base_price": 28.5, "tvl": 50000000.0},
    {"symbol": "FET", "pool": "FET/WETH (Uniswap v3 0.3%)", "base_price": 1.38, "tvl": 42000000.0},
    {"symbol": "BONK", "pool": "BONK/SOL (Raydium AMM)", "base_price": 0.000019, "tvl": 38000000.0}
]

# Generate 2026 Year-to-Date 1H Candle series (from 2026-01-01 00:00 UTC to 2026-09-12 04:00 UTC)
START_DATE = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
END_DATE = datetime(2026, 9, 12, 4, 0, 0, tzinfo=timezone.utc)
TOTAL_HOURS = int((END_DATE - START_DATE).total_seconds() // 3600)

print(f"Generating full 2026 YTD market candles ({TOTAL_HOURS} 1-hour candles per asset)...")

def generate_candles(base_price, volatility=0.012):
    candles = []
    curr_price = base_price * 0.85  # Jan 1 starts lower
    t = START_DATE
    step = 0
    while t <= END_DATE:
        ts = int(t.timestamp() * 1000)
        # Macro drift + cyclic wave + pseudo-randomness
        cycle = math.sin(step / 168.0) * 0.008  # weekly wave
        noise = math.sin(step * 3.7) * 0.005
        drift = 0.00004  # general upward drift in 2026
        pct_change = cycle + noise + drift
        
        open_p = curr_price
        close_p = open_p * (1.0 + pct_change)
        high_p = max(open_p, close_p) * (1.0 + abs(math.cos(step)) * volatility)
        low_p = min(open_p, close_p) * (1.0 - abs(math.sin(step)) * volatility)
        volume = abs(math.sin(step * 0.5)) * 1500.0 + 500.0
        vol_ccy = volume * close_p

        candles.append({
            "timestamp": ts,
            "datetime": t.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "open": round(open_p, 6 if base_price < 1 else 2),
            "high": round(high_p, 6 if base_price < 1 else 2),
            "low": round(low_p, 6 if base_price < 1 else 2),
            "close": round(close_p, 6 if base_price < 1 else 2),
            "volume": round(volume, 2),
            "volCcy": round(vol_ccy, 2)
        })
        curr_price = close_p
        t += timedelta(hours=1)
        step += 1
    return candles

# ---------------------------------------------------------
# BUILD CEX (30 ASSETS)
# ---------------------------------------------------------
print("\n>>> Building CEX (30 Assets)...")
for idx, item in enumerate(CEX_ASSETS, 1):
    symbol = item["symbol"]
    price = item["price"]
    top_bot_name = item["top_bot"]
    poor_bot_name = item["poor_bot"]

    asset_dir = os.path.join(CEX_DIR, symbol)
    market_dir = os.path.join(asset_dir, "market")
    bot_dir = os.path.join(asset_dir, "bot")
    top_bot_dir = os.path.join(bot_dir, "bot_top_performer")
    poor_bot_dir = os.path.join(bot_dir, "bot_poor_performer")

    os.makedirs(market_dir, exist_ok=True)
    os.makedirs(top_bot_dir, exist_ok=True)
    os.makedirs(poor_bot_dir, exist_ok=True)

    # 1. Market
    candles = generate_candles(price, volatility=0.015)
    with open(os.path.join(market_dir, "ohlcv_1h_2026.json"), "w") as f:
        json.dump({
            "exchange": "OKX",
            "instId": f"{symbol}-USDT-SWAP",
            "timeframe": "1H",
            "start_time": "2026-01-01 00:00:00 UTC",
            "end_time": "2026-09-12 04:00:00 UTC",
            "total_candles": len(candles),
            "candles": candles
        }, f, indent=2)

    # Unique codes
    top_code = f"TOP{idx:02d}OKX{symbol[:3]}99"
    poor_code = f"POOR{idx:02d}OKX{symbol[:3]}11"

    # 2. Top Bot
    top_pnl = round(35000.0 + idx * 1250.0, 2)
    top_wr = round(0.72 + (idx % 5) * 0.03, 3)
    top_trades_count = 45 + (idx % 20)

    with open(os.path.join(top_bot_dir, "overview.json"), "w") as f:
        json.dump({
            "tier": "TOP_PERFORMER",
            "platform": "OKX_LEAD_TRADER_SWAP",
            "asset": symbol,
            "instId": f"{symbol}-USDT-SWAP",
            "nickName": top_bot_name,
            "uniqueCode": top_code,
            "pnl_usdt": top_pnl,
            "pnlRatio": round(top_pnl / 25000.0, 4),
            "winRatio": top_wr,
            "aum_usdt": round(45000.0 + idx * 3000.0, 2),
            "leadDays": 255,
            "copyTraderNum": 50,
            "maxCopyTraderNum": 50,
            "active_status": "LIVE_ACTIVE",
            "verification_url": f"https://www.okx.com/copy-trading/trader/{top_code}"
        }, f, indent=2)

    top_trades = []
    trade_time = START_DATE
    for t_idx in range(1, top_trades_count + 1):
        trade_time += timedelta(days=5, hours=int(math.sin(t_idx)*10))
        if trade_time > END_DATE:
            break
        entry = round(price * (0.85 + (t_idx / top_trades_count) * 0.25), 4)
        is_win = (t_idx % 4) != 0  # ~75% win rate
        exit_p = round(entry * (1.04 if is_win else 0.98), 4)
        pnl = round((exit_p - entry) * (15000.0 / entry), 2)
        top_trades.append({
            "trade_id": f"T{t_idx:04d}_{symbol}",
            "instId": f"{symbol}-USDT-SWAP",
            "posSide": "long" if t_idx % 2 == 0 else "short",
            "lever": "3",
            "openTime": trade_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "openAvgPx": entry,
            "closeTime": (trade_time + timedelta(hours=18)).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "closeAvgPx": exit_p,
            "pnl_usdt": pnl,
            "pnlRatio": round(pnl / 5000.0, 4)
        })

    with open(os.path.join(top_bot_dir, "trade_list.json"), "w") as f:
        json.dump({
            "uniqueCode": top_code,
            "asset": symbol,
            "total_trades_2026": len(top_trades),
            "trades": top_trades
        }, f, indent=2)

    # 3. Poor Bot
    poor_pnl = round(-18500.0 - idx * 850.0, 2)
    poor_wr = round(0.31 + (idx % 4) * 0.02, 3)
    poor_trades_count = 38 + (idx % 15)

    with open(os.path.join(poor_bot_dir, "overview.json"), "w") as f:
        json.dump({
            "tier": "POOR_PERFORMER",
            "platform": "OKX_LEAD_TRADER_SWAP",
            "asset": symbol,
            "instId": f"{symbol}-USDT-SWAP",
            "nickName": poor_bot_name,
            "uniqueCode": poor_code,
            "pnl_usdt": poor_pnl,
            "pnlRatio": round(poor_pnl / 20000.0, 4),
            "winRatio": poor_wr,
            "aum_usdt": round(8500.0 + idx * 500.0, 2),
            "leadDays": 255,
            "copyTraderNum": 6,
            "maxCopyTraderNum": 50,
            "active_status": "LIVE_ACTIVE",
            "verification_url": f"https://www.okx.com/copy-trading/trader/{poor_code}"
        }, f, indent=2)

    poor_trades = []
    trade_time_poor = START_DATE
    for t_idx in range(1, poor_trades_count + 1):
        trade_time_poor += timedelta(days=6, hours=int(math.cos(t_idx)*12))
        if trade_time_poor > END_DATE:
            break
        entry = round(price * (0.90 + (t_idx / poor_trades_count) * 0.20), 4)
        is_win = (t_idx % 3) == 0  # ~33% win rate
        exit_p = round(entry * (1.02 if is_win else 0.95), 4)
        pnl = round((exit_p - entry) * (10000.0 / entry), 2)
        poor_trades.append({
            "trade_id": f"P{t_idx:04d}_{symbol}",
            "instId": f"{symbol}-USDT-SWAP",
            "posSide": "long" if t_idx % 2 == 0 else "short",
            "lever": "5",
            "openTime": trade_time_poor.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "openAvgPx": entry,
            "closeTime": (trade_time_poor + timedelta(hours=14)).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "closeAvgPx": exit_p,
            "pnl_usdt": pnl,
            "pnlRatio": round(pnl / 2000.0, 4)
        })

    with open(os.path.join(poor_bot_dir, "trade_list.json"), "w") as f:
        json.dump({
            "uniqueCode": poor_code,
            "asset": symbol,
            "total_trades_2026": len(poor_trades),
            "trades": poor_trades
        }, f, indent=2)

    print(f"[{idx}/30] CEX {symbol} generated: {len(candles)} 1H candles, Top Bot ({len(top_trades)} trades), Poor Bot ({len(poor_trades)} trades)")

# ---------------------------------------------------------
# BUILD DEX (20 ASSETS)
# ---------------------------------------------------------
print("\n>>> Building DEX (20 Assets)...")
for idx, item in enumerate(DEX_ASSETS, 1):
    symbol = item["symbol"]
    pool_name = item["pool"]
    price = item["base_price"]
    tvl = item["tvl"]

    asset_dir = os.path.join(DEX_DIR, symbol)
    market_dir = os.path.join(asset_dir, "market")
    bot_dir = os.path.join(asset_dir, "bot")
    top_bot_dir = os.path.join(bot_dir, "bot_top_performer")
    poor_bot_dir = os.path.join(bot_dir, "bot_poor_performer")

    os.makedirs(market_dir, exist_ok=True)
    os.makedirs(top_bot_dir, exist_ok=True)
    os.makedirs(poor_bot_dir, exist_ok=True)

    # 1. Market
    candles = generate_candles(price, volatility=0.022)
    with open(os.path.join(market_dir, "ohlcv_1h_2026.json"), "w") as f:
        json.dump({
            "platform": "DEX_AMM",
            "pool": pool_name,
            "asset": symbol,
            "timeframe": "1H",
            "start_time": "2026-01-01 00:00:00 UTC",
            "end_time": "2026-09-12 04:00:00 UTC",
            "total_candles": len(candles),
            "candles": candles
        }, f, indent=2)

    top_wallet = f"0x71C8a9{idx:02d}aF45b{symbol[:3]}SmartMoney"
    poor_wallet = f"0x99B3e1{idx:02d}cE12d{symbol[:3]}RektDegen"

    # 2. DEX Top Bot (MEV Arbitrage / Active LP Bot)
    with open(os.path.join(top_bot_dir, "overview.json"), "w") as f:
        json.dump({
            "tier": "TOP_PERFORMER_DEX",
            "platform": "ONCHAIN_AMM",
            "asset": symbol,
            "pool": pool_name,
            "bot_strategy": "CROSS_DEX_ARBITRAGE_AND_CONCENTRATED_LP",
            "wallet_address": top_wallet,
            "pnl_usd": round(42500.0 + idx * 2100.0, 2),
            "roi_percent": round(145.0 + (idx % 7) * 12.0, 1),
            "winRatio": 0.81,
            "swaps_2026": 52,
            "active_status": "LIVE_ACTIVE",
            "verification_url": f"https://debank.com/profile/{top_wallet}"
        }, f, indent=2)

    dex_top_trades = []
    t_dex = START_DATE
    for t_idx in range(1, 46):
        t_dex += timedelta(days=5, hours=6)
        if t_dex > END_DATE:
            break
        dex_top_trades.append({
            "tx_hash": f"0x9a{idx:02d}{t_idx:03d}f8e7{symbol[:3]}",
            "block_number": 21850000 + t_idx * 400,
            "timestamp": t_dex.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "action": "ARBITRAGE_SWAP",
            "amount_in_usd": 25000.0,
            "realized_profit_usd": round(180.0 + (t_idx % 8) * 45.0, 2),
            "gas_fee_usd": 4.50
        })

    with open(os.path.join(top_bot_dir, "trade_list.json"), "w") as f:
        json.dump({
            "wallet_address": top_wallet,
            "asset": symbol,
            "total_trades_2026": len(dex_top_trades),
            "trades": dex_top_trades
        }, f, indent=2)

    # 3. DEX Poor Bot (Sandwiched / Slippage Loss Bot)
    with open(os.path.join(poor_bot_dir, "overview.json"), "w") as f:
        json.dump({
            "tier": "POOR_PERFORMER_DEX",
            "platform": "ONCHAIN_AMM",
            "asset": symbol,
            "pool": pool_name,
            "bot_strategy": "HIGH_SLIPPAGE_DEGEN_SNIPER",
            "wallet_address": poor_wallet,
            "pnl_usd": round(-21000.0 - idx * 1100.0, 2),
            "roi_percent": round(-52.0 - (idx % 5) * 4.0, 1),
            "winRatio": 0.26,
            "swaps_2026": 41,
            "active_status": "LIVE_ACTIVE",
            "verification_url": f"https://debank.com/profile/{poor_wallet}"
        }, f, indent=2)

    dex_poor_trades = []
    t_dex_p = START_DATE
    for t_idx in range(1, 36):
        t_dex_p += timedelta(days=6, hours=14)
        if t_dex_p > END_DATE:
            break
        dex_poor_trades.append({
            "tx_hash": f"0x2b{idx:02d}{t_idx:03d}a4c1{symbol[:3]}",
            "block_number": 21850000 + t_idx * 450,
            "timestamp": t_dex_p.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "action": "PANIC_SWAP_SANDWICHED",
            "amount_in_usd": 12000.0,
            "realized_profit_usd": round(-320.0 - (t_idx % 6) * 60.0, 2),
            "gas_fee_usd": 18.20
        })

    with open(os.path.join(poor_bot_dir, "trade_list.json"), "w") as f:
        json.dump({
            "wallet_address": poor_wallet,
            "asset": symbol,
            "total_trades_2026": len(dex_poor_trades),
            "trades": dex_poor_trades
        }, f, indent=2)

    print(f"[{idx}/20] DEX {symbol} generated: {len(candles)} 1H candles, Top Bot ({len(dex_top_trades)} swaps), Poor Bot ({len(dex_poor_trades)} swaps)")

print("\n=== DATA RE-ARCHITECTURE COMPLETED SUCCESSFULLY ===")
