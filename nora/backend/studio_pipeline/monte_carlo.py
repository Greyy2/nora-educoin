"""Monte Carlo Simulation Engine cho Studio Pipeline.

Thực hiện:
- Vectorized Block Bootstrap Resampling trên tỷ lệ lợi nhuận lệnh (pnl_pct).
- Mô phỏng tăng trưởng vốn theo lãi kép thực tế (Compounded Equity: equity *= 1 + r).
- Đo lường phân phối xác suất Max Drawdown theo danh sách confidence_levels (Percentile 50th, 90th, 95th, 99th).
- Tính toán Xác suất Cháy / Thua lỗ nghiêm trọng (Risk of Ruin %).
- Xuất dữ liệu biểu đồ phân tán và quantile bands (Fan Chart: p5, p25, p50, p75, p95).
- Sử dụng Local Generator ngẫu nhiên `np.random.default_rng(seed)` an toàn đa luồng.
"""
import time
from typing import Any, Dict, List, Optional

import numpy as np

from .jobs import complete_mc_job, fail_mc_job
from .schemas import MonteCarloResultContract, MonteCarloRunRequest


def run_monte_carlo(
    trades: List[Dict[str, Any]],
    simulations: int = 1000,
    initial_capital: float = 10000.0,
    ruin_threshold_pct: float = 30.0,
    confidence_levels: Optional[List[float]] = None,
    block_size: int = 1,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Thực hiện mô phỏng Monte Carlo vector tốc độ cao trên mảng PnL (lãi kép)."""
    if confidence_levels is None:
        confidence_levels = [90.0, 95.0, 99.0]

    # RNG cục bộ không ảnh hưởng global state (an toàn đa luồng)
    rng = np.random.default_rng(seed)

    trades_count = len(trades)
    if trades_count < 30:
        raise ValueError(
            f"Số lượng lệnh ({trades_count}) < 30. "
            "Monte Carlo yêu cầu tối thiểu 30 lệnh để đảm bảo ý nghĩa thống kê."
        )

    # Đọc pnl_pct để tính lãi kép; nếu thiếu thì trích xuất từ pnl_usd / initial_capital, nếu không có thì raise
    pnl_pct_list = []
    for t in trades:
        if "pnl_pct" in t and t["pnl_pct"] is not None:
            pnl_pct_list.append(float(t["pnl_pct"]))
        elif "pnl_usd" in t and t["pnl_usd"] is not None and initial_capital > 0:
            pnl_pct_list.append(float(t["pnl_usd"]) / initial_capital * 100.0)
        elif "estimated_pnl_usd" in t and t["estimated_pnl_usd"] is not None and initial_capital > 0:
            pnl_pct_list.append(float(t["estimated_pnl_usd"]) / initial_capital * 100.0)
        else:
            raise ValueError(f"Trade thiếu trường pnl_pct hoặc pnl_usd: {t}")

    pnl_pct_array = np.array(pnl_pct_list, dtype=np.float64)

    # ─── Vectorized Bootstrap Resampling ────────────────────────────────────────
    if block_size <= 1:
        # Trade Bootstrap độc lập có hoàn lại
        sampled_pcts = rng.choice(pnl_pct_array, size=(simulations, trades_count), replace=True)
    else:
        # Vectorized Block Bootstrap để bảo tồn tương quan chuỗi lệnh
        num_blocks = int(np.ceil(trades_count / block_size))
        max_start = max(1, trades_count - block_size + 1)
        block_starts = rng.integers(0, max_start, size=(simulations, num_blocks))
        offsets = np.arange(block_size)
        indices = (block_starts[:, :, None] + offsets[None, None, :]).reshape(simulations, -1)[:, :trades_count]
        sampled_pcts = pnl_pct_array[indices]

    # ─── Compounded Equity Curves (Lãi kép) ───────────────────────────────────
    # r = pnl_pct / 100.0; multiplier = max(0.0, 1.0 + r)
    step_multipliers = np.maximum(0.0, 1.0 + (sampled_pcts / 100.0))
    cum_returns = np.cumprod(step_multipliers, axis=1)
    all_equities = np.hstack([
        np.full((simulations, 1), initial_capital, dtype=np.float64),
        initial_capital * cum_returns,
    ])

    # ─── Max Drawdown Calculation ──────────────────────────────────────────────
    running_max = np.maximum.accumulate(all_equities, axis=1)
    drawdowns = (running_max - all_equities) / np.maximum(running_max, 1e-9) * 100.0
    sim_max_drawdowns = np.max(drawdowns, axis=1)

    # ─── Risk of Ruin ──────────────────────────────────────────────────────────
    ruined_sims = np.sum(sim_max_drawdowns >= ruin_threshold_pct)
    risk_of_ruin_pct = round(float(ruined_sims / simulations * 100.0), 2)

    # ─── Percentile Metrics ────────────────────────────────────────────────────
    percentile_mdd = {
        "p50": round(float(np.percentile(sim_max_drawdowns, 50)), 2),
    }
    for cl in confidence_levels:
        key = f"p{int(cl)}"
        percentile_mdd[key] = round(float(np.percentile(sim_max_drawdowns, cl)), 2)
    percentile_mdd["worst"] = round(float(np.max(sim_max_drawdowns)), 2)

    terminal_equities = all_equities[:, -1]
    terminal_returns = (terminal_equities - initial_capital) / initial_capital * 100.0
    terminal_return_pct = {
        "p10": round(float(np.percentile(terminal_returns, 10)), 2),
        "p50": round(float(np.percentile(terminal_returns, 50)), 2),
        "p90": round(float(np.percentile(terminal_returns, 90)), 2),
        "worst": round(float(np.min(terminal_returns)), 2),
        "best": round(float(np.max(terminal_returns)), 2),
    }

    profitable_sims = np.sum(terminal_returns > 0)
    win_ratio_of_simulations = round(float(profitable_sims / simulations * 100.0), 1)

    # ─── Downsample Sample Paths for UI Fan Chart ──────────────────────────────
    num_paths_to_export = min(35, simulations)
    worst_idx = int(np.argmin(terminal_equities))
    best_idx = int(np.argmax(terminal_equities))
    median_idx = int(np.argsort(terminal_equities)[simulations // 2])

    chosen_indices = {worst_idx, best_idx, median_idx}
    rand_indices = rng.choice(simulations, size=num_paths_to_export, replace=False)
    for idx in rand_indices:
        chosen_indices.add(int(idx))
        if len(chosen_indices) >= num_paths_to_export:
            break

    total_steps = all_equities.shape[1]
    step_stride = max(1, total_steps // 60)
    sample_indices = list(range(0, total_steps, step_stride))
    if sample_indices[-1] != total_steps - 1:
        sample_indices.append(total_steps - 1)

    exported_paths = []
    for c_idx in chosen_indices:
        path = [round(float(all_equities[c_idx, s]), 2) for s in sample_indices]
        exported_paths.append(path)

    # Step-by-step quantile envelopes across sampled steps
    sampled_matrix = all_equities[:, sample_indices]
    quantile_curves = {
        "steps": len(sample_indices),
        "p5": [round(float(v), 2) for v in np.percentile(sampled_matrix, 5, axis=0)],
        "p25": [round(float(v), 2) for v in np.percentile(sampled_matrix, 25, axis=0)],
        "p50": [round(float(v), 2) for v in np.percentile(sampled_matrix, 50, axis=0)],
        "p75": [round(float(v), 2) for v in np.percentile(sampled_matrix, 75, axis=0)],
        "p95": [round(float(v), 2) for v in np.percentile(sampled_matrix, 95, axis=0)],
        "best": [round(float(v), 2) for v in np.max(sampled_matrix, axis=0)],
        "worst": [round(float(v), 2) for v in np.min(sampled_matrix, axis=0)],
    }

    return {
        "simulations": simulations,
        "trades_count": trades_count,
        "initial_capital": round(initial_capital, 2),
        "percentile_mdd": percentile_mdd,
        "risk_of_ruin_pct": risk_of_ruin_pct,
        "ruin_threshold_pct": ruin_threshold_pct,
        "terminal_return_pct": terminal_return_pct,
        "sample_paths": exported_paths,
        "quantile_curves": quantile_curves,
        "seed": seed,
        "summary": {
            "avg_mdd_pct": round(float(np.mean(sim_max_drawdowns)), 2),
            "median_profit_usd": round(float(np.median(terminal_equities - initial_capital)), 2),
            "win_ratio_of_simulations": win_ratio_of_simulations,
            "min_terminal_equity": round(float(np.min(terminal_equities)), 2),
            "max_terminal_equity": round(float(np.max(terminal_equities)), 2),
        },
    }


# Alias for backward compatibility
run_monte_carlo_simulation = run_monte_carlo


def execute_monte_carlo_pipeline(
    job_id: str,
    req: MonteCarloRunRequest,
    trades: List[Dict[str, Any]],
):
    """Tiến trình thực thi Monte Carlo chạy trên background worker thread."""
    try:
        # Fail-closed: gate defaults False when source_wfa_id is provided.
        # Only True when WFA job is found AND acceptance_gate_passed=True is
        # explicitly confirmed in the result JSON.
        # When source_wfa_id is absent (standalone MC), gate = True (no WFA to check).
        source_gate_passed = (not req.source_wfa_id)  # True only if no WFA dependency
        if req.source_wfa_id:
            from .jobs import get_wfa_job
            import json
            try:
                wfa_job = get_wfa_job(req.source_wfa_id)
                if wfa_job and wfa_job.get("result_json"):
                    res_dict = json.loads(wfa_job["result_json"])
                    source_gate_passed = bool(res_dict.get("acceptance_gate_passed", False))
                # else: job not found or no result -> gate stays False
            except Exception:
                source_gate_passed = False  # Parse failure -> fail-closed

        res = run_monte_carlo(
            trades=trades,
            simulations=req.simulations,
            initial_capital=req.initial_capital,
            ruin_threshold_pct=req.ruin_threshold_pct,
            confidence_levels=req.confidence_levels,
            block_size=req.block_size,
            seed=req.seed,
        )

        mc_contract = MonteCarloResultContract(
            mc_id=job_id,
            source_wfa_id=req.source_wfa_id,
            strategy_name=req.strategy_name or "Strategy",
            symbol=req.symbol or "",
            simulations=req.simulations,
            trades_count=res["trades_count"],
            initial_capital=res["initial_capital"],
            percentile_mdd=res["percentile_mdd"],
            risk_of_ruin_pct=res["risk_of_ruin_pct"],
            ruin_threshold_pct=res["ruin_threshold_pct"],
            terminal_return_pct=res["terminal_return_pct"],
            sample_paths=res["sample_paths"],
            quantile_curves=res["quantile_curves"],
            source_gate_passed=source_gate_passed,
            seed=req.seed,
            summary=res["summary"],
            generated_at=int(time.time() * 1000),
        )

        complete_mc_job(job_id, mc_contract.model_dump())

    except Exception as exc:
        import traceback
        traceback.print_exc()
        fail_mc_job(job_id, f"Ngoại lệ khi thực thi Monte Carlo: {str(exc)}")
