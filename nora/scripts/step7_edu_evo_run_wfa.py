#!/usr/bin/env python3
"""
scripts/step7_edu_evo_run_wfa.py
Thực hiện EDU-EVO-08 & EDU-EVO-09:
1. EDU-EVO-08: Chạy 3 Walk-Forward Analysis (WFA) folds cho các candidate variants đã tạo.
   - Fold 1: train through 2024-09-30; OOS test 2024-10-01 -> 2025-05-31
   - Fold 2: train through 2025-05-31; OOS test 2025-06-01 -> 2026-01-31
   - Fold 3: train through 2026-01-31; OOS test 2026-02-01 -> 2026-10-03
2. Chạy đúng một alpha/candidate mỗi tiến trình; WFA fold chạy tuần tự và checkpoint atomic:
   - WFA_PASS / WFA_FAIL / INSUFFICIENT_SAMPLE / BLOCKED.
   - Báo cáo candidate-specific được ghi sau mỗi fold.
"""

import os
import sys
import json
import time
import argparse
import tempfile
import hashlib
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict

ROOT = Path("/home/vmc03/norabt").resolve()
EDU_DIR = ROOT / "nora/edu"
CHECK_DIR = ROOT / "nora/check"

if str(EDU_DIR) not in sys.path:
    sys.path.insert(0, str(EDU_DIR))
os.environ["NORA_DATA_ROOT"] = str(EDU_DIR / "data")

from backend.jobs.tasks import run_custom
from backend.analys.param import date_ms

PROTOCOL_PATH = CHECK_DIR / "edu_evolution_research_protocol.json"
CANDIDATES_MANIFEST_PATH = CHECK_DIR / "edu_evolution_candidates_manifest.json"
def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one EDU alpha candidate sequentially under the EDU memory wrapper.")
    parser.add_argument("--alpha-id", required=True, help="Parent alpha ID to evaluate")
    parser.add_argument("--candidate-id", required=True, help="Exactly one candidate ID from the candidate manifest")
    parser.add_argument("--output", type=Path, help="Output report path; defaults to a candidate-specific exact-fold report")
    parser.add_argument("--overwrite", action="store_true", help="Replace the selected output file")
    return parser.parse_args()


