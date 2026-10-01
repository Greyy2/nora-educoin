"""
test_gate_integration.py — Đợt 4.1: Gắn Data Quality Gate vào Studio, WFA và Research

Quy tắc: Viết test trước, chạy thấy FAIL, sau đó sửa code để PASS.

Kiểm tra:
1. Thiếu manifest.json:
   - Studio /simulate trả 422
   - WFA execute_wfa_pipeline đánh dấu job failed
   - analyze_market trả verdict DATA_BLOCKED
2. manifest.json có synthetic=True:
   - Studio /simulate trả 422
   - WFA execute_wfa_pipeline đánh dấu job failed
   - analyze_market trả verdict DATA_BLOCKED
3. Dữ liệu sạch (manifest synthetic=False, crawl_ok=True, coverage >= 30 ngày):
   - WFA hoàn thành completed / Studio chấp nhận
"""
import os
import json
import tempfile
import pandas as pd
import numpy as np
import pytest
from fastapi.exceptions import HTTPException

from backend.core.contracts import StrategySnapshot, WfaFoldConfig
from backend.api.jobs.store import create_wfa_job, get_wfa_job, init_db
from backend.wfa.walk_forward import execute_wfa_pipeline
from backend.api.routers.studio import run_simulation, SimulateRequest
from backend.core.research.market_analyzer import analyze_market


def _make_dummy_dataset(target_dir: str, n_days: int = 35, synthetic: bool = False, omit_manifest: bool = False):
    """Tạo bộ dữ liệu 1m và 4h trong target_dir."""
    os.makedirs(target_dir, exist_ok=True)
    n = n_days * 1440
    t0 = 1700000000000
    times = [t0 + i * 60_000 for i in range(n)]
    prices = list(np.random.default_rng(42).lognormal(0, 0.0005, size=n).cumprod() * 100)
    df_1m = pd.DataFrame({
        "open_time": times,
        "open": prices, "high": [p * 1.001 for p in prices],
        "low": [p * 0.999 for p in prices],
        "close": prices, "volume": [10.0] * n,
    })
    df_1m.to_pickle(os.path.join(target_dir, "1m.pkl"))
    df_1m.iloc[::240].to_pickle(os.path.join(target_dir, "4h.pkl"))

    if not omit_manifest:
        from backend.core.data.resampler import compute_df_sha256
        with open(os.path.join(target_dir, "manifest.json"), "w") as f:
            json.dump({
                "source": "test",
                "synthetic": synthetic,
                "crawl_ok": True,
                "coverage_days": float(n_days),
                "filled_ratio_1m": 0.0,
                "start_ts": t0,
                "end_ts": times[-1],
                "rows": {"1m": n, "4h": len(df_1m.iloc[::240])},
                "sha256_1m": compute_df_sha256(df_1m),
            }, f)


VALID_FLOW = {
    "id": "flow1",
    "type": "LONG",
    "ast": {
        "type": "LONG",
        "match": [{
            "condition": [
                [[{"frame": "1m", "column": "close"}, ">", {"frame": "1m", "column": "open"}]]
            ]
        }],
        "stop": [{
            "condition": [
                [[{"frame": "1m", "column": "close"}, "<", {"frame": "1m", "column": "open"}]]
            ]
        }],
    }
}


# ─── Test 1: Studio /simulate trả 422 khi thiếu manifest hoặc synthetic ────────

def test_simulate_blocked_without_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        sym = "NOMANIFEST"
        _make_dummy_dataset(os.path.join(tmp, sym), n_days=35, omit_manifest=True)
        os.environ["NORA_LOCAL_DATA_ROOT"] = tmp

        req = SimulateRequest(
            symbol=sym,
            start_ts=1700000000000,
            end_ts=1700000000000 + 86400000 * 30,
            flows=[VALID_FLOW],
        )
        with pytest.raises(HTTPException) as exc_info:
            run_simulation(req)
        assert exc_info.value.status_code == 422
        assert "quality gate" in str(exc_info.value.detail).lower()


def test_simulate_blocked_synthetic():
    with tempfile.TemporaryDirectory() as tmp:
        sym = "SYNTH"
        _make_dummy_dataset(os.path.join(tmp, sym), n_days=35, synthetic=True)
        os.environ["NORA_LOCAL_DATA_ROOT"] = tmp

        req = SimulateRequest(
            symbol=sym,
            start_ts=1700000000000,
            end_ts=1700000000000 + 86400000 * 30,
            flows=[VALID_FLOW],
        )
        with pytest.raises(HTTPException) as exc_info:
            run_simulation(req)
        assert exc_info.value.status_code == 422
        assert "quality gate" in str(exc_info.value.detail).lower()


# ─── Test 2: WFA fail khi thiếu manifest hoặc synthetic ───────────────────────

def test_wfa_fails_without_manifest():
    init_db()
    with tempfile.TemporaryDirectory() as tmp:
        sym = "WFA_NOMANIFEST"
        _make_dummy_dataset(os.path.join(tmp, sym), n_days=35, omit_manifest=True)
        os.environ["NORA_LOCAL_DATA_ROOT"] = tmp

        snapshot = StrategySnapshot(
            name="Gate Test",
            symbol=sym,
            flows=[{"id": "f1", "type": "LONG", "ast": {"type": "LONG", "nodes": []}}],
        )
        cfg = WfaFoldConfig(train_days=10, test_days=5, fold_count=3)
        job_id = create_wfa_job(sym, "Gate Test", 3)
        execute_wfa_pipeline(job_id, snapshot, cfg, "handle")

        job = get_wfa_job(job_id)
        assert job.get("status") == "failed"
        assert "quality gate" in str(job.get("error")).lower() or "manifest" in str(job.get("error")).lower()


def test_wfa_fails_synthetic():
    init_db()
    with tempfile.TemporaryDirectory() as tmp:
        sym = "WFA_SYNTH"
        _make_dummy_dataset(os.path.join(tmp, sym), n_days=35, synthetic=True)
        os.environ["NORA_LOCAL_DATA_ROOT"] = tmp

        snapshot = StrategySnapshot(
            name="Gate Test",
            symbol=sym,
            flows=[{"id": "f1", "type": "LONG", "ast": {"type": "LONG", "nodes": []}}],
        )
        cfg = WfaFoldConfig(train_days=10, test_days=5, fold_count=3)
        job_id = create_wfa_job(sym, "Gate Test", 3)
        execute_wfa_pipeline(job_id, snapshot, cfg, "handle")

        job = get_wfa_job(job_id)
        assert job.get("status") == "failed"
        assert "quality gate" in str(job.get("error")).lower() or "nhân tạo" in str(job.get("error")).lower()


# ─── Test 3: analyze_market trả verdict DATA_BLOCKED ──────────────────────────

def test_analyze_market_blocked_when_gate_fails():
    with tempfile.TemporaryDirectory() as tmp:
        sym = "RES_BLOCKED"
        _make_dummy_dataset(os.path.join(tmp, sym), n_days=35, synthetic=True)
        res = analyze_market(sym, data_root=tmp, force_refresh=True)
        assert res.get("verdict") == "DATA_BLOCKED"
        assert "backtest_simulation" not in res or not res.get("backtest_simulation", {}).get("total_trades", 0)
