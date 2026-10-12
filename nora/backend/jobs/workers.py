"""Đa tiến trình + RAM (P9.6): giám sát/giới hạn RAM (memwatch) và pool worker an toàn (parallel).

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.6, P9.8).
"""
import os
from concurrent.futures import as_completed, FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from typing import Any, Callable, Iterable, Iterator, Optional, Tuple


# ══════════════════════════════════════════════════════════════════════════
# Giám sát bộ nhớ tiến trình — đọc /proc và cgroup (Linux), không cần psutil.
#
# - rss_mb / peak_rss_mb: RSS hiện tại (VmRSS) và ĐỈNH từ lúc tiến trình khởi động (VmHWM).
# - planning_budget_mb: RAM một job được phép LẬP KẾ HOẠCH dùng ngay bây giờ (cgroup trừ dự phòng + chừa chỗ cho máy).
# ══════════════════════════════════════════════════════════════════════════

_UNLIMITED_V1 = 1 << 60  # cgroup v1 ghi giá trị cực lớn khi không giới hạn


def _status_mb(field: str) -> float:
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith(field + ":"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def rss_mb() -> float:
    """VmRSS (MB) hiện tại; 0.0 nếu không đọc được."""
    return _status_mb("VmRSS")


def rss_anon_mb() -> float:
    """RssAnon (MB): phần RAM RIÊNG của tiến trình (heap), không gồm trang file mmap dùng chung (RssFile)."""
    return _status_mb("RssAnon")


def peak_rss_mb() -> float:
    """VmHWM (MB): RSS lớn nhất từ khi tiến trình khởi động — số dùng để đặt ngân sách mỗi worker."""
    return _status_mb("VmHWM")


def mem_available_mb() -> float:
    """MemAvailable (MB) của máy; 0 nếu không đọc được."""
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def _read_int(path: str) -> Optional[int]:
    try:
        with open(path, "r") as f:
            raw = f.read().strip()
    except OSError:
        return None
    return None if raw == "max" else int(raw)


def _inactive_file(stat_path: str, key: str) -> int:
    """Page cache KHÔNG hoạt động (byte) trong memory.stat — kernel thu hồi được ngay khi cần, không tính là RAM đang dùng."""
    try:
        with open(stat_path, "r") as f:
            for line in f:
                name, _, val = line.partition(" ")
                if name == key:
                    return int(val)
    except (OSError, ValueError):
        pass
    return 0


def _cgroup_levels():
    """Duyệt mọi cấp cgroup chứa tiến trình (lá -> gốc); yield (giới_hạn_byte, đang_dùng_byte) của cấp có giới hạn thật.
    đang_dùng = memory.current trừ page cache không hoạt động (inactive_file): file mmap dùng chung / dữ liệu đã đọc nằm trong
    cache của cgroup nhưng thu hồi được — tính vào thì chia worker quá ít (đo: 8,6 GB cache -> chỉ 4/14 worker)."""
    try:
        with open("/proc/self/cgroup", "r") as f:
            lines = f.read().splitlines()
    except OSError:
        return
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        hier, controllers, path = parts
        if hier == "0" and controllers == "":           # cgroup v2: kiểm mọi cấp từ lá lên gốc
            base, files, inactive = "/sys/fs/cgroup", ("memory.max", "memory.current"), "inactive_file"
        elif "memory" in controllers.split(","):        # cgroup v1
            base, files, inactive = "/sys/fs/cgroup/memory", ("memory.limit_in_bytes", "memory.usage_in_bytes"), "total_inactive_file"
        else:
            continue
        p = path.rstrip("/")
        while True:
            limit = _read_int(f"{base}{p}/{files[0]}")
            used = _read_int(f"{base}{p}/{files[1]}")
            if limit is not None and limit < _UNLIMITED_V1 and used is not None:
                yield limit, max(0, used - _inactive_file(f"{base}{p}/memory.stat", inactive))
            if not p:
                break
            p = p.rsplit("/", 1)[0]


def cgroup_free_mb() -> Optional[float]:
    """Phần còn trống (MB) của giới hạn bộ nhớ cgroup chặt nhất chứa tiến trình; None nếu không bị giới hạn."""
    free: Optional[float] = None
    for limit, used in _cgroup_levels():
        level_free = max(0.0, (limit - used) / (1024 * 1024))
        free = level_free if free is None else min(free, level_free)
    return free


def cgroup_limit_mb() -> Optional[float]:
    """Giới hạn bộ nhớ (MB) chặt nhất trong chuỗi cgroup chứa tiến trình; None nếu không bị giới hạn."""
    limits = [limit / (1024 * 1024) for limit, _ in _cgroup_levels()]
    return min(limits) if limits else None


def require_memory_limit(label: str) -> float:
    """Bắt buộc script nặng chạy dưới trần RAM cgroup; trả về trần (MB; inf nếu được phép chạy không giới hạn).

    Không có trần và NORA_ALLOW_UNLIMITED != "1" -> SystemExit (server dùng chung, không swap: tràn RAM là sập máy).
    """
    limit = cgroup_limit_mb()
    if limit is None:
        if os.environ.get("NORA_ALLOW_UNLIMITED") != "1":
            raise SystemExit(
                f"[{label}] Script này phải chạy dưới trần RAM (cgroup) — server dùng chung, không có swap, "
                "tràn RAM sẽ làm sập cả máy.\n"
                f"  Chạy: ops/run_limited.sh -- -m backend.<gói>.{label} ...\n"
                "  Hoặc, nếu chắc chắn muốn chạy không giới hạn, đặt NORA_ALLOW_UNLIMITED=1."
            )
        return float("inf")  # chủ động cho phép không giới hạn
    return limit


def worker_init() -> None:
    """Initializer cho ProcessPoolExecutor: đặt oom_score_adj cao để khi OOM kernel giết worker, không giết tiến trình điều phối."""
    try:
        with open("/proc/self/oom_score_adj", "w") as f:
            f.write("1000")
    except Exception:
        pass


def planning_budget_mb() -> float:
    """RAM (MB) một job có thể lập kế hoạch dùng ngay bây giờ (để chia số worker / kiểm cổng RAM).

    cgroup (nora.slice) là trần CỨNG; phần dự phòng của máy (NORA_HOST_RESERVE_MB, mặc định 8000) khiến Nora
    tự lùi khi người khác đang dùng nhiều RAM trên server dùng chung.
    - Có cgroup: min(85% phần trống cgroup, MemAvailable của máy − dự phòng).
    - Không cgroup: 60% MemAvailable. Không đọc được gì -> 0 (người gọi tự xử lý)."""
    try:
        reserve = float(os.environ.get("NORA_HOST_RESERVE_MB", "8000"))
    except ValueError:
        reserve = 8000.0
    host = mem_available_mb()
    host_room = host - reserve if host > 0 else float("inf")
    cg_free = cgroup_free_mb()
    if cg_free is not None:
        return max(0.0, min(cg_free * 0.85, host_room))
    return max(0.0, host * 0.6)


def logical_cpus() -> int:
    """Số CPU logic tiến trình được phép dùng (tôn trọng cpuset/taskset), gồm cả luồng hyper-threading."""
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def physical_cores() -> int:
    """Số core thật trong các CPU được phép dùng (đọc topo /sys); không đọc được -> số CPU logic."""
    try:
        cpus = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return logical_cpus()
    cores = set()
    for c in cpus:
        try:
            with open(f"/sys/devices/system/cpu/cpu{c}/topology/core_id") as f:
                core = f.read().strip()
            with open(f"/sys/devices/system/cpu/cpu{c}/topology/physical_package_id") as f:
                pkg = f.read().strip()
        except OSError:
            return logical_cpus()
        cores.add((pkg, core))
    return max(1, len(cores))


def usable_cpus() -> int:
    """Trần số worker theo CPU: số CPU logic được phép dùng (gồm hyper-threading). Đo P1.16 (10k alpha, 9 chiến lược): 7 worker theo
    core thật = 22,8 alpha/s, mỗi worker nhanh hơn nhưng tổng chậm hơn khi dùng cả luồng HT. NORA_CPU_PHYSICAL=1 -> chỉ core thật
    (ít RAM hơn ~40%)."""
    return physical_cores() if os.environ.get("NORA_CPU_PHYSICAL") == "1" else logical_cpus()


def check_memory_gate(required_mb: float, label: str = "") -> None:
    """Raise RuntimeError nếu ngân sách RAM hiện tại (planning_budget_mb) < required_mb."""
    if mem_available_mb() <= 0 and cgroup_free_mb() is None:
        return  # không đọc được /proc (không phải Linux) — bỏ qua
    budget = planning_budget_mb()
    if budget < required_mb:
        raise RuntimeError(
            f"Không đủ RAM{f' cho {label}' if label else ''}: "
            f"cần {required_mb:.0f} MB, ngân sách hiện còn {budget:.0f} MB "
            "(phần trống của cgroup nora.slice, đã trừ dự phòng NORA_HOST_RESERVE_MB cho máy dùng chung). "
            "Dừng lại để tránh OOM."
        )


# ══════════════════════════════════════════════════════════════════════════
# Chạy song song dùng chung cho mọi đường nặng của Nora: cùng một cách chia số worker theo RAM + CPU.
#
# - auto_workers: số worker = min(CPU dùng được, ngân sách RAM / trần RAM một worker, max_workers).
# - resolve_workers: đổi đối số --workers ("auto" hoặc số nguyên) thành int, in dòng [auto] để dễ kiểm.
# - pool_map_safe: map song song chịu được worker bị kill (OOM) mà không che lỗi thật trong job (giai đoạn nhỏ, danh sách job đủ trong RAM).
# - pool_imap_bounded: như trên nhưng job là một iterator (sinh lười) và kết quả trả dần theo thứ tự hoàn thành, luôn giữ <= max_inflight
#   future đang gửi -> bộ nhớ cha phẳng dù có hàng triệu job (đường tối ưu quy mô lớn).
#
# memwatch được import lúc gọi (không phải lúc import module) để test monkeypatch được `backend.jobs.workers`.
# ══════════════════════════════════════════════════════════════════════════

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
    workers = auto_workers(per_worker_mb)
    print(f"[auto] workers={workers} (ngân sách RAM {planning_budget_mb():.0f} MB, "
          f"trần mỗi worker {per_worker_mb:.0f} MB, CPU {usable_cpus()})"
          f"{f' — {label}' if label else ''}", flush=True)
    return workers
