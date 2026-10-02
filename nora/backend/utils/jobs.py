"""Tiện ích chung cho job nền (chạy qua api/jobs/runner.py): tham số, kết quả, tiến độ, huỷ an toàn.

Tiến độ + huỷ an toàn cho job dài: <run_dir>/progress.json (ghi tối đa mỗi 5 giây) và xử lý SIGTERM.

progress.json = {"run_dir", "stage", "done", "total", "rate" (job/giây của giai đoạn), "eta_s", "elapsed_s", "peak_rss_mb" (tiến trình cha),
                 "worker_peak_rss_mb", "status": running|done|cancelled|failed, "updated", "estimate": {...}}
Nếu env NORA_JOB_DIR có đặt (job của API) file được ghi thêm vào đó để API (backend/api/jobs/batch.py) hiển thị.

SIGTERM (nút "Huỷ" của API gửi cho cả nhóm tiến trình): handler ném SystemExit(143) ở luồng chính -> các khối finally của job flush kho kết quả
(ResultsStore.close) rồi ghi progress status="cancelled" -> chạy lại với --resume tiếp tục đúng chỗ dừng.

Thêm: write_job_result (result.json của job API) và options (tham số job: mặc định + giá trị truyền vào, từ chối khoá lạ).
"""
import contextlib
import json
import os
import signal
import time
from types import SimpleNamespace
from typing import Any, Dict, Iterator, Optional, Sequence

from backend.utils.jsonsafe import json_default

WRITE_EVERY_S = 5.0


class Progress:
    def __init__(self, run_dir: Optional[str], extra_dirs: Sequence[str] = (), min_interval: float = WRITE_EVERY_S):
        paths = []
        if run_dir:
            paths.append(os.path.join(run_dir, "progress.json"))
        for d in list(extra_dirs) + ([os.environ["NORA_JOB_DIR"]] if os.environ.get("NORA_JOB_DIR") else []):
            p = os.path.join(d, "progress.json")
            if p not in paths:
                paths.append(p)
        self.paths = paths
        self.run_dir = os.path.abspath(run_dir) if run_dir else None
        self.min_interval = float(min_interval)
        self.t_start = time.time()
        self.stage = ""
        self.total = 0
        self.done = 0
        self.base_done = 0           # số job đã xong TRƯỚC khi bắt đầu (resume) — không tính vào tốc độ
        self.stage_t0 = self.t_start
        self.status = "running"
        self.estimate: Optional[Dict[str, Any]] = None
        self.worker_peak = 0.0
        self._last_write = 0.0
        self._wrote = 0

    def start_stage(self, stage: str, total: int, done: int = 0) -> None:
        self.stage, self.total, self.done, self.base_done = stage, int(total), int(done), int(done)
        self.stage_t0 = time.time()
        self.write(force=True)

    def tick(self, n: int = 1, worker_peak_mb: Optional[float] = None, resumed: bool = False) -> None:
        """n job vừa xong. resumed=True: lấy từ kho (không tính vào tốc độ)."""
        self.done += n
        if resumed:
            self.base_done += n
        if worker_peak_mb:
            self.worker_peak = max(self.worker_peak, float(worker_peak_mb))
        self.write()

    def set_estimate(self, est: Dict[str, Any]) -> None:
        self.estimate = est
        self.write(force=True)

    def snapshot(self) -> Dict[str, Any]:
        now = time.time()
        el = max(now - self.stage_t0, 1e-9)
        ran = self.done - self.base_done
        rate = ran / el if ran > 0 else 0.0
        remaining = max(self.total - self.done, 0)
        eta = remaining / rate if rate > 0 else None
        try:
            from backend.utils.memwatch import peak_rss_mb
            peak = round(peak_rss_mb(), 1)
        except Exception:
            peak = None
        return {"run_dir": self.run_dir, "stage": self.stage, "done": self.done, "total": self.total, "rate": round(rate, 4),
                "eta_s": round(eta, 1) if eta is not None else None, "elapsed_s": round(now - self.t_start, 1),
                "peak_rss_mb": peak, "worker_peak_rss_mb": round(self.worker_peak, 1) or None, "status": self.status,
                "updated": now, "estimate": self.estimate}

    def write(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_write < self.min_interval:
            return
        self._last_write = now
        snap = self.snapshot()
        for path in self.paths:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(snap, fh, ensure_ascii=False)
                os.replace(tmp, path)
                self._wrote += 1
            except OSError:
                pass

    def finish(self, status: str = "done") -> None:
        self.status = status
        self.write(force=True)


@contextlib.contextmanager
def graceful_sigterm(progress: Optional[Progress] = None) -> Iterator[None]:
    """SIGTERM/SIGINT -> SystemExit(143) ở luồng chính để finally flush kho; progress được đánh dấu cancelled/failed khi thoát bất thường."""
    def _handler(signum, frame):
        raise SystemExit(143)

    old: Dict[int, Any] = {}
    try:
        for sig in (signal.SIGTERM,):
            try:
                old[sig] = signal.signal(sig, _handler)
            except ValueError:   # không ở luồng chính (test) -> bỏ qua
                pass
        yield
    except SystemExit as exc:
        if progress is not None:
            progress.finish("cancelled" if exc.code == 143 else ("done" if not exc.code else "failed"))
        raise
    except BaseException:
        if progress is not None:
            progress.finish("failed")
        raise
    finally:
        for sig, h in old.items():
            try:
                signal.signal(sig, h)
            except ValueError:
                pass


# ─── Kết quả + tham số job ──────────────────────────────────────────────────
def write_job_result(result: Any) -> Optional[str]:
    job_dir = os.environ.get("NORA_JOB_DIR")
    if not job_dir:
        return None
    os.makedirs(job_dir, exist_ok=True)
    path = os.path.join(job_dir, "result.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, default=json_default)
    os.replace(tmp, path)  # ghi nguyên tử: API không bao giờ đọc file dở
    return path


def options(defaults: Dict[str, Any], params: Optional[Dict[str, Any]] = None) -> SimpleNamespace:
    """Tham số của một job: `defaults` ghi đè bởi `params`. Khoá lạ -> ValueError (không âm thầm bỏ qua lỗi gõ tên)."""
    params = dict(params or {})
    unknown = sorted(set(params) - set(defaults))
    if unknown:
        raise ValueError(f"tham số lạ: {unknown}; có: {sorted(defaults)}")
    return SimpleNamespace(**{**defaults, **params})


def as_list(value) -> list:
    """Danh sách từ tham số job: None/"" -> [], "a,b" -> ["a", "b"], list/tuple -> list."""
    if not value:
        return []
    if isinstance(value, str):
        return [x for x in value.split(",") if x]
    return list(value)
