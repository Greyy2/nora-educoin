"""Kho dữ liệu thị trường: layout thư mục (một nơi chọn gốc dữ liệu), đọc/ghi pkl, loader nến, resample, quality gate, promote, LRU, json an toàn.

Nguồn gộp: docs/bmad/p9_review_log.md
"""
import os
import re
import threading
from collections import OrderedDict
import datetime as _dt
import math
import json
import hashlib
import time
import copy
import shutil
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple, Any, Hashable
import numpy as np
import pandas as pd


# ── Layout thư mục dữ liệu ────────────────────────────────────────────────────────────────────
# Kiến trúc thư mục dữ liệu thị trường (market data) — một nơi duy nhất quyết định đường dẫn.
#
# Dữ liệu thị trường tách theo SÀN: nora/data/market/<sàn>/{cex,dex}/... — okx (sàn triển khai, mặc định) và binance (tham khảo).
# Chọn sàn: biến môi trường NORA_EXCHANGE (okx | binance). NORA_LOCAL_DATA_ROOT (test) ghi đè cả gốc.
# Cây đích (market/, alpha/, backtest/, wfa/, carlo/, live/, cache/{process,shared}) và helper đường dẫn: mục "P9.3a" bên dưới.
#
#     nora/data/market/<okx|binance>/
#     ├── cex/                    # sàn tập trung — nguồn gốc là NẾN (kline) chính thức của sàn
#     │   └── <SYM>/              #   vd. BTC/  = spot (exchange, market_symbol ghi trong attrs của pkl)
#     │       └── perp/           #   BTC@perp = USDT-M perpetual: nến 1m... + funding.pkl
#     │       ├── 1m.pkl          #   nguồn duy nhất; 5m/15m/1h/4h/24h resample từ 1m
#     │       ├── 5m.pkl 15m.pkl 1h.pkl 4h.pkl 24h.pkl
#     │                           #   metadata (venue, nguồn, checksum, sha256_1m, digest_1m ...) = df.attrs["nora"] trong MỌI .pkl, xem asset_meta
#     ├── dex/                    # sàn phi tập trung (AMM pool) — nguồn gốc là GIAO DỊCH (swap/tick)
#     │   └── <SYM>/              #   vd. AERO/ (network, pool_address ghi trong attrs của pkl)
#     │       ├── 1m.pkl ...      #   nến 1m của pool (phút không có swap -> nến điền is_filled=1)
#     │       ├── ticks.parquet   #   swap thật (nếu có; khai báo trong attrs của chính parquet: ticks + onchain)
#     nora/data/cache/{process,shared}/   # cache tính toán, xoá được bất kỳ lúc nào
#     nora/data/alpha/            # kho alpha / sổ (book.json ghi data_exchange)
#
# okx/cex/<SYM>/perp: OKX USDT-SWAP (crawl/cex.py) — nến 1m từ file ngày chính thức + REST; funding OKX, khoảng trống lấp bằng
# proxy Binance (manifest.funding.sources / proxy_ranges). okx/dex: pool DEX (GeckoTerminal; không thuộc sàn nào, nằm cùng gốc sàn đang dùng). binance/cex: Binance USDT-M (crawl/cex.py), chỉ tham khảo.
#
# Quy ước:
# - Thư mục bắt đầu bằng '.' hoặc '_' không phải tài sản.
# - Ký hiệu tài sản: "BTC" (nếu duy nhất) hoặc có tiền tố venue "cex:BTC" / "dex:UNI" khi trùng tên.
# - Instrument perp: hậu tố "@perp" — "BTC@perp" -> cex/BTC/perp.
# - Thư mục phẳng kiểu cũ <root>/<SYM> vẫn đọc được (dùng trong test) nhưng không dùng cho dữ liệu mới.
#

VENUES = ("cex", "dex")
INSTRUMENTS = ("perp",)
_PREFIX_RE = re.compile(r"^\s*(cex|dex)\s*[:/]\s*(.+)$", re.IGNORECASE)
_INSTRUMENT_RE = re.compile(r"^(.*?)\s*@\s*(perp)\s*$", re.IGNORECASE)


class AmbiguousSymbolError(ValueError):
    """Cùng một ký hiệu tồn tại ở cả cex/ và dex/ mà không chỉ rõ venue."""


NORA_DATA_ROOT = os.environ.get("NORA_DATA_ROOT", "/home/vmc03/norabt/nora/data")
DATA_DIR = NORA_DATA_ROOT
DAY_MS = 86_400_000
DEFAULT_CAPITAL = 10_000.0
DEFAULT_TRAIN_RATIO = 0.7


def iso_date(ts):
    import datetime
    return datetime.datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d")


EXCHANGES = ("okx", "binance")
DEFAULT_EXCHANGE = "okx"


def exchange() -> str:
    """Sàn của dữ liệu thị trường đang dùng (NORA_EXCHANGE, mặc định okx)."""
    ex = (os.environ.get("NORA_EXCHANGE") or DEFAULT_EXCHANGE).strip().lower()
    if ex not in EXCHANGES:
        raise ValueError(f"NORA_EXCHANGE phải là một trong {EXCHANGES}, nhận {ex!r}")
    return ex


def exchange_root(ex: Optional[str] = None) -> str:
    """Gốc dữ liệu của một sàn (mặc định sàn đang dùng) = market_root(ex): market/<ex>; NORA_LOCAL_DATA_ROOT ghi đè (chế độ phẳng)."""
    return market_root(ex)


def default_data_root() -> str:
    """Thư mục gốc dữ liệu thị trường của sàn đang dùng."""
    return exchange_root()


def exchange_of(manifest: Optional[dict]) -> str:
    """Sàn của một tài sản theo manifest ("okx_swap" -> okx, "binance_usdm" -> binance); không rõ (DEX...) -> sàn đang dùng."""
    ex = str((manifest or {}).get("exchange") or "").lower()
    return next((e for e in EXCHANGES if ex.startswith(e)), exchange())


# ----------------------------------------------------------------------------------------------------
# P9.3a — API đường dẫn dữ liệu (ADR-P9 §4). MỘT nơi quyết định mọi đường dẫn dưới nora/data.
#
# Luật chung:
# - Mọi helper tính ở THỜI ĐIỂM GỌI từ env (NORA_LOCAL_DATA_ROOT > NORA_DATA_ROOT > nora/data; NORA_EXCHANGE): không cache lúc import.
# - Helper CHỈ trả đường dẫn (không tạo thư mục, trừ cache_dir() giữ hành vi cũ là makedirs).
# - Chế độ PHẲNG (NORA_LOCAL_DATA_ROOT đặt = test; hoặc NORA_DATA_ROOT có cex/ hay dex/ ngay dưới = bí danh cũ của gốc sàn):
#   thư mục đó vừa là home vừa là gốc sàn (market_root() == home), giữ nguyên hành vi trước P9.3.
# ----------------------------------------------------------------------------------------------------


_current_exchange = exchange   # tham số `exchange` của helper che tên hàm


def data_home() -> str:
    """Gốc cây dữ liệu, theo env tại thời điểm gọi: NORA_LOCAL_DATA_ROOT (test) > NORA_DATA_ROOT > nora/data."""
    return os.environ.get("NORA_LOCAL_DATA_ROOT") or os.environ.get("NORA_DATA_ROOT") or DATA_DIR


def _flat() -> bool:
    if os.environ.get("NORA_LOCAL_DATA_ROOT"):
        return True
    nd = os.environ.get("NORA_DATA_ROOT")
    return bool(nd) and any(os.path.isdir(os.path.join(nd, v)) for v in VENUES)


# kind -> đường dẫn duy nhất tính từ home. Một bảng duy nhất cho helper, cache_dir() và allowed_roots().
def _kind_path(home: str, kind: str) -> str:
    j = os.path.join
    table = {
        "alpha": j(home, "alpha"),
        "funnel": j(home, "alpha", "funnel"),
        "book": j(home, "alpha", "book"),
        "backtest": j(home, "backtest"),
        "wfa": j(home, "wfa"),
        "carlo": j(home, "carlo"),
        "live": j(home, "live"),
        "process": j(home, "cache", "process"),
        "mem": j(home, "cache", "process", "_mem"),
        "shared": j(home, "cache", "shared"),
        "quality_gate": j(home, "cache", "shared", "quality_gate"),
        "staging": j(home, "cache", "process", "_staging"),
    }
    return table[kind]


_SHARED_CACHE_KINDS = ("shared", "quality_gate")


def _under(home: str, kind: str, *parts: str) -> str:
    """Đường dưới gốc của `kind`. Cache dùng chung (shared, quality_gate) không bao giờ nằm trong market/: khi home là market/<sàn>
    (chế độ phẳng trỏ vào cây thật, vd. golden NORA_DATA_ROOT=data/market/binance) thì dùng gốc cây data/ chứa nó."""
    if kind in _SHARED_CACHE_KINDS:
        parent = os.path.dirname(os.path.abspath(home))
        if os.path.basename(parent) == "market":
            home = os.path.dirname(parent)
    return os.path.join(_kind_path(home, kind), *parts)


# Tên thư mục cache (cache_dir(None, "<tên>", ...)) -> kind.
# Tên khác -> cache/process/<tên>: ADR-P9 §4 chỉ có 2 thư mục cache (process/, shared/), không sinh thêm thư mục cache cấp 1.
LEGACY_CACHE_NAMES = {"api_jobs": "process", "book": "book", "funnel": "funnel", "book_wfa": "wfa", "live": "live",
                      "quality_gate": "quality_gate", "runs": "mem"}


def market_root(exchange: Optional[str] = None) -> str:
    """Gốc dữ liệu thị trường của một sàn (mặc định sàn đang dùng): market/<sàn>. Chế độ phẳng -> chính home."""
    if _flat():
        return data_home()
    ex = (exchange or _current_exchange()).lower()
    if ex not in EXCHANGES:
        raise ValueError(f"sàn phải là một trong {EXCHANGES}, nhận {ex!r}")
    home = data_home()
    return os.path.join(home, "market", ex)


def market_dir(exchange: Optional[str] = None, venue: str = "cex", symbol: Optional[str] = None, instrument: Optional[str] = None) -> str:
    """market_root(sàn)/<venue>[/<SYM>[/<instrument>]]; venue: cex | dex.
    symbol nhận 'BTC' hoặc 'BTC@perp' (instrument rút từ hậu tố nếu không truyền). Không kiểm tra tồn tại."""
    venue = (venue or "cex").lower()
    if venue not in VENUES:
        raise ValueError(f"venue phải là một trong {VENUES}, nhận {venue!r}")
    sym, inst = split_instrument(symbol or "")
    inst = (instrument or inst or "").lower() or None
    if inst and inst not in INSTRUMENTS:
        raise ValueError(f"instrument phải là một trong {INSTRUMENTS}, nhận {inst!r}")
    if inst and not sym:
        raise ValueError("instrument cần symbol")
    base = os.path.join(market_root(exchange), venue)
    parts = [clean_name(sym)] if sym else []
    return os.path.join(base, *parts, *([inst] if inst else []))


def alpha_dir(*parts: str) -> str:
    """Kho alpha: alpha/. NORA_ALPHAS_DIR (nếu đặt) ghi đè gốc — một chỗ thay các bản sao alphas_dir()."""
    env = os.environ.get("NORA_ALPHAS_DIR")
    return os.path.join(env, *parts) if env else _under(data_home(), "alpha", *parts)


def alpha_file(*parts: str) -> str:
    """File tên cố định trong kho alpha ('book' | 'registry' | 'presets' hoặc 'x.json'). NORA_BOOK_PATH / NORA_PRESETS_PATH ghi đè book/presets."""
    if len(parts) == 1:
        name = parts[0]
        fname = name if "." in name else f"{name}.json"
        override = {"book.json": "NORA_BOOK_PATH", "presets.json": "NORA_PRESETS_PATH"}.get(fname)
        if override and os.environ.get(override):
            return os.environ[override]
        return alpha_dir(fname)
    return alpha_dir(*parts)



def alpha_user_dir() -> str:
    """alpha/user: alpha người dùng."""
    return alpha_dir("user")


def alpha_education_samples() -> str:
    """alpha/education/samples.json."""
    return os.path.join(data_home(), "alpha", "education", "samples.json")



