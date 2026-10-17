"""Biểu đồ bot live (/live/bot/{id}/chart) + ép khung tín hiệu của bộ chọn chiến lược."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import live as live_routes


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(live_routes.router)
    return TestClient(app)


ROWS = [{"id": "dca_long", "timeframe": "1h", "signal_tf": "1h", "backtested_at": 1}]


def test_picker_rejects_tf_without_stored_backtest(client, monkeypatch):
    monkeypatch.setattr("backend.alpha.strategies.live_candidates", lambda *a, **k: ROWS)
    r = client.post("/api/studio/live/bot", json={"mode": "paper", "alpha_id": "dca_long", "signal_tf": "15m", "from_picker": True})
    assert r.status_code == 400 and "15m" in r.json()["detail"]
    r = client.post("/api/studio/live/bot", json={"mode": "paper", "alpha_id": "dca_long", "from_picker": True})
    assert r.status_code == 400


def test_picker_passes_signal_tf_to_job(client, monkeypatch):
    seen = {}
    monkeypatch.setattr("backend.alpha.strategies.live_candidates", lambda *a, **k: ROWS)
    monkeypatch.setattr(live_routes, "launch", lambda kind, params: seen.update(params) or "job1")
    r = client.post("/api/studio/live/bot", json={"mode": "paper", "alpha_id": "dca_long", "signal_tf": "1h", "base_frame": "1m", "from_picker": True})
    assert r.status_code == 200 and seen["signal_tf"] == "1h" and seen["base_frame"] == "1m"


def test_resolve_live_source_enforces_signal_tf():
    from backend.jobs.tasks import resolve_live_source
    src = resolve_live_source({"alpha_id": "dca_long", "signal_tf": "15m", "symbols": ["BTC-USDT-SWAP"]})
    assert src["base_frame"] == "15m"
    assert src["strategies"][0]["tree"] is not None
    with pytest.raises(ValueError):      # khung chạy không được lớn hơn khung tín hiệu
        resolve_live_source({"alpha_id": "dca_long", "signal_tf": "15m", "base_frame": "1h", "symbols": ["BTC-USDT-SWAP"]})


def test_live_candidates_one_row_per_stored_tf():
    from backend.alpha import strategies
    for r in strategies.live_candidates():
        assert r["timeframe"] and r["signal_tf"] == r["timeframe"] and "backtested_at" in r and r["ret_pct"] > 0


def test_chart_endpoint_shape_and_404(client, monkeypatch):
    shape = {"bot_id": "b", "frame": "1m", "symbols": ["BTC@perp"], "candles": {"BTC@perp": [[1, 1, 2, 0.5, 1.5, 3]]}, "signals": {"BTC@perp": []},
             "fills_live": [], "fills_replay": [], "compare": None}
    import backend.jobs.live_chart as lc
    monkeypatch.setattr(lc, "build_chart", lambda bot_id, frame=None, replay=False: shape if bot_id == "b" else (_ for _ in ()).throw(LookupError("none")))
    assert client.get("/api/studio/live/bot/b/chart?frame=1m").json()["candles"]["BTC@perp"][0][0] == 1
    assert client.get("/api/studio/live/bot/zz/chart").status_code == 404
    assert client.get("/api/studio/live/bot/b/chart?frame=7m").status_code == 422


def test_match_fills_pairs_and_bps():
    from backend.jobs.live_chart import match_fills
    live = [{"t": 1000, "symbol": "BTC@perp", "side": "BUY", "kind": "ENTRY", "price": 101.0},
            {"t": 9_000_000, "symbol": "BTC@perp", "side": "BUY", "kind": "DCA", "price": 50.0}]
    rep = [{"t": 0, "symbol": "BTC@perp", "side": "BUY", "kind": "ENTRY", "price": 100.0}]
    m = match_fills(live, rep, 120_000)
    assert len(m["matched"]) == 1 and m["matched"][0]["bps"] == 100.0 and len(m["only_live"]) == 1 and not m["only_replay"]
