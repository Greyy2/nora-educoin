# Đã chuyển khỏi test/ (P17 T1-B5c): script dựng sổ (build_strategy_book) đã gỡ; bản gốc ở tag pre-p17-research.
"""backend.jobs.workers: số worker dùng chung cho mọi đường nặng (resolve_workers / auto_workers / pool_map_safe)."""
import importlib.util
import sys
from backend.jobs import workers as memwatch, workers as parallel


def test_build_strategy_book_aliases_point_to_parallel_module():
    name = "build_strategy_book"
    from job_modules import job_path
    path = job_path(name)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    assert mod._pool_map_safe is parallel.pool_map_safe
    assert mod._auto_workers is parallel.auto_workers
