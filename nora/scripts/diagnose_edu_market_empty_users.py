"""Chẩn đoán chi tiết Market EDU:
1. Danh sách người dùng (users).
2. Danh sách alpha của từng người dùng trong store.
3. Thẻ card_index và aggregate_cards.
4. Kiểm tra các user bị rỗng (empty metrics / không hiện trên Market).
"""
import sys
import os
import json
from pathlib import Path

REPO_ROOT = Path("/home/vmc03/norabt")
EDU_ROOT = REPO_ROOT / "nora" / "edu"
COIN_ROOT = REPO_ROOT / "nora" / "coin"

sys.path.insert(0, str(EDU_ROOT))
from backend import users
from backend.analys.alpha import store
from backend.routes.market_edu import _market_rows, _build_market_rows

print("=" * 80)
print("1. THƯ MỤC VÀ DỮ LIỆU CƠ BẢN")
print("=" * 80)
user_alphas_dir = store.get_user_alphas_dir()
users_dir = users.users_dir()
print(f"User alphas dir: {user_alphas_dir}")
print(f"Users dir: {users_dir}")

all_users = users.list_users()
print(f"Tổng số users trong hệ thống: {len(all_users)}")

all_alpha_files = [f for f in os.listdir(user_alphas_dir) if f.endswith(".json")] if os.path.exists(user_alphas_dir) else []
print(f"Tổng số file alpha trong user_alphas_dir: {len(all_alpha_files)}")

print("\n" + "=" * 80)
print("2. KIỂM TRA TỪNG USER VÀ CÁC CHIẾN LƯỢC TRONG STORE")
print("=" * 80)
card_idx = store.card_index()
print(f"Số lượng owner có trong card_index: {len(card_idx)}")

empty_users = []
populated_users = []

for u in all_users:
    uid = u.get("id")
    handle = u.get("handle")
    name = u.get("display_name")
    user_cards = card_idx.get(uid, [])
    
    if not user_cards:
        empty_users.append((uid, handle, name, "Không có file alpha nào gắn owner_id"))
        continue
        
    agg = store.aggregate_cards(user_cards)
    best = agg.get("best")
    
    # Kiểm tra xem có dữ liệu backtest (trades, ret_pct, pnl_usd) không
    has_metrics = False
    metrics_summary = []
    for c in user_cards:
        cid = c.get("id")
        cname = c.get("name")
        trades = c.get("trades")
        ret_pct = c.get("ret_pct")
        pnl = c.get("pnl_usd")
        mdd = c.get("mdd_pct")
        sharpe = c.get("sharpe")
        if trades is not None or ret_pct is not None or pnl is not None:
            has_metrics = True
        metrics_summary.append({
            "id": cid, "name": cname, "trades": trades,
            "ret_pct": ret_pct, "pnl_usd": pnl, "mdd_pct": mdd, "sharpe": sharpe
        })
        
    if not has_metrics or not best or best.get("ret_pct") is None:
        empty_users.append((uid, handle, name, f"Có {len(user_cards)} alpha nhưng thiếu metrics backtest (chưa có kết quả)", metrics_summary))
    else:
        populated_users.append((uid, handle, name, len(user_cards), best.get("ret_pct"), best.get("trades"), best.get("pnl_usd")))

print(f"\n-> Số user CÓ ĐỦ DỮ LIỆU HIỂN THỊ TRÊN MARKET: {len(populated_users)}")
for u in populated_users:
    print(f"   [OK] {u[1]} ({u[2]} | ID: {u[0]}): {u[3]} alphas, best ret={u[4]}%, trades={u[5]}, pnl={u[6]} USD")

print(f"\n-> Số user BỊ RỖNG HOẶC THIẾU KẾT QUẢ: {len(empty_users)}")
for item in empty_users:
    uid, handle, name, reason = item[0], item[1], item[2], item[3]
    print(f"   [RỖNG] {handle} ({name} | ID: {uid}): {reason}")
    if len(item) > 4:
        for m in item[4]:
            print(f"          - Alpha {m['id']}: trades={m['trades']}, ret={m['ret_pct']}, pnl={m['pnl_usd']}")

print("\n" + "=" * 80)
print("3. KIỂM TRA ĐẦU RA CỦA _market_rows() (API /api/edu/market)")
print("=" * 80)
m_rows = _market_rows()
print(f"Số dòng trả về bởi _market_rows(): {len(m_rows)}")
for r in m_rows:
    b = r.get("best") or {}
    print(f"   Row: {r.get('handle')} | Display: {r.get('display_name')} | n_strat: {r.get('n_strategies')} | best_ret: {b.get('ret_pct')} | trades: {b.get('trades')}")
print("=" * 80)
