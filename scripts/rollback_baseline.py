#!/usr/bin/env python3
"""
Conflict-Aware Rollback Tool for Nora Baseline Snapshot.
Restores files from a specific snapshot with strict per-file conflict detection:
- If target file has been modified after snapshot (hash != snapshot_hash and hash != backup_hash),
  it STOPS and reports CONFLICT instead of blind overwrite.
- Supports dry-run mode (--dry-run).
"""
import os
import sys
import json
import hashlib
import shutil
import argparse

def sha256_file(p):
    if not os.path.exists(p):
        return None
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def main():
    parser = argparse.ArgumentParser(description="Rollback Nora baseline snapshot with conflict detection.")
    parser.add_argument("--snapshot-dir", required=True, help="Path to baseline_snapshot_<ts> directory")
    parser.add_argument("--root", default="/home/vmc03/norabt", help="Repository root path")
    parser.add_argument("--dry-run", action="store_true", help="Simulate rollback without writing files")
    parser.add_argument("--force", action="store_true", help="Force overwrite even on conflict (NOT recommended)")
    args = parser.parse_args()

    manifest_path = os.path.join(args.snapshot_dir, "manifest_baseline.json")
    if not os.path.exists(manifest_path):
        print(f"ERROR: Manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    records = manifest["records"]
    print(f"Loaded {len(records)} records from {manifest_path}")
    print(f"Mode: {'DRY-RUN (Simulated)' if args.dry_run else 'LIVE RESTORE'}")

    restored = 0
    unchanged = 0
    conflicts = []

    for r in records:
        target_path = os.path.join(args.root, r["rel_path"])
        backup_path = os.path.join(args.snapshot_dir, r["rel_path"])

        curr_hash = sha256_file(target_path)
        snap_hash = r["sha256"]

        if curr_hash == snap_hash:
            unchanged += 1
            continue

        # Target file differs from snapshot
        if curr_hash is not None and not args.force:
            # File was modified after snapshot!
            conflicts.append({
                "path": r["rel_path"],
                "snapshot_hash": snap_hash,
                "current_hash": curr_hash
            })
            continue

        # Restore is safe (missing or force enabled)
        if not args.dry_run:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(backup_path, target_path)
        restored += 1

    print(f"Summary: Unchanged={unchanged}, Restored={restored}, Conflicts={len(conflicts)}")
    if conflicts:
        print(f"\n[WARNING] {len(conflicts)} files have conflicts (modified after snapshot):")
        for c in conflicts[:10]:
            print(f"  - {c['path']} (current: {c['current_hash'][:8]}, snap: {c['snapshot_hash'][:8]})")
        if len(conflicts) > 10:
            print(f"  ... and {len(conflicts) - 10} more conflicts.")
        print("Rollback aborted for conflicting files to prevent data loss. Resolve conflicts or use --force.")
        sys.exit(2)
    else:
        print("\nSUCCESS: Rollback completed cleanly with 0 conflicts.")

if __name__ == "__main__":
    main()
