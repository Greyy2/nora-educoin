"""Crawl tick (swap on-chain EVM) của pool DEX trong cửa sổ trượt ngắn -> dex/<SYM>/ticks.parquet + manifest["ticks"] (nguồn "evm_swaps").

Chỉ DEX: tài sản CEX (OKX perp) chỉ có nến, không có tick. Tài sản phải có sẵn (nến đã crawl/promote); pool, mạng, tên cặp lấy từ manifest.json của nó.
Cửa sổ: mặc định DEFAULT_TICK_DAYS=3 ngày, tối đa MAX_TICK_DAYS=14 (vượt thì cắt về 14 và ghi vào `issues`); tick tích luỹ trong cửa sổ trượt, cũ hơn bị cắt khi lưu.

Hai cơ sở giá (manifest["ticks"]["price_basis"]): `price` = giá KHỚP gồm phí pool (cơ sở của nến GeckoTerminal — đã đối chiếu: nến GT theo token quote trùng giá khớp
cuối phút, median 0 bps; nến GT theo USD còn nhân thêm giá USD của token quote nên lệch vài chục bps) và `mid_price` = giá biên SAU swap (lệch ~phí pool so với giá khớp).
Mỗi dòng = một swap: timestamp_ms, block_number, log_index, tx_hash (= "<tx>:<logIndex>", khoá duy nhất), price (USD / 1 token gốc, THỰC KHỚP đã gồm phí pool),
amount (token gốc), volume_usd, side (taker "buy" khi token gốc RA khỏi pool), mid_price (giá biên của pool SAU swap theo dự trữ x quote_usd; NaN nếu không có Sync), reserve_base / reserve_quote (dự trữ pool SAU swap, đơn vị token, lấy từ
log Sync cùng tx ngay trước log Swap; NaN nếu không ghép được, vd. pool v3 không có Sync), quote_usd (USD / 1 token quote lúc đó).

Mọi tham số mạng nằm ở NETWORKS (ghi đè theo mạng bằng data/_meta/dex_networks.json): rpc_url, chain_id (kiểm tra bằng eth_chainId), log_span (kích thước ban đầu của đoạn
eth_getLogs — tự co đôi khi nút báo vượt giới hạn, nhớ cho phần còn lại), max_rps, batch_size (số lời gọi/JSON-RPC batch, tự co theo giới hạn của nút), eth_usd (nguồn giá ETH/USD cho quote WETH),
uniswap_v2_factories (factory đã biết là Uniswap v2 -> phí 0,3%).

Metadata pool đọc ON-CHAIN, cache vào dex/<SYM>/dex_pool.json["onchain"]: token0/token1 + symbol() + decimals(), token gốc (vế đầu của tên cặp "VVV / WETH"),
loại pool (stable() có -> Aerodrome v2: stable = x^3y+xy^3, volatile = x*y=k; factory thuộc uniswap_v2_factories -> Uniswap v2; còn lại null), phí
(Aerodrome: factory().getFee(pool, stable) đơn vị 1/10000; Uniswap v2 đã xác minh: 0,003; còn lại hoặc gọi lỗi: null kèm fee_note).

Thời gian KHÔNG giả định: (1) log có sẵn blockTimestamp (nút công khai Base có) -> dùng đúng giá trị đó; (2) không có -> lấy mẫu timestamp ở đầu, cuối và vài điểm giữa
cửa sổ: nếu tuyến tính chính xác (thời gian block là hằng số nguyên) thì nội suy; (3) ngược lại tra timestamp từng block riêng biệt (JSON-RPC batch).
Cách dùng được ghi ở manifest["ticks"]["ts_method"] (log_block_timestamp | linear_interpolation | per_block_lookup). Đầu cửa sổ = block đầu tiên có
timestamp >= (timestamp block mới nhất - days x 86400s), tìm bằng chia đôi trên timestamp thật.

Quote -> USD: stable (USDC/USDT/DAI... nhận theo symbol()) = 1; WETH x giá MỞ của phút chứa swap theo nguồn eth_usd của mạng (mặc định nến 1m ETH-USDT-SWAP
của OKX qua REST; không nhìn trước), nguồn ghi ở manifest["ticks"]["quote_usd_source"].

Job API `data_crawl_ticks` (POST /api/data/ticks/crawl -> api/jobs/runner.py -> run_job): params symbols ("AERO" / "dex:AERO"), days.
"""
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from backend.core.data import okx_crawler as okx
from backend.core.data.crawler import log
from backend.db.data_layout import DATA_HOME, default_data_root, parse_symbol, split_instrument
from backend.db.tick_storage import DEFAULT_TICK_DAYS, MAX_TICK_DAYS, save_ticks
from backend.utils.jobs import as_list, options, write_job_result

