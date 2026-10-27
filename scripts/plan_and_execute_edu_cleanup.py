#!/usr/bin/env python3
"""
Plan & Execution Script for EDU Data Cleanup.
Preserves:
- 3 users with no alphas
- 30 users with all-positive alphas (MANDATORY: preserve 'vinh')
- 3 users with mixed alphas
Total preserved: 36 users.
Total deleted: 998 users + their associated alphas & versions.
42 unlinked alphas are archived safely to nora/edu/data/alpha/_unlinked_archive.
"""

import os
import sys
import json
import shutil
import tarfile
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

ROOT = Path("/home/vmc03/norabt")
EDU_DATA = ROOT / "nora/edu/data"
USERS_DIR = EDU_DATA / "users"
ALPHAS_DIR = EDU_DATA / "alpha/user"
VERSIONS_DIR = ALPHAS_DIR / "_versions"
ARCHIVE_DIR = EDU_DATA / "alpha/_unlinked_archive"
BACKUP_BASE = ROOT / ".backup"

def load_accounts():
    accounts = {}
    if USERS_DIR.is_dir():
        for f in USERS_DIR.glob("*.json"):
            if f.is_file():
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        accounts[f.stem] = data
                except Exception as e:
                    print(f"Error loading {f}: {e}")
    return accounts

def load_alphas():
    alphas = []
    if ALPHAS_DIR.is_dir():
        for f in ALPHAS_DIR.glob("*.json"):
            if f.is_file():
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        alphas.append((f.name, f.stem, data))
                except Exception as e:
                    print(f"Error loading {f}: {e}")
    return alphas

def extract_outcome(alpha_data):
    m = (alpha_data.get("result") or {}).get("metrics") or alpha_data.get("metrics") or {}
    sim = m.get("simulate") if isinstance(m, dict) else None
    if not isinstance(sim, dict):
        return None
    for k in ("net_pnl_usdt", "net_pnl_usd", "pnl_usd"):
        if isinstance(sim.get(k), (float, int)):
            return float(sim[k])
    for k in ("net_return_pct", "ret_pct", "total_return_pct"):
        if isinstance(sim.get(k), (float, int)):
            return float(sim[k])
    return None

def categorize_users(accounts, alphas):
    owners = defaultdict(list)
    unlinked = []
    ownerless = []

    for fname, aid, data in alphas:
        oid = str(data.get("owner_id") or "").strip()
        if oid in accounts:
            owners[oid].append((fname, aid, data))
        elif oid:
            unlinked.append((fname, aid, data))
        else:
            ownerless.append((fname, aid, data))

    categories = {}
    for oid, user_alphas in owners.items():
        outcomes = [extract_outcome(d) for _, _, d in user_alphas]
        if not outcomes or any(v is None for v in outcomes):
            cat = "unknown"
        elif all(v > 0 for v in outcomes):
            cat = "all_positive"
        elif all(v >= 0 for v in outcomes) and any(v == 0 for v in outcomes):
            cat = "nonnegative_has_zero"
        elif any(v > 0 for v in outcomes) and any(v < 0 for v in outcomes):
            cat = "mixed"
        elif all(v < 0 for v in outcomes):
            cat = "all_loss"
        else:
            cat = "other"
        categories[oid] = cat

    no_alpha_users = [uid for uid in accounts if uid not in owners]
    all_positive_users = [uid for uid, c in categories.items() if c == "all_positive"]
    mixed_users = [uid for uid, c in categories.items() if c == "mixed"]
    zero_users = [uid for uid, c in categories.items() if c == "nonnegative_has_zero"]
    other_users = [uid for uid, c in categories.items() if c not in ("all_positive", "mixed", "nonnegative_has_zero")]

    return {
        "owners": owners,
        "unlinked": unlinked,
        "ownerless": ownerless,
        "categories": categories,
        "no_alpha_users": no_alpha_users,
        "all_positive_users": all_positive_users,
        "mixed_users": mixed_users,
        "zero_users": zero_users,
        "other_users": other_users
    }

