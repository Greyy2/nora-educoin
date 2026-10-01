"""
Parallel GeckoTerminal OHLCV crawler.
Crawls multiple assets concurrently using a shared Token Bucket rate limiter
to stay within GeckoTerminal's 30 req/min public API limit.

Strategy (Method A - Single IP, Multi-threaded):
  - N workers run in parallel, one per asset
  - All API calls share a single TokenBucket (30 tokens/min = 1 token/2.1s)
  - Smart resume: skips assets that already have valid 1m.pkl files
  - Real-time per-asset progress logging
"""
import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests

# ─── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_BASE_URL = "https://api.geckoterminal.com/api/v2"
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from backend.core.resampler import save_resampled_dataset  # noqa: E402

# Dữ liệu DEX ghi vào data/dex/<SYM>; danh sách target ở data/_meta (xem backend/db/data_layout.py)
DEFAULT_OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "dex"))
DEFAULT_LIMIT = 500
DEFAULT_LOOKBACK_DAYS = 120.0
DEFAULT_MINUTE_MAX_PAGES = 400
DEFAULT_RETRIES = 5
DEFAULT_RETRY_DELAY_SEC = 30.0
DEFAULT_REQUESTS_PER_MINUTE = 28  # stay slightly under 30 to be safe
DEFAULT_WORKERS = 4
DEFAULT_TARGETS_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "_meta", "geckoterminal_targets.json")
)

MINUTE_MS = 60 * 1000
PKL_COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]

# ─── Thread-safe logging ────────────────────────────────────────────────────────
_log_lock = threading.Lock()