def alpha_run_dir(kind: str, run_id: Optional[str] = None) -> str:
    """Thư mục lượt chạy phễu/sổ: alpha/<kind>[/<id>]; kind ∈ {funnel, book}."""
    if kind not in ("funnel", "book"):
        raise ValueError(f"kind phải là funnel|book, nhận {kind!r}")
    return _under(data_home(), kind, *([run_id] if run_id else []))


def run_dir(kind: str, run_id: Optional[str] = None) -> str:
    """Kết quả lâu dài: <kind>[/<id>]; kind ∈ {backtest, wfa, carlo}."""
    if kind not in ("backtest", "wfa", "carlo"):
        raise ValueError(f"kind phải là backtest|wfa|carlo, nhận {kind!r}")
    return _under(data_home(), kind, *([run_id] if run_id else []))


LIVE_MODE_DIR = {"paper": "paper", "demo": "testnet", "live": "live"}   # chế độ bot -> thư mục con của data/live (chỉ 3 thư mục)


def default_engine(mode: str) -> str:
    """Engine mặc định của chế độ: paper = legacy (PaperBook event); demo/live = unified (Runner + OkxVenue)."""
    return "legacy" if mode == "paper" else "unified"


def live_state_key(venue: str, mode: str, book: str = "main", engine: Optional[str] = None) -> str:
    """Thư mục trạng thái của một bot, tương đối so với data/live (MỘT định nghĩa; live/live.py dùng lại qua live_dir):
    <paper|testnet|live>/<sàn>_<sổ>[_<engine> chỉ khi engine khác mặc định của chế độ]. Paper luôn chung một thư mục (unified = PaperBook event như nhau)."""
    eng = engine or default_engine(mode)
    suffix = f"_{eng}" if mode != "paper" and eng != default_engine(mode) else ""
    return f"{LIVE_MODE_DIR[mode]}/{venue}_{book}{suffix}"


def live_dir(venue: str, mode: str, book: str = "main", engine: Optional[str] = None) -> str:
    """Trạng thái bot: live/<paper|testnet|live>/<sàn>_<sổ>[_engine]; lâu dài, không phải cache. KHÔNG tạo thư mục (chỉ đường ghi của bot tạo)."""
    return _under(data_home(), "live", *live_state_key(venue, mode, book, engine).split("/"))


def cache_process_dir(job_id: Optional[str] = None) -> str:
    """Thư mục job đang chạy: cache/process[/<id>]."""
    return _under(data_home(), "process", *([job_id] if job_id else []))


def cache_quality_gate_dir() -> str:
    """Cache kết quả quality gate: cache/shared/quality_gate."""
    return _under(data_home(), "quality_gate")


def cache_runs_dir() -> str:
    """Log RAM của run_limited.sh: cache/process/_mem."""
    return _under(data_home(), "mem")


def cache_staging_dir() -> str:
    """Vùng đệm crawl -> promote: cache/process/_staging."""
    return _under(data_home(), "staging")


# Nhóm kind cho allowed_roots(): "runs" = mọi nơi chứa thư mục lượt chạy mà API cho phép đọc file (thay cache_dir(None) làm gốc chống path traversal).
_ROOT_GROUPS = {"runs": ("book", "funnel", "wfa", "backtest", "carlo", "process")}


def allowed_roots(kind: str) -> List[str]:
    """realpath của gốc cho `kind`. Dùng làm gốc chặn path traversal:
    os.path.realpath(path) phải nằm trong một gốc (xem is_within). kind: một trong alpha|funnel|book|backtest|wfa|carlo|live|process|mem|shared|
    quality_gate|staging, hoặc nhóm 'runs' (book+funnel+wfa+backtest+carlo+process)."""
    home = data_home()
    kinds = _ROOT_GROUPS.get(kind) or (kind,)
    out: List[str] = []
    for k in kinds:
        try:
            real = os.path.realpath(_kind_path(home, k))
        except KeyError:
            raise ValueError(f"allowed_roots: kind không rõ {kind!r}") from None
        if real not in out:
            out.append(real)
    return out


def is_within(path: str, kind: str) -> bool:
    """True nếu realpath(path) nằm trong (hoặc bằng) một gốc của allowed_roots(kind)."""
    real = os.path.realpath(path)
    return any(real == r or real.startswith(r.rstrip(os.sep) + os.sep) for r in allowed_roots(kind))


def cache_dir(data_root: Optional[str] = None, *parts: str) -> str:
    """Cache tính toán / kho lượt chạy theo tên thư mục (xem LEGACY_CACHE_NAMES):
    api_jobs -> cache/process; book -> alpha/book; funnel -> alpha/funnel; book_wfa -> wfa; live -> live; quality_gate -> cache/shared/quality_gate;
    runs -> cache/process/_mem; tên khác và không tên -> cache/process[/<tên>] (không sinh thư mục cache cấp 1 khác).
    `data_root` tường minh được coi là home (vd. root test). Tạo thư mục (makedirs)."""
    home = data_root or data_home()
    kind = LEGACY_CACHE_NAMES.get(parts[0]) if parts else None
    if kind:
        path = _under(home, kind, *parts[1:])
    else:
        path = _under(home, "process", *parts)
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
    """Thư mục tài sản = không bắt đầu bằng '.'/'_', không phải thư mục venue, và có ít nhất một .pkl (nến)."""
    name = os.path.basename(os.path.normpath(path))
    if not os.path.isdir(path) or name.startswith((".", "_")) or name.lower() in VENUES:
        return False
    return _has_pkl(path)


def _has_pkl(path: str) -> bool:
    try:
        return any(e.endswith(".pkl") for e in os.listdir(path))
    except OSError:
        return False


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

    for venue in VENUES:  # instrument lồng bên trong: cex/<SYM>/perp (thư mục <SYM> có thể không có nến riêng)
        vdir = os.path.join(root, venue)
        for name in sorted(os.listdir(vdir)) if os.path.isdir(vdir) else []:
            if name.startswith((".", "_")):
                continue
            for inst in INSTRUMENTS:
                sub = os.path.join(vdir, name, inst)
                if os.path.isdir(sub) and _has_pkl(sub):
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


# ── Đọc/ghi pkl cục bộ ────────────────────────────────────────────────────────────────────────
# Local PKL data access for candle datasets.

BASE_COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]
_COMPAT_COLUMNS = {"symbol", "timestamp", "close_time", "is_close"}




def _frame_ms(frame: str) -> int:
    match = re.fullmatch(r"(\d+)([smhd])", frame.lower())
    if not match:
        return 0
    value = int(match.group(1))
    unit = match.group(2)
    factors = {
        "s": 1000,
        "m": 60 * 1000,
        "h": 60 * 60 * 1000,
        "d": 24 * 60 * 60 * 1000,
    }
    return value * factors[unit]


def _symbol_candidates(symbol: str) -> List[str]:
    raw = str(symbol or "").strip()
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "", raw)
    upper = cleaned.upper()
    candidates = [raw, cleaned, upper]
    for suffix in ("USDT", "USDC", "USD", "PERP"):
        if upper.endswith(suffix) and len(upper) > len(suffix):
            candidates.append(upper[: -len(suffix)])
    result: List[str] = []
    for item in candidates:
        if item and item not in result:
            result.append(item)
    return result


def resolve_symbol_dir(symbol: str, data_root: Optional[str] = None) -> Optional[str]:
    """Thư mục tài sản (cex/<SYM>, dex/<SYM>, hoặc phẳng kiểu cũ). Chấp nhận 'cex:BTC', 'BTCUSDT'."""
    _, instrument = split_instrument(symbol)
    venue, _ = parse_symbol(symbol)
    if venue or instrument:  # ký hiệu có venue/instrument rõ ràng -> chỉ phân giải chính xác, không đoán
        return resolve_asset_dir(symbol, data_root=data_root)
    for candidate in _symbol_candidates(symbol):
        path = resolve_asset_dir(candidate, data_root=data_root)
        if path:
            return path
    return None


def has_frame(symbol: str, frame: str = "4h", data_root: Optional[str] = None) -> bool:
    """Kiểm tra sự tồn tại của file {frame}.pkl cục bộ."""
    s_dir = resolve_symbol_dir(symbol, data_root=data_root)
    if not s_dir:
        return False
    pkl_path = os.path.join(s_dir, f"{frame}.pkl")
    return os.path.isfile(pkl_path)


# ─── Metadata tài sản = thuộc tính (attrs) nằm TRONG file dữ liệu (không còn manifest.json / dex_pool.json) ───────────────────────────────
# Một nơi đọc/ghi duy nhất cho metadata của tài sản:
#   nến     df.attrs["nora"]            trong MỌI <khung>.pkl (đọc từ khung nhỏ nhất, vd. 24h.pkl): source, exchange, venue, market, symbol, pool_address, network,
#                                       pool_name, volume_unit, synthetic, crawl_ok, checksums_verified, official_api, crawl_issues, requested_*, crawled_at, source_files,
#                                       pool_fee_rate (+ pool_fee_source), start_ts, end_ts, rows_1m, filled_ratio_1m, sha256_1m (sha CSV — định danh dữ liệu cho job_key,
#                                       KHÔNG đổi thuật toán), digest_1m (blake2b trên byte numpy của 6 cột: kiểm toàn vẹn nhanh)
#   tick    ticks.parquet attrs["nora"] = {"ticks": {...}, "onchain": {...}} (footer parquet, không đọc dữ liệu)
#   funding funding.pkl attrs["nora"]   = {"funding": {...}}
# Engine không thấy attrs: fetch_candles_df xoá df.attrs ở biên engine. attrs sống qua pickle/parquet; mất khi concat với frame không attrs hoặc fill_missing_1m_candles
# -> writer luôn gán lại ngay trước khi ghi (stamp_attrs).
ATTR_KEY = "nora"
META_FRAMES = ("24h", "4h", "1h", "15m", "5m", "1m")      # khung nhỏ nhất đọc trước (đọc pickle 24h ~ ms)
_META_CACHE: Dict[str, Tuple[Tuple[int, int], Any]] = {}
_META_CACHE_MAX = 1024


def plain(obj: Any) -> Any:
    """Về kiểu JSON thuần (int/float/str/bool/None/list/dict): attrs ghi vào parquet phải JSON được."""
    return json.loads(json.dumps(obj, default=json_default))


