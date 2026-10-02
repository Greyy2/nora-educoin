"""Tính lại danh sách lệnh S1 của một alpha (alpha bị loại ở S1 chỉ lưu thống kê). Tất định: cùng PortfolioEngine, cùng tham số/cửa sổ/dữ liệu
-> TRÙNG TỪNG BIT với lệnh một alpha qua S1 đã lưu (test_funnel kiểm). Kết quả được ghi đệm tại <run_dir>/recomputed/<alpha_id>.json.

Job API `funnel_recompute` (api/jobs/runner.py -> run_job({"run_id", "alpha_id"})): RAM nằm trong nora.slice, không trong tiến trình API.
"""
import json
import os
from typing import Any, Dict, Optional

from backend.optimize.funnel import evaluate as bt, gates
from .storage import RunStore, atomic_write_json


def cache_path(run_dir: str, alpha_id: str) -> str:
    return os.path.join(run_dir, "recomputed", f"{alpha_id}.json")


def read_cached(run_dir: str, alpha_id: str) -> Optional[Dict[str, Any]]:
    try:
        with open(cache_path(run_dir, alpha_id), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def recompute_s1(run_dir: str, alpha_id: str, shared_dir: Optional[str] = None) -> Dict[str, Any]:
    """Backtest S1 lại (dev1, rủi ro chuẩn, SL level, kill tắt) -> {"trades": [hàng như parquet, không alpha_id/stage], "metrics": {...}, "daily": [...]}."""
    store = RunStore(run_dir, read_only=True)
    try:
        alpha = store.get_alpha(alpha_id)
        run = store.read_run()
    finally:
        store.close()
    if alpha is None:
        raise KeyError(alpha_id)
    w = run["windows_ms"]
    symbols = run["config"]["symbols"]
    job = bt.base_job(alpha["strategy"], alpha["params"], (w["start"], w["dev1_end"]), "level", False, gates.BASE_RISK_PER_TRADE_PCT, symbols, shared_dir,
                       run["config"].get("timeframe", "1m"))
    res = bt.run_backtest(job, want_trades=True)
    return {"alpha_id": alpha_id, "trades": res["trades"], "metrics": res["metrics"], "daily": res["daily"], "daily_start": res["daily_start"]}


def run_job(params=None) -> Dict[str, Any]:
    """Tính lại lệnh S1 của params["alpha_id"] trong lượt params["run_id"] -> ghi <run_dir>/recomputed/<alpha_id>.json."""
    from backend.utils.jobs import options
    from backend.utils.memwatch import require_memory_limit
    from backend.core.data.quality_gate import require_data_ok_or_exit
    from .orchestrator import funnel_root
    a = options({"run_id": "", "alpha_id": ""}, params)
    if not a.run_id or not a.alpha_id:
        raise ValueError("cần run_id và alpha_id")
    require_memory_limit("funnel.recompute")
    run_dir = os.path.join(funnel_root(), a.run_id)
    store = RunStore(run_dir, read_only=True)
    try:
        symbols = store.read_run()["config"]["symbols"]
    finally:
        store.close()
    require_data_ok_or_exit(symbols)
    path = cache_path(run_dir, a.alpha_id)
    atomic_write_json(path, recompute_s1(run_dir, a.alpha_id))
    print(f"ghi: {path}", flush=True)
    return {"path": path}
