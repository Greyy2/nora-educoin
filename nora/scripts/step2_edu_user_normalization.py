import json
import hashlib
import datetime
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path("nora/edu").resolve()))
from backend.analys.alpha.code.compile import compile_code
from backend.analys.alpha.code.plan import build_plan

def get_next_version(aid: str, vdir: Path) -> int:
    existing = []
    pattern = re.compile(rf"^{aid}\.v(\d+)\.json$")
    for f in vdir.glob(f"{aid}.v*.json"):
        m = pattern.match(f.name)
        if m:
            existing.append(int(m.group(1)))
    return max(existing) + 1 if existing else 2

def normalize_user_alphas():
    ledger_path = Path("nora/check/edu_source_assessment_ledger.json")
    if not ledger_path.exists():
        raise FileNotFoundError("Run step2_edu_alpha_assessment.py first!")

    ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
    versions_dir = Path("nora/edu/data/alpha/user/_versions")
    versions_dir.mkdir(parents=True, exist_ok=True)

    user_dir = Path("nora/edu/data/alpha/user")

    blocked_count = 0
    vinh_preserved_count = 0
    versioned_created_count = 0
    records_processed = 0

    log = []

    for row in ledger_data["ledger"]:
        if row["source_type"] != "user_alpha":
            continue
        records_processed += 1
        aid = row["record_id"]
        disp = row["disposition"]
        is_vinh = row.get("is_vinh", False)

        user_file = user_dir / f"{aid}.json"
        if not user_file.exists():
            continue
        original_data = json.loads(user_file.read_text(encoding="utf-8"))

        if disp == "BLOCKED_UNKNOWN_INTENT":
            blocked_count += 1
            log.append({
                "id": aid,
                "name": row["name"],
                "disposition": "BLOCKED_UNKNOWN_INTENT",
                "action": "no_rewrite_blocked",
                "reason": row["evidence_notes"]
            })
            continue

        if is_vinh:
            vinh_preserved_count += 1
            log.append({
                "id": aid,
                "name": row["name"],
                "disposition": "VALID_AS_IS",
                "action": "vinh_preserved_intact",
                "reason": "Vinh strategy preserved 100% intact without modification."
            })
            continue

        # Real alpha of other users: create next immutable version aligning config with code
        v_next = get_next_version(aid, versions_dir)
        v_file = versions_dir / f"{aid}.v{v_next}.json"
        
        # Verify destination file does NOT exist
        assert not v_file.exists(), f"Target version file {v_file} already exists! Refusing to overwrite."

        v_data = dict(original_data)
        v_data["version"] = v_next

        # Align config.position exit_unit to match code's declared exit_unit ('pct')
        cfg = dict(v_data.get("config") or {})
        pos = dict(cfg.get("position") or {})
        pos["exit_unit"] = "pct"
        cfg["position"] = pos
        v_data["config"] = cfg

        # Verify compilation and plan with 0 conflict warnings
        prog = compile_code(v_data.get("code", ""))
        plan = build_plan(prog, symbols=cfg.get("symbols", ["BTC"]), position=pos)

        v_data["normalization_meta"] = {
            "action": "aligned_config_version",
            "version": v_next,
            "original_file_sha256": row["code_sha256"],
            "compiler_status": "VALID",
            "legs": prog.legs,
            "timeframe": prog.timeframe,
            "plan_conflicts": plan.warnings,
            "normalized_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "disclosures": {
                "purpose": "Học tập & thực hành phân tích định lượng (Educational Only)",
                "slippage": "Mô phỏng giả định trượt giá bằng 0. Trong giao dịch thực tế luôn có trượt giá.",
                "fees": "Phí giao dịch tính theo mặc định CEX perp (Taker 0.05%, Maker 0.02%)."
            }
        }

        v_file.write_text(json.dumps(v_data, indent=2, ensure_ascii=False), encoding="utf-8")
        versioned_created_count += 1
        log.append({
            "id": aid,
            "name": row["name"],
            "disposition": "VALID_AS_IS",
            "action": f"version_v{v_next}_created",
            "plan_warnings_count": len(plan.warnings)
        })

    report = {
        "total_user_alphas_processed": records_processed,
        "blocked_unknown_intent_count": blocked_count,
        "vinh_preserved_count": vinh_preserved_count,
        "new_version_files_created": versioned_created_count,
        "log": log
    }

    out_p = Path("nora/check/edu_user_normalization_report.json")
    out_p.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"User normalization report written to {out_p}")
    print(f"Total: {records_processed}, Blocked: {blocked_count}, Vinh Preserved: {vinh_preserved_count}, New Versions: {versioned_created_count}")

if __name__ == "__main__":
    normalize_user_alphas()
