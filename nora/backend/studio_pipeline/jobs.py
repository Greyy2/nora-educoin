"""Quản lý Jobs và State Persistence cho Studio Pipeline (Backtest -> WFA -> Monte Carlo).

Sử dụng SQLite bền vững (studio_pipeline.db) kết hợp in-memory cache để:
- Không bao giờ mất lịch sử chạy khi server restart hoặc reload workers.
- Cung cấp API lịch sử (history) cho cả 3 giai đoạn: Backtest, WFA, Monte Carlo.
"""
import json
import os
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="StudioPipelineWorker")

def _get_db_path() -> str:
    """Đọc DB path từ env var mỗi lần gọi để conftest.py có thể override."""
    return os.environ.get(
        "NORA_PIPELINE_DB_PATH",
        "/home/ubuntu/norabt/data/studio_pipeline.db",
    )

# Giá trị tại thời điểm import (giữ để tương thích). Mọi truy cập DB đều gọi
# _get_db_path() nên đổi NORA_PIPELINE_DB_PATH lúc chạy vẫn có hiệu lực.
DB_PATH = _get_db_path()

# In-memory fast caches
_BACKTEST_SOURCES: Dict[str, Dict[str, Any]] = {}
_WFA_JOBS: Dict[str, Dict[str, Any]] = {}
_MC_JOBS: Dict[str, Dict[str, Any]] = {}


