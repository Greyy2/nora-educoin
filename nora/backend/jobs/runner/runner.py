"""Hàng đợi / chạy / huỷ / khôi phục job nền (P9.6 + P9.8): tiện ích job (Progress, graceful_sigterm, ghi result.json — từ utils/jobs.py) và phần tiến trình của api/jobs/batch.py (KINDS, launch, status, huỷ, lưu kết quả lâu dài, dọn); `run_job_dir` là thân của api/jobs/runner.run.

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.6, P9.8). Phần kiểm tham số của batch.py ở routes/jobs.py.
KINDS có thêm khoá "label_vi" (nhãn tiếng Việt cho UI, meta.jobs.kinds) và khoá "func" (mặc định "run_job"): tên hàm job sau khi đổi tên run_<kind>.
"""
# Khối env chạy TRƯỚC mọi import numpy/backend (tiến trình con/worker kế thừa qua fork). Chỉ khi module chạy làm
# điểm vào job (`-m backend.jobs.runner <job_dir>`), để tiến trình API import module này không bị đặt env.
if __name__ == "__main__":
    import os
    for _e in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(_e, "1")
    os.environ.setdefault("NORA_CANDLE_CACHE_MB", "512")
    os.environ.setdefault("NORA_DATA_CACHE_MB", "1024")

import contextlib
import importlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple


# ══════════════════════════════════════════════════════════════════════════
# Tiện ích chung cho job nền (chạy qua jobs/runner.py): tham số, kết quả, tiến độ, huỷ an toàn.
#
# Tiến độ + huỷ an toàn cho job dài: <run_dir>/progress.json (ghi tối đa mỗi 5 giây) và xử lý SIGTERM.
#
# progress.json = {"run_dir", "stage", "done", "total", "rate" (job/giây của giai đoạn), "eta_s", "elapsed_s", "peak_rss_mb" (tiến trình cha),
#                  "worker_peak_rss_mb", "status": running|done|cancelled|failed, "updated", "estimate": {...}}
# Nếu env NORA_JOB_DIR có đặt (job của API) file được ghi thêm vào đó để API (backend/jobs/runner.py) hiển thị.
#
# SIGTERM (nút "Huỷ" của API gửi cho cả nhóm tiến trình): handler ném SystemExit(143) ở luồng chính -> các khối finally của job flush kho kết quả
# (ResultsStore.close) rồi ghi progress status="cancelled" -> chạy lại với --resume tiếp tục đúng chỗ dừng.
#
# Thêm: write_job_result (result.json của job API) và options (tham số job: mặc định + giá trị truyền vào, từ chối khoá lạ).
# ══════════════════════════════════════════════════════════════════════════

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
            from backend.jobs.worker import peak_rss_mb
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
                from backend.models.storage import write_json_atomic
                write_json_atomic(path, snap)
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


# ══════════════════════════════════════════════════════════════════════════
# Job nền nặng (backtest, WFA, dữ liệu...), chạy NGOÀI tiến trình API qua MỘT cửa: backend/jobs/runner.py.
#
# Vì sao: API có trần RAM riêng (3G) nên không được chạy việc nặng trong tiến trình. Mỗi job là một tiến trình con
# `ops/run_limited.sh -- -m backend.jobs.runner <job_dir>`: tự có scope riêng trong nora.slice (trần chung 12G), xếp hàng
# tuần tự (flock) và tự chia worker theo RAM còn trống. runner đọc job.json {kind, params} rồi gọi run_job(params) của module trong KINDS.
# API chỉ khởi chạy, theo dõi và đọc kết quả. UI, terminal (curl) và script đều đi qua cùng endpoint -> cùng job.
#
# Mỗi job có thư mục <data>/cache/process/<job_id>/ (kết quả lâu dài: backtest|wfa|carlo/<job_id>):
#   params.json đầu vào của runner {kind, params}
#   job.json    siêu dữ liệu (id, kind, params, pid, created/started/finished, state, exit_code)
#   out.log     stdout+stderr của job
#   result.json báo cáo cuối do script ghi (quy ước env NORA_JOB_DIR, xem backend/jobs/runner.py)
#   progress.json  (job tối ưu quy mô lớn) tiến độ do job ghi mỗi <= 5 giây: stage, done, total, rate, eta_s, peak_rss_mb (xem backend/jobs/runner.py)
# Trạng thái trả ra: queued (đang chờ hàng đợi run_limited) | running | done | failed | cancelled. Trạng thái bền (job.json) chỉ có running/done/failed/cancelled;
# queued suy ra từ out.log. Huỷ: cancel(job_id) gửi SIGTERM cho CẢ nhóm tiến trình (job flush kho kết quả rồi thoát -> chạy lại bằng resume). Không dùng shell.
# ══════════════════════════════════════════════════════════════════════════

from backend.models.models import NORA_DIR  # noqa: E402  (định nghĩa duy nhất ở models/models)
RUN_LIMITED = os.path.join(NORA_DIR, "ops", "run_limited.sh")

