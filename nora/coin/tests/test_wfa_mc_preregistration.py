import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "backtest_results"
COHORT_PATH = ARTIFACT_DIR / "wfa_mc_cohort_freeze.json"
PROTOCOL_PATH = ARTIFACT_DIR / "wfa_mc_protocol_preregistration.md"


def test_cohort_matches_master_results_and_ledgers():
    cohort = json.loads(COHORT_PATH.read_text(encoding="utf-8"))
    results = json.loads((ARTIFACT_DIR / "master_backtest_results.json").read_text(encoding="utf-8"))
    records = cohort["records"]

    assert cohort["total_cohort_records"] == 25
    assert len(records) == 25
    assert len({record["id"] for record in records}) == 25
    assert {record["id"] for record in records} == {result["id"] for result in results}

    results_by_id = {result["id"]: result for result in results}
    for record in records:
        result = results_by_id[record["id"]]
        ledger_path = ARTIFACT_DIR / record["raw_ledger_file"]
        assert record["in_sample_trades"] == result["trades"]
        assert hashlib.sha256(ledger_path.read_bytes()).hexdigest() == record["raw_ledger_sha256"]


def test_owner_decisions_and_protocol_hash_are_unambiguous():
    cohort = json.loads(COHORT_PATH.read_text(encoding="utf-8"))
    approval = cohort["approval_metadata"]
    decisions = approval["owner_decisions"]
    protocol = PROTOCOL_PATH.read_text(encoding="utf-8")

    assert decisions["oos_sample_rule"]["value"] == "A_AGGREGATED_OOS_MIN_30_TRADES"
    assert decisions["oos_sample_rule"]["status"] == "APPROVED_BY_OWNER"
    assert decisions["classification_thresholds"]["status"] == "APPROVED_BY_OWNER"
    assert approval["status"] == "PARTIAL_DECISIONS_RECORDED_FULL_SIGNOFF_PENDING"
    assert approval["approved_by"] is None
    assert approval["approved_at_utc"] is None
    assert approval["protocol_sha256_at_approval"] is None
    assert approval["protocol_sha256_current"] == hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest()

    assert "PHƯƠNG ÁN A" in protocol
    assert "Phương án B" in protocol and "không được chọn" in protocol
    assert "OWNER ĐÃ CHẤP NHẬN" in protocol
    assert "Full protocol sign-off**: `CHƯA GHI NHẬN`" in protocol
    assert "N=72" in protocol and "không phải 72 trials đã chạy" in protocol
    assert "DSR_UNAVAILABLE" in protocol
    assert "STRICTLY_BLOCKED" in protocol
