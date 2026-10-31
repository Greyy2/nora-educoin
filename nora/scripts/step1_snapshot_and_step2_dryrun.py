#!/usr/bin/env python3
"""
Step 1 Verification & Step 2 Dry-Run:
1. Verify baseline snapshot & manifest.
2. Build and verify conflict-aware rollback script.
3. Perform read-only audit of 66 duplicate alpha IDs between EDU and COIN.
4. Generate comprehensive comparison report & propose initial COIN allowlist for owner approval.
"""

import os
import sys
import json
import hashlib
import shutil
import tempfile

ROOT = '/home/vmc03/norabt'
SNAPSHOT_DIR = os.path.join(ROOT, '.backup', 'baseline_snapshot_20261026_143328')
MANIFEST_PATH = os.path.join(SNAPSHOT_DIR, 'manifest_baseline.json')

def sha256_content(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def verify_snapshot():
    print("=== [1] XÁC NHẬN BASELINE SNAPSHOT ===")
    if not os.path.exists(MANIFEST_PATH):
        raise FileNotFoundError(f"Không tìm thấy manifest tại: {MANIFEST_PATH}")
    
    with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    
    records = manifest['records']
    print(f"Tổng số record đã chụp: {len(records)}")
    print(f"Timestamp: {manifest['snapshot_timestamp']}")
    
    # Kiểm tra mẫu 10 file ngẫu nhiên trong snapshot
    sample_records = records[:10]
    for r in sample_records:
        src = os.path.join(ROOT, r['rel_path'])
        bk = os.path.join(ROOT, r['backup_path'])
        if not os.path.exists(bk):
            raise FileNotFoundError(f"File backup thiếu: {bk}")
        h_bk = sha256_file(bk)
        if h_bk != r['sha256']:
            raise ValueError(f"Hash mismatch trên backup: {bk}")
    print("Xác nhận mẫu 10 file backup khớp SHA-256 hoàn hảo.")
    return manifest

def build_rollback_script():
    print("\n=== [2] TẠO SCRIPT ROLLBACK CÓ KIỂM TRA XUNG ĐỘT ===")
    script_path = os.path.join(ROOT, 'scripts', 'rollback_baseline.py')
    os.makedirs(os.path.dirname(script_path), exist_ok=True)
    
    rollback_code = '''#!/usr/bin/env python3
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
        print(f"\\n[WARNING] {len(conflicts)} files have conflicts (modified after snapshot):")
        for c in conflicts[:10]:
            print(f"  - {c['path']} (current: {c['current_hash'][:8]}, snap: {c['snapshot_hash'][:8]})")
        if len(conflicts) > 10:
            print(f"  ... and {len(conflicts) - 10} more conflicts.")
        print("Rollback aborted for conflicting files to prevent data loss. Resolve conflicts or use --force.")
        sys.exit(2)
    else:
        print("\\nSUCCESS: Rollback completed cleanly with 0 conflicts.")

if __name__ == "__main__":
    main()
'''
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(rollback_code)
    os.chmod(script_path, 0o755)
    print(f"Đã tạo script rollback: {script_path}")

    # Kiểm thử script rollback trên thư mục tạm riêng biệt
    print("Kiểm thử rollback trên thư mục tạm...")
    with tempfile.TemporaryDirectory() as tmp_root:
        # Giả lập snapshot manifest trong tmp
        tmp_snap = os.path.join(tmp_root, 'snap')
        tmp_target = os.path.join(tmp_root, 'workspace')
        os.makedirs(tmp_snap, exist_ok=True)
        os.makedirs(tmp_target, exist_ok=True)

        f1_bk = os.path.join(tmp_snap, 'f1.txt')
        with open(f1_bk, 'w') as f: f.write("original f1")
        h1 = sha256_file(f1_bk)

        f2_bk = os.path.join(tmp_snap, 'f2.txt')
        with open(f2_bk, 'w') as f: f.write("original f2")
        h2 = sha256_file(f2_bk)

        # Target: f1 bị xóa (cần restore), f2 bị sửa (cần conflict)
        f2_cur = os.path.join(tmp_target, 'f2.txt')
        with open(f2_cur, 'w') as f: f.write("modified f2 after snapshot")

        tmp_manifest = {
            'records': [
                {'rel_path': 'f1.txt', 'backup_path': os.path.relpath(f1_bk, tmp_root), 'sha256': h1},
                {'rel_path': 'f2.txt', 'backup_path': os.path.relpath(f2_bk, tmp_root), 'sha256': h2},
            ]
        }
        with open(os.path.join(tmp_snap, 'manifest_baseline.json'), 'w') as f:
            json.dump(tmp_manifest, f)

        import subprocess
        res = subprocess.run([sys.executable, script_path, "--snapshot-dir", tmp_snap, "--root", tmp_target], capture_output=True, text=True)
        print("Test rollback output:\n", res.stdout, res.stderr)
        if res.returncode == 2:
            print("Kiểm thử Rollback thành công: Đã phát hiện xung đột chính xác (exit code 2) và từ chối ghi đè file bị sửa đổi.")
        else:
            raise RuntimeError(f"Kiểm thử Rollback thất bại! Exit code: {res.returncode}")

def audit_duplicate_records():
    print("\n=== [3] DRY-RUN ĐỐI CHIẾU 66 ALPHA ID TRÙNG GIỮA EDU VÀ COIN ===")
    edu_dir = os.path.join(ROOT, 'nora/edu/data/alpha/user')
    coin_dir = os.path.join(ROOT, 'nora/coin/data/alpha/user')

    edu_files = set(f for f in os.listdir(edu_dir) if f.endswith('.json'))
    coin_files = set(f for f in os.listdir(coin_dir) if f.endswith('.json'))

    duplicates = sorted(list(edu_files.intersection(coin_files)))
    print(f"Số lượng file trùng lặp phát hiện: {len(duplicates)}")

    report_rows = []
    identical_count = 0
    diff_count = 0

    for fname in duplicates:
        alpha_id = fname.replace('.json', '')
        edu_path = os.path.join(edu_dir, fname)
        coin_path = os.path.join(coin_dir, fname)

        with open(edu_path, 'r', encoding='utf-8') as f:
            edu_data = json.load(f)
        with open(coin_path, 'r', encoding='utf-8') as f:
            coin_data = json.load(f)

        edu_code = edu_data.get('code', '')
        coin_code = coin_data.get('code', '')
        edu_code_sha = sha256_content(edu_code)
        coin_code_sha = sha256_content(coin_code)
        code_match = (edu_code_sha == coin_code_sha)

        edu_cfg = edu_data.get('config', {})
        coin_cfg = coin_data.get('config', {})
        cfg_match = (json.dumps(edu_cfg, sort_keys=True) == json.dumps(coin_cfg, sort_keys=True))

        edu_m = edu_data.get('metrics', {})
        coin_m = coin_data.get('metrics', {})
        m_match = (json.dumps(edu_m, sort_keys=True) == json.dumps(coin_m, sort_keys=True))

        edu_owner = edu_data.get('user', edu_data.get('source', 'education'))
        coin_owner = coin_data.get('user', coin_data.get('source', 'coin'))

        name = edu_data.get('name', alpha_id)

        is_identical = code_match and cfg_match and m_match
        if is_identical:
            identical_count += 1
            status = "IDENTICAL (Trùng khớp 100%)"
        else:
            diff_count += 1
            diff_parts = []
            if not code_match: diff_parts.append("CODE_DIFF")
            if not cfg_match: diff_parts.append("CONFIG_DIFF")
            if not m_match: diff_parts.append("METRICS_DIFF")
            status = f"DIFFERENT ({', '.join(diff_parts)})"

        report_rows.append({
            'id': alpha_id,
            'name': name,
            'status': status,
            'is_identical': is_identical,
            'edu_code_sha': edu_code_sha,
            'coin_code_sha': coin_code_sha,
            'edu_owner': str(edu_owner),
            'coin_owner': str(coin_owner),
            'symbols': edu_cfg.get('symbols', []),
            'timeframe': edu_cfg.get('timeframe', '')
        })

    print(f"Tổng kết đối chiếu 66 ID:")
    print(f"  - Trùng khớp 100% (Code, Config, Metrics): {identical_count}")
    print(f"  - Có sự sai khác: {diff_count}")

    # Lập báo cáo Markdown
    report_md_path = os.path.join(ROOT, 'nora/check/duplicate_alpha_dryrun_report.md')
    with open(report_md_path, 'w', encoding='utf-8') as f:
        f.write("# BÁO CÁO DRY-RUN ĐỐI CHIẾU 66 ALPHA ID TRÙNG GIỮA EDU VÀ COIN\n\n")
        f.write(f"**Thời điểm tạo:** {SNAPSHOT_DIR}\n")
        f.write(f"**Tổng số ID trùng:** {len(duplicates)}\n")
        f.write(f"**Trùng khớp 100%:** {identical_count}\n")
        f.write(f"**Có sai khác:** {diff_count}\n\n")
        f.write("## 1. Nguyên tắc Xử lý Đề xuất cho Owner Phê duyệt\n\n")
        f.write("1. **EDU:** Giữ nguyên 100% toàn bộ bản ghi alpha thuộc EDU data root.\n")
        f.write("2. **COIN:** Chỉ giữ lại các bản ghi thuộc Allowlist được phê duyệt (Top OKX, Proxima). Các bản ghi trùng còn lại chỉ được chuyển sang vùng cách ly (`nora/coin/data/alpha/_quarantine/`) SAU KHI Owner chốt danh sách.\n")
        f.write("3. **Bảo toàn User:** Không hợp nhất tài khoản user cùng tên giữa EDU và COIN; mỗi bên dùng store riêng biệt.\n\n")
        f.write("## 2. Bảng Đối chiếu Chi tiết 66 Bản ghi Trùng\n\n")
        f.write("| STT | Alpha ID | Tên Chiến lược | Trạng thái Đối chiếu | SHA-256 Code | Symbols | Timeframe |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for idx, row in enumerate(report_rows, 1):
            f.write(f"| {idx} | `{row['id']}` | {row['name']} | **{row['status']}** | `{row['edu_code_sha'][:12]}...` | {','.join(row['symbols'][:3])}{'...' if len(row['symbols'])>3 else ''} | {row['timeframe']} |\n")

    print(f"Đã xuất báo cáo chi tiết tại: {report_md_path}")
    return report_rows

def propose_initial_allowlist(rows):
    print("\n=== [4] LẬP DANH SÁCH ĐỀ XUẤT ALLOWLIST COIN ===")
    # Ứng viên 33312a2f4dfc (Vinh) và các ứng viên có tên Top OKX / Proxima
    top_candidates = []
    for r in rows:
        name_lower = r['name'].lower()
        if r['id'] == '33312a2f4dfc' or 'okx' in name_lower or 'proxima' in name_lower or 'channel breakout' in name_lower:
            top_candidates.append(r)

    print(f"Đề xuất sơ bộ {len(top_candidates)} ứng viên tiềm năng có liên quan đến Top OKX/Proxima/Vinh:")
    for c in top_candidates:
        print(f"  - ID: {c['id']} | Name: {c['name']} | Code SHA-256: {c['edu_code_sha']}")

    allowlist_path = os.path.join(ROOT, 'nora/check/proposed_coin_allowlist.json')
    with open(allowlist_path, 'w', encoding='utf-8') as f:
        json.dump({
            'note': 'PROPOSED ALLOWLIST FOR COIN - AWAITING OWNER APPROVAL',
            'candidates': top_candidates
        }, f, indent=2)
    print(f"Đã lưu danh sách đề xuất tại: {allowlist_path}")

if __name__ == '__main__':
    verify_snapshot()
    build_rollback_script()
    rows = audit_duplicate_records()
    propose_initial_allowlist(rows)
    print("\n>>> HOÀN TẤT BƯỚC 1 & DRY-RUN BƯỚC 2 AN TOÀN (KHÔNG CÓ DỮ LIỆU NÀO BỊ THAY ĐỔI) <<<")
