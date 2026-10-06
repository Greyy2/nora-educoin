"""Tài sản DEX trong backtest: nhận diện ký hiệu (không trộn với perp), metadata pool (phí, loại, mạng, độ phủ tick), vị thế spot-LONG và cửa sổ tick.

DEX là spot AMM: không đòn bẩy, không bán khống -> chỉ chạy chân LONG (market="spot", leverage=1). Mọi số của pool (phí, loại, mạng) đọc từ
manifest.json["ticks"] / dex_pool.json["onchain"] của tài sản — không có giá trị mặc định theo pool; thiếu phí -> từ chối.
"""
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from backend.db.data_layout import clean_name, default_data_root, parse_symbol, resolve_asset_dir, split_instrument

SPOT_POSITION = {"market": "spot", "leverage": 1}    # ghi đè vị thế của chiến lược khi chạy trên DEX
POOL_TYPES = ("aerodrome_v2", "uniswap_v2")          # pool AMM có dự trữ trong tick (Sync): volatile x*y=k hoặc stable x³y+xy³=k


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


def display_name(symbol: str) -> str:
    return symbol.split("@")[0].split(":")[-1]


def require_long_legs(strategy_ids: List[str]) -> None:
    from backend.core.strategy.book import BY_ID
    short = [i for i in strategy_ids if BY_ID[i]["side"] != "LONG"]
    if short:
        raise ValueError(f"DEX là spot AMM — không bán khống được nên chỉ chạy chân LONG; bỏ chân SHORT / \"Cả hai chiều\": {short}")


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def pool_info(symbol: str, data_root: Optional[str] = None) -> Dict[str, Any]:
    """Metadata pool của tài sản DEX: symbol (hiển thị), qualified, network, fee_rate (+ nguồn), stable, pool_type, ticks (manifest["ticks"] hoặc None).
    Phí: manifest["ticks"]["fee_rate"], không có thì dex_pool.json["onchain"]["fee_rate"]; null ở cả hai -> ValueError (không đoán phí)."""
    name = clean_name(parse_symbol(symbol)[1])
    path = resolve_asset_dir(f"dex:{name}", data_root=data_root or default_data_root())
    if not path:
        raise ValueError(f"không có tài sản DEX '{name}' trong kho dữ liệu")
    manifest, onchain = _read_json(os.path.join(path, "manifest.json")), _read_json(os.path.join(path, "dex_pool.json")).get("onchain") or {}
    ticks = manifest.get("ticks") if isinstance(manifest.get("ticks"), dict) else None
    src = "manifest.ticks.fee_rate"
    fee = (ticks or {}).get("fee_rate")
    if fee is None:
        fee, src = onchain.get("fee_rate"), "dex_pool.json onchain.fee_rate"
    if fee is None:
        raise ValueError(f"{name}: chưa xác minh được phí pool on-chain (fee_rate = null) — không thể tính chi phí AMM; crawl lại metadata pool")
    pick = lambda k: (ticks or {}).get(k) if (ticks or {}).get(k) is not None else onchain.get(k)   # noqa: E731
    return {"symbol": name, "qualified": f"dex:{name}", "network": (ticks or {}).get("network") or manifest.get("network"), "fee_rate": float(fee),
            "fee_source": src, "stable": bool(pick("stable")), "pool_type": pick("pool_type"), "ticks": ticks}


def check_amm_pool(info: Dict[str, Any]) -> None:
    """Pool phải có dự trữ trong tick (loại v2 nhận diện được) và có mạng — nếu không thì không mô hình hoá được AMM."""
    if info["pool_type"] not in POOL_TYPES:
        raise ValueError(f"{info['symbol']}: loại pool {info['pool_type']!r} chưa hỗ trợ — chỉ pool có dự trữ (Aerodrome/Uniswap v2): {POOL_TYPES}")
    if not info["network"]:
        raise ValueError(f"{info['symbol']}: manifest thiếu network")


def tick_window(infos: List[Dict[str, Any]], start: Optional[int], end: Optional[int], frame_ms: int) -> Tuple[int, int]:
    """Cửa sổ chạy tick [W, E] (ms) = [start, end] cắt theo độ phủ tick chung của các tài sản: W làm tròn LÊN mốc nến cơ sở kế tiếp (nến tín hiệu đầu tiên
    phủ trọn bằng tick), E = min(end, tick cuối). Ngắn hơn một nến cơ sở -> ValueError."""
    for i in infos:
        if not i["ticks"]:
            raise ValueError(f"{i['symbol']}: chưa có tick — crawl tick (data_crawl_ticks) trước khi chạy backtest tick")
    lo, hi = max(int(i["ticks"]["start_ts"]) for i in infos), min(int(i["ticks"]["end_ts"]) for i in infos)
    w = max(int(start or 0), lo)
    w = -(-w // frame_ms) * frame_ms
    e = min(int(end) if end else hi, hi)
    if e - w < frame_ms:
        raise ValueError(f"cửa sổ tick sau khi cắt theo độ phủ tick ({lo}..{hi} ms) ngắn hơn một nến cơ sở ({frame_ms // 60_000} phút)")
    return w, e
