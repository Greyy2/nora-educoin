"""Giám sát bộ nhớ tiến trình — đọc /proc/self/status (Linux).

Dùng trong run_book() và các hàm nặng để theo dõi RSS thực tế
mà không cần import psutil (không phải lúc nào cũng cài).
"""
import os
from typing import Any, Dict


def rss_mb() -> float:
    """Trả VmRSS (MB) của tiến trình hiện tại. Trả 0.0 nếu không đọc được."""
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def mem_available_mb() -> float:
    """Trả MemAvailable (MB) từ /proc/meminfo. Trả 0 nếu không đọc được."""
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def cache_report() -> Dict[str, Any]:
    """Thống kê các cache module đang dùng RAM.

    Returns dict với keys:
        candle_cache_items   số mục trong _CANDLE_CACHE (core/loader.py)
        data_cache_items     số mục trong _DATA_CACHE (backtest/portfolio.py)
        rss_mb               RSS tiến trình hiện tại (MB)
    """
    report: Dict[str, Any] = {"rss_mb": round(rss_mb(), 1)}
    try:
        from backend.core.loader import _CANDLE_CACHE
        report["candle_cache_items"] = len(_CANDLE_CACHE)
    except Exception:
        report["candle_cache_items"] = -1
    try:
        from backend.backtest.portfolio import _DATA_CACHE
        report["data_cache_items"] = len(_DATA_CACHE)
    except Exception:
        report["data_cache_items"] = -1
    return report


def check_memory_gate(required_mb: float, label: str = "") -> None:
    """Raise RuntimeError nếu MemAvailable < required_mb.

    Dùng ở đầu script để từ chối chạy sớm trước khi bắt đầu tốn RAM.
    """
    avail = mem_available_mb()
    if avail <= 0:
        return  # không đọc được /proc/meminfo (không phải Linux) — bỏ qua
    if avail < required_mb:
        raise RuntimeError(
            f"Không đủ RAM{f' cho {label}' if label else ''}: "
            f"cần {required_mb:.0f} MB, chỉ có {avail:.0f} MB MemAvailable. "
            "Dừng lại để tránh OOM."
        )
