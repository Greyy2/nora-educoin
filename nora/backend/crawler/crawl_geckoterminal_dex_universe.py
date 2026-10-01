"""Crawl a DEX-only GeckoTerminal universe into Nora's local research format.

Phase 1 compliant: crawls raw 1m candles (aggregate=1) and delegates ALL
resampling to core/resampler.py. Generates manifest.json per asset.
No synthetic ticks are generated.
- data/{ASSET}/1m.pkl   (source of truth)
- data/{ASSET}/5m.pkl, 15m.pkl, 1h.pkl, 4h.pkl, 24h.pkl (resampled)
- data/{ASSET}/manifest.json
- data/{ASSET}/dex_pool.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    from backend.db.tick_storage import TICK_COLUMNS, default_data_root
    from backend.core.resampler import save_resampled_dataset
except ImportError:
    from nora.backend.db.tick_storage import TICK_COLUMNS, default_data_root
    from nora.backend.core.resampler import save_resampled_dataset


BASE_URL = "https://api.geckoterminal.com/api/v2"
PKL_COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]
EXCLUDED_SYMBOLS = {
    "BTC", "BTCB", "WBTC", "CBBTC", "TBTC",
    "ETH", "WETH", "WSTETH", "STETH", "RETH", "CBETH",
    "SOL", "WSOL", "MSOL", "JITOSOL", "JUPSOL",
    "USDC", "USDT", "DAI", "USDE", "USDS", "USD1", "PYUSD", "FRAX", "EURC", "EURS",
    "BNB", "WBNB", "MATIC", "WMATIC", "AVAX", "WAVAX",
    "LINK",
}
EXCLUDED_NAME_PARTS = {
    "WBTC", "BTCB", "CBBTC", "CBETH", "WSTETH", "STETH", "RETH",
}


def log(message: str) -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(n):
        return default
    return n


def _slug(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]+", "", str(value or "")).upper()
    return clean[:24] or "DEXTOKEN"


def _parse_iso(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _token_symbol_from_pool(pool: Dict[str, Any], included: Dict[str, str]) -> str:
    relationships = pool.get("relationships") or {}
    token = ((relationships.get("base_token") or {}).get("data") or {}).get("id")
    if token and token in included:
        return _slug(included[token])
    attributes = pool.get("attributes") or {}
    name = str(attributes.get("name") or "")
    return _slug(re.split(r"/|\s", name.strip(), maxsplit=1)[0])


def _included_symbols(payload: Dict[str, Any]) -> Dict[str, str]:
    symbols = {}
    for item in payload.get("included") or []:
        if item.get("type") != "token":
            continue
        symbol = (item.get("attributes") or {}).get("symbol")
        if symbol:
            symbols[str(item.get("id"))] = str(symbol)
    return symbols


def _base_token_id(pool: Dict[str, Any]) -> Optional[str]:
    relationships = pool.get("relationships") or {}
    return ((relationships.get("base_token") or {}).get("data") or {}).get("id")


def _pool_address(pool: Dict[str, Any]) -> str:
    attributes = pool.get("attributes") or {}
    if attributes.get("address"):
        return str(attributes["address"])
    pool_id = str(pool.get("id") or "")
    return pool_id.rsplit("_", 1)[-1]


def _load_targets(path: Optional[str], args: Optional[argparse.Namespace] = None) -> List[Dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    targets = []
    for item in raw if isinstance(raw, list) else []:
        asset = _slug(item.get("asset", ""))
        network = str(item.get("network") or "").strip()
        pool_address = str(item.get("pool_address") or "").strip()
        if not asset or not network or not pool_address or asset in EXCLUDED_SYMBOLS:
            continue
        if args is not None:
            age_days = _safe_float(item.get("pool_age_days"))
            ok, flags, score = _pool_quality(item, asset, asset, age_days, args)
            if not ok:
                warn(f"[quality-skip] {asset}: {','.join(flags)}")
                continue
            item["quality_score"] = score
            item["quality_flags"] = flags
        clean = dict(item)
        clean["asset"] = asset
        clean["network"] = network
        clean["pool_address"] = pool_address
        targets.append(clean)
    return targets


def _pool_age_days(created_at: Optional[str], end_sec: int) -> Optional[float]:
    created_sec = _parse_iso(created_at)
    if created_sec is None:
        return None
    return max(0.0, (end_sec - created_sec) / 86400.0)


def _h24_transactions(attributes: Dict[str, Any]) -> Tuple[int, int, int]:
    tx_24h = (attributes.get("transactions") or {}).get("h24") or {}
    buys = int(tx_24h.get("buys") or 0)
    sells = int(tx_24h.get("sells") or 0)
    buyers = int(tx_24h.get("buyers") or 0)
    sellers = int(tx_24h.get("sellers") or 0)
    return buys + sells, buyers + sellers, buyers


def _pool_quality(
    attributes: Dict[str, Any],
    symbol: str,
    base_symbol: str,
    age_days: Optional[float],
    args: argparse.Namespace,
) -> Tuple[bool, List[str], float]:
    liquidity = _safe_float(attributes.get("reserve_in_usd"), 0.0) or 0.0
    volume_24h = _safe_float((attributes.get("volume_usd") or {}).get("h24"), 0.0) or 0.0
    market_cap = _safe_float(attributes.get("market_cap_usd"), 0.0) or 0.0
    fdv = _safe_float(attributes.get("fdv_usd"), 0.0) or 0.0
    trades_24h, traders_24h, buyers_24h = _h24_transactions(attributes)
    turnover = volume_24h / liquidity if liquidity > 0 else 0.0
    base = _slug(base_symbol or symbol)

    flags: List[str] = []
    if symbol == "DEXTOKEN" or base == "DEXTOKEN":
        flags.append("unknown_symbol")
    if base in EXCLUDED_SYMBOLS or symbol in EXCLUDED_SYMBOLS:
        flags.append("excluded_symbol")
    if any(part in str(base_symbol or symbol).upper() for part in EXCLUDED_NAME_PARTS):
        flags.append("wrapped_or_lst")
    if age_days is not None and age_days < args.min_age_days:
        flags.append("too_young")
    if liquidity < args.min_liquidity_usd:
        flags.append("low_liquidity")
    if volume_24h < args.min_volume_24h_usd:
        flags.append("low_volume")
    if trades_24h < args.min_trades_24h:
        flags.append("low_trades")
    if traders_24h < args.min_traders_24h:
        flags.append("low_independent_traders")
    if buyers_24h < args.min_buyers_24h:
        flags.append("low_buyers")
    if args.min_market_cap_usd > 0 and market_cap < args.min_market_cap_usd and fdv < args.min_market_cap_usd:
        flags.append("low_market_cap")
    if args.max_turnover_24h > 0 and turnover > args.max_turnover_24h and traders_24h < args.high_turnover_min_traders:
        flags.append("suspicious_turnover")

    quality_score = 0.0
    quality_score += min(25.0, liquidity / max(1.0, args.min_liquidity_usd) * 8.0)
    quality_score += min(25.0, volume_24h / max(1.0, args.min_volume_24h_usd) * 8.0)
    quality_score += min(20.0, trades_24h / max(1.0, args.min_trades_24h) * 8.0)
    quality_score += min(20.0, traders_24h / max(1.0, args.min_traders_24h) * 8.0)
    quality_score += min(10.0, (age_days or 0.0) / max(1.0, args.min_age_days) * 5.0)
    if turnover > args.max_turnover_24h > 0:
        quality_score -= min(15.0, turnover - args.max_turnover_24h)

    return not flags, flags, round(max(0.0, min(100.0, quality_score)), 2)


def _api_get(session: requests.Session, path: str, params: Dict[str, Any], retries: int, delay_sec: float) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    clean = {k: v for k, v in params.items() if v is not None}
    for attempt in range(retries + 1):
        response = session.get(url, params=clean, timeout=30)
        if response.status_code == 429 and attempt < retries:
            wait = max(delay_sec, 20.0) * (attempt + 1)
            warn(f"[rate-limit] {path} sleeping {wait:.1f}s")
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f"failed request after retries: {path}")


def discover_targets(args: argparse.Namespace, session: requests.Session, start_sec: int) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen = set()
    networks = [item.strip() for item in args.networks.split(",") if item.strip()]
    source_paths = ["trending_pools", "new_pools"]

    for network in networks:
        for path_name in source_paths:
            payload = _api_get(
                session,
                f"/networks/{network}/{path_name}",
                {"page": 1, "include": "base_token,quote_token,dex"},
                args.retries,
                args.request_delay_sec,
            )
            included = _included_symbols(payload)
            for pool in payload.get("data") or []:
                attributes = pool.get("attributes") or {}
                symbol = _token_symbol_from_pool(pool, included)
                name = str(attributes.get("name") or symbol)
                created_at = attributes.get("pool_created_at")
                age_days = _pool_age_days(created_at, int(time.time()))
                base_symbol = included.get(_base_token_id(pool) or "", symbol)
                if not symbol or symbol in seen:
                    continue

                liquidity = _safe_float(attributes.get("reserve_in_usd"), 0.0) or 0.0
                volume_24h = _safe_float((attributes.get("volume_usd") or {}).get("h24"), 0.0) or 0.0
                market_cap = _safe_float(attributes.get("market_cap_usd"))
                is_good, quality_flags, quality_score = _pool_quality(attributes, symbol, base_symbol, age_days, args)
                if not is_good:
                    continue

                seen.add(symbol)
                candidates.append(
                    {
                        "asset": symbol,
                        "network": network,
                        "pool_address": _pool_address(pool),
                        "name": name,
                        "pool_created_at": created_at,
                        "pool_age_days": round(age_days, 2) if age_days is not None else None,
                        "market_cap_usd": market_cap,
                        "fdv_usd": _safe_float(attributes.get("fdv_usd")),
                        "reserve_in_usd": liquidity,
                        "price_change_percentage": attributes.get("price_change_percentage") or {},
                        "transactions": attributes.get("transactions") or {},
                        "volume_usd": attributes.get("volume_usd") or {},
                        "base_token_price_usd": _safe_float(attributes.get("base_token_price_usd")),
                        "quote_token_price_usd": _safe_float(attributes.get("quote_token_price_usd")),
                        "trades_24h": _h24_transactions(attributes)[0],
                        "traders_24h": _h24_transactions(attributes)[1],
                        "quality_score": quality_score,
                        "quality_flags": quality_flags,
                    }
                )
            if len(candidates) >= args.count:
                break
            time.sleep(args.request_delay_sec)

        if len(candidates) >= args.count:
            break

        for page in range(1, args.discovery_pages + 1):
            payload = _api_get(
                session,
                f"/networks/{network}/pools",
                {"page": page, "include": "base_token,quote_token,dex"},
                args.retries,
                args.request_delay_sec,
            )
            included = _included_symbols(payload)
            for pool in payload.get("data") or []:
                attributes = pool.get("attributes") or {}
                symbol = _token_symbol_from_pool(pool, included)
                name = str(attributes.get("name") or symbol)
                created_at = attributes.get("pool_created_at")
                age_days = _pool_age_days(created_at, int(time.time()))
                base_symbol = included.get(_base_token_id(pool) or "", symbol)
                if not symbol or symbol in seen:
                    continue

                liquidity = _safe_float(attributes.get("reserve_in_usd"), 0.0) or 0.0
                volume_24h = _safe_float((attributes.get("volume_usd") or {}).get("h24"), 0.0) or 0.0
                market_cap = _safe_float(attributes.get("market_cap_usd"))
                is_good, quality_flags, quality_score = _pool_quality(attributes, symbol, base_symbol, age_days, args)
                if not is_good:
                    continue

                seen.add(symbol)
                candidates.append(
                    {
                        "asset": symbol,
                        "network": network,
                        "pool_address": _pool_address(pool),
                        "name": name,
                        "pool_created_at": created_at,
                        "pool_age_days": round(age_days, 2) if age_days is not None else None,
                        "market_cap_usd": market_cap,
                        "fdv_usd": _safe_float(attributes.get("fdv_usd")),
                        "reserve_in_usd": liquidity,
                        "price_change_percentage": attributes.get("price_change_percentage") or {},
                        "transactions": attributes.get("transactions") or {},
                        "volume_usd": attributes.get("volume_usd") or {},
                        "base_token_price_usd": _safe_float(attributes.get("base_token_price_usd")),
                        "quote_token_price_usd": _safe_float(attributes.get("quote_token_price_usd")),
                        "trades_24h": _h24_transactions(attributes)[0],
                        "traders_24h": _h24_transactions(attributes)[1],
                        "quality_score": quality_score,
                        "quality_flags": quality_flags,
                    }
                )
            if len(candidates) >= args.count:
                break
            time.sleep(args.request_delay_sec)

    candidates.sort(
        key=lambda item: (
            float(item.get("quality_score") or 0.0),
            float(item.get("volume_usd", {}).get("h24") or 0.0),
            float(item.get("reserve_in_usd") or 0.0),
        ),
        reverse=True,
    )
    return candidates[: args.count]


def _extract_ohlcv(payload: Dict[str, Any]) -> List[List[Any]]:
    attributes = (payload.get("data") or {}).get("attributes") or {}
    return [row[:6] for row in attributes.get("ohlcv_list") or [] if isinstance(row, (list, tuple)) and len(row) >= 6]


def crawl_ohlcv(
    session: requests.Session,
    target: Dict[str, Any],
    timeframe: str,
    aggregate: int,
    start_sec: int,
    end_sec: int,
    args: argparse.Namespace,
) -> pd.DataFrame:
    raw: List[List[Any]] = []
    before = end_sec
    path = f"/networks/{target['network']}/pools/{target['pool_address']}/ohlcv/{timeframe}"

    needed_pages = math.ceil(args.lookback_days * 1440 / args.limit) + 2
    max_pages = max(getattr(args, "max_pages", 0), needed_pages)

    for page in range(1, max_pages + 1):
        payload = _api_get(
            session,
            path,
            {
                "aggregate": aggregate,
                "before_timestamp": before,
                "limit": args.limit,
                "currency": "usd",
                "token": "base",
                "include_empty_intervals": "false",
            },
            args.retries,
            args.request_delay_sec,
        )
        rows = _extract_ohlcv(payload)
        if not rows:
            break
        raw.extend(rows)
        oldest = min(int(row[0]) for row in rows)
        log(f"[crawl] {target['asset']:12s} {aggregate}{timeframe[0]} page={page:02d} rows={len(rows):4d} oldest={datetime.fromtimestamp(oldest, timezone.utc).date()}")
        if oldest <= start_sec or len(rows) < args.limit:
            break
        before = oldest - 1
        time.sleep(args.request_delay_sec)

    records: Dict[int, Dict[str, float]] = {}
    for row in raw:
        ts = int(row[0])
        if ts < start_sec or ts > end_sec:
            continue
        records[ts * 1000] = {
            "open_time": ts * 1000,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
    if not records:
        return pd.DataFrame(columns=PKL_COLUMNS)
    frame = pd.DataFrame(sorted(records.values(), key=lambda item: item["open_time"]))
    return frame.loc[:, PKL_COLUMNS].reset_index(drop=True)


def aggregate_frame(frame: pd.DataFrame, interval_ms: int) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=PKL_COLUMNS)
    ordered = frame.sort_values("open_time").copy()
    ordered["_bucket"] = (ordered["open_time"] // interval_ms) * interval_ms
    grouped = ordered.groupby("_bucket", as_index=False).agg(
        open_time=("_bucket", "first"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    return grouped.loc[:, PKL_COLUMNS].reset_index(drop=True)


# synthetic_ticks_from_ohlcv was REMOVED in Phase 1.
# Ticks must come from real on-chain data via crawl_dex_ticks.py.
# All OHLCV resampling is delegated to core/resampler.py.


def write_asset(
    target: Dict[str, Any],
    frame_1m: pd.DataFrame,
    output_dir: str,
    crawl_ok: bool = True,
    requested_start_ts: Optional[int] = None,
    requested_end_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Phase 1: write 1m source of truth, resample all timeframes, generate manifest.json."""
    asset = _slug(target["asset"])
    pool_address = str(target.get("pool_address") or "")

    manifest = save_resampled_dataset(
        symbol=asset,
        output_dir=output_dir,
        df_1m_raw=frame_1m,
        pool_address=pool_address,
        timeframes=("5m", "15m", "1h", "4h", "24h"),
        source="geckoterminal",
        synthetic=False,
        crawl_ok=crawl_ok,
        requested_start_ts=requested_start_ts,
        requested_end_ts=requested_end_ts,
        extra_meta={"venue": "dex", "exchange": "geckoterminal", "network": target.get("network"), "volume_unit": "usd"},
    )

    # Also write dex_pool.json metadata (separate from manifest.json)
    asset_dir = os.path.join(output_dir, asset)
    metadata = dict(target)
    metadata["asset"] = asset
    metadata["crawled_at"] = int(time.time())
    metadata["liquidity_usd"] = _safe_float(target.get("reserve_in_usd"))
    metadata["volume_24h_usd"] = _safe_float((target.get("volume_usd") or {}).get("h24"))
    tx_24h = (target.get("transactions") or {}).get("h24") or {}
    metadata["trades_24h"] = int((tx_24h.get("buys") or 0) + (tx_24h.get("sells") or 0))
    metadata["buyers_24h"] = int(tx_24h.get("buyers") or 0)
    metadata["sellers_24h"] = int(tx_24h.get("sellers") or 0)
    metadata["pool_name"] = target.get("name")
    metadata["pool_age_days"] = target.get("pool_age_days")
    metadata["rows"] = manifest["rows"]
    with open(os.path.join(asset_dir, "dex_pool.json"), "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)

    return manifest



def clear_universe(output_dir: str, keep_assets: Iterable[str]) -> None:
    keep = {_slug(asset) for asset in keep_assets}
    protected = {"research", "research_scans", "ticks"}
    os.makedirs(output_dir, exist_ok=True)
    for name in os.listdir(output_dir):
        path = os.path.join(output_dir, name)
        if not os.path.isdir(path) or name in protected or name.startswith("."):
            continue
        if name.upper() not in keep:
            shutil.rmtree(path)
            log(f"[clear] removed old asset dir {path}")
    cache_dir = os.path.join(output_dir, "research", "market_analysis")
    if os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir)
        log(f"[clear] removed stale research cache {cache_dir}")
    scan_cache = os.path.join(output_dir, "research_scans", "latest_scan.json")
    if os.path.isfile(scan_cache):
        os.remove(scan_cache)
        log(f"[clear] removed stale scan cache {scan_cache}")
    legacy_targets = os.path.join(output_dir, "geckoterminal_targets.json")
    if os.path.isfile(legacy_targets):
        os.remove(legacy_targets)
        log(f"[clear] removed stale target file {legacy_targets}")


