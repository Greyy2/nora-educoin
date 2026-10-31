"""Script tái dựng manifest hậu kiểm (post_run_reconstruction) và cập nhật báo cáo master_summary.md.

LƯU Ý QUAN TRỌNG VỀ BẢN CHẤT KỸ THUẬT:
- Manifest sinh ra ở đây là bản TÁI DỰNG HẬU KIỂM (post-run reconstruction), tổng hợp từ artifacts kết quả,
  sổ cái raw_ledgers và mã nguồn trên đĩa sau khi hoàn tất smoke-run.
- Đây KHÔNG PHẢI snapshot bất biến tự động được sinh trong thời gian chạy thực tế (runtime snapshot).
- Không được hiểu từ 'authoritative' là chứng thực chất lượng alpha; nó chỉ biểu thị định dạng cấu trúc chuẩn
  cho provenance tracking kỹ thuật.
"""
import json
import subprocess
import hashlib
import sys
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path("/home/vmc03/norabt")
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "nora" / "coin"))

from scripts.run_master_alpha_backtest import generate_master_markdown_report
from scripts.top_agents_proxy_catalog import TOP_AGENT_PROXY_CODES
from backend.analys.alpha.code.compile import compile_code
from backend.analys.alpha.code.plan import build_plan

OUT_DIR = REPO_ROOT / "artifacts" / "backtest_results"
RESULTS_JSON = OUT_DIR / "master_backtest_results.json"
SUMMARY_MD = OUT_DIR / "master_summary.md"
MANIFEST_JSON = OUT_DIR / "input_manifest.json"

def file_sha256(p: Path) -> str:
    if p.exists():
        return hashlib.sha256(p.read_bytes()).hexdigest()
    return ""

