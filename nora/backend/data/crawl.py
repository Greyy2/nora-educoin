"""Kéo dữ liệu về hệ thống: tải nến 1m OKX perp (CDN zip theo ngày + REST bù), chuẩn hoá, kiểm định, ghi ParquetDataCatalog + manifest.

- Chuẩn hoá: cột chuẩn, open_time ms, bỏ trùng/hỏng, KHỐI LƯỢNG ĐỔI SANG BASE COIN (OKX CSV/REST cho volume theo USDT; catalog lưu base coin như bản dựng ban đầu:
  volume_quote / close), chỉ nến THẬT (không bao giờ ghi nến điền).
- Kiểm định MỘT định nghĩa: `evaluate_data_quality` chạy lúc cập nhật và ghi verdict vào manifest (catalog/_manifest/<BASE>.json, khoá "quality");
  `data.require_data_ok` chỉ ĐỌC verdict đó.
- Chiều import: module này -> backend.data.data (ngược lại thì không). Ghi nến qua backend.nautilus.catalog.write_bars.
"""
from __future__ import annotations

import io
import json
import logging
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from backend.data import data as D
from backend.data.data import DAY_MS, HOUR_MS, MINUTE_MS
from backend.models.storage import as_list, data_home, write_json_atomic

logger = logging.getLogger("nora.data.crawl")

CDN = "https://static.okx.com/cdn/okex/traderecords"
REST = "https://www.okx.com"
HK_OFFSET_MS = 8 * HOUR_MS
COLS = ["open_time", "open", "high", "low", "close", "volume"]


def inst(base: str) -> str:
    return f"{base}-USDT-SWAP"


def _day_tag(d: date) -> Tuple[str, str]:
    return d.strftime("%Y%m%d"), d.isoformat()


def _http_get(session: requests.Session, url: str, retries: int = 5, timeout: int = 60, **kwargs) -> Optional[requests.Response]:
    headers = dict(kwargs.pop("headers", None) or {})
    if "User-Agent" not in headers:
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    kwargs["headers"] = headers
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=timeout, **kwargs)
            if resp.status_code == 404:
                return None
            if resp.status_code in (418, 429) or resp.status_code >= 500:
                wait = min(60, 5 * attempt)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException:
            if attempt == retries:
                raise
            time.sleep(3 * attempt)
    return None


def fetch_day_zip(session: requests.Session, kind: str, base: str, d: date, cache_dir: str) -> Optional[bytes]:
    compact, iso = _day_tag(d)
    name = f"{inst(base)}-{kind}-{iso}.zip"
    path = os.path.join(cache_dir, kind, inst(base), name)
    miss = path + ".404"
    if os.path.exists(path):
        raw = open(path, "rb").read()
    elif os.path.exists(miss) and d < datetime.now(timezone.utc).date() - timedelta(days=3):
        return None
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
    out = pd.DataFrame({
        "open_time": pd.to_numeric(df["open_time"], errors="coerce"),
        "open": pd.to_numeric(df["open"], errors="coerce"),
        "high": pd.to_numeric(df["high"], errors="coerce"),
        "low": pd.to_numeric(df["low"], errors="coerce"),
        "close": pd.to_numeric(df["close"], errors="coerce"),
        "volume": pd.to_numeric(df["vol_quote"], errors="coerce"),
    }).dropna()
    out["open_time"] = out["open_time"].astype("int64")
    return out.reset_index(drop=True)


def _okx_get(session: requests.Session, path: str, params: Dict, pause: float = 0.11) -> List:
    for attempt in range(1, 6):
        resp = _http_get(session, REST + path, params=params)
        body = resp.json() if resp is not None else {"code": "404", "data": []}
        time.sleep(pause)
        if str(body.get("code")) == "0":
            return body.get("data") or []
        if str(body.get("code")) == "50011":
            time.sleep(2 * attempt)
            continue
        raise RuntimeError(f"OKX {path} -> {body.get('code')}: {body.get('msg')}")
    return []


