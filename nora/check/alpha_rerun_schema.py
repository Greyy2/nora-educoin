"""Generate and validate reproducible per-variant COIN alpha research artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"
METRIC_FIELDS = (
    "gross_pnl_usdt",
    "net_pnl_usdt",
    "net_return_pct",
    "trade_count",
    "expectancy_usdt",
    "max_drawdown_pct",
    "win_rate_pct",
    "daily_sharpe",
    "oos_t_stat",
    "fees_usdt",
    "spread_slippage_usdt",
    "funding_usdt",
    "liquidation_count",
    "stress_x2_net_return_pct",
    "stress_x3_net_return_pct",
    "dsr",
    "mc_paths",
    "mc_ruin_probability",
)
GATE_NAMES = (
    "data_causality",
    "execution_parity",
    "cost_model",
    "risk",
    "wfa_oos",
    "cost_stress",
    "dsr",
    "monte_carlo",
    "best_month_removal",
)
INPUT_HASH_FIELDS = (
    "source_sha256",
    "code_sha256",
    "config_sha256",
    "data_sha256",
    "instrument_spec_sha256",
    "cost_model_sha256",
    "engine_sha256",
)
BLOCKING_REASONS = [
    "Backtest-Live execution parity and Demo replay are not accepted.",
    "Historical funding and time-effective instrument specifications are incomplete.",
    "Account fee tier and calibrated execution costs are unverified.",
    "Authoritative durable master risk policy is not accepted.",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expand_manifest(manifest: dict[str, Any], manifest_sha256: str) -> list[dict[str, Any]]:
    """Expand the declared universe without adding, tuning, or dropping variants."""
    candidates = [
        candidate
        for strategy in manifest["system_strategies"]
        for candidate in strategy["candidates"]
    ]
    symbols = manifest["approved_symbols"]
    tracks = manifest["timeframe_tracks"]
    timeframes = [*tracks["swing_track"], *tracks["scalp_track"]]
    rows = []
    for candidate in candidates:
        for symbol in symbols:
            for timeframe in timeframes:
                key = f"{candidate['candidate_id']}|{symbol}|{timeframe}"
                rows.append({
                    "variant_id": key,
                    "candidate_id": candidate["candidate_id"],
                    "side": candidate["side"],
                    "strategy_id": next(
                        strategy["strategy_id"]
                        for strategy in manifest["system_strategies"]
                        if candidate in strategy["candidates"]
                    ),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "track": "scalp" if timeframe in tracks["scalp_track"] else "swing",
                    "manifest_sha256": manifest_sha256,
                })
    expected = manifest["matrix_summary"]["total_finite_variants"]
    ids = [row["variant_id"] for row in rows]
    if len(rows) != expected or len(set(ids)) != expected:
        raise ValueError(
            f"Manifest expansion mismatch: expected {expected} unique rows, "
            f"got {len(rows)} rows and {len(set(ids))} unique IDs"
        )
    return rows


def blocked_package(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_hash = _sha256(manifest_path)
    variants = []
    for variant in expand_manifest(manifest, manifest_hash):
        variants.append({
            **variant,
            "run_status": "BLOCKED",
            "input_hashes": {field: None for field in INPUT_HASH_FIELDS},
            "run": {
                "started_at_utc": None,
                "command": None,
                "window_start_utc": None,
                "window_end_utc": None,
                "folds": [],
                "holdout_opened": False,
                "raw_artifacts": [],
            },
            "metrics": {field: None for field in METRIC_FIELDS},
            "gates": {name: "BLOCKED" for name in GATE_NAMES},
            "blocking_reasons": list(BLOCKING_REASONS),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "report_status": "BLOCKED_NOT_EVALUATED",
        "manifest_name": manifest["name"],
        "manifest_sha256": manifest_hash,
        "variant_count": len(variants),
        "variants": variants,
    }


def validate_package(package: dict[str, Any], manifest_path: Path) -> list[str]:
    errors: list[str] = []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_hash = _sha256(manifest_path)
    expected = expand_manifest(manifest, manifest_hash)
    if package.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if package.get("manifest_sha256") != manifest_hash:
        errors.append("manifest_sha256 does not match the selected manifest")
    if package.get("variant_count") != len(expected):
        errors.append(f"variant_count must be {len(expected)}")
    rows = package.get("variants")
    if not isinstance(rows, list):
        return [*errors, "variants must be a list"]
    expected_by_id = {row["variant_id"]: row for row in expected}
    actual_ids = [row.get("variant_id") for row in rows if isinstance(row, dict)]
    duplicates = sorted({key for key in actual_ids if actual_ids.count(key) > 1})
    if duplicates:
        errors.append(f"duplicate variant IDs: {duplicates}")
    if set(actual_ids) != set(expected_by_id):
        missing = sorted(set(expected_by_id) - set(actual_ids))
        extra = sorted(set(actual_ids) - set(expected_by_id))
        errors.append(f"variant universe mismatch; missing={missing}, extra={extra}")

    observed_statuses = set()
    for row in rows:
        if not isinstance(row, dict):
            errors.append("each variant row must be an object")
            continue
        variant_id = row.get("variant_id")
        expected_row = expected_by_id.get(variant_id)
        if expected_row is None:
            continue
        for field, value in expected_row.items():
            if row.get(field) != value:
                errors.append(f"{variant_id}: {field} does not match manifest")
        status = row.get("run_status")
        observed_statuses.add(status)
        if status not in {"BLOCKED", "COMPLETE", "ERROR", "INSUFFICIENT_SAMPLE"}:
            errors.append(f"{variant_id}: invalid run_status {status!r}")
            continue
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            errors.append(f"{variant_id}: metrics must be an object")
            continue
        if set(metrics) != set(METRIC_FIELDS):
            errors.append(f"{variant_id}: metrics must contain exactly the declared metric fields")
            continue
        if status == "BLOCKED":
            if not row.get("blocking_reasons"):
                errors.append(f"{variant_id}: blocked row must explain its blockers")
            if any(value is not None for value in metrics.values()):
                errors.append(f"{variant_id}: blocked row must not contain fabricated metrics")
            if any(row.get("input_hashes", {}).get(field) is not None for field in INPUT_HASH_FIELDS):
                errors.append(f"{variant_id}: blocked row cannot claim unverified input hashes")
            if any(value != "BLOCKED" for value in row.get("gates", {}).values()):
                errors.append(f"{variant_id}: blocked row must keep every gate blocked")
        elif status == "COMPLETE":
            if row.get("blocking_reasons"):
                errors.append(f"{variant_id}: complete row cannot have blocking reasons")
            if not all(isinstance(row.get("input_hashes", {}).get(field), str) for field in INPUT_HASH_FIELDS):
                errors.append(f"{variant_id}: complete row requires all input hashes")
            for field in METRIC_FIELDS:
                value = metrics[field]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    errors.append(f"{variant_id}: completed metric {field} must be finite numeric")
            if any(gate not in {"PASS", "FAIL"} for gate in row.get("gates", {}).values()):
                errors.append(f"{variant_id}: completed row requires evaluated gates")
            if not row.get("run", {}).get("raw_artifacts"):
                errors.append(f"{variant_id}: complete row requires raw artifact references")
    if package.get("report_status") == "BLOCKED_NOT_EVALUATED" and observed_statuses != {"BLOCKED"}:
        errors.append("BLOCKED_NOT_EVALUATED package must contain only blocked rows")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("alpha_universe_manifest.json"))
    parser.add_argument("--write-blocked", type=Path, help="write an explicit no-metrics blocked inventory package")
    parser.add_argument("--validate", type=Path, help="validate an existing result package")
    args = parser.parse_args()
    if args.write_blocked:
        package = blocked_package(args.manifest)
        args.write_blocked.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {len(package['variants'])} blocked rows to {args.write_blocked}")
    if args.validate:
        package = json.loads(args.validate.read_text(encoding="utf-8"))
        errors = validate_package(package, args.manifest)
        if errors:
            print("\n".join(errors))
            return 1
        print(f"Valid package: {package['variant_count']} variants, status={package['report_status']}")
    if not args.write_blocked and not args.validate:
        parser.error("specify --write-blocked and/or --validate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
