"""API trang Danh mục (docs/ui_contract.md §3): GET /api/studio/portfolio/dashboard.

Nguồn `backtest` đọc result.json của một job book_backtest đã xong (dựng bằng backend/core/analytics/dashboard.py).
`live`/`testnet` đi qua feeds.get_snapshot: chưa có tài khoản thật -> dùng feed GIẢ LẬP (data/_cache/mock_feeds/<nguồn>.json, payload có
"mock": true + "mock_note"); chưa có file giả lập -> {"available": false, "reason"} (HTTP 200). `paper` đã bỏ (422).
Kết quả được đệm LRU theo (nguồn/job_id, period, mtime).
"""
import os
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.core.analytics import feeds
from backend.core.analytics import dashboard as pd_mod
from backend.api.jobs import batch as batch_jobs

router = APIRouter(prefix="/api/studio/portfolio", tags=["portfolio"])

_CACHE = pd_mod.LruCache(32)
_LOCK = threading.Lock()


def _latest_done_backtest() -> Optional[str]:
    for j in batch_jobs.list_jobs(100, "book_backtest"):
        if j.get("status") == "done":
            return j["id"]
    return None


def _mock_dashboard(source: str, period: str):
    feed = feeds.MockFeed(source)
    key = ("feed", source, period, feed.mtime())
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    try:
        snap = feeds.get_snapshot(source)
    except feeds.NotAvailable as e:
        return {"available": False, "reason": str(e)}
    payload = pd_mod.build_from_snapshot(snap, period, pd_mod.snapshot_benchmark(snap.result))
    with _LOCK:
        _CACHE.put(key, payload)
    return payload


@router.get("/dashboard")
def get_dashboard(source: str = Query("backtest", pattern="^(backtest|live|testnet)$"), job_id: Optional[str] = None,
                  period: str = Query("ALL", pattern="^(1M|3M|YTD|1Y|ALL)$")):
    if source != "backtest":
        return _mock_dashboard(source, period)
    if not job_id:   # không truyền job: lấy job backtest xong gần nhất (payload.source.job_id cho biết đã dùng job nào)
        job_id = _latest_done_backtest()
        if not job_id:
            return {"available": False, "reason": "Chưa có job backtest nào hoàn tất — chạy Backtest trước."}
    try:
        rpath = os.path.join(batch_jobs.job_dir(job_id), "result.json")
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    key = (job_id, period, os.path.getmtime(rpath) if os.path.isfile(rpath) else None)
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    try:
        job = batch_jobs.status(job_id)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    if job is None:
        raise HTTPException(404, "không có job này")
    if job.get("kind") != "book_backtest":
        raise HTTPException(422, "job_id phải là job book_backtest")
    if job.get("status") != "done" or not job.get("result"):
        raise HTTPException(409, f"job chưa xong (trạng thái {job.get('status')})")
    res = job["result"]
    feed = feeds.BacktestFeed(res, job_id, batch_jobs.job_label(job["kind"], job.get("params")))
    snap = feed.fetch()
    payload = pd_mod.build_from_snapshot(snap, period, pd_mod.snapshot_benchmark(res))
    with _LOCK:
        _CACHE.put(key, payload)
    return payload


def _result_for(source: str, job_id: Optional[str]):
    """Kết quả dạng book_backtest của nguồn: (result, job_id). Live/Testnet = feed (giả lập tới khi nối sàn)."""
    if source != "backtest":
        try:
            return feeds.get_snapshot(source).result, None
        except feeds.NotAvailable as e:
            raise HTTPException(404, str(e))
    job_id = job_id or _latest_done_backtest()
    if not job_id:
        raise HTTPException(404, "Chưa có job backtest nào hoàn tất — chạy Backtest trước.")
    try:
        job = batch_jobs.status(job_id)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    if job is None:
        raise HTTPException(404, "không có job này")
    if job.get("kind") != "book_backtest" or job.get("status") != "done" or not job.get("result"):
        raise HTTPException(409, "job phải là book_backtest đã xong")
    return job["result"], job_id