MINUTE_MS = 60_000
RPC_RETRIES = 6
TS_SAMPLES = 3                                  # điểm lấy mẫu giữa đầu và cuối cửa sổ để kiểm tra timestamp tuyến tính
NETWORKS: Dict[str, Dict[str, Any]] = {
    "base": {
        "rpc_url": "https://mainnet.base.org", "chain_id": 8453, "log_span": 2000, "max_rps": 8, "batch_size": 10,
        "eth_usd": {"source": "okx_candles", "symbol": "ETH"},
        "uniswap_v2_factories": ["0x8909dc15e40173ff4699343b6eb8132c65e18ec6"],
    },
}

# topic0 = keccak256(chữ ký sự kiện) — hằng số giao thức (đã đối chiếu với log thật của pool Aerodrome trên Base)
SWAP_V2_TOPICS = (
    "0xb3e2773606abfd36b5bd91394b3a54d1398336c65005baf7bf7a05efeffaf75b",   # Aerodrome v2: Swap(address,address,uint256,uint256,uint256,uint256)
    "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822",   # Uniswap v2:   Swap(address,uint256,uint256,uint256,uint256,address)
)
SWAP_V3_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"   # Uniswap v3 / Slipstream: Swap(address,address,int256,int256,uint160,uint128,int24)
SYNC_TOPICS = (
    "0xcf2aa50876cdfbb541206f89af0ee78d44a2abf8d328e37fa4917f982149848a",   # Aerodrome v2: Sync(uint256,uint256)
    "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1",   # Uniswap v2:   Sync(uint112,uint112)
)
USD_QUOTES = {"USDC", "USDBC", "USDT", "DAI", "USDS", "LUSD"}
ETH_QUOTES = {"WETH", "ETH"}
FEE_UNIT = 10_000                               # PoolFactory.getFee trả theo 1/10000


def clamp_days(days: Any) -> Tuple[int, Optional[str]]:
    """Số ngày cửa sổ hợp lệ + ghi chú nếu bị cắt/đổi."""
    n = int(days or DEFAULT_TICK_DAYS)
    if n > MAX_TICK_DAYS:
        return MAX_TICK_DAYS, f"days={n} vượt tối đa {MAX_TICK_DAYS} -> dùng {MAX_TICK_DAYS}"
    if n < 1:
        return DEFAULT_TICK_DAYS, f"days={n} không hợp lệ -> dùng mặc định {DEFAULT_TICK_DAYS}"
    return n, None


def network_config(network: str) -> Dict[str, Any]:
    """Cấu hình của mạng: NETWORKS[network] ghi đè từng khoá bằng data/_meta/dex_networks.json {"base": {"rpc_url": ...}}."""
    cfg = {k: dict(v) for k, v in NETWORKS.items()}
    path = os.path.join(DATA_HOME, "_meta", "dex_networks.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            for name, over in json.load(fh).items():
                cfg[name] = {**cfg.get(name, {}), **over}
    if network not in cfg:
        raise ValueError(f"chưa hỗ trợ mạng {network!r} (có: {sorted(cfg)})")
    return cfg[network]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "nora-research/1.0"})
    return s


# ─── JSON-RPC ───────────────────────────────────────────────────────────────
class RpcRange(Exception):
    """eth_getLogs bị từ chối vì đoạn quá lớn (khoảng block hoặc số kết quả vượt giới hạn của nút) -> thu nhỏ đoạn."""


