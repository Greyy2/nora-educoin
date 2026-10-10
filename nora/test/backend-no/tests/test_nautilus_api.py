"""Test API Nautilus Gateway tích hợp với FastAPI."""
import sys
import os
sys.path.insert(0, os.path.abspath("."))

from fastapi.testclient import TestClient
from backend.main import app

def test_api():
    client = TestClient(app)

    print("1. Kiểm tra /api/studio/nautilus/version:")
    r = client.get("/api/studio/nautilus/version")
    print("Status:", r.status_code, "Data:", r.json())
    assert r.status_code == 200
    assert r.json()["installed"] is True

    print("\n2. Kiểm tra /api/studio/custom/defaults:")
    r = client.get("/api/studio/custom/defaults")
    print("Status:", r.status_code, "Data:", r.json())
    assert r.status_code == 200
    assert "symbols" in r.json()

    print("\n3. Kiểm tra /api/studio/strategies:")
    r = client.get("/api/studio/strategies")
    print("Status:", r.status_code, "Position fields:", len(r.json().get("position_fields", [])))
    assert r.status_code == 200

    print("\n4. Kiểm tra POST /api/studio/custom/backtest (Chạy trực tiếp qua Nautilus):")
    payload = {
        "symbols": ["BTC-USDT-SWAP"],
        "initial_capital": 10000.0,
        "position": {
            "stop_loss_rate": 2.0,
            "take_profit_rate": 5.0,
            "leverage": 2.0,
            "risk_per_trade_pct": 10.0,
            "dca_steps": [1.0, 2.0],
            "dca_multipliers": [1.0, 1.0],
            "sl_anchor": "last_layer",
            "sl_beyond_last_pct": 1.5,
        }
    }
    r = client.post("/api/studio/custom/backtest", json=payload)
    print("Status:", r.status_code)
    data = r.json()
    assert r.status_code == 200
    assert data["status"] == "done"
    assert "result" in data
    print("Metrics:", data["result"]["metrics"])
    print(f"Fills: {len(data['result']['fills'])}")
    print("Job ID:", data["job_id"])

    print("\n5. Kiểm tra GET /api/studio/book/jobs/{id}:")
    r_job = client.get(f"/api/studio/book/jobs/{data['job_id']}")
    assert r_job.status_code == 200
    assert r_job.json()["status"] == "done"
    print("Job status retrieved OK!")

    print("\n>>> TẤT CẢ 5 API NAUTILUS ĐÃ HOẠT ĐỘNG HOÀN HẢO 100% <<<")

if __name__ == "__main__":
    test_api()
