"""Monte Carlo Simulation Engine cho Studio Pipeline.

Thực hiện:
- Vectorized Block Bootstrap Resampling trên tỷ lệ lợi nhuận lệnh (pnl_pct) HOẶC (basis="daily", mặc định khi có WFA nguồn)
  trên lợi suất NGÀY mark-to-market của OOS — đường vốn ngày đã chứa lỗ treo nên MDD không bị đánh giá thấp.
- Mô phỏng tăng trưởng vốn theo lãi kép thực tế (Compounded Equity: equity *= 1 + r).
- Đo lường phân phối xác suất Max Drawdown theo danh sách confidence_levels (Percentile 50th, 90th, 95th, 99th).
- Tính toán Xác suất Cháy / Thua lỗ nghiêm trọng (Risk of Ruin %).
- Xuất dữ liệu biểu đồ phân tán và quantile bands (Fan Chart: p5, p25, p50, p75, p95).
- Sử dụng Local Generator ngẫu nhiên `np.random.default_rng(seed)` an toàn đa luồng.
"""
import json
import time
from typing import Any, Dict, List, Optional

import numpy as np

from .jobs import complete_mc_job, fail_mc_job
from .schemas import MonteCarloResultContract, MonteCarloRunRequest


def _resolve_wfa_gate(source_wfa_id: Optional[str]) -> Optional[bool]:
    """
    Xác định trạng thái gate của WFA nguồn.

    Returns:
        True  – WFA job đã completed với acceptance_gate_passed=True
        False – WFA job tồn tại nhưng gate False, chưa completed,
                không tìm thấy, hoặc có lỗi parse
        None  – Không có source_wfa_id (MC chạy standalone, không qua WFA)

    Luật đọc result (ưu tiên theo thứ tự):
        1. job["result"] (in-memory, luôn là dict nếu đã complete)
        2. json.loads(job["result_json"]) (từ SQLite sau restart)
    """
    if not source_wfa_id:
        return None

    from .jobs import get_wfa_job

    try:
        job = get_wfa_job(source_wfa_id)
    except Exception:
        return False

    if not job:
        return False

    # Job phải ở trạng thái completed
    if job.get("status") != "completed":
        return False

    # Đọc result: ưu tiên in-memory dict, fallback JSON string từ SQLite
    res = job.get("result")
    if res is None:
        raw_json = job.get("result_json")
        if raw_json:
            try:
                res = json.loads(raw_json)
            except Exception:
                return False

    if not res:
        return False

    return bool(res.get("acceptance_gate_passed") is True)


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

    # Đọc pnl_pct để tính lãi kép; nếu thiếu thì trích xuất từ pnl_usd / initial_capital
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


