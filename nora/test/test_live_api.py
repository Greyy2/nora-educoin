"""Test B4 (P17 T5): API routes live bot."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes.live import router


class FakePopen:
    calls = []

    def __init__(self, cmd, **kw):
        FakePopen.calls.append((cmd, kw))
        self.pid = 2 ** 22 + 12345
        self.returncode = None

    def wait(self):
        return 0


@pytest.fixture
def client(monkeypatch):
    FakePopen.calls.clear()
    monkeypatch.setattr("backend.jobs.runner.subprocess.Popen", FakePopen)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)



def test_post_live_bot_requires_confirm_live(client):
    res = client.post("/api/studio/live/bot", json={
        "mode": "live",
        "symbols": ["BTC-USDT-SWAP"],
        "capital": 1000.0,
        "confirm_live": False,
    })
    assert res.status_code == 400
    assert "confirm_live=True" in res.json()["detail"]


def test_post_live_bot_paper_creates_job(client):
    res = client.post("/api/studio/live/bot", json={
        "mode": "paper",
        "symbols": ["BTC-USDT-SWAP"],
        "capital": 1000.0,
        "alpha_id": "kema_long",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["mode"] == "paper"
    assert data["bot_id"].startswith("bot_")
    assert "job_id" in data
    # Kiểm tra Popen được gọi với live_bot
    assert len(FakePopen.calls) > 0


def test_get_live_bots_list(client):
    res = client.get("/api/studio/live/bots")
    assert res.status_code == 200
    assert "bots" in res.json()


def test_bot_not_found(client):
    res = client.get("/api/studio/live/bot/non_existent_bot_999")
    assert res.status_code == 404

    res_stop = client.post("/api/studio/live/bot/non_existent_bot_999/stop")
    assert res_stop.status_code == 404


def test_post_stop_bot_body_and_query(client, monkeypatch):
    recorded_close = []

    def fake_stop_bot(bot_id, close_positions=True):
        recorded_close.append((bot_id, close_positions))
        return {"ok": True, "bot_id": bot_id, "status": "stopped", "close": close_positions}

    monkeypatch.setattr("backend.routes.live.stop_bot", fake_stop_bot)

    # 1. Body {"close": false}
    res = client.post("/api/studio/live/bot/bot_123/stop", json={"close": False})
    assert res.status_code == 200
    assert res.json()["close"] is False
    assert recorded_close[-1] == ("bot_123", False)

    # 2. Query param ?close=false
    res = client.post("/api/studio/live/bot/bot_123/stop?close=false")
    assert res.status_code == 200
    assert res.json()["close"] is False
    assert recorded_close[-1] == ("bot_123", False)

    # 3. Default (no body, no query) -> close=True
    res = client.post("/api/studio/live/bot/bot_123/stop")
    assert res.status_code == 200
    assert res.json()["close"] is True
    assert recorded_close[-1] == ("bot_123", True)

