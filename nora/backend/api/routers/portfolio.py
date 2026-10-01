"""API trang Danh mục (docs/ui_contract.md §3): GET /api/studio/portfolio/dashboard.

Nguồn `backtest` đọc result.json của một job book_backtest đã xong (dựng bằng backend/analytics/portfolio_dashboard.py);
live/paper/testnet chưa có tài khoản -> {"available": false, "reason"} (HTTP 200). Kết quả được đệm LRU theo (job_id, period, mtime).
"""
import os
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.analytics import portfolio_dashboard as pd_mod
from backend.studio_pipeline import batch_jobs

router = APIRouter(prefix="/api/studio/portfolio", tags=["portfolio"])

_CACHE = pd_mod.LruCache(32)
_LOCK = threading.Lock()


def _latest_done_backtest() -> Optional[str]:
    for j in batch_jobs.list_jobs(100, "book_backtest"):
        if j.get("status") == "done":
            return j["id"]
    return None


@router.get("/dashboard")
def get_dashboard(source: str = Query("backtest", pattern="^(backtest|live|paper|testnet)$"), job_id: Optional[str] = None,
                  period: str = Query("ALL", pattern="^(1M|3M|YTD|1Y|ALL)$")):
    if source != "backtest":
        return pd_mod.unavailable(source)
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
    cfg = res.get("config") or {}
    closes = None
    if cfg.get("start") and cfg.get("end"):
        try:
            closes = pd_mod.benchmark_daily_closes("BTC@perp", cfg["start"], cfg["end"])
        except Exception:   # noqa: BLE001  (thiếu dữ liệu benchmark thì vẫn trả dashboard, bench = null)
            closes = None
    payload = pd_mod.build_dashboard(res, closes, period, job_id=job_id, label=batch_jobs.job_label(job["kind"], job.get("args") or []))
    with _LOCK:
        _CACHE.put(key, payload)
    return payload
