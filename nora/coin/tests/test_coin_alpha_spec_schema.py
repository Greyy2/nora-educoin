import copy
import json
import os
import sys
from pathlib import Path
import pytest

COIN_ROOT = Path(__file__).resolve().parent.parent
if str(COIN_ROOT) not in sys.path:
    sys.path.insert(0, str(COIN_ROOT))

os.environ.setdefault("NORA_PRODUCT", "coin")
os.environ.setdefault("NORA_DIR", str(COIN_ROOT))

from backend.analys.alpha.code.compile import load_system_strategies
from backend.analys.alpha.code.spec import (
    ALL_SPEC_KEYS,
    REQUIRED_SPEC_KEYS,
    SCHEMA_VERSION,
    canonical_spec_dict,
    canonical_spec_hash,
    canonical_spec_json,
    validate_candidate_spec,
)


def test_all_6_system_legs_comply_with_frozen_schema():
    loaded = load_system_strategies()
    candidates = loaded["candidates"]
    assert len(candidates) == 6, f"Expected 6 system legs, got {len(candidates)}"

    for cand in candidates:
        is_valid, errors = validate_candidate_spec(cand)
        assert is_valid, f"Candidate {cand.get('id')} failed schema validation: {errors}"
        # Check that all 11 real candidate keys are present
        for req_k in REQUIRED_SPEC_KEYS:
            assert req_k in cand, f"Candidate {cand['id']} missing real key '{req_k}'"


def test_canonical_spec_hash_invariance_to_key_order():
    loaded = load_system_strategies()
    cand = loaded["candidates"][0]

    h1 = canonical_spec_hash(cand)

    # Reverse key order at top level and nested level
    reversed_cand = dict(reversed(list(cand.items())))
    if "position" in reversed_cand:
        reversed_cand["position"] = dict(reversed(list(reversed_cand["position"].items())))
    h2 = canonical_spec_hash(reversed_cand)

    assert h1 == h2, "Hash must be invariant to dictionary key insertion order"


def test_canonical_spec_hash_ignores_provenance_and_volatile_fields():
    loaded = load_system_strategies()
    cand = loaded["candidates"][0]

    h1 = canonical_spec_hash(cand)

    cand_with_provenance = copy.deepcopy(cand)
    cand_with_provenance["author"] = "test_user_42"
    cand_with_provenance["created_at"] = "2026-10-28T18:00:00Z"
    cand_with_provenance["updated_at"] = "2026-10-28T19:00:00Z"
    cand_with_provenance["run_id"] = "run_abc_123"
    cand_with_provenance["git_commit"] = "e646868227c3e3a9e3f24277c8c7220be42c0be7"
    cand_with_provenance["provenance"] = {"source": "manual", "env": "dev"}

    h2 = canonical_spec_hash(cand_with_provenance)

    assert h1 == h2, "Hash must ignore volatile provenance fields"


def test_canonical_spec_hash_changes_on_threshold_mutation():
    loaded = load_system_strategies()
    cand = loaded["candidates"][0]

    h1 = canonical_spec_hash(cand)

    cand_modified = copy.deepcopy(cand)
    # Mutate a threshold: change default of a parameter in params_schema and inside tree
    first_param = list(cand_modified["params_schema"].keys())[0]
    cand_modified["params_schema"][first_param]["default"] = 999.0

    h2 = canonical_spec_hash(cand_modified)
    assert h1 != h2, "Hash must change when any parameter default/threshold is modified"


def test_canonical_spec_hash_sensitive_to_schema_version():
    loaded = load_system_strategies()
    cand = loaded["candidates"][0]

    cand_v1 = copy.deepcopy(cand)
    cand_v1["schema_version"] = "1.0.0"

    cand_v2 = copy.deepcopy(cand)
    cand_v2["schema_version"] = "2.0.0"

    h1 = canonical_spec_hash(cand_v1)
    h2 = canonical_spec_hash(cand_v2)

    assert h1 != h2, "Hash must differ across schema versions"
