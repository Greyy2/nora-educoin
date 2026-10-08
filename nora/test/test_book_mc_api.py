"""POST /api/studio/book/mc: trùng số với run_monte_carlo_daily (cùng seed), fan/histogram/gate, giới hạn đầu vào, nguồn từ job WFA."""
import json
import os
import time

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import optimize
from backend.optimize.process import process as batch_jobs
from backend.carlo.carlo import run_monte_carlo_daily, run_monte_carlo_daily_detail

DAILY = list(np.random.default_rng(11).normal(0.0012, 0.012, 150))


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / "data"))
    app = FastAPI()
    app.include_router(optimize.book_router)
    return TestClient(app)


@pytest.mark.parametrize("scale,block,horizon", [(1.0, 5, 365), (0.5, 3, 100), (2.0, 7, 60), (1.0, 1, 30)])
def test_detail_summary_is_bit_identical_to_run_monte_carlo_daily(scale, block, horizon):
    ref = run_monte_carlo_daily(DAILY, simulations=400, block_days=block, horizon_days=horizon, ruin_threshold_pct=20.0, seed=3, scale=scale)
    d = run_monte_carlo_daily_detail(DAILY, simulations=400, block_days=block, horizon_days=horizon, ruin_threshold_pct=20.0, seed=3,
                                     scale=scale)
    assert d["summary"] == ref


def test_detail_shapes_and_consistency():
    d = run_monte_carlo_daily_detail(DAILY, simulations=500, horizon_days=365, seed=2)
    fan = d["fan"]
    assert fan["days"][0] == 0 and fan["days"][-1] == 365 and fan["days"][1] == 5 and len(fan["days"]) == 74
    for k in ("p5", "p25", "p50", "p75", "p95"):
        assert len(fan[k]) == len(fan["days"]) and fan[k][0] == 0.0
    for a, b in zip(("p5", "p25", "p50", "p75"), ("p25", "p50", "p75", "p95")):
        assert all(x <= y for x, y in zip(fan[a], fan[b]))                      # phân vị không đảo thứ tự
    assert fan["p50"][-1] == pytest.approx(d["summary"]["median_ret_pct"], abs=0.06)   # lãi cuối ngày 365 = lãi cuối của mô phỏng
    assert fan["p5"][-1] == pytest.approx(d["summary"]["p05_ret_pct"], abs=0.06)
    for h in ("mdd_hist", "ret_hist"):
        bins = d[h]["bins"]
        assert len(bins) == 20 and sum(b["count"] for b in bins) == 500 and all(b["lo"] <= b["hi"] for b in bins)
    assert d["mdd_hist"]["bins"][0]["lo"] >= 0
    g = d["gate"]
    assert g["ruin_max_pct"] == 5.0 and g["gate_eligible"] is False and g["passed"] is False       # 500 < 10.000 kịch bản: không đủ làm gate
    assert g["checks"]["ruin"]["passed"] == (d["summary"]["p_mdd_ge_ruin_pct"] <= 5.0)
    assert d["params"]["seed"] == 2 and d["params"]["n_days"] == 150
    json.dumps(d, allow_nan=False)
    with pytest.raises(ValueError):
        run_monte_carlo_daily_detail([])


def test_detail_horizon_not_multiple_of_step_keeps_last_day():
    d = run_monte_carlo_daily_detail(DAILY, simulations=100, horizon_days=33, seed=1)
    assert d["fan"]["days"] == [0, 5, 10, 15, 20, 25, 30, 33]


