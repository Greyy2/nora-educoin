"""Helper dựng tài sản thử có metadata trong attrs (thay cho việc test tự ghi manifest.json / dex_pool.json).

write_asset      thư mục tài sản tối thiểu (1m.pkl + 24h.pkl nhỏ) với attrs["nora"] = meta
patch_meta       sửa attrs["nora"] của MỌI khung pkl của một tài sản (giá trị None = xoá khoá)
set_ticks_attrs  ghi lại attrs của ticks.parquet (ticks / onchain)
"""
import os
from typing import Any, Dict, Optional

import pandas as pd

from backend.crawl import store

_T0 = 1_700_000_000_000 // 60_000 * 60_000


def _tiny(n: int = 3, step_ms: int = 60_000) -> pd.DataFrame:
    t = [_T0 + i * step_ms for i in range(n)]
    return pd.DataFrame({"open_time": t, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0, "is_filled": 0})


def write_asset(root: str, venue: str, sym: str, instrument: Optional[str] = None, **meta: Any) -> str:
    """<root>/<venue>/<sym>[/<instrument>]/ với 1m.pkl + 24h.pkl (3 nến) mang attrs {"venue", "symbol", **meta}. Trả thư mục tài sản."""
    d = os.path.join(root, venue, sym, *([instrument] if instrument else []))
    os.makedirs(d, exist_ok=True)
    full = {"venue": venue, "symbol": f"{sym}@{instrument}" if instrument else sym, **meta}
    for frame, step in (("1m", 60_000), ("24h", 86_400_000)):
        store.write_pickle_atomic(store.stamp_attrs(_tiny(step_ms=step), full), os.path.join(d, f"{frame}.pkl"))
    return d


def patch_meta(asset_dir: str, **updates: Any) -> Dict[str, Any]:
    """Sửa attrs["nora"] của mọi <khung>.pkl trong asset_dir; None xoá khoá. Trả metadata mới. Xoá cache metadata để lần đọc sau thấy ngay."""
    new: Dict[str, Any] = {}
    for name in sorted(os.listdir(asset_dir)):
        if not name.endswith(".pkl") or name == "funding.pkl":
            continue
        path = os.path.join(asset_dir, name)
        df = pd.read_pickle(path)
        meta = dict(df.attrs.get(store.ATTR_KEY) or {})
        for k, v in updates.items():
            if v is None:
                meta.pop(k, None)
            else:
                meta[k] = v
        store.write_pickle_atomic(store.stamp_attrs(df, meta), path)
        new = meta
    store._META_CACHE.clear()
    return new


def set_ticks_attrs(asset_dir: str, ticks: Optional[dict] = None, onchain: Optional[dict] = None) -> None:
    """Ghi lại attrs["nora"] của ticks.parquet (giữ dữ liệu)."""
    path = os.path.join(asset_dir, "ticks.parquet")
    store.write_parquet_atomic(pd.read_parquet(path), path, {"ticks": ticks, "onchain": onchain})
    store._META_CACHE.clear()
