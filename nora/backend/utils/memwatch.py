"""Giám sát bộ nhớ tiến trình — đọc /proc và cgroup (Linux), không cần psutil.

- rss_mb / peak_rss_mb: RSS hiện tại (VmRSS) và ĐỈNH từ lúc tiến trình khởi động (VmHWM).
- effective_available_mb: RAM thật sự còn dùng được = min(MemAvailable của máy, phần còn trống của
  giới hạn cgroup). Khi chạy trong `systemd-run -p MemoryMax=...`, MemAvailable của máy không phản ánh
  giới hạn đó — phải đọc memory.max của cgroup.
"""
import os
from typing import Any, Dict, Optional

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


def cgroup_free_mb() -> Optional[float]:
    """Phần còn trống (MB) của giới hạn bộ nhớ cgroup chặt nhất chứa tiến trình; None nếu không bị giới hạn."""
    try:
        with open("/proc/self/cgroup", "r") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    free: Optional[float] = None
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        hier, controllers, path = parts
        if hier == "0" and controllers == "":           # cgroup v2: kiểm mọi cấp từ lá lên gốc
            base, files = "/sys/fs/cgroup", ("memory.max", "memory.current")
        elif "memory" in controllers.split(","):        # cgroup v1
            base, files = "/sys/fs/cgroup/memory", ("memory.limit_in_bytes", "memory.usage_in_bytes")
        else:
            continue
        p = path.rstrip("/")
        while True:
            limit = _read_int(f"{base}{p}/{files[0]}")
            used = _read_int(f"{base}{p}/{files[1]}")
            if limit is not None and limit < _UNLIMITED_V1 and used is not None:
                level_free = max(0.0, (limit - used) / (1024 * 1024))
                free = level_free if free is None else min(free, level_free)
            if not p:
                break
            p = p.rsplit("/", 1)[0]
    return free


def effective_available_mb() -> float:
    """min(MemAvailable, phần trống của cgroup). 0 nếu không đọc được gì."""
    avail = mem_available_mb()
    cg = cgroup_free_mb()
    if cg is None:
        return avail
    return min(avail, cg) if avail > 0 else cg


def usable_cpus() -> int:
    """Số CPU tiến trình được phép dùng (tôn trọng cpuset/taskset)."""
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def cache_report() -> Dict[str, Any]:
    """RSS hiện tại / đỉnh và kích thước các cache module (số mục + MB)."""
    report: Dict[str, Any] = {"rss_mb": round(rss_mb(), 1), "peak_rss_mb": round(peak_rss_mb(), 1)}
    for name, module, attr in (("candle_cache", "backend.core.loader", "_CANDLE_CACHE"),
                               ("data_cache", "backend.backtest.portfolio", "_DATA_CACHE")):
        try:
            cache = getattr(__import__(module, fromlist=[attr]), attr)
            report[f"{name}_items"] = len(cache)
            report[f"{name}_mb"] = round(cache.used_mb(), 1)
        except Exception:
            report[f"{name}_items"] = -1
    return report


def check_memory_gate(required_mb: float, label: str = "") -> None:
    """Raise RuntimeError nếu RAM dùng được (gồm giới hạn cgroup) < required_mb."""
    avail = effective_available_mb()
    if avail <= 0:
        return  # không đọc được /proc (không phải Linux) — bỏ qua
    if avail < required_mb:
        raise RuntimeError(
            f"Không đủ RAM{f' cho {label}' if label else ''}: "
            f"cần {required_mb:.0f} MB, chỉ có {avail:.0f} MB dùng được (MemAvailable/cgroup). "
            "Dừng lại để tránh OOM."
        )