def run(args: argparse.Namespace) -> List[Dict[str, Any]]:
    session = requests.Session()
    session.headers.update({"accept": "application/json", "user-agent": "Nora DEX Research Crawler/1.0"})
    output_dir = os.path.abspath(args.output_dir)
    end_sec = int(time.time()) if not args.end_ts else int(args.end_ts)
    start_sec = end_sec - int(args.lookback_days * 86400)

    targets = _load_targets(args.targets_file, args)
    if targets:
        log(f"[targets] loaded {len(targets)} targets from {args.targets_file}")
        targets = targets[: args.count]
    else:
        targets = discover_targets(args, session, start_sec)
    if len(targets) < args.count:
        warn(f"[warn] selected only {len(targets)}/{args.count} targets after filters")
    if args.targets_out:
        with open(args.targets_out, "w", encoding="utf-8") as handle:
            json.dump(targets, handle, indent=2, ensure_ascii=False)
        log(f"[targets] wrote {len(targets)} targets to {args.targets_out}")
    if args.discover_only:
        log("[done] discover-only mode")
        for target in targets:
            log(
                f"  {target['asset']:12s} {target['network']:7s} "
                f"liq=${float(target.get('reserve_in_usd') or 0):,.0f} "
                f"vol24=${float((target.get('volume_usd') or {}).get('h24') or 0):,.0f} "
                f"age={target.get('pool_age_days')}d {target.get('name', '')}"
            )
        return []
    if args.clear:
        clear_universe(output_dir, [target["asset"] for target in targets])

    summaries = []
    for idx, target in enumerate(targets, 1):
        log(f"[asset] {idx}/{len(targets)} {target['asset']} | {target['network']} | {target['name']}")
        # Phase 1: crawl raw 1m (aggregate=1), delegate resampling to core/resampler.py
        frame_1m = crawl_ohlcv(session, target, "minute", 1, start_sec, end_sec, args)
        if frame_1m.empty:
            warn(f"[skip] {target['asset']} missing 1m data")
            continue
        try:
            oldest = int(frame_1m["open_time"].min()) // 1000
            crawl_ok = oldest <= start_sec + 86400  # cho phép lệch 1 ngày
            manifest = write_asset(
                target,
                frame_1m,
                output_dir,
                crawl_ok=crawl_ok,
                requested_start_ts=start_sec * 1000,
                requested_end_ts=end_sec * 1000,
            )
            summaries.append({
                "asset": target["asset"],
                "rows_1m": manifest["rows"].get("1m", 0),
                "rows_1h": manifest["rows"].get("1h", 0),
                "rows_4h": manifest["rows"].get("4h", 0),
                "filled_ratio_1m": manifest["filled_ratio_1m"],
                "crawl_ok": manifest.get("crawl_ok", True),
            })
            log(f"[write] {target['asset']} 1m={manifest['rows'].get('1m', 0)} filled={manifest['filled_ratio_1m']:.3f} crawl_ok={crawl_ok}")
        except Exception as exc:
            warn(f"[error] {target['asset']} write failed: {exc}")
            import traceback
            traceback.print_exc()
        time.sleep(args.asset_delay_sec)

    log("[done] DEX universe crawl complete (Phase 1 compliant)")
    for item in summaries:
        log(f"  {item['asset']:12s} 1m={item['rows_1m']:5d} 1h={item['rows_1h']:4d} 4h={item['rows_4h']:3d} filled={item['filled_ratio_1m']:.3f}")
    return summaries


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl top DEX universe data from GeckoTerminal.")
    parser.add_argument("--output-dir", default=os.path.join(default_data_root(), "dex"))
    parser.add_argument("--targets-file", default=None, help="Optional GeckoTerminal DEX targets JSON to crawl without rediscovery.")
    parser.add_argument("--targets-out", default=os.path.join(default_data_root(), "_meta", "geckoterminal_dex_targets.json"))
    parser.add_argument("--networks", default="solana,base,eth,bsc")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--lookback-days", type=float, default=90.0)
    parser.add_argument("--end-ts", default=None)
    parser.add_argument("--discovery-pages", type=int, default=8)
    parser.add_argument("--min-age-days", type=float, default=90.0)
    parser.add_argument("--min-liquidity-usd", type=float, default=100_000.0)
    parser.add_argument("--min-volume-24h-usd", type=float, default=500_000.0)
    parser.add_argument("--min-trades-24h", type=int, default=1000)
    parser.add_argument("--min-traders-24h", type=int, default=200)
    parser.add_argument("--min-buyers-24h", type=int, default=50)
    parser.add_argument("--min-market-cap-usd", type=float, default=0.0)
    parser.add_argument("--max-turnover-24h", type=float, default=120.0)
    parser.add_argument("--high-turnover-min-traders", type=int, default=500)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=80)
    parser.add_argument("--request-delay-sec", type=float, default=1.2)
    parser.add_argument("--asset-delay-sec", type=float, default=1.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--clear", action="store_true", help="Remove old asset dirs not in the selected DEX universe.")
    parser.add_argument("--discover-only", action="store_true", help="Write and print selected targets without crawling OHLCV.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
