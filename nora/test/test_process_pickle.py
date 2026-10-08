"""P9.6 — hàm worker gửi qua ProcessPoolExecutor được pickle theo `module.qualname`: dời hàm giữa các file mà không giữ tên thì pool hỏng lặng lẽ.

Với mỗi worker (run_book, export_job, w_*, worker_init, lớp BacktestJob): (1) pickle round-trip trả đúng đối tượng; (2) `__module__` là NHÀ MỚI
(đường cũ chỉ là alias); (3) một tiến trình `spawn` (interpreter sạch, chỉ import theo tên) giải pickle ra đúng hàm và chạy được initializer.
Bảng HOME cập nhật theo từng bước P9.6.
"""
import concurrent.futures as cf
import importlib
import multiprocessing as mp
import pickle

import pytest

# (đường cũ, tên, nhà mới)
EVAL = "backend.optimize.search.evaluate"
HOME = [
    ("backend.optimize.search.evaluate", "w_backtest", EVAL),
    ("backend.optimize.search.evaluate", "w_backtest_group", EVAL),
    ("backend.optimize.search.evaluate", "w_backtest_group_rss", EVAL),
    ("backend.optimize.search.evaluate", "w_wfa", EVAL),
    ("backend.optimize.search.evaluate", "w_mc", EVAL),
    ("backend.optimize.search.evaluate", "w_sizing", EVAL),
    ("backend.optimize.search.evaluate", "w_holdout", EVAL),
    ("backend.optimize.search.evaluate", "export_job", EVAL),
    ("backend.optimize.book.build", "run_book", "backend.optimize.book.build"),
    ("backend.optimize.process.workers", "worker_init", "backend.optimize.process.workers"),
    ("backend.optimize.search.evaluate", "BacktestJob", EVAL),
]


def _resolve(blob):
    """Chạy TRONG tiến trình spawn: giải pickle -> (module, qualname)."""
    obj = pickle.loads(blob)
    return obj.__module__, obj.__qualname__


def _noop():
    return None


def _load(old, name):
    return getattr(importlib.import_module(old), name)


@pytest.mark.parametrize("old,name,home", HOME)
def test_roundtrip_and_home(old, name, home):
    obj = _load(old, name)
    assert pickle.loads(pickle.dumps(obj)) is obj
    assert obj.__module__ == home, f"{old}.{name} nên sống ở {home}, đang ở {obj.__module__}"
    assert _load(home, name) is obj


def test_spawn_pool_resolves_all_workers():
    from backend.optimize.process.workers import worker_init
    blobs = [pickle.dumps(_load(old, name)) for old, name, _ in HOME]
    ctx = mp.get_context("spawn")
    with cf.ProcessPoolExecutor(max_workers=2, mp_context=ctx, initializer=worker_init) as pool:
        got = list(pool.map(_resolve, blobs))
        assert pool.submit(_noop).result() is None
    assert got == [(home, name) for _, name, home in HOME]
