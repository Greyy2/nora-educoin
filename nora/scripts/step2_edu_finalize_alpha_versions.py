#!/usr/bin/env python3
"""Finalize percentage-unit fixes for the reviewed EDU user-alpha records."""

import argparse
import ast
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
USER_DIR = ROOT / "nora/edu/data/alpha/user"
VERSION_DIR = USER_DIR / "_versions"
LEDGER_PATH = ROOT / "nora/check/edu_source_assessment_ledger.json"
INVENTORY_PATH = ROOT / "nora/check/edu_frozen_inventory_manifest.json"
NORMALIZATION_PATH = ROOT / "nora/check/edu_user_normalization_report.json"
CLEANUP_PATH = ROOT / "nora/check/edu_cleanup_manifest.json"
ACCOUNT_DIR = ROOT / "nora/edu/data/users"
REPORT_PATH = ROOT / "nora/check/edu_alpha_unit_fix_report.json"

FIX_ID = "explicit-percent-exit-unit-v1"
VERSION_ACTION = re.compile(r"version_v(\d+)_created$")
VERSION_FILE = re.compile(r"^([A-Za-z0-9_-]+)\.v(\d+)\.json$")
POSITION_ATTR = re.compile(
    r"^(?P<indent>\s*)(?P<name>"
    r"stop_loss_pct|take_profit_pct|trailing_stop_pct|trailing_activation_pct"
    r")\s*="
)

COMMENT_BY_ATTR = {
    "stop_loss_pct": "SL theo phần trăm giá vào lệnh; 2.5 tương đương 2.5%.",
    "take_profit_pct": "TP theo phần trăm giá vào lệnh; 0 = tắt.",
    "trailing_stop_pct": "Khoảng cách trailing theo phần trăm từ đỉnh/đáy kể từ khi vào lệnh; 0 = tắt.",
    "trailing_activation_pct": "Mức lợi nhuận phần trăm để kích hoạt trailing; 0 = tắt.",
}


def _read_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json_bytes(value))
            stream.flush()
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ast_fingerprint(code: str) -> str:
    return ast.dump(ast.parse(code), annotate_fields=True, include_attributes=False)


def _clarify_code_units(code: str) -> str:
    lines = code.splitlines()
    result: List[str] = []
    inserted_note = False
    seen_attributes = set()

    for line in lines:
        match = POSITION_ATTR.match(line)
        if match:
            name = match.group("name")
            seen_attributes.add(name)
            if not inserted_note:
                result.append(
                    f"{match.group('indent')}# Các trường *_pct là phần trăm, không phải bội số ATR."
                )
                inserted_note = True

            source, marker, comment = line.partition("#")
            if marker and "atr" in comment.lower():
                line = f"{source.rstrip()}  # {COMMENT_BY_ATTR[name]}"
        result.append(line)

    if "stop_loss_pct" not in seen_attributes:
        raise ValueError("Alpha không khai báo stop_loss_pct; cần xem xét thủ công.")

    updated = "\n".join(result) + ("\n" if code.endswith("\n") else "")
    if _ast_fingerprint(code) != _ast_fingerprint(updated):
        raise ValueError("Chỉnh chú thích làm thay đổi AST; từ chối cập nhật.")
    return updated


def _eligible_records() -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    ledger = _read_json(LEDGER_PATH)
    inventory = _read_json(INVENTORY_PATH)
    normalization = _read_json(NORMALIZATION_PATH)
    alpha_rows = [
        row for row in ledger.get("ledger", [])
        if row.get("source_type") == "user_alpha"
    ]
    if len(alpha_rows) != 57:
        raise ValueError(f"Expected 57 ledger alpha rows, found {len(alpha_rows)}")

    actions = {}
    for row in normalization.get("log", []):
        match = VERSION_ACTION.fullmatch(str(row.get("action", "")))
        if match:
            actions[row["id"]] = int(match.group(1))

    eligible = {
        row["record_id"]: row
        for row in alpha_rows
        if row.get("disposition") == "VALID_AS_IS"
        and not row.get("is_vinh")
        and row["record_id"] in actions
    }
    if len(eligible) != 23 or normalization.get("new_version_files_created") != 23:
        raise ValueError(f"Expected 23 normalized non-Vinh alphas, found {len(eligible)}")
    if normalization.get("blocked_unknown_intent_count") != 27:
        raise ValueError("Normalization report no longer has the expected 27 blocked records")
    return eligible, ledger, inventory


