# ARCHIVED (P17-T1 B4): script của kho pkl / backend.crawl cũ (catalog nay cập nhật bằng job data_update -> backend.data.crawl).
import sys, os
sys.path.insert(0, "/home/vmc03/norabt/nora")
import tempfile
import pandas as pd
from backend.nautilus.catalog import (
    get_instrument,
    get_bar_type,
    df_1m_to_nautilus_bars,
    write_catalog_bars,
    load_catalog_bars,
)

inst = get_instrument("BTC")
print("Instrument created:", inst.id, "tickSz:", inst.price_increment, "lotSz:", inst.lot_size)
bt = get_bar_type("BTC", "1m")
print("BarType:", bt)

df = pd.read_pickle("/home/vmc03/norabt/nora/data/market/okx/cex/BTC/perp/1m.pkl").head(100)
bars = df_1m_to_nautilus_bars("BTC", df)
print("Converted bars count:", len(bars))
print("First bar:", bars[0])

with tempfile.TemporaryDirectory() as tmpdir:
    written = write_catalog_bars("BTC", df, catalog_path=tmpdir)
    print("Catalog written bars:", written)

print("ALL CATALOG TESTS PASSED!")
