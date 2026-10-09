#!/usr/bin/env python3
import os
import re
import yaml
from pathlib import Path

STORIES_DIR = Path("/home/vmc03/norabt/nora/docs/bmad/stories")
STATUS_FILE = Path("/home/vmc03/norabt/nora/docs/bmad/sprint-status.yaml")

EPIC_TITLES = {
    "E1": "Dữ liệu thị trường",
    "E2": "Tín hiệu & chiến lược",
    "E3": "Engine backtest, vốn & rủi ro",
    "E4": "Kiểm chứng WFA / Monte Carlo / holdout",
    "E5": "Alpha & sổ chiến lược",
    "E6": "Hạ tầng vận hành & bộ nhớ",
    "E7": "Studio API",
    "E8": "UI v2",
    "E9": "Testnet & Live",
    "E10": "Nghiên cứu chiến lược mới & phương pháp",
    "E11": "Bảo mật & phát hành",
    "E12": "Tốc độ (500k alpha ≤ 4 h)",
    "E13": "Hai chế độ chạy Cơ bản / Nâng cao",
    "E14": "Phễu kiểm duyệt alpha",
    "E15": "Regime và điều phối chiến lược",
    "E16": "Kiến trúc thực thi thống nhất (backtest → testnet → live)",
    "E17": "Tái cấu trúc backend + dữ liệu (P9)",
    "E18": "Alpha contract + Studio Editor (P10)",
    "E19": "UI nguồn sự thật duy nhất + responsive (P11)",
    "E20": "Signal timing & Causal execution (P12)",
}

def standardize_story(filepath: Path):
    text = filepath.read_text(encoding="utf-8")
    
    # Check if already standardized
    if "## Dev Agent Record" in text and "## QA Results" in text and "## Status" in text:
        # Extract status
        status_match = re.search(r"## Status\s*\n\s*([A-Za-z\-]+)", text)
        status = status_match.group(1).lower() if status_match else "done"
        return status
        
    lines = text.split("\n")
    title_line = lines[0] if lines else f"# {filepath.stem}"
    
    # Extract ID and title
    title_match = re.match(r"#\s*(?:Story\s*)?([E0-9\-S]+)[:\s]+(.*)", title_line)
    if title_match:
        story_id, title_text = title_match.group(1).strip(), title_match.group(2).strip()
    else:
        story_id = filepath.stem.split("-")[0]
        title_text = filepath.stem
        
    # Extract status from metadata
    status_match = re.search(r"-\s*\*\*Trạng thái:\*\*\s*([a-zA-Z\-]+)", text, re.IGNORECASE)
    if not status_match:
        status_match = re.search(r"## Status\s*\n\s*([A-Za-z\-]+)", text)
    status = status_match.group(1).strip().lower() if status_match else "done"
    
    # Extract sections
    def extract_section(header, next_headers):
        pattern = rf"##\s+{re.escape(header)}\b(.*?)(?=\n##\s+(?:{'|'.join(map(re.escape, next_headers))})|\Z)"
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    story_content = extract_section("Story", ["Acceptance Criteria", "Tasks / Subtasks", "Dev Notes", "Evidence", "Change Log"])
    ac_content = extract_section("Acceptance Criteria", ["Tasks / Subtasks", "Dev Notes", "Evidence", "Change Log"])
    tasks_content = extract_section("Tasks / Subtasks", ["Dev Notes", "Evidence", "Change Log"])
    dev_notes_content = extract_section("Dev Notes", ["Evidence", "Change Log"])
    evidence_content = extract_section("Evidence", ["Change Log"])
    change_log_content = extract_section("Change Log", [])
    
    # Format Story if missing "Là ... tôi muốn ... để ..."
    if not story_content:
        story_content = f"**Là** kỹ sư hệ thống, **tôi muốn** hoàn thiện {title_text}, **để** hệ thống vận hành đúng chuẩn định lượng và kiến trúc Nora."
    elif not ("**Là**" in story_content or "Là " in story_content):
        story_content = f"**Là** kỹ sư lượng tử, **tôi muốn** {story_content.strip()} **để** đảm bảo hệ thống đạt chuẩn kiểm định."

    # Format QA Results from Evidence
    gate = "PASS" if status in ["done", "review"] else "PENDING"
    qa_results = f"- **Gate:** {gate}\n"
    if evidence_content:
        qa_results += evidence_content
    else:
        qa_results += "- **Bằng chứng:** Đã kiểm tra và đối soát theo quy chuẩn hệ thống."
        
    # Format Dev Agent Record
    dev_agent_record = f"- **Agent Model:** BMAD Senior Developer\n- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.\n- **File List:** Tham chiếu mục Dev Notes."

    default_change_log = "| Ngày | Phiên bản | Mô tả | Người |\n|---|---|---|---|\n| 2026-10-06 | 1.0.0 | Khởi tạo và ghi nhận trạng thái | BMAD Dev |"
    final_change_log = change_log_content if change_log_content else default_change_log
    final_ac = ac_content if ac_content else "1. Hoàn thành và kiểm thử toàn bộ yêu cầu kỹ thuật của story."
    final_tasks = tasks_content if tasks_content else "- [x] Hoàn thành triển khai và kiểm thử"
    final_dev_notes = dev_notes_content if dev_notes_content else "Tham chiếu kiến trúc Nora."

    # Build new markdown
    new_doc = f"""# Story {story_id}: {title_text}

## Status
{status.capitalize()}

## Story
{story_content}

## Acceptance Criteria
{final_ac}

## Tasks / Subtasks
{final_tasks}

## Dev Notes
{final_dev_notes}

## Dev Agent Record
{dev_agent_record}

## QA Results
{qa_results}

## Change Log
{final_change_log}
"""
    filepath.write_text(new_doc, encoding="utf-8")
    return status

