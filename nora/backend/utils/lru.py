"""Bộ đệm LRU giới hạn theo BYTE (không theo số mục), an toàn đa luồng.

Dùng chung cho core/loader.py (_CANDLE_CACHE) và backtest/portfolio.py (_DATA_CACHE).
- Mỗi tiến trình có bản riêng (multiprocessing); trong một tiến trình, API chạy job trên
  ThreadPoolExecutor nên mọi thao tác đều giữ khoá.
- Mục lớn hơn cả ngân sách thì không cache (và bản cũ cùng khoá bị bỏ).
"""
import os
import threading
from collections import OrderedDict
from typing import Any, Hashable, Optional


def env_mb(name: str, default: float) -> float:
    """Đọc ngân sách MB từ biến môi trường; giá trị hỏng -> default."""
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


class ByteLRU:
    def __init__(self, budget_mb: float):
        self.budget = int(max(0.0, float(budget_mb)) * 1024 * 1024)
        self.used = 0
        self._d: "OrderedDict[Hashable, tuple]" = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: Hashable) -> Optional[Any]:
        with self._lock:
            item = self._d.get(key)
            if item is None:
                return None
            self._d.move_to_end(key)
            return item[0]

    def put(self, key: Hashable, value: Any, nbytes: int) -> None:
        nbytes = int(nbytes)
        with self._lock:
            old = self._d.pop(key, None)
            if old is not None:
                self.used -= old[1]
            if nbytes > self.budget:
                return
            while self._d and self.used + nbytes > self.budget:
                _, (_, n) = self._d.popitem(last=False)
                self.used -= n
            self._d[key] = (value, nbytes)
            self.used += nbytes

    def evict(self, key: Hashable) -> None:
        with self._lock:
            item = self._d.pop(key, None)
            if item is not None:
                self.used -= item[1]

    def clear(self) -> None:
        with self._lock:
            self._d.clear()
            self.used = 0

    def used_mb(self) -> float:
        return self.used / (1024 * 1024)

    def __len__(self) -> int:
        with self._lock:
            return len(self._d)
