"""Router tóm tắt số liệu trang chủ Home (P17 T2 B4).

Endpoint GET /api/home/summary phục vụ số liệu thật cho trang Home (2 thẻ Education và Coin).
Số liệu lấy hoàn toàn từ nguồn thật, cache theo thời gian 1s để giảm tải I/O.
"""
import os
import time
from typing import Any, Dict, Optional
from fastapi import APIRouter

from backend import users
from backend.analys.alpha import strategies as store, strategies
from backend.data.data import default_universe, read_manifest
from backend.analys.param import iso_date
from backend.models.storage import alpha_dir, alpha_education_samples, read_json

home_router = APIRouter(tags=["home"])


_SUMMARY_CACHE: Optional[Dict[str, Any]] = None
_CACHE_TIME: float = 0.0


@home_router.get("/api/home/summary")
def get_home_summary() -> Dict[str, Any]:
    """Số liệu thật cho trang Home."""
    global _SUMMARY_CACHE, _CACHE_TIME
    now = time.time()
    if _SUMMARY_CACHE is not None and (now - _CACHE_TIME) < 1.0:
        return _SUMMARY_CACHE

    # 1. Education
    n_users = len(users.list_users())
    all_alphas = store.list_user_alphas()
    n_strategies = sum(1 for a in all_alphas if a.get("owner_id") and a.get("status") != "ARCHIVED")

    samples_file = alpha_education_samples()
    samples_list = read_json(samples_file) if os.path.isfile(samples_file) else []
    n_samples = len(samples_list) if isinstance(samples_list, list) else 0

    res_dir = alpha_dir("education", "results")
    if os.path.isdir(res_dir):
        n_ready = len([f for f in os.listdir(res_dir) if f.endswith(".json") and not f.endswith(".tmp")])
    else:
        n_ready = 0

    edu_data = {
        "users": n_users,
        "strategies": n_strategies,
        "samples": n_samples,
        "samples_ready": n_ready,
    }

    # 2. Coin
    # Đếm số chiến lược hệ thống (theo catalog STRATEGIES)
    n_system = len(strategies.STRATEGIES)
    symbols = default_universe()
    n_symbols = len(symbols)

    lasts = []
    for sym in default_universe():
        m = read_manifest(sym)
        if m and m.get("end_ts"):
            try:
                lasts.append(int(m["end_ts"]))
            except (ValueError, TypeError):
                pass
    data_end = iso_date(min(lasts)) if lasts else None

    coin_data = {
        "system_strategies": n_system,
        "symbols": n_symbols,
        "data_end": data_end,
    }

    res = {"edu": edu_data, "coin": coin_data}
    _SUMMARY_CACHE = res
    _CACHE_TIME = now
    return res
