import sys, json
from pathlib import Path
from fastapi.testclient import TestClient

EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")
sys.path.insert(0, str(EDU_ROOT))

from backend.main import app
client = TestClient(app)

res = client.get("/api/edu/users/fx_u1_357a91")
print(f"Status: {res.status_code}")
data = res.json()
print("User info:", data.get("user"))
print("Summary:", data.get("summary"))
print("Strategies count:", len(data.get("strategies", [])))
if data.get("strategies"):
    s = data["strategies"][0]
    print(f"Strat name: {s.get('name')}")
    print(f"Strat return: {s.get('ret_pct')}%")
    print(f"Strat PnL: ${s.get('pnl_usd')}")
    print(f"Strat trades: {s.get('trades')}")
    print(f"Strat Sharpe: {s.get('sharpe')}")