TRADE_SORT = {"close_time", "enter_time", "pnl", "pnl_pct", "mae_pct", "notional", "symbol", "strategy"}


@router.get("/trades")
def get_trades(source: str = Query("backtest", pattern="^(backtest|live|testnet)$"), job_id: Optional[str] = None,
               period: str = Query("ALL", pattern="^(1M|3M|YTD|1Y|ALL)$"), strategy: Optional[str] = None, symbol: Optional[str] = None,
               side: Optional[str] = Query(None, pattern="^(LONG|SHORT)$"), outcome: Optional[str] = Query(None, pattern="^(win|loss|breakeven)$"),
               sort: str = "-close_time", offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=2000),
               format: str = Query("json", pattern="^(json|csv)$")):
    """Danh sách lệnh đã đóng của nguồn (lọc: kỳ / chiến lược — id hoặc HỌ chiến lược / tài sản / chiều / kết quả), sắp xếp, phân trang;
    format=csv trả toàn bộ hàng đã lọc (không phân trang)."""
    from backend.core.metrics.trades import strategy_family
    res, jid = _result_for(source, job_id)
    rows = [t for t in res.get("trade_list") or [] if t.get("close_time") is not None]
    if period != "ALL":
        nav = pd_mod.daily_nav_series(res)
        if len(nav):
            cut = pd_mod._cutoff(nav.index[-1], period)
            if cut is not None:
                start_ms = int((cut + pd_mod.pd.Timedelta(days=1)).value // 1_000_000)
                rows = [t for t in rows if t["close_time"] >= start_ms]
    if strategy:
        rows = [t for t in rows if t.get("strategy") == strategy or strategy_family(t.get("strategy")) == strategy]
    if symbol:
        want = symbol if "@" in symbol else f"{symbol.upper()}@perp"
        rows = [t for t in rows if t.get("symbol") in (symbol, want)]
    if side:
        rows = [t for t in rows if t.get("side") == side]
    if outcome:
        rows = [t for t in rows if (outcome == "win" and t["pnl"] > 0) or (outcome == "loss" and t["pnl"] < 0) or (outcome == "breakeven" and t["pnl"] == 0)]
    key = sort.lstrip("-")
    if key not in TRADE_SORT:
        raise HTTPException(422, f"sort phải là một trong {sorted(TRADE_SORT)} (thêm '-' để giảm dần)")
    rows = sorted(rows, key=lambda t: (t.get(key) is None, t.get(key) if t.get(key) is not None else 0), reverse=sort.startswith("-"))
    if format == "csv":
        import csv
        import io
        from fastapi.responses import Response
        cols = ["close_time", "enter_time", "symbol", "strategy", "side", "enter_price", "avg_price", "close_price", "qty", "notional",
                "margin_usd", "leverage", "layers", "pnl", "pnl_pct", "fees_usd", "funding_usd", "mae_pct", "status", "close_reason"]
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="trades_{source}_{jid or "feed"}.csv"'})
    total = len(rows)
    return {"items": rows[offset:offset + limit], "total": total, "offset": offset, "limit": limit, "job_id": jid,
            "strategies": sorted({t.get("strategy") for t in res.get("trade_list") or [] if t.get("strategy")}),
            "families": sorted({strategy_family(t.get("strategy")) for t in res.get("trade_list") or [] if t.get("strategy")}),
            "symbols": sorted({t.get("symbol") for t in res.get("trade_list") or [] if t.get("symbol")})}


class MockFeedsRequest(BaseModel):
    only: str = Field("", pattern="^(|live|testnet)$")


@router.post("/mock-feeds")
def post_mock_feeds(req: MockFeedsRequest):
    """Dựng lại feed giả lập Live/Testnet (job nền mock_feeds: engine thật trên dữ liệu mới nhất)."""
    return batch_jobs.http_launch("mock_feeds", {"only": req.only} if req.only else {})
