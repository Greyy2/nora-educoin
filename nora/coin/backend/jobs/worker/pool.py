"""Thực thi song song an toàn, chống leak RAM và OOM."""
import gc
import os
import signal
import sys
from concurrent.futures import as_completed, FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from typing import Any, Callable, Iterable, Iterator, List, Optional, Tuple


def worker_init():
    """Khởi tạo môi trường trong worker tiến trình con."""
    # Reset signal handlers cho worker con
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def _abort_pool(pool, exc: BaseException) -> None:
    """Đóng pool khi có lỗi/huỷ."""
    procs = getattr(pool, "_processes", None) or {}
    procs = list(procs.values()) if isinstance(procs, dict) else list(procs)
    pool.shutdown(wait=False, cancel_futures=True)
    if isinstance(exc, (SystemExit, KeyboardInterrupt)):
        for proc in procs:
            try:
                proc.terminate()
            except Exception:
                pass


def pool_map_safe(pool_fn: Callable, jobs: list, workers: int, label: str, on_done: Optional[Callable[[int, Any], None]] = None) -> list:
    """Chạy jobs song song, trả kết quả ĐÚNG thứ tự jobs."""
    results = [None] * len(jobs)
    done = [False] * len(jobs)
    n_workers = max(1, min(int(workers), len(jobs)))
    for attempt in (1, 2):
        pending = [i for i in range(len(jobs)) if not done[i]]
        if not pending:
            break
        cur_w = n_workers if attempt == 1 else max(1, n_workers // 2)
        if attempt == 2:
            print(f"[WARN] [{label}] Worker bị ngắt, thử lại {len(pending)} jobs với {cur_w} workers...")
        pool = ProcessPoolExecutor(max_workers=cur_w, initializer=worker_init)
        fut_map = {}
        try:
            for idx in pending:
                fut = pool.submit(pool_fn, jobs[idx])
                fut_map[fut] = idx
            for fut in as_completed(fut_map):
                idx = fut_map[fut]
                res = fut.result()
                results[idx] = res
                done[idx] = True
                if on_done:
                    on_done(idx, res)
        except BrokenProcessPool as bpp:
            _abort_pool(pool, bpp)
            if attempt == 2:
                raise RuntimeError(f"[{label}] Pool worker chết 2 lần liên tiếp do cạn kiệt RAM/OOM") from bpp
            continue
        except BaseException as exc:
            _abort_pool(pool, exc)
            raise
        finally:
            pool.shutdown(wait=False)
    return results


def pool_imap_bounded(
    pool_fn: Callable,
    jobs_iter: Iterator[Any],
    workers: int,
    max_inflight: int = 16,
    label: str = "imap",
) -> Iterator[Tuple[int, Any]]:
    """Chạy iterator lười, giữ giới hạn memory phẳng."""
    n_workers = max(1, workers)
    pool = ProcessPoolExecutor(max_workers=n_workers, initializer=worker_init)
    inflight = {}
    job_idx = 0
    iter_exhausted = False

    try:
        while not iter_exhausted or inflight:
            while len(inflight) < max_inflight and not iter_exhausted:
                try:
                    job = next(jobs_iter)
                    fut = pool.submit(pool_fn, job)
                    inflight[fut] = job_idx
                    job_idx += 1
                except StopIteration:
                    iter_exhausted = True
                    break

            if not inflight:
                break

            done, _ = wait(inflight.keys(), return_when=FIRST_COMPLETED)
            for fut in done:
                idx = inflight.pop(fut)
                res = fut.result()
                yield idx, res
    except BaseException as exc:
        _abort_pool(pool, exc)
        raise
    finally:
        pool.shutdown(wait=False)
