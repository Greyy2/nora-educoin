"""Bộ chọn tab Tuỳ chỉnh: MỘT resolve_strategy cho backtest và bot; hash cấu hình; fingerprint khớp."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import live as live_routes
from backend.jobs import tasks

SYM = ["BTC-USDT-SWAP"]
ROWS = [{"id": "dca_short", "timeframe": "1h", "signal_tf": "1h", "backtested_at": 1, "symbols": ["BTC"]}]


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NORA_ALPHAS_DIR", str(tmp_path))
    monkeypatch.setattr("backend.alpha.strategies.live_candidates", lambda *a, **k: ROWS)
    monkeypatch.setattr("backend.data.data.run_defaults", lambda: {"start": "2025-01-01", "end": "2025-02-01"})
    monkeypatch.setattr("backend.jobs.runner.status", lambda jid: {"status": "done"})
    app = FastAPI()
    app.include_router(live_routes.router)
    return TestClient(app)


def _bt(client, monkeypatch, params):
    seen = {}
    monkeypatch.setattr(live_routes, "launch", lambda kind, p: seen.update(kind=kind, p=p) or "jobX")
    r = client.post("/api/studio/live/candidate_backtest", json={"alpha_id": "dca_short", "signal_tf": "1h", "symbols": SYM, "params": params})
    return r, seen


def test_unknown_and_out_of_range_params_400(client, monkeypatch):
    r, _ = _bt(client, monkeypatch, {"nope": 1})
    assert r.status_code == 400 and "nope" in r.json()["detail"]
    r, _ = _bt(client, monkeypatch, {"take_profit_rate": 99})
    assert r.status_code == 400 and "take_profit_rate" in r.json()["detail"]


def test_backtest_uses_resolved_params_and_launch_must_match(client, monkeypatch):
    r, seen = _bt(client, monkeypatch, {"take_profit_rate": 2.5})
    assert r.status_code == 200 and seen["kind"] == "book_backtest"
    assert seen["p"]["strategies"][0]["params"]["take_profit_rate"] == 2.5
    launched = {}
    monkeypatch.setattr(live_routes, "launch", lambda kind, p: launched.update(p) or "jobL")
    body = {"mode": "paper", "alpha_id": "dca_short", "signal_tf": "1h", "symbols": SYM, "from_picker": True, "backtest_job_id": "jobX", "params": {"take_profit_rate": 2.5}}
    assert client.post("/api/studio/live/bot", json=body).status_code == 200 and launched["params"] == {"take_profit_rate": 2.5}
    r = client.post("/api/studio/live/bot", json={**body, "params": {"take_profit_rate": 3.0}})
    assert r.status_code == 400 and "Cấu hình khác lần backtest" in r.json()["detail"]
    r = client.post("/api/studio/live/bot", json={**body, "symbols": ["ETH-USDT-SWAP"]})
    assert r.status_code == 400 and "Cấu hình khác" in r.json()["detail"]


def test_fingerprint_custom_match_and_mismatch(client, monkeypatch):
    _bt(client, monkeypatch, {"take_profit_rate": 2.5})
    p = {"alpha_id": "dca_short", "signal_tf": "1h", "symbols": SYM, "base_frame": "1h", "backtest_job_id": "jobX", "params": {"take_profit_rate": 2.5}}
    src = tasks.resolve_live_source(p)
    assert src["strategies"][0]["position"]["take_profit_rate"] == 2.5
    assert tasks.launch_fingerprint(p, src)["fingerprint_match"] is True
    other = tasks.resolve_live_source({**p, "params": {"take_profit_rate": 1.0}})
    assert tasks.launch_fingerprint(p, other)["fingerprint_match"] is False


def test_fingerprint_default_match():
    p = {"alpha_id": "dca_short", "signal_tf": "1h", "symbols": SYM, "base_frame": "1h"}
    assert tasks.launch_fingerprint(p, tasks.resolve_live_source(p))["fingerprint_match"] is True


def test_schema_endpoint(client):
    j = client.get("/api/studio/live/candidate_schema", params={"alpha_id": "dca_short", "signal_tf": "1h"}).json()
    assert j["kind"] == "system" and "take_profit_rate" in j["fields"] and "take_profit_rate" in j["defaults"]


@pytest.fixture
def real_books(monkeypatch):
    """Sổ thật của dự án (chỉ đọc): data/alpha/book.json + explore/book.json."""
    import os
    from backend.alpha import strategies as sb
    real = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "alpha")
    if not os.path.isfile(os.path.join(real, "book.json")):
        pytest.skip("không có data/alpha/book.json")
    monkeypatch.setenv("NORA_ALPHAS_DIR", real)
    sb._CAND_CACHE["sig"] = None
    yield
    sb._CAND_CACHE["sig"] = None


def test_default_is_exactly_stored_leg_for_every_candidate(real_books):
    """Mặc định = ĐÚNG bộ tham số đã backtest của chân (sau lift) + fingerprint khớp, mọi dòng bộ chọn hệ thống."""
    from backend.alpha import strategies as sb
    rows = [r for r in sb.live_candidates() if r.get("book")]
    assert rows
    for r in rows:
        rs = tasks.resolve_strategy(r["id"], None, r["timeframe"], None, r["symbols"], r["book"])
        assert rs["params"] == sb.lift_frames(sb.BY_ID[r["id"]], r["params"], r["timeframe"]), r["row_id"]
        p = {"alpha_id": r["id"], "signal_tf": r["timeframe"], "symbols": [s + "-USDT-SWAP" for s in r["symbols"][:1]], "base_frame": r["timeframe"], "book_source": r["book"]}
        assert tasks.launch_fingerprint(p, tasks.resolve_live_source(p))["fingerprint_match"] is True, r["row_id"]


def test_explore_dca_short_uses_tuned_params(real_books):
    from backend.alpha import strategies as sb
    r = next((x for x in sb.live_candidates() if x["id"] == "dca_short" and x["book"] == "explore"), None)
    if r is None:
        pytest.skip("không có dòng explore dca_short")
    pos = tasks.resolve_live_source({"alpha_id": "dca_short", "signal_tf": r["timeframe"], "symbols": ["BTC-USDT-SWAP"], "book_source": "explore"})["strategies"][0]["position"]
    assert pos["take_profit_rate"] == r["params"]["take_profit_rate"] != 1.5