def _archive_versions(alpha_id: str) -> Dict[int, Path]:
    result = {}
    for path in VERSION_DIR.glob(f"{alpha_id}.v*.json"):
        match = VERSION_FILE.fullmatch(path.name)
        if match:
            result[int(match.group(2))] = path
    return result


def _version_row(record: Dict[str, Any], version: int) -> Dict[str, Any]:
    return {
        "version": version,
        "saved_at": record.get("updated_at"),
        "program_hash": record.get("program_hash"),
        "job_id": record.get("job_id"),
        "name": record.get("name"),
    }


def _account_counts(ledger: Dict[str, Any]) -> Dict[str, Any]:
    accounts = {path.stem for path in ACCOUNT_DIR.glob("*.json")}
    alpha_owners: Dict[str, set] = {}
    blocked_owners = set()
    valid_owners = set()
    for row in ledger["ledger"]:
        if row.get("source_type") != "user_alpha":
            continue
        owner = row.get("owner_id")
        if not owner:
            raise ValueError(f"Alpha {row.get('record_id')} has no owner_id")
        alpha_owners.setdefault(owner, set()).add(row.get("disposition"))
        if row.get("disposition") == "BLOCKED_UNKNOWN_INTENT":
            blocked_owners.add(owner)
        elif row.get("disposition") == "VALID_AS_IS":
            valid_owners.add(owner)

    no_alpha = accounts - set(alpha_owners)
    valid_alpha = accounts & valid_owners
    blocked_only = (accounts & blocked_owners) - valid_owners
    mixed = (accounts & blocked_owners) & valid_owners
    outside = set(alpha_owners) - accounts

    manifest = _read_json(CLEANUP_PATH)
    expected = manifest.get("remaining_accounts_count")
    if len(accounts) != expected:
        raise ValueError(
            f"Current account count {len(accounts)} differs from cleanup manifest {expected}"
        )
    if outside or mixed:
        raise ValueError(f"Unexpected owner mapping: outside_accounts={sorted(outside)}, mixed={sorted(mixed)}")
    return {
        "total_accounts": len(accounts),
        "users_without_alpha": len(no_alpha),
        "users_with_blocked_alpha_only": len(blocked_only),
        "users_with_at_least_one_valid_alpha": len(valid_alpha),
        "account_ids_without_alpha": sorted(no_alpha),
        "account_ids_with_blocked_alpha_only": sorted(blocked_only),
        "account_ids_with_valid_alpha": sorted(valid_alpha),
    }


def _prepare(
    eligible: Dict[str, Dict[str, Any]],
    ledger: Dict[str, Any],
    inventory: Dict[str, Any],
) -> List[Dict[str, Any]]:
    frozen = {
        row["id"]: row
        for row in inventory.get("active_user_alphas", [])
    }
    prepared = []
    for alpha_id, row in sorted(eligible.items()):
        active_path = USER_DIR / f"{alpha_id}.json"
        active = _read_json(active_path)
        code = active.get("code")
        if not isinstance(code, str) or not code:
            raise ValueError(f"Alpha {alpha_id} has no code")
        frozen_row = frozen.get(alpha_id)
        if not frozen_row or frozen_row.get("code_sha256") != row.get("code_sha256"):
            raise ValueError(f"Alpha {alpha_id} frozen inventory and assessment disagree")
        if code != (frozen_row.get("raw_record") or {}).get("code"):
            raise ValueError(f"Alpha {alpha_id} source code changed since assessment")
        if active.get("unit_fix_meta", {}).get("id") == FIX_ID:
            raise ValueError(f"Alpha {alpha_id} already has {FIX_ID}; use --verify")

        archive_versions = _archive_versions(alpha_id)
        normalization_action = next(
            entry["action"] for entry in _read_json(NORMALIZATION_PATH)["log"]
            if entry.get("id") == alpha_id and VERSION_ACTION.fullmatch(str(entry.get("action", "")))
        )
        match = VERSION_ACTION.fullmatch(normalization_action)
        if match is None:
            raise ValueError(f"Invalid normalization action for {alpha_id}: {normalization_action}")
        normalized_version = int(match.group(1))
        normalized_path = archive_versions.get(normalized_version)
        if normalized_path is None:
            raise ValueError(f"Alpha {alpha_id} normalized archive v{normalized_version} is missing")
        normalized = _read_json(normalized_path)
        if normalized.get("code") != code:
            raise ValueError(f"Alpha {alpha_id} normalized archive has different source code")
        if (normalized.get("config") or {}).get("position", {}).get("exit_unit") != "pct":
            raise ValueError(f"Alpha {alpha_id} normalized archive is not configured for pct exits")
        if normalized.get("program_hash") != active.get("program_hash"):
            raise ValueError(f"Alpha {alpha_id} normalized archive changes program_hash")

        updated_code = _clarify_code_units(code)
        if active.get("program_hash") != normalized.get("program_hash"):
            raise ValueError(f"Alpha {alpha_id} program hash differs between active and normalized archive")

        cfg = json.loads(json.dumps(active.get("config") or {}))
        position = json.loads(json.dumps(cfg.get("position") or {}))
        previous_exit_unit = position.get("exit_unit")
        position["exit_unit"] = "pct"
        cfg["position"] = position

        current_version = int(active.get("version") or 1)
        history_versions = [
            int(entry["version"])
            for entry in active.get("versions", [])
            if isinstance(entry, dict) and str(entry.get("version", "")).isdigit()
        ]
        next_version = max([current_version, *history_versions, *archive_versions.keys()]) + 1
        if (VERSION_DIR / f"{alpha_id}.v{next_version}.json").exists():
            raise FileExistsError(f"Refusing to overwrite {alpha_id}.v{next_version}.json")

        prepared.append({
            "id": alpha_id,
            "owner_id": active.get("owner_id"),
            "active_path": active_path,
            "active": active,
            "active_bytes": active_path.read_bytes(),
            "current_version": current_version,
            "next_version": next_version,
            "archive_versions": archive_versions,
            "normalized_version": normalized_version,
            "inventory_code_hash": row.get("code_sha256"),
            "normalized_path": normalized_path,
            "updated_code": updated_code,
            "config": cfg,
            "previous_exit_unit": previous_exit_unit,
            "ast_unchanged": _ast_fingerprint(code) == _ast_fingerprint(updated_code),
        })
    return prepared


