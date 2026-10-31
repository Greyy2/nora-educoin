#!/usr/bin/env python3
"""scripts/run_wfa_mc_rolling_oos_pipeline.py

Thực hiện Dry-Run hạ tầng kiểm định Rolling OOS (3 Folds) và Stationary Block Bootstrap Monte Carlo
cho toàn bộ 25 đối tượng trong cohort đóng băng.

CẢNH BÁO QUAN TRỌNG VỀ PHƯƠNG PHÁP LUẬN & RANH GIỚI NGHIỆM THU:
1. ĐÂY LÀ DRY-RUN HẠ TẦNG KỸ THUẬT — KHÔNG DÙNG RA QUYẾT ĐỊNH ALPHA (NON-DECISION DIAGNOSTIC).
2. Folds hiện tại được cắt từ raw trade ledger toàn kỳ theo enter_time, chưa phải rerun engine riêng cho từng fold.
   Các lệnh mở cuối fold nhưng đóng ở fold sau được tính toàn bộ PnL vào fold mở lệnh; các lệnh mở trước OOS fold đóng trong fold bị bỏ qua.
3. Sharpe ở đây là Trade-level PnL proxy ước lượng thô, chưa phải chuỗi lợi suất vốn theo ngày (Daily Equity Returns).
4. Monte Carlo resample PnL USD danh nghĩa trên vốn ban đầu cố định, chưa mô hình hóa sizing theo equity động hay compounding.
5. DSR chưa có danh sách kiểm kê trials thực tế; N=72 chỉ là kịch bản giả định bảo thủ từ universe manifest (BLOCKED_NOT_EVALUATED).
6. KHÔNG XUẤT BẤT KỲ NHÃN PHÁN QUYẾT NÀO (KEEP / REVIEW / REJECT) — MỌI THI CÔNG ALPHA VẪN BỊ KHÓA (BLOCKED).
"""

import json
import math
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple
import numpy as np

REPO_ROOT = Path("/home/vmc03/norabt")
OUT_DIR = REPO_ROOT / "artifacts" / "backtest_results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

COHORT_PATH = OUT_DIR / "wfa_mc_cohort_freeze.json"
PROTOCOL_PATH = OUT_DIR / "wfa_mc_protocol_preregistration.md"
MANIFEST_PATH = OUT_DIR / "input_manifest.json"
RESULTS_JSON_PATH = OUT_DIR / "wfa_mc_rolling_oos_results.json"
SUMMARY_MD_PATH = OUT_DIR / "wfa_mc_rolling_oos_summary.md"

