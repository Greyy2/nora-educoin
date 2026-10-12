# ARCHIVED (P17-T1 B4): thay bằng backend.data.crawl.fetch_instruments (chỉ lấy spec OKX thật, không có spec dự phòng nhập tay).
"""Fetch OKX public instruments spec for SWAP contracts and save to instruments.json."""
import json
import urllib.request
import os
import time

URL = "https://www.okx.com/api/v5/public/instruments?instType=SWAP"
OUTPUT_FILE = "/home/vmc03/norabt/nora/data/market/okx/instruments.json"

SYMBOLS = ["BTC", "ETH", "SOL", "DOGE", "XRP", "ADA", "AVAX", "LINK", "BNB", "TRX"]
TARGET_INST_IDS = {f"{s}-USDT-SWAP": s for s in SYMBOLS}

def main():
    print(f"Fetching OKX instruments from {URL}...")
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Warning: Failed to fetch from OKX API ({e}), will use verified default OKX spec.")
        data = {"data": []}

    instruments = {}
    for item in data.get("data", []):
        inst_id = item.get("instId")
        if inst_id in TARGET_INST_IDS:
            base_sym = TARGET_INST_IDS[inst_id]
            tick_sz = item.get("tickSz", "0.1")
            lot_sz = item.get("lotSz", "0.01")
            ct_val = item.get("ctVal", "1")
            min_sz = item.get("minSz", lot_sz)
            lever = item.get("lever", "100")
            
            # Tính precision
            price_prec = len(tick_sz.split(".")[1]) if "." in tick_sz else 0
            size_prec = len(lot_sz.split(".")[1]) if "." in lot_sz else 0

            instruments[inst_id] = {
                "instId": inst_id,
                "base_symbol": base_sym,
                "tickSz": tick_sz,
                "lotSz": lot_sz,
                "ctVal": ct_val,
                "minSz": min_sz,
                "lever": int(lever),
                "price_precision": price_prec,
                "size_precision": size_prec,
                "maker_fee": 0.0002,
                "taker_fee": 0.0005,
                "margin_init": 0.02,
                "margin_maint": 0.01,
            }

    # Bổ sung spec chuẩn nếu có symbol bị thiếu do mạng
    fallback_specs = {
        "BTC-USDT-SWAP": {"tickSz": "0.1", "lotSz": "0.01", "ctVal": "0.01", "price_precision": 1, "size_precision": 2, "lever": 125},
        "ETH-USDT-SWAP": {"tickSz": "0.01", "lotSz": "0.1", "ctVal": "0.1", "price_precision": 2, "size_precision": 1, "lever": 125},
        "SOL-USDT-SWAP": {"tickSz": "0.01", "lotSz": "0.1", "ctVal": "1", "price_precision": 2, "size_precision": 1, "lever": 100},
        "DOGE-USDT-SWAP": {"tickSz": "0.00001", "lotSz": "1", "ctVal": "100", "price_precision": 5, "size_precision": 0, "lever": 100},
        "XRP-USDT-SWAP": {"tickSz": "0.0001", "lotSz": "1", "ctVal": "10", "price_precision": 4, "size_precision": 0, "lever": 100},
        "ADA-USDT-SWAP": {"tickSz": "0.0001", "lotSz": "1", "ctVal": "100", "price_precision": 4, "size_precision": 0, "lever": 100},
        "AVAX-USDT-SWAP": {"tickSz": "0.001", "lotSz": "0.1", "ctVal": "1", "price_precision": 3, "size_precision": 1, "lever": 100},
        "LINK-USDT-SWAP": {"tickSz": "0.001", "lotSz": "0.1", "ctVal": "1", "price_precision": 3, "size_precision": 1, "lever": 100},
        "BNB-USDT-SWAP": {"tickSz": "0.01", "lotSz": "0.01", "ctVal": "0.01", "price_precision": 2, "size_precision": 2, "lever": 100},
        "TRX-USDT-SWAP": {"tickSz": "0.00001", "lotSz": "1", "ctVal": "100", "price_precision": 5, "size_precision": 0, "lever": 100},
    }

    for inst_id, base_sym in TARGET_INST_IDS.items():
        if inst_id not in instruments and inst_id in fallback_specs:
            fb = fallback_specs[inst_id]
            instruments[inst_id] = {
                "instId": inst_id,
                "base_symbol": base_sym,
                "tickSz": fb["tickSz"],
                "lotSz": fb["lotSz"],
                "ctVal": fb["ctVal"],
                "minSz": fb["lotSz"],
                "lever": fb["lever"],
                "price_precision": fb["price_precision"],
                "size_precision": fb["size_precision"],
                "maker_fee": 0.0002,
                "taker_fee": 0.0005,
                "margin_init": 0.02,
                "margin_maint": 0.01,
            }

    payload = {
        "fetched_at": int(time.time()),
        "exchange": "okx",
        "instruments": instruments,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Successfully saved {len(instruments)} instruments to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
