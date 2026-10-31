"""JSON IR Spec Schema & Canonical Hashing for Nora Coin Alpha Candidates.

Frozen Schema Version: 1.0.0
Real Candidate Keys:
- id: str
- strategy: str
- family: str
- side: 'LONG' | 'SHORT'
- description: str
- tree: list
- stop: list (optional)
- dca_gate: list (optional)
- position: dict
- params_schema: dict
- space: dict
- schema_version: str ("1.0.0")

Provenance & volatile fields (timestamp, git_commit, author, run_id, etc.)
are excluded from canonical spec hashing.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

SCHEMA_VERSION: str = "1.0.0"

REQUIRED_SPEC_KEYS: Tuple[str, ...] = (
    "id",
    "strategy",
    "family",
    "side",
    "description",
    "tree",
    "position",
    "params_schema",
    "space",
)

OPTIONAL_SPEC_KEYS: Tuple[str, ...] = (
    "stop",
    "dca_gate",
)

ALL_SPEC_KEYS: Tuple[str, ...] = REQUIRED_SPEC_KEYS + OPTIONAL_SPEC_KEYS + ("schema_version",)

# Provenance and transient keys strictly stripped before hashing
EXCLUDED_PROVENANCE_KEYS: Set[str] = {
    "author",
    "created_at",
    "updated_at",
    "run_id",
    "git_commit",
    "provenance",
    "compiled_at",
    "timestamp",
    "source_file",
    "file",
    "sha256",
    "code_hash",
    "notes",
}


def _canonicalize_value(val: Any) -> Any:
    """Canonicalize Python data types for stable, deterministic JSON serialization."""
    if isinstance(val, float):
        # Normalize float representation: strip trailing zeros, avoid -0.0
        if val == 0.0:
            return 0.0
        # Round to 10 decimal digits for float stability across platforms
        rounded = round(val, 10)
        return int(rounded) if rounded.is_integer() else rounded
    elif isinstance(val, dict):
        return {
            k: _canonicalize_value(v)
            for k, v in sorted(val.items())
            if k not in EXCLUDED_PROVENANCE_KEYS
        }
    elif isinstance(val, (list, tuple)):
        return [_canonicalize_value(item) for item in val]
    return val


def validate_candidate_spec(spec: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate that candidate dictionary complies with Schema Version 1.0.0."""
    errors: List[str] = []
    if not isinstance(spec, dict):
        return False, ["Candidate spec must be a dictionary"]

    for k in REQUIRED_SPEC_KEYS:
        if k not in spec:
            errors.append(f"Missing required key: '{k}'")

    if "side" in spec and spec["side"] not in ("LONG", "SHORT"):
        errors.append(f"Invalid side '{spec['side']}': must be 'LONG' or 'SHORT'")

    if "tree" in spec and not isinstance(spec["tree"], list):
        errors.append("Field 'tree' must be a list of condition blocks")

    if "stop" in spec and not isinstance(spec["stop"], list):
        errors.append("Field 'stop' must be a list of condition blocks")

    if "dca_gate" in spec and not isinstance(spec["dca_gate"], list):
        errors.append("Field 'dca_gate' must be a list of condition blocks")

    if "position" in spec and not isinstance(spec["position"], dict):
        errors.append("Field 'position' must be a dictionary")

    if "params_schema" in spec and not isinstance(spec["params_schema"], dict):
        errors.append("Field 'params_schema' must be a dictionary")

    if "space" in spec and not isinstance(spec["space"], dict):
        errors.append("Field 'space' must be a dictionary")

    return (len(errors) == 0), errors


def canonical_spec_dict(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Convert candidate spec into canonical dictionary with sorted keys and normalized values."""
    is_valid, errors = validate_candidate_spec(spec)
    if not is_valid:
        raise ValueError(f"Invalid candidate spec: {', '.join(errors)}")

    out: Dict[str, Any] = {
        k: _canonicalize_value(spec[k])
        for k in sorted(spec.keys())
        if k not in EXCLUDED_PROVENANCE_KEYS
    }
    out["schema_version"] = spec.get("schema_version", SCHEMA_VERSION)
    return dict(sorted(out.items()))


def canonical_spec_json(spec: Dict[str, Any]) -> str:
    """Serialize candidate spec into canonical, deterministic JSON string."""
    canonical_dict = canonical_spec_dict(spec)
    return json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_spec_hash(spec: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of candidate spec."""
    raw_json = canonical_spec_json(spec)
    return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
