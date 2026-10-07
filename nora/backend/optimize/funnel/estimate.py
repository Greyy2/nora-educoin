"""Ước tính thời gian S1 của phễu từ SỐ ĐO THẬT của các lượt đã chạy (không hằng số "đo sẵn").

Mỗi lượt xong ghi run.json: stages.S1_backtest.{wall_s, input} (thời gian tường và số alpha thật sự được chấm ở S1) và `workers`
(từ P9.13; lượt cũ không có thì đọc dòng "run_id ... | workers=N" trong out.log của job). Số đo = worker-giây mỗi backtest
= wall_s × workers / input (giả định các worker bận gần hết thời gian S1 — chính là cách S1 chạy: pool_imap_bounded kín việc).

Chỉ dùng lượt cùng khung chạy (`timeframe`) và cùng chế độ regime: khác nhau thì giây/backtest khác hẳn (15m vs 1m, regime=learn chạy thêm một lượt
quan sát) -> không ngoại suy. Không có lượt khớp -> sec_per_backtest = None + lý do (giao diện hiện "chưa có số đo"). Không có file bench
nào được lưu nên không có đường dự phòng khác: chỉ số đo thật.
"""
import json
import os
import re
import statistics
from typing import Any, Dict, List, Optional

MAX_REF_RUNS = 8
_WORKERS_RE = re.compile(r"^run_id\s+\S+\s*\|.*\bworkers=(\d+)", re.M)


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _workers_of(run: Dict[str, Any], jobs_root: Optional[str]) -> Optional[int]:
    w = run.get("workers")
    if isinstance(w, int) and not isinstance(w, bool) and w > 0:
        return w
    job_id = run.get("job_id")
    if not job_id or not jobs_root or not re.fullmatch(r"[0-9A-Za-z_-]{3,64}", str(job_id)):
        return None
    try:
        with open(os.path.join(jobs_root, str(job_id), "out.log"), encoding="utf-8", errors="replace") as fh:
            head = fh.read(20000)
    except OSError:
        return None
    m = _WORKERS_RE.search(head)
    return int(m.group(1)) if m else None


def measured_s1_rate(funnel_root: str, timeframe: str, regime: str = "off", jobs_root: Optional[str] = None,
                     limit: int = MAX_REF_RUNS) -> Dict[str, Any]:
    """-> {"sec_per_backtest": trung vị worker-giây/backtest | None, "n_runs", "runs": [{run_id, wall_s, input, workers, sec_per_backtest}],
    "reason": None | lý do không có số đo}."""
    rows: List[Dict[str, Any]] = []
    try:
        names = os.listdir(funnel_root)
    except OSError:
        names = []
    skipped_workers = 0
    for name in names:
        run = _read_json(os.path.join(funnel_root, name, "run.json"))
        if not run or run.get("status") != "done":
            continue
        cfg = run.get("config") or {}
        if (cfg.get("timeframe") or "1m") != timeframe or (cfg.get("regime") or "off") != (regime or "off"):
            continue
        s1 = (run.get("stages") or {}).get("S1_backtest") or {}
        wall, n = s1.get("wall_s"), s1.get("input")
        if s1.get("status") != "done" or not isinstance(wall, (int, float)) or not isinstance(n, (int, float)) or wall <= 0 or n <= 0:
            continue
        workers = _workers_of(run, jobs_root)
        if workers is None:
            skipped_workers += 1
            continue
        rows.append({"run_id": run.get("run_id") or name, "finished": run.get("finished") or 0, "wall_s": float(wall), "input": int(n),
                     "workers": workers, "sec_per_backtest": float(wall) * workers / int(n)})
    rows.sort(key=lambda r: r["finished"], reverse=True)
    rows = rows[:limit]
    if not rows:
        why = f"chưa có lượt phễu đã xong nào ở khung {timeframe}, regime={regime or 'off'}" + (
            f" ({skipped_workers} lượt khớp nhưng không biết số worker)" if skipped_workers else "")
        return {"sec_per_backtest": None, "n_runs": 0, "runs": [], "reason": why}
    return {"sec_per_backtest": statistics.median(r["sec_per_backtest"] for r in rows), "n_runs": len(rows),
            "runs": [{k: v for k, v in r.items() if k != "finished"} for r in rows], "reason": None}
