"""Kho kết quả (P9.6): kho một lần chạy phễu (RunStore: SQLite + parquet) + kho kết quả dùng chung dựng sổ/WFA/phễu (ResultsStore, job_key, code_version).

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.6, P9.8).
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
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

from backend.optimize.process.workers import pool_imap_bounded
from backend.models.storage import json_default, read_json
from backend.metrics.trades import num_or_none


# ══════════════════════════════════════════════════════════════════════════
# Kho một lượt phễu: data/cache/process/funnel/<run_id>/ (xem docs/funnel_contract.md §2).
#
#   run.json              cấu hình + trạng thái từng tầng (ghi nguyên tử)
#   results.sqlite (WAL)  alphas / stage_metrics (theo hợp đồng) + parts / alpha_files / kv (phụ trợ, thêm cột phẳng để phân trang/thống kê nhanh)
#   trades/<stage>/part-*.parquet   danh sách lệnh (cột theo hợp đồng; thời gian = epoch ms int64)
#   daily/<stage>/part-*.parquet    chuỗi lợi suất ngày: 1 hàng = (alpha_id, stage, fold, start_date, rets[list<double>])
#   mc/<alpha_id>.json              Monte Carlo + tìm s
#
# RESUME AN TOÀN: SQLite là sổ cam kết. Mỗi lô: (1) ghi file parquet nguyên tử (tmp -> rename) (2) MỘT giao dịch SQLite ghi stage_metrics + cập nhật alphas
# + đăng ký file vào `parts`/`alpha_files`. Sập giữa (1) và (2) -> file mồ côi (không có trong `parts`); khi mở lại, `recover()` xoá chúng và các alpha của lô đó
# chưa có stage_metrics nên được chạy lại. Chỉ tiến trình cha ghi (worker chỉ tính) nên không có tranh chấp ghi.
# Móc kiểm thử: env NORA_TEST_FUNNEL_FAIL_AFTER_COMMITS=N -> ném RuntimeError sau lần commit lô thứ N (đã commit) để mô phỏng sập.
# ══════════════════════════════════════════════════════════════════════════

DB_NAME = "results.sqlite"

_RUN_SCHEMA = """
CREATE TABLE IF NOT EXISTS alphas(
    alpha_id TEXT PRIMARY KEY, strategy TEXT NOT NULL, params_json TEXT NOT NULL, ord INTEGER NOT NULL,
    stage_reached TEXT NOT NULL, stage_idx INTEGER NOT NULL, rejected_stage TEXT, rejected_idx INTEGER,
    reject_code TEXT, reject_msg TEXT, final_scale REAL);
CREATE INDEX IF NOT EXISTS alphas_pending ON alphas(stage_idx, rejected_idx, strategy, ord);
CREATE INDEX IF NOT EXISTS alphas_strategy ON alphas(strategy, stage_idx);
CREATE TABLE IF NOT EXISTS stage_metrics(
    alpha_id TEXT NOT NULL, stage TEXT NOT NULL, metrics_json TEXT NOT NULL, passed INTEGER,
    ret_pct REAL, mdd_pct REAL, sharpe REAL, trades REAL, win_rate REAL, profit_factor REAL, score REAL,
    PRIMARY KEY(alpha_id, stage));
