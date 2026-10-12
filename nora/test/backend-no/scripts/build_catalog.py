# ARCHIVED (P17-T1 B4): script của kho pkl / backend.crawl cũ (catalog nay cập nhật bằng job data_update -> backend.data.crawl).
"""Build ParquetDataCatalog chuẩn NautilusTrader cho toàn bộ 10 symbols OKX perp.
Đọc 1m.pkl, lọc nến thật (is_filled == 0), chuyển đổi sang base volume, đặt ts_event là close time và ghi vào catalog.
"""
import sys, os
sys.path.insert(0, "/home/vmc03/norabt/nora")
import time
import pandas as pd
from backend.nautilus.catalog import write_catalog_bars, get_catalog_root, normalize_symbol

DATA_ROOT = "/home/vmc03/norabt/nora/data/market/okx/cex"
SYMBOLS = ["BTC", "ETH", "SOL", "DOGE", "XRP", "ADA", "AVAX", "LINK", "BNB", "TRX"]

def main():
    print("Bắt đầu build ParquetDataCatalog Nautilus...")
    cat_root = get_catalog_root()
    print(f"Catalog destination: {cat_root}")
    
    total_bars = 0
    start_total = time.perf_counter()

    for sym in SYMBOLS:
        pkl_path = os.path.join(DATA_ROOT, sym, "perp", "1m.pkl")
        if not os.path.isfile(pkl_path):
            print(f"Bỏ qua {sym}: không tìm thấy {pkl_path}")
            continue

        print(f"\n--- Đang xử lý {sym} ---")
        t0 = time.perf_counter()
        df = pd.read_pickle(pkl_path)
        t_load = time.perf_counter() - t0
        print(f"  Đã tải {len(df):,} nến từ pkl trong {t_load:.2f} s")

        t1 = time.perf_counter()
        written = write_catalog_bars(sym, df)
        t_write = time.perf_counter() - t1
        total_bars += written
        print(f"  Đã ghi {written:,} nến thật vào catalog trong {t_write:.2f} s ({written / max(t_write, 0.001):,.0f} nến/s)")

    elapsed = time.perf_counter() - start_total
    print(f"\n=== HOÀN TẤT BUILD CATALOG: {total_bars:,} nến cho {len(SYMBOLS)} symbols trong {elapsed:.2f} s ===")

if __name__ == "__main__":
    main()