class Rpc:
    """JSON-RPC có nhịp (≤ max_rps request/giây) + thử lại backoff khi 429/5xx/timeout/rate-limit; hỗ trợ batch."""

    def __init__(self, url: str, max_rps: float = 8, session: Optional[requests.Session] = None):
        self.url, self.pause, self.session, self._last, self.batch_cap = url, 1.0 / float(max_rps), session or _session(), 0.0, None

    def _post(self, payload: Any) -> Any:
        for attempt in range(1, RPC_RETRIES + 1):
            time.sleep(max(0.0, self._last + self.pause - time.time()))
            self._last = time.time()
            try:
                resp = self.session.post(self.url, json=payload, timeout=30)
                if resp.status_code == 413:
                    raise RpcRange("HTTP 413 payload too large")
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.RequestException(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                body = resp.json()
            except RpcRange:
                raise
            except (requests.RequestException, ValueError) as exc:
                self._backoff(attempt, str(exc))
                continue
            errs = [b["error"] for b in body if "error" in b] if isinstance(body, list) else ([body["error"]] if "error" in body else [])
            if any(any(k in str(e.get("message", "")).lower() for k in ("rate", "too many", "timeout")) for e in errs):
                self._backoff(attempt, str(errs[0].get("message")))
                continue
            return body
        raise RuntimeError(f"RPC {self.url}: hết {RPC_RETRIES} lần thử")

    def call(self, method: str, params: List) -> Any:
        body = self._post({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        err = body.get("error")
        if not err:
            return body["result"]
        msg = str(err.get("message", "")).lower()
        if method == "eth_getLogs" and (err.get("code") in (-32614, -32005) or any(k in msg for k in ("range", "limit", "more than", "too large", "exceed"))):
            raise RpcRange(msg)
        raise RuntimeError(f"RPC {method} lỗi {err.get('code')}: {err.get('message')}")

    def batch(self, calls: List[Tuple[str, List]], size: int = 50) -> List[Any]:
        """Nhiều lời gọi trong ít request (mỗi request <= size, tự co theo "maximum N calls in 1 batch" của nút và nhớ); kết quả theo thứ tự `calls`; mục lỗi -> RuntimeError."""
        out: List[Any] = []
        i = 0
        while i < len(calls):
            size = min(size, self.batch_cap or size)
            chunk = calls[i:i + size]
            body = self._post([{"jsonrpc": "2.0", "id": j, "method": m, "params": p} for j, (m, p) in enumerate(chunk)])
            cap = re.search(r"maximum (\d+) calls", str(body.get("error", {}).get("message", ""))) if isinstance(body, dict) else None
            if cap:
                self.batch_cap = max(1, int(cap.group(1)))
                continue
            if not isinstance(body, list) or len(body) != len(chunk):
                raise RuntimeError(f"RPC batch: nút trả về không đúng dạng ({str(body)[:200]})")
            by_id = {b["id"]: b for b in body}
            for j, (m, _) in enumerate(chunk):
                if "error" in by_id[j]:
                    raise RuntimeError(f"RPC {m} lỗi {by_id[j]['error']}")
                out.append(by_id[j]["result"])
            i += len(chunk)
        return out

    @staticmethod
    def _backoff(attempt: int, why: str) -> None:
        wait = min(30, 2 * attempt)
        log(f"[warn] RPC {why} -> chờ {wait}s ({attempt}/{RPC_RETRIES})")
        time.sleep(wait)


def eth_call(rpc: Rpc, to: str, data: str) -> Optional[str]:
    """eth_call; None nếu hợp đồng revert hoặc không có hàm đó (kết quả rỗng)."""
    try:
        res = rpc.call("eth_call", [{"to": to, "data": data}, "latest"])
    except RuntimeError:
        return None
    return res if res and res != "0x" else None


def _block(rpc: Rpc, number: Any) -> Dict[str, Any]:
    return rpc.call("eth_getBlockByNumber", [number if isinstance(number, str) else hex(number), False])


def block_at_or_after(rpc: Rpc, ts: int, head: int) -> int:
    """Block đầu tiên có timestamp >= ts (chia đôi trên timestamp thật; timestamp tăng dần theo block)."""
    lo, hi = 0, head
    while lo < hi:
        mid = (lo + hi) // 2
        if int(_block(rpc, mid)["timestamp"], 16) >= ts:
            hi = mid
        else:
            lo = mid + 1
    return lo


# ─── Metadata pool on-chain ─────────────────────────────────────────────────
def _abi_str(hexdata: str) -> str:
    """symbol() trả string ABI hoặc bytes32 (token cũ)."""
    raw = bytes.fromhex(hexdata[2:])
    if len(raw) >= 96:
        n = int.from_bytes(raw[32:64], "big")
        return raw[64:64 + n].decode("utf-8", "replace")
    return raw.rstrip(b"\0").decode("utf-8", "replace")


def _addr(word: str) -> str:
    return "0x" + word[-40:].lower()


def read_pool_onchain(rpc: Rpc, pool: str, pool_name: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Đọc on-chain: token0/1 (symbol, decimals), token gốc, quote, loại pool (stable/volatile), phí. Trường không đọc được = None kèm ghi chú."""
    def need(to: str, data: str) -> str:
        res = eth_call(rpc, to, data)
        if res is None:
            raise RuntimeError(f"eth_call {data[:10]} tới {to} thất bại")
        return res
    tokens = [_addr(need(pool, sel)) for sel in ("0x0dfe1681", "0xd21220a7")]
    syms = [_abi_str(need(t, "0x95d89b41")).upper() for t in tokens]
    decs = [int(need(t, "0x313ce567"), 16) for t in tokens]
    want = pool_name.split("/")[0].strip().upper()
    if want in syms:
        base = syms.index(want)
    elif sum(s in USD_QUOTES | ETH_QUOTES for s in syms) == 1:
        base = [s in USD_QUOTES | ETH_QUOTES for s in syms].index(False)
    else:
        raise ValueError(f"không xác định được token gốc của pool {pool} ({syms}, tên {pool_name!r})")
    quote = syms[1 - base]
    if quote in USD_QUOTES:
        kind = "usd"
    elif quote in ETH_QUOTES:
        kind = "eth"
    else:
        raise ValueError(f"quote {quote!r} chưa hỗ trợ quy đổi USD (hỗ trợ {sorted(USD_QUOTES | ETH_QUOTES)})")
    stable_raw, factory_raw = eth_call(rpc, pool, "0x22be3de1"), eth_call(rpc, pool, "0xc45a0155")
    factory = _addr(factory_raw) if factory_raw else None
    fee, note, pool_type, stable = None, None, None, False
    if stable_raw is not None:
        pool_type, stable = "aerodrome_v2", int(stable_raw, 16) != 0
        fee_raw = eth_call(rpc, factory, "0xcc56b2c5" + pool[2:].rjust(64, "0") + format(int(stable), "064x")) if factory else None
        if fee_raw is not None:
            fee = int(fee_raw, 16) / FEE_UNIT
        else:
            note = "không đọc được PoolFactory.getFee (factory() hoặc getFee lỗi) -> fee_rate null"
    elif factory and factory in [f.lower() for f in cfg.get("uniswap_v2_factories", [])]:
        pool_type, fee = "uniswap_v2", 0.003
    else:
        note = "không nhận diện được loại pool (không có stable(), factory không thuộc uniswap_v2_factories) -> fee_rate null"
    return {"pool_address": pool, "checked_at": int(time.time()), "tokens": tokens, "symbols": syms, "decimals": decs, "base_index": base,
            "quote_symbol": quote, "quote_kind": kind, "pool_type": pool_type, "stable": stable, "factory": factory, "fee_rate": fee, "fee_note": note}


def pool_onchain(rpc: Rpc, asset_dir: str, pool: str, pool_name: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Metadata on-chain của pool, cache ở <asset_dir>/dex_pool.json["onchain"] (đọc lại khi đổi pool)."""
    path = os.path.join(asset_dir, "dex_pool.json")
    doc: Dict[str, Any] = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    cached = doc.get("onchain")
    if isinstance(cached, dict) and cached.get("pool_address") == pool:
        return cached
    doc["onchain"] = read_pool_onchain(rpc, pool, pool_name, cfg)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    os.replace(path + ".tmp", path)
    return doc["onchain"]


# ─── Giải mã Swap + Sync ────────────────────────────────────────────────────
def _words(data: str) -> List[int]:
    h = data[2:]
    return [int(h[i:i + 64], 16) for i in range(0, len(h), 64)]


def swap_flows(topic0: str, data: str) -> Tuple[int, int, int, int]:
    """(amount0In, amount1In, amount0Out, amount1Out) thô của một log Swap (v3: amount có dấu, dương = vào pool)."""
    w = _words(data)
    if topic0 == SWAP_V3_TOPIC:
        a0, a1 = [x - (1 << 256) if x >= (1 << 255) else x for x in w[:2]]
        return max(a0, 0), max(a1, 0), max(-a0, 0), max(-a1, 0)
    return w[0], w[1], w[2], w[3]


def decode_swaps(logs: List[Dict], info: Dict[str, Any]) -> pd.DataFrame:
    """Log (Swap + Sync) của pool -> tick, price theo ĐƠN VỊ QUOTE (chưa quy USD) và CHƯA có timestamp_ms (cột `block_ts` = giây từ log nếu có, NaN nếu không).

    Mỗi Swap ghép với log Sync CUỐI CÙNG cùng tx đứng trước nó (Aerodrome/Uniswap v2 phát Sync rồi Swap) -> reserve_* = dự trữ SAU swap; không có Sync -> NaN.
    Bỏ swap không đổi số dư token gốc hoặc quote."""
    a, q = info["base_index"], 1 - info["base_index"]
    da, dq = 10 ** info["decimals"][a], 10 ** info["decimals"][q]
    rows, last_sync = [], {}
    for lg in sorted(logs, key=lambda x: (int(x["blockNumber"], 16), int(x["logIndex"], 16))):
        topic0, tx = lg["topics"][0], lg["transactionHash"]
        if topic0 in SYNC_TOPICS:
            last_sync[tx] = _words(lg["data"])[:2]
            continue
        flows = swap_flows(topic0, lg["data"])
        a_in, a_out, q_in, q_out = flows[a], flows[2 + a], flows[q], flows[2 + q]
        net_a, net_q = a_out - a_in, abs(q_out - q_in)
        sync = last_sync.pop(tx, None)
        if net_a == 0 or net_q == 0:
            continue
        li = int(lg["logIndex"], 16)
        rows.append((int(lg["blockTimestamp"], 16) if lg.get("blockTimestamp") else np.nan, int(lg["blockNumber"], 16), li, f"{tx}:{li}",
                     net_q / dq / (abs(net_a) / da), abs(net_a) / da, net_q / dq, "buy" if net_a > 0 else "sell",
                     sync[a] / da if sync else np.nan, sync[q] / dq if sync else np.nan))
    return pd.DataFrame(rows, columns=["block_ts", "block_number", "log_index", "tx_hash", "price", "amount", "quote_amount", "side", "reserve_base", "reserve_quote"]
                        ).astype({"block_number": "int64", "log_index": "int64"})


def reserve_price(reserve_base: Any, reserve_quote: Any, stable: bool) -> np.ndarray:
    """Giá biên (quote / 1 base) theo dự trữ: volatile x*y=k -> rq/rb; stable x^3y+xy^3=k -> (3x^2y+y^3)/(x^3+3xy^2) (x = base, y = quote, đơn vị token)."""
    x, y = np.asarray(reserve_base, float), np.asarray(reserve_quote, float)
    if not stable:
        return y / x
    return (3 * x * x * y + y ** 3) / (x ** 3 + 3 * x * y * y)


def attach_timestamps(df: pd.DataFrame, rpc: Rpc, lo: int, hi: int, batch_size: int = 50) -> Tuple[pd.DataFrame, str]:
    """Điền timestamp_ms theo thứ tự ưu tiên: blockTimestamp của log -> nội suy tuyến tính (kiểm chứng bằng mẫu đầu/cuối/giữa [lo, hi]) -> tra từng block. -> (df, ts_method)."""
    out = df.drop(columns=["block_ts"]).copy()
    ts = df["block_ts"].to_numpy(float).copy()
    missing = np.isnan(ts)
    blocks = df["block_number"].to_numpy()

    def lookup(numbers: List[int]) -> Dict[int, int]:
        res = rpc.batch([("eth_getBlockByNumber", [hex(b), False]) for b in numbers], batch_size)
        return {b: int(r["timestamp"], 16) for b, r in zip(numbers, res)}

    if not missing.any():
        method = "log_block_timestamp"
    else:
        probes = sorted({lo, hi, *(lo + (hi - lo) * i // (TS_SAMPLES + 1) for i in range(1, TS_SAMPLES + 1))})
        t = lookup(probes)
        dt, rem = divmod(t[hi] - t[lo], hi - lo) if hi > lo else (0, 1)
        if rem == 0 and dt > 0 and all(t[b] == t[lo] + (b - lo) * dt for b in probes):
            ts[missing] = t[lo] + (blocks[missing] - lo) * dt
            method = "linear_interpolation"
        else:
            got = lookup(sorted(set(blocks[missing].tolist())))
            ts[missing] = [got[b] for b in blocks[missing]]
            method = "per_block_lookup"
    out["timestamp_ms"] = (ts * 1000).astype("int64")
    return out, method


def reserve_deviation_bps(df: pd.DataFrame, stable: bool) -> pd.Series:
    """|price swap / giá theo dự trữ sau swap - 1| (bps, theo đơn vị quote) cho các swap ghép được Sync."""
    ok = df["reserve_base"].notna() & (df["reserve_base"] > 0) & (df["reserve_quote"] > 0)
    px = reserve_price(df.loc[ok, "reserve_base"], df.loc[ok, "reserve_quote"], stable)
    return (df.loc[ok, "price"] / px - 1).abs() * 1e4


def quote_to_usd(df: pd.DataFrame, info: Dict[str, Any], eth_1m: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Thêm quote_usd + mid_price, đổi price/volume sang USD: quote stable = 1; quote WETH x giá MỞ phút chứa swap (eth_1m: open_time, open).
    mid_price = giá biên của pool SAU swap theo dự trữ (reserve_price x quote_usd); NaN khi không có Sync."""
    out = df.copy()
    if info["quote_kind"] == "eth":
        if eth_1m is None or eth_1m.empty:
            raise RuntimeError("thiếu nến ETH/USD để quy WETH -> USD")
        eth = eth_1m.sort_values("open_time")[["open_time", "open"]]
        minute = pd.DataFrame({"open_time": (out["timestamp_ms"] // MINUTE_MS * MINUTE_MS).astype("int64"), "_i": np.arange(len(out))}).sort_values("open_time")
        px = pd.merge_asof(minute, eth, on="open_time", direction="backward").sort_values("_i")["open"].to_numpy()
        if np.isnan(px).any():
            raise RuntimeError("nến ETH/USD không phủ hết khoảng swap")
        out["quote_usd"] = px
    else:
        out["quote_usd"] = 1.0
    out["volume_usd"] = out["quote_amount"] * out["quote_usd"]
    out["price"] = out["price"] * out["quote_usd"]
    rb, rq = out["reserve_base"].to_numpy(float), out["reserve_quote"].to_numpy(float)
    ok = (rb > 0) & (rq > 0)
    mid = np.full(len(out), np.nan)
    mid[ok] = reserve_price(rb[ok], rq[ok], bool(info["stable"]))
    out["mid_price"] = mid * out["quote_usd"].to_numpy()
    return out.drop(columns=["quote_amount"])


def fetch_logs(rpc: Rpc, pool: str, lo: int, hi: int, span: int, topics: List[str]) -> Tuple[List[Dict], int]:
    """eth_getLogs [lo, hi] từng đoạn `span` block; nút từ chối vì quá lớn -> co đôi đoạn và nhớ cho các đoạn sau. -> (logs, span cuối cùng)."""
    out: List[Dict] = []
    while lo <= hi:
        to = min(lo + span - 1, hi)
        try:
            out += rpc.call("eth_getLogs", [{"address": pool, "fromBlock": hex(lo), "toBlock": hex(to), "topics": [topics]}])
        except RpcRange as exc:
            if span == 1:
                raise
            span = max(1, span // 2)
            log(f"[ticks] nút từ chối đoạn ({exc}) -> đoạn {span} block")
            continue
        lo = to + 1
    return out, span


def eth_usd_candles(session: requests.Session, ref: Dict[str, Any], lo_ms: int, hi_ms: int) -> Tuple[pd.DataFrame, str]:
    """Nến 1m ETH/USD của khoảng [lo_ms, hi_ms] theo nguồn tham chiếu của mạng (cfg["eth_usd"]) -> (nến open_time/open, mô tả nguồn)."""
    if ref.get("source") != "okx_candles":
        raise ValueError(f"nguồn ETH/USD chưa hỗ trợ: {ref!r}")
    return okx.fetch_rest_candles(session, ref["symbol"], lo_ms // MINUTE_MS * MINUTE_MS - MINUTE_MS, hi_ms), f"okx_{ref['symbol'].lower()}_usdt_swap_1m_open"


def crawl_dex_ticks(symbol: str, days: Any = DEFAULT_TICK_DAYS, data_root: Optional[str] = None) -> Dict[str, Any]:
    """Swap on-chain của pool DEX `symbol` ("AERO" hoặc "dex:AERO") cho `days` ngày gần nhất -> <gốc>/dex/<SYM>/ticks.parquet."""
    name = parse_symbol(symbol)[1]
    root = data_root or default_data_root()
    asset_dir = os.path.join(root, "dex", name)
    with open(os.path.join(asset_dir, "manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    pool, network = str(man["pool_address"]).lower(), man["network"]
    days, note = clamp_days(days)
    cfg = network_config(network)
    session = _session()
    rpc = Rpc(cfg["rpc_url"], cfg["max_rps"], session)
    chain = int(rpc.call("eth_chainId", []), 16)
    if chain != int(cfg["chain_id"]):
        raise RuntimeError(f"RPC {cfg['rpc_url']} thuộc chain {chain}, mạng {network} cần {cfg['chain_id']}")
    info = pool_onchain(rpc, asset_dir, pool, str(man.get("pool_name") or name), cfg)
    head = _block(rpc, "latest")
    head_bn, head_ts = int(head["number"], 16), int(head["timestamp"], 16)
    start_bn = block_at_or_after(rpc, head_ts - days * 86400, head_bn)
    log(f"[ticks] {name} pool {pool} {info['pool_type']} {'stable' if info['stable'] else 'volatile'} {network} block {start_bn}..{head_bn} (quote {info['quote_symbol']})")
    logs, span = fetch_logs(rpc, pool, start_bn, head_bn, int(cfg["log_span"]), list(SWAP_V2_TOPICS) + [SWAP_V3_TOPIC] + list(SYNC_TOPICS))
    df = decode_swaps(logs, info)
    if df.empty:
        raise RuntimeError(f"pool {pool} không có swap nào trong {days} ngày")
    df, ts_method = attach_timestamps(df, rpc, start_bn, head_bn, int(cfg["batch_size"]))
    matched = float(df["reserve_base"].notna().mean())
    dev = reserve_deviation_bps(df, info["stable"])
    usd_source, eth = "stable_quote=1", None
    if info["quote_kind"] == "eth":
        eth, usd_source = eth_usd_candles(session, cfg["eth_usd"], int(df["timestamp_ms"].min()), head_ts * 1000)
    df = quote_to_usd(df, info, eth)
    issues = [note] if note else []
    saved = save_ticks(df, name, retention_days=days, source="evm_swaps", data_root=data_root, extra_meta={
        "network": network, "chain_id": chain, "pool_address": pool, "pool_type": info["pool_type"], "stable": info["stable"], "fee_rate": info["fee_rate"],
        "fee_note": info["fee_note"], "quote": info["quote_symbol"], "quote_usd_source": usd_source, "ts_method": ts_method, "reserves_basis": "post_swap", "price_basis": {"price": "fill incl. pool fee", "mid_price": "post-swap marginal price from reserves"},
        "sync_matched_pct": round(matched * 100, 2), "reserve_dev_bps_median": round(float(dev.median()), 2) if len(dev) else None,
        "from_block": start_bn, "to_block": head_bn, "log_span": span, "issues": issues})
    return {"symbol": name, "venue": "dex", "window_days": days, "issues": issues, "ts_method": ts_method, "sync_matched_pct": round(matched * 100, 2),
            "window_start": datetime.fromtimestamp(head_ts - days * 86400, timezone.utc).isoformat(), **saved}


# ─── Job ────────────────────────────────────────────────────────────────────
def dex_name(symbol: str) -> str:
    """Tên tài sản DEX của ký hiệu ("AERO" / "dex:AERO"); ký hiệu CEX ("BTC@perp", "cex:BTC") bị từ chối vì CEX chỉ có nến."""
    prefix, name = parse_symbol(symbol)
    if split_instrument(symbol)[1] or prefix == "cex":
        raise ValueError(f"{symbol}: tick chỉ có cho tài sản DEX; tài sản CEX (OKX perp) chỉ có nến")
    return name


def run_job(params=None) -> List[Dict]:
    """Crawl tick theo `params` (symbols, days) -> báo cáo từng tài sản; có tài sản lỗi thì job báo lỗi sau khi ghi đủ kết quả."""
    a = options({"symbols": "", "days": DEFAULT_TICK_DAYS}, params)
    symbols = [s.strip() for s in as_list(a.symbols) if s.strip()]
    if not symbols:
        raise ValueError("cần symbols")
    root, out = default_data_root(), []
    for sym in symbols:
        try:
            out.append(crawl_dex_ticks(dex_name(sym), a.days, root))
            log(f"[done] {sym}: {out[-1]['rows']} tick")
        except Exception as exc:    # một tài sản lỗi không chặn các tài sản còn lại
            log(f"[error] {sym}: {exc}")
            out.append({"symbol": sym, "error": str(exc)})
    write_job_result({"assets": out})
    failed = [r["symbol"] for r in out if "error" in r]
    if failed:
        raise RuntimeError(f"crawl tick lỗi: {failed}")
    return out
