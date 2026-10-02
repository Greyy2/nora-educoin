"""Làm nóng / dọn kho dữ liệu dùng chung (core/data/shared.py) cho MỌI lối chạy nhiều alpha: dựng sổ (optimize/book), WFA
(wfa/walk_forward) và phễu (optimize/funnel). Một chỗ duy nhất — trước đây mỗi lối có bản riêng.

Kho không bắt buộc đầy đủ: worker thiếu nền / cột / chỉ số nào thì tự tính đúng phần đó và ghi vào kho cho worker khác (song song, không
nghẽn ở tiến trình cha). Làm nóng ở tiến trình cha chỉ để các worker đầu tiên không cùng tính một thứ.
"""
import os
import shutil
import time
from typing import Any, Callable, Iterable, List, Optional, Set, Tuple

from backend.core.backtest.run import BacktestJob, make_engine

STORE_DIRS = ("base", "ft", "fv", "ix")


def release_memory() -> None:
    """Xoá bộ đệm nến / dữ liệu trong tiến trình và trả heap về OS (trước khi fork pool / sau khi xuất)."""
    import ctypes
    import gc
    from backend.core.backtest.portfolio import data_cache_clear
    from backend.core.data.loader import CandleLoader
    CandleLoader.clear_cache()
    data_cache_clear()
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:
        pass


def export_job(job: BacktestJob) -> List[str]:
    """Điền kho cho mọi tài sản của job (job.shared_dir). Chạy được trong worker của pool."""
    from backend.core.data import shared as shared_data
    eng, _ = make_engine(job)
    info = shared_data.export(eng, job.shared_dir)
    release_memory()
    return sorted(info["paths"])


class SharedExporter:
    """Làm nóng kho trước khi chạy pool của một giai đoạn và dọn sau giai đoạn.
    ensure(jobs) / exporter(job): xuất một lần cho mỗi (chiến lược, cửa sổ, khung chạy); song song tối đa `workers` tiến trình.
    to_job: đổi job riêng của lối gọi (vd. dict của phễu) sang BacktestJob."""

    def __init__(self, shared_dir: Optional[str], label: str = "", workers: int = 1,
                 to_job: Optional[Callable[[Any], BacktestJob]] = None):
        self.shared_dir, self.label, self.workers, self.to_job = shared_dir, label, max(1, int(workers)), to_job
        self.seen: Set[Tuple] = set()
        self.t0 = time.time()

    def ensure(self, jobs: Iterable[Any]) -> None:
        if not self.shared_dir:
            return
        todo = []
        for j in jobs:
            job = self.to_job(j) if self.to_job else j
            memo = (tuple(cid for cid, _ in job.items), tuple(job.window), job.base_frame)
            if memo in self.seen:
                continue
            self.seen.add(memo)
            todo.append(job._replace(shared_dir=self.shared_dir))
        if not todo:
            return
        os.makedirs(self.shared_dir, exist_ok=True)
        if self.workers <= 1 or len(todo) == 1:
            for job in todo:
                export_job(job)
        else:
            from backend.utils.parallel import pool_map_safe
            pool_map_safe(export_job, todo, min(self.workers, len(todo)), f"[shared] {self.label}")

    def __call__(self, job: Any) -> None:
        self.ensure([job])

    def cleanup(self) -> None:
        """Xoá toàn bộ kho của giai đoạn (gồm phần worker tự điền) — các giai đoạn chạy tuần tự nên an toàn."""
        if not self.shared_dir:
            return
        from backend.core.data import shared as shared_data
        mb = shared_data.size_mb(self.shared_dir) if os.path.isdir(self.shared_dir) else 0.0
        for sub in STORE_DIRS:
            shutil.rmtree(os.path.join(self.shared_dir, sub), ignore_errors=True)
        if self.label:
            print(f"[shared] {self.label}: dọn {mb:.0f} MB ({time.time() - self.t0:.0f}s)", flush=True)
        self.seen.clear()
