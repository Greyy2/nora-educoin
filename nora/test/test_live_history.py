"""Lịch sử bot cũ (đọc thật data/live, chỉ đọc) + bot mới vẫn 501."""
import os

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.models import storage

REAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
HAS = os.path.isfile(os.path.join(REAL, "live", "paper", "okx_explore", "state.json"))
c = TestClient(app)


@pytest.fixture(autouse=True)
def real_data(monkeypatch):
    """Đọc dữ liệu bot cũ thật (CHỈ ĐỌC) thay vì thư mục dữ liệu tạm của conftest."""
    monkeypatch.setattr(storage, "data_home", lambda: REAL)


@pytest.mark.skipif(not HAS, reason="không có data/live")
def test_trades_paper_explore():
    r = c.get("/api/studio/live/trades", params={"mode": "paper", "book": "explore"})
    assert r.status_code == 200
    d = r.json()
    assert d["archived"] and d["has_data"] and d["running"] == []
    assert d["paper"]["trades"] and d["paper"]["trades"][0]["symbol"]
    assert d["equity_stats"]["bars"] > 1 and d["symbols"]


@pytest.mark.skipif(not HAS, reason="không có data/live")
def test_bot_compare_archive():
    assert c.get("/api/studio/live/bot", params={"mode": "demo"}).json()["status"] == "archived"
    assert c.get("/api/studio/live/compare_events", params={"mode": "demo"}).status_code == 200
    assert c.get("/api/studio/live/compare", params={"mode": "demo"}).status_code == 200
    bots = c.get("/api/studio/live/archive").json()["bots"]
    assert {"paper", "testnet"} <= {b["tab"] for b in bots}


def test_live_mode_missing_is_empty_and_new_bot_501():
    d = c.get("/api/studio/live/trades", params={"mode": "live"}).json()
    assert d["exec"]["trades"] == [] or d["has_data"]
    r = c.post("/api/studio/live/bot", json={"mode": "nope"})      # mode sai bị từ chối trước khi tạo job
    assert r.status_code == 422
    r = c.post("/api/studio/live/bot", json={"mode": "live"})
    assert r.status_code == 400
