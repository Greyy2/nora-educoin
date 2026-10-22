"""Runner cho kiểm định Monte Carlo (Carlo Validation Runner)."""
from typing import Any, Dict, List, Optional

from backend.analys.validation.carlo import carlo
from backend.models.storage import write_job_result


def run_carlo(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Chạy mô phỏng Monte Carlo theo tham số và ghi kết quả."""
    params = params or {}
    trades = params.get("trades") or []
    sims = int(params.get("sims", 10000))
    seed = int(params.get("seed", 1))
    
    result = carlo.simulate(trades=trades, sims=sims, seed=seed)
    write_job_result(result)
    return result


__all__ = [
    "run_carlo",
]