def _write_checkpoint(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main():
    args = _arguments()
    print("=" * 80)
    print("BẮT ĐẦU WFA EXACT-FOLD CHO MỘT CANDIDATE")
    print("=" * 80)

    with open(PROTOCOL_PATH, "r", encoding="utf-8") as f:
        protocol = json.load(f)
    wfa_spec = protocol["wfa_specification"]
    folds = wfa_spec["folds"]
    gates = protocol["admission_gates"]
    if len(folds) != wfa_spec["folds_count"]:
        raise RuntimeError(f"Protocol requires {wfa_spec['folds_count']} folds; received {len(folds)}")
    for fold in folds:
        expected_day_after_train = date.fromisoformat(fold["train_end"]) + timedelta(days=1)
        if expected_day_after_train != date.fromisoformat(fold["test_start"]):
            raise RuntimeError(f"Fold {fold['fold_index']}: train_end must be the day before test_start")

    with open(CANDIDATES_MANIFEST_PATH, "r", encoding="utf-8") as f:
        cand_manifest = json.load(f)
    candidates_by_aid = cand_manifest["candidates"]
    if args.alpha_id not in candidates_by_aid:
        raise KeyError(f"Unknown alpha ID: {args.alpha_id}")
    item = candidates_by_aid[args.alpha_id]
    variants = [v for v in item.get("variants", []) if v.get("candidate_id") == args.candidate_id]
    if len(variants) != 1:
        raise ValueError(f"Expected exactly one candidate {args.candidate_id} under {args.alpha_id}; found {len(variants)}")
    if item.get("is_low_sample", False):
        raise ValueError(f"Alpha {args.alpha_id} is marked sample-limited; refusing candidate scan")
    output_path = args.output or CHECK_DIR / f"edu_evolution_wfa_{args.alpha_id}_{args.candidate_id}_exact.json"
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(f"Refusing to overwrite existing report: {output_path}; pass --overwrite intentionally")

    wfa_results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "protocol_version": protocol["protocol_version"],
        "protocol_sha256": protocol["protocol_sha256"],
        "candidate_manifest_sha256": hashlib.sha256(CANDIDATES_MANIFEST_PATH.read_bytes()).hexdigest(),
        "run_scope": {"alpha_id": args.alpha_id, "candidate_id": args.candidate_id, "folds": len(folds),
                      "execution": "single_candidate_sequential", "memory_cap": "2GB via nora/edu/ops/run_limited.sh"},
        "run_status": "RUNNING",
        "total_evaluated": 1,
        "candidates_evaluated": {},
        "verdict_summary": {
            "WFA_PASS": 0,
            "WFA_FAIL": 0,
            "INSUFFICIENT_SAMPLE": 0,
            "BLOCKED": 0
        }
    }

    aid = args.alpha_id
    name = item.get("parent_name")

    print(f"\nEvaluating Alpha: {aid} - {name}")

    v = variants[0]
    cand_id = v["candidate_id"]
    cand_file = ROOT / v["file"]
    cand_data = json.loads(cand_file.read_text(encoding="utf-8"))
    wfa_results["candidate_source_sha256"] = hashlib.sha256(cand_file.read_bytes()).hexdigest()

    code = cand_data["code"]
    cfg = cand_data["config"]
    pos = cfg.get("position", {})

    print(f"  - Testing Candidate: {cand_id} ({v['hypothesis_type']})")

    fold_results = []
    total_wfa_trades = 0
    positive_folds = 0
    wfa_returns = []
    wfa_mdds = []
    total_fees = 0.0
    net_pnl_usd = 0.0
    test_pnls = []
    fold_sample_passes = True

    wfa_results["candidates_evaluated"][aid] = {
        "name": name,
        "parent_aid": aid,
        "overall_verdict": "IN_PROGRESS",
        "variant_evaluations": [{"candidate_id": cand_id, "status": "IN_PROGRESS", "folds_detail": fold_results}],
    }
    _write_checkpoint(output_path, wfa_results)

    for fold in folds:
        f_idx = fold["fold_index"]
        train_start = fold["train_start"]
        test_start = fold["test_start"]
        test_end = fold["test_end"]
        train_days = (date.fromisoformat(test_start) - date.fromisoformat(train_start)).days
        total_days = (date.fromisoformat(test_end) + timedelta(days=1) - date.fromisoformat(train_start)).days
        t_ratio = round(train_days / total_days, 2)
        params = {
            "code": code,
            "symbols": cfg.get("symbols", ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "TRX"]),
            "start": train_start,
            "end": test_end,
            "test_start": test_start,
            "run_frame": cfg.get("run_frame", "24h"),
            "train_ratio": t_ratio,
            "initial_capital": 10000.0,
            "position": pos,
            "include_benchmark": False,
            "include_diagnostics": False,
            "parallel_runs": False,
        }

        try:
            res = run_custom(params)
            if not isinstance(res, dict) or not isinstance(res.get("metrics"), dict):
                raise RuntimeError(f"{cand_id} fold {f_idx}: runner returned no metrics")
            metrics = res["metrics"]
            test_metrics = metrics.get("test")
            train_metrics = metrics.get("train")
            if not isinstance(test_metrics, dict) or not isinstance(train_metrics, dict):
                raise RuntimeError(f"{cand_id} fold {f_idx}: missing train/test metrics")
            if (res.get("config") or {}).get("test_start") != test_start:
                raise RuntimeError(f"{cand_id} fold {f_idx}: effective test_start does not match {test_start}")
            if (res.get("config") or {}).get("end") != test_end:
                raise RuntimeError(f"{cand_id} fold {f_idx}: effective end does not match {test_end}")
            expected_split = date_ms(test_start) // 1000
            if (res.get("series") or {}).get("stage_split") != expected_split:
                raise RuntimeError(f"{cand_id} fold {f_idx}: series stage split does not match {test_start}")

            ret_pct = float(test_metrics["ret_pct"])
            mdd_pct = float(test_metrics["mdd_pct"])
            t_count = int(test_metrics["trades"])
            fees_usd = float(test_metrics["fees_usd"])
            train_ret = float(train_metrics["ret_pct"])
            test_trades = res.get("test_trades")
            if not isinstance(test_trades, list) or len(test_trades) != t_count:
                raise RuntimeError(f"{cand_id} fold {f_idx}: test ledger rows do not reconcile with metrics")
            if any(int(trade["enter_time"]) < date_ms(test_start) for trade in test_trades):
                raise RuntimeError(f"{cand_id} fold {f_idx}: test ledger contains a pre-boundary entry")
            if any(int(trade["close_time"]) >= date_ms(test_end) + 86_400_000 for trade in test_trades):
                raise RuntimeError(f"{cand_id} fold {f_idx}: test ledger contains a post-window exit")
        except Exception as err:
            wfa_results["run_status"] = "FAILED"
            wfa_results["failure"] = {"candidate_id": cand_id, "fold_index": f_idx, "error": str(err)}
            wfa_results["candidates_evaluated"][aid]["variant_evaluations"][0]["status"] = "FAILED"
            _write_checkpoint(output_path, wfa_results)
            raise

        test_pnls.extend(float(trade["pnl_usd"]) for trade in test_trades)
        fold_sample_passes = fold_sample_passes and t_count >= gates["min_trades_per_fold"]
        total_wfa_trades += t_count
        total_fees += fees_usd
        net_pnl_usd += 10000.0 * ret_pct / 100.0
        wfa_returns.append(ret_pct)
        wfa_mdds.append(mdd_pct)
        positive_folds += int(ret_pct > 0)
        fold_results.append({
            "fold_index": f_idx,
            "window": f"{test_start} -> {test_end}",
            "train_ret_pct": round(train_ret, 2),
            "test_ret_pct": round(ret_pct, 2),
            "test_mdd_pct": round(mdd_pct, 2),
            "test_trade_count": t_count,
            "test_fees_usd": round(fees_usd, 2),
            "effective_config": res["config"],
            "effective_test_start": res["config"]["test_start"],
            "effective_split_epoch_us": res["series"]["stage_split"],
            "test_metrics": test_metrics,
            "program_hash": res.get("program_hash"),
            "data": res.get("data"),
            "provenance": res.get("provenance"),
            "test_trade_rows": test_trades,
        })
        wfa_results["candidates_evaluated"][aid]["variant_evaluations"][0]["folds_detail"] = fold_results
        wfa_results["candidates_evaluated"][aid]["variant_evaluations"][0]["folds_completed"] = len(fold_results)
        _write_checkpoint(output_path, wfa_results)
        print(f"      Fold {f_idx} (OOS: {test_start} -> {test_end}): Train = {train_ret:+.2f}%, Test = {ret_pct:+.2f}%, MDD = {mdd_pct:.2f}%, Trades = {t_count}")
        del res

    avg_return = round(sum(wfa_returns) / len(wfa_returns), 2) if wfa_returns else 0.0
    max_mdd = round(max(wfa_mdds), 2) if wfa_mdds else 0.0
    pos_ratio = round(positive_folds / len(folds), 2) if folds else 0.0
    total_gross_pnl = net_pnl_usd + total_fees
    winning_pnl = sum(pnl for pnl in test_pnls if pnl > 0)
    losing_pnl = abs(sum(pnl for pnl in test_pnls if pnl < 0))
    win_rate_pct = 100.0 * sum(pnl > 0 for pnl in test_pnls) / len(test_pnls) if test_pnls else None
    profit_factor = winning_pnl / losing_pnl if losing_pnl > 0 else None
    expectancy_usd = sum(test_pnls) / len(test_pnls) if test_pnls else None
    stressed_net_pnl = total_gross_pnl - total_fees * gates["fee_stress_test"]["stress_multiplier"]
    checks = {
        "trades_gte_20": total_wfa_trades >= gates["min_total_trades"] and fold_sample_passes,
        "return_positive": net_pnl_usd > 0,
        "mdd_lte_30": max_mdd <= gates["max_drawdown_pct"],
        "positive_folds_gte_66pct": pos_ratio >= gates["min_positive_folds_ratio"],
        "passed_fee_stress_1_5x": stressed_net_pnl > 0,
        "win_rate_gte_gate": win_rate_pct is not None and win_rate_pct >= gates["min_win_rate_pct"],
        "profit_factor_gte_gate": (winning_pnl > 0 and losing_pnl == 0)
        or (profit_factor is not None and profit_factor >= gates["min_profit_factor"]),
        "net_expectancy_gte_gate": expectancy_usd is not None and expectancy_usd >= gates["min_net_expectancy_usd"],
    }
    verdict = "INSUFFICIENT_SAMPLE" if not checks["trades_gte_20"] else (
        "WFA_PASS" if all(checks.values()) else "WFA_FAIL"
    )
    evaluation = {
        "candidate_id": cand_id,
        "hypothesis_type": v["hypothesis_type"],
        "total_trades": total_wfa_trades,
        "win_rate_pct": round(win_rate_pct, 2) if win_rate_pct is not None else None,
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "net_expectancy_usd": round(expectancy_usd, 4) if expectancy_usd is not None else None,
        "net_pnl_usd": round(net_pnl_usd, 2),
        "avg_test_return_pct": avg_return,
        "max_drawdown_pct": max_mdd,
        "positive_folds_ratio": pos_ratio,
        "stressed_net_pnl_usd": round(stressed_net_pnl, 2),
        "gate_checks": checks,
        "verdict": verdict,
        "folds_detail": fold_results,
    }
    wfa_results["candidates_evaluated"][aid] = {
        "name": name,
        "parent_aid": aid,
        "overall_verdict": verdict,
        "variant_evaluations": [evaluation],
    }
    wfa_results["verdict_summary"][verdict] += 1
    wfa_results["run_status"] = "COMPLETED"
    _write_checkpoint(output_path, wfa_results)
    print(f"\n[DONE] Report: {output_path}")
    print(f"  • Verdict Summary: {wfa_results['verdict_summary']}")


if __name__ == "__main__":
    main()
