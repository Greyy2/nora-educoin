"""Scan backtest: một chiến lược × nhiều tài sản, chạy nền, có tiến độ, lưu SQLite (bảng scan_jobs).

Mỗi tài sản: chọn dữ liệu đúng thị trường (spot / @perp), qua quality gate, backtest bằng đúng engine
của Studio/WFA (wfa.walk_forward._run_single_window) trên khoảng thời gian yêu cầu (cắt theo độ phủ
dữ liệu của tài sản). Kết quả tái lập được: cùng dữ liệu (sha256_1m) + cùng tham số -> cùng số.
"""
import json
import time
from typing import Any, Dict, List, Optional

from .store import _get_db, generate_handle

_SCAN_JOBS: Dict[str, Dict[str, Any]] = {}
DAY = 86_400_000


def create_scan_job(strategy_name: str, total: int, request: Dict[str, Any]) -> str:
    job_id = generate_handle("scan_job")
    now = int(time.time() * 1000)
    _SCAN_JOBS[job_id] = {"job_id": job_id, "strategy_name": strategy_name, "status": "pending", "progress_pct": 0.0,
                          "total": total, "done": 0, "message": "Đang chờ chạy...", "created_at": now,
                          "completed_at": None, "result": None, "error": None, "request": request}
    with _get_db() as conn:
        conn.execute("""INSERT INTO scan_jobs (job_id, strategy_name, status, progress_pct, total, done, message,
                        created_at, request_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                     (job_id, strategy_name, "pending", 0.0, total, 0, "Đang chờ chạy...", now, json.dumps(request)))
    return job_id


def _update(job_id: str, **fields) -> None:
    job = _SCAN_JOBS.setdefault(job_id, {"job_id": job_id})
    job.update(fields)
    cols = {k: v for k, v in fields.items() if k in ("status", "progress_pct", "done", "message", "completed_at", "error")}
    if "result" in fields:
        cols["result_json"] = json.dumps(fields["result"], default=str)
    if cols:
        with _get_db() as conn:
            conn.execute(f"UPDATE scan_jobs SET {', '.join(f'{k} = ?' for k in cols)} WHERE job_id = ?",
                         (*cols.values(), job_id))


def get_scan_job(job_id: str) -> Optional[Dict[str, Any]]:
    if job_id in _SCAN_JOBS:
        return _SCAN_JOBS[job_id]
    with _get_db() as conn:
        row = conn.execute("SELECT * FROM scan_jobs WHERE job_id = ?", (job_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["result"] = json.loads(d["result_json"]) if d.get("result_json") else None
    d["request"] = json.loads(d["request_json"]) if d.get("request_json") else None
    return d


def list_scan_history(limit: int = 30) -> List[Dict[str, Any]]:
    with _get_db() as conn:
        rows = conn.execute("""SELECT job_id, strategy_name, status, progress_pct, total, done, message, created_at,
                               completed_at FROM scan_jobs ORDER BY created_at DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]


def execute_scan(job_id: str, flows: List[Dict[str, Any]], symbols: List[str], position: Dict[str, Any],
                 signal_params: Dict[str, float], start_ts: Optional[int], end_ts: Optional[int],
                 days: Optional[int], initial_capital: float) -> None:
    from backend.core.backtest.params_builder import data_symbol
    from backend.db.local_pkl import read_manifest
    from backend.core.data.quality_gate import DataQualityStatus, evaluate_data_quality
    from ...wfa.walk_forward import _run_single_window

    rows = []
    _update(job_id, status="running", message="Đang scan...")
    try:
        market = str(position.get("market") or "spot")
        for i, symbol in enumerate(symbols, start=1):
            row: Dict[str, Any] = {"symbol": symbol}
            try:
                data_sym, price_source = data_symbol(symbol, market)
                manifest = read_manifest(data_sym) or {}
                row.update({"data_symbol": data_sym, "price_source": price_source, "venue": manifest.get("venue"),
                            "sha256_1m": manifest.get("sha256_1m")})
                dq = evaluate_data_quality(data_sym, timeframe="1m")
                row["gate"] = dq["status"]
                if dq["status"] in (DataQualityStatus.BLOCKED, DataQualityStatus.NEEDS_MORE_DATA):
                    row["skipped"] = "; ".join(dq["issues"])
                else:
                    lo, hi = int(manifest["start_ts"]), int(manifest["end_ts"])
                    end = min(int(end_ts), hi) if end_ts else hi
                    start = max(int(start_ts), lo) if start_ts else (max(lo, end - int(days) * DAY) if days else lo)
                    started = time.time()
                    summary, _ = _run_single_window(symbol=symbol, flows=flows, start_ts=start, end_ts=end,
                                                    initial_capital=initial_capital,
                                                    **{**position, **{f"sig.{k}": v for k, v in signal_params.items()}})
                    row.update({"start_ts": start, "end_ts": end, "days": round((end - start) / DAY, 1),
                                "seconds": round(time.time() - started, 1), **summary})
            except ValueError as exc:  # ví dụ: DEX không có perp, spot không short
                row["skipped"] = str(exc)
            rows.append(row)
            _update(job_id, done=i, progress_pct=round(i / len(symbols) * 100, 1), message=f"Xong {symbol} ({i}/{len(symbols)})")
        ranked = sorted([r for r in rows if "return_pct" in r], key=lambda r: -r["return_pct"])
        _update(job_id, status="completed", completed_at=int(time.time() * 1000), progress_pct=100.0,
                message="Hoàn thành scan.", result={"rows": rows, "ranking": [r["symbol"] for r in ranked]})
    except Exception as exc:
        _update(job_id, status="failed", error=repr(exc), completed_at=int(time.time() * 1000))