def _get_db() -> sqlite3.Connection:
    path = _get_db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db():
    """Khởi tạo các bảng SQLite nếu chưa tồn tại."""
    path = _get_db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with _get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS backtest_sources (
            handle TEXT PRIMARY KEY,
            symbol TEXT,
            strategy_name TEXT,
            saved_at INTEGER,
            data_json TEXT
        );

        CREATE TABLE IF NOT EXISTS wfa_jobs (
            job_id TEXT PRIMARY KEY,
            source_handle TEXT,
            symbol TEXT,
            strategy_name TEXT,
            status TEXT,
            progress_pct REAL,
            current_fold INTEGER,
            total_folds INTEGER,
            message TEXT,
            created_at INTEGER,
            completed_at INTEGER,
            result_json TEXT,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS mc_jobs (
            job_id TEXT PRIMARY KEY,
            source_wfa_id TEXT,
            symbol TEXT,
            strategy_name TEXT,
            status TEXT,
            progress_pct REAL,
            simulations INTEGER,
            trades_count INTEGER,
            message TEXT,
            created_at INTEGER,
            completed_at INTEGER,
            result_json TEXT,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS scan_jobs (
            job_id TEXT PRIMARY KEY,
            strategy_name TEXT,
            status TEXT,
            progress_pct REAL,
            total INTEGER,
            done INTEGER,
            message TEXT,
            created_at INTEGER,
            completed_at INTEGER,
            request_json TEXT,
            result_json TEXT,
            error TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_scan_created ON scan_jobs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_wfa_created ON wfa_jobs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_mc_created ON mc_jobs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_bt_created ON backtest_sources(saved_at DESC);
        """)
        # Safe migration for existing tables
        try:
            conn.execute("ALTER TABLE wfa_jobs ADD COLUMN source_handle TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE mc_jobs ADD COLUMN source_wfa_id TEXT")
        except Exception:
            pass



# Khởi tạo database ngay khi load module
try:
    init_db()
except Exception as _e:
    print(f"Warning: Failed to initialize pipeline SQLite DB: {_e}")


def generate_handle(prefix: str = "src") -> str:
    return f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:8]}"


# ─── Backtest Source Storage ──────────────────────────────────────────────────
def save_backtest_source(source_data: Dict[str, Any]) -> str:
    handle = source_data.get("source_handle") or generate_handle("bt_src")
    source_data["source_handle"] = handle
    now_ms = int(time.time() * 1000)
    source_data["saved_at"] = now_ms
    _BACKTEST_SOURCES[handle] = source_data

    symbol = str(source_data.get("symbol") or "")
    strat_name = "Studio Strategy"
    if "strategy_snapshot" in source_data:
        strat_name = str(source_data["strategy_snapshot"].get("name") or strat_name)

    try:
        with _get_db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO backtest_sources (handle, symbol, strategy_name, saved_at, data_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (handle, symbol, strat_name, now_ms, json.dumps(source_data)),
            )
    except Exception as ex:
        print(f"SQLite save_backtest_source error: {ex}")

    return handle


def get_backtest_source(handle: str) -> Optional[Dict[str, Any]]:
    if handle in _BACKTEST_SOURCES:
        return _BACKTEST_SOURCES[handle]
    try:
        with _get_db() as conn:
            row = conn.execute("SELECT data_json FROM backtest_sources WHERE handle = ?", (handle,)).fetchone()
            if row and row["data_json"]:
                data = json.loads(row["data_json"])
                _BACKTEST_SOURCES[handle] = data
                return data
    except Exception as ex:
        print(f"SQLite get_backtest_source error: {ex}")
    return None


def list_backtest_history(limit: int = 30) -> List[Dict[str, Any]]:
    history = []
    try:
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT handle, symbol, strategy_name, saved_at, data_json FROM backtest_sources ORDER BY saved_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            for r in rows:
                item = {
                    "handle": r["handle"],
                    "symbol": r["symbol"],
                    "strategy_name": r["strategy_name"],
                    "saved_at": r["saved_at"],
                }
                if r["data_json"]:
                    try:
                        d = json.loads(r["data_json"])
                        item["summary"] = d.get("summary", {})
                        item["trades_count"] = len(d.get("trades", []))
                    except Exception:
                        pass
                history.append(item)
    except Exception as ex:
        print(f"SQLite list_backtest_history error: {ex}")
    return history


# ─── WFA Job Management ───────────────────────────────────────────────────────
def create_wfa_job(symbol: str, strategy_name: str, total_folds: int, source_handle: str = "") -> str:
    job_id = generate_handle("wfa_job")
    now_ms = int(time.time() * 1000)
    job_data = {
        "job_id": job_id,
        "source_handle": source_handle or job_id,
        "symbol": symbol,
        "strategy_name": strategy_name,
        "status": "pending",
        "progress_pct": 0.0,
        "current_fold": 0,
        "total_folds": total_folds,
        "message": "Đang khởi tạo danh sách Folds...",
        "created_at": now_ms,
        "completed_at": None,
        "result": None,
        "error": None,
    }
    _WFA_JOBS[job_id] = job_data

    try:
        with _get_db() as conn:
            conn.execute(
                """INSERT INTO wfa_jobs (job_id, source_handle, symbol, strategy_name, status, progress_pct, current_fold, total_folds, message, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, source_handle or job_id, symbol, strategy_name, "pending", 0.0, 0, total_folds, "Đang khởi tạo Folds...", now_ms),
            )
    except Exception as ex:
        print(f"SQLite create_wfa_job error: {ex}")

    return job_id


def update_wfa_progress(job_id: str, fold: int, total_folds: int, message: str = ""):
    progress = round((fold / total_folds) * 100.0, 1) if total_folds > 0 else 0.0
    if job_id in _WFA_JOBS:
        _WFA_JOBS[job_id]["current_fold"] = fold
        _WFA_JOBS[job_id]["progress_pct"] = progress
        _WFA_JOBS[job_id]["status"] = "running"
        if message:
            _WFA_JOBS[job_id]["message"] = message

    try:
        with _get_db() as conn:
            conn.execute(
                """UPDATE wfa_jobs SET progress_pct = ?, current_fold = ?, status = 'running', message = ?
                   WHERE job_id = ?""",
                (progress, fold, message or "Đang thực thi...", job_id),
            )
    except Exception:
        pass


def complete_wfa_job(job_id: str, result: Dict[str, Any]):
    now_ms = int(time.time() * 1000)
    if job_id in _WFA_JOBS:
        _WFA_JOBS[job_id]["status"] = "completed"
        _WFA_JOBS[job_id]["progress_pct"] = 100.0
        _WFA_JOBS[job_id]["message"] = "Hoàn thành WFA."
        _WFA_JOBS[job_id]["result"] = result
        _WFA_JOBS[job_id]["completed_at"] = now_ms

    try:
        with _get_db() as conn:
            conn.execute(
                """UPDATE wfa_jobs SET status = 'completed', progress_pct = 100.0, message = 'Hoàn thành WFA.',
                   completed_at = ?, result_json = ? WHERE job_id = ?""",
                (now_ms, json.dumps(result), job_id),
            )
    except Exception as ex:
        print(f"SQLite complete_wfa_job error: {ex}")


def fail_wfa_job(job_id: str, error_msg: str):
    now_ms = int(time.time() * 1000)
    if job_id in _WFA_JOBS:
        _WFA_JOBS[job_id]["status"] = "failed"
        _WFA_JOBS[job_id]["error"] = error_msg
        _WFA_JOBS[job_id]["message"] = f"Lỗi: {error_msg}"
        _WFA_JOBS[job_id]["completed_at"] = now_ms

    try:
        with _get_db() as conn:
            conn.execute(
                """UPDATE wfa_jobs SET status = 'failed', error = ?, message = ?, completed_at = ? WHERE job_id = ?""",
                (error_msg, f"Lỗi: {error_msg}", now_ms, job_id),
            )
    except Exception as ex:
        print(f"SQLite fail_wfa_job error: {ex}")


def get_wfa_job(job_id: str) -> Optional[Dict[str, Any]]:
    if job_id in _WFA_JOBS:
        return _WFA_JOBS[job_id]
    try:
        with _get_db() as conn:
            row = conn.execute("SELECT * FROM wfa_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row:
                d = dict(row)
                if d.get("result_json"):
                    try:
                        d["result"] = json.loads(d["result_json"])
                    except Exception:
                        d["result"] = None
                _WFA_JOBS[job_id] = d
                return d
    except Exception as ex:
        print(f"SQLite get_wfa_job error: {ex}")
    return None


def list_wfa_history(limit: int = 30) -> List[Dict[str, Any]]:
    """Lấy danh sách lịch sử các lần chạy WFA từ SQLite."""
    history = []
    try:
        with _get_db() as conn:
            rows = conn.execute(
                """SELECT job_id, source_handle, symbol, strategy_name, status, progress_pct, current_fold, total_folds,
                          message, created_at, completed_at, result_json, error
                   FROM wfa_jobs ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            for r in rows:
                item = dict(r)
                if item.get("result_json"):
                    try:
                        res = json.loads(item["result_json"])
                        item["avg_oos_return_pct"] = res.get("avg_oos_return_pct")
                        item["worst_fold_mdd_pct"] = res.get("worst_fold_mdd_pct")
                        item["acceptance_gate_passed"] = res.get("acceptance_gate_passed")
                        item["total_oos_trades"] = res.get("total_oos_trades")
                        item["result"] = res
                    except Exception:
                        item["result"] = None
                del item["result_json"]
                item["source_handle"] = item.get("source_handle") or item["job_id"]
                history.append(item)
    except Exception as ex:
        print(f"SQLite list_wfa_history error: {ex}")
    return history


# ─── Monte Carlo Job Management ───────────────────────────────────────────────
def create_mc_job(symbol: str, strategy_name: str, simulations: int, source_wfa_id: str = "") -> str:
    job_id = generate_handle("mc_job")
    now_ms = int(time.time() * 1000)
    job_data = {
        "job_id": job_id,
        "source_wfa_id": source_wfa_id or job_id,
        "symbol": symbol,
        "strategy_name": strategy_name,
        "status": "pending",
        "progress_pct": 0.0,
        "simulations": simulations,
        "message": f"Khởi chạy mô phỏng {simulations} kịch bản Monte Carlo...",
        "created_at": now_ms,
        "completed_at": None,
        "result": None,
        "error": None,
    }
    _MC_JOBS[job_id] = job_data

    try:
        with _get_db() as conn:
            conn.execute(
                """INSERT INTO mc_jobs (job_id, source_wfa_id, symbol, strategy_name, status, progress_pct, simulations, trades_count, message, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, source_wfa_id or job_id, symbol, strategy_name, "pending", 0.0, simulations, 0, f"Khởi chạy {simulations} kịch bản...", now_ms),
            )
    except Exception as ex:
        print(f"SQLite create_mc_job error: {ex}")

    return job_id


def complete_mc_job(job_id: str, result: Dict[str, Any]):
    now_ms = int(time.time() * 1000)
    if job_id in _MC_JOBS:
        _MC_JOBS[job_id]["status"] = "completed"
        _MC_JOBS[job_id]["progress_pct"] = 100.0
        _MC_JOBS[job_id]["message"] = "Hoàn thành mô phỏng Monte Carlo."
        _MC_JOBS[job_id]["result"] = result
        _MC_JOBS[job_id]["completed_at"] = now_ms

    trades_count = result.get("trades_count", 0) if isinstance(result, dict) else 0

    try:
        with _get_db() as conn:
            conn.execute(
                """UPDATE mc_jobs SET status = 'completed', progress_pct = 100.0, message = 'Hoàn thành mô phỏng Monte Carlo.',
                   completed_at = ?, trades_count = ?, result_json = ? WHERE job_id = ?""",
                (now_ms, trades_count, json.dumps(result), job_id),
            )
    except Exception as ex:
        print(f"SQLite complete_mc_job error: {ex}")


def fail_mc_job(job_id: str, error_msg: str):
    now_ms = int(time.time() * 1000)
    if job_id in _MC_JOBS:
        _MC_JOBS[job_id]["status"] = "failed"
        _MC_JOBS[job_id]["error"] = error_msg
        _MC_JOBS[job_id]["message"] = f"Lỗi: {error_msg}"
        _MC_JOBS[job_id]["completed_at"] = now_ms

    try:
        with _get_db() as conn:
            conn.execute(
                """UPDATE mc_jobs SET status = 'failed', error = ?, message = ?, completed_at = ? WHERE job_id = ?""",
                (error_msg, f"Lỗi: {error_msg}", now_ms, job_id),
            )
    except Exception as ex:
        print(f"SQLite fail_mc_job error: {ex}")


def get_mc_job(job_id: str) -> Optional[Dict[str, Any]]:
    if job_id in _MC_JOBS:
        return _MC_JOBS[job_id]
    try:
        with _get_db() as conn:
            row = conn.execute("SELECT * FROM mc_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row:
                d = dict(row)
                if d.get("result_json"):
                    try:
                        d["result"] = json.loads(d["result_json"])
                    except Exception:
                        d["result"] = None
                _MC_JOBS[job_id] = d
                return d
    except Exception as ex:
        print(f"SQLite get_mc_job error: {ex}")
    return None


def list_mc_history(limit: int = 30) -> List[Dict[str, Any]]:
    """Lấy danh sách lịch sử các lần chạy Monte Carlo từ SQLite."""
    history = []
    try:
        with _get_db() as conn:
            rows = conn.execute(
                """SELECT job_id, source_wfa_id, symbol, strategy_name, status, progress_pct, simulations, trades_count,
                          message, created_at, completed_at, result_json, error
                   FROM mc_jobs ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            for r in rows:
                item = dict(r)
                if item.get("result_json"):
                    try:
                        res = json.loads(item["result_json"])
                        item["summary"] = res.get("summary", {})
                        item["result"] = res
                    except Exception:
                        item["result"] = None
                del item["result_json"]
                item["source_wfa_id"] = item.get("source_wfa_id") or item["job_id"]
                history.append(item)
    except Exception as ex:
        print(f"SQLite list_mc_history error: {ex}")
    return history


def submit_background_task(fn, *args, **kwargs):
    return _EXECUTOR.submit(fn, *args, **kwargs)

