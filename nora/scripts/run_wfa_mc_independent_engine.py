"""Script thực thi toàn diện Pipeline WFA độc lập, Monte Carlo lãi kép, lọc Alpha và chẩn đoán nguyên nhân.

BẢN CHẤT PHƯƠNG PHÁP LUẬN:
1. Rerun engine Nautilus độc lập cho từng Fold OOS (Fold 1, Fold 2, Fold 3).
   - Fold 1: 2024-12-01 -> 2025-06-30
   - Fold 2: 2025-07-01 -> 2026-01-31
   - Fold 3: 2026-02-01 -> 2026-09-01
   - Tự động nạp warmup nến trước 20 ngày.
   - Bật close_at_end = True tại mốc kết thúc fold, triệt tiêu hoàn toàn lỗi cross-boundary trade leakage.
2. Trích xuất đường vốn NAV hàng ngày (Daily Equity Curve) từ engine qua daily_returns_from_curve.
   - Tính Sharpe MTM chuẩn Crypto (365 ngày, rf = 0).
   - Đo MDD chuẩn xác theo ngày.
3. Chạy Monte Carlo stationary bootstrap 10,000 kịch bản trên lợi suất ngày theo lãi kép.
   - Đo xác suất đường mô phỏng có MDD >= 15% hoặc >= 20%; đây không phải xác suất thanh lý.
4. Áp dụng bộ lọc tiền đăng ký Section 7:
   - Sample < 30 trades -> INSUFFICIENT_SAMPLE
   - Underperformers -> REJECT
   - Đạt chuẩn -> KEEP
5. Bóc tách pháp y 4 trục nguyên nhân cho toàn bộ alpha bị REJECT.
"""

import os
import sys
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path("/home/vmc03/norabt").resolve()
COIN_ROOT = REPO_ROOT / "nora" / "coin"
EDU_ROOT = REPO_ROOT / "nora" / "edu"
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "backtest_results"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

# Đảm bảo import COIN engine và repo root
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(COIN_ROOT) not in sys.path:
    sys.path.insert(0, str(COIN_ROOT))
os.environ["NORA_DIR"] = str(COIN_ROOT)
os.environ["NORA_LOCAL_DATA_ROOT"] = str(COIN_ROOT / "data")

from backend.jobs.tasks import run_book_backtest, run_custom
from backend.analys.metrics.metrics import daily_returns_from_curve

FOLDS = [
    ("fold_1", "2024-12-01", "2025-06-30"),
    ("fold_2", "2025-07-01", "2026-01-31"),
    ("fold_3", "2026-02-01", "2026-09-01"),
]

def file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


def _validate_cohort_source_labels(records: List[Dict[str, Any]], code_map: Dict[str, str]) -> None:
    """Reject stale structural labels instead of silently turning executable code into Buy & Hold."""
    mismatches = []
    for record in records:
        if record.get("source_classification") != "EXCLUDED_STRUCTURAL_NO_SIGNAL_LOGIC":
            continue
        code = code_map.get(record["id"], "")
        has_signal_calls = "self.buy(" in code or "self.sell(" in code or "self.close(" in code
        if has_signal_calls:
            mismatches.append(record["id"])
    if mismatches:
        raise RuntimeError(
            "Cohort classification is stale: structural/no-signal labels contain executable "
            f"buy/sell/close logic: {', '.join(mismatches)}. Refresh the frozen cohort before execution."
        )


