"""Kiến trúc thư mục dữ liệu thị trường (market data) — một nơi duy nhất quyết định đường dẫn.

Từ 04/10/2026 dữ liệu tách theo SÀN: nora/data/<sàn>/{cex,dex}/... — okx (sàn triển khai, mặc định) và binance (tham khảo).
Chọn sàn: biến môi trường NORA_EXCHANGE (okx | binance). NORA_LOCAL_DATA_ROOT (test) ghi đè cả gốc.
Cache tính toán (_cache) và kho alpha (alphas) dùng chung, nằm ở nora/data/ (không theo sàn).

    nora/data/<okx|binance>/
    ├── cex/                    # sàn tập trung — nguồn gốc là NẾN (kline) chính thức của sàn
    │   └── <SYM>/              #   vd. BTC/  = spot (exchange, market_symbol ghi trong manifest.json)
    │       └── perp/           #   BTC@perp = USDT-M perpetual: nến 1m... + funding.pkl + manifest.json
    │       ├── 1m.pkl          #   nguồn duy nhất; 5m/15m/1h/4h/24h resample từ 1m
    │       ├── 5m.pkl 15m.pkl 1h.pkl 4h.pkl 24h.pkl
    │       └── manifest.json   #   venue="cex", nguồn, checksum, độ phủ, sha256_1m ...
    ├── dex/                    # sàn phi tập trung (AMM pool) — nguồn gốc là GIAO DỊCH (swap/tick)
    │   └── <SYM>/              #   vd. AERO/ (network, pool_address ghi trong manifest.json)
    │       ├── 1m.pkl ...      #   nến 1m của pool (phút không có swap -> nến điền is_filled=1)
    │       ├── ticks.parquet   #   swap thật (nếu có; khai báo trong manifest["ticks"])
    │       ├── dex_pool.json   #   metadata pool
    │       └── manifest.json   #   venue="dex"
    nora/data/_meta/            # danh sách target crawl, cấu hình nguồn (không phải tài sản)
    nora/data/_cache/           # cache tính toán (research, funnel, job ...), xoá được bất kỳ lúc nào
    nora/data/alphas/           # kho alpha / sổ (book.json ghi data_exchange)

okx/cex/<SYM>/perp: OKX USDT-SWAP (core/data/okx_crawler.py) — nến 1m từ file ngày chính thức + REST; funding OKX, khoảng trống lấp bằng
proxy Binance (manifest.funding.sources / proxy_ranges). binance/cex: Binance USDT-M (core/data/crawler.py), binance/dex: DEX (lịch sử).

Quy ước:
- Thư mục bắt đầu bằng '.' hoặc '_' không phải tài sản.
- Ký hiệu tài sản: "BTC" (nếu duy nhất) hoặc có tiền tố venue "cex:BTC" / "dex:UNI" khi trùng tên.
- Instrument perp: hậu tố "@perp" — "BTC@perp" -> cex/BTC/perp.
- Thư mục phẳng kiểu cũ <root>/<SYM> vẫn đọc được (dùng trong test) nhưng không dùng cho dữ liệu mới.
"""
import os
import re
from typing import Dict, List, Optional, Tuple

VENUES = ("cex", "dex")
INSTRUMENTS = ("perp",)
_PREFIX_RE = re.compile(r"^\s*(cex|dex)\s*[:/]\s*(.+)$", re.IGNORECASE)
_INSTRUMENT_RE = re.compile(r"^(.*?)\s*@\s*(perp)\s*$", re.IGNORECASE)


class AmbiguousSymbolError(ValueError):
    """Cùng một ký hiệu tồn tại ở cả cex/ và dex/ mà không chỉ rõ venue."""


DATA_HOME = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
EXCHANGES = ("okx", "binance")
DEFAULT_EXCHANGE = "okx"


def exchange() -> str:
    """Sàn của dữ liệu thị trường đang dùng (NORA_EXCHANGE, mặc định okx)."""
    ex = (os.environ.get("NORA_EXCHANGE") or DEFAULT_EXCHANGE).strip().lower()
    if ex not in EXCHANGES:
        raise ValueError(f"NORA_EXCHANGE phải là một trong {EXCHANGES}, nhận {ex!r}")
    return ex


def exchange_root(ex: Optional[str] = None) -> str:
    """Gốc dữ liệu của một sàn: nora/data/<ex> (mặc định sàn đang dùng). NORA_LOCAL_DATA_ROOT (NORA_DATA_ROOT giữ để tương thích) ghi đè."""
    env = os.environ.get("NORA_LOCAL_DATA_ROOT") or os.environ.get("NORA_DATA_ROOT")
    return env or os.path.join(DATA_HOME, ex or exchange())


def default_data_root() -> str:
    """Thư mục gốc dữ liệu thị trường của sàn đang dùng."""
    return exchange_root()


def exchange_of(manifest: Optional[dict]) -> str:
    """Sàn của một tài sản theo manifest ("okx_swap" -> okx, "binance_usdm" -> binance); không rõ (DEX...) -> sàn đang dùng."""
    ex = str((manifest or {}).get("exchange") or "").lower()
    return next((e for e in EXCHANGES if ex.startswith(e)), exchange())