def fetch_rest_candles(session: requests.Session, base: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    rows, after = [], end_ms + MINUTE_MS
    while after > start_ms:
        data = _okx_get(session, "/api/v5/market/history-candles", {"instId": inst(base), "bar": "1m", "after": after, "limit": 100}, 0.11)
        if not data:
            break
        rows += data
        after = min(int(r[0]) for r in data)
    if not rows:
        return pd.DataFrame(columns=COLS)
    df = pd.DataFrame({
        "open_time": [int(r[0]) for r in rows],
        "open": [float(r[1]) for r in rows],
        "high": [float(r[2]) for r in rows],
        "low": [float(r[3]) for r in rows],
        "close": [float(r[4]) for r in rows],
        "volume": [float(r[7]) for r in rows],
        "confirm": [str(r[8]) for r in rows],
    })
    df = df[(df["confirm"] == "1") & (df["open_time"] >= start_ms) & (df["open_time"] <= end_ms)]
    return df.drop(columns=["confirm"]).reset_index(drop=True)


def _hk_days(start_ms: int, end_ms: int) -> List[date]:
    d0 = datetime.fromtimestamp((start_ms + HK_OFFSET_MS) / 1000, timezone.utc).date()
    d1 = datetime.fromtimestamp((end_ms + HK_OFFSET_MS) / 1000, timezone.utc).date()
    return [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]


def _hk_day_range(d: date) -> Tuple[int, int]:
    t0 = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000) - HK_OFFSET_MS
    return t0, t0 + DAY_MS - MINUTE_MS


