"""Tính lại danh sách lệnh S1 của một alpha (alpha bị loại ở S1 chỉ lưu thống kê). Tất định: cùng PortfolioEngine, cùng tham số/cửa sổ/dữ liệu
-> TRÙNG TỪNG BIT với lệnh một alpha qua S1 đã lưu (test_funnel kiểm). Kết quả được ghi đệm tại <run_dir>/recomputed/<alpha_id>.json.

CLI (API chạy qua run_limited.sh --no-lock để RAM nằm trong nora.slice, không trong tiến trình API):
    backend/utils/ops/run_limited.sh --no-lock -- -m backend.optimize.funnel.recompute <run_id> <alpha_id>
"""
import os
if __name__ == "__main__":   # chỉ khi chạy như script (tiến trình con của API): đặt TRƯỚC khi nạp numpy; import từ API không đổi môi trường
    for _e in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(_e, "1")
    os.environ.setdefault("NORA_CANDLE_CACHE_MB", "512")
    os.environ.setdefault("NORA_DATA_CACHE_MB", "1024")

import json
import sys
from typing import Any, Dict, List, Optional

from . import backtest as bt, gates
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
    job = bt.base_job(alpha["strategy"], alpha["params"], (w["start"], w["dev1_end"]), "level", False, gates.BASE_RISK_PER_TRADE_PCT, symbols, shared_dir)
    res = bt.run_backtest(job, want_trades=True)
    return {"alpha_id": alpha_id, "trades": res["trades"], "metrics": res["metrics"], "daily": res["daily"], "daily_start": res["daily_start"]}


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("dùng: python -m backend.optimize.funnel.recompute <run_id> <alpha_id>", file=sys.stderr)
        return 2
    from backend.utils.memwatch import require_memory_limit
    require_memory_limit("funnel.recompute")
    from .orchestrator import funnel_root
    run_id, alpha_id = argv
    run_dir = os.path.join(funnel_root(), run_id)
    from backend.core.data.quality_gate import require_data_ok_or_exit
    store = RunStore(run_dir, read_only=True)
    try:
        symbols = store.read_run()["config"]["symbols"]
    finally:
        store.close()
    require_data_ok_or_exit(symbols)
    atomic_write_json(cache_path(run_dir, alpha_id), recompute_s1(run_dir, alpha_id))
    print(f"ghi: {cache_path(run_dir, alpha_id)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
