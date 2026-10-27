import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alpha_rerun_schema import blocked_package, validate_package


MANIFEST = Path(__file__).with_name("alpha_universe_manifest.json")


def test_blocked_package_contains_exact_manifest_universe_without_metrics():
    package = blocked_package(MANIFEST)

    assert package["report_status"] == "BLOCKED_NOT_EVALUATED"
    assert package["variant_count"] == 72
    assert len({row["variant_id"] for row in package["variants"]}) == 72
    assert {row["run_status"] for row in package["variants"]} == {"BLOCKED"}
    assert all(all(value is None for value in row["metrics"].values()) for row in package["variants"])
    assert validate_package(package, MANIFEST) == []


def test_validator_rejects_missing_and_duplicate_variants():
    package = blocked_package(MANIFEST)
    package["variants"].pop()
    package["variants"].append(json.loads(json.dumps(package["variants"][0])))

    errors = validate_package(package, MANIFEST)

    assert any("duplicate variant IDs" in error for error in errors)
    assert any("variant universe mismatch" in error for error in errors)


def test_validator_rejects_fabricated_metrics_in_blocked_variant():
    package = blocked_package(MANIFEST)
    package["variants"][0]["metrics"]["net_return_pct"] = 0.0

    errors = validate_package(package, MANIFEST)

    assert any("must not contain fabricated metrics" in error for error in errors)


def test_validator_rejects_manifest_hash_mismatch():
    package = blocked_package(MANIFEST)
    package["manifest_sha256"] = "0" * 64

    errors = validate_package(package, MANIFEST)

    assert "manifest_sha256 does not match the selected manifest" in errors


def test_validator_rejects_completed_row_without_raw_artifacts():
    package = blocked_package(MANIFEST)
    row = package["variants"][0]
    row["run_status"] = "COMPLETE"
    row["blocking_reasons"] = []
    row["input_hashes"] = {
        key: "a" * 64 for key in row["input_hashes"]
    }
    row["metrics"] = {key: 0 for key in row["metrics"]}
    row["gates"] = {key: "PASS" for key in row["gates"]}

    errors = validate_package(package, MANIFEST)

    assert any("requires raw artifact references" in error for error in errors)
    assert any("BLOCKED_NOT_EVALUATED package must contain only blocked rows" in error for error in errors)
