"""Cửa sổ dữ liệu của phễu: dev1 / dev2 / holdout (cùng công thức build_strategy_book.windows) + fold WFA."""
from typing import Dict, List, Optional

import pandas as pd

from . import gates

DAY = 86_400_000


def _ms(date_str: str) -> int:
    return int(pd.Timestamp(date_str, tz="UTC").value // 1_000_000)


def iso_date(ts: int) -> str:
    return f"{pd.Timestamp(int(ts), unit='ms'):%Y-%m-%d}"


def compute_windows(symbols: List[str], override: Optional[Dict[str, str]] = None) -> Dict[str, int]:
    """{"start", "dev1_end", "dev2_end", "end"} (ms UTC). Mặc định: start = max(đầu dữ liệu) + WARMUP, end = min(cuối dữ liệu),
    dev1 = 40% đầu, dev2 = 40% tiếp, holdout = 20% cuối. `override` ({khoá: "YYYY-MM-DD"}) ghi đè từng mốc; mốc phải tăng dần."""
    from backend.db.local_pkl import read_manifest
    ms = [read_manifest(s) for s in symbols]
    if not all(ms):
        raise SystemExit(f"Thiếu dữ liệu (manifest) cho: {[s for s, m in zip(symbols, ms) if not m]}")
    start = max(int(m["start_ts"]) for m in ms) + gates.WARMUP_DAYS * DAY
    end = min(int(m["end_ts"]) for m in ms)
    span = end - start
    w = {"start": start, "dev1_end": start + int(span * gates.DEV1_FRAC), "dev2_end": start + int(span * gates.DEV2_FRAC), "end": end}
    for k, v in (override or {}).items():
        if k not in w:
            raise ValueError(f"windows: khoá lạ {k!r}; có: {sorted(w)}")
        w[k] = _ms(v)
    if not (w["start"] < w["dev1_end"] < w["dev2_end"] < w["end"]):
        raise ValueError("windows: phải có start < dev1_end < dev2_end < end")
    return w


def windows_iso(w: Dict[str, int]) -> Dict[str, str]:
    return {k: iso_date(v) for k, v in w.items()}


def wfa_folds(w: Dict[str, int], train_days: Optional[int] = None, test_days: Optional[int] = None) -> List[Dict[str, int]]:
    """Fold WFA trên dev2 (dev1_end -> dev2_end), OOS liền nhau không chồng lấp."""
    from backend.wfa.walk_forward import generate_folds
    return generate_folds(int(w["dev1_end"]), int(w["dev2_end"]), train_days or gates.S3_TRAIN_DAYS, test_days or gates.S3_TEST_DAYS)