def main():
    results = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    
    # 1. Cập nhật master_summary.md
    md_content = generate_master_markdown_report(results)
    SUMMARY_MD.write_text(md_content, encoding="utf-8")
    
    # 2. Thu thập git commit, status, dirty diff hash
    try:
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        git_commit = "unknown"
        
    try:
        git_status_raw = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        git_dirty = len(git_status_raw) > 0
        dirty_files_count = len([ln for ln in git_status_raw.splitlines() if ln.strip()])
    except Exception:
        git_dirty = True
        dirty_files_count = -1
        
    try:
        diff_bytes = subprocess.check_output(["git", "diff"], text=False)
        dirty_diff_sha256 = hashlib.sha256(diff_bytes).hexdigest()
    except Exception:
        dirty_diff_sha256 = "unknown"
        
    runner_script = REPO_ROOT / "scripts" / "run_master_alpha_backtest.py"
    runner_sha256 = file_sha256(runner_script)
    
    # 3. Trích xuất effective parameters và code hashes cho từng alpha
    user_dir = REPO_ROOT / "nora/coin/data/alpha/user"
    
    sys.path.insert(0, str(REPO_ROOT / "nora" / "edu"))
    from data.alpha.education.canonical_templates import CANONICAL_TEMPLATES
    edu_manifest_path = REPO_ROOT / "nora/check/edu_frozen_inventory_manifest.json"
    edu_active_manifest = json.loads(edu_manifest_path.read_text()) if edu_manifest_path.exists() else {}
    edu_active_lookup = {item["id"]: item.get("raw_record", {}).get("code", "") for item in edu_active_manifest.get("active_user_alphas", [])}
    edu_canonical_lookup = {t["id"]: t["code"] for t in CANONICAL_TEMPLATES}

    effective_configs = []
    
    for r in results:
        aid = r["id"]
        cat = r["category"]
        venue = r["venue"]
        raw_ledger_rel = r.get("raw_ledger_file", "")
        raw_ledger_path = OUT_DIR / raw_ledger_rel
        raw_ledger_hash = file_sha256(raw_ledger_path)
        
        cfg = {
            "id": aid,
            "name": r["name"],
            "venue": venue,
            "category": cat,
            "status": r["status"],
            "trades": r.get("trades"),
            "ret_pct": r.get("ret_pct"),
            "mdd_pct": r.get("mdd_pct"),
            "fees_usd": r.get("fees_usd"),
            "raw_ledger_file": raw_ledger_rel,
            "raw_ledger_sha256": raw_ledger_hash,
            "symbols": ["BTC"],
            "timeframe": "1h",
            "cost_model": "preset_research_proxy (0.00160 round-trip)",
        }
        
        # System Legs
        if cat in ("COIN System Leg", "COIN Portfolio"):
            if aid in ("kema_long", "kema_short"):
                src_path = REPO_ROOT / "nora/coin/data/alpha/strategies/kema.py"
                cfg["code_source"] = "nora/coin/data/alpha/strategies/kema.py"
                cfg["code_sha256"] = file_sha256(src_path)
            elif aid in ("sideway_long", "sideway_short"):
                src_path = REPO_ROOT / "nora/coin/data/alpha/strategies/sideway.py"
                cfg["code_source"] = "nora/coin/data/alpha/strategies/sideway.py"
                cfg["code_sha256"] = file_sha256(src_path)
            elif aid in ("dca_long", "dca_short"):
                src_path = REPO_ROOT / "nora/coin/data/alpha/strategies/dca.py"
                cfg["code_source"] = "nora/coin/data/alpha/strategies/dca.py"
                cfg["code_sha256"] = file_sha256(src_path)
            elif aid == "combo_6_system_legs":
                k_sha = file_sha256(REPO_ROOT / "nora/coin/data/alpha/strategies/kema.py")
                s_sha = file_sha256(REPO_ROOT / "nora/coin/data/alpha/strategies/sideway.py")
                d_sha = file_sha256(REPO_ROOT / "nora/coin/data/alpha/strategies/dca.py")
                cfg["code_source"] = "composite(kema.py, sideway.py, dca.py) via backend.jobs.tasks:run_book_backtest"
                cfg["code_sha256"] = hashlib.sha256(f"{k_sha}:{s_sha}:{d_sha}".encode()).hexdigest()
            else:
                cfg["code_source"] = f"backend.core.strategy (leg={aid})"
                cfg["code_sha256"] = file_sha256(REPO_ROOT / "nora/coin/backend/core/strategy.py")
            cfg["sizing_mode"] = "risk"
            cfg["effective_risk_pct"] = 0.5
            cfg["effective_leverage"] = 10.0
            
        # COIN User V2
        elif cat == "COIN User V2":
            p = user_dir / f"{aid}.json"
            if p.exists():
                ud = json.loads(p.read_text())
                code_text = ud.get("code", "")
                cfg["code_sha256"] = hashlib.sha256(code_text.encode()).hexdigest()
                prog = compile_code(code_text)
                v2_symbols = ud.get("config", {}).get("symbols", ["BTC"])
                cfg["symbols"] = v2_symbols
                cfg["timeframe"] = prog.timeframe or "24h"
                plan = build_plan(prog, v2_symbols)
                pos = plan.strategies[0]["position"]
                cfg["sizing_mode"] = pos.get("sizing")
                cfg["effective_risk_pct"] = pos.get("risk_per_trade_pct")
                cfg["effective_stop_loss_rate"] = pos.get("stop_loss_rate")
                cfg["effective_leverage"] = pos.get("leverage")
                
        # COIN Top Agent
        elif cat == "COIN Top Agent":
            code_text = TOP_AGENT_PROXY_CODES.get(aid, "")
            if code_text:
                cfg["code_sha256"] = hashlib.sha256(code_text.encode()).hexdigest()
                prog = compile_code(code_text)
                cfg["symbols"] = ["BTC"]
                cfg["timeframe"] = prog.timeframe or "1h"
                plan = build_plan(prog, ["BTC"])
                pos = plan.strategies[0]["position"]
                cfg["sizing_mode"] = pos.get("sizing")
                cfg["effective_risk_pct"] = pos.get("risk_per_trade_pct")
                cfg["effective_stop_loss_rate"] = pos.get("stop_loss_rate")
                cfg["effective_leverage"] = pos.get("leverage") # 20.0
                
        # EDU Canonical
        elif cat == "EDU Canonical":
            code_text = edu_canonical_lookup.get(aid, "")
            cfg["code_sha256"] = hashlib.sha256(code_text.encode()).hexdigest()
            cfg["sizing_mode"] = "risk"
            cfg["effective_risk_pct"] = 0.5
            cfg["effective_leverage"] = 10.0
            
        # EDU Active User
        elif cat == "EDU Active User":
            code_text = edu_active_lookup.get(aid, "")
            cfg["code_sha256"] = hashlib.sha256(code_text.encode()).hexdigest()
            cfg["sizing_mode"] = "raw_student_code"
            cfg["effective_leverage"] = 10.0
            
        effective_configs.append(cfg)
        
    manifest_data = {
        "manifest_provenance_mode": "post_run_reconstruction",
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "dirty_summary": {
            "dirty_files_count": dirty_files_count,
            "tracked_dirty_diff_sha256": dirty_diff_sha256,
            "note": "tracked_dirty_diff_sha256 is the SHA-256 of git diff, covering modified tracked files; untracked files are excluded from git diff."
        },
        "runner_script": "scripts/run_master_alpha_backtest.py",
        "runner_sha256": runner_sha256,
        "command_invocation": ["python", "scripts/run_master_alpha_backtest.py"],
        "start_date": "2024-01-01",
        "end_date": "2026-09-01",
        "initial_capital": 10000.0,
        "data_catalog_digests": {
            "BTC_1m": "cd026438b6a668b1",
            "ETH_1m": "8d62dc2d69c4d5cf",
            "note": "Pre-computed 64-bit FNV/SHA digest of standardized OHLCV parquet slices."
        },
        "market_data_provenance": {
            "btc_manifest_file": "nora/coin/data/market/okx/catalog/_manifest/BTC.json",
            "btc_manifest_sha256": file_sha256(REPO_ROOT / "nora/coin/data/market/okx/catalog/_manifest/BTC.json"),
            "okx_instruments_file": "nora/coin/data/market/okx/instruments.json",
            "okx_instruments_sha256": file_sha256(REPO_ROOT / "nora/coin/data/market/okx/instruments.json"),
            "btc_catalog_digest": "cd026438b6a668b1",
        },
        "engine_provenance": {
            "coin_backtest_engine_file": "nora/coin/backend/core/backtest.py",
            "coin_backtest_engine_sha256": file_sha256(REPO_ROOT / "nora/coin/backend/core/backtest.py"),
            "coin_strategy_engine_file": "nora/coin/backend/core/strategy.py",
            "coin_strategy_engine_sha256": file_sha256(REPO_ROOT / "nora/coin/backend/core/strategy.py"),
            "coin_tasks_runner_file": "nora/coin/backend/jobs/tasks.py",
            "coin_tasks_runner_sha256": file_sha256(REPO_ROOT / "nora/coin/backend/jobs/tasks.py"),
            "edu_backtest_engine_file": "nora/edu/backend/core/backtest.py",
            "edu_backtest_engine_sha256": file_sha256(REPO_ROOT / "nora/edu/backend/core/backtest.py"),
        },
        "cost_model_provenance": {
            "coin_params_file": "nora/coin/backend/analys/param/params.py",
            "coin_params_sha256": file_sha256(REPO_ROOT / "nora/coin/backend/analys/param/params.py"),
            "cost_model_type": "preset_research_proxy",
            "round_trip_fee_proxy": 0.00160,
        },
        "artifact_hashes": {
            "master_backtest_results_json": file_sha256(RESULTS_JSON),
            "master_summary_md": file_sha256(SUMMARY_MD),
            "auroraxwt_stop_cost_attribution_json": file_sha256(OUT_DIR / "auroraxwt_stop_cost_attribution.json"),
            "edu_coin_golden_parity_audit_json": file_sha256(OUT_DIR / "edu_coin_golden_parity_audit.json"),
        },
        "total_results": len(results),
        "results_summary": effective_configs,
    }
    
    MANIFEST_JSON.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Đã ghi nhận input_manifest.json đầy đủ provenance: {len(effective_configs)} configs/hashes.")

if __name__ == "__main__":
    main()
