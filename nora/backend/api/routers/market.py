"""Tín hiệu thị trường (/api/studio/market): trạng thái tín hiệu từng chiến lược × tài sản tại nến 1m ĐÃ ĐÓNG mới nhất của dữ liệu
(core/signals/snapshot.py — cùng đường tính với backtest). Live/Testnet sau này dùng lại đúng hàm đó trên nến của sàn."""
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

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
                strategies: Optional[str] = Query(None, description="id chiến lược, phân tách dấu phẩy (mặc định cả sổ)")):
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


REGIME_FRAME = "15m"          # nhãn regime trên nến 15m (đặc trưng 1h/4h đã đóng) — cùng đường classifier.series với job


def regime_history(symbol: str, days: int) -> Dict[str, Any]:
    """Regime hiện tại + lịch sử `days` ngày cuối của một tài sản: các đoạn [bắt đầu, kết thúc, trạng thái], tỷ trọng thời gian, chiến lược
    được bật ở regime hiện tại theo bảng của sổ (book.REGIME_MAP)."""
    from backend.core.backtest.run import WARMUP
    from backend.core.regime import classifier as rg
    from backend.core.strategy.book import REGIME_MAP
    from backend.db.local_pkl import read_manifest
    m = read_manifest(symbol)
    if not m:
        return {"symbol": symbol, "error": "chưa có dữ liệu (manifest)"}
    end = int(m["end_ts"]) + 60_000
    key = ("regime", symbol, _fingerprint(symbol), end, days)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    start = end - days * 86_400_000
    s = rg.series(symbol, start - WARMUP, end, base_frame=REGIME_FRAME)
    keep = (s["t"] >= start) & s["real"]
    t, lab = s["t"][keep], s["labels"][keep]
    segs: List[List[Any]] = []
    for i, code in enumerate(lab.tolist()):
        if segs and segs[-1][2] == rg.NAMES[code]:
            segs[-1][1] = int(t[i])
        else:
            segs.append([int(t[i]), int(t[i]), rg.NAMES[code]])
    cur = rg.NAMES[int(lab[-1])] if len(lab) else "UNKNOWN"
    out = {"symbol": symbol, "as_of": int(t[-1]) if len(t) else None,
           "current": {"state": cur, "label": rg.LABEL_VI[cur], "since": segs[-1][0] if segs else None},
           "segments": segs,
           "share_pct": {n: round(100.0 * float((lab == c).mean()), 1) for c, n in enumerate(rg.NAMES) if len(lab) and (lab == c).any()},
           "strategies_on": sorted(cid for cid, cfg in REGIME_MAP.items() if cur in cfg["allowed"]),
           "strategies_off": sorted(cid for cid, cfg in REGIME_MAP.items() if cur not in cfg["allowed"])}
    with _LOCK:
        _CACHE[key] = out
        while len(_CACHE) > _MAX:
            _CACHE.popitem(last=False)
    return out


@router.get("/regime")
def get_regime(symbols: Optional[str] = Query(None, description="vd BTC,SOL (mặc định cả vũ trụ perp của sổ)"),
               days: int = Query(30, ge=1, le=365)):
    """Regime hiện tại + lịch sử từng tài sản (nến 15m đã đóng) và chiến lược đang bật theo bảng regime của sổ."""
    from backend.api.jobs.batch import JobError, check_symbols
    from backend.core.regime import classifier as rg
    from backend.core.strategy.book import perp_symbols
    try:
        syms = check_symbols([s for s in symbols.split(",") if s]) if symbols else perp_symbols()
    except JobError as e:
        raise HTTPException(422, str(e))
    return {"days": days, "frame": REGIME_FRAME, "names": list(rg.NAMES), "labels_vi": rg.LABEL_VI,
            "symbols": [regime_history(s, days) for s in syms]}


class RegimeReportRequest(BaseModel):
    symbols: Optional[List[str]] = Field(None, max_length=16, description="Mặc định cả vũ trụ perp của sổ")
    start: Optional[str] = None
    end: Optional[str] = None
    event_pct: float = Field(12.0, ge=3.0, le=50.0, description="Ngưỡng sự kiện thẳng đứng (|lợi suất 24h| %) dùng để chấm điểm")
    backtest: bool = Field(True, description="Chạy kèm sổ presets tắt/bật regime để so sánh")
    timeframe: str = Field("15m", pattern="^(15m|1h|4h)$", description="Khung chạy (nến mô phỏng)")


@router.post("/regime/report")
def post_regime_report(req: RegimeReportRequest):
    """Báo cáo độ chính xác regime + so sánh bật/tắt regime (job nền regime_report, kết quả ở result.json của job)."""
    from backend.api.jobs import batch as batch_jobs
    p: Dict[str, Any] = {"event_pct": req.event_pct, "backtest": req.backtest, "timeframe": req.timeframe}
    try:
        if req.symbols:
            p["symbols"] = ",".join(batch_jobs.check_symbols(req.symbols))
        for k in ("start", "end"):
            if getattr(req, k):
                p[k] = batch_jobs.check_date(getattr(req, k))
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    return batch_jobs.http_launch("regime_report", p)