# Danh sách trắng: loại job -> (module có run_job(params), các khoá tham số được phép)
RUNNER = "backend.jobs.runner"
KINDS: Dict[str, Dict[str, Any]] = {
    "book_backtest": {"label_vi": "Backtest sổ", "module": "backend.jobs.tasks", "func": "run_book_backtest",
                      "params": {"book", "strategies", "symbols", "start", "end", "risk_per_trade", "stop_fill", "regime", "timeframe", "data", "latency_ms", "gas_usd"}},
    "book_wfa": {"label_vi": "WFA sổ", "module": "backend.jobs.tasks", "func": "run_book_wfa",
                 "params": {"report", "include_rejected", "candidates", "strategies", "symbols", "n", "start", "end", "train_days",
                            "test_days", "step_days", "sims", "mc_seed", "risk_per_trade", "workers", "resume", "max_configs", "force_large",
                            "timeframe", "regime"}},
    "presets_build": {"label_vi": "Dựng preset", "module": "backend.analys.alpha.strategies", "func": "run_presets_build", "params": set()},
    "data_update": {"label_vi": "Cập nhật dữ liệu OKX", "module": "backend.data.crawl", "func": "run_job", "params": {"symbols"}},
    "custom_backtest": {"label_vi": "Backtest tuỳ chỉnh", "module": "backend.jobs.tasks", "func": "run_custom_backtest",
                        "params": {"code", "symbols", "start", "end", "train_ratio", "initial_capital", "position", "run_frame"}},
    "education_warm": {"label_vi": "Làm nóng kết quả mẫu giáo dục", "module": "backend.jobs.tasks", "func": "education_warm", "params": {"keys"}},
    "live_bot": {"label_vi": "Bot Live / Paper / Testnet", "module": "backend.jobs.tasks", "func": "run_live_bot",
                 "params": {"bot_id", "mode", "source", "alpha_id", "code", "symbols", "capital", "base_frame", "confirm_live", "enter_on_start", "position", "resume", "signal_tf", "params", "book_source", "backtest_job_id", "debug_events"}},
    "alpha_research": {"label_vi": "Nghiên cứu Alpha (Prompt)", "module": "backend.jobs.tasks", "func": "run_alpha_research",
                       "params": {"prompt", "opts", "pick", "from_step", "edits", "job_id"}},
    "data_scan_crawl": {"label_vi": "Crawl nến 100 coin quét", "module": "backend.data.crawl", "func": "run_scan_crawl",
                        "params": {"coins", "start_ms", "end_ms", "workers", "resume"}},
    "universe_scan": {"label_vi": "Quét thị trường 100 coin", "module": "backend.jobs.tasks", "func": "run_universe_scan",
                      "params": {"alpha_id", "signal_tf", "book_source", "is_start", "is_end", "oos_start", "oos_end", "capital", "coins"}},
}
NO_LOCK_KINDS: set = {"live_bot"}   # bot live chạy dài hạn, không lock hàng đợi backtest

MAX_ACTIVE = 150        # số job đang chạy/chờ tối đa cùng lúc (hỗ trợ chạy > 50 bot song song)
# Giới hạn số bot live đang chạy đồng thời — sau khi tối ưu cache (128MB) và glibc arena (2), mỗi bot chỉ chiếm ~200-350MB RAM.
# Mặc định 16 bot an toàn (server 32GB, reserve 8GB → budget ~24GB → 16×350MB = ~5.6GB, cực kỳ an toàn).
# Override: NORA_LIVE_MAX_BOTS=<n> (0 = không giới hạn).
MAX_LIVE_BOTS: int = int(os.environ.get("NORA_LIVE_MAX_BOTS", "16") or "16")
# RAM env cho subprocess live_bot — nhỏ hơn backtest vì bot chạy dài hạn và chạy nhiều song song
_LIVE_BOT_ENV: Dict[str, str] = {
    "NORA_CANDLE_CACHE_MB": os.environ.get("NORA_LIVE_CANDLE_CACHE_MB", "128"),
    "NORA_DATA_CACHE_MB": os.environ.get("NORA_LIVE_DATA_CACHE_MB", "256"),
    "MALLOC_ARENA_MAX": "2",
    "PYTHONMALLOC": "malloc",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "RAYON_NUM_THREADS": "2",
    "ARROW_IO_THREADS": "2",
    "POLARS_MAX_THREADS": "2",
}
LOG_TAIL_LINES = 40
WAITING_MARK = "đang chờ job khác của Nora"   # dòng run_limited.sh in khi xếp hàng
_JOB_ID_RE = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{6}$")
_EXIT_RE = re.compile(r"\[run_limited\] peak RAM .*\| exit (\d+)")
_LOCK = threading.Lock()


class JobError(ValueError):
    """Đối số/loại job không hợp lệ (router đổi thành HTTP 422)."""


class InvalidJobIdError(JobError):
    """ID của job không đúng định dạng."""


class JobNotFoundError(JobError):
    """Không tìm thấy job theo ID."""


DEX_UNSUPPORTED = "DEX/AMM không được Nautilus hỗ trợ"


class NotReady(RuntimeError):
    """Tính năng chưa có trên engine Nautilus (DEX/AMM, tick swap, ...): API đổi thành HTTP 501 detail {"code": "NOT_READY", "message"}; trong job -> job lỗi có thông điệp."""
    code = "NOT_READY"


class JobBusy(RuntimeError):
    """Quá nhiều job đang chạy (router đổi thành HTTP 429)."""


# ─── Đường dẫn ──────────────────────────────────────────────────────────────
def jobs_root() -> str:
    """Job ĐANG chạy (và job lỗi còn giữ log): cache/process. Tạo thư mục nếu chưa có."""
    from backend.models.storage import cache_process_dir
    path = cache_process_dir()
    os.makedirs(path, exist_ok=True)
    return path


# Kết quả lâu dài của job đã xong (ADR-P9 §4): backtest|wfa|carlo/<id>. Cùng tệp như thư mục job (job.json, params.json, result.json, ...).
RESULT_KINDS = ("backtest", "wfa", "carlo")


def _persisted_dirs() -> List[str]:
    """Các gốc kết quả lâu dài đang tồn tại (qua helper, đã có fallback cũ->mới); 'education' (kết quả Education) không phải job nên bị loại ở _JOB_ID_RE."""
    from backend.models.storage import run_dir as _rd
    dirs = [_rd(k) for k in RESULT_KINDS]
    return [d for d in dirs if os.path.isdir(d)]


def job_dir(job_id: str) -> str:
    return _job_dir(job_id)


def _job_dir(job_id: str) -> str:
    """Thư mục của một job: bản kết quả lâu dài (nếu có) rồi tới thư mục đang chạy ở cache/process. Job chưa có ở đâu -> đường trong process
    (người gọi tự kiểm tra tồn tại / ghi mới)."""
    if not _JOB_ID_RE.match(job_id):
        raise InvalidJobIdError(f"job_id không hợp lệ: {job_id!r}")
    live = os.path.join(jobs_root(), job_id)
    if os.path.isdir(live):
        return live
    for base in _persisted_dirs():
        cand = os.path.join(base, job_id)
        if os.path.isdir(cand):
            return cand
    return live


# ─── Kiểm đối số ────────────────────────────────────────────────────────────


def _check_params(kind: str, params: Dict[str, Any]) -> None:
    if kind not in KINDS:
        raise JobError(f"loại job không có trong danh sách trắng: {kind!r}")
    if not isinstance(params, dict):
        raise JobError("params phải là dict")
    bad = sorted(set(params) - KINDS[kind]["params"])
    if bad:
        raise JobError(f"tham số không được phép cho {kind}: {bad}")
    try:
        json.dumps(params, allow_nan=False)   # phải ghi được ra params.json (không NaN/kiểu lạ)
    except (TypeError, ValueError) as e:
        raise JobError(f"params không ghi được JSON: {e}")


