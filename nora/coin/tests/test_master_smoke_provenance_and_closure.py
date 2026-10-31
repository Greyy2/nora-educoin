"""Test suite kiểm định toàn bộ tiêu chí đóng của Master Smoke-Run Forensic Phase."""
import json
import hashlib
from pathlib import Path
import pytest

REPO_ROOT = Path("/home/vmc03/norabt")
OUT_DIR = REPO_ROOT / "artifacts" / "backtest_results"
RESULTS_JSON = OUT_DIR / "master_backtest_results.json"
MANIFEST_JSON = OUT_DIR / "input_manifest.json"
SUMMARY_MD = OUT_DIR / "master_summary.md"
AURORA_AUDIT = OUT_DIR / "auroraxwt_stop_cost_attribution.json"
PARITY_AUDIT = OUT_DIR / "edu_coin_golden_parity_audit.json"
LEDGER_DIR = OUT_DIR / "raw_ledgers"

def file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def test_master_results_and_ledgers_integrity():
    """Kiểm tra sự tồn tại và tính nhất quán của 25 results và 25 raw ledgers."""
    assert RESULTS_JSON.exists(), "master_backtest_results.json phải tồn tại"
    results = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    assert len(results) == 25, f"Kỳ vọng đúng 25 results, nhưng nhận {len(results)}"
    
    assert LEDGER_DIR.exists(), "Thư mục raw_ledgers phải tồn tại"
    for r in results:
        assert r["status"] == "SUCCESS", f"Alpha {r['id']} chưa SUCCESS"
        raw_path = OUT_DIR / r["raw_ledger_file"]
        assert raw_path.exists(), f"Raw ledger file {raw_path} không tồn tại"
        trades = json.loads(raw_path.read_text(encoding="utf-8"))
        assert len(trades) == r["trades"], f"Số lệnh trong ledger ({len(trades)}) không khớp kết quả aggregate ({r['trades']}) của {r['id']}"

def test_manifest_provenance_and_checksums():
    """Kiểm tra provenance đầy đủ trong input_manifest.json (effective configs, dirty summary, artifact hashes)."""
    assert MANIFEST_JSON.exists(), "input_manifest.json phải tồn tại"
    manifest = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
    
    assert manifest.get("git_commit"), "Phải có git commit"
    assert manifest.get("git_dirty") is True, "Worktree đang ở trạng thái dirty kiểm toán"
    assert manifest.get("manifest_provenance_mode") == "post_run_reconstruction", "Phải ghi rõ provenance là post_run_reconstruction"
    assert "tracked_dirty_diff_sha256" in manifest.get("dirty_summary", {}), "Phải có tracked_dirty_diff_sha256"
    assert manifest.get("runner_sha256"), "Phải có runner_sha256"
    assert manifest.get("total_results") == 25
    
    # Kiểm tra sha256 của các artifacts chính
    artifact_hashes = manifest.get("artifact_hashes", {})
    assert artifact_hashes.get("master_backtest_results_json") == file_sha256(RESULTS_JSON)
    assert artifact_hashes.get("master_summary_md") == file_sha256(SUMMARY_MD)
    assert artifact_hashes.get("auroraxwt_stop_cost_attribution_json") == file_sha256(AURORA_AUDIT)
    assert artifact_hashes.get("edu_coin_golden_parity_audit_json") == file_sha256(PARITY_AUDIT)
    
    # Kiểm tra effective parameters và sha256 của từng raw ledger
    for item in manifest.get("results_summary", []):
        aid = item["id"]
        assert "sizing_mode" in item, f"Thiếu sizing_mode trong effective config của {aid}"
        assert "effective_leverage" in item, f"Thiếu effective_leverage trong config của {aid}"
        assert "code_sha256" in item, f"Thiếu code_sha256 trong config của {aid}"
        
        # COIN V2 configs
        if aid in ("efa90f74cd08_v2", "18e87aa868ad_v2", "33312a2f4dfc_v2"):
            assert item["symbols"] == ["BTC", "ETH", "SOL"], f"V2 {aid} symbols phải là ['BTC', 'ETH', 'SOL']"
            assert item["timeframe"] == "24h", f"V2 {aid} timeframe phải là 24h"
            assert item["effective_stop_loss_rate"] in (2.5, 3.0), f"V2 {aid} stop_loss_rate không khớp"
            
        recorded_hash = item.get("raw_ledger_sha256")
        ledger_path = OUT_DIR / item["raw_ledger_file"]
        assert recorded_hash == file_sha256(ledger_path), f"Hash của ledger {aid} không khớp manifest"

