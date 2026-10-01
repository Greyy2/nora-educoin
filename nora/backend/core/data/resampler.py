"""Causal Candle Resampler and Manifest Generator.
Phase 1: Single source of truth. All frames (5m, 15m, 1h, 4h, 24h) are strictly
resampled from 1m candles. Missing minutes are filled with previous close, volume=0, is_filled=1.
Resampling is aligned to UTC, label="left", closed="left", 4h anchored at 00:00 UTC.
"""
import os
import json
import hashlib
import time
from typing import Dict, Any, Tuple, Optional
import pandas as pd
import numpy as np

PKL_COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]
TIMEFRAME_MAP = {
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "24h": "24h",
    "1d": "24h",
}


def _fill_missing_1m_candles_with_ratio(df_1m: pd.DataFrame) -> Tuple[pd.DataFrame, float]:
    """
    Internal: Fills gaps in 1m candles. Idempotent: calling twice gives the same result.

    Algorithm:
    1. Strip bất kỳ nến nào đã được điền trước đó (is_filled == 1) ra khỏi input.
       Điều này cho phép dữ liệu thật sau này ghi đè nến điền, và đảm bảo
       fill(fill(x)) == fill(x).
    2. Sort, dedup (keep last: dữ liệu thật thắng nếu trùng ts).
    3. Xây lại lưới thời gian đầy đủ từ min → max bước 60s.
    4. Merge với dữ liệu thật: dòng thiếu → is_filled=1, O=H=L=C=prev_close, volume=0.

    Returns (filled_df, filled_ratio_1m).
    """
    if df_1m.empty:
        df_empty = df_1m.copy()
        if "is_filled" not in df_empty.columns:
            df_empty["is_filled"] = 0
        return df_empty, 0.0

    # ── Bước 1: Strip nến điền cũ để đảm bảo idempotency ─────────────────────
    df = df_1m.copy()
    if "is_filled" in df.columns:
        df = df[df["is_filled"].fillna(0).astype(int) != 1]

    # ── Bước 2: Sort, dedup (keep last = dữ liệu thật thắng nếu trùng ts) ────
    df = df.sort_values("open_time").drop_duplicates("open_time", keep="last").reset_index(drop=True)
    df["is_filled"] = 0

    if df.empty:
        result = df_1m.copy()
        if "is_filled" not in result.columns:
            result["is_filled"] = 0
        return result, 0.0

    min_t = int(df["open_time"].min())
    max_t = int(df["open_time"].max())

    # ── Bước 3: Lưới thời gian đầy đủ ───────────────────────────────────────
    full_times = np.arange(min_t, max_t + 60_000, 60_000, dtype=np.int64)
    grid_df = pd.DataFrame({"open_time": full_times})

    merged = pd.merge(grid_df, df, on="open_time", how="left")

    # ── Bước 4: Điền missing ─────────────────────────────────────────────────
    missing_mask = merged["close"].isna()
    merged.loc[missing_mask, "is_filled"] = 1
    merged.loc[~missing_mask, "is_filled"] = 0
    merged.loc[missing_mask, "volume"] = 0.0

    # Forward fill close (dùng cho O=H=L=C của nến điền)
    merged["close"] = merged["close"].ffill().bfill()
    merged.loc[missing_mask, "open"] = merged.loc[missing_mask, "close"]
    merged.loc[missing_mask, "high"] = merged.loc[missing_mask, "close"]
    merged.loc[missing_mask, "low"] = merged.loc[missing_mask, "close"]

    filled_ratio = float(merged["is_filled"].mean())
    merged["open_time"] = merged["open_time"].astype(np.int64)
    merged["is_filled"] = merged["is_filled"].astype(int)

    return merged, filled_ratio


def fill_missing_1m_candles(df_1m: pd.DataFrame) -> pd.DataFrame:
    """
    Public API: Fills gaps in 1m candles. Idempotent.
    Returns only the filled DataFrame (không kèm filled_ratio).
    """
    filled_df, _ = _fill_missing_1m_candles_with_ratio(df_1m)
    return filled_df




