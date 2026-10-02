"""Chạy song song dùng chung cho mọi đường nặng của Nora: cùng một cách chia số worker theo RAM + CPU.

- auto_workers: số worker = min(CPU dùng được, ngân sách RAM / trần RAM một worker, max_workers).
- resolve_workers: đổi đối số --workers ("auto" hoặc số nguyên) thành int, in dòng [auto] để dễ kiểm.
- pool_map_safe: map song song chịu được worker bị kill (OOM) mà không che lỗi thật trong job (giai đoạn nhỏ, danh sách job đủ trong RAM).
- pool_imap_bounded: như trên nhưng job là một iterator (sinh lười) và kết quả trả dần theo thứ tự hoàn thành, luôn giữ <= max_inflight
  future đang gửi -> bộ nhớ cha phẳng dù có hàng triệu job (đường tối ưu quy mô lớn).

memwatch được import lúc gọi (không phải lúc import module) để test monkeypatch được `backend.utils.memwatch`.
"""
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, as_completed, wait
from concurrent.futures.process import BrokenProcessPool
from typing import Any, Callable, Iterable, Iterator, Optional, Tuple


def _abort_pool(pool, exc: BaseException) -> None:
    """Đóng pool khi có lỗi/huỷ. SIGTERM/Ctrl-C của tiến trình cha (SystemExit/KeyboardInterrupt) -> kết thúc luôn các worker
    đang chạy dở (không để chúng chạy tiếp sau khi cha đã thoát); lỗi job thường thì giữ hành vi cũ (chỉ huỷ job chưa chạy)."""
    procs = getattr(pool, "_processes", None) or {}
    procs = list(procs.values()) if isinstance(procs, dict) else list(procs)   # lấy TRƯỚC shutdown (shutdown xoá bảng tiến trình)
    pool.shutdown(wait=False, cancel_futures=True)
    if isinstance(exc, (SystemExit, KeyboardInterrupt)):
        for proc in procs:
            try:
                proc.terminate()
            except Exception:
                pass


def pool_map_safe(pool_fn, jobs: list, workers: int, label: str, on_done: Optional[Callable[[int, Any], None]] = None) -> list:
    """Chạy jobs song song, trả kết quả ĐÚNG thứ tự jobs.

    - Lỗi trong job (bug, dữ liệu hỏng...) nổi lên ngay và huỷ các job đang chờ — không che lỗi.
    - Chỉ khi pool bị hỏng (worker bị kill, thường do hết RAM / cgroup OOM): giữ kết quả đã xong,
      chạy lại một lần CHỈ các job còn thiếu với nửa số worker.
    - on_done(i, kết quả) (tuỳ chọn) được gọi mỗi khi một job xong (để ghi tiến độ).
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
                if on_done is not None:
                    on_done(i, results[i])
        except BrokenProcessPool as exc:
            pool.shutdown(wait=False, cancel_futures=True)
            for fut, i in futures.items():  # job đã xong nhưng chưa kịp lấy kết quả
                if fut.done() and not fut.cancelled() and fut.exception() is None and not done[i]:
                    results[i] = fut.result()
                    done[i] = True
                    if on_done is not None:
                        on_done(i, results[i])
            missing = sum(not d for d in done)
            if attempt == 2:
                raise RuntimeError(f"{label}: pool vẫn hỏng sau khi giảm còn {n_workers} worker "
                                   f"({missing} job chưa xong)") from exc
            n_workers = max(1, n_workers // 2)
            print(f"[WARN] {label}: worker bị kill (thường do hết RAM) — chạy lại {missing} job còn thiếu "
                  f"với {n_workers} worker", flush=True)
            continue
        except BaseException as exc:
            _abort_pool(pool, exc)
            raise
        pool.shutdown(wait=True)
    return results


def pool_imap_bounded(fn, job_iter: Iterable, workers: int, label: str,
                      max_inflight: Optional[int] = None) -> Iterator[Tuple[int, Any]]:
    """Chạy fn trên từng job của `job_iter` (iterator, sinh lười), yield (chỉ số job theo thứ tự sinh, kết quả) NGAY khi xong.

    - Luôn giữ <= max_inflight (mặc định workers*4) future đã gửi: không bao giờ nạp cả iterator vào RAM.
    - Lỗi trong job nổi lên ngay, huỷ các job đang chờ (không che lỗi) — như pool_map_safe.
    - Chỉ khi pool hỏng (worker bị kill, thường do hết RAM): giữ kết quả đã yield, chạy lại CHỈ các job đã gửi mà chưa xong rồi
      tiếp tục phần iterator còn lại với nửa số worker; hỏng lần hai -> RuntimeError (một lần thử lại, như pool_map_safe).
    - Đóng generator sớm (break / ngoại lệ / SIGTERM của cha) -> pool bị đóng, các job chưa chạy bị huỷ."""
    it = iter(enumerate(job_iter))
    n_workers = max(1, int(workers))
    cap = max(1, int(max_inflight) if max_inflight else n_workers * 4)
    retry: list = []          # (index, job) đã gửi nhưng chưa xong khi pool hỏng
    exhausted = False
    from backend.utils.memwatch import worker_init
    for attempt in (1, 2):
        pool = ProcessPoolExecutor(max_workers=n_workers, initializer=worker_init)
        inflight: dict = {}   # future -> (index, job)
        try:
            while True:
                while len(inflight) < cap:
                    if retry:
                        i, job = retry.pop(0)
                    elif not exhausted:
                        nxt = next(it, None)
                        if nxt is None:
                            exhausted = True
                            continue
                        i, job = nxt
                    else:
                        break
                    inflight[pool.submit(fn, job)] = (i, job)
                if not inflight:
                    break
                finished, _ = wait(list(inflight), return_when=FIRST_COMPLETED)
                for fut in finished:
                    i, job = inflight[fut]
                    res = fut.result()          # lỗi trong job -> bay lên (BrokenProcessPool nếu pool hỏng)
                    del inflight[fut]
                    yield i, res
            pool.shutdown(wait=True)
            return
        except BrokenProcessPool as exc:
            pool.shutdown(wait=False, cancel_futures=True)
            for fut, (i, job) in list(inflight.items()):   # job đã xong nhưng chưa kịp lấy kết quả
                if fut.done() and not fut.cancelled() and fut.exception() is None:
                    inflight.pop(fut)
                    yield i, fut.result()
            retry = sorted(inflight.values(), key=lambda v: v[0])
            if attempt == 2:
                raise RuntimeError(f"{label}: pool vẫn hỏng sau khi giảm còn {n_workers} worker "
                                   f"({len(retry)} job đã gửi chưa xong)") from exc
            n_workers = max(1, n_workers // 2)
            print(f"[WARN] {label}: worker bị kill (thường do hết RAM) — chạy lại {len(retry)} job còn thiếu "
                  f"với {n_workers} worker", flush=True)
            continue
        except BaseException as exc:
            _abort_pool(pool, exc)
            raise


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
