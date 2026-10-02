"""Chạy một giai đoạn tối ưu theo kiểu STREAMING: job sinh lười -> pool (bounded) -> ghi ngay vào ResultsStore -> chỉ giữ top-K trong RAM.

stream_stage() là khung dùng chung cho build_strategy_book (giai đoạn A) và sàng lọc của optimize_alphas:
  - bỏ qua job đã có trong kho (job_key) -> `--resume` tiếp tục đúng chỗ dừng, kết quả cuối y hệt lần chạy không gián đoạn;
  - kết quả mỗi job được chuẩn hoá qua JSON (cùng cấu trúc dù lấy từ worker hay từ kho) trước khi đưa cho `handle`;
  - `handle(ord, params, metrics, from_store) -> (metrics_để_lưu, điểm)` quyết định lưu gì (vd. bỏ chuỗi `daily` của hàng không thuộc top-K).
"""
import itertools
import json
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

from backend.optimize.results_store import ResultsStore
from backend.utils.jsonsafe import json_default
from backend.utils.parallel import pool_imap_bounded


def normalize(obj: Any) -> Any:
    """Qua một vòng JSON (np.float64 -> float, tuple -> list...) — đúng thứ sẽ đọc lại từ kho."""
    return json.loads(json.dumps(obj, default=json_default, allow_nan=True))


def stream_stage(items: Iterable[Tuple[int, Any, Any]], fn: Callable, *, workers: int, label: str,
                 store: Optional[ResultsStore], stage: str, candidate: str,
                 key_of: Callable[[int, Any, Any], str],
                 handle: Callable[[int, Any, Dict[str, Any], bool], Tuple[Dict[str, Any], Optional[float]]],
                 progress=None, max_inflight: Optional[int] = None,
                 prepare: Optional[Callable[[Any], None]] = None) -> Dict[str, int]:
    """items: iterable lười của (ord, params, job). Trả {"new": số job vừa chạy, "resumed": số job lấy từ kho}."""
    pending: Dict[int, Tuple[int, Any, str]] = {}
    counts = {"new": 0, "resumed": 0}

    def feeder():
        seq = itertools.count()
        for ord_, params, job in items:
            key = key_of(ord_, params, job)
            row = store.get(key) if store is not None else None
            if row is not None:
                handle(ord_, params, row["metrics"], True)
                counts["resumed"] += 1
                if progress is not None:
                    progress.tick(resumed=True)
                continue
            if prepare is not None:
                prepare(job)
            pending[next(seq)] = (ord_, params, key)
            yield job

    for i, res in pool_imap_bounded(fn, feeder(), workers, label, max_inflight):
        ord_, params, key = pending.pop(i)
        metrics = normalize(res)
        to_store, score = handle(ord_, params, metrics, False)
        if store is not None:
            store.put(key, stage, candidate, params, to_store, ord=ord_, score=score)
        counts["new"] += 1
        if progress is not None:
            progress.tick(worker_peak_mb=metrics.get("_peak_rss_mb") if isinstance(metrics, dict) else None)
    return counts