# ─── Lưu/đọc job.json ───────────────────────────────────────────────────────
def _read_json(path: str) -> Any:
    from backend.models.storage import read_json
    return read_json(path)


def _read_meta(job_dir: str) -> Optional[Dict[str, Any]]:
    return _read_json(os.path.join(job_dir, "job.json"))


def _write_meta(job_dir: str, meta: Dict[str, Any]) -> None:
    from backend.models.storage import write_json_atomic      # nạp lười: giữ module runner nhẹ
    write_json_atomic(os.path.join(job_dir, "job.json"), meta, indent=1)


def _finish(job_dir: str, exit_code: Optional[int]) -> Dict[str, Any]:
    """Ghi kết thúc một lần (waiter thread hoặc status() phát hiện): done nếu thoát 0 / có result.json khi không rõ mã thoát."""
    if not os.path.isdir(job_dir):   # job đã được lưu lâu dài (lifecycle) bởi waiter/status khác: trả bản ghi ở nơi mới
        moved = _job_dir(os.path.basename(job_dir.rstrip(os.sep)))
        return (_read_meta(moved) or {}) if moved != job_dir else {}
    with _LOCK:
        meta = _read_meta(job_dir) or {}
        if meta.get("state") in ("done", "failed"):
            return meta
        has_result = os.path.isfile(os.path.join(job_dir, "result.json"))
        if exit_code is None:  # tiến trình mất dấu (API khởi động lại): thử mã thoát ở dòng cuối run_limited, rồi tới result.json
            m = _EXIT_RE.findall(_tail_text(os.path.join(job_dir, "out.log"), 8192))
            exit_code = int(m[-1]) if m else (0 if has_result else None)
        state = "done" if exit_code == 0 else "failed"
        if meta.get("cancel_requested") and exit_code != 0 and not has_result:
            state = "cancelled"   # người dùng bấm Huỷ: SIGTERM -> CLI flush kho rồi thoát khác 0 (chạy lại bằng --resume)
        meta.update(state=state, exit_code=exit_code, finished=time.time())
        if exit_code is None and state != "cancelled":
            meta["error"] = "tiến trình kết thúc không rõ mã thoát và không có result.json"
        _write_meta(job_dir, meta)
    if meta.get("state") == "done":
        _persist_quietly(job_dir)   # ngoài _LOCK: sao chép có thể lâu; bước cuối của nó tự lấy _LOCK
    return meta


def _waiter(proc: "subprocess.Popen", job_dir: str) -> None:
    try:
        code = proc.wait()
    except Exception:
        code = None
    _finish(job_dir, code)


# ─── Khởi chạy ──────────────────────────────────────────────────────────────
def _active_count() -> int:
    n = 0
    root = jobs_root()
    for name in os.listdir(root):
        meta = _read_meta(os.path.join(root, name))
        if meta and meta.get("state") == "running" and _alive(meta.get("pid")):
            n += 1
    return n


def _count_running_live_bots() -> int:
    """Đếm số bot live đang thực sự chạy (pid còn sống + kind=live_bot)."""
    n = 0
    root = jobs_root()
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    for name in names:
        meta = _read_meta(os.path.join(root, name))
        if meta and meta.get("kind") == "live_bot" and meta.get("state") == "running" and _alive(meta.get("pid")):
            n += 1
    return n


def running_live_bot_info() -> Dict[str, Any]:
    """Thông tin resource bot live: running_bots, max_bots, pct, at_limit. Dùng cho endpoint /live/resource_status."""
    from backend.jobs.worker.resource import mem_available_mb
    running = _count_running_live_bots()
    max_bots = MAX_LIVE_BOTS
    avail = mem_available_mb()
    return {
        "running_bots": running,
        "max_bots": max_bots,
        "at_limit": max_bots > 0 and running >= max_bots,
        "slots_left": max(0, max_bots - running) if max_bots > 0 else None,
        "ram_available_mb": round(avail, 0),
    }


def _env() -> Dict[str, str]:
    env = dict(os.environ)
    # Khi API chạy từ user service, run_limited.sh cần bus của user session để gọi systemd-run --user.
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={env['XDG_RUNTIME_DIR']}/bus")
    env["PYTHONUNBUFFERED"] = "1"     # log của job hiện ngay trong out.log (không chờ đầy bộ đệm)
    return env


FAILED_LOG_KEEP_DAYS = 0        # người dùng chốt 2026-10-08: job LỖI xoá ở lượt dọn kế tiếp (job mới / API khởi động)
PAUSED_KEEP_DAYS = 7            # job đã HUỶ còn tiến độ chạy dở (progress.json, chạy tiếp bằng --resume) giữ 7 ngày; huỷ mà không có gì -> xoá như job lỗi


def _live_bot_status(meta: Dict[str, Any]) -> Optional[Tuple[str, bool]]:
    """Job live_bot -> (trạng thái của BOT, job này đã bị thay bằng job chạy lại?) hoặc None khi chưa có bot.json (bot đang dựng). Trạng thái do core/live.bot_status
    (bot.json + tiến trình + cờ người dùng dừng) — MỘT nguồn, cùng giá trị với GET /live/bots."""
    from backend.core import live as lv
    d = lv.find_bot_dir(str((meta.get("params") or {}).get("bot_id") or ""))
    bm = _read_json(os.path.join(d, "bot.json")) if d else None
    if not bm:
        return None
    return lv.bot_status(bm, d), bool(bm.get("job_id") and bm.get("job_id") != meta.get("id"))