CREATE INDEX IF NOT EXISTS sm_stage ON stage_metrics(stage, passed, score);
CREATE TABLE IF NOT EXISTS parts(kind TEXT NOT NULL, stage TEXT NOT NULL, file TEXT NOT NULL, n_rows INTEGER, PRIMARY KEY(kind, stage, file));
CREATE TABLE IF NOT EXISTS alpha_files(alpha_id TEXT NOT NULL, kind TEXT NOT NULL, stage TEXT NOT NULL, file TEXT NOT NULL,
    PRIMARY KEY(alpha_id, kind, stage, file));
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
"""

TRADE_COLS = ["alpha_id", "stage", "fold", "symbol", "side", "enter_time", "close_time", "enter_price", "close_price", "qty",
              "pnl_usd", "pnl_pct", "fees_usd", "funding_usd", "status", "layers", "mae_pct", "strategy", "margin_usd", "leverage", "entry_equity"]
TRADE_SCHEMA = pa.schema([
    ("alpha_id", pa.string()), ("stage", pa.string()), ("fold", pa.int32()), ("symbol", pa.string()), ("side", pa.string()),
    ("enter_time", pa.int64()), ("close_time", pa.int64()), ("enter_price", pa.float64()), ("close_price", pa.float64()),
    ("qty", pa.float64()), ("pnl_usd", pa.float64()), ("pnl_pct", pa.float64()), ("fees_usd", pa.float64()),
    ("funding_usd", pa.float64()), ("status", pa.string()), ("layers", pa.int32()), ("mae_pct", pa.float64()),
    ("strategy", pa.string()), ("margin_usd", pa.float64()), ("leverage", pa.float64()), ("entry_equity", pa.float64())])   # file cũ thiếu 4 cột cuối: đọc vẫn được
DAILY_SCHEMA = pa.schema([("alpha_id", pa.string()), ("stage", pa.string()), ("fold", pa.int32()), ("start_date", pa.string()),
                          ("rets", pa.list_(pa.float64()))])
FLAT_KEYS = ("ret_pct", "mdd_pct", "sharpe", "trades", "win_rate", "profit_factor")


@dataclass
class StageResult:
    """Kết quả của MỘT alpha ở MỘT tầng (đã quyết định qua/loại)."""
    alpha_id: str
    stage: str
    metrics: Dict[str, Any]
    passed: bool
    code: Optional[str] = None
    msg: Optional[str] = None
    trades: List[Tuple[str, List[Dict[str, Any]]]] = field(default_factory=list)   # [(giá trị cột `stage`, hàng lệnh có/không khoá fold)]
    daily: List[Tuple[str, List[Dict[str, Any]]]] = field(default_factory=list)    # [(giá trị cột `stage`, [{fold, start, rets}])]
    final_scale: Optional[float] = None


def _idx_span(prev_idx: int) -> Tuple[int, int]:
    """[prev_idx, số hiệu tầng kế): số hiệu tầng có khe (S2 đã gộp) nên đầu vào của S3 gồm cả stage_idx 2 của lượt cũ."""
    from backend.optimize.funnel import stages as gates
    nxt = min((i for i in gates.STAGE_IDX.values() if i > prev_idx), default=prev_idx + 1)
    return prev_idx, nxt


def _run_dumps(o: Any) -> str:
    return json.dumps(o, default=json_default, allow_nan=False, ensure_ascii=False)


def _clean(o: Any) -> Any:
    """Thay NaN/inf bằng None (JSON hợp lệ cho trình duyệt)."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def flat_columns(m: Dict[str, Any]) -> Dict[str, Optional[float]]:
    out = {k: num_or_none(m.get(k), None) for k in FLAT_KEYS}
    r, d = out["ret_pct"], out["mdd_pct"]
    out["score"] = (r / max(d, 1.0)) if r is not None and d is not None else None
    return out


