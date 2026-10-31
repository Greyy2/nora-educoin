import os
import sys
import json
import hashlib
import datetime
from pathlib import Path

# Add EDU path for compiler
sys.path.insert(0, str(Path("nora/edu").resolve()))
from backend.analys.alpha.code.compile import compile_code, compile_strategy_module

def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def normalize_code(code: str) -> str:
    return "\n".join(line.rstrip() for line in str(code).strip().splitlines())

def test_compile(code: str, is_system: bool = False):
    if not code:
        return {"status": "EMPTY_CODE", "error": "Code is empty"}
    try:
        if is_system:
            prog = compile_strategy_module(code)
            return {
                "status": "VALID",
                "kind": "system_module",
                "name": getattr(prog, "name", ""),
            }
        else:
            prog = compile_code(code)
            return {
                "status": "VALID",
                "kind": "custom_dsl",
                "timeframe": getattr(prog, "timeframe", None),
                "legs": getattr(prog, "legs", []),
                "position_overrides": getattr(prog, "position_overrides", {}),
                "warnings": getattr(prog, "warnings", []),
            }
    except Exception as e:
        return {
            "status": "COMPILE_ERROR",
            "error_type": type(e).__name__,
            "error_message": str(e)
        }

def build_frozen_inventory():
    base_dir = Path("nora/edu/data/alpha")
    user_dir = base_dir / "user"
    versions_dir = user_dir / "_versions"
    education_samples_path = base_dir / "education/samples.json"
    strategies_dir = base_dir / "strategies"
    archive_dir = base_dir / "_unlinked_archive"

    # 1. Active User Alphas (57)
    user_alphas = []
    code_hash_to_group = {}
    group_counter = 1

    for p in sorted(user_dir.glob("*.json")):
        if p.name.startswith(".") or not p.is_file():
            continue
        raw_text = p.read_text(encoding="utf-8")
        file_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        data = json.loads(raw_text)
        
        aid = p.stem
        code = data.get("code", "")
        norm_code = normalize_code(code)
        c_hash = sha256_str(norm_code) if norm_code else ""
        
        if c_hash:
            if c_hash not in code_hash_to_group:
                code_hash_to_group[c_hash] = f"GROUP_{group_counter:03d}"
                group_counter += 1
            group_id = code_hash_to_group[c_hash]
        else:
            group_id = "NO_CODE"

        config = data.get("config") or {}
        config_str = json.dumps(config, sort_keys=True, ensure_ascii=False)
        cfg_hash = sha256_str(config_str)

        compile_res = test_compile(code)

        user_alphas.append({
            "id": aid,
            "file_path": str(p),
            "owner_id": data.get("owner_id"),
            "name": data.get("name") or data.get("title", ""),
            "status": data.get("status"),
            "source": data.get("source"),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "file_sha256": file_sha256,
            "code_sha256": c_hash,
            "config_sha256": cfg_hash,
            "duplicate_group": group_id,
            "compile_status": compile_res["status"],
            "compile_details": compile_res,
            "code_snippet": code[:120].strip() if code else "",
            "raw_record": data
        })

    # 2. Education Samples (50)
    education_samples = []
    if education_samples_path.exists():
        raw_samples = json.loads(education_samples_path.read_text(encoding="utf-8"))
        for idx, sample in enumerate(raw_samples):
            code = sample.get("code", "")
            norm_code = normalize_code(code)
            c_hash = sha256_str(norm_code) if norm_code else ""
            compile_res = test_compile(code)

            education_samples.append({
                "index": idx,
                "key": sample.get("key"),
                "name": sample.get("name"),
                "category": sample.get("category"),
                "difficulty": sample.get("difficulty"),
                "summary": sample.get("summary"),
                "code_sha256": c_hash,
                "compile_status": compile_res["status"],
                "compile_details": compile_res,
                "raw_sample": sample
            })

    # 3. Frontend Onboarding Examples (3)
    # Dynamically extract from EduStudioOnboarding.jsx to ensure 100% agreement
    onboarding_path = Path("nora/edu/frontend/src/components/alpha/studio/EduStudioOnboarding.jsx")
    onboarding_samples = []
    if onboarding_path.exists():
        import re
        text = onboarding_path.read_text(encoding="utf-8")
        pattern = re.compile(r"id:\s*'([^']+)',\s*name:\s*'([^']+)',\s*timeframe:\s*'([^']+)',.*?code:\s*`([^`]+)`", re.DOTALL)
        for match in pattern.finditer(text):
            obs_id = match.group(1)
            obs_name = match.group(2)
            obs_tf = match.group(3)
            obs_code = match.group(4)
            c_hash = sha256_str(normalize_code(obs_code))
            compile_res = test_compile(obs_code)
            onboarding_samples.append({
                "id": obs_id,
                "name": obs_name,
                "timeframe": obs_tf,
                "code": obs_code,
                "code_sha256": c_hash,
                "compile_status": compile_res["status"],
                "compile_details": compile_res
            })

    # 4. System Strategies (3)
    system_strategies = []
    for sp in sorted(strategies_dir.glob("*.py")):
        if sp.name.startswith("__"):
            continue
        content = sp.read_text(encoding="utf-8")
        s_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        c_res = test_compile(content, is_system=True)
        system_strategies.append({
            "name": sp.name,
            "file_path": str(sp),
            "file_sha256": s_hash,
            "compile_status": c_res["status"],
            "compile_details": c_res
        })

    # 5. Active User Versions (13)
    user_versions = []
    if versions_dir.exists():
        for vp in sorted(versions_dir.glob("*.json")):
            v_text = vp.read_text(encoding="utf-8")
            v_sha = hashlib.sha256(v_text.encode("utf-8")).hexdigest()
            try:
                vd = json.loads(v_text)
            except Exception:
                vd = {}
            code = vd.get("code", "")
            c_hash = sha256_str(normalize_code(code)) if code else ""
            user_versions.append({
                "file_name": vp.name,
                "file_path": str(vp),
                "file_sha256": v_sha,
                "alpha_id": vd.get("id"),
                "version": vd.get("version"),
                "owner_id": vd.get("owner_id"),
                "code_sha256": c_hash,
                "compile_status": test_compile(code)["status"] if code else "NO_CODE"
            })

    # 6. Archived Unlinked (46)
    archived_unlinked = []
    if archive_dir.exists():
        for ap in sorted(archive_dir.glob("*.json")):
            archived_unlinked.append(ap.name)

    manifest = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "summary_counts": {
            "active_user_alphas": len(user_alphas),
            "education_samples": len(education_samples),
            "onboarding_examples": len(onboarding_samples),
            "system_strategies": len(system_strategies),
            "active_alpha_versions": len(user_versions),
            "archived_unlinked": len(archived_unlinked),
            "duplicate_groups_count": len(code_hash_to_group)
        },
        "active_user_alphas": user_alphas,
        "education_samples": education_samples,
        "onboarding_examples": onboarding_samples,
        "system_strategies": system_strategies,
        "active_alpha_versions": user_versions,
        "archived_unlinked_files": archived_unlinked
    }

    out_file = Path("nora/check/edu_frozen_inventory_manifest.json")
    out_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Manifest written to {out_file}")
    print(json.dumps(manifest["summary_counts"], indent=2))

if __name__ == "__main__":
    build_frozen_inventory()
