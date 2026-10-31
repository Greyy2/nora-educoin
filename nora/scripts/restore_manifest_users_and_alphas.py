#!/usr/bin/env python3
import json
import os
import shutil
from pathlib import Path

ROOT = Path("/home/vmc03/norabt")
MANIFEST_PATH = ROOT / "nora/check/edu_cleanup_manifest.json"
FROZEN_PATH = ROOT / "nora/check/edu_frozen_inventory_manifest.json"

BACKUP_USERS = ROOT / ".backup/edu_cleanup_snapshot_20261027_081046/users"
BACKUP_ALPHAS = ROOT / ".backup/edu_cleanup_snapshot_20261027_081046/alpha_user"

TARGET_USERS = ROOT / "nora/edu/data/users"
TARGET_ALPHAS = ROOT / "nora/edu/data/alpha/user"

def restore():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    kept_users = set(manifest["kept_users"])
    
    print(f"Target kept users count: {len(kept_users)}")
    restored_users = 0
    for uid in kept_users:
        src = BACKUP_USERS / f"{uid}.json"
        dst = TARGET_USERS / f"{uid}.json"
        if not dst.exists() and src.exists():
            shutil.copy2(src, dst)
            restored_users += 1
    print(f"Restored {restored_users} user account files.")
    
    frozen = json.loads(FROZEN_PATH.read_text(encoding="utf-8"))
    all_57_alphas = {a["id"] for a in frozen["active_user_alphas"]}
    print(f"Target kept alphas count: {len(all_57_alphas)}")
    restored_alphas = 0
    for aid in all_57_alphas:
        src = BACKUP_ALPHAS / f"{aid}.json"
        dst = TARGET_ALPHAS / f"{aid}.json"
        if not dst.exists() and src.exists():
            shutil.copy2(src, dst)
            restored_alphas += 1
    print(f"Restored {restored_alphas} alpha files.")

if __name__ == "__main__":
    restore()