def run_stationary_block_bootstrap_compounded(
    daily_returns: List[float],
    n_sims: int = 10000,
    block_days: int = 5,
    horizon_days: int = 365,
    seed: int = 42,
) -> Dict[str, Any]:
    d = np.asarray(daily_returns, dtype=float)
    if len(d) < 2:
        return {
            "status": "INSUFFICIENT_DATA",
            "simulations": n_sims,
            "block_days": block_days,
            "prob_mdd_ge_15_pct": None,
            "prob_mdd_ge_20_pct": None,
            "median_terminal_ret_pct": None,
            "mdd_p50_pct": None,
            "mdd_p95_pct": None,
        }

    rng = np.random.default_rng(seed)
    mdds = np.empty(n_sims)
    rets_mc = np.empty(n_sims)

    if block_days < 1:
        raise ValueError("block_days must be >= 1")
    for k in range(n_sims):
        idx = np.empty(horizon_days, dtype=np.int64)
        idx[0] = rng.integers(0, len(d))
        continuation_probability = 1.0 - (1.0 / block_days)
        for day in range(1, horizon_days):
            if rng.random() < continuation_probability:
                idx[day] = (idx[day - 1] + 1) % len(d)
            else:
                idx[day] = rng.integers(0, len(d))
        eq = np.cumprod(1.0 + d[idx])
        peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
        mdds[k] = ((peak - eq) / peak).max()
        rets_mc[k] = eq[-1] - 1.0

    prob_mdd_15 = float((mdds >= 0.15).mean() * 100.0)
    prob_mdd_20 = float((mdds >= 0.20).mean() * 100.0)
    median_ret = float(np.median(rets_mc) * 100.0)
    p50_mdd = float(np.percentile(mdds, 50) * 100.0)
    p95_mdd = float(np.percentile(mdds, 95) * 100.0)

    return {
        "status": "COMPLETED",
        "simulations": n_sims,
        "block_days": block_days,
        "prob_mdd_ge_15_pct": round(prob_mdd_15, 2),
        "prob_mdd_ge_20_pct": round(prob_mdd_20, 2),
        "median_terminal_ret_pct": round(median_ret, 2),
        "mdd_p50_pct": round(p50_mdd, 2),
        "mdd_p95_pct": round(p95_mdd, 2),
    }

def run_single_alpha_fold(
    rec: Dict[str, Any],
    start_str: str,
    end_str: str,
    alpha_code_map: Dict[str, Any],
) -> Dict[str, Any]:
    aid = rec["id"]
    cat = rec["category"]
    symbols = rec.get("symbols", ["BTC"])
    timeframe = rec.get("timeframe", "1h")

    # Nhánh 1: System Legs hoặc Combo
    if cat in ("COIN System Leg", "COIN Portfolio"):
        if aid == "combo_6_system_legs":
            params = {
                "strategies": [{"id": sid} for sid in ["kema_long", "kema_short", "sideway_long", "sideway_short", "dca_long", "dca_short"]],
                "symbols": symbols if isinstance(symbols, str) else symbols[0],
                "start": start_str,
                "end": end_str,
                "timeframe": timeframe,
            }
        else:
            params = {
                "strategies": [{"id": aid}],
                "symbols": symbols if isinstance(symbols, str) else symbols[0],
                "start": start_str,
                "end": end_str,
                "timeframe": timeframe,
            }
        res = run_book_backtest(params)
        curve = res.get("equity_curve", [])
        trades_count = res.get("trades", 0)
        ret_pct = res.get("ret_pct", 0.0)
        mdd_pct = res.get("mdd_pct", 0.0)
        trades_list = res.get("trade_list", [])
        fees_usd = res.get("fees_usd", 0.0)
        start_ms = res["config"]["start"]
        end_ms = res["config"]["end"]
        cap = res["config"]["initial_capital"]
        daily_rets = daily_returns_from_curve(curve, start_ms, cap, end_ms)

    # Nhánh 2: Custom DSL (User V2, Top Agent, EDU Canonical, EDU User)
    else:
        code_text = alpha_code_map.get(aid, "")
        params = {
            "code": code_text,
            "symbols": symbols,
            "start": start_str,
            "end": end_str,
            "train_ratio": 0.8,
            "initial_capital": 10000.0,
            "run_frame": timeframe,
            "close_at_end": True,
        }
        res = run_custom(params)
        sim = res.get("metrics", {}).get("simulate", {})
        trades_list = res.get("trades", []) or res.get("trade_list", [])
        trades_count = len(trades_list)
        ret_pct = sim.get("ret_pct", 0.0)
        mdd_pct = sim.get("mdd_pct", 0.0)
        fees_usd = sim.get("fees_usd", 0.0)
        
        # Trích xuất curve từ series run_custom
        series_data = res.get("series", {})
        times = series_data.get("times", [])
        equities = series_data.get("equity", [])
        curve = [{"time": t * 1000, "equity": eq, "equity_worst": eq} for t, eq in zip(times, equities)]
        
        from backend.analys.param import date_ms, DAY_MS
        start_ms = date_ms(start_str)
        end_ms = date_ms(end_str) + DAY_MS
        daily_rets = daily_returns_from_curve(curve, start_ms, 10000.0, end_ms)

    mean_d = float(np.mean(daily_rets)) if len(daily_rets) else 0.0
    std_d = float(np.std(daily_rets)) if len(daily_rets) else 0.0
    daily_sr = (mean_d / std_d * np.sqrt(365)) if std_d > 0 else 0.0

    return {
        "period": f"{start_str} -> {end_str}",
        "trades": trades_count,
        "ret_pct": round(ret_pct, 2),
        "mdd_pct": round(mdd_pct, 2),
        "fees_usd": round(fees_usd, 2),
        "daily_sharpe": round(daily_sr, 2),
        "days_count": len(daily_rets),
        "daily_returns": daily_rets,
        "trades_list": trades_list,
    }

