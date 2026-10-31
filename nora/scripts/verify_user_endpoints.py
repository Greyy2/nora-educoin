import sys
from pathlib import Path
from fastapi.testclient import TestClient

EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")
sys.path.insert(0, str(EDU_ROOT))

from backend.main import app
client = TestClient(app)

handles = ["fx_u1_357a91", "fx_u2_28da0d", "fx_u4_5dc329", "vinh"]
for h in handles:
    r_user = client.get(f"/api/edu/users/{h}")
    r_strats = client.get(f"/api/edu/users/{h}/strategies")
    print(f"User @{h:15s}: user_api={r_user.status_code}, strats_api={r_strats.status_code}, n_strats={len(r_strats.json()) if r_strats.status_code==200 else 'ERR'}")
    if r_strats.status_code == 200 and len(r_strats.json()) > 0:
        s0 = r_strats.json()[0]
        print(f"    Chiến lược: {s0.get('name')} | ret={s0.get('ret_pct')}% | trades={s0.get('trades')} | sharpe={s0.get('sharpe')}")
