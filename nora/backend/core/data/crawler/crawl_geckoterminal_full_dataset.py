"""Build selected GeckoTerminal DEX OHLCV datasets as pickle files.

Phase 1 compliant: crawls raw 1m candles from GeckoTerminal (aggregate=1),
then delegates ALL resampling and manifest generation to core/resampler.py.
Single source of truth = 1m.pkl. All higher timeframes are derived.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests

# Phase 1: delegate resampling to core resampler
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    from backend.core.data.resampler import save_resampled_dataset
except ImportError:
    from nora.backend.core.data.resampler import save_resampled_dataset

DEFAULT_BASE_URL = "https://api.geckoterminal.com/api/v2"
# Dữ liệu DEX ghi vào data/dex/<SYM>; danh sách target ở data/_meta (xem backend/db/data_layout.py)
DEFAULT_OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data", "dex"))
DEFAULT_LIMIT = 500
MINUTE_MS = 60 * 1000
HOUR_MS = 60 * MINUTE_MS
DEFAULT_PAGE_DELAY_SEC = 2.8
DEFAULT_RETRIES = 5
DEFAULT_RETRY_DELAY_SEC = 30.0
DEFAULT_ASSET_DELAY_SEC = 3.0
DEFAULT_MAX_PAGES = 30
DEFAULT_MINUTE_MAX_PAGES = 400
DEFAULT_CHECKPOINT_EVERY_PAGES = 5
DEFAULT_MINUTE_AGGREGATES = "1,5,10,15"
DEFAULT_LOOKBACK_DAYS = 90.0  # Chuẩn 3 tháng gần nhất cho dữ liệu DEX
DEFAULT_CORE_ASSETS = "BTC,ETH,SOL"
DEFAULT_TRENDING_COUNT = 3
DEFAULT_NEW_COUNT = 2
DEFAULT_TRENDING_NETWORKS = "solana,eth"
DEFAULT_CURRENCY = "usd"
DEFAULT_TOKEN = "base"
DEFAULT_TARGETS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data", "_meta", "geckoterminal_targets.json"))

CORE_POOLS = {
    "BTC": {
        "network": "eth",
        "pool_address": "0x4585fe77225b41b697c938b018e2ac67ac5a20c0",
        "name": "WBTC / WETH 0.05%",
    },
    "ETH": {
        "network": "eth",
        "pool_address": "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640",
        "name": "WETH / USDC 0.05%",
    },
    "SOL": {
        "network": "solana",
        "pool_address": "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE",
        "name": "SOL / USDC",
    },
}

PKL_COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]

_SESSION = requests.Session()
_SESSION.headers.update({
    "accept": "application/json",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
})


class RateLimitError(RuntimeError):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


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


def _asset_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_]+", "", value).strip("_")
    return (slug or "POOL").upper()[:32]


def _clean_symbol(value: str) -> str:
    symbol = re.sub(r"[^A-Za-z0-9]+", "", value).upper()
    wrapped = {"WBTC": "BTC", "WETH": "ETH", "WSOL": "SOL", "WBNB": "BNB", "WMATIC": "MATIC"}
    return wrapped.get(symbol, symbol)[:16]


def _api_get(
    base_url: str,
    path: str,
    params: Dict[str, Any],
    timeout: int,
    retries: int,
    retry_delay_sec: float,
    context: str = "request",
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    clean_params = {k: v for k, v in params.items() if v is not None}
    for attempt in range(retries + 1):
        try:
            response = _SESSION.get(url, params=clean_params, timeout=timeout)
        except requests.RequestException as exc:
            if attempt >= retries:
                raise
            wait_sec = retry_delay_sec * (attempt + 1)
            warn(f"[warn] {context} request failed ({exc}); sleeping {wait_sec:.1f}s before retry {attempt + 1}/{retries}.")
            time.sleep(wait_sec)
            continue

        if response.status_code != 429:
            response.raise_for_status()
            return response.json()
        if attempt >= retries:
            raise RateLimitError(f"429 Too Many Requests for {context}")

        retry_after = response.headers.get("Retry-After")
        wait_sec = retry_delay_sec * (attempt + 1)
        if retry_after and retry_after.isdigit() and float(retry_after) > 0:
            wait_sec = max(wait_sec, float(retry_after))
        warn(f"[warn] {context} rate limited; sleeping {wait_sec:.1f}s before retry {attempt + 1}/{retries}.")
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
        timestamp_sec = int(row[0])
        if timestamp_sec < start_sec or timestamp_sec > end_sec:
            continue
        open_time = timestamp_sec * 1000
        if open_time in records:
            continue
        records[open_time] = {
            "open_time": open_time,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
    frame = pd.DataFrame(records.values(), columns=PKL_COLUMNS)
    if frame.empty:
        return frame
    frame = frame.sort_values("open_time").reset_index(drop=True)
    return frame


def _frame_to_raw_rows(frame: pd.DataFrame) -> List[List[Any]]:
    if frame.empty:
        return []
    raw_rows = []
    for open_time, open_, high, low, close, volume in frame.loc[:, PKL_COLUMNS].itertuples(index=False, name=None):
        raw_rows.append([int(open_time) // 1000, open_, high, low, close, volume])
    return raw_rows


def _crawl_ohlcv(
    base_url: str,
    network: str,
    pool_address: str,
    timeframe: str,
    aggregate: int,
    start_sec: int,
    end_sec: int,
    limit: int,
    page_delay_sec: float,
    retries: int,
    retry_delay_sec: float,
    timeout: int,
    max_pages: Optional[int],
    currency: str,
    token: str,
    context_label: str,
    existing_frame: Optional[pd.DataFrame] = None,
    checkpoint_path: Optional[str] = None,
    checkpoint_every_pages: int = DEFAULT_CHECKPOINT_EVERY_PAGES,
) -> Tuple[pd.DataFrame, int]:
    path = f"/networks/{network}/pools/{pool_address}/ohlcv/{timeframe}"
    before_timestamp = end_sec
    page = 0
    raw_rows = _frame_to_raw_rows(existing_frame) if existing_frame is not None else []

    oldest_existing_sec: Optional[int] = None
    newest_existing_sec: Optional[int] = None
    fetching_recent_gap = False
    if raw_rows:
        oldest_existing_sec = min(int(row[0]) for row in raw_rows)
        newest_existing_sec = max(int(row[0]) for row in raw_rows)
        log(
            f"[resume] {context_label} existing_rows={len(raw_rows)} "
            f"range={datetime.fromtimestamp(oldest_existing_sec, timezone.utc).isoformat()}.."
            f"{datetime.fromtimestamp(newest_existing_sec, timezone.utc).isoformat()}"
        )
        if oldest_existing_sec <= start_sec and (end_sec - newest_existing_sec) < 1800:
            log(f"[complete] {context_label} already covers lookback range ({datetime.fromtimestamp(oldest_existing_sec, timezone.utc).isoformat()} <= {datetime.fromtimestamp(start_sec, timezone.utc).isoformat()}); skipping API crawl.")
            return _normalize_rows(raw_rows, start_sec, end_sec), 0
        fetching_recent_gap = newest_existing_sec < (end_sec - 60)
        if not fetching_recent_gap:
            before_timestamp = min(before_timestamp, oldest_existing_sec - 1)

    while True:
        if max_pages and page >= max_pages:
            warn(f"[warn] {context_label} reached max_pages={max_pages}; stopping early.")
            break
        page += 1
        page_context = f"{context_label} page={page} before={before_timestamp}"

        payload = _api_get(
            base_url,
            path,
            {
                "aggregate": aggregate,
                "before_timestamp": before_timestamp,
                "limit": limit,
                "currency": currency,
                "token": token,
                "include_empty_intervals": "false",
            },
            timeout,
            retries,
            retry_delay_sec,
            page_context,
        )
        rows = _extract_rows(payload)
        if not rows:
            log(f"[page] {context_label} page={page} rows=0 done")
            break

        raw_rows.extend(rows)
        oldest_sec = min(int(row[0]) for row in rows)
        newest_sec = max(int(row[0]) for row in rows)
        log(
            f"[page] {context_label} page={page} rows={len(rows)} "
            f"oldest={datetime.fromtimestamp(oldest_sec, timezone.utc).isoformat()} "
            f"newest={datetime.fromtimestamp(newest_sec, timezone.utc).isoformat()} total_raw={len(raw_rows)}"
        )
        if checkpoint_path and checkpoint_every_pages > 0 and page % checkpoint_every_pages == 0:
            checkpoint_frame = _normalize_rows(raw_rows, start_sec, end_sec)
            _write_pickle(checkpoint_path, checkpoint_frame)
            log(f"[checkpoint] {context_label} rows={len(checkpoint_frame)} pages={page} path={checkpoint_path}")
        if fetching_recent_gap and newest_existing_sec is not None and oldest_sec <= newest_existing_sec:
            fetching_recent_gap = False
            if oldest_existing_sec is not None and oldest_existing_sec <= start_sec:
                break
            before_timestamp = oldest_existing_sec - 1 if oldest_existing_sec is not None else oldest_sec - 1
            if page_delay_sec:
                time.sleep(page_delay_sec)
            continue
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

    return _normalize_rows(raw_rows, start_sec, end_sec), page


def _included_symbol_map(payload: Dict[str, Any]) -> Dict[str, str]:
    symbols = {}
    for item in payload.get("included") or []:
        if item.get("type") != "token":
            continue
        attributes = item.get("attributes") or {}
        symbol = attributes.get("symbol")
        if symbol:
            symbols[str(item.get("id"))] = str(symbol)
    return symbols


def _pool_symbol(pool: Dict[str, Any], included_symbols: Dict[str, str]) -> str:
    relationships = pool.get("relationships") or {}
    base_token = relationships.get("base_token") or {}
    token_data = base_token.get("data") or {}
    token_id = str(token_data.get("id") or "")
    if token_id in included_symbols:
        return _clean_symbol(included_symbols[token_id])
    if "_" in token_id:
        return _clean_symbol(token_id.rsplit("_", 1)[-1])

    attributes = pool.get("attributes") or {}
    name = str(attributes.get("name") or attributes.get("pool_created_at") or "")
    first = re.split(r"/|\s", name.strip(), maxsplit=1)[0]
    return _clean_symbol(str(first or pool.get("id") or "POOL"))


def _pool_address(pool: Dict[str, Any]) -> str:
    pool_id = str(pool.get("id") or "")
    if "_" in pool_id:
        return pool_id.rsplit("_", 1)[-1]
    attributes = pool.get("attributes") or {}
    return str(attributes.get("address") or pool_id)


def _discover_pools(
    base_url: str,
    networks: List[str],
    path_name: str,
    count: int,
    timeout: int,
    retries: int,
    retry_delay_sec: float,
    existing_assets: set,
) -> List[Dict[str, str]]:
    if count <= 0:
        return []

    targets: List[Dict[str, str]] = []
    for network in networks:
        payload = _api_get(
            base_url,
            f"/networks/{network}/{path_name}",
            {"include": "base_token,quote_token,dex"},
            timeout,
            retries,
            retry_delay_sec,
        )
        included_symbols = _included_symbol_map(payload)
        for pool in payload.get("data") or []:
            asset = _pool_symbol(pool, included_symbols)
            if not asset or asset in existing_assets:
                continue
            pool_address = _pool_address(pool)
            attributes = pool.get("attributes") or {}
            if not pool_address:
                continue
            existing_assets.add(asset)
            targets.append(
                {
                    "asset": asset,
                    "network": network,
                    "pool_address": pool_address,
                    "name": str(attributes.get("name") or asset),
                }
            )
            if len(targets) >= count:
                return targets
    return targets


def _parse_list(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_aggregates(value: str, suffix: str, minimum: int, maximum: int, arg_name: str) -> List[int]:
    values = set()
    for part in value.split(","):
        part = part.strip().lower().removesuffix(suffix)
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            values.update(range(int(start), int(end) + 1))
        else:
            values.add(int(part))
    invalid = [item for item in values if item < minimum or item > maximum]
    if invalid:
        raise ValueError(f"--{arg_name} values must be between {minimum} and {maximum}")
    if not values:
        raise ValueError(f"--{arg_name} must not be empty")
    return sorted(values)


def _parse_hours(value: str) -> List[int]:
    return _parse_aggregates(value, "h", 1, 24, "hours")


def _parse_minutes(value: str) -> List[int]:
    return _parse_aggregates(value, "m", 1, 30, "minutes")


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


def _read_pickle_if_usable(path: str) -> pd.DataFrame:
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        return pd.DataFrame(columns=PKL_COLUMNS)
    try:
        frame = pd.read_pickle(path)
    except Exception as exc:
        warn(f"[warn] Cannot resume from {path}: {exc}")
        return pd.DataFrame(columns=PKL_COLUMNS)
    missing = [column for column in PKL_COLUMNS if column not in frame.columns]
    if missing:
        warn(f"[warn] Cannot resume from {path}: missing columns {','.join(missing)}")
        return pd.DataFrame(columns=PKL_COLUMNS)
    # Bỏ nến điền (is_filled==1) TRƯỚC khi cắt về PKL_COLUMNS: nếu cắt cột trước thì
    # mất cờ is_filled và nến điền bị coi là phút có giao dịch thật khi resume.
    if "is_filled" in frame.columns:
        frame = frame[frame["is_filled"].fillna(0).astype(int) != 1]
    frame = frame.loc[:, PKL_COLUMNS].copy()
    frame["open_time"] = frame["open_time"].astype("int64")
    return frame.sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)


def _format_frame_list(values: List[int], suffix: str) -> str:
    return ",".join(f"{value}{suffix}" for value in values) if values else "none"


def _clear_asset_dirs(output_dir: str, assets: Iterable[str]) -> None:
    for asset in assets:
        path = os.path.join(output_dir, _asset_slug(asset))
        if os.path.isdir(path):
            shutil.rmtree(path)
            log(f"[clear] Removed old {path}")


def _load_targets_file(path: str) -> List[Dict[str, str]]:
    if not path or not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        raw_targets = json.load(handle)
    targets = []
    for item in raw_targets:
        asset = _asset_slug(str(item.get("asset", "")))
        network = str(item.get("network", "")).strip()
        pool_address = str(item.get("pool_address", "")).strip()
        if not asset or not network or not pool_address:
            continue
        targets.append(
            {
                "asset": asset,
                "network": network,
                "pool_address": pool_address,
                "name": str(item.get("name") or asset),
            }
        )
    return targets


def _target_set(args: argparse.Namespace, base_url: str, timeout: int, retries: int, retry_delay_sec: float) -> List[Dict[str, str]]:
    targets_file = args.targets_file or os.environ.get("GECKOTERMINAL_FULL_TARGETS_FILE", DEFAULT_TARGETS_FILE)
    targets = _load_targets_file(targets_file)
    if targets:
        return targets

    assets = [_asset_slug(asset) for asset in _parse_list(args.core_assets)]
    targets = []
    seen_assets = set()
    for asset in assets:
        pool = CORE_POOLS.get(asset)
        if not pool:
            warn(f"[warn] No built-in core pool for {asset}; skipping.")
            continue
        seen_assets.add(asset)
        targets.append({"asset": asset, **pool})

    networks = _parse_list(args.trending_networks)
    trending = _discover_pools(
        base_url,
        networks,
        "trending_pools",
        args.trending_count,
        timeout,
        retries,
        retry_delay_sec,
        seen_assets,
    )
    new = _discover_pools(
        base_url,
        networks,
        "new_pools",
        args.new_count,
        timeout,
        retries,
        retry_delay_sec,
        seen_assets,
    )
    return targets + trending + new


def run(args: argparse.Namespace) -> List[Dict[str, Any]]:
    base_url = os.environ.get("GECKOTERMINAL_BASE_URL", DEFAULT_BASE_URL)
    output_dir = os.path.abspath(os.environ.get("GECKOTERMINAL_FULL_OUTPUT_DIR", args.output_dir))
    timeout = int(os.environ.get("GECKOTERMINAL_TIMEOUT", "30"))
    limit = args.limit or int(os.environ.get("GECKOTERMINAL_FULL_LIMIT", str(DEFAULT_LIMIT)))
    page_delay_sec = args.page_delay_sec
    if page_delay_sec is None:
        page_delay_sec = float(os.environ.get("GECKOTERMINAL_FULL_PAGE_DELAY_SEC", str(DEFAULT_PAGE_DELAY_SEC)))
    retries = args.retries if args.retries is not None else int(os.environ.get("GECKOTERMINAL_RETRIES", str(DEFAULT_RETRIES)))
    retry_delay_sec = args.retry_delay_sec
    if retry_delay_sec is None:
        retry_delay_sec = float(os.environ.get("GECKOTERMINAL_RETRY_DELAY_SEC", str(DEFAULT_RETRY_DELAY_SEC)))
    asset_delay_sec = args.asset_delay_sec
    if asset_delay_sec is None:
        asset_delay_sec = float(os.environ.get("GECKOTERMINAL_FULL_ASSET_DELAY_SEC", str(DEFAULT_ASSET_DELAY_SEC)))
    max_pages = args.max_pages
    if max_pages is None:
        max_pages_env = os.environ.get("GECKOTERMINAL_FULL_MAX_PAGES")
        max_pages = int(max_pages_env) if max_pages_env else DEFAULT_MAX_PAGES

    if limit < 1 or limit > 1000:
        raise ValueError("--limit must be between 1 and 1000")
    if page_delay_sec < 0:
        raise ValueError("--page-delay-sec must be non-negative")
    if retries < 0:
        raise ValueError("--retries must be non-negative")
    if retry_delay_sec < 0:
        raise ValueError("--retry-delay-sec must be non-negative")
    if asset_delay_sec < 0:
        raise ValueError("--asset-delay-sec must be non-negative")
    if args.currency not in {"usd", "token"}:
        raise ValueError("--currency must be usd or token")
    if args.token not in {"base", "quote"} and not re.fullmatch(r"[A-Za-z0-9:_\-]+", args.token):
        raise ValueError("--token must be base, quote, or a token address")

    if args.end_ts:
        end_sec = _to_seconds(args.end_ts)
    else:
        end_sec = int(time.time())
    if args.start_ts:
        start_sec = _to_seconds(args.start_ts)
    else:
        start_sec = end_sec - int(args.lookback_days * 86400)
    if start_sec >= end_sec:
        raise ValueError("start timestamp must be smaller than end timestamp")

    if args.skip_hours:
        hours = []
    else:
        hours = _parse_hours(args.hours)
        if 1 not in hours:
            hours = [1] + hours
    minute_aggregates = args.minutes or os.environ.get("GECKOTERMINAL_FULL_MINUTE_AGGREGATES", DEFAULT_MINUTE_AGGREGATES)
    minutes = _parse_minutes(minute_aggregates)
    if 1 not in minutes:
        minutes = [1] + minutes
    minute_max_pages = args.minute_max_pages
    if minute_max_pages is None:
        minute_max_pages_env = os.environ.get("GECKOTERMINAL_FULL_MINUTE_MAX_PAGES")
        minute_max_pages = int(minute_max_pages_env) if minute_max_pages_env else DEFAULT_MINUTE_MAX_PAGES
    if minute_max_pages is not None and minute_max_pages < 1:
        raise ValueError("--minute-max-pages must be positive")
    checkpoint_every_pages = args.checkpoint_every_pages
    if checkpoint_every_pages is None:
        checkpoint_env = os.environ.get("GECKOTERMINAL_FULL_CHECKPOINT_EVERY_PAGES")
        checkpoint_every_pages = int(checkpoint_env) if checkpoint_env else DEFAULT_CHECKPOINT_EVERY_PAGES
    if checkpoint_every_pages < 0:
        raise ValueError("--checkpoint-every-pages must be non-negative")
    targets = _target_set(args, base_url, timeout, retries, retry_delay_sec)
    if args.clear:
        _clear_asset_dirs(output_dir, [target["asset"] for target in targets])

    # --minutes/--hours không còn tác dụng: chỉ crawl 1m, các khung khác do core/resampler.py sinh ra
    log(
        f"[start] {len(targets)} assets, source=1m, derived=5m,15m,1h,4h,24h (core/resampler.py), "
        f"output={output_dir}"
    )
    log(f"[range] {datetime.fromtimestamp(start_sec, timezone.utc).isoformat()} -> {datetime.fromtimestamp(end_sec, timezone.utc).isoformat()}")

    return run_pipeline(
        args=args,
        targets=targets,
        output_dir=output_dir,
        base_url=base_url,
        start_sec=start_sec,
        end_sec=end_sec,
        limit=limit,
        page_delay_sec=page_delay_sec,
        asset_delay_sec=asset_delay_sec,
        retries=retries,
        retry_delay_sec=retry_delay_sec,
        timeout=timeout,
        minute_max_pages=minute_max_pages,
        checkpoint_every_pages=checkpoint_every_pages,
    )

def _process_asset(
    target: Dict[str, Any],
    args: Any,
    output_dir: str,
    base_url: str = "https://api.geckoterminal.com/api/v2",
    start_sec: Optional[int] = None,
    end_sec: Optional[int] = None,
    limit: int = 100,
    page_delay_sec: float = 0.0,
    retries: int = 3,
    retry_delay_sec: float = 1.0,
    timeout: int = 15,
    minute_max_pages: int = 150,
    checkpoint_every_pages: int = 5,
) -> Optional[Dict[str, Any]]:
    """Xử lý crawl và resample cho một pool tài sản duy nhất."""
    asset = _asset_slug(target["asset"])
    network = target["network"]
    pool_address = target["pool_address"]

    one_minute_path = os.path.join(output_dir, asset, "1m.pkl")
    checkpoint_path = os.path.join(output_dir, asset, "1m_raw.partial.pkl")
    existing_1m = _read_pickle_if_usable(one_minute_path)
    if not existing_1m.empty and "is_filled" in existing_1m.columns:
        existing_1m = existing_1m[existing_1m["is_filled"] != 1].reset_index(drop=True)

    log(f"[crawl] {asset} 1m source (aggregate=1)")

    minute_pages = 0
    crawl_ok = True
    frame_1m = pd.DataFrame()

    try:
        frame_1m, minute_pages = _crawl_ohlcv(
            base_url,
            network,
            pool_address,
            "minute",
            1,
            start_sec,
            end_sec,
            limit,
            page_delay_sec,
            retries,
            retry_delay_sec,
            timeout,
            minute_max_pages,
            getattr(args, "currency", "usd"),
            getattr(args, "token", "base"),
            f"{asset} 1m",
            existing_1m,
            checkpoint_path,
            checkpoint_every_pages,
        )
    except Exception as exc:
        warn(f"[error] {asset} 1m crawl failed: {exc}")
        crawl_ok = False
        # Try to use checkpointed data
        frame_1m = _read_pickle_if_usable(checkpoint_path)
        if frame_1m.empty:
            frame_1m = _read_pickle_if_usable(one_minute_path)
        if frame_1m.empty:
            warn(f"[skip] {asset}: no 1m data available, skipping.")
            return None
        warn(f"[partial] {asset} using checkpointed 1m rows={len(frame_1m)}")

    if frame_1m.empty:
        warn(f"[skip] {asset}: 1m crawl returned 0 rows, skipping.")
        return None

    log(f"[write] {asset} 1m rows={len(frame_1m)} pages={minute_pages}")

    try:
        manifest = save_resampled_dataset(
            symbol=asset,
            output_dir=output_dir,
            df_1m_raw=frame_1m,
            pool_address=pool_address,
            timeframes=("5m", "15m", "1h", "4h", "24h"),
            source="geckoterminal",
            synthetic=False,
            crawl_ok=crawl_ok,
            requested_start_ts=start_sec * 1000 if start_sec else None,
            requested_end_ts=end_sec * 1000 if end_sec else None,
            extra_meta={
                "venue": "dex",
                "exchange": "geckoterminal",
                "network": network,
                "volume_unit": "usd",
                "pool_name": target.get("name", ""),
            },
        )
        log(
            f"[manifest] {asset} rows={manifest['rows']} "
            f"filled_ratio={manifest['filled_ratio_1m']:.3f} "
            f"crawl_ok={manifest['crawl_ok']} "
            f"start={datetime.fromtimestamp(manifest['start_ts']/1000, timezone.utc).date()} "
            f"end={datetime.fromtimestamp(manifest['end_ts']/1000, timezone.utc).date()}"
        )
        # Crawl + resample thành công: xoá checkpoint thô để lần sau không đọc nhầm dữ liệu dở dang
        if crawl_ok and os.path.isfile(checkpoint_path):
            os.remove(checkpoint_path)
        return manifest
    except Exception as exc:
        warn(f"[error] {asset} resampling failed: {exc}")
        import traceback
        traceback.print_exc()
        return None


def run_pipeline(
    args: argparse.Namespace,
    targets: List[Dict[str, Any]],
    output_dir: str,
    base_url: str,
    start_sec: int,
    end_sec: int,
    limit: int,
    page_delay_sec: float,
    asset_delay_sec: float,
    retries: int,
    retry_delay_sec: float,
    timeout: int,
    minute_max_pages: int,
    checkpoint_every_pages: int,
) -> List[Dict[str, Any]]:
    summaries = []
    total_steps = len(targets)
    for target_index, target in enumerate(targets):
        if target_index > 0 and asset_delay_sec:
            log(f"[wait] Sleeping {asset_delay_sec:.1f}s before next asset")
            time.sleep(asset_delay_sec)

        asset = _asset_slug(target["asset"])
        network = target["network"]
        pool_address = target["pool_address"]
        log(f"[asset] ({target_index+1}/{total_steps}) {asset} | {network} | {target.get('name', '')} | pool={pool_address}")

        manifest = _process_asset(
            target=target,
            args=args,
            output_dir=output_dir,
            base_url=base_url,
            start_sec=start_sec,
            end_sec=end_sec,
            limit=limit,
            page_delay_sec=page_delay_sec,
            retries=retries,
            retry_delay_sec=retry_delay_sec,
            timeout=timeout,
            minute_max_pages=minute_max_pages,
            checkpoint_every_pages=checkpoint_every_pages,
        )
        if manifest:
            summaries.append(
                {
                    "asset": asset,
                    "network": network,
                    "pool_address": pool_address,
                    "name": target.get("name", ""),
                    "rows_1m": manifest["rows"].get("1m", 0),
                    "rows_1h": manifest["rows"].get("1h", 0),
                    "rows_4h": manifest["rows"].get("4h", 0),
                    "filled_ratio_1m": manifest["filled_ratio_1m"],
                    "crawl_ok": manifest.get("crawl_ok", True),
                }
            )

    log("[summary]")
    for item in summaries:
        log(
            f"[summary] {item['asset']:12s} 1m={item['rows_1m']:6d} "
            f"1h={item['rows_1h']:4d} 4h={item['rows_4h']:4d} "
            f"filled={item['filled_ratio_1m']:.3f} pool={item['pool_address']}"
        )
    log("[done] Full GeckoTerminal PKL dataset build finished (Phase 1 compliant).")
    return summaries



def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl selected GeckoTerminal DEX OHLCV assets to PKL files.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output root, default data.")
    parser.add_argument("--core-assets", default=DEFAULT_CORE_ASSETS, help="Comma-separated core assets to crawl: BTC,ETH,SOL.")
    parser.add_argument("--trending-networks", default=DEFAULT_TRENDING_NETWORKS, help="Comma-separated networks for trending/new pools.")
    parser.add_argument("--trending-count", type=int, default=DEFAULT_TRENDING_COUNT, help="How many trending pools to add.")
    parser.add_argument("--new-count", type=int, default=DEFAULT_NEW_COUNT, help="How many new pools to add.")
    parser.add_argument("--targets-file", default=None, help="JSON file with asset/network/pool_address targets.")
    parser.add_argument("--hours", default="1-24", help="Hourly pickle files to build, e.g. 1-24 or 1,4,12,24.")
    parser.add_argument("--skip-hours", action="store_true", help="Only build minute pickle files; leave existing hourly files untouched.")
    parser.add_argument("--minutes", default=None, help="Minute pickle files to build, e.g. 1-30 or 1,5,15,30.")
    parser.add_argument("--start-ts", default=None, help="Start timestamp (s, ms, or ISO8601).")
    parser.add_argument("--end-ts", default=None, help="End timestamp (s, ms, or ISO8601). Defaults to now.")
    parser.add_argument("--lookback-days", type=float, default=DEFAULT_LOOKBACK_DAYS, help="Alternative to --start-ts.")
    parser.add_argument("--limit", type=int, default=None, help=f"Rows per page, default {DEFAULT_LIMIT}.")
    parser.add_argument("--page-delay-sec", type=float, default=None, help=f"Seconds between requests, default {DEFAULT_PAGE_DELAY_SEC}.")
    parser.add_argument("--retries", type=int, default=None, help=f"Retries for rate limits, default {DEFAULT_RETRIES}.")
    parser.add_argument("--retry-delay-sec", type=float, default=None, help=f"Base retry delay, default {DEFAULT_RETRY_DELAY_SEC}.")
    parser.add_argument("--asset-delay-sec", type=float, default=None, help=f"Seconds between assets, default {DEFAULT_ASSET_DELAY_SEC}.")
    parser.add_argument("--max-pages", type=int, default=None, help=f"Safety cap per hourly source, default {DEFAULT_MAX_PAGES}.")
    parser.add_argument("--minute-max-pages", type=int, default=None, help=f"Safety cap for 1m source, default {DEFAULT_MINUTE_MAX_PAGES}.")
    parser.add_argument("--checkpoint-every-pages", type=int, default=None, help=f"Write partial 1m PKL every N pages, default {DEFAULT_CHECKPOINT_EVERY_PAGES}; 0 disables.")
    parser.add_argument("--currency", default=DEFAULT_CURRENCY, help="Pricing currency: usd or token.")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="base, quote, or token address.")
    parser.add_argument("--clear", action="store_true", help="Remove old selected asset directories before writing.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    try:
        run(parse_args(argv))
    except Exception as exc:
        warn(f"[fatal] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
