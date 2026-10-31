import sys
from pathlib import Path

EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")
sys.path.insert(0, str(EDU_ROOT))

from backend.analys.alpha import store
from backend import users
from backend.routes.market_edu import _market_rows

print("--- KIỂM TRA CARD INDEX VÀ USER ALPHAS ---")
idx = store.card_index()
all_users = users.list_users()

print(f"Tổng số users trong hệ thống: {len(all_users)}")
print(f"Tổng số users có trong card_index: {len(idx)}")

total_cards = sum(len(cards) for cards in idx.values())
print(f"Tổng số cards: {total_cards}")

users_with_cards = []
users_empty_cards = []
users_missing_cards = []

for u in all_users:
    u_id = u["id"]
    u_handle = u.get("handle")
    u_cards = idx.get(u_id, [])
    if not u_cards:
        users_missing_cards.append((u_id, u_handle))
    else:
        # Kiểm tra xem cards của user có dữ liệu hay rỗng
        has_valid_ret = any(c.get("ret_pct") is not None for c in u_cards)
        if has_valid_ret:
            users_with_cards.append((u_id, u_handle, len(u_cards)))
        else:
            users_empty_cards.append((u_id, u_handle, len(u_cards)))

print(f"\nUsers có kết quả backtest (ret_pct hợp lệ): {len(users_with_cards)}")
for u in users_with_cards:
    print(f"  {u[1]:20s} (id={u[0]}): {u[2]} cards")

print(f"\nUsers có alpha nhưng card rỗng (ret_pct is None): {len(users_empty_cards)}")
for u in users_empty_cards:
    print(f"  {u[1]:20s} (id={u[0]}): {u[2]} cards")

print(f"\nUsers không có alpha nào: {len(users_missing_cards)}")
for u in users_missing_cards[:10]:
    print(f"  {u[1]:20s} (id={u[0]})")

print("\n--- KIỂM TRA _market_rows() ---")
rows = _market_rows()
print(f"Số hàng trong market_rows: {len(rows)}")
empty_rows = [r for r in rows if not r.get("best") or r.get("best", {}).get("ret_pct") is None]
print(f"Số hàng có best.ret_pct is None (card rỗng trên UI): {len(empty_rows)}")
for r in empty_rows:
    print(f"  handle={r.get('handle'):20s} best={r.get('best')}")
