"""Quy ước job nền của API: khi env NORA_JOB_DIR có đặt, script ghi báo cáo cuối vào $NORA_JOB_DIR/result.json.

API (backend/studio_pipeline/batch_jobs.py) đặt biến này khi chạy script qua run_limited.sh rồi đọc lại file.
Không đặt biến -> không làm gì (chạy tay như cũ).
"""
import json
import os
from typing import Any, Optional

from backend.utils.jsonsafe import json_default


def write_job_result(result: Any) -> Optional[str]:
    job_dir = os.environ.get("NORA_JOB_DIR")
    if not job_dir:
        return None
    os.makedirs(job_dir, exist_ok=True)
    path = os.path.join(job_dir, "result.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, default=json_default)
    os.replace(tmp, path)  # ghi nguyên tử: API không bao giờ đọc file dở
    return path
