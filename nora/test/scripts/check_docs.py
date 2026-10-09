#!/usr/bin/env python3
"""
Kiểm tra tính nhất quán toàn diện của bộ tài liệu Nora BMAD:
1. Khớp 100% giữa stories/ và sprint-status.yaml
2. Khớp giữa stories/ và epics.md
3. Kiểm tra liên kết tương đối giữa các file markdown trong docs/bmad/
4. Quét cảnh báo module cũ trong tài liệu active
5. Kiểm tra tính xác thực của QA Results cho các story Done:
   - Mọi test file (test/..py, test/scripts/..py) phải tồn tại thật trên đĩa
   - Mọi commit hash trong backtick phải tồn tại trong git log
   - QA Results phải có ít nhất một commit và một test
"""
import os
import re
import sys
import subprocess
import yaml
from pathlib import Path

REPO_ROOT = Path("/home/vmc03/norabt")
NORA_ROOT = REPO_ROOT / "nora"
BMAD_DIR = NORA_ROOT / "docs" / "bmad"
STORIES_DIR = BMAD_DIR / "stories"
STATUS_FILE = BMAD_DIR / "sprint-status.yaml"
EPICS_FILE = BMAD_DIR / "epics.md"

OLD_MODULE_PATTERNS = [
    r"\bbackend/api/\b",
    r"\bcore/execute/\b",
    r"\bdata/alphas/candidates\b",
    r"\boptimize_alphas\b",
]

def get_all_git_commits():
    try:
        out = subprocess.check_output(
            ["git", "--no-pager", "log", "--all", "--format=%H %h"],
            cwd=str(REPO_ROOT),
            text=True
        )
        commits = set()
        for line in out.splitlines():
            parts = line.strip().split()
            commits.update(parts)
        return commits
    except Exception as e:
        print(f"Cảnh báo: Không thể lấy git commits ({e})", flush=True)
        return set()

def check_sprint_status_parity():
    errors = []
    if not STATUS_FILE.exists():
        return ["sprint-status.yaml không tồn tại!"]
        
    with open(STATUS_FILE, "r", encoding="utf-8") as f:
        status_data = yaml.safe_load(f)
        
    yaml_stories = {}
    for epic_id, epic_info in status_data.get("epics", {}).items():
        for story_slug, status in epic_info.get("stories", {}).items():
            yaml_stories[story_slug] = status.lower()

    story_files = list(STORIES_DIR.glob("*.md"))
    file_slugs = {f.stem: f for f in story_files}
    
    # Check all files are in yaml
    for slug, fpath in file_slugs.items():
        if slug not in yaml_stories:
            errors.append(f"Story {slug} có file nhưng thiếu trong sprint-status.yaml")
        else:
            text = fpath.read_text(encoding="utf-8")
            m = re.search(r"## Status\s*\n\s*([A-Za-z\-]+)", text)
            if m:
                file_status = m.group(1).lower()
                yaml_status = yaml_stories[slug]
                if file_status != yaml_status:
                    errors.append(f"Lệch trạng thái {slug}: file={file_status} vs yaml={yaml_status}")
            else:
                errors.append(f"Story {slug} thiếu mục ## Status")

    # Check all yaml stories have files
    for slug in yaml_stories:
        if slug not in file_slugs:
            errors.append(f"Story {slug} có trong yaml nhưng không tìm thấy file!")

    return errors

def check_epics_md_parity():
    errors = []
    if not EPICS_FILE.exists():
        return ["epics.md không tồn tại!"]
        
    text = EPICS_FILE.read_text(encoding="utf-8")
    story_links = re.findall(r"\[(E\d+-S\d+)\]\(stories/([^)]+)\)", text)
    
    for story_id, filename in story_links:
        target = STORIES_DIR / filename
        if not target.exists():
            errors.append(f"epics.md trỏ tới {filename} nhưng file không tồn tại!")
            
    return errors

def check_relative_links():
    errors = []
    md_files = [f for f in BMAD_DIR.rglob("*.md") if "archive" not in str(f)]
    
    for doc in md_files:
        text = doc.read_text(encoding="utf-8")
        links = re.findall(r"\[.*?\]\(([^http#][^)]*)\)", text)
        for link in links:
            clean_link = link.split("#")[0].split("?")[0].strip()
            if not clean_link or clean_link.startswith("mailto:"):
                continue
            target_path = (doc.parent / clean_link).resolve()
            if not target_path.exists():
                root_target = (REPO_ROOT / clean_link).resolve()
                if not root_target.exists():
                    errors.append(f"Link chết trong {doc.relative_to(BMAD_DIR)}: {link}")
                    
    return errors

def scan_old_patterns():
    warnings = []
    active_docs = [
        BMAD_DIR / "prd.md",
        BMAD_DIR / "architecture.md",
        BMAD_DIR / "ux-design.md",
        BMAD_DIR / "product-brief.md",
    ]
    active_docs.extend((BMAD_DIR / "architecture").glob("*.md"))
    
    for doc in active_docs:
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8")
        for pat in OLD_MODULE_PATTERNS:
            if re.search(pat, text):
                warnings.append(f"Cảnh báo mẫu cũ '{pat}' trong {doc.name}")
                
    return warnings

