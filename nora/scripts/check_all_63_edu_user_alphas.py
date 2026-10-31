"""Kiểm tra toàn bộ 63 file alpha trong nora/edu/data/alpha/user/"""
import sys, os, json
from pathlib import Path

EDU_USER_DIR = Path("/home/vmc03/norabt/nora/edu/data/alpha/user")
files = sorted([f for f in EDU_USER_DIR.glob("*.json") if f.name != "__init__.py"])

print(f"Tổng số file json: {len(files)}")

has_result_count = 0
no_result_count = 0
no_result_list = []

for f in files:
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        aid = d.get("id") or f.stem
        owner = d.get("owner_id")
        name = d.get("name")
        status = d.get("status")
        bt_status = d.get("backtest_status")
        
        # Kiểm tra metrics / result
        sim = (d.get("metrics") or {}).get("simulate")
        has_res = bool(d.get("result"))
        has_snap = False
        ch = d.get("contract_history")
        if isinstance(ch, list) and ch:
            for item in ch:
                if isinstance(item, dict) and (item.get("result_snapshot") or {}).get("metrics"):
                    has_snap = True
                    break
                    
        is_populated = bool(sim or has_res or has_snap)
        if is_populated:
            has_result_count += 1
        else:
            no_result_count += 1
            no_result_list.append({
                "id": aid,
                "file": f.name,
                "owner_id": owner,
                "name": name,
                "backtest_status": bt_status,
                "status": status,
            })
    except Exception as e:
        print(f"Lỗi đọc file {f.name}: {e}")

print(f"\nSố file ĐÃ CÓ kết quả backtest/metrics: {has_result_count}")
print(f"Số file CHƯA CÓ kết quả (RỖNG): {no_result_count}")

print("\nDanh sách các file CHƯA CÓ kết quả (RỖNG):")
for item in no_result_list:
    print(f"  ID: {item['id']} | Owner: {item['owner_id']} | BT Status: {item['backtest_status']} | Name: {item['name']}")