def _updated_record(item: Dict[str, Any], timestamp: str) -> Dict[str, Any]:
    old = item["active"]
    record = json.loads(json.dumps(old))
    record["code"] = item["updated_code"]
    record["config"] = item["config"]
    record["version"] = item["next_version"]
    record["updated_at"] = timestamp

    previous_metrics = old.get("metrics") or {}
    record["metrics"] = {}
    record["checklist"] = None
    record["evidence"] = None
    record["result"] = None
    record["explain"] = None
    record["market_context"] = None
    record["data_sha"] = None
    record["job_id"] = None
    record["final_equity"] = None
    record["metrics_status"] = "NOT_RUN_AFTER_UNIT_FIX"
    old_note = str(old.get("note") or "").strip()
    disclosure = (
        "Bản này làm rõ các trường *_pct và đặt exit_unit=pct; "
        "chưa chạy lại backtest. Metrics ở các version trước chỉ là lịch sử, "
        "không được xem là kết quả của version hiện tại."
    )
    record["note"] = f"{old_note}\n\n{disclosure}".strip()
    record["unit_fix_meta"] = {
        "id": FIX_ID,
        "source_version": item["current_version"],
        "version": item["next_version"],
        "normalized_archive_version": item["normalized_version"],
        "source_code_sha256": _sha256(old["code"].encode("utf-8")),
        "source_inventory_code_hash": item["inventory_code_hash"],
        "updated_code_sha256": _sha256(item["updated_code"].encode("utf-8")),
        "source_program_hash": old.get("program_hash"),
        "ast_unchanged": item["ast_unchanged"],
        "previous_exit_unit": item["previous_exit_unit"],
        "effective_exit_unit": "pct",
        "backtest_run": False,
        "previous_metrics_sha256": _sha256(_json_bytes(previous_metrics)),
        "updated_at": timestamp,
    }

    rows: Dict[int, Dict[str, Any]] = {}
    for entry in old.get("versions", []):
        if isinstance(entry, dict) and str(entry.get("version", "")).isdigit():
            rows[int(entry["version"])] = dict(entry)
    for version, path in item["archive_versions"].items():
        archived = _read_json(path)
        rows.setdefault(version, _version_row(archived, version))
    if item["current_version"] not in rows:
        rows[item["current_version"]] = _version_row(old, item["current_version"])
    rows[item["next_version"]] = _version_row(record, item["next_version"])
    record["versions"] = [rows[version] for version in sorted(rows)]
    return record


