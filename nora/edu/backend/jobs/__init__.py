"""Kiến trúc Module Jobs (backend.jobs):
- tasks.py: File tổng duy nhất bên ngoài, điều phối mọi tác vụ/job
- runner/: 6 runner chuyên biệt (backtest, live, alpha, wfa, carlo, runner điều phối)
- worker/: pool xử lý đa tiến trình và Celery
"""
import sys

from . import runner, worker, tasks
from .runner import backtest as evaluate
from .runner import live as live_supervisor
from .runner import live as live_chart
from .runner import alpha as scan
from .runner import alpha as sweep
from .runner import wfa

from .tasks import (
    run_custom_backtest,
    run_custom,
    run_book_backtest,
    run_book_wfa,
    run_alpha_research,
    run_universe_scan,
    run_param_sweep,
    load_universe_sectors,
    build_chart,
)


from .runner import (
    Progress,
    KINDS,
    launch,
    cancel,
    status,
    job_status,
    list_jobs,
)

from .worker import resource as workers

# Alias backward compatibility cho các module cũ đã được tích hợp vào runner/ và worker/
sys.modules.setdefault("backend.jobs.evaluate", evaluate)
sys.modules.setdefault("backend.jobs.scan", scan)
sys.modules.setdefault("backend.jobs.sweep", sweep)
sys.modules.setdefault("backend.jobs.workers", workers)

__all__ = [
    # Top-level coordinator
    "tasks",
    "runner",
    "worker",
    # Runner tools
    "Progress",
    "KINDS",
    "launch",
    "cancel",
    "status",
    "job_status",
    "list_jobs",
    # Tasks
    "run_custom_backtest",
    "run_custom",
    "run_book_backtest",
    "run_book_wfa",
    "run_alpha_research",
    "run_universe_scan",
    "run_param_sweep",
    "load_universe_sectors",
    "build_chart",
]