# Mốc thời gian 3 Folds OOS (Epoch milliseconds UTC)
F1_START_MS = int(datetime(2024, 12, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
F1_END_MS = int(datetime(2025, 6, 30, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)

F2_START_MS = int(datetime(2025, 7, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
F2_END_MS = int(datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)

F3_START_MS = int(datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
F3_END_MS = int(datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)

INITIAL_CAPITAL = 10000.0


def file_sha256(p: Path) -> str:
    if p.exists():
        return hashlib.sha256(p.read_bytes()).hexdigest()
    return ""


def calculate_trade_metrics(trades: List[Dict[str, Any]], initial_equity: float = INITIAL_CAPITAL) -> Dict[str, Any]:
    """Tính các chỉ số kinh tế trên danh sách trade rows."""
    if not trades:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "net_pnl_usd": 0.0,
            "ret_pct": 0.0,
            "mdd_pct": 0.0,
            "fees_usd": 0.0,
            "trade_based_sharpe_proxy": 0.0,
            "sharpe": 0.0,
            "profit_factor": 0.0,
            "metrics_note": "Sharpe ở đây là trade PnL proxy ước lượng thô, chưa phải chuỗi lợi suất vốn theo ngày (time-weighted daily equity returns)."
        }

    pnls = [t.get("pnl", 0.0) for t in trades]
    fees = [t.get("fees_usd", t.get("fee", 0.0)) for t in trades]
    total_net_pnl = sum(pnls)
    total_fees = sum(fees)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else (999.0 if wins else 0.0)

    # Tính drawdown trên equity curve tích lũy
    eq = initial_equity
    peak = eq
    max_dd = 0.0
    for p in pnls:
        eq += p
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100.0 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    ret_pct = (total_net_pnl / initial_equity) * 100.0

    # Sharpe ước tính theo lệnh (annualized theo ~21 tháng OOS)
    if len(pnls) > 1 and np.std(pnls) > 0:
        trades_per_year = len(pnls) / (630.0 / 365.25)
        mean_pnl = np.mean(pnls)
        std_pnl = np.std(pnls, ddof=1)
        sharpe_proxy = float((mean_pnl / std_pnl) * math.sqrt(trades_per_year))
    else:
        sharpe_proxy = 0.0

    return {
        "trades": len(trades),
        "win_rate": round(win_rate, 2),
        "net_pnl_usd": round(total_net_pnl, 2),
        "ret_pct": round(ret_pct, 2),
        "mdd_pct": round(max_dd, 2),
        "fees_usd": round(total_fees, 2),
        "trade_based_sharpe_proxy": round(sharpe_proxy, 2),
        "sharpe": round(sharpe_proxy, 2),
        "profit_factor": round(profit_factor, 2),
        "metrics_note": "Sharpe ở đây là trade PnL proxy ước lượng thô, chưa phải chuỗi lợi suất vốn theo ngày (time-weighted daily equity returns)."
    }


def run_stationary_block_bootstrap_mc(
    pnls: List[float],
    block_length: int = 5,
    n_sims: int = 1000,
    seed: int = 42,
    initial_capital: float = INITIAL_CAPITAL
) -> Dict[str, Any]:
    """Mô phỏng Monte Carlo theo phương pháp Stationary Block Bootstrap trên PnL danh nghĩa cố định."""
    if not pnls or len(pnls) < 2:
        return {
            "simulations": n_sims,
            "block_length": block_length,
            "seed": seed,
            "prob_profit_pct": 0.0,
            "prob_ruin_mdd_15_pct": 0.0,
            "prob_ruin_mdd_20_pct": 0.0,
            "median_ret_pct": 0.0,
            "ci_95_lower_pct": 0.0,
            "ci_95_upper_pct": 0.0,
            "status": "INSUFFICIENT_DATA",
            "methodology_note": "Stationary block bootstrap trên PnL USD danh nghĩa của lệnh với vốn ban đầu cố định; chưa mô hình hóa sizing theo equity động (% margin resizing) hay compounding.",
            "ruin_policy_caveat": "Xác suất ruin ở đây không đại diện cho kiểm định rủi ro thực tế theo chính sách Master Risk."
        }

    n_trades = len(pnls)
    p_exit = 1.0 / block_length
    pnl_arr = np.array(pnls, dtype=np.float64)

    rng = np.random.default_rng(seed)

    final_returns = []
    max_dds = []

    for _ in range(n_sims):
        sim_pnls = []
        cur_idx = rng.integers(0, n_trades)
        for _ in range(n_trades):
            sim_pnls.append(pnl_arr[cur_idx])
            if rng.random() < p_exit:
                cur_idx = rng.integers(0, n_trades)
            else:
                cur_idx = (cur_idx + 1) % n_trades

        eq = initial_capital
        peak = eq
        path_mdd = 0.0
        for p in sim_pnls:
            eq += p
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100.0 if peak > 0 else 0.0
            if dd > path_mdd:
                path_mdd = dd

        final_returns.append((eq - initial_capital) / initial_capital * 100.0)
        max_dds.append(path_mdd)

    final_returns = np.array(final_returns)
    max_dds = np.array(max_dds)

    prob_profit = float(np.mean(final_returns > 0.0) * 100.0)
    prob_ruin_15 = float(np.mean(max_dds > 15.0) * 100.0)
    prob_ruin_20 = float(np.mean(max_dds > 20.0) * 100.0)
    median_ret = float(np.median(final_returns))
    ci_lower = float(np.percentile(final_returns, 2.5))
    ci_upper = float(np.percentile(final_returns, 97.5))

    return {
        "simulations": n_sims,
        "block_length": block_length,
        "seed": seed,
        "prob_profit_pct": round(prob_profit, 2),
        "prob_ruin_mdd_15_pct": round(prob_ruin_15, 2),
        "prob_ruin_mdd_20_pct": round(prob_ruin_20, 2),
        "median_ret_pct": round(median_ret, 2),
        "ci_95_lower_pct": round(ci_lower, 2),
        "ci_95_upper_pct": round(ci_upper, 2),
        "status": "COMPLETED",
        "methodology_note": "Stationary block bootstrap trên PnL USD danh nghĩa của lệnh với vốn ban đầu cố định; chưa mô hình hóa sizing theo equity động (% margin resizing) hay compounding.",
        "ruin_policy_caveat": "Xác suất ruin ở đây không đại diện cho kiểm định rủi ro thực tế theo chính sách Master Risk."
    }


def compute_dsr_exploratory(sharpe: float, n_trades: int, n_trials: int, skew: float = 0.0, kurt: float = 3.0) -> float:
    """Tính Deflated Sharpe Ratio thăm dò (Bailey & López de Prado)."""
    if n_trades <= 2 or n_trials <= 0:
        return 0.0

    em_c = 0.5772156649
    ln_n = math.log(n_trials)
    sr_0 = math.sqrt(2 * ln_n) * (1 - em_c / (2 * ln_n)) if ln_n > 0 else 0.0

    var_sr = 1.0 - skew * sharpe + ((kurt - 1.0) / 4.0) * (sharpe ** 2)
    if var_sr <= 0:
        var_sr = 1.0

    t_stat = (sharpe - sr_0) * math.sqrt(n_trades - 1) / math.sqrt(var_sr)
    dsr = 0.5 * (1.0 + math.erf(t_stat / math.sqrt(2.0)))
    return round(float(dsr), 4)


def main():
    if not COHORT_PATH.exists():
        print(f"❌ Không tìm thấy {COHORT_PATH}")
        return

    cohort_payload = json.loads(COHORT_PATH.read_text(encoding="utf-8"))
    records = cohort_payload["records"]

    eval_results = []

    print(f"Bắt đầu chạy Dry-Run Rolling OOS & Monte Carlo (Non-Decision Diagnostics) cho {len(records)} đối tượng...", flush=True)

    for idx, rec in enumerate(records, 1):
        aid = rec["id"]
        cat = rec["category"]
        source_class = rec["source_classification"]
        wfa_method = rec["wfa_method_assigned"]
        ledger_file = OUT_DIR / rec["raw_ledger_file"]

        print(f"[{idx:02d}/25] Xử lý chẩn đoán `{aid}` ({source_class})...", flush=True)

        if not ledger_file.exists():
            print(f"  ❌ Không tìm thấy ledger {ledger_file}")
            continue

        raw_trades = json.loads(ledger_file.read_text(encoding="utf-8"))

        # Phân chia trades theo 3 Folds OOS dựa trên enter_time
        t_f1 = [t for t in raw_trades if F1_START_MS <= t.get("enter_time", 0) <= F1_END_MS]
        t_f2 = [t for t in raw_trades if F2_START_MS <= t.get("enter_time", 0) <= F2_END_MS]
        t_f3 = [t for t in raw_trades if F3_START_MS <= t.get("enter_time", 0) <= F3_END_MS]
        t_agg_oos = t_f1 + t_f2 + t_f3

        m_f1 = calculate_trade_metrics(t_f1)
        m_f2 = calculate_trade_metrics(t_f2)
        m_f3 = calculate_trade_metrics(t_f3)
        m_agg = calculate_trade_metrics(t_agg_oos)

        folds_positive = sum(1 for m in [m_f1, m_f2, m_f3] if m["net_pnl_usd"] > 0)

        # Chạy Monte Carlo trên tập Aggregated OOS
        pnls_agg = [t.get("pnl", 0.0) for t in t_agg_oos]
        mc_base = run_stationary_block_bootstrap_mc(pnls_agg, block_length=5, n_sims=1000, seed=42)
        mc_sens_3 = run_stationary_block_bootstrap_mc(pnls_agg, block_length=3, n_sims=1000, seed=42)
        mc_sens_10 = run_stationary_block_bootstrap_mc(pnls_agg, block_length=10, n_sims=1000, seed=42)

        # DSR thăm dò: Toàn bộ status là DSR_UNAVAILABLE_TRIALS_UNAUDITED; không xuất giá trị số
        # để tránh gây hiểu nhầm rằng DSR đã được tính toán hoặc dùng để phán quyết.
        dsr_record = {
            "dsr_status": "DSR_UNAVAILABLE_TRIALS_UNAUDITED",
            "dsr_value": None,
            "note": (
                "Số lượng thử nghiệm lịch sử thực tế (N_trials) chưa được kiểm kê; 72 biến thể trong universe manifest "
                "đang ở trạng thái BLOCKED_NOT_EVALUATED. Tuyệt đối không xuất giá trị số và không dùng DSR để phán quyết "
                "loại bỏ alpha (kể cả dca_short)."
            )
        }

        # Phân loại trạng thái KỸ THUẬT PHI PHÁN QUYẾT (Non-decision diagnostics)
        if source_class == "PORTFOLIO_COMBO":
            disposition = "PORTFOLIO_COMBO_EVALUATED_SEPARATELY"
            disp_reason = "Đánh giá cấp danh mục độc lập; cấm xếp hạng cùng các alpha đơn lẻ."
        elif source_class == "EXCLUDED_STRUCTURAL_NO_SIGNAL_LOGIC":
            disposition = "NOT_APPLICABLE"
            disp_reason = "Mã nguồn học viên chỉ có lệnh Mua ở đầu chu kỳ (Buy & Hold 1 lệnh), không có logic tín hiệu/thoát."
        elif wfa_method == "RESEARCH_ONLY_NO_DECISION":
            disposition = "RESEARCH_PROXY_NO_DECISION"
            disp_reason = "Top Agent chỉ có tham số thoát lệnh từ OKX, điều kiện vào lệnh là proxy nghiên cứu; chỉ mang tính khảo sát kỹ thuật."
        elif len(t_agg_oos) < 30:
            disposition = "INSUFFICIENT_SAMPLE"
            disp_reason = f"Tổng số lệnh OOS gộp ({len(t_agg_oos)}) < 30 lệnh tối thiểu theo Phương án A đã chọn."
        else:
            # Alpha đủ mẫu nhưng tuyệt đối KHÔNG gán nhãn KEEP/REJECT
            disposition = "DRY_RUN_DIAGNOSTIC_ONLY"
            disp_reason = "Chẩn đoán kỹ thuật hạ tầng (non-decision diagnostic); không áp dụng phán quyết KEEP/REJECT khi các readiness gates còn mở và fold chưa chạy độc lập."

        item_res = {
            "id": aid,
            "name": rec["name"],
            "venue": rec["venue"],
            "category": cat,
            "source_classification": source_class,
            "wfa_method_assigned": wfa_method,
            "total_smoke_trades": rec["in_sample_trades"],
            "total_agg_oos_trades": len(t_agg_oos),
            "provenance": {
                "raw_ledger_file": rec["raw_ledger_file"],
                "raw_ledger_sha256": rec["raw_ledger_sha256"],
                "code_sha256": rec["code_sha256"],
            },
            "folds_metrics": {
                "fold_slicing_caveat": "Cắt theo enter_time từ ledger toàn kỳ, chưa phải fold engine backtest độc lập.",
                "fold_1": {"period": "2024-12 -> 2025-06", **m_f1},
                "fold_2": {"period": "2025-07 -> 2026-01", **m_f2},
                "fold_3": {"period": "2026-02 -> 2026-09", **m_f3},
            },
            "aggregated_oos_metrics": {
                "trades": len(t_agg_oos),
                "folds_positive_count": folds_positive,
                "consistency": f"{folds_positive}/3 Folds Positive",
                **m_agg
            },
            "monte_carlo_block_bootstrap": {
                "base_block_5": mc_base,
                "sensitivity_block_3": mc_sens_3,
                "sensitivity_block_10": mc_sens_10,
            },
            "deflated_sharpe_ratio": dsr_record,
            "disposition": disposition,
            "disposition_reason": disp_reason,
        }
        eval_results.append(item_res)

    # Lưu JSON artifact đầy đủ kèm provenance
    payload = {
        "report_title": "DRY-RUN HẠ TẦNG KỸ THUẬT: ROLLING OOS & MONTE CARLO (NON-DECISION DIAGNOSTICS)",
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "dry_run_notice": (
            "KẾT QUẢ NÀY LÀ DRY-RUN HẠ TẦNG KỸ THUẬT, TUYỆT ĐỐI KHÔNG DÙNG RA QUYẾT ĐỊNH ALPHA THỰC TẾ. "
            "Toàn bộ chạy trên dữ liệu smoke-run hiện hữu. Bốn readiness gates (risk policy, leverage clamp, "
            "calibrated fees, funding rate) vẫn ở trạng thái BLOCKED."
        ),
        "methodology_caveats": {
            "fold_slicing_mode": "ledger_entry_timestamp_slicing",
            "cross_boundary_limitation": (
                "Folds được tạo bằng cách cắt sổ cái backtest toàn kỳ theo enter_time, chưa phải rerun engine riêng cho từng fold. "
                "Các lệnh mở cuối fold nhưng đóng ở fold sau được tính toàn bộ PnL vào fold mở lệnh; các lệnh mở trước OOS fold đóng trong fold bị bỏ qua."
            ),
            "data_independence_limitation": (
                "Các lát cắt OOS này là Pseudo-OOS vì dữ liệu 2024-2026 đã bị nhìn trước qua đợt master smoke run."
            ),
            "alpha_decision_ban": (
                "Cấm dùng các số liệu và nhãn dry-run này để lọc alpha, chẩn đoán nguyên nhân hoặc tiến hóa candidate."
            )
        },
        "provenance_hashes": {
            "cohort_freeze_file": "artifacts/backtest_results/wfa_mc_cohort_freeze.json",
            "cohort_freeze_sha256": file_sha256(COHORT_PATH),
            "protocol_file": "artifacts/backtest_results/wfa_mc_protocol_preregistration.md",
            "protocol_sha256": file_sha256(PROTOCOL_PATH),
            "master_manifest_file": "artifacts/backtest_results/input_manifest.json",
            "master_manifest_sha256": file_sha256(MANIFEST_PATH),
            "market_data": {
                "btc_manifest_file": "nora/coin/data/market/okx/catalog/_manifest/BTC.json",
                "btc_manifest_sha256": file_sha256(REPO_ROOT / "nora/coin/data/market/okx/catalog/_manifest/BTC.json"),
                "okx_instruments_file": "nora/coin/data/market/okx/instruments.json",
                "okx_instruments_sha256": file_sha256(REPO_ROOT / "nora/coin/data/market/okx/instruments.json"),
                "btc_catalog_digest": "cd026438b6a668b1",
            },
            "engine": {
                "coin_backtest_engine_file": "nora/coin/backend/core/backtest.py",
                "coin_backtest_engine_sha256": file_sha256(REPO_ROOT / "nora/coin/backend/core/backtest.py"),
                "coin_strategy_engine_file": "nora/coin/backend/core/strategy.py",
                "coin_strategy_engine_sha256": file_sha256(REPO_ROOT / "nora/coin/backend/core/strategy.py"),
                "coin_tasks_runner_file": "nora/coin/backend/jobs/tasks.py",
                "coin_tasks_runner_sha256": file_sha256(REPO_ROOT / "nora/coin/backend/jobs/tasks.py"),
                "edu_backtest_engine_file": "nora/edu/backend/core/backtest.py",
                "edu_backtest_engine_sha256": file_sha256(REPO_ROOT / "nora/edu/backend/core/backtest.py"),
            },
            "cost_model": {
                "coin_params_file": "nora/coin/backend/analys/param/params.py",
                "coin_params_sha256": file_sha256(REPO_ROOT / "nora/coin/backend/analys/param/params.py"),
                "cost_model_type": "preset_research_proxy (0.00160 round-trip)",
            },
        },
        "total_records": len(eval_results),
        "disposition_summary": {
            "DRY_RUN_DIAGNOSTIC_ONLY": sum(1 for r in eval_results if r["disposition"] == "DRY_RUN_DIAGNOSTIC_ONLY"),
            "INSUFFICIENT_SAMPLE": sum(1 for r in eval_results if r["disposition"] == "INSUFFICIENT_SAMPLE"),
            "NOT_APPLICABLE": sum(1 for r in eval_results if r["disposition"] == "NOT_APPLICABLE"),
            "RESEARCH_PROXY_NO_DECISION": sum(1 for r in eval_results if r["disposition"] == "RESEARCH_PROXY_NO_DECISION"),
            "PORTFOLIO_COMBO_EVALUATED_SEPARATELY": sum(1 for r in eval_results if r["disposition"] == "PORTFOLIO_COMBO_EVALUATED_SEPARATELY"),
        },
        "records": eval_results
    }
    RESULTS_JSON_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Đã lưu kết quả chi tiết: {RESULTS_JSON_PATH}")

    # Sinh Markdown Summary chuẩn forensic
    md_lines = []
    md_lines.append("# BÁO CÁO DRY-RUN HẠ TẦNG: ROLLING OOS & MONTE CARLO (NON-DECISION DIAGNOSTICS)")
    md_lines.append(f"\n*Ngày thực hiện: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | Mẫu số: 25 Đối Tượng Đóng Băng*")
    md_lines.append("\n> [!CAUTION]")
    md_lines.append("> **RANH GIỚI NGHIỆM THU: DRY-RUN HẠ TẦNG KỸ THUẬT — KHÔNG DÙNG RA QUYẾT ĐỊNH ALPHA**")
    md_lines.append("> - Báo cáo này kiểm tra thông tuyến thuật toán tính toán Rolling OOS, Block Bootstrap Monte Carlo và DSR.")
    md_lines.append("> - Folds hiện tại được cắt từ raw ledger toàn kỳ theo `enter_time`, chưa phải rerun engine riêng cho từng fold (cross-boundary trades chưa được hạch toán theo thời gian thực).")
    md_lines.append("> - Sharpe là Trade PnL proxy ước lượng thô; Monte Carlo resample PnL USD danh nghĩa trên vốn cố định, không mô hình hóa dynamic sizing/compounding.")
    md_lines.append("> - Tuyệt đối **KHÔNG CÓ PHÁN QUYẾT KEEP/REJECT**; cấm dùng kết quả này để loại bỏ, chẩn đoán hay tiến hóa alpha.")
    md_lines.append("> - Mọi gates chính thức (Master Risk runtime clamp, Calibrated costs, Historical funding) vẫn **BỊ KHÓA (BLOCKED)**; kết quả chính thức sẽ được chạy lại khi các gates được đóng.\n")

    md_lines.append("## 1. Bảng Tổng Hợp Chẩn Đoán Kỹ Thuật Từng Alpha (25 Đối Tượng)")
    md_lines.append("| STT | ID Alpha / Leg | Phân Loại Nguồn | Lệnh OOS Gộp | Folds Lãi | OOS Ret% | OOS MDD% | Sharpe Proxy (Trade) | DSR Status | P(Ruin>15%) | Trạng Thái Dry-Run |")
    md_lines.append("|---|---|---|---|---|---|---|---|---|---|---|")

    for idx, r in enumerate(eval_results, 1):
        m_agg = r["aggregated_oos_metrics"]
        mc = r["monte_carlo_block_bootstrap"]["base_block_5"]
        dsr_status = r["deflated_sharpe_ratio"]["dsr_status"]

        disp = r["disposition"]
        if disp == "DRY_RUN_DIAGNOSTIC_ONLY":
            disp_badge = "🟡 CHẨN ĐOÁN KỸ THUẬT (NON-DECISION)"
        elif disp == "INSUFFICIENT_SAMPLE":
            disp_badge = "⚪ INSUFFICIENT_SAMPLE"
        elif disp == "NOT_APPLICABLE":
            disp_badge = "⚫ NOT_APPLICABLE"
        elif disp == "RESEARCH_PROXY_NO_DECISION":
            disp_badge = "🔵 PROXY_NO_DECISION"
        else:
            disp_badge = "🟣 COMBO_SEPARATE"

        ruin_str = f"{mc['prob_ruin_mdd_15_pct']:.1f}%" if mc['status'] == 'COMPLETED' else "N/A"

        md_lines.append(
            f"| {idx:02d} | `{r['id']}` | {r['source_classification']} | {r['total_agg_oos_trades']} | {m_agg['consistency']} | {m_agg['ret_pct']:+.2f}% | {m_agg['mdd_pct']:.2f}% | {m_agg['trade_based_sharpe_proxy']:.2f} | {dsr_status} | {ruin_str} | {disp_badge} |"
        )

    md_lines.append("\n## 2. Thống Kê Phân Bổ Trạng Thái")
    s = payload["disposition_summary"]
    md_lines.append(f"- **🟡 DRY_RUN_DIAGNOSTIC_ONLY (Đủ mẫu để chẩn đoán, không phán quyết)**: {s['DRY_RUN_DIAGNOSTIC_ONLY']} alphas")
    md_lines.append(f"- **⚪ INSUFFICIENT_SAMPLE (< 30 lệnh OOS gộp)**: {s['INSUFFICIENT_SAMPLE']} alphas")
    md_lines.append(f"- **⚫ NOT_APPLICABLE (Buy & Hold 1 trade không có logic bán)**: {s['NOT_APPLICABLE']} bài tập EDU")
    md_lines.append(f"- **🔵 RESEARCH_PROXY_NO_DECISION (Top Agent chỉ có exit proxy)**: {s['RESEARCH_PROXY_NO_DECISION']} alphas")
    md_lines.append(f"- **🟣 PORTFOLIO_COMBO_EVALUATED_SEPARATELY (Rổ danh mục vốn chung)**: {s['PORTFOLIO_COMBO_EVALUATED_SEPARATELY']} combo")
    md_lines.append(f"- **TUYỆT ĐỐI KHÔNG GÁN NHÃN `KEEP` HOẶC `REJECT` TRONG ĐỢT DRY-RUN NÀY**.")

    md_lines.append("\n## 3. Các Giới Hạn Phương Pháp Luận Cần Giải Quyết")
    md_lines.append("1. **Lỗi cắt fold theo enter_time**: Các fold hiện tại được cắt từ raw ledger toàn kỳ theo enter_time, chưa phải rerun engine riêng cho từng fold. Các lệnh mở cuối fold nhưng đóng ở fold sau được tính toàn bộ PnL vào fold mở lệnh; các lệnh mở trước OOS fold đóng trong fold bị bỏ qua.")
    md_lines.append("2. **Chỉ số Sharpe**: Được tính trên PnL USD mỗi trade với annualization ước lượng, chưa phải chuỗi lợi suất vốn theo ngày (Daily Equity Returns).")
    md_lines.append("3. **Monte Carlo**: Resample PnL USD danh nghĩa trên vốn ban đầu cố định $10,000, chưa mô hình hóa sizing theo % equity động (khi drawdown thì margin giảm, khi lãi thì compounding).")
    md_lines.append("4. **DSR**: Số trial thực tế ($N_{\\text{trials}}$) chưa được kiểm kê; 72 biến thể universe đang ở trạng thái BLOCKED_NOT_EVALUATED. Toàn bộ giá trị số DSR (bao gồm số 0.0 thăm dò của `dca_short`) đã bị loại bỏ khỏi bảng chẩn đoán để ngăn chặn mọi ngộ nhận phán quyết.")
    md_lines.append("5. **Khảo sát độ nhạy Block Length**: Phân tích độ nhạy sơ bộ với $b \\in \\{3, 5, 10\\}$ cho thấy độ biến thiên của phân phối khi thay đổi độ dài khối; chưa đủ cơ sở để kết luận về tính chất tương quan chuỗi hay chế độ thị trường.")
    md_lines.append("6. **Kết luận**: **Chưa lọc alpha tệ, chưa chẩn đoán nguyên nhân và chưa tiến hóa dựa trên bảng dry-run này**.")

    SUMMARY_MD_PATH.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"✅ Đã lưu báo cáo tóm tắt Markdown: {SUMMARY_MD_PATH}")

if __name__ == "__main__":
    main()
