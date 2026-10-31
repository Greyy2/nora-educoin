import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "backtest_results"
RESULTS_PATH = ARTIFACT_DIR / "wfa_mc_independent_results.json"
SUMMARY_PATH = ARTIFACT_DIR / "wfa_mc_independent_summary.md"
DOSSIER_PATH = ARTIFACT_DIR / "alpha_underperformer_dossier.md"
COHORT_PATH = ARTIFACT_DIR / "wfa_mc_cohort_freeze.json"


def test_independent_wfa_engine_and_monte_carlo_results_integrity():
    assert RESULTS_PATH.exists(), "wfa_mc_independent_results.json phải tồn tại"
    assert SUMMARY_PATH.exists(), "wfa_mc_independent_summary.md phải tồn tại"
    assert DOSSIER_PATH.exists(), "alpha_underperformer_dossier.md phải tồn tại"

    payload = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    cohort = json.loads(COHORT_PATH.read_text(encoding="utf-8"))

    if payload.get("artifact_status") == "INVALIDATED_STALE_COHORT_CLASSIFICATION":
        assert "structural/no-signal" in payload["artifact_status_reason"]
        return

    # 1. Kiểm tra số lượng và danh mục 25 đối tượng
    records = payload["records"]
    assert payload["total_records"] == 25
    assert len(records) == 25
    assert {r["id"] for r in records} == {c["id"] for c in cohort["records"]}

    # 2. Kiểm tra phương pháp luận WFA độc lập
    engine_meta = payload["methodology"]
    assert engine_meta["execution_mode"] == "INDEPENDENT_ENGINE_RUN_PER_FOLD"
    assert engine_meta["boundary_handling"] == "WARMUP_20D_PRELOAD_WITH_CLOSE_AT_END"
    assert engine_meta["metric_calculation"] == "DAILY_EQUITY_RETURNS_MTM_365D_SHARPE"
    assert "COMPOUNDED_STATIONARY" in engine_meta["monte_carlo_model"]

    # 3. Kiểm tra Provenance
    assert "provenance_hashes" in payload
    assert payload["provenance_hashes"]["cohort_freeze_sha256"]
    assert payload["provenance_hashes"]["protocol_sha256"]
    assert payload["provenance_hashes"]["manifest_sha256"]

    # 4. Kiểm tra phân loại cấu trúc & proxy
    summary = payload["disposition_summary"]
    assert summary["RESEARCH_PROXY_NO_DECISION"] == 3
    assert summary["PORTFOLIO_COMBO_EVALUATED_SEPARATELY"] == 1

    # 5. Kiểm tra từng record
    rejected_ids = []
    for r in records:
        aid = r["id"]
        assert "folds_metrics" in r
        assert "fold_1" in r["folds_metrics"]
        assert "fold_2" in r["folds_metrics"]
        assert "fold_3" in r["folds_metrics"]
        assert "monte_carlo_block_bootstrap" in r

        # Daily equity return checks
        f1 = r["folds_metrics"]["fold_1"]
        f2 = r["folds_metrics"]["fold_2"]
        f3 = r["folds_metrics"]["fold_3"]
        assert f1["days_count"] > 0
        assert f2["days_count"] > 0
        assert f3["days_count"] > 0

        # Monte Carlo compounding
        mc_base = r["monte_carlo_block_bootstrap"]["base_block_5"]
        assert mc_base["simulations"] == 10000
        assert mc_base["block_days"] == 5
        assert mc_base["status"] in ("COMPLETED", "INSUFFICIENT_DATA")
        assert r["monte_carlo_block_bootstrap"]["sensitivity_block_3"]["block_days"] == 3
        assert r["monte_carlo_block_bootstrap"]["sensitivity_block_10"]["block_days"] == 10

        # DSR audit check
        dsr = r["deflated_sharpe_ratio"]
        assert dsr["dsr_status"] == "DSR_UNAVAILABLE_TRIALS_UNAUDITED"
        assert dsr.get("dsr_value") is None
        assert not any(isinstance(v, (int, float)) for v in dsr.values())

        # Kiểm tra tính nhất quán theo Section 7
        disp = r["disposition"]
        source_class = r["source_classification"]
        if source_class == "PORTFOLIO_COMBO":
            assert disp == "PORTFOLIO_COMBO_EVALUATED_SEPARATELY"
        elif source_class == "EXCLUDED_STRUCTURAL_NO_SIGNAL_LOGIC":
            assert disp == "NOT_APPLICABLE"
        elif r["wfa_method_assigned"] == "RESEARCH_ONLY_NO_DECISION":
            assert disp == "RESEARCH_PROXY_NO_DECISION"
        else:
            total_trades = r["aggregated_oos_metrics"]["trades"]
            if total_trades < 30:
                assert disp == "INSUFFICIENT_SAMPLE"
            else:
                assert disp in ("KEEP", "REJECT", "REVIEW")
                if disp == "REJECT":
                    rejected_ids.append(aid)

    # 6. Kiểm tra Dossier pháp y chứa đầy đủ các alpha bị REJECT
    dossier_text = DOSSIER_PATH.read_text(encoding="utf-8")
    for rej_id in rejected_ids:
        assert f"## Alpha: `{rej_id}`" in dossier_text, f"{rej_id} phải có hồ sơ trong dossier"
