"""Crawler cho OKX DEX (on-chain) candle data.

Gọi API on-chain của OKX (web3.okx.com) theo địa chỉ contract token
(chainIndex + tokenContractAddress), KHÔNG phải API CEX theo instId.
Kết quả được ghi ra file CSV phẳng trong nora/data.

Yêu cầu biến môi trường: OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRASE.
Xem nora/.env.example.
"""
import argparse
import base64
import csv
import hashlib
import hmac
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

DEFAULT_BASE_URL = "https://web3.okx.com"
DEFAULT_LIMIT = 50
DEFAULT_PAGE_DELAY_SEC = 1.0
CANDLES_PATH = "/api/v6/dex/market/candles"
HISTORICAL_CANDLES_PATH = "/api/v6/dex/market/historical-candles"

CSV_FIELDS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "volume_usd",
    "confirm",
]


def _to_ms(value: Any) -> int:
    """Chuyển timestamp linh hoạt (giây / mili giây / ISO8601) về mili giây."""
    if value is None:
        raise ValueError("timestamp is required")
    if isinstance(value, (int, float)):
        num = int(value)
        # Heuristic: giá trị giây thường < 10^12, mili giây >= 10^12
        if num < 10**12:
            return num * 1000
        return num
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return _to_ms(int(s))
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    raise TypeError(f"Unsupported timestamp type: {type(value)!r}")


def _iso_timestamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _build_query(params: Dict[str, Any]) -> str:
    items = [(k, v) for k, v in params.items() if v is not None]
    items.sort(key=lambda kv: kv[0])
    return "&".join(f"{k}={v}" for k, v in items)


