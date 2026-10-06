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

from backend.db.local_pkl import _frame_ms

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




def ticks_to_bars(ticks_df: pd.DataFrame, frame: str = "1m", price_col: str = "price") -> pd.DataFrame:
    """Tick -> nến khung `frame` ("1m", "5m", "15m", "1h", "4h", "1d"...; mốc thẳng epoch UTC): open_time ms, OHLC theo `price_col`, volume = tổng volume_usd,
    n_trades = số swap, n_fallback = số swap phải dùng `price` (giá khớp) vì `price_col` NaN, vwap = Σvolume_usd/Σamount của giá KHỚP, is_filled.
    Mặc định OHLC theo giá KHỚP `price` (gồm phí pool): đây chính là cơ sở nến của GeckoTerminal (đo: nến GT tính theo token quote trùng close giá khớp cuối phút, chênh
    median 0 bps trên 161 phút; còn mid_price lệch đúng mức phí pool ~30 bps). price_col="mid_price" -> OHLC theo giá biên sau swap (giá swap không bị phí làm lệch, dùng
    cho phân tích giá pool; swap thiếu mid dùng price và được đếm ở n_fallback).
    Lưới đủ từ nến tick đầu tới nến tick cuối: nến không có swap -> is_filled=1, n_trades=0, volume 0, O=H=L=C=vwap=close trước (không bịa lệnh).
    Chỉ để đối chiếu/phân tích — KHÔNG ghi vào kho nến."""
    cols = PKL_COLUMNS + ["n_trades", "n_fallback", "vwap", "is_filled"]
    step = _frame_ms(frame)
    if step <= 0:
        raise ValueError(f"khung không hợp lệ: {frame!r} (vd. 1m, 15m, 1h, 1d)")
    if ticks_df.empty:
        return pd.DataFrame(columns=cols)
    t = ticks_df.sort_values("timestamp_ms", kind="stable")
    px = t[price_col] if price_col in t.columns else pd.Series(np.nan, index=t.index)
    t = t.assign(_px=px.fillna(t["price"]), _fb=px.isna().astype(int))
    grp = t.groupby((t["timestamp_ms"] // step * step).astype(np.int64).rename("open_time"))
    bars = pd.DataFrame({"open": grp["_px"].first(), "high": grp["_px"].max(), "low": grp["_px"].min(), "close": grp["_px"].last(),
                         "volume": grp["volume_usd"].sum(), "n_trades": grp["_px"].size(), "n_fallback": grp["_fb"].sum(),
                         "vwap": grp["volume_usd"].sum() / grp["amount"].sum()})
    grid = np.arange(bars.index.min(), bars.index.max() + step, step, dtype=np.int64)
    out = bars.reindex(pd.Index(grid, name="open_time"))
    filled = out["close"].isna()
    out["close"] = out["close"].ffill()
    for c in ("open", "high", "low", "vwap"):
        out.loc[filled, c] = out.loc[filled, "close"]
    out["volume"] = out["volume"].fillna(0.0)
    for c in ("n_trades", "n_fallback"):
        out[c] = out[c].fillna(0).astype(np.int64)
    out["is_filled"] = filled.astype(int)
    return out.reset_index()[cols]


def ticks_to_1m(ticks_df: pd.DataFrame, price_col: str = "price") -> pd.DataFrame:
    """Tick -> nến 1m (xem ticks_to_bars): open_time thẳng phút UTC + n_trades, n_fallback, vwap, is_filled."""
    return ticks_to_bars(ticks_df, "1m", price_col)


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
