"""Crawl nến 1m Binance Spot (CEX) nhiều năm -> 1m.pkl + các khung resample + manifest.json.

Nguồn (theo thứ tự):
1. data.binance.vision  — file ZIP theo THÁNG cho các tháng đã đóng, kèm .CHECKSUM (SHA-256).
2. data.binance.vision  — file ZIP theo NGÀY cho tháng hiện tại (tới hôm qua).
3. REST /api/v3/klines — phần còn lại tới hiện tại (hôm nay).

Mọi resample/manifest đi qua core/resampler.save_resampled_dataset (một nguồn duy nhất = 1m).

Lưu ý định dạng:
- Từ 2025-01-01, open_time trong file spot của data.binance.vision tính bằng MICRO-giây
  (trước đó là mili-giây). REST API vẫn trả mili-giây. Mọi timestamp được chuẩn hoá về ms.
- volume ghi vào pkl là quote_asset_volume (USDT) để cùng đơn vị USD với dữ liệu DEX.

Ví dụ:
    python -m backend.crawler.crawl_binance_klines --symbols BTC,ETH --years 3            # -> data/cex/<SYM>
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    from backend.core.resampler import save_resampled_dataset
except ImportError:  # pragma: no cover
    from nora.backend.core.resampler import save_resampled_dataset

VISION_BASE = "https://data.binance.vision/data/spot"
REST_BASE = "https://api.binance.com/api/v3/klines"
MARKETS = {
    "spot": {"vision": "https://data.binance.vision/data/spot", "rest": REST_BASE,
             "source": "binance_spot", "exchange": "binance", "market": "spot"},
    "um": {"vision": "https://data.binance.vision/data/futures/um", "rest": "https://fapi.binance.com/fapi/v1/klines",
           "funding_rest": "https://fapi.binance.com/fapi/v1/fundingRate",
           "source": "binance_usdm", "exchange": "binance_usdm", "market": "perp"},
}
MINUTE_MS = 60_000
DEFAULT_CACHE_DIR = os.environ.get("NORA_BINANCE_CACHE_DIR") or os.path.join(
    os.path.dirname(REPO_ROOT), "data", "cache", "binance")  # REPO_ROOT = thư mục nora/ -> cha = gốc repo
KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume_base", "close_time",
    "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore",
]


def log(msg: str) -> None:
    print(msg, flush=True)


class ChecksumMismatch(RuntimeError):
    pass


def normalize_ts_ms(ts: pd.Series) -> pd.Series:
    """µs (>= 1e14, dùng từ 2025) -> ms; ms giữ nguyên."""
    ts = pd.to_numeric(ts, errors="coerce").astype("int64")
    return ts.where(ts < 10**14, ts // 1000)


def parse_kline_csv(raw: bytes) -> pd.DataFrame:
    """Đọc CSV kline Binance (có hoặc không có header) -> OHLCV chuẩn, ts ms, volume = quote (USDT)."""
    df = pd.read_csv(io.BytesIO(raw), header=None, names=KLINE_COLUMNS, dtype=str)
    df = df[pd.to_numeric(df["open_time"], errors="coerce").notna()]  # bỏ dòng header nếu có
    if df.empty:
        return pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"])
    out = pd.DataFrame({
        "open_time": normalize_ts_ms(df["open_time"]),
        "open": pd.to_numeric(df["open"], errors="coerce"),
        "high": pd.to_numeric(df["high"], errors="coerce"),
        "low": pd.to_numeric(df["low"], errors="coerce"),
        "close": pd.to_numeric(df["close"], errors="coerce"),
        "volume": pd.to_numeric(df["quote_volume"], errors="coerce"),
    }).dropna()
    return out.reset_index(drop=True)


def _http_get(session: requests.Session, url: str, retries: int = 5, timeout: int = 60, **kwargs) -> Optional[requests.Response]:
    """GET có retry. Trả None nếu 404 (file chưa có)."""
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=timeout, **kwargs)
            if resp.status_code == 404:
                return None
            if resp.status_code in (418, 429) or resp.status_code >= 500:
                wait = min(60, 5 * attempt)
                log(f"[warn] HTTP {resp.status_code} {url} -> chờ {wait}s ({attempt}/{retries})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            if attempt == retries:
                raise
            log(f"[warn] {exc} -> thử lại ({attempt}/{retries})")
            time.sleep(3 * attempt)
    raise RuntimeError(f"GET thất bại sau {retries} lần: {url}")


def fetch_vision_zip(session: requests.Session, url: str, cache_dir: str) -> Optional[bytes]:
    """Tải ZIP + CHECKSUM (có cache trên đĩa), kiểm SHA-256. Trả CSV bytes; None nếu file chưa tồn tại."""
    os.makedirs(cache_dir, exist_ok=True)
    name = url.rsplit("/", 1)[-1]
    zip_path = os.path.join(cache_dir, name)

    checksum_resp = _http_get(session, url + ".CHECKSUM")
    if checksum_resp is None:
        return None
    expected = checksum_resp.text.strip().split()[0].lower()

    if os.path.isfile(zip_path):
        with open(zip_path, "rb") as f:
            payload = f.read()
        if hashlib.sha256(payload).hexdigest() != expected:
            os.remove(zip_path)  # cache hỏng -> tải lại
            payload = None
    else:
        payload = None

    if payload is None:
        resp = _http_get(session, url)
        if resp is None:
            return None
        payload = resp.content
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            raise ChecksumMismatch(f"{name}: sha256 {actual} != {expected}")
        with open(zip_path, "wb") as f:
            f.write(payload)

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return zf.read(zf.namelist()[0])


def fetch_rest_klines(session: requests.Session, market_symbol: str, start_ms: int, end_ms: int,
                      rest_url: str = REST_BASE) -> pd.DataFrame:
    """REST klines (spot /api/v3 hoặc futures /fapi/v1) từ start_ms tới end_ms (ms). Chỉ lấy nến đã đóng."""
    rows: List[list] = []
    cursor = start_ms
    now_ms = int(time.time() * 1000)
    while cursor <= end_ms:
        resp = _http_get(session, rest_url, params={
            "symbol": market_symbol, "interval": "1m", "startTime": cursor, "endTime": end_ms, "limit": 1000,
        }, timeout=30)
        batch = resp.json() if resp is not None else []
        if not batch:
            break
        rows.extend(batch)
        cursor = int(batch[-1][0]) + MINUTE_MS
        if len(batch) < 1000:
            break
        time.sleep(0.2)
    if not rows:
        return pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"])
    raw = "\n".join(",".join(str(v) for v in r) for r in rows).encode()
    df = parse_kline_csv(raw)
    close_time = df["open_time"] + MINUTE_MS
    return df[close_time <= now_ms].reset_index(drop=True)


def _month_iter(start: date, end_exclusive: date):
    cur = date(start.year, start.month, 1)
    while cur < end_exclusive:
        yield cur
        cur = date(cur.year + (cur.month // 12), cur.month % 12 + 1, 1)


def parse_funding_csv(raw: bytes) -> pd.DataFrame:
    """CSV funding của data.binance.vision: calc_time,funding_interval_hours,last_funding_rate."""
    df = pd.read_csv(io.BytesIO(raw), header=None, dtype=str)
    df = df[pd.to_numeric(df[0], errors="coerce").notna()]
    out = pd.DataFrame({
        "funding_time": normalize_ts_ms(df[0]),
        "interval_h": pd.to_numeric(df[1], errors="coerce") if df.shape[1] > 2 else 8.0,
        "rate": pd.to_numeric(df[df.shape[1] - 1], errors="coerce"),
    })
    return out.dropna(subset=["rate"]).reset_index(drop=True)


def crawl_funding(session: requests.Session, market_symbol: str, start_ms: int, end_ms: int,
                  cache_dir: str) -> Tuple[pd.DataFrame, List[str]]:
    """Lịch sử funding USDT-M: file tháng (có checksum) + REST cho tháng hiện tại."""
    cfg = MARKETS["um"]
    start_d = datetime.fromtimestamp(start_ms / 1000, timezone.utc).date()
    end_d = datetime.fromtimestamp(end_ms / 1000, timezone.utc).date()
    this_month = date(end_d.year, end_d.month, 1)
    frames, issues = [], []
    for month in _month_iter(start_d, this_month):
        tag = month.strftime("%Y-%m")
        url = f"{cfg['vision']}/monthly/fundingRate/{market_symbol}/{market_symbol}-fundingRate-{tag}.zip"
        raw = fetch_vision_zip(session, url, os.path.join(cache_dir, "um", market_symbol))
        if raw is None:
            issues.append(f"thiếu funding tháng {tag}")
            continue
        frames.append(parse_funding_csv(raw))
    cursor = int(datetime(this_month.year, this_month.month, 1, tzinfo=timezone.utc).timestamp() * 1000)
    while cursor <= end_ms:
        resp = _http_get(session, cfg["funding_rest"], params={"symbol": market_symbol, "startTime": cursor,
                                                                "endTime": end_ms, "limit": 1000}, timeout=30)
        batch = resp.json() if resp is not None else []
        if not batch:
            break
        frames.append(pd.DataFrame({"funding_time": [int(b["fundingTime"]) for b in batch],
                                    "interval_h": np.nan, "rate": [float(b["fundingRate"]) for b in batch]}))
        cursor = int(batch[-1]["fundingTime"]) + 1
        if len(batch) < 1000:
            break
    if not frames:
        return pd.DataFrame(columns=["funding_time", "interval_h", "rate"]), issues + ["không có funding"]
    df = pd.concat(frames, ignore_index=True)
    df = df[(df["funding_time"] >= start_ms) & (df["funding_time"] <= end_ms)]
    df = df.drop_duplicates("funding_time", keep="last").sort_values("funding_time").reset_index(drop=True)
    return df, issues


def crawl_symbol(
    session: requests.Session,
    base: str,
    quote: str,
    start_ms: int,
    end_ms: int,
    cache_dir: str,
    market_kind: str = "spot",
) -> Tuple[pd.DataFrame, Dict[str, int], List[str]]:
    """Trả (df_1m, thống kê nguồn, danh sách vấn đề). Vấn đề không rỗng -> crawl_ok=False."""
    cfg = MARKETS[market_kind]
    vision = cfg["vision"]
    market = f"{base}{quote}".upper()
    zip_cache = os.path.join(cache_dir, market) if market_kind == "spot" else os.path.join(cache_dir, market_kind, market)
    start_d = datetime.fromtimestamp(start_ms / 1000, timezone.utc).date()
    end_d = datetime.fromtimestamp(end_ms / 1000, timezone.utc).date()
    this_month = date(end_d.year, end_d.month, 1)
    frames: List[pd.DataFrame] = []
    stats = {"monthly_files": 0, "daily_files": 0, "rest_rows": 0}
    issues: List[str] = []

    # 1) Tháng đã đóng
    for month in _month_iter(start_d, this_month):
        tag = month.strftime("%Y-%m")
        url = f"{vision}/monthly/klines/{market}/1m/{market}-1m-{tag}.zip"
        raw = fetch_vision_zip(session, url, zip_cache)
        if raw is None:
            issues.append(f"thiếu file tháng {tag}")
            continue
        frames.append(parse_kline_csv(raw))
        stats["monthly_files"] += 1
        log(f"[month] {market} {tag} rows={len(frames[-1])}")

    # 2) Ngày của tháng hiện tại, tới hôm qua (file ngày có thể trễ ~1 ngày -> REST bù)
    day = this_month
    last_daily_end = int(datetime(this_month.year, this_month.month, 1, tzinfo=timezone.utc).timestamp() * 1000)
    while day < end_d:
        tag = day.isoformat()
        url = f"{vision}/daily/klines/{market}/1m/{market}-1m-{tag}.zip"
        raw = fetch_vision_zip(session, url, zip_cache)
        if raw is None:
            break  # chưa phát hành -> phần còn lại lấy qua REST
        frames.append(parse_kline_csv(raw))
        stats["daily_files"] += 1
        last_daily_end = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000) + 86_400_000
        day += timedelta(days=1)

    # 3) Phần còn lại tới hiện tại qua REST
    rest = fetch_rest_klines(session, market, last_daily_end, end_ms, cfg["rest"])
    stats["rest_rows"] = len(rest)
    if not rest.empty:
        frames.append(rest)

    if not frames:
        return pd.DataFrame(), stats, issues + ["không có dữ liệu"]

    df = pd.concat(frames, ignore_index=True)
    df = df[(df["open_time"] >= start_ms) & (df["open_time"] <= end_ms)]
    df = df.drop_duplicates("open_time", keep="last").sort_values("open_time").reset_index(drop=True)
    misaligned = int((df["open_time"] % MINUTE_MS != 0).sum())
    if misaligned:
        issues.append(f"{misaligned} nến không thẳng mốc phút")
    return df, stats, issues


def run(args: argparse.Namespace) -> List[Dict]:
    if not args.output_dir:
        from backend.db.data_layout import default_data_root
        args.output_dir = os.path.join(default_data_root(), "cex")
    end_ms = int(time.time() * 1000) // MINUTE_MS * MINUTE_MS if not args.end_ts else int(args.end_ts)
    start_ms = end_ms - int(args.years * 365.25 * 86_400_000)
    start_ms = start_ms // MINUTE_MS * MINUTE_MS
    session = requests.Session()
    session.headers.update({"User-Agent": "nora-research/1.0"})
    summaries = []
    for base in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        log(f"[asset] {base}{args.quote} {datetime.fromtimestamp(start_ms/1000, timezone.utc):%Y-%m-%d} -> "
            f"{datetime.fromtimestamp(end_ms/1000, timezone.utc):%Y-%m-%d %H:%M}")
        cfg = MARKETS[args.market]
        try:
            df, stats, issues = crawl_symbol(session, base, args.quote, start_ms, end_ms, args.cache_dir, args.market)
            funding = None
            if args.market == "um":
                funding, f_issues = crawl_funding(session, f"{base}{args.quote}", start_ms, end_ms, args.cache_dir)
                issues += f_issues
        except ChecksumMismatch as exc:
            log(f"[error] {base}: {exc} -> bỏ qua tài sản này")
            continue
        if df.empty:
            log(f"[skip] {base}: không có dữ liệu ({issues})")
            continue
        # spot -> <out>/<SYM>;  perp -> <out>/<SYM>/perp  (xem backend/db/data_layout.py)
        out_dir, dir_name = (args.output_dir, base) if args.market == "spot" else (os.path.join(args.output_dir, base), "perp")
        extra = {
            "venue": "cex",
            "exchange": cfg["exchange"],
            "market": cfg["market"],
            "base_symbol": base,
            "market_symbol": f"{base}{args.quote}",
            "volume_unit": f"quote_{args.quote.lower()}",
            "source_files": stats,
            "checksums_verified": True,
            "crawl_issues": issues,
        }
        if funding is not None:
            extra["funding"] = {
                "file": "funding.pkl",
                "rows": int(len(funding)),
                "start_ts": int(funding["funding_time"].min()) if len(funding) else None,
                "end_ts": int(funding["funding_time"].max()) if len(funding) else None,
                "mean_rate": float(funding["rate"].mean()) if len(funding) else None,
            }
        manifest = save_resampled_dataset(
            symbol=dir_name,
            output_dir=out_dir,
            df_1m_raw=df,
            pool_address=f"binance:{cfg['market']}:{base}{args.quote}",
            source=cfg["source"],
            synthetic=False,
            crawl_ok=not issues,
            requested_start_ts=start_ms,
            requested_end_ts=end_ms,
            extra_meta=extra,
        )
        if funding is not None:
            funding.to_pickle(os.path.join(out_dir, dir_name, "funding.pkl"))
        if args.market != "spot":  # ký hiệu instrument: BTC@perp
            manifest["symbol"] = f"{base}@perp"
            with open(os.path.join(out_dir, dir_name, "manifest.json"), "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=2)
        log(f"[manifest] {base} rows_1m={manifest['rows']['1m']} coverage_days={manifest['coverage_days']} "
            f"filled={manifest['filled_ratio_1m']:.4f} crawl_ok={manifest['crawl_ok']} files={stats}")
        summaries.append(manifest)
    log(f"[done] Binance {args.market} crawl finished.")
    return summaries


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbols", required=True, help="Base assets, vd BTC,ETH,SOL")
    p.add_argument("--quote", default="USDT")
    p.add_argument("--market", choices=sorted(MARKETS), default="spot", help="spot | um (USDT-M perpetual)")
    p.add_argument("--years", type=float, default=3.0)
    p.add_argument("--end-ts", default=None, help="End timestamp ms (mặc định: hiện tại)")
    p.add_argument("--output-dir", default=None, help="Mặc định: <data_root>/cex")
    p.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    return p.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