def _prune_failed(kinds, days: float, now: Optional[float], paused_days: float = PAUSED_KEEP_DAYS) -> List[str]:
    """Xoá thư mục job LỖI/HUỶ trong cache/process (`kinds` None = mọi loại). Job lỗi và job huỷ không còn tiến độ: quá `days` ngày;
    job huỷ còn tiến độ chạy dở (progress.json -> chạy tiếp được): quá `paused_days` ngày (mtime job.json). Trả job_id đã xoá."""
    import shutil
    root, now, gone = jobs_root(), (time.time() if now is None else now), []
    for name in os.listdir(root):
        path = os.path.join(root, name)
        meta = _read_meta(path) if _JOB_ID_RE.match(name) else None
        if not meta or meta.get("state") not in ("failed", "cancelled"):
            continue
        kind = meta.get("kind")
        if kinds is not None and kind not in kinds:
            continue
        if kind == "live_bot":                           # job của bot chưa kết thúc (đang chạy lại...) giữ nguyên: Công việc phải hiện "resuming"
            lb = _live_bot_status(meta)
            if lb is not None and not lb[1] and lb[0] in ("starting", "running", "resuming", "stopping"):
                continue
        keep = paused_days if meta.get("state") == "cancelled" and os.path.isfile(os.path.join(path, "progress.json")) else days
        sig = _sig(os.path.join(path, "job.json"))
        if sig and now - sig[0] / 1e9 > keep * 86400:
            shutil.rmtree(path, ignore_errors=True)
            gone.append(name)
    return gone


def prune_failed_jobs(days: float = FAILED_LOG_KEEP_DAYS, now: Optional[float] = None) -> List[str]:
    """ADR §4.3: job LỖI xoá ngay ở lượt dọn; job HUỶ còn tiến độ chạy dở giữ PAUSED_KEEP_DAYS (7) ngày, huỷ không có gì xoá ngay; kèm thư mục mồ côi."""
    return _prune_failed(None, days, now) + prune_orphan_dirs(now=now)


ORPHAN_MIN_AGE = 600.0          # giây: thư mục không job.json chỉ bị xoá khi KHÔNG file nào đổi trong 10 phút (tránh đụng launch/run_sync đang dựng)


def prune_orphan_dirs(min_age: float = ORPHAN_MIN_AGE, now: Optional[float] = None) -> List[str]:
    """Xoá thư mục mồ côi trong cache/process: không job.json (không pid), không phải _mem/_staging, mọi file/thư mục đã im >= `min_age` giây.
    Vd. tiến trình bot bị huỷ ghi result.json SAU khi API đã xoá thư mục job, hoặc chỉ còn out.log. Trả tên đã xoá."""
    import shutil
    root, now, gone = jobs_root(), (time.time() if now is None else now), []
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if name in ("_mem", "_staging") or not os.path.isdir(path) or os.path.exists(os.path.join(path, "job.json")):
            continue
        try:
            newest = max([os.stat(path).st_mtime] + [os.stat(os.path.join(path, f)).st_mtime for f in os.listdir(path)])
        except OSError:
            continue
        if now - newest >= min_age:
            shutil.rmtree(path, ignore_errors=True)
            gone.append(name)
    return gone


# ─── Vòng đời kết quả (ADR-P9 §4 bước 2–3) ──────────────────────────────────
EPHEMERAL_KINDS = ("custom_backtest",)   # /alpha/create, /education: chạy TẠM, không lưu ra data/; kết quả xong nằm trong bộ nhớ API (LRU) tới khi API khởi động lại
EPHEMERAL_MAX = 64
_EPH: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
# Loại khác (presets_build, data_update): kết quả bền do chính job ghi
# -> xong là dọn thư mục process (không chép).
PERSIST_AREAS = {"book_backtest": ("run", "backtest"), "book_wfa": ("run", "wfa")}
PERSIST_FILES = ("job.json", "params.json", "result.json", "out.log", "progress.json")   # không chép checkpoint/_shared/staging


def persist_dest_base(kind: str) -> Optional[str]:
    """Thư mục kết quả lâu dài của một loại job; None nếu loại này không lưu (xem PERSIST_AREAS)."""
    from backend.models.storage import alpha_run_dir, run_dir
    area = PERSIST_AREAS.get(kind)
    if not area:
        return None
    return (run_dir if area[0] == "run" else alpha_run_dir)(area[1])


EPHEMERAL_IDS_FILE = "_ephemeral_ids"    # trong cache/process: id các job tạm đã xong (bền qua khởi động lại) -> phân biệt "đã hết hạn" với "chưa từng có"
EPHEMERAL_IDS_MAX = 2000


class EphemeralGone(Exception):
    """Job tạm (custom_backtest) đã xong nhưng kết quả không còn trong bộ nhớ API (bị đẩy khỏi LRU hoặc API đã khởi động lại). Route trả 410, code EPHEMERAL_GONE."""
    code = "EPHEMERAL_GONE"

    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__(f"Kết quả chạy thử {job_id} đã hết hạn (kết quả tạm chỉ giữ trong bộ nhớ API) — hãy chạy lại backtest rồi lưu.")


def _ephemeral_ids_path() -> str:
    return os.path.join(jobs_root(), EPHEMERAL_IDS_FILE)


def _note_ephemeral_id(job_id: str) -> None:
    path = _ephemeral_ids_path()
    try:
        ids = _read_ephemeral_ids()
        ids.append(job_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(ids[-EPHEMERAL_IDS_MAX:]) + "\n")
    except OSError:
        pass


def _read_ephemeral_ids() -> List[str]:
    try:
        with open(_ephemeral_ids_path(), encoding="utf-8") as fh:
            return [ln.strip() for ln in fh if ln.strip()]
    except OSError:
        return []


def ephemeral_gone(job_id: str) -> bool:
    """Id từng là job tạm đã xong nhưng không còn trong bộ nhớ (xem EphemeralGone). Id chưa từng có -> False (404)."""
    jid = str(job_id)
    if not _JOB_ID_RE.match(jid):
        return False
    with _LOCK:
        if jid in _EPH:
            return False
    return jid in _read_ephemeral_ids() and not os.path.isdir(os.path.join(jobs_root(), jid))


def _remember_ephemeral(job_dir: str) -> bool:
    """Job tạm đã xong: nạp job.json + result.json + đuôi log vào bộ nhớ (LRU) rồi xoá thư mục process. Không đọc được result -> giữ thư mục."""
    import shutil
    meta, res = _read_meta(job_dir) or {}, _read_json(os.path.join(job_dir, "result.json"))
    if not meta.get("id") or not isinstance(res, dict):
        return False
    tail = _tail_text(os.path.join(job_dir, "out.log"), 65536)
    snap = {**meta, "status": meta["state"], "waiting_in_queue": False, "progress": _read_progress(job_dir),
            "log_tail": [ln for ln in tail.splitlines() if ln.strip()][-LOG_TAIL_LINES:], "result": res}
    _note_ephemeral_id(meta["id"])
    with _LOCK:
        _EPH[meta["id"]] = snap
        _EPH.move_to_end(meta["id"])
        while len(_EPH) > EPHEMERAL_MAX:
            _EPH.popitem(last=False)
    shutil.rmtree(job_dir, ignore_errors=True)
    return True


