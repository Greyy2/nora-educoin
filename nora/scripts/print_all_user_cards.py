import sys
from pathlib import Path

EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")
sys.path.insert(0, str(EDU_ROOT))

from backend.analys.alpha import store
from backend import users

idx = store.card_index()
all_users = {u["id"]: u["handle"] for u in users.list_users()}

for oid, cards in sorted(idx.items(), key=lambda x: len(x[1]), reverse=True):
    handle = all_users.get(oid, "UNKNOWN_USER")
    rets = [c.get("ret_pct") for c in cards]
    valid_rets = [r for r in rets if r is not None]
    print(f"{handle:22s} ({oid}): total={len(cards)}, valid_rets={len(valid_rets)}, cards={[(c['id'], c['name'], c.get('ret_pct')) for c in cards]}")