def test_auroraxwt_audit_findings():
    """Kiểm tra kết quả kiểm toán attribution của Auroraxwt (cả 2 bộ số risk, sai số kế toán, worst loss)."""
    assert AURORA_AUDIT.exists(), "auroraxwt_stop_cost_attribution.json phải tồn tại"
    audit = json.loads(AURORA_AUDIT.read_text(encoding="utf-8"))
    
    assert audit["alpha_id"] == "okx_auroraxwt"
    assert audit["total_trades"] == 467
    assert audit["losses_count"] == 393
    assert audit["wins_count"] == 74
    assert audit["all_rows_layers_equal_1"] is True
    assert audit["all_rows_leverage_equal_20"] is True
    
    # Sai số số học tối đa không vượt quá 0.0001 USD
    assert audit["accounting_identity_max_discrepancy"] <= 0.0001
    
    # Đối soát cả 2 cách tính risk
    fixed_exceed = audit["loss_exceedance_summary"]["fixed_nominal_risk_25_usd"]
    assert fixed_exceed["greater_than_1x_count"] == 36
    assert fixed_exceed["greater_than_2x_count"] == 7
    assert fixed_exceed["greater_than_5x_count"] == 1
    
    dyn_exceed = audit["loss_exceedance_summary"]["dynamic_entry_equity_risk"]
    assert dyn_exceed["greater_than_1x_count"] == 54
    assert dyn_exceed["greater_than_2x_count"] == 11
    assert dyn_exceed["greater_than_5x_count"] == 1
    
    # Worst loss thực tế trong ledger
    assert audit["top_worst_losses"][0]["net_loss_usd"] == -139.72
    assert "16:00 UTC" in audit["attribution_findings"][5]
    assert "17:00 UTC" in audit["attribution_findings"][5]

def test_edu_coin_golden_parity_audit():
    """Kiểm tra kết quả đối soát parity giữa EDU và COIN Monolith ở cả cấp độ Metric và Trade Row."""
    assert PARITY_AUDIT.exists(), "edu_coin_golden_parity_audit.json phải tồn tại"
    parity = json.loads(PARITY_AUDIT.read_text(encoding="utf-8"))
    
    # Metric-level parity
    m_level = parity["metric_level_parity"]
    assert m_level["metrics_exact_match"] is True
    assert m_level["edu_metrics"]["trades"] == 11
    assert m_level["edu_metrics"]["ret_pct"] == -1.4
    assert m_level["edu_metrics"]["mdd_pct"] == 2.25
    assert m_level["edu_metrics"]["fees_usd"] == 17.95
    assert m_level["coin_metrics"] == m_level["edu_metrics"]
    
    # Trade-level parity
    t_level = parity["trade_level_parity"]
    assert t_level["all_11_trades_economic_fields_match"] is True
    assert t_level["trade_level_mismatches_count"] == 0
    assert len(parity["trades_details"]) == 11

def test_summary_markdown_no_overclaims():
    """Báo cáo master_summary.md không được có các claim vượt quá bằng chứng kỹ thuật."""
    summary_text = SUMMARY_MD.read_text(encoding="utf-8")
    assert "khớp 100% với matching engine Nautilus và sổ lệnh OKX" not in summary_text
    assert "xuất sắc" not in summary_text
    assert "Pipeline SUCCESS" in summary_text
    assert "chưa được kẹp trần runtime" in summary_text
    assert "promotion_allowed = false" in summary_text
    assert "Schema hiện tại chưa bao gồm stop trigger price" in summary_text
    assert "tái dựng hậu kiểm" in summary_text
    assert "post_run_reconstruction" in summary_text
    assert "tracked files" in summary_text
    assert "hoàn toàn không bao gồm nội dung của các file untracked" in summary_text
