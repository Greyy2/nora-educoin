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


class MockFeedsRequest(BaseModel):
    only: str = Field("", pattern="^(|live|testnet)$")


@router.post("/mock-feeds")
def post_mock_feeds(req: MockFeedsRequest):
    """Dựng lại feed giả lập Live/Testnet (job nền mock_feeds: engine thật trên dữ liệu mới nhất)."""
    return batch_jobs.http_launch("mock_feeds", {"only": req.only} if req.only else {})
