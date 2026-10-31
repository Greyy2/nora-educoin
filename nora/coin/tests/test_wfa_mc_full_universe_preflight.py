import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_wfa_mc_full_universe.py"
SPEC = importlib.util.spec_from_file_location("full_universe_runner", SCRIPT_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_universe_preflight_rejects_non_compilable_custom_source():
    records = [{
        "id": "bad",
        "universe_key": "edu-user:bad",
        "code_key": "edu-user:bad",
        "category": "EDU User",
        "source_classification": "FIXED_PARAM_ROLLING_OOS",
    }]
    with pytest.raises(RuntimeError, match="preflight compile failed"):
        runner.validate_universe(records, {"edu-user:bad": "import os\nclass Bad(SimpleAlgorithm):\n    pass"})


def test_universe_preflight_rejects_missing_custom_source():
    records = [{
        "id": "missing",
        "universe_key": "edu-user:missing",
        "code_key": "edu-user:missing",
        "category": "EDU User",
        "source_classification": "FIXED_PARAM_ROLLING_OOS",
    }]
    with pytest.raises(RuntimeError, match="missing source code"):
        runner.validate_universe(records, {})


@pytest.mark.parametrize("alpha_id", ["18e87aa868ad", "33312a2f4dfc"])
def test_discovery_keeps_coin_and_edu_sources_separate_when_ids_collide(alpha_id):
    records, code_map = runner.discover_full_universe()
    scoped_keys = {record["universe_key"] for record in records}

    assert len(records) == 95
    assert len(code_map) == 87
    coin_key = f"coin-user:{alpha_id}"
    edu_key = f"edu-user:{alpha_id}"
    assert coin_key in scoped_keys
    assert edu_key in scoped_keys

    for product, key in (("coin", coin_key), ("edu", edu_key)):
        source_dir = runner.REPO_ROOT / "nora" / product / "data" / "alpha" / "user"
        matching_sources = []
        for path in source_dir.glob("*.json"):
            source = json.loads(path.read_text(encoding="utf-8"))
            if (source.get("id") or path.stem) == alpha_id:
                matching_sources.append(source)
        assert len(matching_sources) == 1
        assert code_map[key] == matching_sources[0]["code"]


def test_protocol_fingerprint_is_stable_and_includes_fold_boundaries():
    first = runner.protocol_provenance()
    second = runner.protocol_provenance()

    assert first == second
    assert first["definition"]["folds"] == runner.FOLDS
    assert first["definition"]["close_at_end"] is True
    assert len(first["sha256"]) == 64


def test_cohort_hash_binds_product_scoped_records_and_source_keys():
    coin_record = {
        "universe_key": "coin-user:same-id",
        "code_key": "coin-user:same-id",
        "category": "COIN User",
        "venue": "coin",
        "timeframe": "1h",
        "symbols": ["BTC-USDT"],
        "source_classification": "FIXED_PARAM_ROLLING_OOS",
    }
    edu_record = {
        **coin_record,
        "universe_key": "edu-user:same-id",
        "code_key": "edu-user:same-id",
        "category": "EDU User",
        "venue": "edu",
    }

    provenance = runner.cohort_provenance([coin_record, edu_record])

    assert provenance["record_count"] == 2
    assert {member["universe_key"] for member in provenance["members"]} == {
        "coin-user:same-id",
        "edu-user:same-id",
    }
    assert len(provenance["sha256"]) == 64


def test_current_universe_provenance_covers_all_source_and_market_symbols():
    records, code_map = runner.discover_full_universe()
    runner.validate_universe(records, code_map)

    sources = runner.source_provenance(code_map)
    cohort = runner.cohort_provenance(records)
    data = runner.data_manifest_provenance(records)

    assert cohort["record_count"] == len(records)
    assert len(sources["alpha_sources_sha256"]) == 64
    assert len(sources["implementation_sha256"]) == 64
    assert data["status"] == "COMPLETE"
    assert data["missing_symbols"] == []