def run_monte_carlo_daily(
    daily_returns,
    simulations: int = 4000,
    block_days: int = 5,
    horizon_days: int = 365,
    ruin_threshold_pct: float = 30.0,
    seed: int = 1,
    scale: float = 1.0,
) -> Dict[str, Any]:
    """Block bootstrap trên LỢI SUẤT NGÀY mark-to-market (gồm cả lỗ chưa chốt), mô phỏng `horizon_days` ngày.

    Khác run_monte_carlo (lệnh đã đóng): đường vốn ngày đã chứa lỗ treo nên MDD không bị đánh giá thấp.
    `scale` nhân lợi suất ngày (hệ số rủi ro). Thứ tự gọi RNG GIỮ NGUYÊN bản bootstrap của build_strategy_book
    (mỗi lần mô phỏng một lệnh rng.integers) -> cùng seed/scale cho đúng cùng số; đừng vector hoá khi chưa so lại bit.
    """
    d = np.asarray(daily_returns, dtype=float)
    if len(d) == 0:
        raise ValueError("Cần ít nhất một lợi suất ngày để chạy Monte Carlo")
    rng = np.random.default_rng(seed)
    n = int(simulations)
    mdds, rets = np.empty(n), np.empty(n)
    for k in range(n):
        idx = (rng.integers(0, len(d), horizon_days // block_days + 1)[:, None] + np.arange(block_days)).ravel()[:horizon_days] % len(d)
        eq = np.cumprod(1 + scale * d[idx])
        peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
        mdds[k] = ((peak - eq) / peak).max()
        rets[k] = eq[-1] - 1
    return _daily_summary(mdds, rets, ruin_threshold_pct, n, block_days, horizon_days, seed)


def _daily_summary(mdds, rets, ruin_threshold_pct, n, block_days, horizon_days, seed) -> Dict[str, Any]:
    """Tóm tắt từ MDD/lãi cuối của n lần mô phỏng (dùng chung run_monte_carlo_daily và bản chi tiết -> cùng làm tròn)."""
    return {
        "median_ret_pct": round(float(np.median(rets) * 100), 1),
        "p05_ret_pct": round(float(np.percentile(rets, 5) * 100), 1),
        "mdd_p50_pct": round(float(np.percentile(mdds, 50) * 100), 1),
        "mdd_p95_pct": round(float(np.percentile(mdds, 95) * 100), 1),
        "p_mdd_ge_ruin_pct": round(float((mdds >= ruin_threshold_pct / 100).mean() * 100), 2),
        "simulations": n, "block_days": int(block_days), "horizon_days": int(horizon_days), "seed": seed,
    }


def _hist(values, bins: int = 20) -> Dict[str, Any]:
    """Histogram ~`bins` cột: [{lo, hi, count}] (đơn vị của `values`, làm tròn 2 số lẻ)."""
    v = np.asarray(values, dtype=float)
    lo, hi = float(v.min()), float(v.max())
    if hi - lo < 1e-9:
        hi = lo + 1e-6 if lo == 0 else lo + abs(lo) * 1e-6
    counts, edges = np.histogram(v, bins=bins, range=(lo, hi))
    return {"bins": [{"lo": round(float(edges[i]), 2), "hi": round(float(edges[i + 1]), 2), "count": int(counts[i])}
                     for i in range(len(counts))]}


FAN_STEP_DAYS = 5
FAN_QUANTILES = (5, 25, 50, 75, 95)


def run_monte_carlo_daily_detail(
    daily_returns,
    simulations: int = 4000,
    block_days: int = 5,
    horizon_days: int = 365,
    ruin_threshold_pct: float = 30.0,
    seed: int = 1,
    scale: float = 1.0,
    max_ruin_pct: float = 5.0,
) -> Dict[str, Any]:
    """Như run_monte_carlo_daily (CÙNG RNG, CÙNG thứ tự gọi -> `summary` trùng từng bit) nhưng thêm dữ liệu vẽ:
    fan = phân vị 5/25/50/75/95 của đường vốn (% lãi từ đầu) lấy mẫu mỗi FAN_STEP_DAYS ngày, histogram MDD và lãi cuối (%), gate ruin."""
    d = np.asarray(daily_returns, dtype=float)
    if len(d) == 0:
        raise ValueError("Cần ít nhất một lợi suất ngày để chạy Monte Carlo")
    rng = np.random.default_rng(seed)
    n = int(simulations)
    days = sorted({0, *range(FAN_STEP_DAYS, int(horizon_days) + 1, FAN_STEP_DAYS), int(horizon_days)})
    cols = np.asarray([k - 1 for k in days if k > 0], dtype=int)      # đường vốn sau k ngày = eq[k-1]
    mdds, rets = np.empty(n), np.empty(n)
    fan_vals = np.empty((n, len(cols)))
    for k in range(n):
        idx = (rng.integers(0, len(d), horizon_days // block_days + 1)[:, None] + np.arange(block_days)).ravel()[:horizon_days] % len(d)
        eq = np.cumprod(1 + scale * d[idx])
        peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
        mdds[k] = ((peak - eq) / peak).max()
        rets[k] = eq[-1] - 1
        fan_vals[k] = eq[cols] - 1
    summary = _daily_summary(mdds, rets, ruin_threshold_pct, n, block_days, horizon_days, seed)
    q = np.percentile(fan_vals * 100, FAN_QUANTILES, axis=0)
    fan: Dict[str, Any] = {"days": days}
    for name, row in zip(("p5", "p25", "p50", "p75", "p95"), q):
        fan[name] = [0.0] + [round(float(x), 2) for x in row]
    return {
        "summary": summary, "fan": fan,
        "mdd_hist": _hist(mdds * 100), "ret_hist": _hist(rets * 100),
        "gate": {"ruin_max_pct": float(max_ruin_pct), "passed": bool(summary["p_mdd_ge_ruin_pct"] <= max_ruin_pct)},
        "params": {"simulations": n, "block_days": int(block_days), "horizon_days": int(horizon_days),
                   "ruin_threshold_pct": float(ruin_threshold_pct), "seed": seed, "scale": float(scale), "n_days": int(len(d))},
    }


# Alias for backward compatibility
run_monte_carlo_simulation = run_monte_carlo


def execute_monte_carlo_pipeline(
    job_id: str,
    req: MonteCarloRunRequest,
    trades: List[Dict[str, Any]],
):
    """
    Tiến trình thực thi Monte Carlo chạy trên background worker thread.

    Ưu tiên nguồn lệnh: source_wfa_id > trades truyền vào.
    Nếu có source_wfa_id, LUÔN dùng aggregate_oos_trades từ WFA job.
    Client không được bypass gate bằng cách tự gửi trades giả.
    """
    try:
        # ── Resolve gate (3 giá trị: True / False / None) ────────────────────
        source_gate_passed = _resolve_wfa_gate(req.source_wfa_id)

        # ── Lấy trades từ WFA job nếu có source_wfa_id ───────────────────────
        # Ưu tiên: source_wfa_id > trades truyền vào (không cho phép bypass)
        effective_trades = trades
        basis = "trades"
        basis_note = None
        if req.source_wfa_id:
            # Có source_wfa_id thì CHỈ dùng dữ liệu OOS của job; không fallback về trades của client.
            # Job thiếu lệnh -> danh sách rỗng -> run_monte_carlo raise (< 30 lệnh) -> job failed.
            from .jobs import get_wfa_job
            wfa_job = get_wfa_job(req.source_wfa_id)
            res = None
            if wfa_job:
                res = wfa_job.get("result")
                if res is None and wfa_job.get("result_json"):
                    try:
                        res = json.loads(wfa_job["result_json"])
                    except Exception:
                        res = None
            res = res or {}
            effective_trades = list(res.get("aggregate_oos_trades") or [])
            if req.basis == "daily":
                daily = list(res.get("aggregate_oos_daily_returns") or [])
                if len(daily) >= 30:
                    # Lợi suất ngày -> "lệnh giả" pnl_pct để dùng chung bộ mô phỏng vector (horizon = độ dài lịch sử OOS)
                    effective_trades = [{"pnl_pct": float(r) * 100.0} for r in daily]
                    basis = "daily"
                else:
                    basis_note = (f"WFA nguồn chỉ có {len(daily)} lợi suất ngày (< 30; job cũ thì không có) "
                                  "-> dùng lệnh đã đóng (basis=trades)")
        elif req.basis == "daily":
            basis_note = "basis=daily cần source_wfa_id; nguồn lệnh trực tiếp -> dùng lệnh đã đóng (basis=trades)"

        res = run_monte_carlo(
            trades=effective_trades,
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
            max_ruin_pct=req.max_ruin_pct,
            robust_passed=bool(source_gate_passed is True and res["risk_of_ruin_pct"] <= req.max_ruin_pct),
            robust_checks={
                "wfa_gate": {"required": True, "actual": source_gate_passed, "passed": source_gate_passed is True},
                "risk_of_ruin": {
                    "required": f"<= {req.max_ruin_pct}% (MDD >= {req.ruin_threshold_pct}%)",
                    "actual": res["risk_of_ruin_pct"],
                    "passed": res["risk_of_ruin_pct"] <= req.max_ruin_pct,
                },
            },
            seed=req.seed,
            summary={**res["summary"], **({"basis_note": basis_note} if basis_note else {})},
            basis=basis,
            generated_at=int(time.time() * 1000),
        )

        complete_mc_job(job_id, mc_contract.model_dump())

    except Exception as exc:
        import traceback
        traceback.print_exc()
        fail_mc_job(job_id, f"Ngoại lệ khi thực thi Monte Carlo: {str(exc)}")