def apply() -> Dict[str, Any]:
    eligible, ledger, inventory = _eligible_records()
    prepared = _prepare(eligible, ledger, inventory)
    accounts = _account_counts(ledger)
    if REPORT_PATH.exists():
        raise FileExistsError(f"Refusing to replace existing report {REPORT_PATH}")

    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    records = {item["id"]: _updated_record(item, timestamp) for item in prepared}
    untouched_hashes = {}
    for row in ledger["ledger"]:
        if row.get("source_type") != "user_alpha":
            continue
        if row.get("disposition") == "BLOCKED_UNKNOWN_INTENT" or row.get("is_vinh"):
            path = USER_DIR / f"{row['record_id']}.json"
            untouched_hashes[row["record_id"]] = _sha256(path.read_bytes())

    for item in prepared:
        archive = item["archive_versions"].get(item["current_version"])
        if archive is None:
            _atomic_write(
                VERSION_DIR / f"{item['id']}.v{item['current_version']}.json",
                item["active"],
            )
        # Existing colliding archives came from the prior normalization run.
        # Their metrics/result are preserved; never overwrite them.
        _atomic_write(item["active_path"], records[item["id"]])

    before = {item["id"]: _sha256(item["active_bytes"]) for item in prepared}
    report = {
        "status": "LOCAL_SOURCE_CONFIG_UPDATED_NOT_BACKTESTED",
        "created_at": timestamp,
        "scope": "23 VALID_AS_IS non-Vinh user alphas with a prior normalized version",
        "changes": {
            "active_versions_created": len(prepared),
            "source_logic_changed": False,
            "comments_corrected": True,
            "config_exit_unit_set_to": "pct",
            "old_active_metrics_cleared": True,
            "backtest_run": False,
        },
        "preservation": {
            "original_code_program_hash_preserved": True,
            "active_record_sha256_before_update": before,
            "untouched_active_record_sha256": untouched_hashes,
            "older_version_archives_not_overwritten": True,
            "original_vinh_alphas_modified": 0,
            "blocked_alpha_records_modified": 0,
        },
        "users": accounts,
        "alpha_counts": {
            "active_user_alphas": len([
                row for row in ledger["ledger"]
                if row.get("source_type") == "user_alpha"
            ]),
            "blocked_unknown_intent": 27,
            "valid_as_is": 30,
            "fixed_non_vinh": len(prepared),
            "valid_vinh_preserved": 7,
        },
        "alphas": [
            {
                "id": item["id"],
                "owner_id": item["owner_id"],
                "source_version": item["current_version"],
                "normalized_archive_version": item["normalized_version"],
                "new_active_version": item["next_version"],
                "previous_exit_unit": item["previous_exit_unit"],
                "effective_exit_unit": "pct",
                "program_hash": item["active"].get("program_hash"),
                "inventory_code_hash": item["inventory_code_hash"],
                "ast_unchanged": item["ast_unchanged"],
                "old_metrics_archived": True,
                "new_version_metrics": "NOT_RUN",
                "source_record_sha256_before_update": before[item["id"]],
            }
            for item in prepared
        ],
        "disclaimers": [
            "Chỉ sửa chú thích và cấu hình đơn vị; không đổi điều kiện tín hiệu hay tham số chiến lược.",
            "Backtest chưa chạy. Không thể dùng metrics lịch sử để đánh giá version mới.",
            "27 alpha BLOCKED_UNKNOWN_INTENT và 7 alpha của Vinh được giữ nguyên.",
            "Không xóa tài khoản, alpha hoặc archive.",
        ],
    }
    _atomic_write(REPORT_PATH, report)
    verify()
    return report


