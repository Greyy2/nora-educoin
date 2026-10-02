"""backend.utils.parallel: số worker dùng chung cho mọi đường nặng (resolve_workers / auto_workers / pool_map_safe)."""
import importlib.util
import sys

from backend.utils import memwatch, parallel


def _patch(monkeypatch, budget, cpus):
    monkeypatch.setattr(memwatch, "planning_budget_mb", lambda: budget)
    monkeypatch.setattr(memwatch, "usable_cpus", lambda: cpus)


def test_resolve_workers_int_string_does_not_touch_memory(monkeypatch, capsys):
    def boom():
        raise AssertionError("không được đọc RAM khi truyền số cụ thể")
    monkeypatch.setattr(memwatch, "planning_budget_mb", boom)
    assert parallel.resolve_workers("6", 900, "t") == 6
    assert parallel.resolve_workers(3, 900, "t") == 3
    assert parallel.resolve_workers("0", 900, "t") == 1   # tối thiểu 1
    assert "[auto]" not in capsys.readouterr().out


def test_resolve_workers_auto_prints_and_sizes(monkeypatch, capsys):
    _patch(monkeypatch, 10_000.0, 14)
    assert parallel.resolve_workers("auto", 900, "t") == 11      # 10000 / 900
    assert parallel.resolve_workers(" AUTO ", 900) == 11
    out = capsys.readouterr().out
    assert "[auto] workers=11 (ngân sách RAM 10000 MB, trần mỗi worker 900 MB, CPU 14)" in out


def test_auto_workers_limited_by_cpu_then_ram(monkeypatch):
    _patch(monkeypatch, 100_000.0, 14)
    assert parallel.auto_workers(900) == 14                       # RAM dư -> bị chặn bởi CPU
    _patch(monkeypatch, 3_000.0, 14)
    assert parallel.auto_workers(900) == 3                        # RAM chặn


def test_auto_workers_max_workers_cap(monkeypatch):
    _patch(monkeypatch, 100_000.0, 14)
    assert parallel.auto_workers(900, max_workers=4) == 4
    _patch(monkeypatch, 1_000.0, 14)
    assert parallel.auto_workers(900, max_workers=4) == 1         # RAM thấp hơn trần -> giữ giá trị RAM
    assert parallel.auto_workers(900, max_workers=0) == 1         # không bao giờ < 1


def test_auto_workers_conservative_when_budget_unreadable(monkeypatch):
    _patch(monkeypatch, 0.0, 14)
    assert parallel.auto_workers(900) == 2
    _patch(monkeypatch, 0.0, 1)
    assert parallel.auto_workers(900) == 1
    _patch(monkeypatch, 0.0, 14)
    assert parallel.auto_workers(900, max_workers=1) == 1


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
