"""Bảo vệ bộ nhớ của pipeline (lỗi cũ: build_strategy_book làm sập server vì tràn RAM).

Kiểm:
- ByteLRU: loại theo BYTE (không theo số mục), cập nhật khoá cũ đúng sổ, mục quá ngân sách không cache,
  sổ byte không lệch khi nhiều luồng dùng cùng lúc (API chạy job trên ThreadPoolExecutor);
- data.load_candles: cửa sổ trả về khớp đúng khung đầy đủ, lần 2 lấy từ cache; không thêm cột compat; ghi lại catalog thì cache tự hết hạn;
- _pool_map_safe: giữ thứ tự; lỗi trong job nổi lên ngay (không chạy lại, không che lỗi);
  worker bị kill -> chỉ chạy lại các job còn thiếu;
- memwatch: RAM dùng được tính cả giới hạn cgroup; script nặng bắt buộc có trần RAM (require_memory_limit);
  planning_budget_mb = min(85% cgroup trống, MemAvailable − dự phòng) (60% MemAvailable khi không có cgroup);
  _auto_workers chia ngân sách đó cho trần mỗi worker, CPU = usable_cpus.
"""
import importlib
import importlib.util
from types import SimpleNamespace
import os
import random
import sys
import threading

import numpy as np
import pandas as pd
import pytest

from data_helpers import save_synthetic

T0 = 1_700_006_400_000
M = 60_000
DAY = 86_400_000
MB = 1024 * 1024


# ─── ByteLRU ────────────────────────────────────────────────────────────────

