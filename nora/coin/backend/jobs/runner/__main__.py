"""Điểm vào thực thi khi gọi `python -m backend.jobs.runner <job_dir>`."""
import sys
from .runner import run_job_dir

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("dùng: python -m backend.jobs.runner <job_dir>")
    run_job_dir(sys.argv[1])
