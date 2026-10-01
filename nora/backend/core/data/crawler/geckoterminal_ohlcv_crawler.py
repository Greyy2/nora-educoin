"""Crawler for GeckoTerminal public DEX OHLCV data."""
import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

DEFAULT_BASE_URL = "https://api.geckoterminal.com/api/v2"
DEFAULT_LIMIT = 50
DEFAULT_PAGE_DELAY_SEC = 12.0
DEFAULT_RETRIES = 5
DEFAULT_RETRY_DELAY_SEC = 60.0
DEFAULT_HOURLY_AGGREGATES = "1-24"
DEFAULT_CURRENCY = "usd"
DEFAULT_TOKEN = "base"

CSV_FIELDS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
]


def _to_seconds(value: Any) -> int:
    if value is None:
        raise ValueError("timestamp is required")
    if isinstance(value, (int, float)):
        num = int(value)
        if num >= 10**12:
            return num // 1000
        return num
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return _to_seconds(int(s))
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    raise TypeError(f"Unsupported timestamp type: {type(value)!r}")


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_]+", "", value).strip("_")
    return (slug or "pool").lower()[:32]


def _timeframe_label(timeframe: str, aggregate: int) -> str:
    suffix = {"second": "s", "minute": "m", "hour": "h", "day": "d"}[timeframe]
    return f"{aggregate}{suffix}"


