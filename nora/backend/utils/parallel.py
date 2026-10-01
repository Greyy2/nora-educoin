"""Chạy song song dùng chung cho mọi đường nặng của Nora: cùng một cách chia số worker theo RAM + CPU.

- auto_workers: số worker = min(CPU dùng được, ngân sách RAM / trần RAM một worker, max_workers).
- resolve_workers: đổi đối số --workers ("auto" hoặc số nguyên) thành int, in dòng [auto] để dễ kiểm.
- pool_map_safe: map song song chịu được worker bị kill (OOM) mà không che lỗi thật trong job.

memwatch được import lúc gọi (không phải lúc import module) để test monkeypatch được `backend.utils.memwatch`.
"""
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from typing import Optional


def pool_map_safe(pool_fn, jobs: list, workers: int, label: str) -> list:
    """Chạy jobs song song, trả kết quả ĐÚNG thứ tự jobs.

    - Lỗi trong job (bug, dữ liệu hỏng...) nổi lên ngay và huỷ các job đang chờ — không che lỗi.
    - Chỉ khi pool bị hỏng (worker bị kill, thường do hết RAM / cgroup OOM): giữ kết quả đã xong,
      chạy lại một lần CHỈ các job còn thiếu với nửa số worker.
    """
    results = [None] * len(jobs)
    done = [False] * len(jobs)
    n_workers = max(1, min(int(workers), len(jobs)))
    for attempt in (1, 2):
        pending = [i for i in range(len(jobs)) if not done[i]]
        if not pending:
            break
        from backend.utils.memwatch import worker_init
        pool = ProcessPoolExecutor(max_workers=n_workers, initializer=worker_init)
        futures = {}
        try:
            futures = {pool.submit(pool_fn, jobs[i]): i for i in pending}
            for fut in as_completed(futures):
                i = futures[fut]
                results[i] = fut.result()
                done[i] = True
        except BrokenProcessPool as exc:
            pool.shutdown(wait=False, cancel_futures=True)
            for fut, i in futures.items():  # job đã xong nhưng chưa kịp lấy kết quả
                if fut.done() and not fut.cancelled() and fut.exception() is None:
                    results[i] = fut.result()
                    done[i] = True
            missing = sum(not d for d in done)
            if attempt == 2:
                raise RuntimeError(f"{label}: pool vẫn hỏng sau khi giảm còn {n_workers} worker "
                                   f"({missing} job chưa xong)") from exc
            n_workers = max(1, n_workers // 2)
            print(f"[WARN] {label}: worker bị kill (thường do hết RAM) — chạy lại {missing} job còn thiếu "
                  f"với {n_workers} worker", flush=True)
            continue
        except BaseException:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        pool.shutdown(wait=True)
    return results


def auto_workers(per_worker_mb: float, max_workers: Optional[int] = None) -> int:
    """Số worker = min(CPU dùng được, ngân sách RAM / trần RAM một worker[, max_workers]).

    Ngân sách = planning_budget_mb(): phần trống của cgroup nora.slice (85%), không vượt quá MemAvailable của máy
    trừ dự phòng cho người dùng khác; không có cgroup thì 60% MemAvailable. CPU dùng được tôn trọng taskset
    (taskset -c 0-5 -> 6); không trừ CPU cho tiến trình điều phối vì nó hầu như chỉ chờ."""
    from backend.utils.memwatch import planning_budget_mb, usable_cpus
    cpu_limit = max(1, usable_cpus())
    avail = planning_budget_mb()
    if avail <= 0:
        n = min(cpu_limit, 2)  # không đọc được RAM: chạy dè dặt
    else:
        n = max(1, min(cpu_limit, int(avail / per_worker_mb)))
    if max_workers is not None:
        n = max(1, min(n, int(max_workers)))
    return n


def resolve_workers(arg, per_worker_mb: float, label: str = "") -> int:
    """`--workers`: "auto" -> auto_workers(per_worker_mb) (in dòng [auto]); chuỗi/số nguyên -> int (tối thiểu 1)."""
    if str(arg).strip().lower() != "auto":
        return max(1, int(arg))
    from backend.utils.memwatch import planning_budget_mb, usable_cpus
    workers = auto_workers(per_worker_mb)
    print(f"[auto] workers={workers} (ngân sách RAM {planning_budget_mb():.0f} MB, "
          f"trần mỗi worker {per_worker_mb:.0f} MB, CPU {usable_cpus()})"
          f"{f' — {label}' if label else ''}", flush=True)
    return workers
