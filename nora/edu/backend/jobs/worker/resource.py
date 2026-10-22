"""Giám sát tài nguyên hệ thống (RAM, CPU, CGroup) cho Nora Jobs."""
import os
import sys
from typing import Any, List, Optional

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
            return int(f.read().strip())
    except Exception:
        return None


def _cgroup_paths() -> List[str]:
    """Tìm tất cả các đường dẫn cgroup tiềm năng của tiến trình (từ scope/slice con lên root)."""
    paths = []
    slice_cg = os.environ.get("NORA_SLICE_CG")
    if slice_cg and os.path.isdir(slice_cg):
        paths.append(slice_cg)
    try:
        uid = os.getuid()
        default_nora_cg = f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/nora.slice"
        if os.path.isdir(default_nora_cg) and default_nora_cg not in paths:
            paths.append(default_nora_cg)
    except Exception:
        pass
    try:
        with open("/proc/self/cgroup", "r") as f:
            for line in f:
                parts = line.strip().split(":")
                if len(parts) >= 3 and parts[2]:
                    cg_rel = parts[2].lstrip("/")
                    curr = os.path.join("/sys/fs/cgroup", cg_rel)
                    while curr and curr.startswith("/sys/fs/cgroup"):
                        if curr not in paths and os.path.isdir(curr):
                            paths.append(curr)
                        if curr == "/sys/fs/cgroup":
                            break
                        curr = os.path.dirname(curr)
    except Exception:
        pass
    if "/sys/fs/cgroup" not in paths and os.path.isdir("/sys/fs/cgroup"):
        paths.append("/sys/fs/cgroup")
    return paths


def cgroup_limit_mb() -> Optional[float]:
    """Giới hạn RAM của cgroup (v2 memory.max hoặc v1 memory.limit_in_bytes) tính theo MB; None nếu không giới hạn."""
    for cg_dir in _cgroup_paths():
        val = _read_int(os.path.join(cg_dir, "memory.max"))
        if val is not None and val < _UNLIMITED_V1:
            return val / 1024.0 / 1024.0
        val = _read_int(os.path.join(cg_dir, "memory.limit_in_bytes"))
        if val is not None and val < _UNLIMITED_V1:
            return val / 1024.0 / 1024.0
        val = _read_int(os.path.join(cg_dir, "memory/memory.limit_in_bytes"))
        if val is not None and val < _UNLIMITED_V1:
            return val / 1024.0 / 1024.0
    return None


def cgroup_usage_mb() -> Optional[float]:
    """RAM cgroup đang dùng (v2 memory.current hoặc v1 memory.usage_in_bytes) tính theo MB; None nếu không đọc được."""
    for cg_dir in _cgroup_paths():
        val = _read_int(os.path.join(cg_dir, "memory.current"))
        if val is not None:
            return val / 1024.0 / 1024.0
        val = _read_int(os.path.join(cg_dir, "memory.usage_in_bytes"))
        if val is not None:
            return val / 1024.0 / 1024.0
        val = _read_int(os.path.join(cg_dir, "memory/memory.usage_in_bytes"))
        if val is not None:
            return val / 1024.0 / 1024.0
    return None


def cgroup_free_mb() -> Optional[float]:
    """RAM còn trống trong cgroup = limit - current (MB); None nếu không bị giới hạn bởi cgroup."""
    limit = cgroup_limit_mb()
    if limit is None:
        return None
    usage = cgroup_usage_mb() or 0.0
    return max(0.0, limit - usage)


def host_reserve_mb() -> float:
    """Dự phòng RAM cho máy dùng chung (MB) — mặc định 8000 MB, chỉnh qua biến môi trường NORA_HOST_RESERVE_MB."""
    try:
        return float(os.environ.get("NORA_HOST_RESERVE_MB", "8000"))
    except ValueError:
        return 8000.0


