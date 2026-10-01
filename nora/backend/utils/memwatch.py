"""Giám sát bộ nhớ tiến trình — đọc /proc và cgroup (Linux), không cần psutil.

- rss_mb / peak_rss_mb: RSS hiện tại (VmRSS) và ĐỈNH từ lúc tiến trình khởi động (VmHWM).
- effective_available_mb: RAM thật sự còn dùng được = min(MemAvailable của máy, phần còn trống của
  giới hạn cgroup). Khi chạy trong `systemd-run -p MemoryMax=...`, MemAvailable của máy không phản ánh
  giới hạn đó — phải đọc memory.max của cgroup.
- planning_budget_mb: RAM một job được phép LẬP KẾ HOẠCH dùng ngay bây giờ (cgroup trừ dự phòng + chừa chỗ cho máy).
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


def _cgroup_levels():
    """Duyệt mọi cấp cgroup chứa tiến trình (lá -> gốc); yield (giới_hạn_byte, đang_dùng_byte) của cấp có giới hạn thật."""
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
                yield limit, used
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
                f"  Chạy: backend/ops/run_limited.sh -- -m backend.cli.{label} ...\n"
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


def effective_available_mb() -> float:
    """min(MemAvailable, phần trống của cgroup). 0 nếu không đọc được gì."""
    avail = mem_available_mb()
    cg = cgroup_free_mb()
    if cg is None:
        return avail
    return min(avail, cg) if avail > 0 else cg


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


def usable_cpus() -> int:
    """Số CPU tiến trình được phép dùng (tôn trọng cpuset/taskset)."""
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def cache_report() -> Dict[str, Any]:
    """RSS hiện tại / đỉnh và kích thước các cache module (số mục + MB)."""
    report: Dict[str, Any] = {"rss_mb": round(rss_mb(), 1), "peak_rss_mb": round(peak_rss_mb(), 1)}
    for name, module, attr in (("candle_cache", "backend.core.data.loader", "_CANDLE_CACHE"),
                               ("data_cache", "backend.core.backtest.portfolio", "_DATA_CACHE")):
        try:
            cache = getattr(__import__(module, fromlist=[attr]), attr)
            report[f"{name}_items"] = len(cache)
            report[f"{name}_mb"] = round(cache.used_mb(), 1)
        except Exception:
            report[f"{name}_items"] = -1
    return report


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