def _sign_request(secret: str, timestamp: str, method: str, request_path: str, query_string: str) -> str:
    prehash = f"{timestamp}{method.upper()}{request_path}"
    if query_string:
        prehash += f"?{query_string}"
    mac = hmac.new(secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")


def _auth_headers(method: str, request_path: str, query_string: str) -> Dict[str, str]:
    api_key = os.environ.get("OKX_API_KEY")
    api_secret = os.environ.get("OKX_API_SECRET")
    api_passphrase = os.environ.get("OKX_API_PASSPHRASE")
    if not api_key or not api_secret or not api_passphrase:
        raise RuntimeError(
            "Missing OKX credentials. Set OKX_API_KEY, OKX_API_SECRET, "
            "OKX_API_PASSPHRASE as environment variables (see nora/.env.example)."
        )
    timestamp = _iso_timestamp_now()
    signature = _sign_request(api_secret, timestamp, method, request_path, query_string)
    return {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": signature,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": api_passphrase,
        "Content-Type": "application/json",
    }


def _extract_rows(payload: Dict[str, Any]) -> List[List[Any]]:
    if str(payload.get("code")) not in ("0", "None"):
        raise RuntimeError(f"OKX API error: code={payload.get('code')} msg={payload.get('msg')}")
    data = payload.get("data") or []
    rows = []
    for row in data:
        if not isinstance(row, (list, tuple)) or len(row) < 8:
            continue
        rows.append(list(row))
    return rows


def _api_get(base_url: str, path: str, params: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    query_string = _build_query(params)
    headers = _auth_headers("GET", path, query_string)
    url = f"{base_url}{path}"
    if query_string:
        url += f"?{query_string}"
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _normalize_rows(raw_rows: List[List[Any]]) -> List[Dict[str, Any]]:
    normalized = []
    for row in raw_rows:
        normalized.append(
            {
                "open_time": int(row[0]),
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
                "volume_usd": row[6],
                "confirm": row[7],
            }
        )
    normalized.sort(key=lambda r: r["open_time"])
    return normalized


def _safe_contract_slug(symbol: Optional[str], contract_address: str) -> str:
    base = symbol or contract_address
    slug = re.sub(r"[^A-Za-z0-9]+", "", base)
    if not slug:
        slug = "token"
    return slug[:24]


def _merge_with_existing_rows(path: str, new_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    existing: Dict[int, Dict[str, Any]] = {}
    if os.path.exists(path):
        with open(path, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ot = int(row["open_time"])
                except (KeyError, ValueError):
                    continue
                existing[ot] = row
    for row in new_rows:
        existing[row["open_time"]] = row
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
    base_url = os.environ.get("OKX_DEX_BASE_URL", DEFAULT_BASE_URL)
    timeout = int(os.environ.get("OKX_DEX_TIMEOUT", "30"))
    limit = args.limit or int(os.environ.get("OKX_DEX_LIMIT", str(DEFAULT_LIMIT)))
    page_delay_sec = args.page_delay_sec
    if page_delay_sec is None:
        page_delay_sec = float(os.environ.get("OKX_DEX_PAGE_DELAY_SEC", str(DEFAULT_PAGE_DELAY_SEC)))
    if limit < 1:
        raise ValueError("--limit must be at least 1")
    if page_delay_sec < 0:
        raise ValueError("--page-delay-sec must be non-negative")

    if args.end_ts is not None:
        end_ts = _to_ms(args.end_ts)
    else:
        end_ts = int(time.time() * 1000)

    if args.start_ts is not None:
        start_ts = _to_ms(args.start_ts)
    elif args.lookback_days is not None:
        start_ts = end_ts - int(args.lookback_days * 86400 * 1000)
    else:
        raise ValueError("Must provide either --start-ts or --lookback-days")

    path = HISTORICAL_CANDLES_PATH if args.use_historical else CANDLES_PATH

    all_rows: List[List[Any]] = []
    before = None
    after = str(end_ts)
    page = 0

    while True:
        page += 1
        if args.max_pages and page > args.max_pages:
            print(f"[warn] Reached --max-pages={args.max_pages}, stopping pagination early.", file=sys.stderr)
            break

        params = {
            "chainIndex": args.chain_index,
            "tokenContractAddress": args.token_contract_address,
            "bar": args.interval,
            "limit": limit,
            "after": after,
            "before": before,
        }
        payload = _api_get(base_url, path, params, timeout)
        rows = _extract_rows(payload)
        if not rows:
            break

        all_rows.extend(rows)

        oldest_ts = min(int(r[0]) for r in rows)
        if oldest_ts <= start_ts:
            break
        if len(rows) < limit:
            break

        before = str(oldest_ts)
        after = None
        if page_delay_sec:
            time.sleep(page_delay_sec)

    filtered = [r for r in all_rows if start_ts <= int(r[0]) <= end_ts]
    normalized = _normalize_rows(filtered)

    slug = _safe_contract_slug(args.token_symbol, args.token_contract_address)
    filename = f"okx_dex_chain{args.chain_index}_{slug}_{args.interval}_{start_ts}_{end_ts}.csv"
    output_path = os.path.join(args.output_dir, filename)

    _write_csv(output_path, normalized, args.append)
    print(f"Wrote {len(normalized)} rows to {output_path}")
    return output_path


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl OKX DEX (on-chain) candle data.")
    parser.add_argument("--chain-index", required=True, help="Numeric chain identifier, e.g. 501 for Solana.")
    parser.add_argument("--token-contract-address", required=True, help="On-chain token contract address.")
    parser.add_argument("--token-symbol", default=None, help="Optional symbol used for readable filenames.")
    parser.add_argument("--interval", default="1m", help="Candle interval, e.g. 1m, 5m, 1H, 4H, 1D.")
    parser.add_argument("--start-ts", default=None, help="Start timestamp (s, ms, or ISO8601).")
    parser.add_argument("--end-ts", default=None, help="End timestamp (s, ms, or ISO8601). Defaults to now.")
    parser.add_argument("--lookback-days", type=float, default=None, help="Alternative to --start-ts.")
    parser.add_argument("--limit", type=int, default=None, help=f"Rows per page (default {DEFAULT_LIMIT}).")
    parser.add_argument("--page-delay-sec", type=float, default=None, help=f"Seconds to wait between paginated requests (default {DEFAULT_PAGE_DELAY_SEC}).")
    parser.add_argument("--max-pages", type=int, default=None, help="Safety cap on pagination pages.")
    parser.add_argument("--output-dir", default="nora/data", help="Directory to write CSV output.")
    parser.add_argument("--append", action="store_true", help="Merge/dedup with existing CSV instead of overwrite.")
    parser.add_argument("--use-historical", action="store_true", help="Use historical-candles endpoint instead of candles.")
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