def resample_from_1m(df_1m: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resamples 1m candles into higher timeframe (e.g. 5m, 15m, 1h, 4h, 24h).
    Enforces UTC alignment, label="left", closed="left".
    4h is anchored at 00:00 UTC.
    """
    if df_1m.empty:
        return pd.DataFrame(columns=PKL_COLUMNS)

    rule = TIMEFRAME_MAP.get(timeframe)
    if rule is None:
        if timeframe.endswith("m"):
            rule = f"{timeframe[:-1]}min"
        elif timeframe.endswith("h"):
            rule = timeframe
        else:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

    df = df_1m.copy().sort_values("open_time").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("dt")

    # Resample with left label and left closed boundary
    resampled = df.resample(rule, closed="left", label="left", origin="start_day").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open", "close"])

    scale = 10**6 if "ns" in str(resampled.index.dtype) else (10**3 if "us" in str(resampled.index.dtype) else 1)
    resampled["open_time"] = (resampled.index.astype("int64") // scale).astype(np.int64)
    result = resampled[PKL_COLUMNS].reset_index(drop=True)
    return result


def compute_df_sha256(df: pd.DataFrame) -> str:
    """Computes SHA-256 hash of dataframe values."""
    data_bytes = df[PKL_COLUMNS].to_csv(index=False).encode("utf-8")
    return hashlib.sha256(data_bytes).hexdigest()


def generate_manifest(
    symbol: str,
    pool_address: str,
    df_1m: pd.DataFrame,
    df_4h: pd.DataFrame,
    filled_ratio: float,
    source: str = "geckoterminal",
    synthetic: bool = False,
    extra_rows: Optional[Dict[str, int]] = None,
    crawl_ok: bool = True,
    requested_start_ts: Optional[int] = None,
    requested_end_ts: Optional[int] = None,
    ticks: Optional[Dict[str, Any]] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generates manifest metadata dictionary according to Phase 1 specification.
    extra_meta: metadata bổ sung (vd. venue="cex"/"dex", exchange, market_symbol, network);
    không được ghi đè các trường lõi của manifest.
    """
    start_ts = int(df_1m["open_time"].min()) if not df_1m.empty else 0
    end_ts = int(df_1m["open_time"].max()) if not df_1m.empty else 0
    
    rows = {
        "1m": len(df_1m),
        "4h": len(df_4h) if df_4h is not None and not df_4h.empty else 0,
    }
    if extra_rows:
        rows.update(extra_rows)

    coverage_days = round((end_ts - start_ts) / 86_400_000, 2) if end_ts > start_ts else 0.0
    if requested_start_ts is not None and requested_end_ts is not None and requested_end_ts > requested_start_ts:
        coverage_ratio = round((end_ts - start_ts) / max(1, requested_end_ts - requested_start_ts), 3)
    else:
        coverage_ratio = 1.0

    manifest = {
        "source": source,
        "symbol": symbol,
        "pool_address": pool_address,
        "base_resolution": "1m",
        "synthetic": synthetic,
        "crawled_at": int(time.time()),
        "crawl_ok": crawl_ok,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "requested_start_ts": requested_start_ts,
        "requested_end_ts": requested_end_ts,
        "coverage_days": coverage_days,
        "coverage_ratio": coverage_ratio,
        "rows": rows,
        "filled_ratio_1m": round(filled_ratio, 4),
        "sha256_1m": compute_df_sha256(df_1m) if not df_1m.empty else "",
    }
    if ticks is not None:
        manifest["ticks"] = ticks
    for key, value in (extra_meta or {}).items():
        if key not in manifest:
            manifest[key] = value
    return manifest


def save_resampled_dataset(
    symbol: str,
    output_dir: str,
    df_1m_raw: pd.DataFrame,
    pool_address: str,
    timeframes: Tuple[str, ...] = ("5m", "15m", "1h", "4h", "24h"),
    source: str = "geckoterminal",
    synthetic: bool = False,
    crawl_ok: bool = True,
    requested_start_ts: Optional[int] = None,
    requested_end_ts: Optional[int] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Fills 1m gaps, resamples all target timeframes, writes pkl files and manifest.json.
    """
    target_dir = os.path.join(output_dir, symbol)
    os.makedirs(target_dir, exist_ok=True)

    # Read existing manifest to preserve ticks metadata if present
    existing_manifest_path = os.path.join(target_dir, "manifest.json")
    existing_ticks = None
    if os.path.isfile(existing_manifest_path):
        try:
            with open(existing_manifest_path, "r", encoding="utf-8") as f:
                old_m = json.load(f)
                existing_ticks = old_m.get("ticks")
        except Exception:
            pass

    df_1m, filled_ratio = _fill_missing_1m_candles_with_ratio(df_1m_raw)
    
    # Save 1m
    df_1m.to_pickle(os.path.join(target_dir, "1m.pkl"))

    rows_dict = {"1m": len(df_1m)}
    df_4h = None
    for tf in timeframes:
        df_resampled = resample_from_1m(df_1m, tf)
        df_resampled.to_pickle(os.path.join(target_dir, f"{tf}.pkl"))
        rows_dict[tf] = len(df_resampled)
        if tf == "4h":
            df_4h = df_resampled

    if df_4h is None:
        df_4h = resample_from_1m(df_1m, "4h")

    manifest = generate_manifest(
        symbol=symbol,
        pool_address=pool_address,
        df_1m=df_1m,
        df_4h=df_4h,
        filled_ratio=filled_ratio,
        source=source,
        synthetic=synthetic,
        extra_rows=rows_dict,
        crawl_ok=crawl_ok,
        requested_start_ts=requested_start_ts,
        requested_end_ts=requested_end_ts,
        ticks=existing_ticks,
        extra_meta=extra_meta,
    )

    manifest_path = os.path.join(target_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest
