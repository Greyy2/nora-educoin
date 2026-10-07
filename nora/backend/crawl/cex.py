"""Nến + funding CEX (Binance data.binance.vision/REST và OKX CDN/REST) -> 1m.pkl + khung resample + manifest.

P9.2 (ADR-P9): gộp NGUYÊN VĂN core/data/crawler.py (Binance) + core/data/okx_crawler.py (OKX).
Tên trùng giữa hai nguồn được đổi phía OKX: crawl -> okx_crawl, crawl_funding -> okx_crawl_funding, run_job -> okx_run_job,
DEFAULT_CACHE_DIR -> OKX_DEFAULT_CACHE_DIR. Đường dẫn module cũ vẫn dùng được qua shim (core/data/{crawler,okx_crawler}.py).
"""
import hashlib
import io
import json
import os
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import requests
from backend.utils.jobs import as_list, options, write_job_result
from backend.crawl.store import save_resampled_dataset


# ====================================================================================================
# ↓ core/data/crawler.py  (P9.2: chuyển nguyên văn; module cũ: backend.core.data.crawler)
# ====================================================================================================
# Crawl nến 1m Binance Spot (CEX) nhiều năm -> 1m.pkl + các khung resample + manifest.json.
#
# Nguồn (theo thứ tự):
# 1. data.binance.vision  — file ZIP theo THÁNG cho các tháng đã đóng, kèm .CHECKSUM (SHA-256).
# 2. data.binance.vision  — file ZIP theo NGÀY cho tháng hiện tại (tới hôm qua).
# 3. REST /api/v3/klines — phần còn lại tới hiện tại (hôm nay).
#
# Mọi resample/manifest đi qua core/resampler.save_resampled_dataset (một nguồn duy nhất = 1m).
#
# Lưu ý định dạng:
# - Từ 2025-01-01, open_time trong file spot của data.binance.vision tính bằng MICRO-giây
#   (trước đó là mili-giây). REST API vẫn trả mili-giây. Mọi timestamp được chuẩn hoá về ms.
# - volume ghi vào pkl là quote_asset_volume (USDT) để cùng đơn vị USD với dữ liệu DEX.
#
# Job API `data_crawl` (POST /api/data/crawl -> api/jobs/runner.py -> run_job): params symbols ("BTC,ETH" hoặc list), market (spot|um),
# years, quote, end_ts; mặc định ghi vào data/binance/cex (Binance = dữ liệu tham khảo; sàn triển khai OKX: core/data/okx_crawler.py).
#

NORA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

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
    os.path.dirname(NORA_DIR), "data", "cache", "binance")  # cha của thư mục nora/ = gốc repo
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


def crawl(args) -> List[Dict]:
    if not args.output_dir:
        from backend.crawl.store import exchange_root
        args.output_dir = os.path.join(exchange_root("binance"), "cex")
    end_ms = int(time.time() * 1000) // MINUTE_MS * MINUTE_MS if not args.end_ts else int(args.end_ts)
    start_ms = end_ms - int(args.years * 365.25 * 86_400_000)
    start_ms = start_ms // MINUTE_MS * MINUTE_MS
    session = requests.Session()
    session.headers.update({"User-Agent": "nora-research/1.0"})
    summaries = []
    for base in [s.strip().upper() for s in as_list(args.symbols) if s.strip()]:
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


def run_job(params=None) -> List[Dict]:
    """Crawl theo `params` (khoá: symbols, quote, market, years, end_ts, output_dir, cache_dir) -> báo cáo từng tài sản."""
    a = options({"symbols": "", "quote": "USDT", "market": "spot", "years": 3.0, "end_ts": None, "output_dir": None,
                 "cache_dir": DEFAULT_CACHE_DIR}, params)
    if not as_list(a.symbols):
        raise ValueError("cần symbols")
    if a.market not in MARKETS:
        raise ValueError(f"market phải là một trong {sorted(MARKETS)}")
    out = crawl(a)
    write_job_result({"assets": out})
    return out


