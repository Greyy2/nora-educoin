"""Mặc định MỘT chỗ của backtest chiến lược Python (custom_run, edu_precompute, GET /api/studio/custom/defaults): rổ + cửa sổ ngày + vốn đều lấy từ kho dữ liệu OKX.

Module nhẹ (không đặt biến môi trường của job như custom_run) để API và job cùng import được.
"""
from datetime import datetime, timezone
from typing import Dict, List, Tuple

DAY = 86_400_000
DEFAULT_CAPITAL = 10_000.0
DEFAULT_TRAIN_RATIO = 0.7


def iso_day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def default_universe() -> List[str]:
    """Rổ mặc định = mọi tài sản perp CEX có trong kho dữ liệu của sàn đang dùng (OKX), tên cơ sở đã sắp xếp."""
    from backend.crawl.store import list_assets
    return sorted({a["symbol"].split("@")[0] for a in list_assets() if a["venue"] == "cex" and a.get("instrument") == "perp"})


def default_window() -> Tuple[str, str]:
    """(start, end) 'YYYY-MM-DD' = phần dữ liệu chung của cả rổ: sau nến đầu muộn nhất 1 ngày, trước nến cuối sớm nhất 1 ngày."""
    from backend.crawl.store import read_manifest
    firsts, lasts = [], []
    for n in default_universe():
        m = read_manifest(f"{n}@perp") or {}
        if m.get("start_ts") and m.get("end_ts"):
            firsts.append(int(m["start_ts"]))
            lasts.append(int(m["end_ts"]))
    if not firsts:
        raise ValueError("Kho dữ liệu chưa có manifest (start_ts/end_ts) cho rổ mặc định")
    return iso_day(max(firsts) + DAY), iso_day(min(lasts) - DAY)


def run_defaults() -> Dict[str, object]:
    start, end = default_window()
    return {"symbols": [f"{n}@perp" for n in default_universe()], "start": start, "end": end,
            "train_ratio": DEFAULT_TRAIN_RATIO, "initial_capital": DEFAULT_CAPITAL}
