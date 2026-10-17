"""Bộ điều phối runner và các module thực thi chuyên biệt:
- runner.py: Trung tâm điều phối hàng đợi, vòng đời (launch, cancel, status, progress)
- backtest.py: Chạy backtest chiến lược tự do và danh mục sổ sách (custom_backtest, book_backtest)
- wfa.py: Walk-Forward Analysis và thẩm định ngoài mẫu (book_wfa)
- carlo.py: Mô phỏng Monte Carlo đa kịch bản
- alpha.py: Sinh tham số, scan universe 100 coins, sweep tham số, alpha research
- live.py: Thực thi bot live, giám sát tự phục hồi (supervisor), biểu đồ trực tiếp
"""
import subprocess
from . import runner
from .runner import *
from .runner import (
    _SUMMARY_CACHE,
    _LOCK,
    _read_meta,
    _write_meta,
    _job_dir,
    _alive,
)



from .backtest import run_custom_backtest, run_book_backtest, run_custom
from .wfa import run_book_wfa
from .carlo import run_carlo
from .alpha import run_alpha_research, run_scan_job, run_sweep_job
from .live import run_live_bot

__all__ = [
    # Subprocess cho monkeypatch test
    "subprocess",
    # Trung tâm điều phối

    "Progress",
    "graceful_sigterm",
    "JobError",
    "InvalidJobIdError",
    "JobNotFoundError",
    "NotReady",
    "JobBusy",
    "MAX_LIVE_BOTS",
    "running_live_bot_info",
    "EphemeralGone",
    "DEX_UNSUPPORTED",
    "KINDS",
    "launch",
    "cancel",
    "status",
    "job_status",
    "list_jobs",
    "new_job_id",
    "inject_ephemeral_result",

    # 5 runners chuyên biệt
    "run_custom_backtest",
    "run_book_backtest",
    "run_custom",
    "run_book_wfa",
    "run_carlo",
    "run_alpha_research",
    "run_scan_job",
    "run_sweep_job",
    "run_live_bot",
]