def _meta_cached(path: str, reader) -> Any:
    """reader(path) có đệm theo (mtime_ns, size) của file; file thiếu/lỗi -> None."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    fp = (st.st_mtime_ns, st.st_size)
    hit = _META_CACHE.get(path)
    if hit is not None and hit[0] == fp:
        return hit[1]
    try:
        value = reader(path)
    except Exception:
        value = None
    if len(_META_CACHE) >= _META_CACHE_MAX:
        _META_CACHE.clear()
    _META_CACHE[path] = (fp, value)
    return value


def _read_pkl_attrs(path: str) -> Optional[dict]:
    attrs = pd.read_pickle(path).attrs.get(ATTR_KEY)
    return attrs if isinstance(attrs, dict) else None


def _read_parquet_attrs(path: str) -> Optional[dict]:
    """attrs["nora"] từ footer parquet (pandas metadata) — không đọc dữ liệu."""
    import pyarrow.parquet as pq
    raw = (pq.read_schema(path).metadata or {}).get(b"pandas")
    doc = json.loads(raw) if raw else {}
    attrs = (doc.get("attributes") or doc.get("attrs") or {}).get(ATTR_KEY)   # pandas 2.x ghi "attributes"
    return attrs if isinstance(attrs, dict) else None


def asset_meta(a_dir: str) -> Dict[str, Any]:
    """Metadata của thư mục tài sản: {"dataset": dict|None, "ticks": dict|None, "onchain": dict|None, "funding": dict|None} (bản sao, sửa tự do).
    dataset = attrs nến (khung nhỏ nhất có attrs); ticks/onchain = attrs ticks.parquet; funding = attrs funding.pkl."""
    ds = None
    for frame in META_FRAMES:
        p = os.path.join(a_dir, f"{frame}.pkl")
        if os.path.isfile(p):
            ds = _meta_cached(p, _read_pkl_attrs)
            break
    pq_attrs = _meta_cached(os.path.join(a_dir, "ticks.parquet"), _read_parquet_attrs) or {}
    fund = (_meta_cached(os.path.join(a_dir, "funding.pkl"), _read_pkl_attrs) or {}).get("funding")
    ticks, onchain = pq_attrs.get("ticks"), pq_attrs.get("onchain")
    if onchain is None:
        onchain = (ds or {}).get("onchain")
    return copy.deepcopy({"dataset": ds, "ticks": ticks if isinstance(ticks, dict) else None,
                          "onchain": onchain if isinstance(onchain, dict) else None, "funding": fund if isinstance(fund, dict) else None})


def manifest_of_dir(a_dir: str) -> Optional[dict]:
    """Dạng "manifest" của một thư mục tài sản (khoá/giá trị như manifest.json cũ): dataset attrs + coverage_days/coverage_ratio/rows suy ra + ticks + funding. None nếu không có metadata."""
    meta = asset_meta(a_dir)
    out = meta["dataset"]
    if out is None:
        return None
    out.setdefault("base_resolution", "1m")
    start, end = int(out.get("start_ts") or 0), int(out.get("end_ts") or 0)
    out.setdefault("coverage_days", round((end - start) / 86_400_000, 2) if end > start else 0.0)
    rs, re_ = out.get("requested_start_ts"), out.get("requested_end_ts")
    out.setdefault("coverage_ratio", round((end - start) / max(1, re_ - rs), 3) if rs is not None and re_ is not None and re_ > rs else 1.0)
    if "rows" not in out and out.get("rows_1m") is not None:
        out["rows"] = {"1m": int(out["rows_1m"])}
    for key in ("ticks", "funding"):
        if meta[key] is not None:
            out[key] = meta[key]
    return out


def stamp_attrs(df: pd.DataFrame, meta: Dict[str, Any]) -> pd.DataFrame:
    """Gán df.attrs["nora"] = meta (đã về kiểu JSON thuần) rồi trả lại chính df. Gọi NGAY TRƯỚC khi ghi (attrs bị mất qua concat / fill_missing_1m_candles)."""
    df.attrs = {ATTR_KEY: plain(meta)}
    return df


def write_pickle_atomic(df: pd.DataFrame, path: str) -> None:
    """to_pickle ra tên tạm rồi os.replace: người đọc không bao giờ thấy file dở."""
    tmp = f"{path}.{os.getpid()}.tmp"
    df.to_pickle(tmp)
    os.replace(tmp, path)


def write_json_atomic(path: str, obj: Any) -> None:
    """json.dump (default=json_default) ra tên tạm rồi os.replace: người đọc không bao giờ thấy file dở. Lỗi -> xoá file tạm rồi ném lại."""
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, default=json_default)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_parquet_atomic(df: pd.DataFrame, path: str, meta: Optional[Dict[str, Any]] = None) -> None:
    """to_parquet (snappy) kèm attrs["nora"]=meta, ghi nguyên tử."""
    if meta is not None:
        df.attrs = {ATTR_KEY: plain(meta)}
    tmp = f"{path}.{os.getpid()}.tmp"
    df.to_parquet(tmp, engine="pyarrow", compression="snappy", index=False)
    os.replace(tmp, path)


def read_manifest(symbol: str, data_root: Optional[str] = None) -> Optional[dict]:
    """Metadata của asset (dạng manifest; xem manifest_of_dir); None nếu không có."""
    s_dir = resolve_symbol_dir(symbol, data_root=data_root)
    return manifest_of_dir(s_dir) if s_dir else None


def has_ticks(symbol: str, data_root: Optional[str] = None, min_days: float = 0.0) -> bool:
    """True chỉ khi có tick THẬT đã được khai báo trong attrs của ticks.parquet (fail-closed).

    Yêu cầu: ticks.parquet tồn tại, có khối ticks với synthetic=False và độ phủ thời gian của tick >= min_days.
    File ticks.parquet không khai báo -> KHÔNG được coi là tick thật.
    """
    s_dir = resolve_symbol_dir(symbol, data_root=data_root)
    if not s_dir or not os.path.isfile(os.path.join(s_dir, "ticks.parquet")):
        return False
    ticks_meta = asset_meta(s_dir)["ticks"]
    if not isinstance(ticks_meta, dict) or ticks_meta.get("synthetic", True) is not False:
        return False
    if min_days > 0:
        start_ts = int(ticks_meta.get("start_ts") or 0)
        end_ts = int(ticks_meta.get("end_ts") or 0)
        if end_ts <= start_ts or (end_ts - start_ts) / 86_400_000 < min_days:
            return False
    return True


def fetch_candles_df(
    symbol: str,
    frame: str = "4h",
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    columns: Optional[List[str]] = None,
    db_name: str = "",
    limit: Optional[int] = None,
    data_root: Optional[str] = None,
    compat: bool = True,
) -> pd.DataFrame:
    """Nạp nến từ file pkl cục bộ.

    Tối ưu bộ nhớ:
    - Chỉ dropna / sort khi thật sự cần (file do resampler ghi đã sạch và sắp xếp).
    - Cắt cửa sổ bằng iloc TRƯỚC khi .copy(): chỉ sao chép phần trong cửa sổ.
      (CandleLoader nạp cả file để cache, nên với engine bản sao này là cả file — một lần.)
    - compat=False (CandleLoader/engine): không thêm cột symbol/timestamp/close_time/is_close.
    """
    symbol_dir = resolve_symbol_dir(symbol, data_root=data_root)
    if not symbol_dir:
        return pd.DataFrame()

    path = os.path.join(symbol_dir, f"{frame}.pkl")
    if not os.path.isfile(path):
        return pd.DataFrame()

    df = pd.read_pickle(path)
    df.attrs = {}   # biên engine: metadata (attrs["nora"]) không đi vào engine -> khung y hệt trước khi có attrs
    if df.empty:
        return df
    if "open_time" not in df.columns:
        raise ValueError(f"Local PKL file missing open_time column: {path}")

    # Chuẩn hóa open_time (dropna chỉ khi thật sự có NaN — tránh một bản sao cả file)
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
    if df["open_time"].isna().any():
        df = df.dropna(subset=["open_time"])
    df["open_time"] = df["open_time"].astype("int64")

    # Sort chỉ khi chưa monotonic (pkl do resampler ghi luôn đã sắp xếp)
    if not df["open_time"].is_monotonic_increasing:
        df = df.sort_values("open_time", kind="stable").reset_index(drop=True)

    # Cắt cửa sổ [start_ts, end_ts] bằng vị trí (iloc) TRƯỚC khi .copy(): không sao chép phần ngoài cửa sổ
    open_times = df["open_time"].to_numpy()
    lo = int(np.searchsorted(open_times, int(start_ts), side="left")) if start_ts is not None else 0
    hi = int(np.searchsorted(open_times, int(end_ts), side="right")) if end_ts is not None else len(df)
    df = df.iloc[lo:hi]
    if limit:
        df = df.head(limit)

    # Luôn giữ is_filled nếu có: engine cần biết nến nào là nến điền
    needed_columns = list(BASE_COLUMNS) + (["is_filled"] if "is_filled" in df.columns else [])
    if columns:
        for column in columns:
            if column in df.columns and column not in needed_columns:
                needed_columns.append(column)
    existing_columns = [column for column in needed_columns if column in df.columns]
    # .copy() tại đây — sau khi đã cắt cửa sổ, chỉ sao chép phần cần dùng
    df = df.loc[:, existing_columns].copy()

    # Cột compat chỉ thêm khi cần thiết (caller yêu cầu hoặc không chỉ định columns)
    requested = set(columns or [])
    needs_compat = compat and (not columns or bool(requested & _COMPAT_COLUMNS))
    if needs_compat:
        symbol_name = os.path.basename(symbol_dir)
        interval_ms = _frame_ms(frame)
        df["symbol"] = symbol_name
        df["timestamp"] = df["open_time"] // 1000
        df["close_time"] = df["open_time"] + interval_ms if interval_ms else df["open_time"]
        df["is_close"] = 1

    if columns is not None:
        keep = [column for column in columns if column in df.columns]
        df = df.loc[:, keep]

    return df.reset_index(drop=True)


def benchmark_daily_closes(symbol: str, start_ms: int, end_ms: int) -> pd.Series:
    """Giá đóng cửa ngày UTC (khung 24h của dữ liệu cục bộ) trong [start - 10 ngày, end]; Series rỗng nếu thiếu dữ liệu."""
    df = fetch_candles_df(symbol, "24h", start_ts=int(start_ms) - 10 * 86_400_000, end_ts=int(end_ms), columns=["open_time", "close"],
                          compat=False)
    if df is None or df.empty:
        return pd.Series(dtype=float)
    idx = pd.to_datetime(df["open_time"].to_numpy(), unit="ms").normalize()
    return pd.Series(df["close"].to_numpy(dtype=float), index=idx).groupby(level=0).last()


# ── Bộ đệm LRU theo byte ──────────────────────────────────────────────────────────────────────
# Bộ đệm LRU giới hạn theo BYTE (không theo số mục), an toàn đa luồng.
#
# Dùng chung cho crawl/store.py (_CANDLE_CACHE) và nautilus/engine.py (_DATA_CACHE).
# - Mỗi tiến trình có bản riêng (multiprocessing); trong một tiến trình, API chạy job trên
#   ThreadPoolExecutor nên mọi thao tác đều giữ khoá.
# - Mục lớn hơn cả ngân sách thì không cache (và bản cũ cùng khoá bị bỏ).
#

def env_mb(name: str, default: float) -> float:
    """Đọc ngân sách MB từ biến môi trường; giá trị hỏng -> default."""
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


class ByteLRU:
    def __init__(self, budget_mb: float):
        self.budget = int(max(0.0, float(budget_mb)) * 1024 * 1024)
        self.used = 0
        self._d: "OrderedDict[Hashable, tuple]" = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: Hashable) -> Optional[Any]:
        with self._lock:
            item = self._d.get(key)
            if item is None:
                return None
            self._d.move_to_end(key)
            return item[0]

    def put(self, key: Hashable, value: Any, nbytes: int) -> None:
        nbytes = int(nbytes)
        with self._lock:
            old = self._d.pop(key, None)
            if old is not None:
                self.used -= old[1]
            if nbytes > self.budget:
                return
            while self._d and self.used + nbytes > self.budget:
                _, (_, n) = self._d.popitem(last=False)
                self.used -= n
            self._d[key] = (value, nbytes)
            self.used += nbytes

    def evict(self, key: Hashable) -> None:
        with self._lock:
            item = self._d.pop(key, None)
            if item is not None:
                self.used -= item[1]

    def clear(self) -> None:
        with self._lock:
            self._d.clear()
            self.used = 0

    def used_mb(self) -> float:
        return self.used / (1024 * 1024)

    def __len__(self) -> int:
        with self._lock:
            return len(self._d)


# ── JSON an toàn ──────────────────────────────────────────────────────────────────────────────
# Chuyển kiểu numpy/pandas/datetime sang kiểu JSON thuần — dùng làm `default=` của json.dump.
#
# Lỗi gốc: `default=str` biến np.bool_ thành chuỗi 'False' (truthy!) và số numpy thành chuỗi.
#

def json_default(o):
    # Lưu ý: np.float64 là lớp con của float nên json xử lý trực tiếp (NaN vẫn ra "NaN"); default chỉ gọi cho kiểu json không biết.
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (_dt.datetime, _dt.date, _dt.time)) or hasattr(o, "isoformat"):  # gồm pd.Timestamp
        return o.isoformat()
    if isinstance(o, np.datetime64):
        return str(o)
    return str(o)


def read_json(path: str, default: Any = None) -> Any:
    """Nội dung JSON của file; `default` nếu file thiếu / không đọc được / không phải JSON hợp lệ (OSError, ValueError)."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


# ─── Kết quả + tham số job (từ optimize/process/process.py; P9.10b: crawl nằm dưới optimize nên helper job ở đây) ──────────────────────────────────────────────────
def write_job_result(result: Any) -> Optional[str]:
    job_dir = os.environ.get("NORA_JOB_DIR")
    if not job_dir or not os.path.isdir(job_dir):   # thư mục job đã bị API xoá (huỷ/xong): KHÔNG tạo lại làm thư mục mồ côi
        return None
    path = os.path.join(job_dir, "result.json")
    write_json_atomic(path, result)  # ghi nguyên tử: API không bao giờ đọc file dở
    return path


