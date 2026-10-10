"""P15-A: tín hiệu của backend.core.strategy.evaluate_signals == backend-no (cũ) từng bit, trên 10 mẫu giáo dục × BTC, ETH, cửa sổ 2024-01-01..2024-07-01.
Hai phía chạy trong tiến trình con riêng (cũ: PYTHONPATH chỉ có thư mục tạm với symlink backend -> test/backend-no) để không đụng tên gói `backend`."""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLD = os.path.join(ROOT, "test", "backend-no")
WORKER = os.path.join(ROOT, "test", "_strategy_signal_worker.py")
MARKET = os.path.join(ROOT, "data", "market", "okx", "cex")
SYMBOLS = ["BTC", "ETH"]


def _ms(s: str) -> int:
    return int(datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def _run(pythonpath: str, module: str, cfg: str, out: str) -> None:
    env = {**os.environ, "PYTHONPATH": pythonpath, "PYTHONDONTWRITEBYTECODE": "1", "NUMBA_CACHE_DIR": os.path.join(os.path.dirname(out), "numba"),
           "NORA_ALLOW_UNLIMITED": "1"}
    for k in ("NORA_LOCAL_DATA_ROOT", "NORA_DATA_ROOT"):
        env.pop(k, None)
    r = subprocess.run([sys.executable, WORKER, module, cfg, out], cwd=tempfile.gettempdir(), env=env, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-3000:]


@pytest.mark.skipif(not os.path.isdir(os.path.join(MARKET, "BTC", "perp")), reason="thiếu dữ liệu nến BTC/ETH")
def test_evaluate_signals_bit_identical_to_old():
    from backend.crawl.store import load_samples
    samples = [{"key": s["key"], "code": s["code"]} for s in load_samples(os.path.join(ROOT, "data", "alpha", "education", "samples.json"))[:10]]
    assert len(samples) == 10
    with tempfile.TemporaryDirectory() as tmp:
        shim = os.path.join(tmp, "old")
        os.makedirs(shim)
        os.symlink(OLD, os.path.join(shim, "backend"))
        cfg = os.path.join(tmp, "cfg.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({"samples": samples, "symbols": SYMBOLS, "start": _ms("2024-01-01"), "end": _ms("2024-07-01"),
                       "warm_ms": 120 * 86_400_000, "root": MARKET}, fh)
        old_out, new_out = os.path.join(tmp, "old.npz"), os.path.join(tmp, "new.npz")
        _run(shim, "backend.core.backtest", cfg, old_out)
        _run(ROOT, "backend.core.strategy", cfg, new_out)
        old, new = np.load(old_out), np.load(new_out)
        assert sorted(old.files) == sorted(new.files)
        assert not [f for f in old.files if f.endswith("|error")], [str(old[f]) for f in old.files if f.endswith("|error")]
        assert sum(old[f].size for f in old.files if f.endswith("|match")) > 0
        assert any(f.endswith("|match") for f in old.files), "không mẫu nào tính được tín hiệu"
        for k in old.files:
            a, b = old[k], new[k]
            assert a.shape == b.shape and a.dtype == b.dtype, k
            if a.dtype.kind in "fc":
                assert np.array_equal(a, b, equal_nan=True), k
            else:
                assert np.array_equal(a, b), k