def crawl_candles(
    session: requests.Session,
    base: str,
    start_ms: int,
    end_ms: int,
    cache_dir: str,
    workers: int = 4,
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
    return df, stats, issues


# ══════════════════════════════════════════════════════════════════════════
# CHUẨN HOÁ VÀ CẬP NHẬT CATALOG
# ══════════════════════════════════════════════════════════════════════════

def normalize_candles(df: pd.DataFrame, after_open_ms: Optional[int] = None) -> pd.DataFrame:
    """Nến thô OKX (volume theo USDT) -> nến chuẩn catalog: bỏ NaN/trùng/hỏng (giá <= 0, high < low, volume < 0), chỉ lấy open_time > after_open_ms,
    sắp theo thời gian, volume đổi sang base coin (= volume_usdt / close)."""
    if df.empty:
        return pd.DataFrame(columns=COLS)
    out = df[COLS].dropna().copy()
    out["open_time"] = out["open_time"].astype("int64")
    out = out.drop_duplicates("open_time", keep="last").sort_values("open_time")
    ok = (out[["open", "high", "low", "close"]] > 0).all(axis=1) & (out["high"] >= out["low"]) & (out["volume"] >= 0)
    out = out[ok]
    if after_open_ms is not None:
        out = out[out["open_time"] > int(after_open_ms)]
    out["volume"] = out["volume"] / out["close"]
    return out.reset_index(drop=True)


def _manifest_path(base: str, data_root: Optional[str] = None) -> str:
    return os.path.join(D.default_catalog_path(data_root), "_manifest", f"{base}.json")


def _write_manifest(base: str, manifest: Dict[str, Any], data_root: Optional[str] = None) -> None:
    path = _manifest_path(base, data_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_json_atomic(path, manifest)


def _last_open_ms(m: Optional[Dict[str, Any]]) -> Optional[int]:
    """open_time (ms) của nến cuối theo manifest (end_ts_ns = giờ ĐÓNG nến cuối = open + 1 phút)."""
    if not m:
        return None
    if m.get("end_ts_ns"):
        return int(m["end_ts_ns"]) // 1_000_000 - MINUTE_MS
    return int(m["end_ts"]) if m.get("end_ts") else None



# ══════════════════════════════════════════════════════════════════════════
# KIỂM ĐỊNH CHẤT LƯỢNG (MỘT ĐỊNH NGHĨA) VÀ GHI VERDICT VÀO MANIFEST
# ══════════════════════════════════════════════════════════════════════════

class DataQualityStatus:
    APPROVED = "APPROVED"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    NEEDS_MORE_DATA = "NEEDS_MORE_DATA"


MAX_FILLED_RATIO_1M = 0.60     # tỉ lệ phút thiếu (sẽ bị điền khi dựng nến cho tín hiệu) tối đa
MIN_COVERAGE_DAYS = 30.0
JUMP_WARN = 0.50               # bước nhảy giá 1 phút > 50%: sự kiện thật của sàn chính thức -> cảnh báo, không chặn


def _verdict(symbol: str, status: str, score: float, issues: List[str], metrics: Dict[str, Any]) -> Dict[str, Any]:
    return {"symbol": symbol, "status": status, "quality_score": score, "issues": issues, "metrics": metrics}


def evaluate_data_quality(symbol: str, data_root: Optional[str] = None) -> Dict[str, Any]:
    """Kiểm định nến 1m THẬT của catalog: catalog+manifest tồn tại, phủ >= 30 ngày, giá > 0, không trùng open_time, tỉ lệ phút thiếu <= 60%,
    bước nhảy giá > 50%/phút (cảnh báo). Đọc toàn bộ nến 1m một lần (chỉ chạy lúc cập nhật, kết quả ghi vào manifest)."""
    norm = D.normalize_symbol(symbol)
    base = D.base_name(symbol)
    B = DataQualityStatus
    m = D.read_manifest(base, data_root)
    if m is None:
        return _verdict(symbol, B.BLOCKED, 0.0, [f"Chặn chạy: {symbol} chưa có dữ liệu trong catalog"], {"total_bars": 0})
    start_ts, end_ts = m.get("start_ts"), m.get("end_ts")
    if not start_ts or not end_ts:
        return _verdict(symbol, B.BLOCKED, 0.0, [f"Chặn chạy: {symbol} thiếu mốc thời gian start_ts / end_ts"], {"total_bars": 0})
    coverage_days = (end_ts - start_ts + MINUTE_MS) / DAY_MS      # số phút phủ (đầu và cuối cùng tính) quy ra ngày
    if coverage_days < MIN_COVERAGE_DAYS:
        return _verdict(symbol, B.NEEDS_MORE_DATA, 30.0, [f"Độ phủ {coverage_days:.1f} ngày < {MIN_COVERAGE_DAYS:.0f} ngày tối thiểu"],
                        {"coverage_days": coverage_days})
    arr = D.read_1m(norm, 0, 2**62, data_root)
    t = arr["t"]
    if len(t) == 0:
        return _verdict(symbol, B.BLOCKED, 0.0, [f"{symbol}: không đọc được nến 1m từ catalog"], {"total_bars": 0})
    if (arr["c"] <= 0).any() or (arr["o"] <= 0).any() or (arr["h"] < arr["l"]).any():
        return _verdict(symbol, B.BLOCKED, 0.0, [f"{symbol}: phát hiện giá <= 0 hoặc high < low"], {"total_bars": int(len(t))})
    if len(t) > 1 and bool((np.diff(t) == 0).any()):
        return _verdict(symbol, B.BLOCKED, 0.0, [f"Chặn chạy: phát hiện open_time trùng lặp trong nến 1m của {symbol}"], {"total_bars": int(len(t))})
    expected = int((t[-1] - t[0]) // MINUTE_MS) + 1
    filled_ratio = 1.0 - len(t) / expected
    if filled_ratio > MAX_FILLED_RATIO_1M:
        return _verdict(symbol, B.BLOCKED, 10.0,
                        [f"Chặn chạy: tỉ lệ nến thiếu (filled_ratio={filled_ratio*100:.1f}%) vượt ngưỡng {MAX_FILLED_RATIO_1M*100:.0f}%"],
                        {"filled_ratio": filled_ratio})
    metrics: Dict[str, Any] = {"coverage_days": coverage_days, "total_bars": int(len(t)), "filled_ratio": filled_ratio}
    issues: List[str] = []
    jump = np.abs(np.diff(arr["c"]) / arr["c"][:-1]) > JUMP_WARN
    if jump.any():
        times = [datetime.fromtimestamp(int(x) / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M") + "Z" for x in t[1:][jump]]
        issues.append(f"Cảnh báo: {len(times)} phút có biến động > 50% (dữ liệu OKX chính thức, giữ lại như sự kiện thật): "
                      f"{', '.join(times[:5])}{' …' if len(times) > 5 else ''}")
        return _verdict(symbol, B.WARNING, 90.0, issues, metrics)
    return _verdict(symbol, B.APPROVED, 100.0, issues, metrics)


def stamp_quality(symbol: str, data_root: Optional[str] = None) -> Dict[str, Any]:
    """Tính verdict và ghi vào manifest (khoá "quality", kèm dấu vân tay catalog + thời điểm kiểm). Chỉ ghi file manifest json."""
    base = D.base_name(symbol)
    verdict = evaluate_data_quality(symbol, data_root)
    m = D.read_manifest(base, data_root)
    if m is not None:
        m = {k: v for k, v in m.items() if not (k in ("start_ts", "end_ts") and f"{k}_ns" in m)}   # start_ts/end_ts suy ra từ *_ns khi đọc, không lưu
        m["quality"] = {**verdict, "catalog_digest": D.catalog_digest([symbol], data_root), "evaluated_at": int(time.time())}
        _write_manifest(base, m, data_root)
    return verdict


def refresh_quality(symbols: Optional[List[str]] = None, data_root: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Đóng dấu lại verdict chất lượng vào manifest hiện có của các symbol (mặc định cả rổ trong catalog). Không đụng nến."""
    names = [D.base_name(s) for s in symbols] if symbols else D.default_universe()
    return {n: stamp_quality(n, data_root) for n in names}



def fetch_instruments(symbols: Optional[List[str]] = None, data_root: Optional[str] = None) -> Dict[str, Any]:
    """Cập nhật instruments.json từ OKX REST API. Nếu symbols không truyền -> hợp của 10 coin gốc + coin trong universe_scan.json.
    Merge vào file hiện có, giữ nguyên các mục cũ; thiếu spec thì báo lỗi, không bù số."""
    out_dir = os.path.dirname(D.default_catalog_path(data_root))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "instruments.json")

    existing: Dict[str, Any] = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                old_res = json.load(fh)
            existing = old_res.get("instruments") or {}
        except Exception:
            existing = {}

    target_bases = set(D.base_name(s) for s in symbols) if symbols else (set(D.UNIVERSE_BASES) | set(scan_universe_bases(data_root)))

    session = requests.Session()
    data = _okx_get(session, "/api/v5/public/instruments", {"instType": "SWAP"}, 0.2)
    spec_map: Dict[str, Any] = dict(existing)
    for item in data:
        inst_id = item.get("instId")
        base = inst_id.split("-")[0] if inst_id else ""
        if inst_id != inst(base) or base not in target_bases:
            continue
        tick, lot = str(item["tickSz"]), str(item["lotSz"])
        spec_map[inst_id] = {
            "instId": inst_id,
            "base_symbol": base,
            "tickSz": tick,
            "lotSz": lot,
            "ctVal": str(item["ctVal"]),
            "minSz": str(item.get("minSz", lot)),
            "lever": int(float(item.get("lever") or 0)),
            "price_precision": len(tick.split(".")[1]) if "." in tick else 0,
            "size_precision": len(lot.split(".")[1]) if "." in lot else 0,
            "maker_fee": 0.0002,
            "taker_fee": 0.0005,
            "margin_init": 0.02,
            "margin_maint": 0.01,
        }
    missing = [inst(b) for b in target_bases if inst(b) not in spec_map]
    if missing:
        raise RuntimeError(f"OKX không trả spec cho {missing}")
    res = {"fetched_at": int(time.time()), "exchange": "okx", "instruments": spec_map}
    write_json_atomic(path, res)
    return res


def commit_candles(symbol: str, df: pd.DataFrame, data_root: Optional[str] = None, spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Ghi nến ĐÃ chuẩn hoá (open_time ms, OHLC, volume base coin; mới hơn nến cuối của catalog) vào catalog, cập nhật manifest {rows_1m, start/end,
    volume_unit} và đóng dấu verdict chất lượng. `spec` thay spec instruments.json (dữ liệu thử)."""
    from backend.nautilus.catalog import write_bars

    norm = D.normalize_symbol(symbol)
    base = D.base_name(symbol)
    m = D.read_manifest(base, data_root)
    if df.empty:
        return {"symbol": norm, "status": "NO_NEW_DATA", "new_rows": 0}
    written = write_bars(norm, df, D.default_catalog_path(data_root), spec)
    first_ns = (int(df["open_time"].iloc[0]) + MINUTE_MS) * 1_000_000
    last_ns = (int(df["open_time"].iloc[-1]) + MINUTE_MS) * 1_000_000
    new_m = {
        "symbol": norm,
        "base_symbol": base,
        "updated_at": int(time.time()),
        "rows_1m": int((m or {}).get("rows_1m") or 0) + written,
        "start_ts_ns": int((m or {}).get("start_ts_ns") or first_ns),
        "end_ts_ns": last_ns,
        "volume_unit": "base_coin",
    }
    _write_manifest(base, new_m, data_root)
    D.clear_caches()
    verdict = stamp_quality(base, data_root)
    return {"symbol": norm, "status": "UPDATED", "new_rows": written, "quality": verdict["status"]}


def append_to_catalog(symbol: str, df_new: pd.DataFrame, data_root: Optional[str] = None) -> Dict[str, Any]:
    """Nến thô OKX -> chuẩn hoá, bỏ nến đã có trong catalog (open_time <= nến cuối) -> commit_candles. Chạy lại với cùng dữ liệu không ghi đôi."""
    df = normalize_candles(df_new, _last_open_ms(D.read_manifest(D.base_name(symbol), data_root)))
    return commit_candles(symbol, df, data_root)


def update_catalog(
    symbol: str,
    end_ms: Optional[int] = None,
    data_root: Optional[str] = None,
    start_ms: Optional[int] = None,
    days: Optional[int] = None,
) -> Dict[str, Any]:
    """Cập nhật nến 1m từ nến cuối trong manifest tới end_ms (mặc định: hiện tại - 2 phút); chưa có dữ liệu thì lấy days ngày gần nhất (mặc định 30 ngày, hoặc start_ms)."""
    base = D.base_name(symbol)
    norm = D.normalize_symbol(symbol)
    allowed_bases = set(D.UNIVERSE_BASES) | set(scan_universe_bases(data_root))
    if base not in allowed_bases:
        raise ValueError(f"{symbol}: không thuộc rổ OKX perp của Nora ({', '.join(sorted(allowed_bases))})")
    last = _last_open_ms(D.read_manifest(base, data_root))
    target_end = int(end_ms) if end_ms else int(time.time() * 1000) - 2 * MINUTE_MS
    default_lookback_days = days if days is not None else 30
    if start_ms is not None and last is None:
        calc_start = int(start_ms)
    elif last is not None:
        calc_start = last + MINUTE_MS
    else:
        calc_start = target_end - default_lookback_days * DAY_MS
    if calc_start >= target_end:
        return {"symbol": norm, "status": "UP_TO_DATE", "new_rows": 0}
    session = requests.Session()
    cache_dir = os.path.join(data_home(), "cache", "okx")
    df_new, _, issues = crawl_candles(session, base, calc_start, target_end, cache_dir)
    res = append_to_catalog(base, df_new, data_root)
    if issues:
        res["issues"] = issues
    return res


def run_job(params: Dict[str, Any]) -> Dict[str, Any]:
    """Job `data_update`: cập nhật catalog cho các symbol (mặc định cả rổ)."""
    sym_list = as_list(params.get("symbols") or D.default_universe())
    results: Dict[str, Any] = {}
    for s in sym_list:
        try:
            results[s] = update_catalog(s)
        except Exception as exc:
            results[s] = {"error": str(exc)}
    return {"results": results}


# ══════════════════════════════════════════════════════════════════════════
# UNIVERSE SCAN (100 CẶP OKX USDT-SWAP)
# ══════════════════════════════════════════════════════════════════════════

NON_CRYPTO_BLACKLIST = {
    "SNDK", "SOXL", "SKHYNIX", "XAU", "MU", "CL", "SPCX", "KORU", "CT",
    "TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "BNO", "UNG",
}
MAX_LIST_TIME = 1743465599000  # 2025-03-31 23:59:59 UTC (niêm yết <= 2025-03)


def scan_universe_path(data_root: Optional[str] = None) -> str:
    out_dir = os.path.dirname(D.default_catalog_path(data_root))
    return os.path.join(out_dir, "universe_scan.json")


def load_scan_universe(data_root: Optional[str] = None) -> List[Dict[str, Any]]:
    path = scan_universe_path(data_root)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("coins") or []
    except Exception:
        return []


def scan_universe_bases(data_root: Optional[str] = None) -> List[str]:
    coins = load_scan_universe(data_root)
    return [c["base"] for c in coins if "base" in c]


def select_scan_universe(data_root: Optional[str] = None, max_coins: int = 100) -> Dict[str, Any]:
    """Lọc 100 coin OKX USDT-SWAP tự động từ API OKX -> ghi universe_scan.json.
    Quy tắc:
    - state == "live", instId == "{base}-USDT-SWAP"
    - listTime <= 2025-03 (đảm bảo đủ lịch sử)
    - loại non-crypto / hàng hoá / ETF
    - vol24h_usd >= 1M
    - luôn gồm 10 coin hiện có
    - Top 100 theo volume USD
    - Hạng: A (>=20M), B (5-20M), C (1-5M)
    """
    import json
    session = requests.Session()
    inst_data = _okx_get(session, "/api/v5/public/instruments", {"instType": "SWAP"}, 0.15)
    ticker_data = _okx_get(session, "/api/v5/market/tickers", {"instType": "SWAP"}, 0.15)

    ticker_map = {t["instId"]: t for t in ticker_data if "instId" in t}

    valid_candidates = []
    seen_bases = set()

    for item in inst_data:
        inst_id = item.get("instId", "")
        if not inst_id.endswith("-USDT-SWAP"):
            continue
        parts = inst_id.split("-")
        if len(parts) < 3:
            continue
        base = parts[0].upper()
        if base in seen_bases:
            continue

        if item.get("state") != "live":
            continue

        if base in NON_CRYPTO_BLACKLIST:
            continue
        if str(item.get("instCategory", "1")) != "1":
            continue

        list_time = int(item.get("listTime") or 0)
        is_core_10 = base in D.UNIVERSE_BASES
        if not is_core_10 and list_time > MAX_LIST_TIME:
            continue

        tick_info = ticker_map.get(inst_id)
        if not tick_info:
            continue

        last_px = float(tick_info.get("last") or 0.0)
        vol_ccy = float(tick_info.get("volCcy24h") or 0.0)
        vol24h_usd = vol_ccy * last_px

        if not is_core_10 and vol24h_usd < 1_000_000:
            continue

        grade = "A" if vol24h_usd >= 20_000_000 else "B" if vol24h_usd >= 5_000_000 else "C"

        seen_bases.add(base)
        valid_candidates.append({
            "base": base,
            "inst_id": inst_id,
            "grade": grade,
            "list_time": list_time,
            "vol24h_usd": round(vol24h_usd, 2),
            "ct_val": str(item.get("ctVal", "")),
            "tick_sz": str(item.get("tickSz", "")),
            "lot_sz": str(item.get("lotSz", "")),
            "min_sz": str(item.get("minSz", item.get("lotSz", ""))),
            "lever": int(float(item.get("lever") or 0)),
            "is_core": is_core_10,
        })

    valid_candidates.sort(key=lambda x: x["vol24h_usd"], reverse=True)

    core_candidates = [c for c in valid_candidates if c["is_core"]]
    other_candidates = [c for c in valid_candidates if not c["is_core"]]

    selected = core_candidates + other_candidates[:max(0, max_coins - len(core_candidates))]
    selected.sort(key=lambda x: x["vol24h_usd"], reverse=True)

    for c in selected:
        c.pop("is_core", None)

    res = {
        "generated_at": int(time.time()),
        "rule": "state:live, -USDT-SWAP, listTime<=2025-03, vol>=1M, top 100",
        "total_coins": len(selected),
        "coins": selected,
    }

    path = scan_universe_path(data_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_json_atomic(path, res)

    cnt_a = sum(1 for c in selected if c["grade"] == "A")
    cnt_b = sum(1 for c in selected if c["grade"] == "B")
    cnt_c = sum(1 for c in selected if c["grade"] == "C")
    print(f"[Universe Scan] Đã chọn {len(selected)} coin -> {path}")
    print(f"  Hạng A (>= $20M): {cnt_a} coin")
    print(f"  Hạng B ($5M-$20M): {cnt_b} coin")
    print(f"  Hạng C ($1M-$5M):  {cnt_c} coin")
    return res


def run_scan_crawl(params: Dict[str, Any]) -> Dict[str, Any]:
    """Job `data_scan_crawl`: crawl nến 2 năm cho 100 coin quét từ OKX CDN zip.
    Chạy đa luồng theo coin (3 workers để kiểm soát RAM < 12G nora.slice). Resume được.
    """
    coins = params.get("coins") or scan_universe_bases()
    start_ms = int(params.get("start_ms") or 1728777600000)   # 2024-10-13 00:00:00 UTC (2 năm)
    end_ms = int(params.get("end_ms") or (time.time() * 1000 - 2 * MINUTE_MS))
    workers = min(int(params.get("workers") or 3), 4)
    resume = bool(params.get("resume", True))

    results: Dict[str, Any] = {}
    total = len(coins)
    done_count = 0
    t_start = time.time()

    print(f"[Scan Crawl] Bắt đầu tải {total} coin (từ {start_ms} tới {end_ms}, workers={workers})")

    def _worker(base: str) -> Tuple[str, Dict[str, Any]]:
        if resume:
            m = D.read_manifest(base)
            if m and m.get("quality", {}).get("status") in ("APPROVED", "WARNING") and int(m.get("rows_1m") or 0) >= 900_000:
                return base, {"symbol": base, "status": "ALREADY_EXISTS", "rows_1m": int(m.get("rows_1m") or 0), "quality": m.get("quality", {}).get("status")}
        try:
            res = update_catalog(base, end_ms=end_ms, start_ms=start_ms)
            return base, res
        except Exception as exc:
            return base, {"error": str(exc), "status": "FAILED"}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for base, res in pool.map(_worker, coins):
            done_count += 1
            results[base] = res
            status = res.get("status") or ("FAILED" if "error" in res else "OK")
            q = res.get("quality") or "—"
            elapsed = time.time() - t_start
            eta = (elapsed / done_count) * (total - done_count) if done_count > 0 else 0
            print(f"[{done_count}/{total}] {base}: {status} (quality={q}) - ETA {eta/60:.1f}m")

    summary = {
        "total": total,
        "completed": len(results),
        "approved": sum(1 for r in results.values() if r.get("quality") == "APPROVED"),
        "warning": sum(1 for r in results.values() if r.get("quality") == "WARNING"),
        "failed": sum(1 for r in results.values() if "error" in r),
        "elapsed_s": round(time.time() - t_start, 1),
        "details": results,
    }
    return summary
