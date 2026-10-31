import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "backtest_results"
RESULTS_PATH = ARTIFACT_DIR / "wfa_mc_rolling_oos_results.json"
SUMMARY_PATH = ARTIFACT_DIR / "wfa_mc_rolling_oos_summary.md"
COHORT_PATH = ARTIFACT_DIR / "wfa_mc_cohort_freeze.json"


def test_dry_run_rolling_oos_and_monte_carlo_results_integrity():
    assert RESULTS_PATH.exists(), "wfa_mc_rolling_oos_results.json phải tồn tại"
    payload = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    cohort = json.loads(COHORT_PATH.read_text(encoding="utf-8"))

    records = payload["records"]
    assert payload["total_records"] == 25
    assert len(records) == 25
    assert {r["id"] for r in records} == {c["id"] for c in cohort["records"]}

    summary = payload["disposition_summary"]
    assert summary["NOT_APPLICABLE"] == 4
    assert summary["RESEARCH_PROXY_NO_DECISION"] == 3
    assert summary["PORTFOLIO_COMBO_EVALUATED_SEPARATELY"] == 1
    assert summary["INSUFFICIENT_SAMPLE"] == 11
    assert summary["DRY_RUN_DIAGNOSTIC_ONLY"] == 6
    assert "KEEP" not in summary
    assert "REJECT" not in summary

    # Kiểm tra tính toàn vẹn của provenance và methodology caveats
    assert "provenance_hashes" in payload
    assert payload["provenance_hashes"]["cohort_freeze_sha256"]
    assert payload["provenance_hashes"]["protocol_sha256"]
    assert payload["provenance_hashes"]["master_manifest_sha256"]
    assert payload["provenance_hashes"]["market_data"]["btc_manifest_sha256"]
    assert payload["provenance_hashes"]["engine"]["coin_backtest_engine_sha256"]
    assert payload["provenance_hashes"]["cost_model"]["coin_params_sha256"]

    caveats = payload["methodology_caveats"]
    assert caveats["fold_slicing_mode"] == "ledger_entry_timestamp_slicing"
    assert "cross_boundary_limitation" in caveats
    assert "alpha_decision_ban" in caveats

    # Kiểm tra tính toàn vẹn của từng alpha và không có giá trị số DSR gây ngộ nhận
    for r in records:
        aid = r["id"]
        assert "folds_metrics" in r
        assert "fold_1" in r["folds_metrics"]
        assert "fold_2" in r["folds_metrics"]
        assert "fold_3" in r["folds_metrics"]
        assert "monte_carlo_block_bootstrap" in r

        dsr = r["deflated_sharpe_ratio"]
        assert dsr["dsr_status"] == "DSR_UNAVAILABLE_TRIALS_UNAUDITED"
        assert dsr.get("dsr_value") is None
        assert not any(isinstance(v, (int, float)) for v in dsr.values())

        disp = r["disposition"]
        if r["source_classification"] == "PORTFOLIO_COMBO":
            assert disp == "PORTFOLIO_COMBO_EVALUATED_SEPARATELY"
        elif r["source_classification"] == "EXCLUDED_STRUCTURAL_NO_SIGNAL_LOGIC":
            assert disp == "NOT_APPLICABLE"
        elif r["wfa_method_assigned"] == "RESEARCH_ONLY_NO_DECISION":
            assert disp == "RESEARCH_PROXY_NO_DECISION"
        elif r["total_agg_oos_trades"] < 30:
            assert disp == "INSUFFICIENT_SAMPLE"
        else:
            assert disp == "DRY_RUN_DIAGNOSTIC_ONLY"

    # Kiểm tra Markdown summary
    assert SUMMARY_PATH.exists()
    summary_text = SUMMARY_PATH.read_text(encoding="utf-8")
    assert "DRY-RUN HẠ TẦNG KỸ THUẬT — KHÔNG DÙNG RA QUYẾT ĐỊNH ALPHA" in summary_text
    assert "BỊ KHÓA (BLOCKED)" in summary_text
    assert "TUYỆT ĐỐI KHÔNG GÁN NHÃN `KEEP` HOẶC `REJECT`" in summary_text
    for c in cohort["records"]:
        assert f"`{c['id']}`" in summary_text