def test_endpoint_matches_run_monte_carlo_daily(client):
    body = {"daily_returns": DAILY, "simulations": 500, "block_days": 5, "horizon_days": 200, "ruin_threshold_pct": 25, "seed": 7,
            "scale": 1.5, "mode": "advanced"}
    r = client.post("/api/studio/book/mc", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    ref = run_monte_carlo_daily(DAILY, simulations=500, block_days=5, horizon_days=200, ruin_threshold_pct=25.0, seed=7, scale=1.5)
    assert out["summary"] == ref
    assert set(out) == {"summary", "fan", "mdd_hist", "ret_hist", "stress", "worst_path", "gate", "params"}
    assert out["gate"]["ruin_max_pct"] == 5.0 and out["params"]["source"] == {"kind": "daily_returns"}


def test_endpoint_defaults_use_contract_values(client):
    out = client.post("/api/studio/book/mc", json={"daily_returns": DAILY}).json()
    assert out["params"]["simulations"] == 10_000 and out["params"]["block_days"] == 5 and out["params"]["horizon_days"] == 365
    assert out["params"]["ruin_threshold_pct"] == 30.0 and out["params"]["seed"] == 7
    assert out["summary"] == run_monte_carlo_daily(DAILY, simulations=10_000, seed=7)
    assert out["gate"]["gate_eligible"] is True


@pytest.mark.parametrize("patch", [
    {"simulations": 50_001}, {"simulations": 5}, {"horizon_days": 731}, {"horizon_days": 1}, {"block_days": 0}, {"block_days": 31},
    {"ruin_threshold_pct": 0}, {"ruin_threshold_pct": 101}, {"scale": 0}, {"scale": 11}, {"stress_max_mdd_pct": 0}, {"extra_cost_daily_pct": -1}, {"basis": "mid"}, {"seed": -1},
    {"daily_returns": [0.01] * 5},                     # quá ít ngày
    {"daily_returns": [0.01] * 19 + [-1.0]},           # lỗ 100%
    {"daily_returns": [0.01] * 19 + [float("nan")]},
])
def test_endpoint_rejects_bad_limits(client, patch):
    body = {"daily_returns": DAILY, **patch}
    r = client.post("/api/studio/book/mc", content=json.dumps(body), headers={"content-type": "application/json"})
    assert r.status_code == 422, (patch, r.text)


def test_endpoint_needs_exactly_one_source(client):
    assert client.post("/api/studio/book/mc", json={}).status_code == 422
    assert client.post("/api/studio/book/mc", json={"daily_returns": DAILY, "wfa_job_id": "20260101_000000_ffffff"}).status_code == 422


def _wfa_job(result, kind="book_wfa", name="20260101_000000_a1b2c3", ok=True):
    d = os.path.join(batch_jobs.jobs_root(), name)
    os.makedirs(d, exist_ok=True)
    batch_jobs._write_meta(d, {"id": name, "kind": kind, "params": {}, "pid": 2 ** 22 + 9, "created": 1.0, "started": None,
                               "finished": None, "state": "running", "exit_code": None})
    open(os.path.join(d, "out.log"), "w").write(f"[run_limited] peak RAM 1 MB / limit x | exit {0 if ok else 1}\n")
    if result is not None:
        json.dump(result, open(os.path.join(d, "result.json"), "w"))
    return name


def test_endpoint_from_wfa_job_uses_chosen_basis(client):
    lv, ex = DAILY, [x * 0.5 for x in DAILY]
    jid = _wfa_job({"summary": {"oos_daily": {"level": lv, "extreme": ex}}})
    for basis, series in (("level", lv), ("extreme", ex)):
        r = client.post("/api/studio/book/mc", json={"wfa_job_id": jid, "basis": basis, "simulations": 300, "seed": 4, "mode": "advanced"})
        assert r.status_code == 200, r.text
        assert r.json()["summary"] == run_monte_carlo_daily(series, simulations=300, seed=4)
        assert r.json()["params"]["source"] == {"kind": "wfa", "job_id": jid, "basis": basis}
    assert client.post("/api/studio/book/mc", json={"wfa_job_id": "20260101_000009_ffffff"}).status_code == 404
    assert client.post("/api/studio/book/mc", json={"wfa_job_id": "bad"}).status_code == 422
    bt = _wfa_job({"x": 1}, kind="book_backtest", name="20260101_000001_a1b2c3")
    assert client.post("/api/studio/book/mc", json={"wfa_job_id": bt}).status_code == 422
    failed = _wfa_job(None, name="20260101_000002_a1b2c3", ok=False)
    assert client.post("/api/studio/book/mc", json={"wfa_job_id": failed}).status_code == 409
    short = _wfa_job({"summary": {"oos_daily": {"extreme": [0.01] * 5}}}, name="20260101_000003_a1b2c3")
    assert client.post("/api/studio/book/mc", json={"wfa_job_id": short}).status_code == 422


def test_endpoint_is_fast_at_max_size(client):
    t0 = time.time()
    r = client.post("/api/studio/book/mc", json={"daily_returns": DAILY, "simulations": 50_000, "horizon_days": 730, "block_days": 5, "mode": "advanced"})
    assert r.status_code == 200 and time.time() - t0 < 60
