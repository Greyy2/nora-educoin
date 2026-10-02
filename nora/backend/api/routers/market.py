"""Tín hiệu thị trường (/api/studio/market): trạng thái tín hiệu từng chiến lược × tài sản tại nến 1m ĐÃ ĐÓNG mới nhất của dữ liệu
(core/signals/snapshot.py — cùng đường tính với backtest). Live/Testnet sau này dùng lại đúng hàm đó trên nến của sàn."""
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/studio/market", tags=["market"])
_CACHE: "OrderedDict[tuple, Dict[str, Any]]" = OrderedDict()
_LOCK = threading.Lock()
_MAX = 64


def _fingerprint(symbol: str) -> Optional[tuple]:
    from backend.db.local_pkl import resolve_symbol_dir
    d = resolve_symbol_dir(symbol)
    if not d:
        return None
    f = os.path.join(d, "1m.pkl")
    try:
        st = os.stat(f)
        return (f, st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def snapshot_cached(symbol: str, ids: List[str]) -> Dict[str, Any]:
    from backend.core.signals.snapshot import book_strategies, signal_snapshot
    from backend.db.local_pkl import read_manifest
    m = read_manifest(symbol)
    if not m:
        return {"symbol": symbol, "error": "chưa có dữ liệu (manifest)", "strategies": []}
    key = (symbol, tuple(ids), _fingerprint(symbol), int(m["end_ts"]))
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    t0 = time.time()
    snap = signal_snapshot(symbol, book_strategies(ids or None), int(m["end_ts"]) + 60_000)
    snap["compute_s"] = round(time.time() - t0, 2)
    with _LOCK:
        _CACHE[key] = snap
        while len(_CACHE) > _MAX:
            _CACHE.popitem(last=False)
    return snap


@router.get("/signals")
def get_signals(symbols: Optional[str] = Query(None, description="vd BTC,SOL (mặc định cả vũ trụ perp của sổ)"),
                strategies: Optional[str] = Query(None, description="id chiến lược, phân tách dấu phẩy (mặc định cả 7)")):
    from backend.api.jobs.batch import JobError, check_candidate_ids, check_symbols
    from backend.core.strategy.book import perp_symbols
    try:
        syms = check_symbols([s for s in symbols.split(",") if s]) if symbols else perp_symbols()
        ids = check_candidate_ids([s for s in strategies.split(",") if s]) if strategies else []
    except JobError as e:
        raise HTTPException(422, str(e))
    rows = [snapshot_cached(s, ids) for s in syms]
    return {"symbols": rows, "strategies": ids or None,
            "note": "Tín hiệu tại nến 1m đã đóng cuối của dữ liệu; điều kiện khung lớn chỉ dùng nến đã đóng. Tham số = preset của từng chiến lược."}
