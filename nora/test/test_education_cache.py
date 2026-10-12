"""Cache kết quả thật của mẫu giáo dục: khoá đổi theo mã/khung, get/put khứ hồi, endpoint 404 NOT_READY khi chưa có cache (không số dựng sẵn)."""
import json
import os

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend import strategies as sample_cache
from backend.routes import alpha as alpha_routes

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "alpha", "education", "samples.json")
SPEC = {"symbols": ["BTC@perp"], "start": "2024-01-01", "end": "2024-03-01", "train_ratio": 0.7, "initial_capital": 10000.0, "run_frame": ""}


def _sample():
    with open(SAMPLES, encoding="utf-8") as fh:
        s = json.load(fh)[0]
    return s


@pytest.fixture
def cache_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("NORA_ALPHAS_DIR", str(tmp_path / "alpha"))
    return tmp_path


def test_key_changes_with_code_and_frame():
    code = _sample()["code"]
    k = sample_cache.sample_cache_key(code, SPEC)
    assert k == sample_cache.sample_cache_key(code, dict(SPEC))
    assert k != sample_cache.sample_cache_key(code, {**SPEC, "run_frame": "1m"})
    assert k != sample_cache.sample_cache_key(code, {**SPEC, "end": "2024-04-01"})
    # mẫu khác (logic khác) -> hash chương trình khác -> khoá khác
    alt = _sample()
    for s in json.load(open(SAMPLES, encoding="utf-8"))[1:]:
        if s["code"] != code:
            alt = s
            break
    assert k != sample_cache.sample_cache_key(alt["code"], SPEC)


def test_get_put_roundtrip(cache_dir):
    key = "a" * 64
    assert sample_cache.sample_get(key) is None
    sample_cache.sample_put(key, {"metrics": {"x": 1}, "final_equity": 1.5})
    assert sample_cache.sample_get(key) == {"metrics": {"x": 1}, "final_equity": 1.5}
    assert os.path.exists(cache_dir / "alpha" / "education" / "results" / f"{key}.json")
    assert sample_cache.sample_get("không-hợp-lệ") is None


def test_endpoint_not_ready_without_cache(cache_dir, monkeypatch):
    s = _sample()
    monkeypatch.setattr(alpha_routes, "_load_samples", lambda: [s])
    monkeypatch.setattr(sample_cache, "sample_run_spec", lambda sample, defaults=None: dict(SPEC))
    c = TestClient(app)
    r = c.get(f"/api/studio/education/samples/{s['key']}/result")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "NOT_READY"
    lst = c.get("/api/studio/education/samples").json()
    assert lst[0]["result_status"] == "NOT_READY" and "metrics" not in lst[0] and "final_equity" not in lst[0]
    # có cache thật -> trả đúng nội dung cache
    key = sample_cache.sample_cache_key(s["code"], SPEC)
    sample_cache.sample_put(key, {"metrics": {"m": 1}, "final_equity": 11000.0, "config": {"initial_capital": 10000.0}})
    assert c.get(f"/api/studio/education/samples/{s['key']}/result").json()["final_equity"] == 11000.0
    lst = c.get("/api/studio/education/samples").json()
    assert lst[0]["pnl_usd"] == 1000.0 and "result_status" not in lst[0]