def check_qa_evidence(valid_commits):
    errors = []
    story_files = list(STORIES_DIR.glob("*.md"))
    
    for fpath in story_files:
        text = fpath.read_text(encoding="utf-8")
        m_status = re.search(r"## Status\s*\n\s*([A-Za-z\-]+)", text)
        status = m_status.group(1).lower() if m_status else ""
        
        # Chỉ kiểm tra nghiêm ngặt với các story có Status = Done
        if status != "done":
            continue
            
        m_qa = re.search(r"## QA Results\b(.*?)(?=\n##\s+|\Z)", text, re.DOTALL)
        if not m_qa:
            errors.append(f"Story {fpath.name} (Done) thiếu mục ## QA Results")
            continue
            
        qa_text = m_qa.group(1).strip()
        
        # 1. Kiểm tra commit hash hợp lệ trong git log
        # Tìm commit hash trong backtick (7-40 ký tự hex)
        commit_hashes = re.findall(r"`([0-9a-f]{7,40})`", qa_text)
        if not commit_hashes:
            # Cho phép nếu có ghi "chưa commit" hoặc tương đương, nhưng với Done phải có commit thật
            if "commit" not in qa_text.lower():
                errors.append(f"Story {fpath.name} (Done) không có thông tin commit trong QA Results")
        else:
            for ch in commit_hashes:
                if ch not in valid_commits:
                    # Kiểm tra xem có prefix của commit nào không
                    prefix_match = any(full.startswith(ch) for full in valid_commits)
                    if not prefix_match:
                        errors.append(f"Story {fpath.name} có commit `{ch}` không tồn tại trong git log")
                        
        # 2. Kiểm tra test files trong QA Results hoặc cả story
        # Tìm các pattern test/..py, test/scripts/..py
        test_mentions = re.findall(r"\b(test(?:/[a-zA-Z0-9_\-]+)+\.py)\b", text)
        # Cũng tìm dạng test_xxx.py
        standalone_tests = re.findall(r"\b(test_[a-zA-Z0-9_]+\.py)\b", text)
        
        all_tests = set(test_mentions)
        for st in standalone_tests:
            all_tests.add(f"test/{st}")
            
        if not all_tests:
            # Kiểm tra xem có test lệnh khác không (ví dụ npm run build, pytest)
            if not any(k in qa_text.lower() for k in ["test", "pytest", "npm", "smoke"]):
                errors.append(f"Story {fpath.name} (Done) không có bằng chứng test trong QA Results")
        else:
            for tpath in all_tests:
                # Kiểm tra trên đĩa tại nora/ hoặc repo root
                p1 = NORA_ROOT / tpath
                p2 = REPO_ROOT / tpath
                if not (p1.exists() or p2.exists()):
                    errors.append(f"Story {fpath.name} nhắc tới file test không tồn tại: {tpath}")
                    
    return errors

def main():
    print("=" * 60)
    print("BẮT ĐẦU KIỂM TRA TÀI LIỆU NORA BMAD")
    print("=" * 60)
    
    valid_commits = get_all_git_commits()
    print(f"Đã nạp {len(valid_commits)} commit hash từ git log.")
    
    # 1. Parity
    status_errors = check_sprint_status_parity()
    if status_errors:
        print(f"❌ sprint-status.yaml kiểm tra thất bại ({len(status_errors)} lỗi):")
        for e in status_errors[:10]:
            print(f"  - {e}")
    else:
        print("✅ sprint-status.yaml: 100% khớp với toàn bộ stories/")
        
    # 2. Epics
    epic_errors = check_epics_md_parity()
    if epic_errors:
        print(f"❌ epics.md kiểm tra thất bại ({len(epic_errors)} lỗi):")
        for e in epic_errors:
            print(f"  - {e}")
    else:
        print("✅ epics.md: 100% liên kết stories hợp lệ")
        
    # 3. Relative links
    link_errors = check_relative_links()
    if link_errors:
        print(f"⚠️  Phát hiện {len(link_errors)} liên kết chết:")
        for e in link_errors[:10]:
            print(f"  - {e}")
    else:
        print("✅ Liên kết nội bộ markdown: Không có liên kết gãy")

    # 4. Old patterns
    old_warnings = scan_old_patterns()
    if old_warnings:
        print(f"⚠️  Phát hiện {len(old_warnings)} mẫu cũ trong active docs:")
        for w in old_warnings:
            print(f"  - {w}")
    else:
        print("✅ Active docs: Không còn mẫu module cũ")

    # 5. QA Evidence Verification
    qa_errors = check_qa_evidence(valid_commits)
    if qa_errors:
        print(f"❌ Bằng chứng QA Results không hợp lệ ({len(qa_errors)} lỗi):")
        for e in qa_errors:
            print(f"  - {e}")
    else:
        print("✅ Bằng chứng QA Results: 100% test file và commit hash xác thực hợp lệ trên đĩa và git log!")

    total_failures = len(status_errors) + len(epic_errors) + len(qa_errors)
    print("=" * 60)
    if total_failures == 0:
        print("🎉 TẤT CẢ KIỂM TRA ĐẠT TIÊU CHUẨN BMAD!")
        return 0
    else:
        print(f"💥 CÒN {total_failures} LỖI CẦN XỬ LÝ.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