def plan_selection(cat_data, accounts):
    # Mandatory keep: vinh
    vinh_uid = None
    for uid, acc in accounts.items():
        h = str(acc.get("handle") or "").lower()
        d = str(acc.get("display_name") or "").lower()
        if h == "vinh" or d == "vinh":
            vinh_uid = uid
            break

    if not vinh_uid:
        raise ValueError("Could not find user 'vinh' in accounts!")

    print(f"Found user 'vinh': UID={vinh_uid}, Handle={accounts[vinh_uid].get('handle')}, Category={cat_data['categories'].get(vinh_uid)}")

    # 1. No alpha users: keep 3 (newest created_at)
    no_alpha_sorted = sorted(
        cat_data["no_alpha_users"],
        key=lambda u: accounts[u].get("created_at") or "",
        reverse=True
    )
    keep_no_alpha = no_alpha_sorted[:3]
    del_no_alpha = no_alpha_sorted[3:]

    # 2. All positive users: keep 30 (must include vinh + 29 others sorted by alpha count or newest)
    all_pos = [u for u in cat_data["all_positive_users"] if u != vinh_uid]
    all_pos_sorted = sorted(
        all_pos,
        key=lambda u: (len(cat_data["owners"].get(u, [])), accounts[u].get("created_at") or ""),
        reverse=True
    )
    keep_all_positive = [vinh_uid] + all_pos_sorted[:29]
    del_all_positive = all_pos_sorted[29:]

    # 3. Mixed users: keep 3 (sorted by count/created_at)
    mixed_sorted = sorted(
        cat_data["mixed_users"],
        key=lambda u: (len(cat_data["owners"].get(u, [])), accounts[u].get("created_at") or ""),
        reverse=True
    )
    keep_mixed = mixed_sorted[:3]
    del_mixed = mixed_sorted[3:]

    # 4. Zero users: delete all
    del_zero = list(cat_data["zero_users"])

    # 5. Other users: delete all
    del_other = list(cat_data["other_users"])

    keep_users = set(keep_no_alpha + keep_all_positive + keep_mixed)
    delete_users = set(del_no_alpha + del_all_positive + del_mixed + del_zero + del_other)

    assert len(keep_users) == 36, f"Expected 36 kept users, got {len(keep_users)}"
    assert len(delete_users) == len(accounts) - 36, f"Expected {len(accounts) - 36} deleted users, got {len(delete_users)}"
    assert vinh_uid in keep_users, "CRITICAL: Vinh is NOT in kept users!"

    return {
        "vinh_uid": vinh_uid,
        "keep_users": keep_users,
        "delete_users": delete_users,
        "keep_breakdown": {
            "no_alpha": keep_no_alpha,
            "all_positive": keep_all_positive,
            "mixed": keep_mixed
        },
        "delete_breakdown": {
            "no_alpha": del_no_alpha,
            "all_positive": del_all_positive,
            "mixed": del_mixed,
            "zero": del_zero,
            "other": del_other
        }
    }

def create_backup():
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUP_BASE / f"edu_cleanup_snapshot_{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Creating full backup at: {backup_dir}")
    
    # Copy users
    shutil.copytree(USERS_DIR, backup_dir / "users", dirs_exist_ok=True)
    # Copy alphas
    shutil.copytree(ALPHAS_DIR, backup_dir / "alpha_user", dirs_exist_ok=True)
    
    print("Backup completed successfully.")
    return backup_dir