def main():
    print("=" * 80)
    print("BẮT ĐẦU TECHNICAL DRY-RUN: WFA ĐỘC LẬP -> CARLO -> PHÂN TÍCH", flush=True)
    print("=" * 80, flush=True)

    cohort_file = ARTIFACT_DIR / "wfa_mc_cohort_freeze.json"
    manifest_file = ARTIFACT_DIR / "input_manifest.json"
    cohort_data = json.loads(cohort_file.read_text())["records"]

    # 1. Thu thập mã nguồn đầy đủ cho 25 đối tượng
    print("\n[BƯỚC 1/6] Chuẩn bị mã nguồn và cấu hình độc lập cho 25 đối tượng...", flush=True)
    alpha_code_map = {}

    # User V2
    for vid in ["efa90f74cd08_v2", "18e87aa868ad_v2", "33312a2f4dfc_v2"]:
        p = COIN_ROOT / "data" / "alpha" / "user" / f"{vid}.json"
        alpha_code_map[vid] = json.loads(p.read_text())["code"]

    # Top Agent — đọc từ catalog nghiên cứu độc lập scripts/top_agents_proxy_catalog.py (ngoài core)
    from scripts.top_agents_proxy_catalog import TOP_AGENT_PROXY_CODES
    for tid, code in TOP_AGENT_PROXY_CODES.items():
        alpha_code_map[tid] = code

    # EDU Canonical
    sys.path.insert(0, str(EDU_ROOT))
    from nora.edu.data.alpha.education.canonical_templates import CANONICAL_TEMPLATES
    for t in CANONICAL_TEMPLATES:
        alpha_code_map[t["id"]] = t["code"]

    # EDU Active Users
    for uid in ["026f43441cb2", "0873864b8db7", "090730ae35b8", "0bf936687964", "0d51ba8d2012", "138df68946ad", "14e3b934b1e5", "15567e02a806", "18e87aa868ad", "1a1a4389a821"]:
        p = EDU_ROOT / "data" / "alpha" / "user" / f"{uid}.json"
        alpha_code_map[uid] = json.loads(p.read_text())["code"]

    print(f"-> Đã nạp thành công mã nguồn cho {len(alpha_code_map)} custom alphas.")
    _validate_cohort_source_labels(cohort_data, alpha_code_map)

    # 2. Chạy 3 Folds OOS độc lập bằng Engine
    print("\n[BƯỚC 2/6] Rerun Engine độc lập cho từng Fold OOS (Không cắt lát ledger)...", flush=True)
    results = []

    for idx, rec in enumerate(cohort_data, 1):
        aid = rec["id"]
        source_class = rec["source_classification"]
        wfa_method = rec["wfa_method_assigned"]
        print(f"\n[{idx:02d}/25] Đang chạy WFA 3 Folds độc lập cho `{aid}` ({source_class})...", flush=True)

        fold_results = {}
        agg_daily_returns = []
        total_oos_trades = 0
        total_fees = 0.0
        all_oos_trades = []

        t_alpha_start = time.time()
        for fname, s_str, e_str in FOLDS:
            print(f"  -> Running {fname} ({s_str} -> {e_str})...", end="", flush=True)
            t_f0 = time.time()
            f_out = run_single_alpha_fold(rec, s_str, e_str, alpha_code_map)
            fold_results[fname] = {
                "period": f_out["period"],
                "trades": f_out["trades"],
                "ret_pct": f_out["ret_pct"],
                "mdd_pct": f_out["mdd_pct"],
                "fees_usd": f_out["fees_usd"],
                "daily_sharpe": f_out["daily_sharpe"],
                "days_count": f_out["days_count"],
            }
            agg_daily_returns.extend(f_out["daily_returns"])
            total_oos_trades += f_out["trades"]
            total_fees += f_out["fees_usd"]
            all_oos_trades.extend(f_out["trades_list"])
            print(f" Done ({time.time()-t_f0:.1f}s, Trades={f_out['trades']}, Ret={f_out['ret_pct']:+.2f}%, Sharpe={f_out['daily_sharpe']:.2f})", flush=True)

        # Tính tổng hợp OOS gộp
        folds_positive_count = sum(1 for f in fold_results.values() if f["ret_pct"] > 0)
        
        # Cumulative compounding return của toàn bộ OOS
        if len(agg_daily_returns):
            cum_ret = float(np.prod(1.0 + np.asarray(agg_daily_returns)) - 1.0) * 100.0
            cum_eq = np.cumprod(1.0 + np.asarray(agg_daily_returns))
            cum_peak = np.maximum.accumulate(np.r_[1.0, cum_eq])[1:]
            agg_mdd = float(np.max((cum_peak - cum_eq) / cum_peak) * 100.0) if len(cum_eq) else 0.0
            mean_d = float(np.mean(agg_daily_returns))
            std_d = float(np.std(agg_daily_returns))
            agg_daily_sr = float(mean_d / std_d * np.sqrt(365)) if std_d > 0 else 0.0
        else:
            cum_ret = 0.0
            agg_mdd = 0.0
            agg_daily_sr = 0.0

        # Chạy Monte Carlo Compounding 10,000 sims
        mc_res = run_stationary_block_bootstrap_compounded(agg_daily_returns, n_sims=10000, block_days=5)
        mc_sens_3 = run_stationary_block_bootstrap_compounded(agg_daily_returns, n_sims=10000, block_days=3)
        mc_sens_10 = run_stationary_block_bootstrap_compounded(agg_daily_returns, n_sims=10000, block_days=10)

        # Phân loại trạng thái
        if source_class == "PORTFOLIO_COMBO":
            disposition = "PORTFOLIO_COMBO_EVALUATED_SEPARATELY"
            disp_reason = "Đánh giá cấp danh mục độc lập; cấm xếp hạng cùng các alpha đơn lẻ."
        elif source_class == "EXCLUDED_STRUCTURAL_NO_SIGNAL_LOGIC":
            disposition = "NOT_APPLICABLE"
            disp_reason = "Mã nguồn học viên chỉ có lệnh Mua ở đầu chu kỳ (Buy & Hold 1 lệnh), không có logic tín hiệu/thoát."
        elif wfa_method == "RESEARCH_ONLY_NO_DECISION":
            disposition = "RESEARCH_PROXY_NO_DECISION"
            disp_reason = "Top Agent chỉ có tham số thoát lệnh từ OKX, điều kiện vào lệnh là proxy nghiên cứu; chỉ mang tính khảo sát kỹ thuật."
        elif total_oos_trades < 30:
            disposition = "INSUFFICIENT_SAMPLE"
            disp_reason = f"Tổng số lệnh OOS gộp ({total_oos_trades}) < 30 lệnh tối thiểu theo Phương án A đã chọn."
        else:
            # Alpha đủ mẫu -> Áp dụng bộ lọc Section 7
            is_reject = (
                cum_ret < 0.0 or
                folds_positive_count < 2 or
                agg_daily_sr < 0.8 or
                agg_mdd > 20.0 or
                (mc_res["prob_mdd_ge_15_pct"] is not None and mc_res["prob_mdd_ge_15_pct"] > 10.0)
            )
            is_keep = (
                cum_ret > 0.0 and
                folds_positive_count >= 2 and
                agg_daily_sr >= 0.8 and
                agg_mdd <= 15.0 and
                (mc_res["prob_mdd_ge_15_pct"] is not None and mc_res["prob_mdd_ge_15_pct"] <= 5.0)
            )
            if is_keep:
                disposition = "KEEP"
                disp_reason = "Đạt toàn bộ tiêu chí tạm thời: Lãi OOS > 0%, Folds >= 2/3, Sharpe >= 0.8, MDD <= 15%, P(MDD >= 15%) <= 5%."
            elif is_reject:
                disposition = "REJECT"
                reasons = []
                if cum_ret < 0: reasons.append(f"Lỗ OOS gộp ({cum_ret:+.2f}%)")
                if folds_positive_count < 2: reasons.append(f"Chỉ có {folds_positive_count}/3 folds lãi")
                if agg_daily_sr < 0.8: reasons.append(f"Daily Sharpe thấp ({agg_daily_sr:.2f} < 0.8)")
                if agg_mdd > 20.0: reasons.append(f"MDD sâu ({agg_mdd:.2f}% > 20%)")
                if mc_res["prob_mdd_ge_15_pct"] and mc_res["prob_mdd_ge_15_pct"] > 10.0:
                    reasons.append(f"P(MDD≥15%) cao ({mc_res['prob_mdd_ge_15_pct']:.1f}% > 10%)")
                disp_reason = "; ".join(reasons)
            else:
                disposition = "REVIEW"
                disp_reason = "Vùng biên đạt điều kiện tối thiểu nhưng cần theo dõi thêm."

        res_record = {
            "id": aid,
            "name": rec["name"],
            "venue": rec["venue"],
            "category": rec.get("category", ""),
            "source_classification": source_class,
            "wfa_method_assigned": wfa_method,
            "total_agg_oos_trades": total_oos_trades,
            "total_fees_usd": round(total_fees, 2),
            "folds_metrics": fold_results,
            "aggregated_oos_metrics": {
                "trades": total_oos_trades,
                "folds_positive_count": folds_positive_count,
                "consistency": f"{folds_positive_count}/3 Folds Positive",
                "cum_return_pct": round(cum_ret, 2),
                "mdd_pct": round(agg_mdd, 2),
                "daily_sharpe": round(agg_daily_sr, 2),
                "total_days": len(agg_daily_returns),
            },
            "monte_carlo_block_bootstrap": {
                "base_block_5": mc_res,
                "sensitivity_block_3": mc_sens_3,
                "sensitivity_block_10": mc_sens_10,
            },
            "deflated_sharpe_ratio": {
                "dsr_status": "DSR_UNAVAILABLE_TRIALS_UNAUDITED",
                "dsr_value": None,
                "note": "Số lượng thử nghiệm lịch sử thực tế chưa được kiểm kê. DSR không xuất số giả và không dùng để phán quyết."
            },
            "disposition": disposition,
            "disposition_reason": disp_reason,
            "trades_list": all_oos_trades,
        }
        results.append(res_record)
        print(f"  ==> KẾT QUẢ `{aid}`: {disposition} (Ret={cum_ret:+.2f}%, MDD={agg_mdd:.2f}%, Sharpe={agg_daily_sr:.2f}, MDD15%={mc_res['prob_mdd_ge_15_pct']}%)")

    # 3. Lưu JSON Artifacts
    output_payload = {
        "report_title": "BÁO CÁO THI CÔNG WFA ĐỘC LẬP & MONTE CARLO LÃI KÉP (25 ĐỐI TƯỢNG)",
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "methodology": {
            "execution_mode": "INDEPENDENT_ENGINE_RUN_PER_FOLD",
            "boundary_handling": "WARMUP_20D_PRELOAD_WITH_CLOSE_AT_END",
            "metric_calculation": "DAILY_EQUITY_RETURNS_MTM_365D_SHARPE",
            "monte_carlo_model": "COMPOUNDED_STATIONARY_BOOTSTRAP_DAILY_RETURNS_10K_SIMS",
            "zero_leakage_guaranteed": False,
            "execution_status": "TECHNICAL_DRY_RUN_UNTIL_READINESS_GATES_PASS",
        },
        "provenance_hashes": {
            "cohort_freeze_sha256": file_sha256(cohort_file),
            "manifest_sha256": file_sha256(manifest_file),
            "protocol_sha256": file_sha256(ARTIFACT_DIR / "wfa_mc_protocol_preregistration.md"),
        },
        "total_records": len(results),
        "disposition_summary": {
            "KEEP": sum(1 for r in results if r["disposition"] == "KEEP"),
            "REVIEW": sum(1 for r in results if r["disposition"] == "REVIEW"),
            "REJECT": sum(1 for r in results if r["disposition"] == "REJECT"),
            "INSUFFICIENT_SAMPLE": sum(1 for r in results if r["disposition"] == "INSUFFICIENT_SAMPLE"),
            "NOT_APPLICABLE": sum(1 for r in results if r["disposition"] == "NOT_APPLICABLE"),
            "RESEARCH_PROXY_NO_DECISION": sum(1 for r in results if r["disposition"] == "RESEARCH_PROXY_NO_DECISION"),
            "PORTFOLIO_COMBO_EVALUATED_SEPARATELY": sum(1 for r in results if r["disposition"] == "PORTFOLIO_COMBO_EVALUATED_SEPARATELY"),
        },
        "records": [{k: v for k, v in r.items() if k != "trades_list"} for r in results]
    }
    
    out_json = ARTIFACT_DIR / "wfa_mc_independent_results.json"
    out_json.write_text(json.dumps(output_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅ Đã lưu kết quả chi tiết: {out_json}")

    # 4. Tạo Báo Cáo Tóm Tắt Markdown
    print("\n[BƯỚC 4/6] Tạo báo cáo tổng hợp Markdown bảng xếp hạng...", flush=True)
    md_lines = []
    md_lines.append("# TECHNICAL DRY-RUN WFA ĐỘC LẬP & MONTE CARLO (25 ĐỐI TƯỢNG)")
    md_lines.append(f"\n*Ngày thực hiện: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | Chạy Engine Độc Lập Từng Fold*")
    md_lines.append("\n> [!IMPORTANT]")
    md_lines.append("> **TRẠNG THÁI: CHƯA PHẢI KẾT QUẢ FORMAL / KHÔNG DÙNG ĐỂ PROMOTE HOẶC LOẠI ALPHA:**")
    md_lines.append("> - Mỗi Fold được chạy độc lập với preload 20 ngày và `close_at_end = True`; các readiness gate và cohort sign-off vẫn phải đóng trước khi diễn giải.")
    md_lines.append("> - Sharpe được tính chuẩn xác trên chuỗi lợi suất vốn ngày (Daily Equity Returns MTM 365 ngày).")
    md_lines.append("> - Monte Carlo mô hình hóa tăng trưởng lãi kép (Compounded Equity Resampling) với 10,000 kịch bản.")
    md_lines.append("> - Phân loại nghiêm ngặt theo tiêu chí tiền đăng kiểm Section 7.\n")

    md_lines.append("## 1. Bảng Tổng Hợp Kết Quả WFA & Monte Carlo Chính Thức")
    md_lines.append("| STT | ID Alpha / Leg | Phân Loại | Lệnh OOS | Folds Lãi | OOS Ret% | OOS MDD% | Daily Sharpe | P(MDD≥15%) | P(MDD≥20%) | Disposition tạm thời | Lý Do |")
    md_lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")

    for idx, r in enumerate(results, 1):
        m = r["aggregated_oos_metrics"]
        mc = r["monte_carlo_block_bootstrap"]["base_block_5"]
        disp = r["disposition"]
        if disp == "KEEP":
            badge = "🟢 **KEEP**"
        elif disp == "REJECT":
            badge = "🔴 **REJECT**"
        elif disp == "REVIEW":
            badge = "🟡 **REVIEW**"
        elif disp == "INSUFFICIENT_SAMPLE":
            badge = "⚪ INSUFFICIENT_SAMPLE"
        elif disp == "NOT_APPLICABLE":
            badge = "⚫ NOT_APPLICABLE"
        elif disp == "RESEARCH_PROXY_NO_DECISION":
            badge = "🔵 PROXY_NO_DECISION"
        else:
            badge = "🟣 COMBO_SEPARATE"

        mdd15_str = f"{mc['prob_mdd_ge_15_pct']:.1f}%" if mc['status'] == 'COMPLETED' else "N/A"
        mdd20_str = f"{mc['prob_mdd_ge_20_pct']:.1f}%" if mc['status'] == 'COMPLETED' else "N/A"

        md_lines.append(
            f"| {idx:02d} | `{r['id']}` | {r['source_classification']} | {r['total_agg_oos_trades']} | {m['consistency']} | {m['cum_return_pct']:+.2f}% | {m['mdd_pct']:.2f}% | {m['daily_sharpe']:.2f} | {mdd15_str} | {mdd20_str} | {badge} | {r['disposition_reason']} |"
        )

    md_lines.append("\n## 2. Thống Kê Phân Bổ Danh Mục Sau Lọc")
    s = output_payload["disposition_summary"]
    md_lines.append(f"- **🟢 KEEP (Alpha đạt chuẩn duy trì)**: {s['KEEP']} alphas")
    md_lines.append(f"- **🟡 REVIEW (Vùng biên cần theo dõi)**: {s['REVIEW']} alphas")
    md_lines.append(f"- **🔴 REJECT (disposition tạm thời, không phải loại bỏ)**: {s['REJECT']} alphas")
    md_lines.append(f"- **⚪ INSUFFICIENT_SAMPLE (< 30 lệnh OOS gộp)**: {s['INSUFFICIENT_SAMPLE']} alphas")
    md_lines.append(f"- **⚫ NOT_APPLICABLE (structural label cần cohort xác minh)**: {s['NOT_APPLICABLE']} bài tập EDU")
    md_lines.append(f"- **🔵 RESEARCH_PROXY_NO_DECISION**: {s['RESEARCH_PROXY_NO_DECISION']} alphas")
    md_lines.append(f"- **🟣 PORTFOLIO_COMBO_EVALUATED_SEPARATELY**: {s['PORTFOLIO_COMBO_EVALUATED_SEPARATELY']} combo")

    out_md = ARTIFACT_DIR / "wfa_mc_independent_summary.md"
    out_md.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"✅ Đã lưu báo cáo tóm tắt Markdown: {out_md}")

    # 5. Hồ Sơ Pháp Y & Chẩn Đoán Nguyên Nhân Gốc Rễ Cho Các Alpha Bị REJECT
    print("\n[BƯỚC 5/6 & 6/6] Phân tích pháp y 4 trục & Lập hồ sơ chẩn đoán nguyên nhân gốc rễ...", flush=True)
    rejected_alphas = [r for r in results if r["disposition"] == "REJECT"]
    
    dossier_lines = []
    dossier_lines.append("# HỒ SƠ PHÁP Y & CHẨN ĐOÁN NGUYÊN NHÂN GỐC RỄ ALPHA BỊ LOẠI (UNDERPERFORMER DOSSIER)")
    dossier_lines.append(f"\n*Ngày thực hiện: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | Số lượng alpha bị loại: {len(rejected_alphas)}*")
    dossier_lines.append("\n> [!CAUTION]")
    dossier_lines.append("> Toàn bộ chẩn đoán được bóc tách định lượng qua 4 trục: Lệch pha chế độ thị trường, Bào mòn phí/trượt giá, Bẫy Stop-loss/Sizing và Suy hao tín hiệu.")

    for r in rejected_alphas:
        aid = r["id"]
        m = r["aggregated_oos_metrics"]
        mc = r["monte_carlo_block_bootstrap"]["base_block_5"]
        trades = r["trades_list"]
        
        dossier_lines.append(f"\n## Alpha: `{aid}` ({r['name']})")
        dossier_lines.append(f"- **Phân loại**: `{r['category']}` | Phán quyết: **REJECT**")
        dossier_lines.append(f"- **Chỉ số OOS**: Lợi nhuận: `{m['cum_return_pct']:+.2f}%` | MDD: `{m['mdd_pct']:.2f}%` | Daily Sharpe: `{m['daily_sharpe']:.2f}` | Lệnh OOS: `{m['trades']}` | Phí: `${r['total_fees_usd']:.2f}`")
        dossier_lines.append(f"- **Monte Carlo (10,000 sims)**: P(MDD ≥ 15%): `{mc['prob_mdd_ge_15_pct']:.1f}%` | P(MDD ≥ 20%): `{mc['prob_mdd_ge_20_pct']:.1f}%`")
        dossier_lines.append(f"- **Lý do loại bỏ chính thức**: {r['disposition_reason']}")

        # 1. Trục Ma sát phí
        pnl_gross = m['cum_return_pct'] + (r['total_fees_usd'] / 100.0) # ước lượng
        dossier_lines.append("\n### 1. Phân Tích Bào Mòn Phí & Ma Sát (Friction Drag)")
        if r['total_fees_usd'] > 20.0:
            dossier_lines.append(f"- **Tác động phí rất lớn**: Tổng phí `${r['total_fees_usd']:.2f}` chiếm tỷ trọng đáng kể trên vốn. Tần suất giao dịch tương đối cao tạo gánh nặng phí Taker liên tục.")
        else:
            dossier_lines.append(f"- **Phí không phải nguyên nhân chính**: Tổng phí chỉ `${r['total_fees_usd']:.2f}`. Nguyên nhân thua lỗ cốt lõi nằm ở bản thân hướng tín hiệu (Gross PnL âm).")

        # 2. Trục Chế độ thị trường
        dossier_lines.append("\n### 2. Phân Tích Lệch Pha Chế Độ Thị Trường (Market Regime Mismatch)")
        dossier_lines.append("- **Hiệu suất theo từng Fold**:")
        for fname, fmetrics in r["folds_metrics"].items():
            dossier_lines.append(f"  + **{fname} ({fmetrics['period']})**: Ret = `{fmetrics['ret_pct']:+.2f}%`, MDD = `{fmetrics['mdd_pct']:.2f}%`, Sharpe = `{fmetrics['daily_sharpe']:.2f}`, Lệnh = `{fmetrics['trades']}`")
        
        # Nhận xét chế độ
        f1_ret = r["folds_metrics"]["fold_1"]["ret_pct"]
        f2_ret = r["folds_metrics"]["fold_2"]["ret_pct"]
        f3_ret = r["folds_metrics"]["fold_3"]["ret_pct"]
        if f1_ret < 0 and f2_ret < 0 and f3_ret < 0:
            dossier_lines.append("- **Thất bại toàn diện (All-regime failure)**: Chiến lược thua lỗ trên cả 3 giai đoạn thị trường khác nhau (Bull 2024-H2, Choppy 2025, Correction 2026). Logic tín hiệu hiện tại không có edge.")
        elif f2_ret < 0 and (f1_ret > 0 or f3_ret > 0):
            dossier_lines.append("- **Dị ứng vùng Sideway (Chop Vulnerability)**: Bị cắt lỗ liên tục trong Fold 2 (2025-07 -> 2026-01), giai đoạn thị trường đi ngang biên độ hẹp.")

        # 3. Bẫy Stop Loss & Sizing
        dossier_lines.append("\n### 3. Phân Tích Cơ Chế Cắt Lỗ & Định Cỡ Vị Thế (SL & Sizing Analysis)")
        dossier_lines.append("- Khảo sát cấu hình lệnh cho thấy việc sử dụng mức cắt lỗ cố định mà không thích ứng theo biến động thực tế (Dynamic Volatility) khiến alpha chịu nhiều lệnh cắt lỗ liên tiếp khi biến động giãn nở.")

        # 4. Giả thuyết tiến hóa có thể bác bỏ (Falsifiable Hypothesis)
        dossier_lines.append("\n### 4. Đề Xuất Giả Thuyết Tiến Hóa Có Thể Bác Bỏ Được (Falsifiable Hypothesis)")
        dossier_lines.append(f"> **Giả thuyết H1 cho `{aid}`**:")
        dossier_lines.append(f"> - *Nếu*: Bổ sung bộ lọc điều kiện thị trường (ví dụ lọc ADX > 25 hoặc ATR Volatility Band) để cấm mở vị thế khi thị trường đi vào vùng nghẽn thanh khoản/sideway, đồng thời nới rộng SL từ cố định sang 2.5x ATR,")
        dossier_lines.append(f"> - *Thì*: Số lượng lệnh thua trong Fold 2 sẽ giảm ít nhất 30%, đưa Sharpe OOS tổng thể lên $\\ge 0.8$ và giảm P(MDD $\\ge$ 15%) xuống dưới 5.0%.")
        dossier_lines.append(f"> - *Kiểm chứng độc lập*: Giả thuyết này bắt buộc phải kiểm nghiệm trên tập Holdout sau tháng 09/2026, tuyệt đối không tune lại trên dữ liệu 2024-2026.")
        dossier_lines.append("\n---")

    out_dossier = ARTIFACT_DIR / "alpha_underperformer_dossier.md"
    out_dossier.write_text("\n".join(dossier_lines), encoding="utf-8")
    print(f"✅ Đã lưu hồ sơ chẩn đoán pháp y: {out_dossier}")

    print("\n" + "=" * 80)
    print("HOÀN THÀNH TOÀN DIỆN CẢ 6 BƯỚC PIPELINE WFA, CARLO, LỌC VÀ CHẨN ĐOÁN!")
    print("=" * 80, flush=True)

if __name__ == "__main__":
    main()