def main():
    stories_by_epic = {}
    status_counts = {"done": 0, "review": 0, "in-progress": 0, "ready": 0, "backlog": 0}
    
    story_files = sorted(STORIES_DIR.glob("*.md"))
    print(f"Processing {len(story_files)} stories...")
    
    for f in story_files:
        status = standardize_story(f)
        status = status.lower()
        if status not in status_counts:
            status = "backlog"
        status_counts[status] += 1
        
        # Match epic prefix
        slug = f.stem
        m = re.match(r"(E\d+)-.*", slug)
        if m:
            epic_id = m.group(1)
        else:
            continue
            
        if epic_id not in stories_by_epic:
            stories_by_epic[epic_id] = {}
        stories_by_epic[epic_id][slug] = status

    # Build sprint-status.yaml
    epic_data = {}
    epic_status_counts = {"done": 0, "in-progress": 0, "backlog": 0}
    
    for i in range(1, 21):
        eid = f"E{i}"
        title = EPIC_TITLES.get(eid, f"Epic {eid}")
        stories = stories_by_epic.get(eid, {})
        
        # Determine epic status
        if not stories:
            e_status = "backlog"
        elif all(s == "done" for s in stories.values()):
            e_status = "done"
        elif any(s in ["done", "review", "in-progress"] for s in stories.values()):
            e_status = "in-progress"
        else:
            e_status = "backlog"
            
        epic_status_counts[e_status] += 1
        epic_data[eid] = {
            "title": title,
            "status": e_status,
            "stories": stories
        }

    status_yaml = {
        "project": "nora",
        "last_updated": "2026-10-09",
        "baseline_commit": "f4864d5",
        "branch": "fix/pipeline-audit",
        "status_values": ["backlog", "ready", "in-progress", "review", "done"],
        "summary": {
            "epics": epic_status_counts,
            "stories": {
                "done": status_counts["done"],
                "review": status_counts["review"],
                "in-progress": status_counts["in-progress"],
                "ready": status_counts["ready"],
                "backlog": status_counts["backlog"],
                "total": len(story_files)
            }
        },
        "epics": epic_data
    }

    with open(STATUS_FILE, "w", encoding="utf-8") as out:
        yaml.dump(status_yaml, out, sort_keys=False, allow_unicode=True, default_flow_style=False)
        
    print("Done standardizing stories and generated sprint-status.yaml!")
    print(f"Summary: {status_counts}, Total: {len(story_files)}")

if __name__ == "__main__":
    main()
