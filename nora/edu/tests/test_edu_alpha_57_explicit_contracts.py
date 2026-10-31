from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from backend.analys.alpha.code.compile import compile_code
from backend.analys.indicator import FEATURES, OPS
from backend.analys.param import POSITION_KEYS


ROOT = Path(__file__).resolve().parents[3]
ALPHA_DIR = ROOT / "nora/edu/data/alpha/user"
MANIFEST_PATH = ROOT / "nora/check/edu_alpha_57_explicit_contracts_20261028.json"
CONTRACT_VERSION = "edu-alpha-explicit-contract-v1"


def _records() -> dict[str, dict]:
    records = {}
    for path in ALPHA_DIR.glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        records[record["id"]] = record
    return records


def _number_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _number_literal(node.operand)
    return False


def _call_name(node: ast.Call) -> str:
    fn = node.func
    name = fn.id if isinstance(fn, ast.Name) else ""
    while isinstance(fn, ast.Attribute):
        name = fn.attr
        fn = fn.value
    return name if isinstance(fn, ast.Name) else ""


def test_frozen_inventory_and_manifest_are_complete_without_backtests() -> None:
    records = _records()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert len(records) == 57
    assert manifest["record_count"] == 57
    assert manifest["compiled_count"] == 57
    assert manifest["signal_ir_equivalent_count"] == 57
    assert manifest["backtests_run"] == 0
    assert manifest["jobs_submitted"] == 0
    assert {row["alpha_id"] for row in manifest["results"]} == set(records)


def test_every_record_compiles_and_matches_explicit_saved_contract() -> None:
    records = _records()
    for alpha_id, record in records.items():
        program = compile_code(record["code"], register=False)
        position = record["config"]["position"]

        assert record["strategy_contract_version"] == CONTRACT_VERSION, alpha_id
        assert record["program_hash"] == program.code_hash, alpha_id
        assert record["code_sha256"] == hashlib.sha256(record["code"].encode("utf-8")).hexdigest(), alpha_id
        assert set(position) == set(POSITION_KEYS), alpha_id
        assert program.position_overrides == position, alpha_id
        assert record["strategy_contract"]["prior_signal_ir_preserved"] is True, alpha_id
        assert record["strategy_contract"]["warmup_bars"] == program.warmup_bars, alpha_id
        assert set(record["strategy_contract"]["position_provenance"]) == set(POSITION_KEYS), alpha_id
        assert record["contract_history"][0].get("config"), alpha_id


def test_signal_literals_are_parameters_and_code_ir_matches_prior_source() -> None:
    records = _records()
    for alpha_id, record in records.items():
        tree = ast.parse(record["code"])
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "on_bar")
        for node in ast.walk(method):
            if isinstance(node, ast.Call):
                name = _call_name(node)
                spec = FEATURES.get(name) or OPS.get(name)
                if spec is not None:
                    for arg, param in zip(node.args, spec.params):
                        if param.kind in {"int", "float", "matype"}:
                            assert not _number_literal(arg), f"{alpha_id}: inline {name}.{param.name}"
            if isinstance(node, ast.Compare):
                assert not any(_number_literal(item) for item in node.comparators), f"{alpha_id}: inline threshold"

        program = compile_code(record["code"], register=False)
        history = record["contract_history"]
        assert history, alpha_id
        assert history[-1]["signal_ir_sha256"] == record["strategy_contract"]["signal_ir_sha256"], alpha_id
        assert record["strategy_contract"]["signal_ir_sha256"], alpha_id
        assert program.timeframe == record["strategy_contract"]["signal_timeframe"], alpha_id


def test_old_results_are_archived_not_presented_as_current() -> None:
    records = _records()
    superseded = 0
    for alpha_id, record in records.items():
        historical_results = [
            item for item in record["contract_history"]
            if item.get("result_snapshot")
        ]
        if historical_results:
            superseded += 1
            assert record["result"] is None, alpha_id
            assert record["metrics"] == {}, alpha_id
            assert record["metrics_status"] == "STALE_SOURCE_CHANGED", alpha_id
            assert record["backtest_status"] == "STALE_SOURCE_CHANGED", alpha_id
            result_snapshot = next(
                item["result_snapshot"]
                for item in reversed(historical_results)
                if item["result_snapshot"].get("result") and item["result_snapshot"].get("metrics")
            )
            assert result_snapshot["result"], alpha_id
            assert result_snapshot["metrics"], alpha_id
        else:
            assert record["result"] is None, alpha_id
            assert record["metrics"] == {}, alpha_id
            assert record["backtest_status"] == "NOT_RUN_AFTER_CONTRACT_UPDATE", alpha_id
    assert superseded == 30


def test_known_legacy_rule_shape_collisions_are_not_marked_unique() -> None:
    records = _records()
    collision_ids = {
        "0873864b8db7",
        "bf519617d973",
        "090730ae35b8",
        "18e87aa868ad",
        "303d4b713dda",
        "33312a2f4dfc",
        "efb1fbe2db86",
        "fa9587a97fa9",
    }
    for alpha_id in collision_ids:
        assert records[alpha_id]["novelty_status"] == "STRUCTURAL_COLLISION_REVIEW_REQUIRED"
        assert records[alpha_id]["strategy_contract"]["normalized_rule_shape_collision_ids"]


def test_missing_exchange_is_not_guessed_for_new_records() -> None:
    records = _records()
    proposals = [record for record in records.values() if record.get("disposition") == "RESEARCH_PROPOSAL"]
    assert len(proposals) == 27
    for record in proposals:
        scope = record["strategy_contract"]["data_scope"]
        assert scope["exchange"] is None
        assert scope["exchange_status"] == "UNSPECIFIED_NOT_INFERRED"
