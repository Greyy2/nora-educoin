"""B7: job edu_precompute (core/backtest/edu_precompute.py) + API /api/studio/education/*."""
import json
import os

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.jobs import batch as batch_jobs
from backend.api.routers import education as edu_router
from backend.core.backtest import edu_precompute as edu
from backend.core.strategy.pydsl.weights import TOP10

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "binance_hist"))
HAVE_DATA = all(os.path.isfile(os.path.join(ROOT, "cex", s, "24h.pkl")) for s in TOP10)


def test_job_kind_registered_and_params_validated():
    assert batch_jobs.KINDS["edu_precompute"]["module"] == "backend.core.backtest.edu_precompute"
    assert batch_jobs.build_job("edu_precompute", {}) == {}
    assert batch_jobs.build_job("edu_precompute", {"only": ["trend_kema_breakout"]}) == {"only": ["trend_kema_breakout"]}
    with pytest.raises(batch_jobs.JobError):
        batch_jobs.build_job("edu_precompute", {"only": ["không_có"]})
    with pytest.raises(batch_jobs.JobError):
        batch_jobs.build_job("edu_precompute", {"start": "2024-01-01"})


def test_downsample_keeps_ends_and_alignment():
    n = 1000
    s = {"times": list(range(n)), "equity": [float(i) for i in range(n)], "drawdown": [0.0] * n, "stage_split": 5,
         "benchmark": {"times": list(range(n)), "equity": [1.0] * n, "label": "x"}}
    out = edu.downsample_series(s, 100)
    assert len(out["times"]) == len(out["equity"]) == len(out["benchmark"]["equity"]) <= 100
    assert out["times"][0] == 0 and out["times"][-1] == n - 1 and out["stage_split"] == 5 and out["downsampled_from"] == n
    assert out["equity"] == [float(t) for t in out["times"]]


def test_samples_json_matches_education_profiles():
    rows = edu.load_samples()
    assert len(rows) == 50 and len({r["key"] for r in rows}) == 50
    assert all(r["profile"] in ("xno", "nora") for r in rows)


def test_api_reads_results_and_rejects_bad_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(edu_router, "RESULTS_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(edu_router.router)
    c = TestClient(app)
    assert c.get("/api/studio/education/results").status_code == 404
    (tmp_path / "index.json").write_text(json.dumps({"count": 1, "items": [{"key": "a_b"}]}))
    (tmp_path / "a_b.json").write_text(json.dumps({"key": "a_b"}))
    assert c.get("/api/studio/education/results").json()["count"] == 1
    assert c.get("/api/studio/education/results/a_b").json() == {"key": "a_b"}
    assert c.get("/api/studio/education/results/nope").status_code == 404
    assert c.get("/api/studio/education/results/..%2Findex").status_code == 404


@pytest.mark.skipif(not HAVE_DATA, reason="chưa có data/binance_hist")
def test_run_job_real_sample_writes_result_and_index(tmp_path, monkeypatch):
    monkeypatch.setattr(edu, "RESULTS_DIR", str(tmp_path))
    monkeypatch.delenv("NORA_JOB_DIR", raising=False)
    res = edu.run_job({"only": ["trend_kema_breakout"]})
    assert res["ok"] == 1 and res["failed"] == 0
    rec = json.load(open(tmp_path / "trend_kema_breakout.json"))
    for k in ("key", "program_hash", "config", "data", "git_commit", "generated_at", "metrics", "diagnostics", "insights", "series", "explain"):
        assert k in rec
    assert rec["data"]["sha256_1m"]["BTC"] and rec["series"]["downsampled_from"] > len(rec["series"]["times"])
    assert rec["diagnostics"]["market_comparison"]["available"] and "benchmark" in rec["series"]
    idx = json.load(open(tmp_path / "index.json"))
    assert idx["count"] == 1 and idx["items"][0]["status"] == "ok"
    assert (idx["start"], idx["end"], idx["train_ratio"], idx["initial_capital"]) == ("2019-12-31", "2024-12-31", 0.7, 100000.0)   # trang Education đọc cửa sổ mặc định từ đây
    assert rec["config"]["start"] == idx["start"] and all(y["days"] >= 2 for y in rec["yearly"])
    assert np.isfinite(idx["items"][0]["final_equity"])
