#!/usr/bin/env python3
"""Replace the 27 blocked EDU fixture alpha records in place with research-v2 code."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
USER_ALPHA_DIR = ROOT / "nora/edu/data/alpha/user"
BASELINE_PATH = ROOT / "nora/check/edu_alpha_baseline_results.json"
CANDIDATE_PATH = ROOT / "nora/check/candidates/edu_fixture_alpha_candidates_v2_20261028.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value, raw


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=1)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def replace_record(candidate: dict[str, Any], current: dict[str, Any], now: str) -> dict[str, Any]:
    parent_id = candidate["parent_id"]
    if current.get("id") != parent_id:
        raise ValueError(f"{parent_id}: record ID mismatch")
    if current.get("owner_id") != candidate.get("owner_id"):
        raise ValueError(f"{parent_id}: owner changed since candidate generation")
    if current.get("config") != candidate.get("config"):
        raise ValueError(f"{parent_id}: config changed since candidate generation")
    if sha256(current.get("code", "").encode("utf-8")) != candidate["parent_source_sha256"]:
        raise ValueError(f"{parent_id}: source code changed since candidate generation")
    if current.get("status") not in {"SAVED", "CANDIDATE"}:
        raise ValueError(f"{parent_id}: unexpected record status {current.get('status')!r}")

    class_name = candidate["code"].splitlines()[0].split("(", 1)[0].removeprefix("class ").strip()
    updated: dict[str, Any] = {
        "id": parent_id,
        "name": class_name,
        "note": (
            f"{candidate['thesis']} "
            f"Vào: {candidate['entry_rule']} "
            f"Thoát: {candidate['exit_rule']} "
            "Research proposal; chưa production-compile hoặc backtest."
        ),
        "source": current.get("source", "education"),
        "status": current.get("status", "SAVED"),
        "created_at": current.get("created_at"),
        "updated_at": now,
        "code": candidate["code"],
        "code_sha256": candidate["code_sha256"],
        "program_hash": None,
        "config": current["config"],
        "owner_id": current.get("owner_id"),
        "version": int(current.get("version") or 1) + 1,
        "thesis": candidate["thesis"],
        "entry_rule": candidate["entry_rule"],
        "exit_rule": candidate["exit_rule"],
        "falsifier": candidate["falsifier"],
        "signal_priority": candidate["signal_priority"],
        "dsl_compile_status": "NOT_RUN",
        "backtest_status": "NOT_RUN",
        "disposition": "RESEARCH_PROPOSAL",
        "parent_source_sha256": candidate["parent_source_sha256"],
        "parent_record_sha256": candidate["parent_record_sha256"],
    }
    if current.get("forked_from"):
        updated["forked_from"] = current["forked_from"]
    return updated


def main() -> None:
    baseline, _ = read_json(BASELINE_PATH)
    candidate_doc, _ = read_json(CANDIDATE_PATH)
    blocked_ids = set(baseline["blocked_records"])
    candidates = candidate_doc.get("candidates", [])
    candidate_by_id = {row["parent_id"]: row for row in candidates}

    if len(blocked_ids) != 27 or len(candidates) != 27 or set(candidate_by_id) != blocked_ids:
        raise ValueError("Expected exactly the 27 blocked IDs, each with one research-v2 candidate")

    staged: list[tuple[Path, dict[str, Any]]] = []
    now = datetime.now(timezone.utc).isoformat()
    for alpha_id in sorted(blocked_ids):
        path = USER_ALPHA_DIR / f"{alpha_id}.json"
        current, raw = read_json(path)
        candidate = candidate_by_id[alpha_id]
        if sha256(raw) != candidate["parent_record_sha256"]:
            raise ValueError(f"{alpha_id}: record changed since candidate generation")
        staged.append((path, replace_record(candidate, current, now)))

    for path, updated in staged:
        write_atomic(path, updated)

    print(f"Replaced {len(staged)} existing EDU alpha records in place; no new alpha IDs created.")
    print("All replaced records explicitly remain uncompiled and unbacktested.")


if __name__ == "__main__":
    main()