# ====================================================================================================
# ↓ core/data/okx_crawler.py  (P9.2: chuyển nguyên văn; module cũ: backend.core.data.okx_crawler)
# ====================================================================================================
# Crawl nến 1m + funding OKX USDT-SWAP (sàn triển khai của Nora) nhiều năm -> 1m.pkl + các khung resample + funding.pkl + manifest.json.
#
# Nguồn nến (theo thứ tự):
# 1. static.okx.com/cdn/okex/traderecords/candlesticks/daily — file ZIP CHÍNH THỨC theo NGÀY (ngày giờ Hồng Kông, UTC+8: file "D" phủ
#    D-1 16:00Z -> D 15:59Z), cột instrument_name,open,high,low,close,vol,vol_ccy,vol_quote,open_time,confirm.
# 2. REST /api/v5/market/history-candles (bar 1m, 100 nến/lần, phân trang lùi) — ngày chưa phát hành (thường hôm nay) hoặc file thiếu.
# volume ghi vào pkl = vol_quote / volCcyQuote (USDT) — cùng đơn vị với dữ liệu Binance (quote) và DEX.
#
# Nguồn funding (theo thứ tự, mỗi mốc chỉ lấy một nguồn):
# 1. static.okx.com/.../swaprate/daily — file ngày chính thức (real_funding_rate = funding đã thanh toán); OKX ngừng phát hành từ ~09/2025.
# 2. REST /api/v5/public/funding-rate-history (realizedRate) — chỉ ~3 tháng gần nhất.
# 3. Khoảng trống còn lại: PROXY = funding Binance USDT-M cùng mã (data/binance/cex/<SYM>/perp/funding.pkl) — ghi rõ trong manifest
#    (funding.sources, funding.proxy_ranges). Funding hai sàn tương quan cao nhưng không trùng: kết quả backtest trong khoảng proxy là xấp xỉ.
#
# Dữ liệu từ API chính thức của sàn (không có file checksum như data.binance.vision) -> manifest official_api=True, checksums_verified=False.
#
# Job API `data_crawl_okx` (POST /api/data/crawl exchange=okx -> api/jobs/runner.py -> run_job): params symbols, years, end_ts, output_dir
# (router đặt data_staging/), cache_dir, workers. Sau đó POST /api/data/promote đưa tài sản qua quality gate vào data/okx/cex/.
#

NORA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CDN = "https://static.okx.com/cdn/okex/traderecords"
REST = "https://www.okx.com"
MINUTE_MS, HOUR_MS, DAY_MS = 60_000, 3_600_000, 86_400_000
HK_OFFSET_MS = 8 * HOUR_MS                 # ngày của file CDN theo giờ Hồng Kông
FUNDING_GAP_MS = 16 * HOUR_MS              # hai mốc funding OKX cách nhau hơn mức này -> khoảng trống (chu kỳ chuẩn 8h)
OKX_DEFAULT_CACHE_DIR = os.environ.get("NORA_OKX_CACHE_DIR") or os.path.join(os.path.dirname(NORA_DIR), "data", "cache", "okx")
COLS = ["open_time", "open", "high", "low", "close", "volume"]


def inst(base: str) -> str:
    return f"{base}-USDT-SWAP"


def _day_tag(d: date) -> Tuple[str, str]:
    return d.strftime("%Y%m%d"), d.isoformat()


def fetch_day_zip(session: requests.Session, kind: str, base: str, d: date, cache_dir: str) -> Optional[bytes]:
    """CSV bytes của file ngày `kind` (candlesticks | swaprate); None nếu chưa/không phát hành. ZIP được cache trên đĩa."""
    compact, iso = _day_tag(d)
    name = f"{inst(base)}-{kind}-{iso}.zip"
    path = os.path.join(cache_dir, kind, inst(base), name)
    miss = path + ".404"
    if os.path.exists(path):
        raw = open(path, "rb").read()
    elif os.path.exists(miss) and d < datetime.now(timezone.utc).date() - timedelta(days=3):
        return None                                   # đã biết không có (chỉ tin dấu 404 với ngày đủ cũ)
    else:
        resp = _http_get(session, f"{CDN}/{kind}/daily/{compact}/{name}")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if resp is None:
            open(miss, "w").close()
            return None
        raw = resp.content
        with open(path + ".tmp", "wb") as fh:
            fh.write(raw)
        os.replace(path + ".tmp", path)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        return zf.read(zf.namelist()[0])