def execute_cleanup(plan, cat_data, accounts, alphas):
    backup_dir = create_backup()
    
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Archive 42 unlinked/ownerless alphas
    unlinked_all = cat_data["unlinked"] + cat_data["ownerless"]
    print(f"Archiving {len(unlinked_all)} unlinked/ownerless alphas to {ARCHIVE_DIR}...")
    archived_count = 0
    for fname, aid, data in unlinked_all:
        src = ALPHAS_DIR / fname
        dst = ARCHIVE_DIR / fname
        if src.is_file():
            shutil.move(str(src), str(dst))
            archived_count += 1
            # Move versions if any
            if VERSIONS_DIR.is_dir():
                for vfile in VERSIONS_DIR.glob(f"{aid}.v*.json"):
                    v_dst = ARCHIVE_DIR / vfile.name
                    shutil.move(str(vfile), str(v_dst))
    print(f"Archived {archived_count} files successfully.")

    # 2. Delete alphas of deleted users
    del_alphas_count = 0
    del_versions_count = 0
    for uid in plan["delete_users"]:
        user_alphas = cat_data["owners"].get(uid, [])
        for fname, aid, _ in user_alphas:
            alpha_file = ALPHAS_DIR / fname
            if alpha_file.is_file():
                alpha_file.unlink()
                del_alphas_count += 1
            # Delete associated versions
            if VERSIONS_DIR.is_dir():
                for vfile in VERSIONS_DIR.glob(f"{aid}.v*.json"):
                    vfile.unlink()
                    del_versions_count += 1

    print(f"Deleted {del_alphas_count} alpha records and {del_versions_count} version records for deleted users.")

    # 3. Delete user accounts
    del_accounts_count = 0
    for uid in plan["delete_users"]:
        user_file = USERS_DIR / f"{uid}.json"
        if user_file.is_file():
            user_file.unlink()
            del_accounts_count += 1

    print(f"Deleted {del_accounts_count} user account files.")

    # 4. Verify post-cleanup state
    remaining_accounts = list(USERS_DIR.glob("*.json"))
    remaining_alphas = [f for f in ALPHAS_DIR.glob("*.json") if f.is_file()]
    
    vinh_account = USERS_DIR / f"{plan['vinh_uid']}.json"
    vinh_alphas = [f for f in remaining_alphas if json.loads(f.read_text()).get("owner_id") == plan['vinh_uid']]

    print("\n=== POST-CLEANUP VERIFICATION ===")
    print(f"Remaining user accounts: {len(remaining_accounts)} (Target: 36)")
    print(f"Remaining alpha files: {len(remaining_alphas)}")
    print(f"Vinh account exists: {vinh_account.is_file()}")
    print(f"Vinh alphas count: {len(vinh_alphas)}")
    assert vinh_account.is_file(), "FATAL: Vinh account was deleted!"
    assert len(vinh_alphas) >= 7, f"FATAL: Vinh lost alphas! Found {len(vinh_alphas)}"
    assert len(remaining_accounts) == 36, f"FATAL: Expected 36 accounts, got {len(remaining_accounts)}"

    # Save manifest log
    manifest = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backup_dir": str(backup_dir),
        "kept_users": list(plan["keep_users"]),
        "deleted_users_count": del_accounts_count,
        "deleted_alphas_count": del_alphas_count,
        "archived_unlinked_count": archived_count,
        "vinh_uid": plan["vinh_uid"],
        "vinh_alphas": [f.stem for f in vinh_alphas],
        "remaining_accounts_count": len(remaining_accounts),
        "remaining_alphas_count": len(remaining_alphas)
    }
    manifest_path = ROOT / "nora/check/edu_cleanup_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Saved audit manifest to {manifest_path}")

def main():
    dry_run = "--execute" not in sys.argv
    accounts = load_accounts()
    alphas = load_alphas()
    cat_data = categorize_users(accounts, alphas)
    plan = plan_selection(cat_data, accounts)

    print("=== EDU CLEANUP PLAN ===")
    print(f"Total current accounts: {len(accounts)}")
    print(f"Target kept accounts: {len(plan['keep_users'])}")
    print(f"  - No alpha users: {len(plan['keep_breakdown']['no_alpha'])}")
    print(f"  - All positive users: {len(plan['keep_breakdown']['all_positive'])} (including Vinh: {plan['vinh_uid']})")
    print(f"  - Mixed users: {len(plan['keep_breakdown']['mixed'])}")
    print(f"Target deleted accounts: {len(plan['delete_users'])}")
    print(f"  - No alpha deleted: {len(plan['delete_breakdown']['no_alpha'])}")
    print(f"  - All positive deleted: {len(plan['delete_breakdown']['all_positive'])}")
    print(f"  - Mixed deleted: {len(plan['delete_breakdown']['mixed'])}")
    print(f"  - Zero deleted: {len(plan['delete_breakdown']['zero'])}")
    print(f"Unlinked / Ownerless alphas to archive: {len(cat_data['unlinked']) + len(cat_data['ownerless'])}")

    if dry_run:
        print("\n[DRY RUN ONLY] No files modified. Run with --execute to perform actual cleanup.")
    else:
        print("\nExecuting actual cleanup...")
        execute_cleanup(plan, cat_data, accounts, alphas)

if __name__ == "__main__":
    main()
