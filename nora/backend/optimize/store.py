"""Kho kết quả append-only (SQLite, WAL) cho mỗi lần chạy tối ưu quy mô lớn: <run_dir>/results.sqlite.

Vì sao: tối ưu tới ~1.000.000 cấu hình không thể giữ mọi kết quả trong RAM của tiến trình cha (và không thể chạy lại từ đầu khi
bị kill). Mỗi kết quả của một job được ghi NGAY vào kho (idempotent theo job_key); tiến trình cha chỉ giữ top-K trong RAM; chạy lại
với --resume bỏ qua các job_key đã có -> kết quả cuối y hệt lần chạy không gián đoạn.

Bảng:
  results(job_key TEXT PRIMARY KEY, stage, candidate, ord INTEGER, params_json, metrics_json, score REAL, created REAL)
      ord = chỉ số cấu hình theo thứ tự sinh (để xếp hạng hoà điểm giống `sorted` ổn định); score = điểm xếp hạng (NULL = không đạt / -inf)
  meta(key TEXT PRIMARY KEY, value TEXT)
job_key = sha1(stage, candidate, params chuẩn hoá, cửa sổ, stop_fill, risk, sha256 dữ liệu, phiên bản mã) — đổi một trong các thành phần
này thì kết quả cũ KHÔNG bao giờ được dùng lại.

Ghi theo lô (commit mỗi COMMIT_EVERY lần put hoặc COMMIT_SECONDS giây); flush()/close() ghi nốt — CLI gọi trong finally + khi nhận SIGTERM.
Móc kiểm thử: env NORA_TEST_FAIL_AFTER_PUTS=N -> sau lần put thứ N (đã commit) ném RuntimeError để mô phỏng sập giữa chừng (chỉ dùng trong test).

Chạy một giai đoạn kiểu streaming (stream_stage):
Chạy một giai đoạn tối ưu theo kiểu STREAMING: job sinh lười -> pool (bounded) -> ghi ngay vào ResultsStore -> chỉ giữ top-K trong RAM.

stream_stage() là khung dùng chung cho build_strategy_book (giai đoạn A) và sàng lọc của optimize_alphas:
  - bỏ qua job đã có trong kho (job_key) -> `--resume` tiếp tục đúng chỗ dừng, kết quả cuối y hệt lần chạy không gián đoạn;
  - kết quả mỗi job được chuẩn hoá qua JSON (cùng cấu trúc dù lấy từ worker hay từ kho) trước khi đưa cho `handle`;
  - `handle(ord, params, metrics, from_store) -> (metrics_để_lưu, điểm)` quyết định lưu gì (vd. bỏ chuỗi `daily` của hàng không thuộc top-K).
"""
import hashlib
import heapq
import itertools
import json
import math
import os
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from backend.utils.jsonsafe import json_default
from backend.utils.parallel import pool_imap_bounded