def parse_candles_csv(raw: bytes, base: str) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw))
    df = df[df["instrument_name"] == inst(base)]
    out = pd.DataFrame({"open_time": pd.to_numeric(df["open_time"], errors="coerce"),
                        "open": pd.to_numeric(df["open"], errors="coerce"), "high": pd.to_numeric(df["high"], errors="coerce"),
                        "low": pd.to_numeric(df["low"], errors="coerce"), "close": pd.to_numeric(df["close"], errors="coerce"),
                        "volume": pd.to_numeric(df["vol_quote"], errors="coerce")}).dropna()
    out["open_time"] = out["open_time"].astype("int64")
    return out.reset_index(drop=True)


def parse_swaprate_csv(raw: bytes) -> pd.DataFrame:
    """Cột (header song ngữ): contract_type, funding_rate (dự báo), real_funding_rate (đã thanh toán), funding_time."""
    df = pd.read_csv(io.BytesIO(raw), header=None, skiprows=1, encoding="latin1")
    return pd.DataFrame({"funding_time": pd.to_numeric(df[3], errors="coerce"),
                         "rate": pd.to_numeric(df[2], errors="coerce")}).dropna().astype({"funding_time": "int64"})


def _okx_get(session: requests.Session, path: str, params: Dict, pause: float) -> List:
    for attempt in range(1, 6):
        resp = _http_get(session, REST + path, params=params)
        body = resp.json() if resp is not None else {"code": "404", "data": []}
        time.sleep(pause)
        if str(body.get("code")) == "0":
            return body.get("data") or []
        if str(body.get("code")) == "50011":           # quá giới hạn tần suất
            time.sleep(2 * attempt)
            continue
        raise RuntimeError(f"OKX {path} {params} -> {body.get('code')}: {body.get('msg')}")
    raise RuntimeError(f"OKX {path}: quá giới hạn tần suất sau 5 lần")