def verify() -> Dict[str, Any]:
    report = _read_json(REPORT_PATH)
    eligible, ledger, inventory = _eligible_records()
    if report.get("status") != "LOCAL_SOURCE_CONFIG_UPDATED_NOT_BACKTESTED":
        raise ValueError("Unexpected unit-fix report status")
    if len(report.get("alphas", [])) != 23:
        raise ValueError("Unit-fix report does not contain 23 alpha records")

    for alpha_id in eligible:
        active = _read_json(USER_DIR / f"{alpha_id}.json")
        meta = active.get("unit_fix_meta") or {}
        if meta.get("id") != FIX_ID:
            raise ValueError(f"Alpha {alpha_id} is not finalized")
        if active.get("version") != meta.get("version"):
            raise ValueError(f"Alpha {alpha_id} active version does not match unit-fix metadata")
        if active.get("config", {}).get("position", {}).get("exit_unit") != "pct":
            raise ValueError(f"Alpha {alpha_id} active config is not pct")
        if active.get("program_hash") != meta.get("source_program_hash"):
            raise ValueError(f"Alpha {alpha_id} program hash changed")
        if not meta.get("ast_unchanged") or meta.get("backtest_run") is not False:
            raise ValueError(f"Alpha {alpha_id} metadata does not prove a comment-only, untested update")
        if active.get("metrics") != {} or active.get("result") is not None:
            raise ValueError(f"Alpha {alpha_id} still exposes stale active metrics/results")
        if not any(
            isinstance(entry, dict) and entry.get("version") == active["version"]
            for entry in active.get("versions", [])
        ):
            raise ValueError(f"Alpha {alpha_id} active version is not linked in history")
        for entry in active.get("versions", []):
            version = int(entry["version"])
            if version < active["version"] and not (
                VERSION_DIR / f"{alpha_id}.v{version}.json"
            ).exists():
                raise ValueError(f"Alpha {alpha_id} history points to missing version v{version}")
        source_version_path = VERSION_DIR / f"{alpha_id}.v{meta['source_version']}.json"
        if not source_version_path.exists():
            raise ValueError(f"Alpha {alpha_id} previous metrics archive is missing")
        source_version = _read_json(source_version_path)
        if _sha256(_json_bytes(source_version.get("metrics") or {})) != meta.get("previous_metrics_sha256"):
            raise ValueError(f"Alpha {alpha_id} previous metrics were not preserved")
        code = active.get("code", "")
        normalized_version = next(
            item["normalized_archive_version"]
            for item in report["alphas"]
            if item["id"] == alpha_id
        )
        normalized = _read_json(VERSION_DIR / f"{alpha_id}.v{normalized_version}.json")
        if _ast_fingerprint(code) != _ast_fingerprint(
            normalized.get("code", "")
        ):
            raise ValueError(f"Alpha {alpha_id} code AST differs from its normalized source")
        if _sha256(code.encode("utf-8")) != meta.get("updated_code_sha256"):
            raise ValueError(f"Alpha {alpha_id} source hash differs from unit-fix metadata")
        ledger_row = next(
            row for row in ledger["ledger"]
            if row.get("record_id") == alpha_id and row.get("source_type") == "user_alpha"
        )
        if meta.get("source_inventory_code_hash") != ledger_row.get("code_sha256"):
            raise ValueError(f"Alpha {alpha_id} source hash differs from frozen assessment")
        frozen = next(
            item for item in inventory["active_user_alphas"]
            if item.get("id") == alpha_id
        )
        if _ast_fingerprint(code) != _ast_fingerprint(frozen["raw_record"]["code"]):
            raise ValueError(f"Alpha {alpha_id} strategy AST differs from frozen source")
        for line in code.splitlines():
            if POSITION_ATTR.match(line) and "atr" in line.partition("#")[2].lower():
                raise ValueError(f"Alpha {alpha_id} has a misleading ATR comment on a *_pct field")

    for alpha_id, expected_hash in report.get("preservation", {}).get("untouched_active_record_sha256", {}).items():
        path = USER_DIR / f"{alpha_id}.json"
        if _sha256(path.read_bytes()) != expected_hash:
            raise ValueError(f"Blocked or Vinh alpha {alpha_id} was modified")

    accounts = _account_counts(ledger)
    if accounts != report.get("users"):
        raise ValueError("Current user-account counts differ from the generated report")
    return report


def preflight() -> Dict[str, Any]:
    eligible, ledger, inventory = _eligible_records()
    prepared = _prepare(eligible, ledger, inventory)
    if REPORT_PATH.exists():
        raise FileExistsError(f"Refusing to replace existing report {REPORT_PATH}")
    return {
        "status": "PREFLIGHT_PASS_NO_WRITES",
        "fixed_alphas": len(prepared),
        "new_versions": {
            item["id"]: item["next_version"]
            for item in prepared
        },
        "users": _account_counts(ledger),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true", help="create linked versions and update active records")
    group.add_argument("--verify", action="store_true", help="verify the completed migration without writing")
    group.add_argument("--preflight", action="store_true", help="validate scope, archives, and user counts without writing")
    args = parser.parse_args()
    if args.apply:
        result = apply()
    elif args.verify:
        result = verify()
    else:
        result = preflight()
    print(json.dumps({
        "status": result["status"],
        "fixed_alphas": result.get("fixed_alphas", len(result.get("alphas", []))),
        "users": result["users"],
        "report": str(REPORT_PATH.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
