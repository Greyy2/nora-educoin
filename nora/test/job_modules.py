"""File của các module job (có run_job(params)) để test nạp lại một bản riêng từ file (tên ngắn cũ -> đường dẫn mới)."""
import os

JOB_FILES = {
    "build_strategy_book": "optimize/book.py",
    "validate_book": "wfa/run.py",
    "run_book_backtest": "core/backtest/run.py",
    "run_funnel": "optimize/funnel/run.py",
    "promote_staging": "core/data/promote.py",
}


def job_path(name: str) -> str:
    return os.path.join(os.path.dirname(__file__), "..", "backend", *JOB_FILES[name].split("/"))


def launched(call):
    """(kind, params) của một lần batch.launch đã ghi lại bởi FakePopen: cmd = [run_limited.sh, "--", "-m", runner, job_dir]."""
    import json
    cmd = call[0]
    assert cmd[1:4] == ["--", "-m", "backend.api.jobs.runner"], cmd
    with open(os.path.join(cmd[4], "params.json"), encoding="utf-8") as fh:
        spec = json.load(fh)
    return spec["kind"], spec["params"]
