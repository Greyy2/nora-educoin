import sys, json
from pathlib import Path
from fastapi.testclient import TestClient

EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")
sys.path.insert(0, str(EDU_ROOT))

from backend.main import app

client = TestClient(app)

res = client.get("/api/edu/market?sort=name")
print(f"Status code: {res.status_code}")
data = res.json()

users_list = data.get("users", [])
print(f"Tổng số tác giả trả về trên Market: {len(users_list)}")

empty_best = []
valid_best = []

for u in users_list:
    best = u.get("best")
    if not best or best.get("ret_pct") is None:
        empty_best.append(u.get("handle"))
    else:
        valid_best.append((
            u.get("handle"),
            best.get("name"),
            best.get("symbol"),
            best.get("timeframe"),
            best.get("trades"),
            best.get("ret_pct"),
            best.get("pnl_usd"),
            best.get("mdd_pct"),
            best.get("sharpe"),
        ))

print(f"\nSố tác giả có dữ liệu đầy đủ: {len(valid_best)}")
print(f"Số tác giả bị rỗng (ret_pct is None): {len(empty_best)}")

print("\n--- 10 TÁC GIẢ TIÊU BIỂU TRÊN MARKET ---")
for v in valid_best[:10]:
    print(f"  @{v[0]:18s} | {v[1]:32s} | {v[2]} {v[3]} | trades={v[4]:4d} | ret={v[5]:6.2f}% | pnl=${v[6]:8.2f} | mdd={v[7]:5.2f}% | sharpe={str(v[8]):5s}")