def atomic_write_json(path: str, obj: Any, *, indent: Optional[int] = None, clean: bool = True, allow_nan: bool = False) -> None:
    """MỘT bộ ghi JSON nguyên tử (file tạm cạnh đích + os.replace: người đọc không bao giờ thấy file dở). `clean` thay NaN/inf bằng null
    trước khi ghi; `allow_nan` cho phép token NaN/Infinity (chỉ khi clean=False và nơi đọc chấp nhận); `indent` tuỳ chọn."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(_clean(obj) if clean else obj, fh, ensure_ascii=False, indent=indent, allow_nan=allow_nan, default=json_default)
    os.replace(tmp, path)


class RunStore:
    """Kho của MỘT lượt chạy. Mở lại cùng thư mục = resume."""

    def __init__(self, run_dir: str, read_only: bool = False):
        self.run_dir = os.path.abspath(run_dir)
        self.db_path = os.path.join(self.run_dir, DB_NAME)
        self.read_only = read_only
        self._lock = threading.RLock()
        if read_only:
            self._con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=60.0, check_same_thread=False, isolation_level=None)
            self._con.execute("PRAGMA query_only=1")
        else:
            os.makedirs(self.run_dir, exist_ok=True)
            self._con = sqlite3.connect(self.db_path, timeout=60.0, check_same_thread=False, isolation_level=None)
            self._con.execute("PRAGMA journal_mode=WAL")
            self._con.execute("PRAGMA synchronous=NORMAL")
            self._con.executescript(_RUN_SCHEMA)
        self._con.execute("PRAGMA busy_timeout=60000")
        self._commits = 0
        self._fail_after = int(os.environ.get("NORA_TEST_FUNNEL_FAIL_AFTER_COMMITS") or 0)
        if not read_only:
            self.recover()

    # ── đường dẫn ──────────────────────────────────────────────────────────
    def part_dir(self, kind: str, stage: str) -> str:
        return os.path.join(self.run_dir, kind, stage)

    def mc_path(self, alpha_id: str) -> str:
        return os.path.join(self.run_dir, "mc", f"{alpha_id}.json")

    @property
    def run_json_path(self) -> str:
        return os.path.join(self.run_dir, "run.json")

    def close(self) -> None:
        with self._lock:
            self._con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── run.json / kv ──────────────────────────────────────────────────────
    def read_run(self) -> Dict[str, Any]:
        return read_json(self.run_json_path, {})

    def update_run(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            run = self.read_run()
            for k, v in patch.items():
                if isinstance(v, dict) and isinstance(run.get(k), dict):
                    run[k] = {**run[k], **v}
                else:
                    run[k] = v
            atomic_write_json(self.run_json_path, run)
            return run

    def set_kv(self, key: str, value: Any) -> None:
        with self._lock:
            self._con.execute("INSERT OR REPLACE INTO kv(key, value) VALUES (?,?)", (key, _run_dumps(value)))

    def get_kv(self, key: str, default: Any = None) -> Any:
        with self._lock:
            r = self._con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else default

    # ── resume: dọn file mồ côi ────────────────────────────────────────────
    def recover(self) -> int:
        """Xoá file parquet không có trong `parts` (lô chưa commit) và file .tmp dở. -> số file đã xoá."""
        with self._lock:
            known = {(k, s, f) for k, s, f in self._con.execute("SELECT kind, stage, file FROM parts")}
        removed = 0
        for kind in ("trades", "daily"):
            root = os.path.join(self.run_dir, kind)
            if not os.path.isdir(root):
                continue
            for stage in os.listdir(root):
                d = os.path.join(root, stage)
                for fn in os.listdir(d) if os.path.isdir(d) else []:
                    if (kind, stage, fn) not in known:
                        try:
                            os.remove(os.path.join(d, fn))
                            removed += 1
                        except OSError:
                            pass
        mc = os.path.join(self.run_dir, "mc")
        for fn in os.listdir(mc) if os.path.isdir(mc) else []:
            if ".tmp" in fn:
                try:
                    os.remove(os.path.join(mc, fn))
                except OSError:
                    pass
        return removed

    # ── S0: ghi alpha ──────────────────────────────────────────────────────
    def add_alphas(self, rows: Sequence[Dict[str, Any]]) -> int:
        """rows: {alpha_id, strategy, params, ord, rejected_code?, rejected_msg?}. INSERT OR IGNORE (idempotent). -> số hàng mới."""
        from backend.optimize.funnel import stages as gates
        with self._lock:
            self._con.execute("BEGIN")
            n0 = self._con.execute("SELECT COUNT(*) FROM alphas").fetchone()[0]
            self._con.executemany(
                "INSERT OR IGNORE INTO alphas(alpha_id, strategy, params_json, ord, stage_reached, stage_idx, rejected_stage, rejected_idx, "
                "reject_code, reject_msg) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(r["alpha_id"], r["strategy"], _run_dumps(r["params"]), r["ord"], gates.STAGES[0], 0,
                  gates.STAGES[0] if r.get("reject_code") else None, 0 if r.get("reject_code") else None,
                  r.get("reject_code"), r.get("reject_msg")) for r in rows])
            n1 = self._con.execute("SELECT COUNT(*) FROM alphas").fetchone()[0]
            self._con.execute("COMMIT")
        return int(n1 - n0)

    # ── commit một lô kết quả của một tầng ─────────────────────────────────
    def _write_part(self, kind: str, stage: str, rows: List[Dict[str, Any]], schema: pa.Schema) -> Tuple[str, int]:
        d = self.part_dir(kind, stage)
        os.makedirs(d, exist_ok=True)
        with self._lock:
            n = self._con.execute("SELECT COUNT(*) FROM parts WHERE kind=? AND stage=?", (kind, stage)).fetchone()[0]
        fn = f"part-{n:06d}.parquet"
        cols = {name: [r.get(name) for r in rows] for name in schema.names}
        table = pa.Table.from_pydict(cols, schema=schema)
        tmp = os.path.join(d, fn + ".tmp")
        pq.write_table(table, tmp, compression="zstd")
        os.replace(tmp, os.path.join(d, fn))
        return fn, len(rows)

    def commit_results(self, results: List[StageResult], neighbours: bool = False) -> None:
        """Ghi một lô: parquet (lệnh + ngày) rồi MỘT giao dịch SQLite. neighbours=True: chỉ stage_metrics (điểm lân cận, không đụng bảng alphas)."""
        from backend.optimize.funnel import stages as gates
        if not results:
            return
        results = sorted(results, key=lambda r: (r.stage, r.alpha_id))
        t_groups: Dict[str, List[Dict[str, Any]]] = {}
        d_groups: Dict[str, List[Dict[str, Any]]] = {}
        who: Dict[Tuple[str, str], set] = {}
        for r in results:
            for stage_col, rows in r.trades:
                for t in rows:
                    t_groups.setdefault(r.stage, []).append({**t, "alpha_id": r.alpha_id, "stage": stage_col, "fold": t.get("fold")})
                if rows:
                    who.setdefault(("trades", r.stage), set()).add(r.alpha_id)
            for stage_col, rows in r.daily:
                for d in rows:
                    d_groups.setdefault(r.stage, []).append({"alpha_id": r.alpha_id, "stage": stage_col, "fold": d.get("fold"),
                                                             "start_date": d.get("start"), "rets": [float(x) for x in d["rets"]]})
                if rows:
                    who.setdefault(("daily", r.stage), set()).add(r.alpha_id)
        files: List[Tuple[str, str, str, int]] = []
        for stage, rows in t_groups.items():
            fn, n = self._write_part("trades", stage, rows, TRADE_SCHEMA)
            files.append(("trades", stage, fn, n))
        for stage, rows in d_groups.items():
            fn, n = self._write_part("daily", stage, rows, DAILY_SCHEMA)
            files.append(("daily", stage, fn, n))
        with self._lock:
            self._con.execute("BEGIN")
            try:
                for kind, stage, fn, n in files:
                    self._con.execute("INSERT OR REPLACE INTO parts(kind, stage, file, n_rows) VALUES (?,?,?,?)", (kind, stage, fn, n))
                    self._con.executemany("INSERT OR IGNORE INTO alpha_files(alpha_id, kind, stage, file) VALUES (?,?,?,?)",
                                          [(a, kind, stage, fn) for a in sorted(who.get((kind, stage), ()))])
                for r in results:
                    m = _clean(r.metrics)
                    fc = flat_columns(m)
                    self._con.execute(
                        "INSERT OR REPLACE INTO stage_metrics(alpha_id, stage, metrics_json, passed, ret_pct, mdd_pct, sharpe, trades, win_rate, "
                        "profit_factor, score) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (r.alpha_id, r.stage, _run_dumps(m), None if neighbours else int(r.passed), fc["ret_pct"], fc["mdd_pct"], fc["sharpe"],
                         fc["trades"], fc["win_rate"], fc["profit_factor"], fc["score"]))
                    if neighbours:
                        continue
                    idx = gates.STAGE_IDX[r.stage]
                    if r.passed:
                        self._con.execute("UPDATE alphas SET stage_reached=?, stage_idx=?, final_scale=COALESCE(?, final_scale) WHERE alpha_id=?",
                                          (r.stage, idx, r.final_scale, r.alpha_id))
                    else:
                        self._con.execute("UPDATE alphas SET stage_reached=?, stage_idx=?, rejected_stage=?, rejected_idx=?, reject_code=?, "
                                          "reject_msg=? WHERE alpha_id=?", (r.stage, idx, r.stage, idx, r.code, r.msg, r.alpha_id))
                self._con.execute("COMMIT")
            except BaseException:
                if self._con.in_transaction:   # SIGTERM có thể tới ngay SAU khi COMMIT xong -> không còn giao dịch để huỷ
                    self._con.execute("ROLLBACK")
                raise
        self._commits += 1
        if self._fail_after and self._commits >= self._fail_after:
            raise RuntimeError(f"[test] mô phỏng sập sau {self._commits} lô (NORA_TEST_FUNNEL_FAIL_AFTER_COMMITS)")

    # ── đọc: alpha / số đếm ────────────────────────────────────────────────
    def count_alphas(self) -> int:
        with self._lock:
            return int(self._con.execute("SELECT COUNT(*) FROM alphas").fetchone()[0])

    def pending(self, prev_idx: int, strategy: Optional[str] = None, after_ord: int = -1, limit: int = 1000) -> List[Dict[str, Any]]:
        """Alpha đã qua tầng prev_idx và chưa được chấm ở tầng kế (stage_idx trong [prev_idx, số hiệu tầng kế), chưa bị loại), theo ord tăng dần,
        ord > after_ord. (Lượt cũ: alpha đã qua tầng S2_antiluck cũ có stage_idx 2 và vẫn là đầu vào hợp lệ của S3.)"""
        lo, hi = _idx_span(prev_idx)
        q = "SELECT alpha_id, strategy, params_json, ord FROM alphas WHERE stage_idx>=? AND stage_idx<? AND rejected_idx IS NULL AND ord>?"
        args: List[Any] = [lo, hi, after_ord]
        if strategy is not None:
            q += " AND strategy=?"
            args.append(strategy)
        q += " ORDER BY ord LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self._con.execute(q, args).fetchall()
        return [{"alpha_id": a, "strategy": s, "params": json.loads(p), "ord": o} for a, s, p, o in rows]

    def count_pending(self, prev_idx: int, strategy: Optional[str] = None) -> int:
        lo, hi = _idx_span(prev_idx)
        q, args = "SELECT COUNT(*) FROM alphas WHERE stage_idx>=? AND stage_idx<? AND rejected_idx IS NULL", [lo, hi]
        if strategy is not None:
            q += " AND strategy=?"
            args.append(strategy)
        with self._lock:
            return int(self._con.execute(q, args).fetchone()[0])

    def strategies_at(self, stage_idx: int) -> List[str]:
        with self._lock:
            return [r[0] for r in self._con.execute(
                "SELECT DISTINCT strategy FROM alphas WHERE stage_idx>=? AND stage_idx<? AND rejected_idx IS NULL ORDER BY strategy", _idx_span(stage_idx))]

    def has_legacy_stage(self) -> bool:
        """Lượt chạy trước 08/10/2026 có khối tầng S2_antiluck (đã gộp vào S3/S4): đọc/hiển thị được, không ghi lại."""
        from backend.optimize.funnel import stages as gates
        with self._lock:
            return self._con.execute("SELECT 1 FROM stage_metrics WHERE stage=? LIMIT 1", (gates.LEGACY_STAGE,)).fetchone() is not None

    def stage_counts(self) -> List[Dict[str, Any]]:
        """[{stage, input (đủ điều kiện = đã qua tầng trước), done (đã chấm), passed, rejected}] cho mọi tầng (kèm S2_antiluck nếu là lượt cũ)."""
        from backend.optimize.funnel import stages as gates
        with self._lock:
            grp = self._con.execute("SELECT stage_idx, rejected_idx, COUNT(*) FROM alphas GROUP BY stage_idx, rejected_idx").fetchall()
        order = sorted(gates.ALL_STAGE_IDX if self.has_legacy_stage() else gates.STAGE_IDX, key=lambda st: gates.ALL_STAGE_IDX[st])
        out, prev_passed, first = [], None, None
        for stage in order:
            k = gates.ALL_STAGE_IDX[stage]
            done = sum(n for sidx, _, n in grp if sidx >= k)        # số alpha có stage_idx >= k
            rejected = sum(n for _, ridx, n in grp if ridx == k)
            passed = done - rejected
            first = done if first is None else first
            out.append({"stage": stage, "input": int(first if prev_passed is None else prev_passed), "done": int(done), "passed": int(passed),
                        "rejected": int(rejected)})
            prev_passed = passed
        return out

    def top_rejects(self) -> Dict[str, Dict[str, Any]]:
        """{stage: {code, count}} lý do loại phổ biến nhất của mỗi tầng (một truy vấn GROUP BY)."""
        with self._lock:
            rows = self._con.execute("SELECT rejected_stage, reject_code, COUNT(*) FROM alphas WHERE rejected_stage IS NOT NULL "
                                     "GROUP BY rejected_stage, reject_code").fetchall()
        best: Dict[str, Dict[str, Any]] = {}
        for stage, code, n in rows:
            if stage not in best or n > best[stage]["count"] or (n == best[stage]["count"] and str(code) < str(best[stage]["code"])):
                best[stage] = {"code": code, "count": int(n)}
        return best

    def final_alphas(self) -> List[Dict[str, Any]]:
        from backend.optimize.funnel import stages as gates
        with self._lock:
            ids = [r[0] for r in self._con.execute("SELECT alpha_id FROM alphas WHERE stage_idx=? AND rejected_idx IS NULL ORDER BY ord",
                                                   (gates.STAGE_IDX["FINAL"],)).fetchall()]
        return [self.get_alpha(i) for i in ids]

    def get_alpha(self, alpha_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            r = self._con.execute(
                "SELECT alpha_id, strategy, params_json, ord, stage_reached, stage_idx, rejected_stage, reject_code, reject_msg, final_scale "
                "FROM alphas WHERE alpha_id=?", (alpha_id,)).fetchone()
        if not r:
            return None
        return {"alpha_id": r[0], "strategy": r[1], "params": json.loads(r[2]), "ord": r[3], "stage_reached": r[4], "stage_idx": r[5],
                "rejected_stage": r[6], "reject_code": r[7], "reject_msg": r[8], "final_scale": r[9]}

    def alpha_metrics(self, alpha_id: str) -> Dict[str, Dict[str, Any]]:
        from backend.optimize.funnel import stages as gates
        with self._lock:
            rows = self._con.execute("SELECT stage, metrics_json FROM stage_metrics WHERE alpha_id=?", (alpha_id,)).fetchall()
        return {s: json.loads(m) for s, m in rows if s in gates.ALL_STAGE_IDX}

    def metrics_of(self, alpha_ids: Sequence[str], stage: str) -> Dict[str, Dict[str, Any]]:
        """{alpha_id: metrics} của một stage (kể cả NEIGHBOUR_STAGE), theo lô để không vượt giới hạn tham số SQLite."""
        out: Dict[str, Dict[str, Any]] = {}
        ids = list(alpha_ids)
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            with self._lock:
                rows = self._con.execute(f"SELECT alpha_id, metrics_json FROM stage_metrics WHERE stage=? AND alpha_id IN ({','.join('?' * len(part))})",
                                         [stage, *part]).fetchall()
            out.update({a: json.loads(m) for a, m in rows})
        return out

    def iter_stage_metrics(self, stage: str, strategy: Optional[str] = None, flat: bool = True,
                           passed_only: bool = False) -> Iterator[Tuple[str, str, Dict[str, Any], float]]:
        """Duyệt (alpha_id, strategy, metrics_json đã parse, score) của một tầng theo ord (streaming, lô 2000). passed_only: chỉ alpha qua tầng."""
        q = ("SELECT m.alpha_id, a.strategy, m.metrics_json, m.score FROM stage_metrics m JOIN alphas a ON a.alpha_id=m.alpha_id "
             "WHERE m.stage=?" + (" AND m.passed=1" if passed_only else ""))
        args: List[Any] = [stage]
        if strategy is not None:
            q += " AND a.strategy=?"
            args.append(strategy)
        q += " ORDER BY a.ord"
        with self._lock:
            cur = self._con.cursor()
            cur.execute(q, args)
        while True:
            with self._lock:
                batch = cur.fetchmany(2000)
            if not batch:
                break
            for a, s, mj, sc in batch:
                yield a, s, json.loads(mj), sc

    def top_by_score(self, stage: str, strategy: str, k: int) -> List[str]:
        """k alpha_id điểm IS (ret/max(mdd,1)) cao nhất của một chiến lược ở một tầng; hoà điểm -> ord nhỏ trước."""
        with self._lock:
            rows = self._con.execute(
                "SELECT m.alpha_id FROM stage_metrics m JOIN alphas a ON a.alpha_id=m.alpha_id WHERE m.stage=? AND a.strategy=? "
                "ORDER BY m.score IS NULL, m.score DESC, a.ord LIMIT ?", (stage, strategy, int(k))).fetchall()
        return [r[0] for r in rows]

    # ── đọc: parquet ───────────────────────────────────────────────────────
    def _files_of(self, alpha_id: str, kind: str, stage: Optional[str] = None) -> List[Tuple[str, str]]:
        q, args = "SELECT stage, file FROM alpha_files WHERE alpha_id=? AND kind=?", [alpha_id, kind]
        if stage is not None:
            q += " AND stage=?"
            args.append(stage)
        with self._lock:
            return [(s, f) for s, f in self._con.execute(q + " ORDER BY stage, file", args).fetchall()]

    def read_trades(self, alpha_id: str, stage: Optional[str] = None, fold: Optional[int] = None) -> List[Dict[str, Any]]:
        """Lệnh đã lưu của alpha (theo tầng thư mục; cột `stage` có thể là biến thể vd. S6_holdout_extreme), sắp theo (stage, fold, enter_time)."""
        rows: List[Dict[str, Any]] = []
        for st, fn in self._files_of(alpha_id, "trades", stage):
            flt = [("alpha_id", "=", alpha_id)]
            if fold is not None:
                flt.append(("fold", "=", int(fold)))
            tb = pq.read_table(os.path.join(self.part_dir("trades", st), fn), filters=flt)
            rows.extend(tb.to_pylist())
        rows.sort(key=lambda r: (r["stage"], -1 if r["fold"] is None else r["fold"], r["enter_time"]))
        return rows

    def has_trades(self, alpha_id: str, stage: str) -> bool:
        return bool(self._files_of(alpha_id, "trades", stage))

    def read_daily(self, alpha_id: str, stage: str, stage_col: Optional[str] = None) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for st, fn in self._files_of(alpha_id, "daily", stage):
            tb = pq.read_table(os.path.join(self.part_dir("daily", st), fn), filters=[("alpha_id", "=", alpha_id)])
            out.extend(r for r in tb.to_pylist() if stage_col is None or r["stage"] == stage_col)
        out.sort(key=lambda r: (-1 if r["fold"] is None else r["fold"]))
        return out

    def read_daily_many(self, alpha_ids: Sequence[str], stage: str, stage_col: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """{alpha_id: [hàng daily]} của nhiều alpha (đọc mỗi file parquet một lần)."""
        wanted = set(alpha_ids)
        by_file: Dict[str, set] = {}
        for i in range(0, len(alpha_ids), 500):
            part = list(alpha_ids[i:i + 500])
            with self._lock:
                rows = self._con.execute(
                    f"SELECT alpha_id, file FROM alpha_files WHERE kind='daily' AND stage=? AND alpha_id IN ({','.join('?' * len(part))})",
                    [stage, *part]).fetchall()
            for a, f in rows:
                by_file.setdefault(f, set()).add(a)
        out: Dict[str, List[Dict[str, Any]]] = {}
        for fn, ids in sorted(by_file.items()):
            tb = pq.read_table(os.path.join(self.part_dir("daily", stage), fn), filters=[("alpha_id", "in", sorted(ids))])
            for r in tb.to_pylist():
                if r["alpha_id"] in wanted and (stage_col is None or r["stage"] == stage_col):
                    out.setdefault(r["alpha_id"], []).append(r)
        for rows in out.values():
            rows.sort(key=lambda r: (-1 if r["fold"] is None else r["fold"]))
        return out

    # ── mc ─────────────────────────────────────────────────────────────────
    def write_mc(self, alpha_id: str, obj: Dict[str, Any]) -> None:
        atomic_write_json(self.mc_path(alpha_id), obj)

    def read_mc(self, alpha_id: str) -> Optional[Dict[str, Any]]:
        return read_json(self.mc_path(alpha_id))

    # ── thống kê dung lượng ────────────────────────────────────────────────
    def disk_bytes(self) -> int:
        total = 0
        for base, _, files in os.walk(self.run_dir):
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(base, fn))
                except OSError:
                    pass
        return total


# ══════════════════════════════════════════════════════════════════════════
# Kho kết quả append-only (SQLite, WAL) cho mỗi lần chạy tối ưu quy mô lớn: <run_dir>/results.sqlite.
#
# Vì sao: tối ưu tới ~1.000.000 cấu hình không thể giữ mọi kết quả trong RAM của tiến trình cha (và không thể chạy lại từ đầu khi
# bị kill). Mỗi kết quả của một job được ghi NGAY vào kho (idempotent theo job_key); tiến trình cha chỉ giữ top-K trong RAM; chạy lại
# với --resume bỏ qua các job_key đã có -> kết quả cuối y hệt lần chạy không gián đoạn.
#
# Bảng:
#   results(job_key TEXT PRIMARY KEY, stage, candidate, ord INTEGER, params_json, metrics_json, score REAL, created REAL)
#       ord = chỉ số cấu hình theo thứ tự sinh (để xếp hạng hoà điểm giống `sorted` ổn định); score = điểm xếp hạng (NULL = không đạt / -inf)
#   meta(key TEXT PRIMARY KEY, value TEXT)
# job_key = sha1(stage, candidate, params chuẩn hoá, cửa sổ, stop_fill, risk, sha256 dữ liệu, phiên bản mã) — đổi một trong các thành phần
# này thì kết quả cũ KHÔNG bao giờ được dùng lại.
#
# Ghi theo lô (commit mỗi COMMIT_EVERY lần put hoặc COMMIT_SECONDS giây); flush()/close() ghi nốt — CLI gọi trong finally + khi nhận SIGTERM.
# Móc kiểm thử: env NORA_TEST_FAIL_AFTER_PUTS=N -> sau lần put thứ N (đã commit) ném RuntimeError để mô phỏng sập giữa chừng (chỉ dùng trong test).
#
# Chạy một giai đoạn kiểu streaming (stream_stage):
# Chạy một giai đoạn tối ưu theo kiểu STREAMING: job sinh lười -> pool (bounded) -> ghi ngay vào ResultsStore -> chỉ giữ top-K trong RAM.
#
# stream_stage() là khung dùng chung cho build_strategy_book (giai đoạn A) và sàng lọc của optimize/funnel/stages:
#   - bỏ qua job đã có trong kho (job_key) -> `--resume` tiếp tục đúng chỗ dừng, kết quả cuối y hệt lần chạy không gián đoạn;
#   - kết quả mỗi job được chuẩn hoá qua JSON (cùng cấu trúc dù lấy từ worker hay từ kho) trước khi đưa cho `handle`;
#   - `handle(ord, params, metrics, from_store) -> (metrics_để_lưu, điểm)` quyết định lưu gì (vd. bỏ chuỗi `daily` của hàng không thuộc top-K).
# ══════════════════════════════════════════════════════════════════════════

COMMIT_EVERY = 200
COMMIT_SECONDS = 3.0
SCHEMA_VERSION = 1

_RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS results(
    job_key TEXT PRIMARY KEY, stage TEXT NOT NULL, candidate TEXT NOT NULL, ord INTEGER,
    params_json TEXT NOT NULL, metrics_json TEXT NOT NULL, score REAL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS results_rank ON results(stage, candidate, score DESC, ord);
CREATE INDEX IF NOT EXISTS results_ord ON results(stage, candidate, ord);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""

_CODE_FILES = (   # mọi file ảnh hưởng kết quả backtest: đổi một file -> khoá job đổi -> --resume không dùng lại kết quả cũ
    "backend/alpha/dsl/strategy.py", "backend/models/models.py", "backend/models/params.py", "backend/models/position_size.py",   # tín hiệu + kế hoạch vị thế
    "backend/nautilus/engine.py", "backend/optimize/search/evaluate.py",   # P15: engine khớp lệnh = Nautilus (adapter) + vòng chạy
    "backend/metrics/metrics.py", "backend/metrics/trades.py",   # P9.5: returns+portfolio gộp, trades chuyển
    "backend/data/data.py", "backend/alpha/dsl/signal.py", "backend/alpha/contract.py", "backend/alpha/compile.py", "backend/alpha/dsl/indicator.py",   # P9.4 part 2: evaluator/kernels đã gộp
    "backend/optimize/book/build.py", "backend/wfa/wfa.py",   # P9.5 (+ P9.9: sổ chiến lược book.py/library.py gộp vào build.py/signal.py)
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
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from backend.nautilus.version import NAUTILUS_VERSION
        h = hashlib.sha1(f"v{SCHEMA_VERSION}|nautilus {NAUTILUS_VERSION}".encode())   # nâng Nautilus -> khoá job đổi
        for rel in _CODE_FILES:
            try:
                with open(os.path.join(root, rel), "rb") as fh:
                    h.update(rel.encode() + b"\0" + fh.read())
            except OSError:
                h.update(rel.encode() + b"\0missing")
        _CODE_VERSION = h.hexdigest()[:16]
    return _CODE_VERSION


def data_fingerprint(symbols: Iterable[str]) -> List[Any]:
    """Dấu vân tay catalog nến 1m của từng tài sản (data.catalog_digest) — thành phần của job_key."""
    from backend.data.data import catalog_digest
    return [[s, catalog_digest([s])] for s in symbols]


def make_job_key(stage: str, candidate: str, params: Any, window: Any = None, stop_fill: Any = None, risk: Any = None,
                 data: Any = None, code: Optional[str] = None, extra: Any = None) -> str:
    payload = canonical([stage, candidate, params, window, stop_fill, risk, data, code or code_version(), extra])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _results_dumps(obj: Any) -> str:
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
            self._con.executescript(_RESULTS_SCHEMA)
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
                (job_key, stage, candidate, ord, _results_dumps(params), _results_dumps(metrics), sc, time.time()))
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
            self._con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)", (key, _results_dumps(value)))

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