def log(asset: str, message: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    with _log_lock:
        print(f"[{ts}] [{asset:12s}] {message}", flush=True)


def warn(asset: str, message: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    with _log_lock:
        print(f"[{ts}] [{asset:12s}] ⚠ {message}", flush=True, file=sys.stderr)


# ─── Token Bucket Rate Limiter ──────────────────────────────────────────────────
class TokenBucket:
    """Thread-safe token bucket for rate limiting shared across all workers."""

    def __init__(self, rate_per_minute: float):
        self._rate = rate_per_minute / 60.0  # tokens per second
        self._tokens = rate_per_minute       # start full
        self._max_tokens = rate_per_minute
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a token is available, then consume it."""
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(
                    self._max_tokens,
                    self._tokens + elapsed * self._rate
                )
                self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Calculate exact sleep time needed
                needed = (1.0 - self._tokens) / self._rate
            time.sleep(needed)


# ─── Helpers ───────────────────────────────────────────────────────────────────
class RateLimitError(RuntimeError):
    pass


def _to_seconds(value: Any) -> int:
    if value is None:
        raise ValueError("timestamp is required")
    if isinstance(value, (int, float)):
        num = int(value)
        return num // 1000 if num >= 10**12 else num
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return _to_seconds(int(s))
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    raise TypeError(f"Unsupported timestamp type: {type(value)!r}")


def _asset_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_]+", "", value).strip("_")
    return (slug or "POOL").upper()[:32]


def _api_get(
    bucket: TokenBucket,
    base_url: str,
    path: str,
    params: Dict[str, Any],
    timeout: int,
    retries: int,
    retry_delay_sec: float,
    asset: str,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    clean_params = {k: v for k, v in params.items() if v is not None}
    for attempt in range(retries + 1):
        bucket.acquire()  # wait for rate limit token
        try:
            response = requests.get(
                url,
                params=clean_params,
                headers={"accept": "application/json"},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            if attempt >= retries:
                raise
            wait_sec = retry_delay_sec * (attempt + 1)
            warn(asset, f"Request failed ({exc}); retrying in {wait_sec:.1f}s [{attempt+1}/{retries}]")
            time.sleep(wait_sec)
            continue

        if response.status_code != 429:
            response.raise_for_status()
            return response.json()
        if attempt >= retries:
            raise RateLimitError(f"429 Too Many Requests for {path}")
        retry_after = response.headers.get("Retry-After")
        wait_sec = retry_delay_sec * (attempt + 1)
        if retry_after and retry_after.isdigit():
            wait_sec = max(wait_sec, float(retry_after))
        warn(asset, f"Rate limited (429); sleeping {wait_sec:.1f}s [{attempt+1}/{retries}]")
        time.sleep(wait_sec)
    raise RuntimeError("unreachable retry state")


def _extract_rows(payload: Dict[str, Any]) -> List[List[Any]]:
    data = payload.get("data") or {}
    attributes = data.get("attributes") or {}
    rows = attributes.get("ohlcv_list") or []
    normalized = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) >= 6:
            normalized.append(list(row[:6]))
    return normalized


def _normalize_rows(raw_rows: Iterable[List[Any]], start_sec: int, end_sec: int) -> pd.DataFrame:
    records: Dict[int, Dict[str, Any]] = {}
    for row in raw_rows:
        ts = int(row[0])
        if ts < start_sec or ts > end_sec:
            continue
        ts_ms = ts * 1000 if ts < 10**12 else ts
        records[ts_ms] = {
            "open_time": ts_ms,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
    if not records:
        return pd.DataFrame(columns=PKL_COLUMNS)
    df = pd.DataFrame(sorted(records.values(), key=lambda r: r["open_time"]))
    return df[PKL_COLUMNS].reset_index(drop=True)


def _aggregate_frame(frame: pd.DataFrame, interval_ms: int) -> pd.DataFrame:
    if frame.empty:
        return frame.loc[:, PKL_COLUMNS].copy()
    ordered = frame.loc[:, PKL_COLUMNS].sort_values("open_time").reset_index(drop=True)
    buckets = (ordered["open_time"] // interval_ms) * interval_ms
    grouped = (
        ordered.assign(_bucket=buckets)
        .groupby("_bucket", as_index=False, sort=True)
        .agg(
            open_time=("_bucket", "first"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
    )
    return grouped.loc[:, PKL_COLUMNS]


def _write_pickle(path: str, frame: pd.DataFrame) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    frame.to_pickle(path)


# ─── Core crawl for a single asset ─────────────────────────────────────────────
def _crawl_asset(
    target: Dict[str, str],
    bucket: TokenBucket,
    base_url: str,
    output_dir: str,
    start_sec: int,
    end_sec: int,
    limit: int,
    minute_aggregates: List[int],
    minute_max_pages: int,
    retries: int,
    retry_delay_sec: float,
    timeout: int,
    resume: bool,
    stagger_sec: float = 0.0,
) -> Dict[str, Any]:
    asset = _asset_slug(target["asset"])
    network = target["network"]
    pool_address = target["pool_address"]
    asset_dir = os.path.join(output_dir, asset)
    one_minute_path = os.path.join(asset_dir, "1m.pkl")

    # ── Resume: skip if already complete ──────────────────────────────────────
    if resume and os.path.isfile(one_minute_path):
        log(asset, f"✓ Skipping (1m.pkl already exists)")
        return {"asset": asset, "status": "skipped", "rows": 0}

    # ── Stagger start to avoid burst at t=0 ──────────────────────────────────
    if stagger_sec > 0:
        log(asset, f"Stagger delay {stagger_sec:.1f}s before first request...")
        time.sleep(stagger_sec)

    log(asset, f"Starting crawl | pool={pool_address} | network={network}")
    log(asset, f"Range: {datetime.fromtimestamp(start_sec, timezone.utc).strftime('%Y-%m-%d')} → {datetime.fromtimestamp(end_sec, timezone.utc).strftime('%Y-%m-%d')}")

    # ── Crawl 1m source ───────────────────────────────────────────────────────
    path = f"/networks/{network}/pools/{pool_address}/ohlcv/minute"
    before_timestamp = end_sec
    page = 0
    raw_rows: List[List[Any]] = []
    total_candles = 0

    while True:
        page += 1
        if minute_max_pages and page > minute_max_pages:
            warn(asset, f"Reached max_pages={minute_max_pages}; stopping early.")
            break

        try:
            payload = _api_get(
                bucket, base_url, path,
                {
                    "aggregate": 1,
                    "before_timestamp": before_timestamp,
                    "limit": limit,
                    "currency": "usd",
                    "token": "base",
                    "include_empty_intervals": "false",
                },
                timeout, retries, retry_delay_sec, asset,
            )
        except Exception as exc:
            warn(asset, f"Page {page} failed: {exc}")
            break

        rows = _extract_rows(payload)
        if not rows:
            break

        raw_rows.extend(rows)
        total_candles += len(rows)
        oldest_sec = min(int(r[0]) for r in rows)
        oldest_dt = datetime.fromtimestamp(oldest_sec, timezone.utc).strftime("%Y-%m-%d")

        log(asset, f"Page {page:3d} | +{len(rows):4d} candles | total={total_candles:6d} | oldest={oldest_dt}")

        if oldest_sec <= start_sec:
            break
        if len(rows) < limit:
            break
        next_before = oldest_sec - 1
        if next_before >= before_timestamp:
            break
        before_timestamp = next_before

    # ── Normalize & write ────────────────────────────────────────────────────
    try:
        frame_1m = _normalize_rows(raw_rows, start_sec, end_sec)
    except Exception as exc:
        warn(asset, f"Normalize failed: {exc}")
        return {"asset": asset, "status": "error", "error": str(exc), "rows": 0}

    if frame_1m.empty:
        warn(asset, "No data returned – skipping write.")
        return {"asset": asset, "status": "empty", "rows": 0}

    # Một nguồn duy nhất: 1m -> core/resampler (điền phút trống, resample, manifest.json).
    # minute_aggregates chỉ còn để tương thích tham số CLI; các khung do resampler sinh.
    crawl_ok = bool(raw_rows) and min(int(r[0]) for r in raw_rows) <= start_sec + 86400
    manifest = save_resampled_dataset(
        symbol=asset, output_dir=output_dir, df_1m_raw=frame_1m, pool_address=pool_address,
        source="geckoterminal", synthetic=False, crawl_ok=crawl_ok,
        requested_start_ts=start_sec * 1000, requested_end_ts=end_sec * 1000,
        extra_meta={"venue": "dex", "exchange": "geckoterminal", "network": network, "volume_unit": "usd"},
    )
    log(asset, f"✓ Wrote 1m + resampled frames + manifest | rows={manifest['rows']['1m']} "
               f"filled={manifest['filled_ratio_1m']:.3f} crawl_ok={crawl_ok} pages={page}")

    return {"asset": asset, "status": "done", "rows": len(frame_1m), "pages": page}


# ─── Entry point ───────────────────────────────────────────────────────────────
def run(args: argparse.Namespace) -> None:
    base_url = os.environ.get("GECKOTERMINAL_BASE_URL", DEFAULT_BASE_URL)
    output_dir = os.path.abspath(
        os.environ.get("GECKOTERMINAL_FULL_OUTPUT_DIR", args.output_dir)
    )
    timeout = int(os.environ.get("GECKOTERMINAL_TIMEOUT", "30"))
    targets_file = args.targets_file or os.environ.get(
        "GECKOTERMINAL_FULL_TARGETS_FILE", DEFAULT_TARGETS_FILE
    )

    # Load targets
    if not targets_file or not os.path.isfile(targets_file):
        print(f"[fatal] Targets file not found: {targets_file}", file=sys.stderr)
        sys.exit(1)
    with open(targets_file, "r", encoding="utf-8") as f:
        raw = json.load(f)
    targets = [
        {
            "asset": _asset_slug(str(t.get("asset", ""))),
            "network": str(t.get("network", "")).strip(),
            "pool_address": str(t.get("pool_address", "")).strip(),
            "name": str(t.get("name", "")),
        }
        for t in raw
        if t.get("asset") and t.get("network") and t.get("pool_address")
    ]

    # Time range
    end_sec = int(time.time())
    start_sec = end_sec - int(args.lookback_days * 86400)

    # Minute aggregates
    minute_aggregates = sorted(set(int(x) for x in args.minutes.split(",") if x.strip()))
    if 1 not in minute_aggregates:
        minute_aggregates = [1] + minute_aggregates

    # Token bucket
    bucket = TokenBucket(rate_per_minute=args.requests_per_minute)

    workers = min(args.workers, len(targets))
    print(
        f"\n[parallel] {len(targets)} assets | {workers} workers | "
        f"{args.requests_per_minute} req/min (shared bucket)\n"
        f"[range]    {datetime.fromtimestamp(start_sec, timezone.utc).isoformat()} → "
        f"{datetime.fromtimestamp(end_sec, timezone.utc).isoformat()}\n"
        f"[output]   {output_dir}\n",
        flush=True,
    )

    # Stagger delay per worker: worker i waits i * stagger_sec
    # This avoids a burst of simultaneous requests at startup.
    stagger_sec_per_worker = 60.0 / args.requests_per_minute  # = ~2.14s per slot

    results = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="crawler") as executor:
        futures = {}
        for idx, target in enumerate(targets):
            stagger = idx * stagger_sec_per_worker
            future = executor.submit(
                _crawl_asset,
                target,
                bucket,
                base_url,
                output_dir,
                start_sec,
                end_sec,
                args.limit,
                minute_aggregates,
                args.minute_max_pages,
                args.retries,
                args.retry_delay_sec,
                timeout,
                args.resume,
                stagger,
            )
            futures[future] = target["asset"]
        for future in as_completed(futures):
            asset = futures[future]
            try:
                result = future.result()
                results.append(result)
                status = result.get("status", "?")
                rows = result.get("rows", 0)
                pages = result.get("pages", "-")
                log(asset, f"[DONE] status={status} rows={rows} pages={pages}")
            except Exception as exc:
                warn(asset, f"[FAILED] {exc}")
                results.append({"asset": asset, "status": "exception", "error": str(exc)})

    print("\n[summary]", flush=True)
    for r in sorted(results, key=lambda x: x["asset"]):
        print(
            f"  {r['asset']:12s} status={r.get('status','?'):8s} "
            f"rows={r.get('rows', 0):6d} pages={r.get('pages', '-')}",
            flush=True,
        )
    print("[done] Parallel crawl finished.", flush=True)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parallel GeckoTerminal DEX OHLCV crawler with Token Bucket rate limiting."
    )
    parser.add_argument("--targets-file", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--minutes", default="1,5,10,15",
                        help="Comma-separated minute aggregates to build (e.g. 1,5,10,15)")
    parser.add_argument("--lookback-days", type=float, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help="OHLCV rows per API page (max 500)")
    parser.add_argument("--minute-max-pages", type=int, default=DEFAULT_MINUTE_MAX_PAGES)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--retry-delay-sec", type=float, default=DEFAULT_RETRY_DELAY_SEC)
    parser.add_argument("--requests-per-minute", type=float, default=DEFAULT_REQUESTS_PER_MINUTE,
                        help="Shared rate limit across all workers (default: 28)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help="Number of parallel workers (assets crawled simultaneously)")
    parser.add_argument("--resume", action="store_true", default=True,
                        help="Skip assets that already have a valid 1m.pkl (default: True)")
    parser.add_argument("--no-resume", dest="resume", action="store_false",
                        help="Force re-crawl all assets even if 1m.pkl exists")
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
