"""Crawl nến 1m + funding OKX USDT-SWAP (sàn triển khai của Nora) nhiều năm -> 1m.pkl + các khung resample + funding.pkl + manifest.json.

Nguồn nến (theo thứ tự):
1. static.okx.com/cdn/okex/traderecords/candlesticks/daily — file ZIP CHÍNH THỨC theo NGÀY (ngày giờ Hồng Kông, UTC+8: file "D" phủ
   D-1 16:00Z -> D 15:59Z), cột instrument_name,open,high,low,close,vol,vol_ccy,vol_quote,open_time,confirm.
2. REST /api/v5/market/history-candles (bar 1m, 100 nến/lần, phân trang lùi) — ngày chưa phát hành (thường hôm nay) hoặc file thiếu.
volume ghi vào pkl = vol_quote / volCcyQuote (USDT) — cùng đơn vị với dữ liệu Binance (quote) và DEX.

Nguồn funding (theo thứ tự, mỗi mốc chỉ lấy một nguồn):
1. static.okx.com/.../swaprate/daily — file ngày chính thức (real_funding_rate = funding đã thanh toán); OKX ngừng phát hành từ ~09/2025.
2. REST /api/v5/public/funding-rate-history (realizedRate) — chỉ ~3 tháng gần nhất.
3. Khoảng trống còn lại: PROXY = funding Binance USDT-M cùng mã (data/binance/cex/<SYM>/perp/funding.pkl) — ghi rõ trong manifest
   (funding.sources, funding.proxy_ranges). Funding hai sàn tương quan cao nhưng không trùng: kết quả backtest trong khoảng proxy là xấp xỉ.

Dữ liệu từ API chính thức của sàn (không có file checksum như data.binance.vision) -> manifest official_api=True, checksums_verified=False.

Job API `data_crawl_okx` (POST /api/data/crawl exchange=okx -> api/jobs/runner.py -> run_job): params symbols, years, end_ts, output_dir
(router đặt data_staging/), cache_dir, workers. Sau đó POST /api/data/promote đưa tài sản qua quality gate vào data/okx/cex/.
"""
import io
import json
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from backend.core.data.crawler import _http_get, log
from backend.core.data.resampler import save_resampled_dataset
from backend.utils.jobs import as_list, options, write_job_result

NORA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CDN = "https://static.okx.com/cdn/okex/traderecords"
REST = "https://www.okx.com"
MINUTE_MS, HOUR_MS, DAY_MS = 60_000, 3_600_000, 86_400_000
HK_OFFSET_MS = 8 * HOUR_MS                 # ngày của file CDN theo giờ Hồng Kông
FUNDING_GAP_MS = 16 * HOUR_MS              # hai mốc funding OKX cách nhau hơn mức này -> khoảng trống (chu kỳ chuẩn 8h)
DEFAULT_CACHE_DIR = os.environ.get("NORA_OKX_CACHE_DIR") or os.path.join(os.path.dirname(NORA_DIR), "data", "cache", "okx")
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


def crawl_funding(session: requests.Session, base: str, start_ms: int, end_ms: int, cache_dir: str, workers: int,
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
            from backend.core.data.crawler import DEFAULT_CACHE_DIR, crawl_funding as binance_funding_hist
            lo0 = min(lo for lo, _ in gaps)
            got, b_issues = binance_funding_hist(session, f"{base}USDT", lo0, end_ms, DEFAULT_CACHE_DIR)
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


def crawl(args) -> List[Dict]:
    if not args.output_dir:
        from backend.db.data_layout import exchange_root
        args.output_dir = os.path.join(exchange_root("okx"), "cex")
    from backend.db.data_layout import DATA_HOME
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
        funding, fmeta, f_issues = crawl_funding(session, base, start_ms, end_ms, args.cache_dir, args.workers, bpath)
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


def run_job(params=None) -> List[Dict]:
    """Crawl theo `params` (khoá: symbols, years, end_ts, output_dir, cache_dir, workers) -> báo cáo từng tài sản."""
    a = options({"symbols": "", "years": 3.0, "end_ts": None, "output_dir": None, "cache_dir": DEFAULT_CACHE_DIR, "workers": 8}, params)
    if not as_list(a.symbols):
        raise ValueError("cần symbols")
    out = crawl(a)
    write_job_result({"assets": out})
    return out