def test_byte_lru_evicts_least_recently_used_by_bytes():
    from backend.models.storage import ByteLRU
    lru = ByteLRU(1)
    lru.put("a", "A", MB // 2)
    lru.put("b", "B", MB // 2)
    assert len(lru) == 2
    assert lru.get("a") == "A"          # a vừa được dùng -> b là mục cũ nhất
    lru.put("c", "C", MB // 2)
    assert lru.get("b") is None
    assert lru.get("a") == "A" and lru.get("c") == "C"
    assert lru.used == MB


def test_byte_lru_replacing_a_key_keeps_the_byte_ledger_right():
    from backend.models.storage import ByteLRU
    lru = ByteLRU(1)
    lru.put("a", 1, 600_000)
    lru.put("a", 2, 300_000)
    assert len(lru) == 1 and lru.get("a") == 2 and lru.used == 300_000
    lru.put("a", 3, 2 * MB)              # lớn hơn ngân sách: không cache, bản cũ cũng bị bỏ
    assert lru.get("a") is None and lru.used == 0


def test_byte_lru_ledger_stays_consistent_under_threads():
    from backend.models.storage import ByteLRU
    lru = ByteLRU(1)

    def work(seed):
        rng = random.Random(seed)
        for _ in range(3000):
            key = rng.randrange(40)
            if rng.random() < 0.5:
                lru.put(key, key, rng.randrange(1, 120_000))
            elif rng.random() < 0.9:
                lru.get(key)
            else:
                lru.evict(key)

    threads = [threading.Thread(target=work, args=(s,)) for s in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert lru.used == sum(n for _, n in lru._d.values())
    assert 0 <= lru.used <= lru.budget


# ─── data.load_candles ─────────────────────────────────────────────────────

def _series(days, seed=3):
    n = days * 1440
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open_time": T0 + np.arange(n, dtype=np.int64) * M, "open": o,
                         "high": np.maximum(o, c) * 1.0005, "low": np.minimum(o, c) * 0.9995,
                         "close": c, "volume": 10.0})


@pytest.fixture
def one_asset(tmp_path, monkeypatch):
    from backend.data.data import clear_caches
    root = tmp_path / "data"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    save_synthetic(symbol="AAA", output_dir=str(root / "cex"), df_1m_raw=_series(5))
    clear_caches()
    yield root
    clear_caches()


def test_loader_windows_match_full_frame_and_are_cached(one_asset):
    from backend.data import data as D
    windows = ((T0, T0 + DAY), (T0 + DAY + 7 * M, T0 + 3 * DAY - M), (T0 - DAY, T0 + 10 * DAY))
    for frame in ("1m", "15m", "1h"):
        full = D.load_candles("AAA", frame, 0, 2**62)
        for start, end in windows:
            got = D.load_candles("AAA", frame, start, end).reset_index(drop=True)
            expected = full[(full["open_time"] >= start) & (full["open_time"] <= end)].reset_index(drop=True)
            pd.testing.assert_frame_equal(got, expected)
    assert len(D._get_candles_cache()) > 0
    again = D.load_candles("AAA", "1h", T0, T0 + DAY)
    assert D.load_candles("AAA", "1h", T0, T0 + DAY) is again       # lần 2 lấy từ cache


def test_loader_returns_only_engine_columns(one_asset):
    from backend.data.data import load_candles
    cols = set(load_candles("AAA", "1m", T0, T0 + DAY).columns)
    assert {"open_time", "open", "high", "low", "close", "volume", "is_filled"} <= cols
    assert not cols & {"symbol", "timestamp", "close_time", "is_close"}


def test_loader_cache_expires_when_catalog_is_rewritten(one_asset):
    from backend.data.data import load_candles
    before = load_candles("AAA", "1m", T0, T0 + DAY)["close"].to_numpy().copy()
    df = _series(5)
    df[["open", "high", "low", "close"]] *= 2
    save_synthetic(symbol="AAA", output_dir=str(one_asset / "cex"), df_1m_raw=df)    # ghi lại catalog: digest đổi -> cache hết hạn
    after = load_candles("AAA", "1m", T0, T0 + DAY)["close"].to_numpy()
    np.testing.assert_allclose(after, before * 2)


# ─── _pool_map_safe ─────────────────────────────────────────────────────────

def _load_book_script():
    """Bộ pool/worker dùng chung của job (backend/jobs/workers.py): thay cho script dựng sổ cũ; `_pool_map_safe` / `_auto_workers` là tên cũ."""
    from backend.jobs import workers
    return SimpleNamespace(_pool_map_safe=workers.pool_map_safe, _auto_workers=workers.auto_workers)


def _square(x):
    return x * x


def _fail_on_three(x):
    if x == 3:
        raise ValueError("lỗi thật trong job")
    return x


def _killed_once(arg):
    x, flag = arg
    if x == 2 and not os.path.exists(flag):
        open(flag, "w").close()
        os._exit(1)                      # mô phỏng worker bị OOM-kill
    return x * 10


def test_pool_map_safe_keeps_job_order():
    book = _load_book_script()
    assert book._pool_map_safe(_square, list(range(12)), 3, "t") == [x * x for x in range(12)]


def test_pool_map_safe_surfaces_job_errors_without_retrying(capsys):
    book = _load_book_script()
    with pytest.raises(ValueError, match="lỗi thật"):
        book._pool_map_safe(_fail_on_three, list(range(6)), 2, "t")
    assert "[WARN]" not in capsys.readouterr().out


def test_pool_map_safe_reruns_only_missing_jobs_after_worker_kill(tmp_path, capsys):
    book = _load_book_script()
    flag = str(tmp_path / "killed")
    jobs = [(x, flag) for x in range(6)]
    assert book._pool_map_safe(_killed_once, jobs, 2, "t") == [x * 10 for x in range(6)]
    assert "[WARN]" in capsys.readouterr().out


# ─── memwatch ───────────────────────────────────────────────────────────────

def test_peak_rss_is_at_least_current_rss():
    from backend.jobs import workers as memwatch
    if not os.path.exists("/proc/self/status"):
        pytest.skip("cần Linux /proc")
    assert memwatch.peak_rss_mb() >= memwatch.rss_mb() > 0


# ─── trần RAM bắt buộc + cỡ pool theo cgroup ─────────────────────────────────

def test_require_memory_limit_refuses_without_cap(monkeypatch):
    from backend.jobs import workers as memwatch
    monkeypatch.setattr(memwatch, "cgroup_limit_mb", lambda: None)
    monkeypatch.delenv("NORA_ALLOW_UNLIMITED", raising=False)
    with pytest.raises(SystemExit, match="run_limited.sh"):
        memwatch.require_memory_limit("build_strategy_book")
    monkeypatch.setenv("NORA_ALLOW_UNLIMITED", "0")
    with pytest.raises(SystemExit):
        memwatch.require_memory_limit("build_strategy_book")


def test_require_memory_limit_allows_explicit_unlimited(monkeypatch):
    from backend.jobs import workers as memwatch
    monkeypatch.setattr(memwatch, "cgroup_limit_mb", lambda: None)
    monkeypatch.setenv("NORA_ALLOW_UNLIMITED", "1")
    memwatch.require_memory_limit("build_strategy_book")  # không raise


def test_require_memory_limit_returns_the_cap(monkeypatch):
    from backend.jobs import workers as memwatch
    monkeypatch.setattr(memwatch, "cgroup_limit_mb", lambda: 8192.0)
    monkeypatch.delenv("NORA_ALLOW_UNLIMITED", raising=False)
    assert memwatch.require_memory_limit("build_strategy_book") == 8192.0


def _patch_mem(monkeypatch, cgroup_free, host, reserve="8000"):
    from backend.jobs import workers as memwatch
    monkeypatch.setattr(memwatch, "cgroup_free_mb", lambda: cgroup_free)
    monkeypatch.setattr(memwatch, "mem_available_mb", lambda: host)
    if reserve is None:
        monkeypatch.delenv("NORA_HOST_RESERVE_MB", raising=False)
    else:
        monkeypatch.setenv("NORA_HOST_RESERVE_MB", reserve)
    return memwatch


def test_planning_budget_cgroup_limited(monkeypatch):
    memwatch = _patch_mem(monkeypatch, 10_000.0, 30_000.0)
    assert memwatch.planning_budget_mb() == pytest.approx(8_500.0)   # min(10000*0.85, 30000-8000)


def test_planning_budget_backs_off_when_host_busy(monkeypatch):
    memwatch = _patch_mem(monkeypatch, 10_000.0, 12_000.0)
    assert memwatch.planning_budget_mb() == pytest.approx(4_000.0)   # min(8500, 12000-8000)


def test_planning_budget_without_cgroup_uses_60pct_of_host(monkeypatch):
    memwatch = _patch_mem(monkeypatch, None, 20_000.0)
    assert memwatch.planning_budget_mb() == pytest.approx(12_000.0)


def test_planning_budget_clamps_negative_to_zero(monkeypatch):
    memwatch = _patch_mem(monkeypatch, 10_000.0, 5_000.0)             # máy còn ít hơn phần dự phòng
    assert memwatch.planning_budget_mb() == 0.0
    memwatch = _patch_mem(monkeypatch, 0.0, 30_000.0)                 # cgroup hết chỗ
    assert memwatch.planning_budget_mb() == 0.0


def test_planning_budget_reserve_from_env_default_8000(monkeypatch):
    memwatch = _patch_mem(monkeypatch, 10_000.0, 12_000.0, reserve="2000")
    assert memwatch.planning_budget_mb() == pytest.approx(8_500.0)   # min(8500, 10000)
    memwatch = _patch_mem(monkeypatch, 10_000.0, 12_000.0, reserve=None)
    assert memwatch.planning_budget_mb() == pytest.approx(4_000.0)   # mặc định 8000


def test_check_memory_gate_uses_planning_budget(monkeypatch):
    memwatch = _patch_mem(monkeypatch, 10_000.0, 12_000.0)           # ngân sách 4000
    memwatch.check_memory_gate(3_000, "x")                            # không raise
    with pytest.raises(RuntimeError, match="NORA_HOST_RESERVE_MB"):
        memwatch.check_memory_gate(5_000, "x")


def test_auto_workers_trusts_cgroup_when_limited(monkeypatch):
    book = _load_book_script()
    memwatch = _patch_mem(monkeypatch, 8192.0, 60_000.0)
    monkeypatch.setattr(memwatch, "usable_cpus", lambda: 16)
    assert book._auto_workers(2000) == 3        # min(8192*0.85, 52000) / 2000 = 3.48


def test_auto_workers_uses_mem_available_when_unlimited(monkeypatch):
    book = _load_book_script()
    memwatch = _patch_mem(monkeypatch, None, 20_000.0)
    monkeypatch.setattr(memwatch, "usable_cpus", lambda: 16)
    assert book._auto_workers(2000) == 6        # 20000 * 0.6 / 2000
    monkeypatch.setattr(memwatch, "usable_cpus", lambda: 4)
    assert book._auto_workers(2000) == 4        # bị chặn bởi số CPU (không còn trừ 2)


def test_auto_workers_backs_off_when_host_busy(monkeypatch):
    book = _load_book_script()
    memwatch = _patch_mem(monkeypatch, 10_000.0, 12_000.0)           # ngân sách 4000
    monkeypatch.setattr(memwatch, "usable_cpus", lambda: 6)
    assert book._auto_workers(2000) == 2


def test_worker_init_never_raises():
    from backend.jobs import workers as memwatch
    memwatch.worker_init()