def _api_get(
    base_url: str,
    path: str,
    params: Dict[str, Any],
    timeout: int,
    retries: int,
    retry_delay_sec: float,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    clean_params = {k: v for k, v in params.items() if v is not None}
    for attempt in range(retries + 1):
        resp = requests.get(url, params=clean_params, headers={"accept": "application/json"}, timeout=timeout)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp.json()
        if attempt >= retries:
            resp.raise_for_status()
        retry_after = resp.headers.get("Retry-After")
        wait_sec = retry_delay_sec * (attempt + 1)
        if retry_after and retry_after.isdigit():
            wait_sec = max(wait_sec, float(retry_after))
        print(f"[warn] Rate limited, sleeping {wait_sec:.1f}s before retry {attempt + 1}/{retries}.", file=sys.stderr)
        time.sleep(wait_sec)
    raise RuntimeError("unreachable retry state")


def _extract_rows(payload: Dict[str, Any]) -> List[List[Any]]:
    data = payload.get("data") or {}
    attributes = data.get("attributes") or {}
    rows = attributes.get("ohlcv_list") or []
    normalized = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        normalized.append(list(row[:6]))
    return normalized


def _normalize_rows(raw_rows: List[List[Any]]) -> List[Dict[str, Any]]:
    by_open_time: Dict[int, Dict[str, Any]] = {}
    for row in raw_rows:
        open_time_ms = int(row[0]) * 1000
        if open_time_ms in by_open_time:
            continue
        by_open_time[open_time_ms] = {
            "open_time": open_time_ms,
            "open": row[1],
            "high": row[2],
            "low": row[3],
            "close": row[4],
            "volume": row[5],
        }
    normalized = list(by_open_time.values())
    normalized.sort(key=lambda r: r["open_time"])
    return normalized


def _read_csv_rows(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rows.append(
                    {
                        "open_time": int(row["open_time"]),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["volume"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
    rows.sort(key=lambda r: r["open_time"])
    return rows


def _parse_hourly_aggregates(value: str) -> List[int]:
    hours = set()
    for part in value.split(","):
        part = part.strip().lower().removesuffix("h")
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            hours.update(range(int(start), int(end) + 1))
        else:
            hours.add(int(part))
    if not hours:
        raise ValueError("--hourly-aggregates must not be empty")
    invalid = [hour for hour in hours if hour < 1 or hour > 24]
    if invalid:
        raise ValueError("--hourly-aggregates values must be between 1 and 24")
    return sorted(hours)


def _aggregate_rows(rows: List[Dict[str, Any]], interval_ms: int) -> List[Dict[str, Any]]:
    buckets: Dict[int, Dict[str, Any]] = {}
    for row in sorted(rows, key=lambda r: int(r["open_time"])):
        open_time = int(row["open_time"])
        bucket_open_time = (open_time // interval_ms) * interval_ms
        bucket = buckets.get(bucket_open_time)
        if bucket is None:
            buckets[bucket_open_time] = {
                "open_time": bucket_open_time,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            }
            continue
        bucket["high"] = max(float(bucket["high"]), float(row["high"]))
        bucket["low"] = min(float(bucket["low"]), float(row["low"]))
        bucket["close"] = row["close"]
        bucket["volume"] = float(bucket["volume"]) + float(row["volume"])
    aggregated = list(buckets.values())
    aggregated.sort(key=lambda r: r["open_time"])
    return aggregated


def _build_hourly_files(asset_dir: str, rows_1m: List[Dict[str, Any]], hourly_aggregates: List[int]) -> List[str]:
    paths = []
    for hours in hourly_aggregates:
        path = os.path.join(asset_dir, f"{hours}h.csv")
        rows = _aggregate_rows(rows_1m, hours * 60 * 60 * 1000)
        _write_csv(path, rows, append=False)
        print(f"Built {len(rows)} rows to {path}")
        paths.append(path)
    return paths


def _merge_with_existing_rows(path: str, new_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    existing: Dict[int, Dict[str, Any]] = {}
    if os.path.exists(path):
        with open(path, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    open_time = int(row["open_time"])
                except (KeyError, ValueError):
                    continue
                existing[open_time] = row
    for row in new_rows:
        existing[int(row["open_time"])] = row
    merged = list(existing.values())
    merged.sort(key=lambda r: int(r["open_time"]))
    return merged


def _write_csv(path: str, rows: List[Dict[str, Any]], append: bool) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if append:
        rows = _merge_with_existing_rows(path, rows)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in CSV_FIELDS})


def crawl(args: argparse.Namespace) -> str:
    base_url = os.environ.get("GECKOTERMINAL_BASE_URL", DEFAULT_BASE_URL)
    timeout = int(os.environ.get("GECKOTERMINAL_TIMEOUT", "30"))
    retries = args.retries if args.retries is not None else int(os.environ.get("GECKOTERMINAL_RETRIES", str(DEFAULT_RETRIES)))
    retry_delay_sec = args.retry_delay_sec
    if retry_delay_sec is None:
        retry_delay_sec = float(os.environ.get("GECKOTERMINAL_RETRY_DELAY_SEC", str(DEFAULT_RETRY_DELAY_SEC)))
    limit = args.limit or int(os.environ.get("GECKOTERMINAL_LIMIT", str(DEFAULT_LIMIT)))
    page_delay_sec = args.page_delay_sec
    if page_delay_sec is None:
        page_delay_sec = float(os.environ.get("GECKOTERMINAL_PAGE_DELAY_SEC", str(DEFAULT_PAGE_DELAY_SEC)))

    if limit < 1 or limit > 1000:
        raise ValueError("--limit must be between 1 and 1000")
    if page_delay_sec < 0:
        raise ValueError("--page-delay-sec must be non-negative")
    if retries < 0:
        raise ValueError("--retries must be non-negative")
    if retry_delay_sec < 0:
        raise ValueError("--retry-delay-sec must be non-negative")
    if args.timeframe not in {"minute", "hour", "day", "second"}:
        raise ValueError("--timeframe must be one of: minute, hour, day, second")
    if args.currency not in {"usd", "token"}:
        raise ValueError("--currency must be usd or token")
    if args.token not in {"base", "quote"} and not re.fullmatch(r"[A-Za-z0-9:_\-]+", args.token):
        raise ValueError("--token must be base, quote, or a token address")

    if args.end_ts is not None:
        end_sec = _to_seconds(args.end_ts)
    else:
        end_sec = int(time.time())

    if args.start_ts is not None:
        start_sec = _to_seconds(args.start_ts)
    elif args.lookback_days is not None:
        start_sec = end_sec - int(args.lookback_days * 86400)
    else:
        raise ValueError("Must provide either --start-ts or --lookback-days")

    if start_sec >= end_sec:
        raise ValueError("start timestamp must be smaller than end timestamp")

    path = f"/networks/{args.network}/pools/{args.pool_address}/ohlcv/{args.timeframe}"
    all_rows: List[List[Any]] = []
    before_timestamp = end_sec
    page = 0

    while True:
        page += 1
        if args.max_pages and page > args.max_pages:
            print(f"[warn] Reached --max-pages={args.max_pages}, stopping pagination early.", file=sys.stderr)
            break

        payload = _api_get(
            base_url,
            path,
            {
                "aggregate": args.aggregate,
                "before_timestamp": before_timestamp,
                "limit": limit,
                "currency": args.currency,
                "token": args.token,
                "include_empty_intervals": str(args.include_empty_intervals).lower(),
            },
            timeout,
            retries,
            retry_delay_sec,
        )
        rows = _extract_rows(payload)
        if not rows:
            break

        all_rows.extend(rows)
        oldest_sec = min(int(r[0]) for r in rows)
        if oldest_sec <= start_sec:
            break
        if len(rows) < limit:
            break

        next_before_timestamp = oldest_sec - 1
        if next_before_timestamp >= before_timestamp:
            break
        before_timestamp = next_before_timestamp
        if page_delay_sec:
            time.sleep(page_delay_sec)

    filtered = [r for r in all_rows if start_sec <= int(r[0]) <= end_sec]
    normalized = _normalize_rows(filtered)

    asset = _safe_slug(args.asset or args.symbol or args.pool_address)
    asset_dir = os.path.join(args.output_dir, asset)
    filename = f"{_timeframe_label(args.timeframe, args.aggregate)}.csv"
    output_path = os.path.join(asset_dir, filename)
    _write_csv(output_path, normalized, args.append)
    if args.build_hourly and args.timeframe == "minute" and args.aggregate == 1:
        source_rows = _read_csv_rows(output_path)
        _build_hourly_files(asset_dir, source_rows, _parse_hourly_aggregates(args.hourly_aggregates))
    print(f"Wrote {len(normalized)} rows to {output_path}")
    return output_path


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl GeckoTerminal public DEX OHLCV data.")
    parser.add_argument("--network", default="solana", help="GeckoTerminal network id, e.g. solana, eth, bsc.")
    parser.add_argument("--pool-address", required=True, help="DEX pool address on the selected network.")
    parser.add_argument("--asset", default=None, help="Asset folder name under output-dir, e.g. btc, eth, sol.")
    parser.add_argument("--symbol", default=None, help="Optional symbol used for readable filenames.")
    parser.add_argument("--timeframe", default="minute", help="Candle timeframe: second, minute, hour, day.")
    parser.add_argument("--aggregate", type=int, default=1, help="Candle aggregation multiplier, e.g. 1, 5, 15.")
    parser.add_argument("--start-ts", default=None, help="Start timestamp (s, ms, or ISO8601).")
    parser.add_argument("--end-ts", default=None, help="End timestamp (s, ms, or ISO8601). Defaults to now.")
    parser.add_argument("--lookback-days", type=float, default=None, help="Alternative to --start-ts.")
    parser.add_argument("--limit", type=int, default=None, help=f"Rows per page (default {DEFAULT_LIMIT}).")
    parser.add_argument("--page-delay-sec", type=float, default=None, help=f"Seconds to wait between paginated requests (default {DEFAULT_PAGE_DELAY_SEC}).")
    parser.add_argument("--retries", type=int, default=None, help=f"Retries for HTTP 429 responses (default {DEFAULT_RETRIES}).")
    parser.add_argument("--retry-delay-sec", type=float, default=None, help=f"Base seconds to wait after HTTP 429 (default {DEFAULT_RETRY_DELAY_SEC}).")
    parser.add_argument("--max-pages", type=int, default=None, help="Safety cap on pagination pages.")
    parser.add_argument("--currency", default=DEFAULT_CURRENCY, help="Pricing currency: usd or token.")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="base, quote, or token address.")
    parser.add_argument("--include-empty-intervals", action="store_true", help="Ask API to include empty candle intervals.")
    parser.add_argument("--output-dir", default="nora/data", help="Directory to write CSV output.")
    parser.add_argument("--append", action="store_true", help="Merge/dedup with existing CSV instead of overwrite.")
    parser.add_argument("--build-hourly", action="store_true", default=True, help="Build 1h..24h CSV files from 1m data.")
    parser.add_argument("--no-build-hourly", action="store_false", dest="build_hourly", help="Skip hourly CSV generation.")
    parser.add_argument("--hourly-aggregates", default=DEFAULT_HOURLY_AGGREGATES, help="Hourly files to build, e.g. 1-24 or 1,4,12,24.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        crawl(args)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