def options(defaults: Dict[str, Any], params: Optional[Dict[str, Any]] = None) -> SimpleNamespace:
    """Tham số của một job: `defaults` ghi đè bởi `params`. Khoá lạ -> ValueError (không âm thầm bỏ qua lỗi gõ tên)."""
    params = dict(params or {})
    unknown = sorted(set(params) - set(defaults))
    if unknown:
        raise ValueError(f"tham số lạ: {unknown}; có: {sorted(defaults)}")
    return SimpleNamespace(**{**defaults, **params})


def as_list(value) -> list:
    """Danh sách từ tham số job: None/"" -> [], "a,b" -> ["a", "b"], list/tuple -> list."""
    if not value:
        return []
    if isinstance(value, str):
        return [x for x in value.split(",") if x]
    return list(value)


# ── Loader nến ────────────────────────────────────────────────────────────────────────────────
# Dữ liệu Nến và Data Loader tốc độ cao.
#
# Cung cấp cơ chế nạp nến (Candle Loader) sử dụng bộ đệm (Memory Caching)
# để tái sử dụng dữ liệu nến giữa các lần chạy (Backtest / Optimize).
#
# Thiết kế bộ đệm (v2 — fix OOM):
# - Local pkl: cache CẢ FILE (toàn bộ lịch sử) một lần, không cache từng cửa sổ.
#   Khoá: (data_root, symbol, frame, mtime_ns, size_bytes) -> file crawl lại thì tự hết hạn.
# - Cửa sổ start_ts -> end_ts cắt bằng .loc trên index open_time đã sắp xếp (không sao chép).
#   Kết quả là VIEW của bản trong cache: người gọi phải copy trước khi sửa (engine copy trong _prepare_candles).
# - Tổng RAM giới hạn bằng ByteLRU (backend/crawl/store.py), NORA_CANDLE_CACHE_MB (mặc định 1024 MB).
# - Chỉ giữ các cột engine cần (compat=False): không thêm cột symbol/timestamp/close_time/is_close.
# - Mongo: KHÔNG cache, luôn nạp theo cửa sổ (không bao giờ kéo cả collection vào RAM).
#

_CANDLE_CACHE = ByteLRU(env_mb("NORA_CANDLE_CACHE_MB", 1024))


def _file_fingerprint(symbol: str, frame: str, data_root: Optional[str]) -> Optional[Tuple[int, int]]:
    """(mtime_ns, size_bytes) của file {frame}.pkl, hoặc None nếu không tìm thấy."""
    sym_dir = resolve_symbol_dir(symbol, data_root=data_root)
    if not sym_dir:
        return None
    try:
        st = os.stat(os.path.join(sym_dir, f"{frame}.pkl"))
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _index_by_open_time(df: pd.DataFrame) -> pd.DataFrame:
    """Index = open_time (không tên, không sao chép cột) để .loc cắt cửa sổ nhanh."""
    if df.empty or "open_time" not in df.columns:
        return df
    df.index = pd.Index(df["open_time"].to_numpy())
    if not df.index.is_monotonic_increasing:
        df = df.sort_index(kind="stable")
    return df


class CandleLoader:
    """Công cụ nạp và quản lý dữ liệu nến cho Backtest."""

    def __init__(self, symbol: str, frame: str = "4h", use_cache: bool = True, **_ignored):
        self.symbol = symbol
        self.frame = frame
        self.use_cache = use_cache
        self.local_data_root = default_data_root()

    def _cache_key(self) -> Optional[tuple]:
        fp = _file_fingerprint(self.symbol, self.frame, self.local_data_root)
        if fp is None:
            return None
        return (self.local_data_root, self.symbol, self.frame, *fp)

    def load_data(
        self,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        columns: Optional[List[str]] = None,
        force_reload: bool = False,
    ) -> pd.DataFrame:
        """Nạp nến trong [start_ts, end_ts] (gồm hai đầu)."""
        if start_ts is None or end_ts is None:
            raise ValueError("CandleLoader require explicit start_ts and end_ts to prevent Memory Overload!")

        key = self._cache_key() if self.use_cache else None
        if key is None:  # không cache: chỉ nạp đúng cửa sổ
            df = _index_by_open_time(self._fetch_local(start_ts, end_ts))
            return self._slice_data(df, start_ts, end_ts, columns)
        full_df = None if force_reload else _CANDLE_CACHE.get(key)
        if full_df is None:
            full_df = _index_by_open_time(self._fetch_local(None, None))
            if not full_df.empty:
                _CANDLE_CACHE.put(key, full_df, int(full_df.memory_usage(index=True, deep=True).sum()))
        return self._slice_data(full_df, start_ts, end_ts, columns)

    def _fetch_local(self, start_ts: Optional[int], end_ts: Optional[int]) -> pd.DataFrame:
        """Nến từ file local (đã sắp xếp; None/None = cả file), chỉ các cột engine cần."""
        if not has_frame(self.symbol, self.frame, data_root=self.local_data_root):
            raise FileNotFoundError(f"Không tìm thấy file nến local {self.frame}.pkl cho {self.symbol} tại {self.local_data_root}.")
        df = fetch_candles_df(symbol=self.symbol, frame=self.frame, start_ts=start_ts, end_ts=end_ts,
                                data_root=self.local_data_root, compat=False)
        if df.empty:
            raise FileNotFoundError(f"Dữ liệu local cho {self.symbol} ({self.frame}) rỗng.")
        return df

    @staticmethod
    def _slice_data(df: pd.DataFrame, start_ts: Optional[int], end_ts: Optional[int],
                    columns: Optional[List[str]]) -> pd.DataFrame:
        if df.empty:
            return df
        sliced = df.loc[start_ts:end_ts]
        if columns is not None:
            sliced = sliced[[c for c in columns if c in sliced.columns]]
        return sliced

    @staticmethod
    def clear_cache() -> None:
        """Xóa toàn bộ bộ đệm RAM."""
        _CANDLE_CACHE.clear()


# ── Resampler ─────────────────────────────────────────────────────────────────────────────────
# Causal Candle Resampler and Manifest Generator.
# Phase 1: Single source of truth. All frames (5m, 15m, 1h, 4h, 24h) are strictly
# resampled from 1m candles. Missing minutes are filled with previous close, volume=0, is_filled=1.
# Resampling is aligned to UTC, label="left", closed="left", 4h anchored at 00:00 UTC.
#

PKL_COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]
TIMEFRAME_MAP = {
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "24h": "24h",
    "1d": "24h",
}


def _fill_missing_1m_candles_with_ratio(df_1m: pd.DataFrame) -> Tuple[pd.DataFrame, float]:
    """
    Internal: Fills gaps in 1m candles. Idempotent: calling twice gives the same result.

    Algorithm:
    1. Strip bất kỳ nến nào đã được điền trước đó (is_filled == 1) ra khỏi input.
       Điều này cho phép dữ liệu thật sau này ghi đè nến điền, và đảm bảo
       fill(fill(x)) == fill(x).
    2. Sort, dedup (keep last: dữ liệu thật thắng nếu trùng ts).
    3. Xây lại lưới thời gian đầy đủ từ min → max bước 60s.
    4. Merge với dữ liệu thật: dòng thiếu → is_filled=1, O=H=L=C=prev_close, volume=0.

    Returns (filled_df, filled_ratio_1m).
    """
    if df_1m.empty:
        df_empty = df_1m.copy()
        if "is_filled" not in df_empty.columns:
            df_empty["is_filled"] = 0
        return df_empty, 0.0

    # ── Bước 1: Strip nến điền cũ để đảm bảo idempotency ─────────────────────
    df = df_1m.copy()
    if "is_filled" in df.columns:
        df = df[df["is_filled"].fillna(0).astype(int) != 1]

    # ── Bước 2: Sort, dedup (keep last = dữ liệu thật thắng nếu trùng ts) ────
    df = df.sort_values("open_time").drop_duplicates("open_time", keep="last").reset_index(drop=True)
    df["is_filled"] = 0

    if df.empty:
        result = df_1m.copy()
        if "is_filled" not in result.columns:
            result["is_filled"] = 0
        return result, 0.0

    min_t = int(df["open_time"].min())
    max_t = int(df["open_time"].max())

    # ── Bước 3: Lưới thời gian đầy đủ ───────────────────────────────────────
    full_times = np.arange(min_t, max_t + 60_000, 60_000, dtype=np.int64)
    grid_df = pd.DataFrame({"open_time": full_times})

    merged = pd.merge(grid_df, df, on="open_time", how="left")

    # ── Bước 4: Điền missing ─────────────────────────────────────────────────
    missing_mask = merged["close"].isna()
    merged.loc[missing_mask, "is_filled"] = 1
    merged.loc[~missing_mask, "is_filled"] = 0
    merged.loc[missing_mask, "volume"] = 0.0

    # Forward fill close (dùng cho O=H=L=C của nến điền)
    merged["close"] = merged["close"].ffill().bfill()
    merged.loc[missing_mask, "open"] = merged.loc[missing_mask, "close"]
    merged.loc[missing_mask, "high"] = merged.loc[missing_mask, "close"]
    merged.loc[missing_mask, "low"] = merged.loc[missing_mask, "close"]

    filled_ratio = float(merged["is_filled"].mean())
    merged["open_time"] = merged["open_time"].astype(np.int64)
    merged["is_filled"] = merged["is_filled"].astype(int)

    return merged, filled_ratio


def fill_missing_1m_candles(df_1m: pd.DataFrame) -> pd.DataFrame:
    """
    Public API: Fills gaps in 1m candles. Idempotent.
    Returns only the filled DataFrame (không kèm filled_ratio).
    """
    filled_df, _ = _fill_missing_1m_candles_with_ratio(df_1m)
    return filled_df