def fetch_rest_candles(session: requests.Session, base: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Nến 1m [start_ms, end_ms] qua history-candles (phân trang lùi từ end_ms; giới hạn 20 request/2s)."""
    rows, after = [], end_ms + MINUTE_MS
    while after > start_ms:
        data = _okx_get(session, "/api/v5/market/history-candles", {"instId": inst(base), "bar": "1m", "after": after, "limit": 100}, 0.11)
        if not data:
            break
        rows += data
        after = min(int(r[0]) for r in data)
    if not rows:
        return pd.DataFrame(columns=COLS)
    df = pd.DataFrame({"open_time": [int(r[0]) for r in rows], "open": [float(r[1]) for r in rows], "high": [float(r[2]) for r in rows],
                       "low": [float(r[3]) for r in rows], "close": [float(r[4]) for r in rows], "volume": [float(r[7]) for r in rows],
                       "confirm": [str(r[8]) for r in rows]})
    df = df[(df["confirm"] == "1") & (df["open_time"] >= start_ms) & (df["open_time"] <= end_ms)]
    return df.drop(columns=["confirm"]).reset_index(drop=True)


def _hk_days(start_ms: int, end_ms: int) -> List[date]:
    """Các ngày (giờ HK) của file CDN phủ [start_ms, end_ms]."""
    d0 = datetime.fromtimestamp((start_ms + HK_OFFSET_MS) / 1000, timezone.utc).date()
    d1 = datetime.fromtimestamp((end_ms + HK_OFFSET_MS) / 1000, timezone.utc).date()
    return [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]


def _hk_day_range(d: date) -> Tuple[int, int]:
    t0 = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000) - HK_OFFSET_MS
    return t0, t0 + DAY_MS - MINUTE_MS


def crawl_candles(session: requests.Session, base: str, start_ms: int, end_ms: int, cache_dir: str, workers: int
                  ) -> Tuple[pd.DataFrame, Dict, List[str]]:
    days = _hk_days(start_ms, end_ms)
    with ThreadPoolExecutor(max(1, workers)) as ex:
        raws = list(ex.map(lambda d: fetch_day_zip(session, "candlesticks", base, d, cache_dir), days))
    frames, missing = [], []
    for d, raw in zip(days, raws):
        if raw is None:
            missing.append(d)
        else:
            frames.append(parse_candles_csv(raw, base))
    stats = {"daily_files": len(frames), "rest_days": len(missing), "rest_rows": 0}
    log(f"[candles] {base} file ngày={len(frames)} thiếu={len(missing)} -> REST")
    issues = []
    for d in missing:
        lo, hi = _hk_day_range(d)
        rest = fetch_rest_candles(session, base, max(lo, start_ms), min(hi, end_ms))
        stats["rest_rows"] += len(rest)
        if not rest.empty:
            frames.append(rest)
        elif d < days[-1]:
            issues.append(f"không có nến ngày {d.isoformat()} (HK)")
    if not frames:
        return pd.DataFrame(columns=COLS), stats, issues + ["không có dữ liệu"]
    df = pd.concat(frames, ignore_index=True)
    df = df[(df["open_time"] >= start_ms) & (df["open_time"] <= end_ms)]
    df = df.drop_duplicates("open_time", keep="last").sort_values("open_time").reset_index(drop=True)
    misaligned = int((df["open_time"] % MINUTE_MS != 0).sum())
    if misaligned:
        issues.append(f"{misaligned} nến không thẳng mốc phút")
    return df, stats, issues


def _gaps(times: np.ndarray, start_ms: int, end_ms: int) -> List[Tuple[int, int]]:
    """Các khoảng (lo, hi) trong [start_ms, end_ms] không có mốc funding OKX (hai mốc liền nhau cách > FUNDING_GAP_MS)."""
    if not len(times):
        return [(start_ms, end_ms)]
    out = []
    if times[0] - start_ms > FUNDING_GAP_MS:
        out.append((start_ms, int(times[0]) - HOUR_MS))
    for a, b in zip(times[:-1], times[1:]):
        if b - a > FUNDING_GAP_MS:
            out.append((int(a) + HOUR_MS, int(b) - HOUR_MS))
    if end_ms - times[-1] > FUNDING_GAP_MS:
        out.append((int(times[-1]) + HOUR_MS, end_ms))
    return out


def okx_crawl_funding(session: requests.Session, base: str, start_ms: int, end_ms: int, cache_dir: str, workers: int,
                  binance_funding: Optional[str]) -> Tuple[pd.DataFrame, Dict, List[str]]:
    days = _hk_days(start_ms, end_ms)
    with ThreadPoolExecutor(max(1, workers)) as ex:
        raws = list(ex.map(lambda d: fetch_day_zip(session, "swaprate", base, d, cache_dir), days))
    arch = [parse_swaprate_csv(r) for r in raws if r is not None]
    arch_df = pd.concat(arch, ignore_index=True) if arch else pd.DataFrame(columns=["funding_time", "rate"])
    rest_rows, after = [], None
    while True:
        p = {"instId": inst(base), "limit": 100}
        if after:
            p["after"] = after
        data = _okx_get(session, "/api/v5/public/funding-rate-history", p, 0.21)
        if not data:
            break
        rest_rows += [(int(r["fundingTime"]), float(r.get("realizedRate") or r["fundingRate"])) for r in data]
        after = min(int(r["fundingTime"]) for r in data)
        if after <= start_ms:
            break
    rest_df = pd.DataFrame(rest_rows, columns=["funding_time", "rate"])
    okx = pd.concat([f for f in (arch_df.assign(src="okx_archive"), rest_df.assign(src="okx_rest")) if len(f)]
                    or [pd.DataFrame(columns=["funding_time", "rate", "src"])], ignore_index=True)
    okx = okx[(okx["funding_time"] >= start_ms) & (okx["funding_time"] <= end_ms)]
    okx = okx.drop_duplicates("funding_time", keep="last").sort_values("funding_time").reset_index(drop=True)
    gaps = _gaps(okx["funding_time"].to_numpy(), start_ms, end_ms)
    issues, proxy = [], pd.DataFrame(columns=["funding_time", "rate"])
    if gaps:
        bf = None
        if binance_funding and os.path.exists(binance_funding):
            bf = pd.read_pickle(binance_funding)[["funding_time", "rate"]]
        else:                                          # chưa có dữ liệu Binance của mã này: tải funding Binance USDT-M (file tháng + REST)
            lo0 = min(lo for lo, _ in gaps)
            got, b_issues = crawl_funding(session, f"{base}USDT", lo0, end_ms, DEFAULT_CACHE_DIR)
            bf = got[["funding_time", "rate"]] if len(got) else None
            issues += [f"funding Binance (proxy): {x}" for x in b_issues if "không có funding" in x]
        if bf is not None:
            mask = np.zeros(len(bf), dtype=bool)
            for lo, hi in gaps:
                mask |= bf["funding_time"].between(lo, hi).to_numpy()
            proxy = bf[mask]
        else:
            issues.append(f"thiếu funding cho {len(gaps)} khoảng và không có funding Binance để làm proxy")
    df = pd.concat([f for f in (okx, proxy.assign(src="binance_proxy")) if len(f)] or [okx], ignore_index=True)
    df = df.drop_duplicates("funding_time", keep="first").sort_values("funding_time").reset_index(drop=True)
    sources = df["src"].value_counts().to_dict()
    meta = {"sources": {k: int(v) for k, v in sources.items()},
            "proxy_ranges": [[int(lo), int(hi)] for lo, hi in gaps] if len(proxy) else [],
            "archive_days": len(arch)}
    log(f"[funding] {base} {meta['sources']} khoảng proxy={len(meta['proxy_ranges'])}")
    out = pd.DataFrame({"funding_time": df["funding_time"].astype("int64"), "interval_h": np.nan, "rate": df["rate"].astype(float)})
    return out, meta, issues


def okx_crawl(args) -> List[Dict]:
    if not args.output_dir:
        from backend.crawl.store import exchange_root
        args.output_dir = os.path.join(exchange_root("okx"), "cex")
    from backend.crawl.store import DATA_HOME
    end_ms = int(time.time() * 1000) // MINUTE_MS * MINUTE_MS - MINUTE_MS if not args.end_ts else int(args.end_ts)
    start_ms = (end_ms - int(args.years * 365.25 * DAY_MS)) // MINUTE_MS * MINUTE_MS
    session = requests.Session()
    session.headers.update({"User-Agent": "nora-research/1.0"})
    summaries = []
    for base in [s.strip().upper() for s in as_list(args.symbols) if s.strip()]:
        log(f"[asset] {inst(base)} {datetime.fromtimestamp(start_ms / 1000, timezone.utc):%Y-%m-%d} -> "
            f"{datetime.fromtimestamp(end_ms / 1000, timezone.utc):%Y-%m-%d %H:%M}")
        df, stats, issues = crawl_candles(session, base, start_ms, end_ms, args.cache_dir, args.workers)
        if df.empty:
            log(f"[skip] {base}: không có dữ liệu ({issues})")
            continue
        bpath = os.path.join(DATA_HOME, "binance", "cex", base, "perp", "funding.pkl")
        funding, fmeta, f_issues = okx_crawl_funding(session, base, start_ms, end_ms, args.cache_dir, args.workers, bpath)
        issues += f_issues
        extra = {
            "venue": "cex", "exchange": "okx_swap", "market": "perp", "base_symbol": base, "market_symbol": inst(base),
            "volume_unit": "quote_usdt", "source_files": stats, "checksums_verified": False, "official_api": True, "crawl_issues": issues,
            "funding": {"file": "funding.pkl", "rows": int(len(funding)),
                        "start_ts": int(funding["funding_time"].min()) if len(funding) else None,
                        "end_ts": int(funding["funding_time"].max()) if len(funding) else None,
                        "mean_rate": float(funding["rate"].mean()) if len(funding) else None, **fmeta},
        }
        out_dir = os.path.join(args.output_dir, base)
        manifest = save_resampled_dataset(symbol="perp", output_dir=out_dir, df_1m_raw=df, pool_address=f"okx:perp:{inst(base)}",
                                          source="okx_swap", synthetic=False, crawl_ok=not issues, requested_start_ts=start_ms,
                                          requested_end_ts=end_ms, extra_meta=extra)
        funding.to_pickle(os.path.join(out_dir, "perp", "funding.pkl"))
        manifest["symbol"] = f"{base}@perp"
        with open(os.path.join(out_dir, "perp", "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
        log(f"[manifest] {base} rows_1m={manifest['rows']['1m']} coverage_days={manifest['coverage_days']} "
            f"filled={manifest['filled_ratio_1m']:.4f} crawl_ok={manifest['crawl_ok']} files={stats}")
        summaries.append(manifest)
    log("[done] OKX swap crawl finished.")
    return summaries


def okx_run_job(params=None) -> List[Dict]:
    """Crawl theo `params` (khoá: symbols, years, end_ts, output_dir, cache_dir, workers) -> báo cáo từng tài sản."""
    a = options({"symbols": "", "years": 3.0, "end_ts": None, "output_dir": None, "cache_dir": OKX_DEFAULT_CACHE_DIR, "workers": 8}, params)
    if not as_list(a.symbols):
        raise ValueError("cần symbols")
    out = okx_crawl(a)
    write_job_result({"assets": out})
    return out
