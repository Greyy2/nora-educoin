"""Manifest-driven compile coverage and regression tests for EDU alpha rollout.
Asserts:
1. Every active user alpha (57) compiles into a valid Program.
2. Every education sample (50) compiles into a valid Program with disclosures.
3. Every onboarding sample (3) compiles into a valid Program with exact percentage units.
4. Canonical teaching templates compile cleanly, have prior-bar shift, and build valid execution plans.
5. Normalized user-alpha archives align config.position with code, and finalized active versions
   are linked, use pct exits, and expose no stale metrics after the unit fix.
6. Preserved historical versions (fa9587a97fa9.v2.json) match frozen SHA-256.
7. Assessment ledger classifies all 27 trivial records as BLOCKED_UNKNOWN_INTENT.
"""
import json
import hashlib
import re
import pytest
from pathlib import Path
import sys

edu_root = Path(__file__).resolve().parent.parent
if str(edu_root) not in sys.path:
    sys.path.insert(0, str(edu_root))

from backend.analys.alpha.code.compile import compile_code
from backend.analys.alpha.code.plan import build_plan
from backend.analys.signal import Program
from data.alpha.education.canonical_templates import CANONICAL_TEMPLATES, ADVANCED_CANONICAL_TEMPLATE


def test_manifest_active_user_alphas_compile():
    manifest_path = Path("nora/check/edu_frozen_inventory_manifest.json")
    assert manifest_path.exists(), "Manifest file missing"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    user_alphas = manifest.get("active_user_alphas", [])
    assert len(user_alphas) == 57, f"Expected 57 active user alphas, got {len(user_alphas)}"

    for item in user_alphas:
        aid = item["id"]
        raw_rec = item["raw_record"]
        code = raw_rec.get("code", "")
        assert code, f"Alpha {aid} has empty code"
        prog = compile_code(code)
        assert isinstance(prog, Program), f"Alpha {aid} failed to compile into Program"
        assert prog.timeframe, f"Alpha {aid} missing timeframe"
        assert len(prog.legs) > 0, f"Alpha {aid} has no active legs"


def test_education_samples_compile_and_have_disclosures():
    samples_path = Path("nora/edu/data/alpha/education/samples.json")
    assert samples_path.exists()
    samples = json.loads(samples_path.read_text(encoding="utf-8"))
    assert len(samples) == 50, f"Expected 50 education samples, got {len(samples)}"

    for s in samples:
        key = s.get("key")
        code = s.get("code")
        assert code, f"Sample {key} has empty code"
        prog = compile_code(code)
        assert isinstance(prog, Program)
        assert "disclosures" in s
        assert "slippage" in s["disclosures"]
        assert "fees" in s["disclosures"]


def test_onboarding_samples_compile_and_have_valid_units():
    onboarding_path = Path("nora/edu/frontend/src/components/alpha/studio/EduStudioOnboarding.jsx")
    assert onboarding_path.exists()
    text = onboarding_path.read_text(encoding="utf-8")

    # Verify SL 2.0 / TP 4.0 fix is in place
    assert "stop_loss_rate = 2.0" in text
    assert "take_profit_rate = 4.0" in text

    # Verify each onboarding sample code compiles
    manifest_path = Path("nora/check/edu_frozen_inventory_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for obs in manifest["onboarding_examples"]:
        prog = compile_code(obs["code"])
        assert isinstance(prog, Program)


def test_canonical_templates_execution_plans_and_prior_bar_shift():
    # Verify prior-bar shift in advanced breakout template
    adv_code = ADVANCED_CANONICAL_TEMPLATE["code"]
    assert "shift(1)" in adv_code, "Advanced Donchian breakout must use prior-bar shift to avoid self-inclusion"

    for tmpl in CANONICAL_TEMPLATES:
        code = str(tmpl["code"])
        prog = compile_code(code)
        plan = build_plan(prog, symbols=["BTC/USDT"])
        assert len(plan.strategies) == 1
        assert plan.base_frame == tmpl["timeframe"]
        
        # Verify echo and provenance
        prov = plan.echo["param_provenance"]
        assert prov["stop_loss_rate"]["source"] == "code"
        assert prov["exit_unit"]["value"] == "pct"
        assert prov["slippage_rate"]["value"] == 0.0


def test_historical_fa9587a97fa9_v2_intact():
    v2_path = Path("nora/edu/data/alpha/user/_versions/fa9587a97fa9.v2.json")
    assert v2_path.exists()
    expected_sha = "73c004968c74790e3a042da899f98887e7b8f0d3f497b96c411c4dfbb1333fc4"
    actual_sha = hashlib.sha256(v2_path.read_bytes()).hexdigest()
    assert actual_sha == expected_sha, f"Historical fa9587a97fa9.v2.json altered! Got {actual_sha}"


def test_versioned_user_alphas_config_alignment():
    vdir = Path("nora/edu/data/alpha/user/_versions")
    norm_report = json.loads(Path("nora/check/edu_user_normalization_report.json").read_text(encoding="utf-8"))
    assert norm_report["new_version_files_created"] == 23

    for entry in norm_report["log"]:
        match = re.fullmatch(r"version_v(\d+)_created", str(entry.get("action", "")))
        if match:
            aid = entry["id"]
            version_path = vdir / f"{aid}.v{match.group(1)}.json"
            assert version_path.exists()
            normalized = json.loads(version_path.read_text(encoding="utf-8"))
            cfg = normalized.get("config", {})
            pos = cfg.get("position", {})
            assert pos.get("exit_unit") == "pct"

            prog = compile_code(normalized.get("code", ""))
            plan = build_plan(prog, symbols=cfg.get("symbols", ["BTC"]), position=pos)
            assert len(plan.warnings) == 0, f"Alpha {aid} has plan conflict warnings: {plan.warnings}"


def test_finalized_user_alpha_units_are_linked_and_unrun():
    report = json.loads(
        Path("nora/check/edu_alpha_unit_fix_report.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "LOCAL_SOURCE_CONFIG_UPDATED_NOT_BACKTESTED"
    assert report["changes"]["backtest_run"] is False
    assert len(report["alphas"]) == 23

    user_dir = Path("nora/edu/data/alpha/user")
    for item in report["alphas"]:
        record = json.loads((user_dir / f"{item['id']}.json").read_text(encoding="utf-8"))
        position = record["config"]["position"]
        assert position["exit_unit"] == "pct"
        assert record["version"] == item["new_active_version"]
        assert any(row["version"] == record["version"] for row in record["versions"])
        assert record["metrics"] == {}
        assert record["result"] is None
        assert record["metrics_status"] == "NOT_RUN_AFTER_UNIT_FIX"

        program = compile_code(record["code"], register=False)
        assert program.code_hash == record["program_hash"]
        plan = build_plan(program, symbols=record["config"].get("symbols", ["BTC"]), position=position)
        assert plan.echo["param_provenance"]["exit_unit"]["value"] == "pct"
        assert not plan.warnings


def test_assessment_ledger_classifications():
    ledger_path = Path("nora/check/edu_source_assessment_ledger.json")
    assert ledger_path.exists()
    report = json.loads(ledger_path.read_text(encoding="utf-8"))
    
    breakdown = report["user_alphas_breakdown"]
    assert breakdown["total_user_alphas"] == 57
    assert breakdown["blocked_unknown_intent_count"] == 27
    assert breakdown["valid_as_is_count"] == 30