def cache_dir(data_root: Optional[str] = None, *parts: str) -> str:
    """Cache tính toán: nora/data/_cache (dùng chung mọi sàn); khi NORA_LOCAL_DATA_ROOT đặt (test) thì nằm dưới gốc đó."""
    env = os.environ.get("NORA_LOCAL_DATA_ROOT") or os.environ.get("NORA_DATA_ROOT")
    path = os.path.join(data_root or env or DATA_HOME, "_cache", *parts)
    os.makedirs(path, exist_ok=True)
    return path


def clean_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "", str(name or "").strip()).upper()


def split_instrument(symbol: str) -> Tuple[str, Optional[str]]:
    """'BTC@perp' -> ('BTC', 'perp'); 'BTC' -> ('BTC', None)."""
    match = _INSTRUMENT_RE.match(str(symbol or "").strip())
    return (match.group(1), match.group(2).lower()) if match else (str(symbol or "").strip(), None)


def parse_symbol(symbol: str) -> Tuple[Optional[str], str]:
    """'cex:btc' -> ('cex', 'BTC'); 'AERO' -> (None, 'AERO'). (Bỏ qua hậu tố @perp.)"""
    raw, _ = split_instrument(symbol)
    match = _PREFIX_RE.match(raw)
    if match:
        return match.group(1).lower(), clean_name(match.group(2))
    return None, clean_name(raw)


def is_asset_dir(path: str) -> bool:
    """Thư mục tài sản = không bắt đầu bằng '.'/'_', không phải thư mục venue, và có manifest.json hoặc .pkl."""
    name = os.path.basename(os.path.normpath(path))
    if not os.path.isdir(path) or name.startswith((".", "_")) or name.lower() in VENUES:
        return False
    try:
        entries = os.listdir(path)
    except OSError:
        return False
    return "manifest.json" in entries or any(e.endswith(".pkl") for e in entries)


def list_assets(data_root: Optional[str] = None) -> List[Dict[str, str]]:
    """Mọi tài sản: [{symbol, venue, path, qualified}]. venue='legacy' cho thư mục phẳng kiểu cũ."""
    root = data_root or default_data_root()
    found: List[Dict[str, str]] = []
    if not os.path.isdir(root):
        return found
    for venue in VENUES:
        vdir = os.path.join(root, venue)
        if os.path.isdir(vdir):
            for name in sorted(os.listdir(vdir)):
                path = os.path.join(vdir, name)
                if is_asset_dir(path):
                    found.append({"symbol": name.upper(), "venue": venue, "path": path})
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if is_asset_dir(path):
            found.append({"symbol": name.upper(), "venue": "legacy", "path": path})

    for venue in VENUES:  # instrument lồng bên trong: cex/<SYM>/perp (thư mục <SYM> có thể không có manifest riêng)
        vdir = os.path.join(root, venue)
        for name in sorted(os.listdir(vdir)) if os.path.isdir(vdir) else []:
            if name.startswith((".", "_")):
                continue
            for inst in INSTRUMENTS:
                sub = os.path.join(vdir, name, inst)
                if os.path.isdir(sub) and "manifest.json" in os.listdir(sub):
                    found.append({"symbol": f"{name.upper()}@{inst}", "venue": venue, "path": sub, "instrument": inst})

    counts: Dict[str, int] = {}
    for item in found:
        counts[item["symbol"]] = counts.get(item["symbol"], 0) + 1
    for item in found:
        ambiguous = counts[item["symbol"]] > 1 and item["venue"] in VENUES
        item["qualified"] = f"{item['venue']}:{item['symbol']}" if ambiguous else item["symbol"]
        item.setdefault("instrument", "spot")
    return found


def resolve_asset_dir(symbol: str, data_root: Optional[str] = None) -> Optional[str]:
    """Thư mục của tài sản đang có; None nếu không tồn tại. Raise nếu trùng tên giữa cex/dex."""
    root = data_root or default_data_root()
    base, instrument = split_instrument(symbol)
    if instrument:
        base_dir = resolve_asset_dir(base, data_root=root)
        if base_dir is None:
            return None
        sub = os.path.join(base_dir, instrument)
        return sub if os.path.isdir(sub) else None
    venue, name = parse_symbol(symbol)
    if not name:
        return None
    if venue:
        path = os.path.join(root, venue, name)
        return path if os.path.isdir(path) else None
    hits = [os.path.join(root, v, name) for v in VENUES if os.path.isdir(os.path.join(root, v, name))]
    if len(hits) > 1:
        raise AmbiguousSymbolError(
            f"'{name}' có ở cả cex/ và dex/ — hãy ghi rõ 'cex:{name}' hoặc 'dex:{name}'."
        )
    if hits:
        return hits[0]
    flat = os.path.join(root, name)
    return flat if os.path.isdir(flat) else None


def asset_dir_for_write(venue: str, symbol: str, data_root: Optional[str] = None) -> str:
    """Thư mục để GHI dữ liệu mới: <root>/<venue>/<SYM> (tạo nếu chưa có)."""
    venue = str(venue or "").lower()
    if venue not in VENUES:
        raise ValueError(f"venue phải là một trong {VENUES}, nhận '{venue}'")
    path = os.path.join(data_root or default_data_root(), venue, clean_name(symbol))
    os.makedirs(path, exist_ok=True)
    return path

