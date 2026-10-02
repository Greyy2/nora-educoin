"""Một cửa chạy mọi job nền (backtest, WFA, dựng sổ, phễu, ...).

batch.launch / batch.run_sync -> backend/utils/ops/run_limited.sh -- -m backend.api.jobs.runner <job_dir>
runner đọc <job_dir>/params.json {kind, params}, nạp module của `kind` trong batch.KINDS và gọi run_job(params).
Không có lệnh terminal riêng cho từng việc: terminal/script gọi đúng endpoint API như UI.
"""
# Đặt TRƯỚC mọi import numpy/backend: tiến trình con (worker) kế thừa qua fork.
import os
for _e in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_e, "1")
os.environ.setdefault("NORA_CANDLE_CACHE_MB", "512")
os.environ.setdefault("NORA_DATA_CACHE_MB", "1024")

import importlib
import json
import sys


def run(job_dir: str):
    with open(os.path.join(job_dir, "params.json"), encoding="utf-8") as fh:
        spec = json.load(fh)
    from backend.api.jobs.batch import KINDS
    kind = spec["kind"]
    if kind not in KINDS:
        raise SystemExit(f"loại job không có trong danh sách trắng: {kind!r}")
    os.environ["NORA_JOB_DIR"] = job_dir
    return importlib.import_module(KINDS[kind]["module"]).run_job(spec.get("params") or {})


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("dùng: python -m backend.api.jobs.runner <job_dir>")
    run(sys.argv[1])