def ticks_to_bars(ticks_df: pd.DataFrame, frame: str = "1m", price_col: str = "price") -> pd.DataFrame:
    """Tick -> nến khung `frame` ("1m", "5m", "15m", "1h", "4h", "1d"...; mốc thẳng epoch UTC): open_time ms, OHLC theo `price_col`, volume = tổng volume_usd,
    n_trades = số swap, n_fallback = số swap phải dùng `price` (giá khớp) vì `price_col` NaN, vwap = Σvolume_usd/Σamount của giá KHỚP, is_filled.
    Mặc định OHLC theo giá KHỚP `price` (gồm phí pool): đây chính là cơ sở nến của GeckoTerminal (đo: nến GT tính theo token quote trùng close giá khớp cuối phút, chênh
    median 0 bps trên 161 phút; còn mid_price lệch đúng mức phí pool ~30 bps). price_col="mid_price" -> OHLC theo giá biên sau swap (giá swap không bị phí làm lệch, dùng
    cho phân tích giá pool; swap thiếu mid dùng price và được đếm ở n_fallback).
    Lưới đủ từ nến tick đầu tới nến tick cuối: nến không có swap -> is_filled=1, n_trades=0, volume 0, O=H=L=C=vwap=close trước (không bịa lệnh).
    Chỉ để đối chiếu/phân tích — KHÔNG ghi vào kho nến."""
    cols = PKL_COLUMNS + ["n_trades", "n_fallback", "vwap", "is_filled"]
    step = _frame_ms(frame)
    if step <= 0:
        raise ValueError(f"khung không hợp lệ: {frame!r} (vd. 1m, 15m, 1h, 1d)")
    if ticks_df.empty:
        return pd.DataFrame(columns=cols)
    t = ticks_df.sort_values("timestamp_ms", kind="stable")
    px = t[price_col] if price_col in t.columns else pd.Series(np.nan, index=t.index)
    t = t.assign(_px=px.fillna(t["price"]), _fb=px.isna().astype(int))
    grp = t.groupby((t["timestamp_ms"] // step * step).astype(np.int64).rename("open_time"))
    bars = pd.DataFrame({"open": grp["_px"].first(), "high": grp["_px"].max(), "low": grp["_px"].min(), "close": grp["_px"].last(),
                         "volume": grp["volume_usd"].sum(), "n_trades": grp["_px"].size(), "n_fallback": grp["_fb"].sum(),
                         "vwap": grp["volume_usd"].sum() / grp["amount"].sum()})
    grid = np.arange(bars.index.min(), bars.index.max() + step, step, dtype=np.int64)
    out = bars.reindex(pd.Index(grid, name="open_time"))
    filled = out["close"].isna()
    out["close"] = out["close"].ffill()
    for c in ("open", "high", "low", "vwap"):
        out.loc[filled, c] = out.loc[filled, "close"]
    out["volume"] = out["volume"].fillna(0.0)
    for c in ("n_trades", "n_fallback"):
        out[c] = out[c].fillna(0).astype(np.int64)
    out["is_filled"] = filled.astype(int)
    return out.reset_index()[cols]


def resample_from_1m(df_1m: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resamples 1m candles into higher timeframe (e.g. 5m, 15m, 1h, 4h, 24h).
    Enforces UTC alignment, label="left", closed="left".
    4h is anchored at 00:00 UTC.
    """
    if df_1m.empty:
        return pd.DataFrame(columns=PKL_COLUMNS)

    rule = TIMEFRAME_MAP.get(timeframe)
    if rule is None:
        if timeframe.endswith("m"):
            rule = f"{timeframe[:-1]}min"
        elif timeframe.endswith("h"):
            rule = timeframe
        else:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

    df = df_1m.copy().sort_values("open_time").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("dt")

    # Resample with left label and left closed boundary
    resampled = df.resample(rule, closed="left", label="left", origin="start_day").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open", "close"])

    scale = 10**6 if "ns" in str(resampled.index.dtype) else (10**3 if "us" in str(resampled.index.dtype) else 1)
    resampled["open_time"] = (resampled.index.astype("int64") // scale).astype(np.int64)
    result = resampled[PKL_COLUMNS].reset_index(drop=True)
    return result


def compute_df_sha256(df: pd.DataFrame) -> str:
    """Computes SHA-256 hash of dataframe values."""
    data_bytes = df[PKL_COLUMNS].to_csv(index=False).encode("utf-8")
    return hashlib.sha256(data_bytes).hexdigest()


def compute_df_digest(df: pd.DataFrame) -> str:
    """blake2b trên byte numpy của 6 cột OHLCV+thời gian (digest_1m): kiểm toàn vẹn NHANH (~ms) thay cho sha256 CSV, đổi một bit là lệch."""
    h = hashlib.blake2b()
    for c in PKL_COLUMNS:
        h.update(np.ascontiguousarray(df[c].to_numpy()).tobytes())
    return h.hexdigest()


def generate_manifest(
    symbol: str,
    pool_address: str,
    df_1m: pd.DataFrame,
    df_4h: pd.DataFrame,
    filled_ratio: float,
    source: str = "geckoterminal",
    synthetic: bool = False,
    extra_rows: Optional[Dict[str, int]] = None,
    crawl_ok: bool = True,
    requested_start_ts: Optional[int] = None,
    requested_end_ts: Optional[int] = None,
    ticks: Optional[Dict[str, Any]] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generates manifest metadata dictionary according to Phase 1 specification.
    extra_meta: metadata bổ sung (vd. venue="cex"/"dex", exchange, market_symbol, network);
    không được ghi đè các trường lõi của manifest.
    """
    start_ts = int(df_1m["open_time"].min()) if not df_1m.empty else 0
    end_ts = int(df_1m["open_time"].max()) if not df_1m.empty else 0
    
    rows = {
        "1m": len(df_1m),
        "4h": len(df_4h) if df_4h is not None and not df_4h.empty else 0,
    }
    if extra_rows:
        rows.update(extra_rows)

    coverage_days = round((end_ts - start_ts) / 86_400_000, 2) if end_ts > start_ts else 0.0
    if requested_start_ts is not None and requested_end_ts is not None and requested_end_ts > requested_start_ts:
        coverage_ratio = round((end_ts - start_ts) / max(1, requested_end_ts - requested_start_ts), 3)
    else:
        coverage_ratio = 1.0

    manifest = {
        "source": source,
        "symbol": (extra_meta or {}).get("symbol") or symbol,   # extra_meta["symbol"] đặt ký hiệu hiển thị (vd. "BTC@perp" khi thư mục là "perp")
        "pool_address": pool_address,
        "base_resolution": "1m",
        "synthetic": synthetic,
        "crawled_at": int(time.time()),
        "crawl_ok": crawl_ok,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "requested_start_ts": requested_start_ts,
        "requested_end_ts": requested_end_ts,
        "coverage_days": coverage_days,
        "coverage_ratio": coverage_ratio,
        "rows": rows,
        "filled_ratio_1m": round(filled_ratio, 4),
        "sha256_1m": compute_df_sha256(df_1m) if not df_1m.empty else "",
        "digest_1m": compute_df_digest(df_1m) if not df_1m.empty else "",
    }
    if ticks is not None:
        manifest["ticks"] = ticks
    for key, value in (extra_meta or {}).items():
        if key not in manifest:
            manifest[key] = value
    return manifest


def save_resampled_dataset(
    symbol: str,
    output_dir: str,
    df_1m_raw: pd.DataFrame,
    pool_address: str,
    timeframes: Tuple[str, ...] = ("5m", "15m", "1h", "4h", "24h"),
    source: str = "geckoterminal",
    synthetic: bool = False,
    crawl_ok: bool = True,
    requested_start_ts: Optional[int] = None,
    requested_end_ts: Optional[int] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Fills 1m gaps, resamples all target timeframes, writes pkl files (mọi khung kèm attrs["nora"] = metadata, xem stamp_attrs) và trả manifest (dict).
    Ghi nguyên tử từng file; 24h.pkl (khung đọc metadata) ghi CUỐI.
    """
    target_dir = os.path.join(output_dir, symbol)
    os.makedirs(target_dir, exist_ok=True)

    df_1m, filled_ratio = _fill_missing_1m_candles_with_ratio(df_1m_raw)

    frames = {"1m": df_1m}
    rows_dict = {"1m": len(df_1m)}
    df_4h = None
    for tf in timeframes:
        df_resampled = resample_from_1m(df_1m, tf)
        frames[tf] = df_resampled
        rows_dict[tf] = len(df_resampled)
        if tf == "4h":
            df_4h = df_resampled

    if df_4h is None:
        df_4h = resample_from_1m(df_1m, "4h")

    manifest = generate_manifest(
        symbol=symbol,
        pool_address=pool_address,
        df_1m=df_1m,
        df_4h=df_4h,
        filled_ratio=filled_ratio,
        source=source,
        synthetic=synthetic,
        extra_rows=rows_dict,
        crawl_ok=crawl_ok,
        requested_start_ts=requested_start_ts,
        requested_end_ts=requested_end_ts,
        extra_meta=extra_meta,
    )
    meta = {k: v for k, v in manifest.items() if k not in _DERIVED_META}
    meta["rows_1m"] = rows_dict["1m"]
    for tf in sorted(frames, key=lambda f: META_FRAMES.index(f) if f in META_FRAMES else len(META_FRAMES), reverse=True):   # khung đọc metadata (24h) ghi cuối
        write_pickle_atomic(stamp_attrs(frames[tf], meta), os.path.join(target_dir, f"{tf}.pkl"))
    return manifest


# Khoá của manifest suy ra được từ metadata khác (không lưu trong attrs): khung/độ phủ/ticks/funding.
_DERIVED_META = ("rows", "coverage_days", "coverage_ratio", "base_resolution", "ticks", "funding")


# ── Quality gate ──────────────────────────────────────────────────────────────────────────────
# Data Quality Gate Module
# Validates asset tick and candle data integrity, checks for missing bars, duplicate timestamps,
# extreme outliers, and zero-volume periods.
# Outputs Data Quality Score (0-100) and Gate Status (APPROVED, WARNING, BLOCKED, NEEDS_MORE_DATA).
#

# Tỉ lệ phút không có giao dịch tối đa cho phép. Engine KHÔNG khớp lệnh trên nến điền
# (chờ phút có giao dịch thật), nên nến điền không tạo lệnh ảo; ngưỡng này chỉ loại
# các pool quá thưa. Đo thực tế: AERO/USDC (Base, ~$30M thanh khoản) = 43%.
MAX_FILLED_RATIO_1M = 0.60


class DataQualityStatus:
    APPROVED = "APPROVED"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    NEEDS_MORE_DATA = "NEEDS_MORE_DATA"


# Cache kết quả gate trong process. Khoá gồm (mtime_ns, size) của MỌI file trong thư mục
# tài sản -> bất kỳ file nào đổi (crawl lại, sửa pkl) thì cache tự hết hạn.
# Gate trên 3 năm dữ liệu 1m mất ~11s (sha256 + resample 1,58 triệu nến), cache tránh lặp lại
# ở mỗi lần backtest/WFA.
_GATE_CACHE: Dict[tuple, Dict[str, Any]] = {}
_GATE_CACHE_MAX = 256


def _gate_cache_key(symbol: str, timeframe: str, data_root: Optional[str]) -> Optional[tuple]:
    from backend.crawl.dex import symbol_dir  # lazy: dex <-> store vòng import (dex nạp store ở đầu file)
    s_dir = symbol_dir(symbol, data_root)
    if not os.path.isdir(s_dir):
        return None
    files = []
    for name in sorted(os.listdir(s_dir)):
        path = os.path.join(s_dir, name)
        if os.path.isfile(path):
            st = os.stat(path)
            files.append((name, st.st_mtime_ns, st.st_size))
    return (os.path.abspath(s_dir), timeframe, tuple(files))


_CODE_SIG: Optional[str] = None


def _code_sig() -> str:
    """sha1 mã nguồn module này: luật gate đổi -> cache trên đĩa tự hết hạn."""
    global _CODE_SIG
    if _CODE_SIG is None:
        import hashlib
        with open(__file__, "rb") as fh:
            _CODE_SIG = hashlib.sha1(fh.read()).hexdigest()[:16]
    return _CODE_SIG


def _disk_cache_path(key: tuple, data_root: Optional[str]) -> str:
    """Cache kết quả gate TRÊN ĐĨA — MỘT thư mục duy nhất cache/shared/quality_gate (không còn thư mục theo gốc dữ liệu): mỗi job là một tiến trình mới -> không phải kiểm lại ~10 s/tài sản.
    Khoá = (thư mục tuyệt đối, khung, (tên, mtime_ns, size) mọi file của tài sản, chữ ký mã gate) -> gốc dữ liệu khác nhau không đụng nhau."""
    sig = _code_sig()
    h = hashlib.sha1(json.dumps([list(key[:2]), [list(f) for f in key[2]], sig]).encode()).hexdigest()
    d = cache_quality_gate_dir()
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{sig}_{h}.json")


_GATE_PRUNED: Dict[str, bool] = {}


def _prune_gate_cache(d: str) -> None:
    """Cache gate chỉ giữ kết quả của mã gate HIỆN TẠI: file của chữ ký mã khác (hoặc tên kiểu cũ không tiền tố) bị xoá, một lần mỗi tiến trình."""
    if _GATE_PRUNED.get(d):
        return
    _GATE_PRUNED[d] = True
    keep = _code_sig() + "_"
    try:
        for n in os.listdir(d):
            if n.endswith(".json") and not n.startswith(keep):
                try:
                    os.remove(os.path.join(d, n))
                except OSError:
                    pass
    except OSError:
        pass


def _disk_get(key: tuple, data_root: Optional[str]) -> Optional[Dict[str, Any]]:
    try:
        with open(_disk_cache_path(key, data_root), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _disk_put(key: tuple, data_root: Optional[str], result: Dict[str, Any]) -> None:
    path = _disk_cache_path(key, data_root)
    _prune_gate_cache(os.path.dirname(path))
    try:
        write_json_atomic(path, result)
    except (OSError, TypeError, ValueError):
        pass


def evaluate_data_quality(
    symbol: str,
    timeframe: str = "1h",
    df_candles: Optional[pd.DataFrame] = None,
    df_ticks: Optional[pd.DataFrame] = None,
    data_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Quality gate (có cache khi chỉ đọc từ đĩa, xem _GATE_CACHE)."""
    if df_candles is not None or df_ticks is not None:
        return _evaluate_data_quality_uncached(symbol, timeframe, df_candles, df_ticks, data_root)
    key = _gate_cache_key(symbol, timeframe, data_root)
    if key is not None and key in _GATE_CACHE:
        return copy.deepcopy(_GATE_CACHE[key])
    result = _disk_get(key, data_root) if key is not None else None
    if result is None:
        result = _evaluate_data_quality_uncached(symbol, timeframe, None, None, data_root)
        if key is not None:
            _disk_put(key, data_root, result)
    if key is not None:
        if len(_GATE_CACHE) >= _GATE_CACHE_MAX:
            _GATE_CACHE.clear()
        _GATE_CACHE[key] = copy.deepcopy(result)
    return result


def _evaluate_data_quality_uncached(
    symbol: str,
    timeframe: str = "1h",
    df_candles: Optional[pd.DataFrame] = None,
    df_ticks: Optional[pd.DataFrame] = None,
    data_root: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Evaluates data quality for a given asset.
    Returns:
        status: APPROVED | WARNING | BLOCKED | NEEDS_MORE_DATA
        quality_score: 0.0 - 100.0
        issues: list of issue descriptions
        metrics: detailed breakdown metrics
    """
    from backend.crawl.dex import symbol_dir  # lazy: dex <-> store vòng import (dex nạp store ở đầu file)
    s_dir = symbol_dir(symbol, data_root)
    if not os.path.isdir(s_dir):
        return {
            "symbol": symbol,
            "status": DataQualityStatus.BLOCKED,
            "quality_score": 0.0,
            "issues": [f"Thư mục dữ liệu {symbol} không tồn tại"],
            "metrics": {"total_bars": 0, "total_ticks": 0},
        }

    verified_warnings: List[str] = []  # cảnh báo không chặn, gộp vào kết quả cuối

    # Phase 1 Gate Check: metadata nguồn gốc (attrs["nora"] của pkl) phải tồn tại và synthetic == False
    manifest = manifest_of_dir(s_dir)

    if manifest is None:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.BLOCKED,
            "quality_score": 0.0,
            "issues": [f"Chặn chạy: {symbol} thiếu metadata (attrs) kiểm định nguồn gốc dữ liệu"],
            "metrics": {"total_bars": 0, "total_ticks": 0},
        }

    if manifest.get("synthetic", True) is True:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.BLOCKED,
            "quality_score": 0.0,
            "issues": [f"Chặn chạy: {symbol} được đánh dấu dữ liệu nhân tạo (synthetic=true)"],
            "metrics": {"total_bars": 0, "total_ticks": 0},
        }

    # 1. crawl_ok check
    if manifest.get("crawl_ok") is False:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.BLOCKED,
            "quality_score": 0.0,
            "issues": [f"Chặn chạy: Quá trình crawl dữ liệu của {symbol} bị lỗi (crawl_ok=False)"],
            "metrics": {"total_bars": 0, "total_ticks": 0},
        }

    # 2. coverage_days check (tối thiểu 30 ngày)
    coverage_days = float(manifest.get("coverage_days", 0.0))
    if coverage_days <= 0.0 and manifest.get("start_ts") and manifest.get("end_ts"):
        coverage_days = (manifest["end_ts"] - manifest["start_ts"]) / 86_400_000.0
    if coverage_days < 30.0:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.NEEDS_MORE_DATA,
            "quality_score": 30.0,
            "issues": [f"Chặn chạy: Thời gian dữ liệu của {symbol} ({coverage_days:.1f} ngày) chưa đủ ngưỡng tối thiểu 30 ngày (NEEDS_MORE_DATA)"],
            "metrics": {"coverage_days": coverage_days},
        }

    # 3. Kiểm tra nến 1m
    from backend.crawl.dex import load_candle_df  # lazy: dex <-> store vòng import (dex nạp store ở đầu file)
    df_1m = load_candle_df(symbol, "1m", data_root)
    if df_1m is None or df_1m.empty:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.BLOCKED,
            "quality_score": 0.0,
            "issues": [f"Chặn chạy: Có manifest nhưng thiếu nến 1m của {symbol}"],
            "metrics": {"total_bars": 0},
        }

    # 4. Toàn vẹn 1m: digest_1m (blake2b byte numpy, nhanh); metadata cũ chưa có digest -> sha256 CSV như trước (chuyển tiếp)
    manifest_digest = manifest.get("digest_1m")
    if manifest_digest:
        actual_digest = compute_df_digest(df_1m)
        if actual_digest != manifest_digest:
            return {
                "symbol": symbol,
                "status": DataQualityStatus.BLOCKED,
                "quality_score": 0.0,
                "issues": [f"Chặn chạy: digest_1m không khớp giữa 1m.pkl và metadata của {symbol}"],
                "metrics": {"manifest_digest": manifest_digest, "actual_digest": actual_digest},
            }
    elif manifest.get("sha256_1m"):
        manifest_sha = manifest["sha256_1m"]
        actual_sha = compute_df_sha256(df_1m)
        if actual_sha != manifest_sha:
            return {
                "symbol": symbol,
                "status": DataQualityStatus.BLOCKED,
                "quality_score": 0.0,
                "issues": [f"Chặn chạy: sha256 không khớp giữa 1m.pkl và metadata của {symbol}"],
                "metrics": {"manifest_sha": manifest_sha, "actual_sha": actual_sha},
            }

    # 5. Không có timestamp trùng lặp trong 1m
    if df_1m["open_time"].duplicated().any():
        return {
            "symbol": symbol,
            "status": DataQualityStatus.BLOCKED,
            "quality_score": 0.0,
            "issues": [f"Chặn chạy: Phát hiện timestamp trùng lặp trong nến 1m của {symbol}"],
            "metrics": {"total_bars": len(df_1m)},
        }

    # 6. Tỉ lệ nến điền (filled_ratio) không vượt ngưỡng MAX_FILLED_RATIO_1M
    filled_ratio = float(manifest.get("filled_ratio_1m", 0.0))
    if "is_filled" in df_1m.columns:
        filled_ratio = float((df_1m["is_filled"] == 1).mean())
    if filled_ratio > MAX_FILLED_RATIO_1M:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.BLOCKED,
            "quality_score": 10.0,
            "issues": [f"Chặn chạy: Tỉ lệ nến điền (filled_ratio={filled_ratio*100:.1f}%) vượt ngưỡng {MAX_FILLED_RATIO_1M*100:.0f}%"],
            "metrics": {"filled_ratio": filled_ratio},
        }

    # 7. Bước nhảy giá > 50% trong 1 phút.
    #    - Dữ liệu CEX chính thức (Binance data.binance.vision đã kiểm checksum, hoặc API chính thức của sàn — OKX history-candles): đây là
    #      sự kiện thị trường THẬT (vd. cú sập thanh lý 2025-10-10) -> WARNING + liệt kê thời điểm,
    #      KHÔNG chặn (loại sự kiện rủi ro thật khỏi backtest làm Monte Carlo lạc quan sai).
    #    - Nguồn khác (DEX / chưa kiểm chứng): có thể là lỗi dữ liệu -> chặn.
    pct_1m = df_1m["close"].pct_change().abs()
    jump_mask = pct_1m > 0.50
    if jump_mask.any():
        verified_cex = str(manifest.get("venue", "")).lower() == "cex" and (manifest.get("checksums_verified") is True
                                                                           or manifest.get("official_api") is True)
        if not verified_cex:
            return {
                "symbol": symbol,
                "status": DataQualityStatus.BLOCKED,
                "quality_score": 10.0,
                "issues": ["Chặn chạy: Phát hiện bước nhảy giá bất thường > 50% trong 1 phút"],
                "metrics": {"max_1m_jump": float(pct_1m.max())},
            }
        jump_times = pd.to_datetime(df_1m.loc[jump_mask, "open_time"], unit="ms", utc=True)
        extreme_moves = [f"{t:%Y-%m-%d %H:%M}Z" for t in jump_times]
        verified_warnings.append(
            f"Cảnh báo: {len(extreme_moves)} phút có biến động > 50% (dữ liệu CEX chính thức, "
            f"giữ lại như sự kiện thật): {', '.join(extreme_moves[:5])}{' …' if len(extreme_moves) > 5 else ''}"
        )

    # 8. So resample: mọi khung đang có (bắt buộc 4h), O/H/L/C sai số tương đối < 1e-9, volume < 1e-6

    for check_tf in ["4h", "15m", "1h", "5m"]:
        df_stored = load_candle_df(symbol, check_tf, data_root)
        if check_tf == "4h" and (df_stored is None or df_stored.empty):
            # Engine Studio/WFA dùng 1m + 4h -> thiếu 4h là không chạy được, phải chặn
            return {
                "symbol": symbol,
                "status": DataQualityStatus.BLOCKED,
                "quality_score": 0.0,
                "issues": [f"Chặn chạy: {symbol} thiếu nến 4h (bắt buộc cho engine 1m + 4h)"],
                "metrics": {"total_bars": len(df_1m)},
            }
        if df_stored is not None and not df_stored.empty:
            resampled = resample_from_1m(df_1m, check_tf)
            merged_check = pd.merge(resampled, df_stored, on="open_time", suffixes=("_resampled", "_stored"))
            if merged_check.empty or len(merged_check) != len(df_stored):
                return {
                    "symbol": symbol,
                    "status": DataQualityStatus.BLOCKED,
                    "quality_score": 0.0,
                    "issues": [f"Chặn chạy: Timestamps giữa 1m resample và {check_tf} lưu trữ không khớp"],
                    "metrics": {"resampled_bars": len(resampled), "stored_bars": len(df_stored)},
                }
            for c in ["open", "high", "low", "close"]:
                rel_err = ((merged_check[f"{c}_resampled"] - merged_check[f"{c}_stored"]).abs() / merged_check[f"{c}_stored"].abs().clip(lower=1e-300)).max()
                if rel_err > 1e-9:
                    return {
                        "symbol": symbol,
                        "status": DataQualityStatus.BLOCKED,
                        "quality_score": 0.0,
                        "issues": [f"Chặn chạy: Resample 1m sang {check_tf} lệch cột {c} (sai số tương đối: {rel_err:.6e} > 1e-9)"],
                        "metrics": {f"rel_diff_{check_tf}_{c}": float(rel_err)},
                    }
            vol_diff = (merged_check["volume_resampled"] - merged_check["volume_stored"]).abs().max()
            if vol_diff > 1e-6:
                return {
                    "symbol": symbol,
                    "status": DataQualityStatus.BLOCKED,
                    "quality_score": 0.0,
                    "issues": [f"Chặn chạy: Resample 1m sang {check_tf} lệch volume (max diff: {vol_diff:.6e} > 1e-6)"],
                    "metrics": {f"diff_{check_tf}_vol": float(vol_diff)},
                }

    # Load candles if not provided
    if df_candles is None or df_candles.empty:
        from backend.crawl.dex import load_candle_df  # lazy: dex <-> store vòng import (dex nạp store ở đầu file)
        df_candles = load_candle_df(symbol, timeframe, data_root)
    
    # Load ticks if not provided
    if df_ticks is None or df_ticks.empty:
        from backend.crawl.dex import load_ticks_df  # lazy: dex <-> store vòng import (dex nạp store ở đầu file)
        df_ticks = load_ticks_df(symbol, data_root)

    total_ticks = len(df_ticks) if df_ticks is not None else 0
    total_bars = len(df_candles) if df_candles is not None else 0

    issues: List[str] = []
    penalties: float = 0.0

    # 1. Check sample size
    if total_bars < 30 and total_ticks < 100:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.NEEDS_MORE_DATA,
            "quality_score": 35.0,
            "issues": ["Dữ liệu quá mỏng (dưới 30 nến / 100 ticks), chưa đủ để kết luận định lượng"],
            "metrics": {
                "total_bars": total_bars,
                "total_ticks": total_ticks,
                "time_span_days": 0.0,
            },
        }

    # 2. Analyze Candle Structure
    zero_vol_pct = 0.0
    max_gap_hours = 0.0
    time_span_days = 0.0
    outlier_count = 0
    noise_ratio = 0.0

    if total_bars > 0 and "close" in df_candles.columns:
        # Time span calculation
        t_min = df_candles["open_time"].min()
        t_max = df_candles["open_time"].max()
        time_span_days = max(0.01, (t_max - t_min) / (1000 * 86400))

        # Check zero / flat volume
        if "volume" in df_candles.columns:
            zero_vol_count = (df_candles["volume"] <= 0).sum()
            zero_vol_pct = float(zero_vol_count / total_bars * 100.0)
            if zero_vol_pct > 30.0:
                penalties += min(30.0, zero_vol_pct * 0.6)
                issues.append(f"Tỷ lệ nến rỗng (volume = 0) cao: {zero_vol_pct:.1f}%")

        # Check timestamp continuity / gaps
        diffs = df_candles["open_time"].diff().dropna()
        if not diffs.empty:
            expected_step = diffs.median()
            large_gaps = diffs[diffs > expected_step * 3]
            if len(large_gaps) > 0:
                max_gap_hours = float(diffs.max() / (1000 * 3600))
                penalties += min(25.0, len(large_gaps) * 4.0)
                issues.append(f"Phát hiện {len(large_gaps)} khoảng trống dữ liệu (gap lớn nhất: {max_gap_hours:.1f} giờ)")

        # Check price anomalies / extreme outliers
        returns = df_candles["close"].pct_change().dropna()
        if not returns.empty:
            std_ret = returns.std()
            if std_ret > 0:
                extreme_jumps = returns[returns.abs() > 0.50]  # > 50% in single bar
                outlier_count = len(extreme_jumps)
                if outlier_count > 0:
                    penalties += min(30.0, outlier_count * 8.0)
                    issues.append(f"Có {outlier_count} biến động giá đột biến bất thường (>50% trong 1 bar)")

            # High noise estimation: Parkinson volatility vs return volatility
            high_low_ratio = (df_candles["high"] / (df_candles["low"] + 1e-9) - 1.0).mean()
            abs_ret_mean = returns.abs().mean()
            if abs_ret_mean > 0:
                noise_ratio = float(high_low_ratio / (abs_ret_mean + 1e-9))
                if noise_ratio > 3.5:
                    penalties += 10.0
                    issues.append("Độ nhiễu bóng nến (high-low spread) lớn so với bước giá thực")

    # 3. Analyze Tick Density & Microstructure (Tick-Native)
    inter_trade_median_sec = 0.0
    inter_trade_p95_sec = 0.0
    trades_per_day = 0.0
    dup_timestamp_rate = 0.0
    estimated_slippage_pct = 0.15  # baseline 0.15%
    buy_sell_imbalance = 0.0

    if total_ticks > 0 and df_ticks is not None and not df_ticks.empty:
        if time_span_days <= 0.0 and "timestamp_ms" in df_ticks.columns:
            t_min = df_ticks["timestamp_ms"].min()
            t_max = df_ticks["timestamp_ms"].max()
            time_span_days = max(0.01, (t_max - t_min) / (1000 * 86400))

        trades_per_day = float(total_ticks / max(0.01, time_span_days))

        # Inter-trade intervals
        if "timestamp_ms" in df_ticks.columns:
            sorted_ts = df_ticks["timestamp_ms"].sort_values().values
            diff_sec = np.diff(sorted_ts) / 1000.0
            if len(diff_sec) > 0:
                inter_trade_median_sec = float(np.median(diff_sec))
                inter_trade_p95_sec = float(np.percentile(diff_sec, 95))

                if inter_trade_p95_sec > 7200:  # > 2h gap
                    penalties += min(20.0, (inter_trade_p95_sec / 3600) * 2.0)
                    issues.append(f"Khoảng cách giữa các lệnh giao dịch lớn (p95: {inter_trade_p95_sec / 60:.1f} phút)")

            # Check duplicates
            dup_ts_count = int(pd.Series(sorted_ts).duplicated().sum())
            dup_timestamp_rate = float(dup_ts_count / total_ticks)

        # Slippage estimation based on trade activity and trade sizes
        if "volume_usd" in df_ticks.columns:
            med_vol = float(df_ticks["volume_usd"].median())
            if med_vol < 20.0:
                estimated_slippage_pct = 0.75
                penalties += 12.0
                issues.append("Kích thước lệnh giao dịch USD trung bình thấp (< $20), pool có thanh khoản mỏng")
            elif med_vol < 100.0:
                estimated_slippage_pct = 0.40
            else:
                estimated_slippage_pct = 0.20

        # Buy / Sell imbalance
        if "side" in df_ticks.columns:
            buys = float(np.sum(df_ticks["side"] == "buy"))
            sells = float(np.sum(df_ticks["side"] == "sell"))
            buy_sell_imbalance = float(abs(buys - sells) / max(1.0, buys + sells))
            if buy_sell_imbalance > 0.65:
                penalties += 10.0
                issues.append(f"Mất cân bằng chiều giao dịch mua/bán on-chain cao ({buy_sell_imbalance * 100:.1f}%)")

        if total_ticks < 100:
            penalties += 25.0
            issues.append("Số lượng tick giao dịch quá mỏng (< 100 trades), trượt giá thực tế sẽ rất cao")

    # Sample check for status
    if total_ticks < 50 and total_bars < 20:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.NEEDS_MORE_DATA,
            "quality_score": 30.0,
            "issues": ["Dữ liệu quá mỏng (dưới 50 ticks), cần thu thập thêm lịch sử on-chain"],
            "metrics": {
                "total_bars": int(total_bars),
                "total_ticks": int(total_ticks),
                "time_span_days": round(time_span_days, 1),
                "zero_volume_pct": round(zero_vol_pct, 1),
                "max_gap_hours": round(max_gap_hours, 1),
                "outlier_count": int(outlier_count),
                "noise_ratio": round(noise_ratio, 2),
                "inter_trade_median_sec": round(inter_trade_median_sec, 1),
                "inter_trade_p95_sec": round(inter_trade_p95_sec, 1),
                "trades_per_day": round(trades_per_day, 1),
                "estimated_slippage_pct": round(estimated_slippage_pct, 3),
            },
        }

    # Calculate final quality score
    base_score = 100.0 - penalties
    quality_score = max(5.0, min(100.0, base_score))

    # Determine status
    if quality_score >= 75.0 and len(issues) <= 1:
        status = DataQualityStatus.APPROVED
    elif quality_score >= 50.0:
        status = DataQualityStatus.WARNING
    else:
        status = DataQualityStatus.BLOCKED

    if verified_warnings:
        issues = list(issues) + verified_warnings
        if status == DataQualityStatus.APPROVED:
            status = DataQualityStatus.WARNING

    return {
        "symbol": symbol,
        "status": status,
        "quality_score": round(quality_score, 1),
        "issues": issues if issues else ["Dữ liệu liên tục, sạch và đạt chuẩn kiểm định"],
        "metrics": {
            "total_bars": int(total_bars),
            "total_ticks": int(total_ticks),
            "time_span_days": round(time_span_days, 1),
            "zero_volume_pct": round(zero_vol_pct, 1),
            "max_gap_hours": round(max_gap_hours, 1),
            "outlier_count": int(outlier_count),
            "noise_ratio": round(noise_ratio, 2),
            "inter_trade_median_sec": round(inter_trade_median_sec, 1),
            "inter_trade_p95_sec": round(inter_trade_p95_sec, 1),
            "trades_per_day": round(trades_per_day, 1),
            "estimated_slippage_pct": round(estimated_slippage_pct, 3),
            "dup_timestamp_rate": round(dup_timestamp_rate, 4),
            "buy_sell_imbalance": round(buy_sell_imbalance, 3),
        },
    }


_WARNED: set = set()


class DataQualityError(RuntimeError):
    """Dữ liệu của ít nhất một tài sản không đạt quality gate (BLOCKED / NEEDS_MORE_DATA) -> từ chối chạy."""


def require_data_ok(symbols, data_root: Optional[str] = None, timeframe: str = "1m", logger=None) -> Dict[str, Dict[str, Any]]:
    """Cổng dữ liệu BẮT BUỘC cho mọi đường sổ chiến lược (backtest danh mục, dựng sổ, WFA, feed giả lập, tối ưu alpha).

    Chạy `evaluate_data_quality` cho từng ký hiệu (kết quả có cache theo (mtime_ns, size) của file tài sản, nên gọi lại rẻ).
    BLOCKED / NEEDS_MORE_DATA -> ném DataQualityError (tiếng Việt, liệt kê vấn đề từng tài sản, KHÔNG nới gate).
    WARNING được phép chạy nhưng ghi log. Trả {symbol: kết quả gate}."""
    import logging
    log = logger or logging.getLogger("nora.data_gate")
    out: Dict[str, Dict[str, Any]] = {}
    bad: List[str] = []
    t0 = time.time()
    for sym in dict.fromkeys(str(s) for s in (symbols or [])):
        dq = evaluate_data_quality(sym, timeframe=timeframe, data_root=data_root)
        out[sym] = dq
        status = dq.get("status")
        if status in (DataQualityStatus.BLOCKED, DataQualityStatus.NEEDS_MORE_DATA):
            bad.append(f"  - {sym} [{status}]: " + "; ".join(str(i) for i in dq.get("issues") or []))
        elif status == DataQualityStatus.WARNING:
            msg = f"[data-gate] {sym}: WARNING — " + "; ".join(str(i) for i in dq.get("issues") or [])
            if msg not in _WARNED:   # PortfolioEngine gọi lại mỗi job: chỉ ghi log một lần mỗi tiến trình
                _WARNED.add(msg)
                log.warning(msg)   # stderr qua logging (lastResort) -> có trong out.log của job
    if time.time() - t0 > 0.5:   # vừa đọc/so khớp 1m thật: trả heap đã giải phóng về OS (tiến trình cha sắp fork pool)
        import gc
        gc.collect()
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except OSError:
            pass
    if bad:
        raise DataQualityError("Dữ liệu không đạt kiểm định chất lượng (quality gate) — từ chối chạy:\n" + "\n".join(bad))
    return out


def require_data_ok_or_exit(symbols, data_root: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Như require_data_ok nhưng cho CLI: lỗi -> SystemExit(thông điệp) (không in traceback)."""
    try:
        return require_data_ok(symbols, data_root)
    except DataQualityError as exc:
        raise SystemExit(str(exc)) from None


# ── Promote staging -> data ───────────────────────────────────────────────────────────────────
# Chuyển tài sản đã crawl từ vùng đệm (cache_staging_dir) sang data/<sàn>/<venue>/<SYM> — chỉ khi qua quality gate.
#
# sàn (okx | binance) và venue ("cex" | "dex") lấy từ metadata (attrs) của pkl; xem backend/crawl/store.py.
#
# Job API `data_promote` (POST /api/data/promote -> optimize/process/process.py -> run_job). Mặc định chỉ lập kế hoạch (dry-run); apply=True để thực hiện.
#
# - Tài sản trong staging qua gate (không BLOCKED / NEEDS_MORE_DATA) -> chuyển vào data/<sàn>/<venue>/<SYM>
#   (thư mục cùng tên ở data/ được cất vào _archive_invalid trước).
# - archive_legacy=True: cất mọi thư mục tài sản trong data/<sàn>/ KHÔNG có metadata (attrs)
#   vào data/_archive_invalid/legacy_<ngày>/ (không xoá).
#

# staging=None: quét `<cache/process>/<job>/staging/` của các job crawl (+ vùng đệm chung cache/process/_staging nếu còn); data=None: gốc market/<sàn> của helper.
DEFAULTS = {"staging": None, "data": None, "apply": False, "archive_legacy": False}
STAGING_SUBDIR = "staging"      # khớp optimize/process/process.STAGING_SUBDIR


def _staging_roots() -> List[str]:
    """Các gốc staging mặc định: cache/process/<job>/staging (crawl ghi thẳng vào thư mục process của job) + cache_staging_dir() nếu tồn tại."""
    roots = []
    base = cache_process_dir()
    if os.path.isdir(base):
        roots += [p for p in (os.path.join(base, n, STAGING_SUBDIR) for n in sorted(os.listdir(base))) if os.path.isdir(p)]
    legacy = cache_staging_dir()
    if os.path.isdir(legacy):
        roots.append(legacy)
    return roots


def _move_atomic(src: str, dst: str) -> None:
    """Chuyển thư mục tài sản: os.replace sang tên tạm cạnh đích rồi đổi tên (cùng filesystem = nguyên tử); khác filesystem thì chép vào tên tạm trước."""
    parent = os.path.dirname(dst)
    os.makedirs(parent, exist_ok=True)
    tmp = os.path.join(parent, f".promote_{os.getpid()}_{os.path.basename(dst)}")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        os.rename(src, tmp)
    except OSError:
        shutil.copytree(src, tmp)
        shutil.rmtree(src, ignore_errors=True)
    os.rename(tmp, dst)

BLOCKING = (DataQualityStatus.BLOCKED, DataQualityStatus.NEEDS_MORE_DATA)


def run_job(params=None):
    """Lập kế hoạch (và nếu apply=True thì thực hiện) chuyển tài sản đã qua gate từ staging sang data -> {"actions", "applied"}."""
    args = options(DEFAULTS, params)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_home = args.data or os.path.join(data_home(), "market")
    archive_root = os.path.join(archive_home, "_archive_invalid", f"legacy_{stamp}")
    actions = []
    staging_roots = [args.staging] if args.staging else _staging_roots()

    def _market(ex: str) -> str:   # data tường minh = gốc cũ <data>/<sàn>; mặc định = market_root(sàn)
        return os.path.join(args.data, ex) if args.data else market_root(ex)

    for staging in staging_roots:
        for item in list_assets(staging):
            sym = item["qualified"]
            dq = evaluate_data_quality(sym, timeframe="1m", data_root=staging)
            m = read_manifest(sym, data_root=staging) or {}
            venue = str(m.get("venue") or "").lower()
            if venue not in VENUES:
                print(f"[skip]    {sym:6s} metadata thiếu venue hợp lệ ('{venue}')")
                continue
            info = (f"venue={m.get('venue')} days={m.get('coverage_days')} filled={m.get('filled_ratio_1m')} "
                    f"crawl_ok={m.get('crawl_ok')} gate={dq['status']}")
            if dq["status"] in BLOCKING:
                print(f"[skip]    {sym:6s} {info} issues={dq['issues']}")
                continue
            ex = exchange_of(m)
            print(f"[promote] {sym:6s} {ex} {info}")
            rel = os.path.join(*item["symbol"].split("@", 1))          # BTC@perp -> BTC/perp
            dst = os.path.join(_market(ex), venue, rel)
            if os.path.exists(dst):
                actions.append(("archive", dst, os.path.join(archive_root, ex, venue, rel)))
            actions.append(("move", item["path"], dst))

    if args.archive_legacy:
        promoted = {a[2] for a in actions if a[0] == "move"}
        for ex in EXCHANGES:
            for item in list_assets(_market(ex)):
                sym, path = item["symbol"], item["path"]
                if item["venue"] == "legacy" or asset_meta(path)["dataset"] is None:
                    if path in promoted:
                        continue
                    if not any(a[0] == "archive" and a[1] == path for a in actions):
                        actions.append(("archive", path, os.path.join(archive_root, ex, item["venue"], sym)))

    for kind, src, dst in actions:
        print(f"  {kind:7s} {src} -> {dst}")
        if args.apply:
            _move_atomic(src, dst)
    if args.apply and not args.staging:   # tài sản đã chuyển hết khỏi staging của job -> xoá staging (file tạm crawl); tài sản bị gate chặn thì giữ lại
        for staging in staging_roots:
            if os.path.basename(staging) == STAGING_SUBDIR and not list_assets(staging):
                shutil.rmtree(staging, ignore_errors=True)
    if not args.apply:
        print("\n(dry-run) Đặt apply=True để thực hiện.")
    out = {"actions": [{"kind": k, "src": a, "dst": b} for k, a, b in actions], "applied": bool(args.apply)}
    write_job_result(out)
    return out


# Kho mmap dùng chung (core/data/shared.py cũ: plan/load/fill/export/remove/size_mb) đã chuyển sang backend/optimize/search/evaluate.py
# (engine-API pass: bộ đệm TỐC ĐỘ của engine, không phải I/O dữ liệu gốc; cạnh SharedExporter).


# ══════════════════════════════════════════════════════════════════════════
# Nhận diện tài sản theo thư mục dữ liệu (engine-API pass: từ nautilus/engine.py khối dex và models/params.data_symbol — chúng đọc đĩa nên không thuộc core).
# ══════════════════════════════════════════════════════════════════════════

def base_name(symbol: str) -> str:
    """Tên gốc (không venue / hậu tố @perp) của ký hiệu."""
    return parse_symbol(split_instrument(symbol)[0])[1]


def data_symbol(symbol: str, market: str) -> Tuple[str, str]:
    """Ký hiệu dữ liệu thực dùng cho backtest: perp -> '<SYM>@perp' nếu có dữ liệu perp thật.

    Trả (symbol_dữ_liệu, nguồn_giá): 'perp' | 'spot_proxy' | 'spot'.
    """
    base, _ = split_instrument(symbol)
    if market != "perp":
        return base, "spot"
    perp = f"{base}@perp"
    return (perp, "perp") if resolve_asset_dir(perp) else (base, "spot_proxy")


def is_dex_symbol(symbol: str, data_root: Optional[str] = None) -> bool:
    """'dex:AERO' -> DEX; 'BTC@perp' / 'cex:...' -> không; tên trần: perp có dữ liệu thì là perp (tương thích cũ), không thì DEX nếu có dex/<TÊN>."""
    if split_instrument(symbol)[1]:
        return False
    venue, name = parse_symbol(symbol)
    if venue:
        return venue == "dex"
    root = data_root or default_data_root()
    if resolve_asset_dir(f"cex:{name}@perp", data_root=root):
        return False
    return os.path.isdir(os.path.join(root, "dex", name))


def classify_symbols(symbols: List[str], data_root: Optional[str] = None) -> Tuple[List[str], str]:
    """Ký hiệu người dùng -> (ký hiệu engine, venue): perp -> 'BTC@perp' (như cũ); DEX -> 'dex:AERO'. Trộn perp với DEX -> ValueError."""
    dex = [is_dex_symbol(s, data_root) for s in symbols]
    if any(dex) and not all(dex):
        raise ValueError("không chạy chung tài sản perp (CEX) với tài sản DEX trong một lần backtest — chọn một loại")
    if all(dex) and dex:
        out = []
        for s in symbols:
            q = f"dex:{parse_symbol(s)[1]}"
            if q not in out:
                out.append(q)
        return out, "dex"
    return [s if "@" in s else f"{s}@perp" for s in symbols], "cex"


def require_perp(symbols: List[str], what: str) -> None:
    """WFA / phễu chỉ chạy perp: tài sản DEX (spot AMM, dữ liệu ngắn) chưa có quy trình kiểm định -> từ chối rõ ràng."""
    bad = [s for s in symbols if is_dex_symbol(str(s))]
    if bad:
        raise ValueError(f"{what} chưa hỗ trợ tài sản DEX {bad}: chỉ perp (CEX). Backtest đơn (book_backtest) có hỗ trợ DEX")


# ══════════════════════════════════════════════════════════════════════════
# Nạp dữ liệu và cấu hình phục vụ chạy pipeline (P11 D2.3: chuyển từ process/tasks)
# ══════════════════════════════════════════════════════════════════════════

def default_universe() -> List[str]:
    """Rổ mặc định = mọi tài sản perp CEX có trong kho dữ liệu của sàn đang dùng (OKX), tên cơ sở đã sắp xếp."""
    return sorted({a["symbol"].split("@")[0] for a in list_assets() if a["venue"] == "cex" and a.get("instrument") == "perp"})


def default_window() -> Tuple[str, str]:
    """(start, end) 'YYYY-MM-DD' = phần dữ liệu chung của cả rổ: sau nến đầu muộn nhất 1 ngày, trước nến cuối sớm nhất 1 ngày."""
    firsts, lasts = [], []
    for n in default_universe():
        m = read_manifest(f"{n}@perp") or {}
        if m.get("start_ts") and m.get("end_ts"):
            firsts.append(int(m["start_ts"]))
            lasts.append(int(m["end_ts"]))
    if not firsts:
        raise ValueError("Kho dữ liệu chưa có manifest (start_ts/end_ts) cho rổ mặc định")
    return iso_date(max(firsts) + DAY_MS), iso_date(min(lasts) - DAY_MS)


def run_defaults() -> Dict[str, object]:
    start, end = default_window()
    return {"symbols": [f"{n}@perp" for n in default_universe()], "start": start, "end": end,
            "train_ratio": DEFAULT_TRAIN_RATIO, "initial_capital": DEFAULT_CAPITAL}



def resolve_symbols(symbols: Optional[List[str]]) -> List[str]:
    """Tên cơ sở (BTC, ETH, ...) của rổ: `symbols` nếu có, không thì default_universe()."""
    if symbols:
        return list(dict.fromkeys(base_name(s) for s in symbols))
    names = default_universe()
    if not names:
        raise ValueError("Kho dữ liệu chưa có tài sản perp nào")
    return names


def check_data(data_symbols: List[str]) -> None:
    missing = [s for s in data_symbols if not resolve_asset_dir(s)]
    if missing:
        have = sorted({a["symbol"] for a in list_assets()})
        raise ValueError(f"Không có dữ liệu sàn {exchange()} cho {missing}; tài sản có: {have}")


def data_info(data_symbols: List[str], start: int, end: int, source: str) -> Tuple[Dict[str, Any], List[str]]:
    warns, sha = [], {}
    for s in data_symbols:
        m = read_manifest(s) or {}
        sha[s] = m.get("sha256_1m")
        if m.get("start_ts") and start < int(m["start_ts"]):
            warns.append(f"{s}: dữ liệu bắt đầu {iso_date(int(m['start_ts']))}, sau start {iso_date(start)} — giữ tiền mặt tới nến đầu có dữ liệu")
        if m.get("end_ts") and end - DAY_MS > int(m["end_ts"]):
            warns.append(f"{s}: dữ liệu kết thúc {iso_date(int(m['end_ts']))}, trước end {iso_date(end - DAY_MS)}")
    return {"source": source, "sha256_1m": sha}, warns


def load_samples(path: Optional[str] = None) -> List[Dict[str, Any]]:
    with open(path or alpha_education_samples(), encoding="utf-8") as fh:
        return json.load(fh)



def load_report(report_dir):
    """(stage_a, report) từ thư mục lần chạy build_strategy_book."""
    with open(os.path.join(report_dir, "stage_a.json"), encoding="utf-8") as fh:
        stage_a = json.load(fh)
    with open(os.path.join(report_dir, "report.json"), encoding="utf-8") as fh:
        report = json.load(fh)
    return stage_a, report


_FRAME_ORDER = ("24h", "4h", "1h", "15m", "5m", "1m")


def _clean(df: pd.DataFrame, drop_filled: bool = True) -> pd.DataFrame:
    out = df.copy()
    if drop_filled and "is_filled" in out.columns:
        out = out[pd.to_numeric(out["is_filled"], errors="coerce").fillna(0).astype(int) == 0].reset_index(drop=True)
    return out


def daily_close(symbol: str, end: int) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """(nhãn đóng ngày ms, giá đóng cửa ngày) của tài sản từ đầu lịch sử tới `end`; khung 24h nếu có, không thì gộp từ khung nhỏ hơn. None nếu không có dữ liệu."""
    for frame in _FRAME_ORDER:
        try:
            df = _clean(CandleLoader(symbol, frame=frame, use_cache=True).load_data(0, end))
        except FileNotFoundError:
            continue
        if df.empty:
            continue
        t, c = df["open_time"].to_numpy(dtype="int64"), df["close"].to_numpy(dtype="float64")
        if frame != "24h":
            day = t // DAY_MS * DAY_MS
            keep = np.r_[day[1:] != day[:-1], True]            # nến cuối của mỗi ngày
            t, c = day[keep], c[keep]
        return t + DAY_MS, c
    return None


def load_prices(symbols: List[str], end: int) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """{ký hiệu dữ liệu (BTC, BTC@perp, ...): (nhãn ngày, giá đóng)} cho các tài sản đọc được."""
    out = {}
    for s in symbols:
        r = daily_close(s, end)
        if r is not None:
            out[str(s).split(":")[-1]] = r
    return out


def strategy_frames(symbols: List[str], timeframe: str, end: int, drop_filled: bool = False) -> Dict[str, pd.DataFrame]:
    """Nến khung chiến lược của từng tài sản từ đầu lịch sử tới `end` (chỉ báo như engine: gốc cố định); tài sản không đọc được bị bỏ qua.
    drop_filled=True khi khung chiến lược = khung chạy (engine bỏ nến điền ở khung chạy)."""
    out = {}
    for s in symbols:
        try:
            df = _clean(CandleLoader(s, frame=timeframe, use_cache=True).load_data(0, end), drop_filled)
        except FileNotFoundError:
            continue
        if not df.empty:
            out[str(s).split(":")[-1]] = df
    return out