def planning_budget_mb() -> float:
    """Ngân sách RAM (MB) tiến trình được phép LẬP KẾ HOẠCH dùng:
    - Nếu chạy trong cgroup có limit: min(85% cgroup trống, MemAvailable − dự phòng).
    - Nếu không có cgroup: 60% MemAvailable.
    """
    cg = cgroup_free_mb()
    host_avail = mem_available_mb()
    reserve = host_reserve_mb()
    if cg is not None:
        if cg <= 0.0 or host_avail <= reserve:
            return 0.0
        return max(0.0, min(cg * 0.85, host_avail - reserve))
    return max(0.0, host_avail * 0.6)


def logical_cpus() -> int:
    """Số CPU logic tiến trình được phép dùng (tôn trọng cpuset/taskset)."""
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def physical_cores() -> int:
    """Số core thật trong các CPU được phép dùng."""
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
    """Trần số worker theo CPU."""
    return physical_cores() if os.environ.get("NORA_CPU_PHYSICAL") == "1" else logical_cpus()


def check_memory_gate(required_mb: float, label: str = "") -> None:
    """Raise RuntimeError nếu ngân sách RAM hiện tại < required_mb."""
    if mem_available_mb() <= 0 and cgroup_free_mb() is None:
        return
    budget = planning_budget_mb()
    if budget < required_mb:
        raise RuntimeError(
            f"Không đủ RAM{f' cho {label}' if label else ''}: "
            f"cần {required_mb:.0f} MB, ngân sách hiện còn {budget:.0f} MB "
            "(đã trừ dự phòng NORA_HOST_RESERVE_MB). "
            "Dừng lại để tránh OOM."
        )


def auto_workers(mb_per_worker: float, max_workers: Optional[int] = None, min_workers: int = 1) -> int:
    """Tính số worker an toàn: min(usable_cpus, budget_mb / mb_per_worker, max_workers)."""
    cpus = usable_cpus()
    budget = planning_budget_mb()
    if budget <= 0.0:
        w = min(cpus, 2)
    else:
        ram_w = int(budget / max(1.0, float(mb_per_worker)))
        w = min(cpus, ram_w)
    if max_workers is not None:
        if max_workers > 0:
            w = min(w, max_workers)
        else:
            w = 1
    return max(min_workers, max(1, w))


def resolve_workers(workers_spec: Any, mb_per_worker: float, label: str = "", max_workers: Optional[int] = None) -> int:
    """Chuyển đổi workers_spec ('auto' hoặc số) sang int."""
    spec_str = str(workers_spec).strip()
    if spec_str.lower() in ("auto", "none", ""):
        budget = planning_budget_mb()
        w = auto_workers(mb_per_worker, max_workers=max_workers)
        cpus = usable_cpus()
        print(f"[auto] workers={w} (ngân sách RAM {budget:.0f} MB, trần mỗi worker {mb_per_worker:.0f} MB, CPU {cpus})")
        return w
    try:
        val = int(spec_str)
        return max(1, val)
    except Exception:
        return 1


def require_memory_limit(label: str) -> float:
    """Bắt buộc script nặng chạy dưới trần RAM cgroup; trả về trần (MB; inf nếu được phép chạy không giới hạn)."""
    limit = cgroup_limit_mb()
    if limit is None:
        if os.environ.get("NORA_ALLOW_UNLIMITED") != "1":
            raise SystemExit(
                f"[{label}] Script này phải chạy dưới trần RAM (cgroup) — server dùng chung, không có swap, "
                "tràn RAM sẽ làm sập cả máy.\n"
                f"  Chạy: ops/run_limited.sh -- -m backend.<gói>.{label} ...\n"
                "  Hoặc, nếu chắc chắn muốn chạy không giới hạn, đặt NORA_ALLOW_UNLIMITED=1."
            )
        return float("inf")
    return limit


# Re-exports cho tính tương thích ngược hoàn chỉnh của backend.jobs.workers
from .pool import pool_map_safe, worker_init, pool_imap_bounded  # noqa: E402