def ephemeral_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Kết quả job tạm đã xong còn trong bộ nhớ API (None nếu không có / API đã khởi động lại)."""
    with _LOCK:
        snap = _EPH.get(str(job_id))
        if snap is not None:
            _EPH.move_to_end(str(job_id))
    return _clone(snap) if snap is not None else None


def _same_result(a: str, b: str) -> bool:
    """Hai thư mục job cùng một kết quả: job.json bên đích đã done và result.json cùng kích thước."""
    ma = _read_meta(b) or {}
    sa, sb = _sig(os.path.join(a, "result.json")), _sig(os.path.join(b, "result.json"))
    return ma.get("state") == "done" and (sa is None or (sb is not None and sa[1] == sb[1]))


def persist_job(job_dir: str, dry_run: bool = False) -> Dict[str, Any]:
    """Áp luật vòng đời cho MỘT job trong cache/process. Trả {id, kind, action, dest}: action ∈ persisted | cleaned | exists (đích đã khớp, chỉ dọn process) |
    skip (chưa xong/loại không lưu/không ở process) | would_* (dry_run). Nguyên tử: ghi vào thư mục tạm cạnh đích rồi rename; chỉ xoá thư mục process
    SAU khi đích đã đủ -> chết giữa chừng không mất kết quả, chạy lại là idempotent."""
    import shutil
    meta = _read_meta(job_dir) or {}
    jid, kind = meta.get("id") or os.path.basename(job_dir), meta.get("kind")
    out = {"id": jid, "kind": kind, "action": "skip", "dest": None}
    in_root = os.path.realpath(os.path.dirname(os.path.realpath(job_dir))) == os.path.realpath(jobs_root()) and bool(_JOB_ID_RE.match(str(jid)))
    if kind in EPHEMERAL_KINDS and meta.get("state") == "done" and in_root:
        if dry_run:
            out["action"] = "would_clean"
        elif _remember_ephemeral(job_dir):
            out["action"] = "cleaned"
        return out
    if (meta.get("state") != "done" or os.path.realpath(os.path.dirname(os.path.realpath(job_dir))) != os.path.realpath(jobs_root())
            or not _JOB_ID_RE.match(str(jid))):
        return out
    base = persist_dest_base(kind)
    if not base:
        out["action"] = "would_clean" if dry_run else "cleaned"
        if not dry_run:
            shutil.rmtree(job_dir, ignore_errors=True)
        return out
    dest = os.path.join(base, jid)
    out["dest"] = dest
    if not os.path.isfile(os.path.join(job_dir, "result.json")):
        return out   # job xong không có kết quả: giữ nguyên ở process
    if dry_run:
        out["action"] = "would_exists" if os.path.isdir(dest) and _same_result(job_dir, dest) else "would_persist"
        return out
    os.makedirs(base, exist_ok=True)
    if os.path.isdir(dest) and _same_result(job_dir, dest):
        out["action"] = "exists"
        shutil.rmtree(job_dir, ignore_errors=True)
        return out
    tmp = os.path.join(base, f".{jid}.tmp-{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        for name in PERSIST_FILES:
            if name != "job.json" and os.path.isfile(os.path.join(job_dir, name)):
                shutil.copy2(os.path.join(job_dir, name), os.path.join(tmp, name))
        if os.path.isdir(os.path.join(job_dir, "alphas")):
            shutil.copytree(os.path.join(job_dir, "alphas"), os.path.join(tmp, "alphas"))
        with _LOCK:   # job.json đọc LẠI sau khi chép (stamp_job có thể vừa ghi nhãn); giữ khoá tới khi đích có đủ
            meta = _read_meta(job_dir) or meta
            meta["persisted"] = {"at": time.time(), "from": job_dir}
            rp = None
            try:
                with open(os.path.join(tmp, "result.json"), encoding="utf-8") as fh:
                    res = json.load(fh)
                rp = res.get("report_path") or res.get("run_dir") if isinstance(res, dict) else None
            except (OSError, ValueError):
                pass
            if kind == "book_wfa" and rp:
                meta["report_dir"] = os.path.dirname(rp) if str(rp).endswith(".json") else rp   # báo cáo WFA sống ở wfa/<thời điểm>/, không chép
            _write_meta(tmp, meta)
            if os.path.isdir(dest):   # đích dở dang/khác: thay (nguồn còn nguyên tới lúc này)
                shutil.rmtree(dest)
            os.rename(tmp, dest)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    shutil.rmtree(job_dir, ignore_errors=True)
    out["action"] = "persisted"
    return out


def _persist_quietly(job_dir: str) -> None:
    """Gọi khi job vừa xong: lỗi lưu không làm hỏng job (kết quả vẫn ở process; persist_finished_jobs thử lại sau)."""
    try:
        persist_job(job_dir)
    except Exception as e:   # noqa: BLE001
        print(f"[jobs] không lưu được job {os.path.basename(job_dir)} sang thư mục kết quả: {e}", flush=True)


def persist_finished_jobs(apply: bool = False) -> List[Dict[str, Any]]:
    """MỘT LẦN (cho script chuyển cây): áp luật 2 cho mọi job ĐÃ XONG còn trong cache/process. Mặc định dry-run (chỉ báo). Trả danh sách persist_job()."""
    root, rows = jobs_root(), []
    for name in sorted(os.listdir(root)):
        if _JOB_ID_RE.match(name) and os.path.isdir(os.path.join(root, name)):
            r = persist_job(os.path.join(root, name), dry_run=not apply)
            if r["action"] != "skip":
                rows.append(r)
    return rows


def enforce_lifecycle() -> Dict[str, Any]:
    """Luật "cache chỉ chứa tiến trình chưa xong" — gọi khi API khởi động: job mất tiến trình được chốt trạng thái; job xong -> lưu về nhà bền rồi xoá thư mục process
    (job tạm custom_backtest cũ: xoá); job lỗi: xoá; job huỷ còn tiến độ chạy dở: giữ 7 ngày (PAUSED_KEEP_DAYS), huỷ không có gì: xoá; đang chạy giữ nguyên."""
    root, rows = jobs_root(), []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        meta = _read_meta(d) if _JOB_ID_RE.match(name) and os.path.isdir(d) else None
        if not meta:
            continue
        if meta.get("state") == "running" and not _alive(meta.get("pid")):
            _finish(d, None)
        if os.path.isdir(d):
            meta = _read_meta(d) or meta
            if meta.get("kind") in EPHEMERAL_KINDS and meta.get("state") == "done":
                import shutil
                shutil.rmtree(d, ignore_errors=True)      # API vừa khởi động: bộ nhớ tạm đã mất, thư mục cũ không còn ai cần
                rows.append({"id": name, "kind": meta.get("kind"), "action": "cleaned", "dest": None})
                continue
            r = persist_job(d)
            if r["action"] != "skip":
                rows.append(r)
    return {"jobs": rows, "pruned": prune_failed_jobs()}


def new_job_id() -> str:
    return f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def inject_ephemeral_result(job_id: str, kind: str, result: Dict[str, Any]) -> None:
    """Đưa kết quả backtest thật (đã chạy xong) vào bộ nhớ job tạm để store.save_user_alpha đọc."""
    snap = {"id": job_id, "kind": kind, "state": "done", "status": "done", "result": result, "progress": None, "log_tail": []}
    with _LOCK:
        _EPH[job_id] = snap


def launch(kind: str, params: Dict[str, Any]) -> str:
    """Khởi chạy job nền, trả job_id ngay (không chờ). params đã qua build_job / router."""
    params = dict(params)
    _check_params(kind, params)
    max_active = getattr(sys.modules.get("backend.jobs.runner"), "MAX_ACTIVE", MAX_ACTIVE)
    if _active_count() >= max_active:
        raise JobBusy(f"đang có >= {max_active} job chạy/chờ; thử lại sau")
    # Kiểm tra giới hạn bot live riêng (mỗi bot chiếm ~600-900MB RAM dài hạn)
    if kind == "live_bot":
        max_live = MAX_LIVE_BOTS
        if max_live > 0:
            running = _count_running_live_bots()
            if running >= max_live:
                raise JobBusy(
                    f"Đã đạt giới hạn {max_live} bot đang chạy đồng thời. "
                    "Dừng bớt bot cũ để giải phóng tài nguyên, hoặc đặt NORA_LIVE_MAX_BOTS để tăng giới hạn."
                )
    job_id = new_job_id()
    job_dir = os.path.join(jobs_root(), job_id)
    os.makedirs(job_dir)
    prune_failed_jobs()   # job lỗi/huỷ: xoá (cache chỉ giữ tiến trình đang chạy)
    with open(os.path.join(job_dir, "params.json"), "w", encoding="utf-8") as fh:   # đầu vào của runner (ghi TRƯỚC khi chạy)
        json.dump({"kind": kind, "params": params}, fh, ensure_ascii=False)
    env = dict(_env(), NORA_JOB_DIR=job_dir)
    # Bot live: dùng cache nhỏ hơn để tiết kiệm RAM khi chạy nhiều bot song song
    if kind == "live_bot":
        env.update(_LIVE_BOT_ENV)
    cmd = [RUN_LIMITED] + (["--no-lock", "--no-mem-log"] if kind in NO_LOCK_KINDS else []) + ["--", "-m", RUNNER, job_dir]
    log = open(os.path.join(job_dir, "out.log"), "ab")
    try:
        proc = subprocess.Popen(cmd, cwd=NORA_DIR, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        log.close()  # tiến trình con giữ bản riêng của fd
    with _LOCK:
        _write_meta(job_dir, {"id": job_id, "kind": kind, "params": params, "pid": proc.pid, "created": time.time(), "started": None,
                              "finished": None, "state": "running", "exit_code": None})
    threading.Thread(target=_waiter, args=(proc, job_dir), name=f"batch-job-{job_id}", daemon=True).start()
    return job_id


def run_sync(kind: str, params: Dict[str, Any], job_dir: str, timeout: float = 1800) -> None:
    """Chạy một job NGAY và chờ xong (không qua hàng đợi: run_limited --no-lock, vẫn trong nora.slice). Dùng cho việc ngắn mà API cần
    kết quả tại chỗ (vd. tính lại lệnh một alpha). Lỗi -> RuntimeError kèm đuôi log; quá thời gian -> TimeoutError."""
    _check_params(kind, params)
    os.makedirs(job_dir, exist_ok=True)
    with open(os.path.join(job_dir, "params.json"), "w", encoding="utf-8") as fh:
        json.dump({"kind": kind, "params": params}, fh, ensure_ascii=False)
    try:
        p = subprocess.run([RUN_LIMITED, "--no-lock", "--", "-m", RUNNER, job_dir], cwd=NORA_DIR, env=dict(_env(), NORA_JOB_DIR=job_dir),
                           capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"{kind}: quá {timeout:.0f} giây")
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "")[-400:])


# ─── Theo dõi ───────────────────────────────────────────────────────────────
def _alive(pid: Optional[int]) -> bool:
    from backend.models.storage import pid_alive      # định nghĩa duy nhất của "tiến trình còn sống"
    return pid_alive(pid)


def _tail_text(path: str, nbytes: int) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - nbytes))
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _summary(job_dir: str) -> Optional[Dict[str, Any]]:
    meta = _read_meta(job_dir)
    if not meta:
        return None
    if meta.get("state") == "running" and not _alive(meta.get("pid")):
        meta = _finish(job_dir, None)   # waiter không còn (API khởi động lại) hoặc đã ghi xong
        if meta.get("id") and not os.path.isdir(job_dir):
            job_dir = _job_dir(meta["id"])   # vừa được lưu sang thư mục kết quả lâu dài
    tail = _tail_text(os.path.join(job_dir, "out.log"), 65536)
    lines = [ln for ln in tail.splitlines() if ln.strip()]
    waiting = (meta.get("state") == "running" and bool(lines)
               and all(WAITING_MARK in ln for ln in lines))
    if meta.get("state") == "running" and not waiting and not meta.get("started"):
        with _LOCK:
            fresh = _read_meta(job_dir) or meta
            fresh["started"] = fresh.get("started") or time.time()
            _write_meta(job_dir, fresh)
            meta = fresh
    status = "queued" if waiting else meta["state"]
    superseded = False
    if meta.get("kind") == "live_bot":
        lb = _live_bot_status(meta)
        if lb is not None and not lb[1]:
            status = lb[0]                   # running | resuming | stopping | stopped | failed theo bot (không bao giờ "failed/done" khi bot vẫn chạy)
        superseded = bool(lb and lb[1])
    out = {**meta, "status": status, "waiting_in_queue": waiting, "superseded": superseded}
    out["progress"] = _read_progress(job_dir) if status in ("running", "done", "cancelled", "failed") else None
    out["_lines"] = lines
    return out


def _read_progress(job_dir: str) -> Optional[Dict[str, Any]]:
    """progress.json do CLI ghi (stage/done/total/rate/eta_s/peak_rss_mb); None nếu job không có/chưa ghi."""
    p = _read_json(os.path.join(job_dir, "progress.json"))
    return p if isinstance(p, dict) else None


def cancel(job_id: str) -> Optional[Dict[str, Any]]:
    """Huỷ job đang chạy/chờ: SIGTERM cho CẢ nhóm tiến trình (job chạy với start_new_session -> pgid = pid). CLI bắt SIGTERM, flush kho
    kết quả rồi thoát nên có thể chạy tiếp bằng --resume <run_dir>. Sau 20 giây nhóm còn sống thì SIGKILL. Trả trạng thái mới;
    None nếu không có job. Job đã kết thúc -> JobError."""
    job_dir = _job_dir(job_id)
    meta = _read_meta(job_dir)
    if meta is None:
        return None
    pid = meta.get("pid")
    if meta.get("state") != "running" or not _alive(pid):
        raise JobError(f"job không còn chạy (trạng thái {meta.get('state')})")
    if meta.get("kind") == "live_bot":      # người dùng huỷ job bot = dừng bot (giữ nguyên vị thế): đặt cờ `stop` close=False để supervisor KHÔNG chạy lại
        from backend.core import live as lv
        bid = str((meta.get("params") or {}).get("bot_id") or "")
        if lv.find_bot_dir(bid):
            lv.stop_bot(bid, close_positions=False)
    with _LOCK:
        fresh = _read_meta(job_dir) or meta
        fresh["cancel_requested"] = time.time()
        _write_meta(job_dir, fresh)
    try:
        os.killpg(int(pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        raise JobError(f"không gửi được SIGTERM cho nhóm tiến trình {pid}: {exc}")

    def _hard_kill():
        try:
            os.killpg(int(pid), 0)            # nhóm còn sống?
            os.killpg(int(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    timer = threading.Timer(20.0, _hard_kill)
    timer.daemon = True
    timer.start()
    return status(job_id)


def status(job_id: str) -> Optional[Dict[str, Any]]:
    """Trạng thái một job (làm mới theo pid/mã thoát) + 40 dòng log cuối + result.json khi đã xong. None nếu không có job."""
    job_dir = _job_dir(job_id)
    out = _summary(job_dir)
    if out is None:
        return ephemeral_status(job_id)
    job_dir = _job_dir(job_id)   # _summary có thể vừa kết thúc + lưu job sang thư mục lâu dài
    out["log_tail"] = out.pop("_lines")[-LOG_TAIL_LINES:]
    out["result"] = None
    if out["status"] == "done":
        try:
            with open(os.path.join(job_dir, "result.json"), encoding="utf-8") as fh:
                out["result"] = json.load(fh)
        except (OSError, ValueError):
            out["result"] = None
    return out


job_status = status


def status_etag(job_id: str, lite: bool = False) -> Optional[str]:
    """ETag của GET job khi job ĐÃ kết thúc (job.json state done/failed/cancelled): job_id + mtime_ns của result.json + job.json + cờ lite.
    None nếu job chưa kết thúc / không có (khi đó không đệm được). Chỉ stat, không đọc file lớn."""
    job_dir = _job_dir(job_id)
    meta = _read_meta(job_dir)
    if not meta and ephemeral_status(job_id):
        return f'"{job_id}-mem-{int(bool(lite))}"'
    if not meta or meta.get("state") not in TERMINAL_STATES:
        return None
    r, m = _sig(os.path.join(job_dir, "result.json")), _sig(os.path.join(job_dir, "job.json"))
    return f'"{job_id}-{r[0] if r else 0}-{r[1] if r else 0}-{m[0] if m else 0}-{int(bool(lite))}"'


def status_lite(s: Dict[str, Any]) -> Dict[str, Any]:
    """Bản nhẹ của status(): bỏ `result.trade_list` (UI phân trang lệnh qua /portfolio/trades). Không sửa bản gốc ở cấp trên."""
    res = s.get("result")
    if isinstance(res, dict) and "trade_list" in res:
        s = {**s, "result": {k: v for k, v in res.items() if k != "trade_list"}}
    return s


def _names(v: Any) -> str:
    return ", ".join(v) if isinstance(v, (list, tuple)) else str(v or "").replace(",", ", ")


def _book_rel() -> str:
    """Đường dẫn sổ hiện hành để hiển thị (sinh từ models/storage, không viết cứng): <gốc dữ liệu>/alpha/book.json."""
    from backend.models.storage import alpha_dir, alpha_file
    ad = alpha_dir()
    return "/".join([os.path.basename(os.path.dirname(ad)), os.path.basename(ad), os.path.basename(alpha_file("book"))])


def job_label(kind: str, params: Optional[Dict[str, Any]]) -> str:
    """Nhãn ngắn cho người đọc, vd "Backtest · breakout_4h_long, breakout_4h_short · BTC,SOL · 2025-03-01→2025-04-30"."""
    p = params if isinstance(params, dict) else {}
    syms = ",".join(str(x).split("@")[0].split(":")[-1] for x in p["symbols"]) if p.get("symbols") else "cả vũ trụ"
    rng = f"{p.get('start') or '…'}→{p.get('end') or '…'}"
    if kind == "book_backtest":
        ids = ", ".join(s["id"] for s in p["strategies"]) if p.get("strategies") else f"sổ {_book_rel()}"
        return f"Backtest{' tick' if p.get('data') == 'tick' else ''} · {ids} · {syms} · {rng}"
    if kind == "book_wfa":
        if p.get("candidates"):
            src = f"{_names(p['candidates'])} (n={p.get('n') or 3})"
        elif p.get("strategies"):
            src = ", ".join(f"{s['id']}×{len(s['configs'])}" for s in p["strategies"])
        else:
            src = f"báo cáo {os.path.basename(p.get('report') or '?')}"
        return f"WFA · {src} · {syms} · {rng}" if (p.get("start") or p.get("symbols")) else f"WFA · {src}"
    if kind == "presets_build":
        return "Dựng presets.json"
    if kind == "data_update":
        return f"Cập nhật dữ liệu OKX · {_names(p.get('symbols')) or 'cả rổ'} · perp"
    return kind


TERMINAL_STATES = ("done", "failed", "cancelled")
_SUMMARY_CACHE: "OrderedDict[str, Tuple[Tuple, Dict[str, Any]]]" = OrderedDict()   # job_dir -> (chữ ký file, tóm tắt job đã kết thúc)
_SUMMARY_CACHE_MAX = 1024
_SUMMARY_LOCK = threading.Lock()


def _sig(path: str) -> Optional[Tuple[int, int]]:
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _clone(v: Any) -> Any:
    """Sao chép dict/list lồng nhau (dữ liệu từ JSON) — nhanh hơn copy.deepcopy ~5 lần; người gọi list_jobs có thể sửa hàng trả ra."""
    if isinstance(v, dict):
        return {k: _clone(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clone(x) for x in v]
    return v


def _summary_cached(job_dir: str) -> Optional[Dict[str, Any]]:
    """Như _summary nhưng job đã kết thúc (done/failed/cancelled) thì đệm theo (job.json, progress.json) mtime+size: khỏi đọc đuôi out.log 64KB
    (với job kết thúc `waiting_in_queue` luôn False, `_lines` bị list_jobs bỏ) và parse lại JSON. Job còn chạy/queued: đi đường cũ."""
    key = (_sig(os.path.join(job_dir, "job.json")), _sig(os.path.join(job_dir, "progress.json")))
    with _SUMMARY_LOCK:
        hit = _SUMMARY_CACHE.get(job_dir)
        if hit is not None and key[0] is not None and hit[0] == key:
            _SUMMARY_CACHE.move_to_end(job_dir)
            return _clone(hit[1])
    s = _summary(job_dir)
    if s is not None and s.get("state") in TERMINAL_STATES and s.get("status") == s["state"] and s.get("kind") != "live_bot":   # live_bot: trạng thái đổi theo bot -> không đệm
        done = {k: v for k, v in s.items() if k != "_lines"}
        key = (_sig(os.path.join(job_dir, "job.json")), _sig(os.path.join(job_dir, "progress.json")))   # _summary có thể vừa ghi job.json (_finish)
        with _SUMMARY_LOCK:
            _SUMMARY_CACHE[job_dir] = (key, _clone(done))
            _SUMMARY_CACHE.move_to_end(job_dir)
            while len(_SUMMARY_CACHE) > _SUMMARY_CACHE_MAX:
                _SUMMARY_CACHE.popitem(last=False)
    return s


def _history_dirs() -> List[Tuple[str, str]]:
    """(job_id, thư mục) cho Lịch sử/danh sách job: kết quả lâu dài (backtest|wfa|carlo/<id>) + job trong cache/process.
    Job ĐÃ XONG trong cache/process KHÔNG phải lịch sử (ADR §4.5) — chỉ job đang chạy/chờ/lỗi/huỷ
    (nhìn tiến độ, đọc log); bản đã xong phải có ở thư mục kết quả."""
    out: Dict[str, str] = {}
    root = jobs_root()
    for n in os.listdir(root):
        if not _JOB_ID_RE.match(n):
            continue
        d = os.path.join(root, n)
        m = _read_meta(d) or {}
        if m.get("state") == "done" and m.get("kind") != "live_bot":      # job live_bot đã dừng vẫn hiện (trạng thái "stopped") tới khi xoá bot
            continue
        out[n] = d
    for base in _persisted_dirs():
        for n in os.listdir(base):
            if _JOB_ID_RE.match(n) and n not in out and os.path.isdir(os.path.join(base, n)):
                out[n] = os.path.join(base, n)
    return sorted(out.items(), reverse=True)


def list_jobs(limit: int = 20, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """Job mới nhất trước (không kèm log/result), có `label`. `kind` lọc theo loại job (lọc TRƯỚC khi cắt limit)."""
    limit = max(1, min(int(limit), 100))
    if kind is not None and kind not in KINDS:
        raise JobError(f"loại job không có trong danh sách trắng: {kind!r}")
    rows = []
    for n, d in _history_dirs():
        s = _summary_cached(d)
        if not s or (kind and s.get("kind") != kind):
            continue
        s.pop("_lines", None)
        if s.get("superseded"):
            continue
        s["label"] = job_label(s.get("kind"), s.get("params"))
        rows.append(s)
        if len(rows) >= limit:
            break
    return rows


# ══════════════════════════════════════════════════════════════════════════
# Thân chạy một job (trước đây api/jobs/runner.run; điểm vào `python -m backend.jobs.runner <job_dir>` ở cuối file; khối env OMP/NORA_*_CACHE_MB
# ở đầu file, chỉ đặt khi chạy làm __main__). Tra KINDS[kind]["module"] + ["func"] (mặc định "run_job").
# ══════════════════════════════════════════════════════════════════════════
def run_job_dir(job_dir: str):
    with open(os.path.join(job_dir, "params.json"), encoding="utf-8") as fh:
        spec = json.load(fh)
    kind = spec["kind"]
    if kind not in KINDS:
        raise SystemExit(f"loại job không có trong danh sách trắng: {kind!r}")
    os.environ["NORA_JOB_DIR"] = job_dir
    entry = KINDS[kind]
    jid = os.path.basename(job_dir.rstrip("/"))
    print(f"[terminal] $ ops/run_limited.sh -- -m backend.jobs.runner {jid}", flush=True)
    print(f"[runner] Bắt đầu tiến trình job '{kind}' (PID {os.getpid()})", flush=True)
    try:
        res = getattr(importlib.import_module(entry["module"]), entry.get("func", "run_job"))(spec.get("params") or {})
        print(f"[runner] Hoàn tất job '{kind}' thành công.", flush=True)
        return res
    except Exception as e:
        print(f"[error] Tiến trình {kind} thất bại: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":     # P9.10a — từ api/jobs/runner.py (đã xoá)
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("dùng: python -m backend.jobs.runner <job_dir>")
    run_job_dir(sys.argv[1])
