"""API Education (B7): kết quả backtest tính trước cho 50 mẫu chiến lược giáo dục (job edu_precompute -> crawl/store.education_results_dir()).

GET  /api/studio/education/results          danh sách (index.json: mỗi mẫu trạng thái + vài số đo chính)
GET  /api/studio/education/results/{key}    kết quả đầy đủ của một mẫu (metrics, diagnostics, insights, series hạ mẫu, explain)
POST /api/studio/education/precompute       chạy lại job edu_precompute qua đường job chuẩn -> {"job_id"} (theo dõi: GET /api/studio/book/jobs/{job_id})
"""
import json
import os
import re
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api.jobs import batch as batch_jobs
from backend.crawl.store import education_results_dir

router = APIRouter(prefix="/api/studio/education", tags=["education"])
_KEY_RE = re.compile(r"^[a-z0-9_]{1,80}$")


class PrecomputeRequest(BaseModel):
    only: Optional[List[str]] = Field(None, max_length=60, description="Key mẫu cần chạy lại; trống = cả 50 mẫu")
    start: Optional[str] = None
    end: Optional[str] = None
    train_ratio: Optional[float] = Field(None, ge=0.1, le=0.95)
    initial_capital: Optional[float] = Field(None, gt=0, le=1e9)


def _read(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise HTTPException(500, "file kết quả hỏng; chạy lại job edu_precompute")


@router.get("/results")
def list_results():
    idx = _read(os.path.join(education_results_dir(), "index.json"))
    if idx is None:
        raise HTTPException(404, "chưa có kết quả tính trước; POST /api/studio/education/precompute")
    return idx


@router.get("/results/{key}")
def get_result(key: str):
    if not _KEY_RE.match(key):
        raise HTTPException(404, "key không hợp lệ")
    rec = _read(os.path.join(education_results_dir(), f"{key}.json"))
    if rec is None:
        raise HTTPException(404, f"chưa có kết quả cho mẫu {key!r}")
    return rec


@router.post("/precompute")
def post_precompute(req: Optional[PrecomputeRequest] = None):
    """Khởi chạy job edu_precompute -> {"job_id"}."""
    return _launch(req.model_dump(exclude_none=True) if req else {})


def _launch(body: dict):
    try:
        params = batch_jobs.build_job("edu_precompute", body)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    return batch_jobs.http_launch("edu_precompute", params)