DB_NAME = "results.sqlite"
COMMIT_EVERY = 200
COMMIT_SECONDS = 3.0
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS results(
    job_key TEXT PRIMARY KEY, stage TEXT NOT NULL, candidate TEXT NOT NULL, ord INTEGER,
    params_json TEXT NOT NULL, metrics_json TEXT NOT NULL, score REAL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS results_rank ON results(stage, candidate, score DESC, ord);
CREATE INDEX IF NOT EXISTS results_ord ON results(stage, candidate, ord);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""

_CODE_FILES = (   # mọi file ảnh hưởng kết quả backtest: đổi một file -> khoá job đổi -> --resume không dùng lại kết quả cũ
    "backend/core/backtest.py", "backend/core/models.py", "backend/core/params.py", "backend/core/position_size.py",   # P9.4: engine gộp
    "backend/core/execute/tracker.py",
    "backend/core/metrics/portfolio.py", "backend/core/metrics/returns.py", "backend/core/metrics/trades.py",
    "backend/core/data/shared.py", "backend/core/signals/evaluator.py", "backend/core/signals/kernels.py",
    "backend/core/strategy/book.py", "backend/core/strategy/library.py", "backend/wfa/walk_forward.py",
)
_CODE_VERSION: Optional[str] = None


def canonical(obj: Any) -> str:
    """JSON chuẩn hoá (khoá sắp xếp, không khoảng trắng) — dùng cho job_key."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=json_default, allow_nan=True)


def code_version() -> str:
    """Chuỗi phiên bản mã ảnh hưởng kết quả: sha1 nội dung các file engine/chiến lược (hoặc env NORA_CODE_VERSION). Tính một lần."""
    global _CODE_VERSION
    env = os.environ.get("NORA_CODE_VERSION")
    if env:
        return env
    if _CODE_VERSION is None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        h = hashlib.sha1(f"v{SCHEMA_VERSION}".encode())
        for rel in _CODE_FILES:
            try:
                with open(os.path.join(root, rel), "rb") as fh:
                    h.update(rel.encode() + b"\0" + fh.read())
            except OSError:
                h.update(rel.encode() + b"\0missing")
        _CODE_VERSION = h.hexdigest()[:16]
    return _CODE_VERSION


def data_fingerprint(symbols: Iterable[str]) -> List[Any]:
    """sha256 của 1m.pkl theo manifest từng tài sản (thiếu thì (start, end, số nến)) — thành phần của job_key."""
    from backend.db.local_pkl import read_manifest
    out = []
    for s in symbols:
        m = read_manifest(s) or {}
        out.append([s, m.get("sha256_1m") or [m.get("start_ts"), m.get("end_ts"), m.get("rows_1m") or m.get("total_rows")]])
    return out


def make_job_key(stage: str, candidate: str, params: Any, window: Any = None, stop_fill: Any = None, risk: Any = None,
                 data: Any = None, code: Optional[str] = None, extra: Any = None) -> str:
    payload = canonical([stage, candidate, params, window, stop_fill, risk, data, code or code_version(), extra])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=json_default, allow_nan=True)


class ResultsStore:
    """Kho kết quả của MỘT lần chạy (một file SQLite trong run_dir). An toàn đa luồng; nhiều tiến trình cùng ghi được (WAL + busy_timeout)."""

    def __init__(self, run_dir: str, name: str = DB_NAME, read_only: bool = False):
        self.path = run_dir if run_dir.endswith(".sqlite") else os.path.join(run_dir, name)
        if not read_only:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.read_only = read_only
        self._lock = threading.RLock()
        self._con = sqlite3.connect(self.path, timeout=60.0, check_same_thread=False, isolation_level=None)
        self._con.execute("PRAGMA busy_timeout=60000")
        if read_only:
            self._con.execute("PRAGMA query_only=1")
        else:
            self._con.execute("PRAGMA journal_mode=WAL")
            self._con.execute("PRAGMA synchronous=NORMAL")
            self._con.executescript(_SCHEMA)
        self._pending = 0
        self._in_tx = False
        self._last_commit = time.time()
        self._puts = 0
        self._fail_after = int(os.environ.get("NORA_TEST_FAIL_AFTER_PUTS") or 0)

    # ── ghi ────────────────────────────────────────────────────────────────
    def put(self, job_key: str, stage: str, candidate: str, params: Any, metrics: Any, ord: Optional[int] = None,
            score: Optional[float] = None) -> bool:
        """Ghi một kết quả; idempotent theo job_key (đã có -> không đổi, trả False)."""
        sc = None if score is None or (isinstance(score, float) and not math.isfinite(score)) else float(score)
        with self._lock:
            if not self._in_tx:
                self._con.execute("BEGIN")
                self._in_tx = True
            cur = self._con.execute(
                "INSERT OR IGNORE INTO results(job_key, stage, candidate, ord, params_json, metrics_json, score, created) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (job_key, stage, candidate, ord, _dumps(params), _dumps(metrics), sc, time.time()))
            inserted = cur.rowcount == 1
            self._pending += 1
            if self._pending >= COMMIT_EVERY or time.time() - self._last_commit >= COMMIT_SECONDS:
                self._commit()
            if inserted:
                self._puts += 1
                if self._fail_after and self._puts >= self._fail_after:
                    self._commit()
                    raise RuntimeError(f"[test] mô phỏng sập sau {self._puts} job (NORA_TEST_FAIL_AFTER_PUTS)")
            return inserted

    def _commit(self) -> None:
        if self._in_tx:
            self._con.execute("COMMIT")
            self._in_tx = False
        self._pending = 0
        self._last_commit = time.time()

    def flush(self) -> None:
        with self._lock:
            if not self.read_only:
                self._commit()

    def close(self) -> None:
        with self._lock:
            try:
                self.flush()
            finally:
                self._con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def set_meta(self, key: str, value: Any) -> None:
        with self._lock:   # autocommit; nếu đang trong giao dịch put thì commit cùng lô
            self._con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)", (key, _dumps(value)))

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    # ── đọc ────────────────────────────────────────────────────────────────
    @staticmethod
    def _row(r) -> Dict[str, Any]:
        return {"job_key": r[0], "stage": r[1], "candidate": r[2], "ord": r[3], "params": json.loads(r[4]),
                "metrics": json.loads(r[5]), "score": r[6]}

    _COLS = "job_key, stage, candidate, ord, params_json, metrics_json, score"

    def has(self, job_key: str) -> bool:
        with self._lock:
            return self._con.execute("SELECT 1 FROM results WHERE job_key=?", (job_key,)).fetchone() is not None

    def get(self, job_key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            r = self._con.execute(f"SELECT {self._COLS} FROM results WHERE job_key=?", (job_key,)).fetchone()
        return self._row(r) if r else None

    def count(self, stage: Optional[str] = None, candidate: Optional[str] = None) -> int:
        q, args = "SELECT COUNT(*) FROM results", []
        cond = []
        if stage is not None:
            cond.append("stage=?"); args.append(stage)
        if candidate is not None:
            cond.append("candidate=?"); args.append(candidate)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        with self._lock:
            return int(self._con.execute(q, args).fetchone()[0])

    def done_keys(self, stage: Optional[str] = None, candidate: Optional[str] = None) -> Iterator[str]:
        """Duyệt job_key đã xong (iterator — không nạp cả tập vào RAM)."""
        q, args = "SELECT job_key FROM results", []
        cond = []
        if stage is not None:
            cond.append("stage=?"); args.append(stage)
        if candidate is not None:
            cond.append("candidate=?"); args.append(candidate)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        con = self._con
        with self._lock:
            keys = con.execute(q, args)
            for (k,) in keys:
                yield k

    def iter_rows(self, stage: str, candidate: str) -> Iterator[Dict[str, Any]]:
        """Duyệt hàng theo ord (streaming, từng lô 500)."""
        with self._lock:
            cur = self._con.cursor()
            cur.execute(f"SELECT {self._COLS} FROM results WHERE stage=? AND candidate=? ORDER BY ord", (stage, candidate))
        while True:
            with self._lock:
                batch = cur.fetchmany(500)
            if not batch:
                break
            for r in batch:
                yield self._row(r)

    def top_k(self, stage: str, candidate: str, k: int, score_fn: Optional[Callable[[Dict[str, Any]], float]] = None) -> List[Dict[str, Any]]:
        """k hàng điểm cao nhất, xếp (-điểm, ord) — hoà điểm thì cấu hình sinh trước đứng trước (= `sorted` ổn định theo -điểm).
        score_fn(row) -> float (-inf = không đạt); mặc định dùng cột score (NULL = -inf). Duyệt streaming, RAM O(k)."""
        k = max(0, int(k))
        if score_fn is None:
            with self._lock:
                rs = self._con.execute(
                    f"SELECT {self._COLS} FROM results WHERE stage=? AND candidate=? "
                    f"ORDER BY score IS NULL, score DESC, ord LIMIT ?", (stage, candidate, k)).fetchall()
            return [self._row(r) for r in rs]

        def keyed():
            for row in self.iter_rows(stage, candidate):
                sc = score_fn(row)
                yield (-sc, row["ord"] if row["ord"] is not None else 0), row["job_key"], row
        best = heapq.nsmallest(k, keyed(), key=lambda t: t[0])
        return [t[2] for t in best]

    def page(self, stage: str, candidate: Optional[str] = None, offset: int = 0, limit: int = 100,
             sort: str = "order") -> List[Dict[str, Any]]:
        """Phân trang: sort="order" (thứ tự sinh) hoặc "score" (cao -> thấp, hoà theo ord)."""
        order = "ORDER BY score IS NULL, score DESC, ord" if sort == "score" else "ORDER BY ord"
        q, args = f"SELECT {self._COLS} FROM results WHERE stage=?", [stage]
        if candidate is not None:
            q += " AND candidate=?"
            args.append(candidate)
        q += f" {order} LIMIT ? OFFSET ?"
        args += [max(1, min(int(limit), 1000)), max(0, int(offset))]
        with self._lock:
            rs = self._con.execute(q, args).fetchall()
        return [self._row(r) for r in rs]

    def candidates(self, stage: str) -> List[str]:
        with self._lock:
            return [r[0] for r in self._con.execute("SELECT DISTINCT candidate FROM results WHERE stage=? ORDER BY candidate", (stage,))]


# ─── Chạy một giai đoạn kiểu streaming (stream_stage) ──────────────────────
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
