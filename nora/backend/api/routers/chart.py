"""Biểu đồ tín hiệu (/api/studio/chart): nến + chỉ báo + điểm tín hiệu + từng điều kiện đúng/sai — để hiểu TẠI SAO một lệnh được vào.

Chiến lược lấy từ: alpha của một lượt phễu (run_id + alpha_id: lệnh backtest quá khứ) hoặc sổ đang chạy (book main|explore + strategy_id:
lệnh của bot). Dữ liệu: "data" = kho nến của sàn đang dùng (data/<sàn>/cex, toàn bộ lịch sử như backtest), "okx" = nến công khai OKX
mới nhất (lệnh live gần đây). Tính bằng đúng đường của engine/bot: core/analytics/signal_explain.py.
"""
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/studio/chart", tags=["chart"])
FRAME_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "24h": 86_400_000}
MAX_BARS = 5000          # nến tối đa trong cửa sổ trả về
OKX_LIMIT = 1500         # như bot: đủ khởi động chỉ báo (signals khớp engine với 1500 nến)


class ExplainRequest(BaseModel):
    symbol: str = Field(..., pattern=r"^[A-Za-z0-9]{2,12}(@perp)?$")
    start: int = Field(..., ge=0, description="ms, mở cửa sổ")
    end: int = Field(..., ge=0, description="ms, đóng cửa sổ")
    run_id: Optional[str] = Field(None, max_length=64, description="alpha của lượt phễu (cùng alpha_id)")
    alpha_id: Optional[str] = Field(None, pattern=r"^[0-9a-f]{16}$")
    book: Optional[str] = Field(None, pattern="^(main|explore)$", description="sổ đang chạy (cùng strategy_id)")
    strategy_id: Optional[str] = Field(None, max_length=64)
    source: str = Field("data", pattern="^(data|okx)$")


def _strategy(req: ExplainRequest):
    """-> (chiến lược đã materialize, khung chạy, thông tin hiển thị)."""
    from backend.core.params.modes import lift_frames
    from backend.core.strategy.book import CANDIDATES, materialize
    by = {c["id"]: c for c in CANDIDATES}
    if req.run_id and req.alpha_id:
        from backend.api.routers.funnel import _open
        from backend.optimize.funnel.generate import split_regime
        st = _open(req.run_id)
        try:
            al = st.get_alpha(req.alpha_id)
            tf = (st.read_run().get("config") or {}).get("timeframe", "1m")
        finally:
            st.close()
        if al is None:
            raise HTTPException(404, f"không có alpha {req.alpha_id}")
        params, regime = split_regime(al["params"])
        cid, src = al["strategy"], {"run_id": req.run_id, "alpha_id": req.alpha_id, "regime": regime}
    elif req.book and req.strategy_id:
        from backend.live.bot import load_book
        try:
            book = load_book(kind=req.book, mode="paper")
        except (SystemExit, OSError) as e:
            raise HTTPException(404, str(e))
        item = next((s for s in book["strategies"] if s["id"] == req.strategy_id), None)
        if item is None:
            raise HTTPException(404, f"sổ {req.book} không có chiến lược {req.strategy_id}")
        params, regime, tf, cid = item["params"], None, book.get("timeframe", "1m"), item["id"]
        src = {"book": req.book, "book_source": book.get("source"), "unvalidated": cid in (book.get("unvalidated") or [])}
    else:
        raise HTTPException(422, "cần (run_id + alpha_id) hoặc (book + strategy_id)")
    if cid not in by:
        raise HTTPException(404, f"chiến lược {cid} không còn trong danh sách")
    params = {k: v for k, v in params.items() if k != "risk_per_trade_pct"}
    st = materialize(by[cid], lift_frames(by[cid], params, tf), risk_per_trade_pct=1.0, stop_fill="level")
    meta = {"id": cid, "side": by[cid]["side"], "family": by[cid].get("family"), "description": by[cid].get("description"),
            "params": params, **src}
    return st, tf, meta


_OKX = None             # một adapter dùng chung: bộ đệm nến theo (mã, khung) -> lần sau chỉ 1 request /candles mỗi khung


def _okx():
    global _OKX
    if _OKX is None:
        from backend.live.okx import OkxAdapter
        _OKX = OkxAdapter(None, demo=False)
    return _OKX


def _frames(symbol: str, st: Dict[str, Any], tf: str, source: str) -> Dict[str, Any]:
    """data: kho nến của sàn đang dùng (toàn bộ lịch sử). okx: kho nến + nến OKX mới nhất nối vào sau (lệnh live gần đây)."""
    import time
    import pandas as pd
    from backend.db.data_layout import default_data_root
    from backend.live import signals as ls
    need = ls.required_frames(symbol, [st], tf)
    root = os.path.join(default_data_root(), "cex", symbol, "perp")
    now = int(time.time() * 1000)
    out = {}
    for fr in need:
        path = os.path.join(root, f"{fr}.pkl")
        hist = pd.read_pickle(path) if os.path.isfile(path) else None
        if source == "okx":
            last = int(hist["open_time"].iloc[-1]) if hist is not None and len(hist) else 0
            gap = (now - last) // FRAME_MS[fr] + 3 if last else OKX_LIMIT
            live = ls.klines_frame(_okx().klines(symbol, fr, int(min(max(gap, 10), OKX_LIMIT)), now), now)
            if hist is not None:
                live = pd.concat([hist[[c for c in live.columns if c in hist.columns]], live], ignore_index=True)
                live = live.drop_duplicates("open_time", keep="last").sort_values("open_time").reset_index(drop=True)
            hist = live
        if hist is None:
            raise HTTPException(404, f"chưa có dữ liệu {symbol} khung {fr} ({path})")
        out[fr] = hist
    return out


@router.post("/explain")
def post_explain(req: ExplainRequest) -> Dict[str, Any]:
    """Nến + chỉ báo + tín hiệu vào/thoát (kèm từng điều kiện và giá trị lúc đó) của một chiến lược trên một mã, trong cửa sổ [start, end]."""
    from backend.core.analytics.signal_explain import explain
    symbol = req.symbol.split("@")[0].upper()
    st, tf, meta = _strategy(req)
    start, end = int(req.start), int(req.end)
    if end <= start:
        raise HTTPException(422, "end phải sau start")
    if (end - start) // FRAME_MS[tf] > MAX_BARS:
        start = end - MAX_BARS * FRAME_MS[tf]
    frames = _frames(symbol, st, tf, req.source)
    try:
        out = explain(symbol, st, tf, frames, start, end)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {**out, "strategy": meta, "source": req.source}
