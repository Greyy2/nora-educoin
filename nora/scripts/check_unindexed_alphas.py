import sys, json
from pathlib import Path

EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")
sys.path.insert(0, str(EDU_ROOT))

from backend.analys.alpha import store
from backend import users

idx = store.card_index()
all_users = {u["id"]: u["handle"] for u in users.list_users()}

assigned_alpha_ids = set()
for oid, cards in idx.items():
    for c in cards:
        assigned_alpha_ids.add(c["id"])

user_dir = Path("nora/edu/data/alpha/user")
all_files = list(user_dir.glob("*.json"))

print(f"Tổng files trong user dir: {len(all_files)}")
print(f"Số alpha có trong card_index: {len(assigned_alpha_ids)}")

unindexed = []
for p in all_files:
    if p.stem not in assigned_alpha_ids:
        d = json.loads(p.read_text(encoding="utf-8"))
        unindexed.append((p.stem, d.get("owner_id"), d.get("name"), d.get("status")))

print(f"Số alpha không có trong card_index: {len(unindexed)}")
for u in unindexed:
    print(f"  {u[0]} | owner={u[1]} ({all_users.get(u[1], 'NO_USER')}) | name={u[2]} | status={u[3]}")
