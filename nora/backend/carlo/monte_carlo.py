"""Monte Carlo: bootstrap theo khối + kịch bản cực xấu + gate (mọi cổng alpha/sổ đều đọc hằng số ở đây).

Thực hiện:
- Vectorized Block Bootstrap Resampling trên tỷ lệ lợi nhuận lệnh (pnl_pct) HOẶC (basis="daily", mặc định khi có WFA nguồn)
  trên lợi suất NGÀY mark-to-market của OOS — đường vốn ngày đã chứa lỗ treo nên MDD không bị đánh giá thấp.
- Mô phỏng tăng trưởng vốn theo lãi kép thực tế (Compounded Equity: equity *= 1 + r).
- Đo lường phân phối xác suất Max Drawdown theo danh sách confidence_levels (Percentile 50th, 90th, 95th, 99th).
- Tính toán Xác suất Cháy / Thua lỗ nghiêm trọng (Risk of Ruin %).
- Xuất dữ liệu biểu đồ phân tán và quantile bands (Fan Chart: p5, p25, p50, p75, p95).
- Sử dụng Local Generator ngẫu nhiên `np.random.default_rng(seed)` an toàn đa luồng.
"""
from typing import Any, Dict, List, Optional

import numpy as np


# ─── Hằng số GATE Monte Carlo (mọi cổng alpha/sổ đều đọc ở đây; KHÔNG nới để có kết quả đẹp) ───────────────
MC_MIN_SIMULATIONS = 10_000        # số kịch bản bootstrap TỐI THIỂU để một kết quả được dùng làm gate (ít hơn -> gate_eligible=False)
MC_MAX_SIMULATIONS = 50_000        # trần cho API Studio (RAM/thời gian)
MC_RUIN_THRESHOLD_PCT = 30.0       # "cháy" = MDD của một đường mô phỏng >= 30%
MC_MAX_RUIN_PCT = 5.0              # P(MDD >= 30%) tối đa 5%
STRESS_MAX_MDD_PCT = 50.0          # MDD của MỌI kịch bản cực xấu phải < 50% (cấu hình được: tham số stress_max_mdd_pct)
# Phí khứ hồi bổ sung cho kịch bản cost_x2 khi nguồn KHÔNG cho biết vòng quay vốn (sổ danh mục / API chỉ có chuỗi lợi suất ngày):
# (taker 0,05% + trượt giá 0,02% của CEX perp) x 2 chiều x vòng quay giả định 0,5 lần vốn mỗi ngày = 0,07% vốn/ngày hoạt động.
# Giả định 0,5x/ngày CAO hơn nhiều so với alpha thật (~0,1x) nên thiên về bảo thủ.
STRESS_COST_TAKER = 0.0005
STRESS_COST_SLIPPAGE = 0.0002
STRESS_COST_FALLBACK_TURNOVER = 0.5
STRESS_COST_FALLBACK_DAILY = (STRESS_COST_TAKER + STRESS_COST_SLIPPAGE) * 2 * STRESS_COST_FALLBACK_TURNOVER
CRASH_CAP = 0.95                   # ngày sập tối đa -95%
MC_CHUNK_ELEMS = 2_000_000         # xử lý theo lô: mỗi mảng (lô x bước) <= 16 MB float64 -> đỉnh RAM vài chục MB dù 50.000 mô phỏng
STRESS_PATH_POINTS = 72            # số điểm tối đa mỗi đường vẽ trả về cho UI

STRESS_LABELS_VI = {
    "worst_days_first": "Ngày lỗ tệ nhất đến trước",
    "reversed_order": "Đảo ngược thứ tự lịch sử",
    "crash_day": "Ngày sập (2x ngày xấu nhất) ở đầu",
    "cost_x2": "Chi phí giao dịch gấp đôi",
    "longest_losing_streak_x2": "Chuỗi thua dài nhất lặp 2 lần ở đầu",
    "worst_bootstrap": "Đường bootstrap tệ nhất (MDD lớn nhất)",
}


# ─── Kịch bản cực xấu (tất định, KHÔNG ngẫu nhiên) + gate ──────────────────────────────────────────────
def _sample_idx(total: int, points: int = STRESS_PATH_POINTS) -> List[int]:
    """Chỉ số bước (0 = vốn đầu) lấy mẫu để vẽ: đều nhau, luôn có bước đầu và cuối."""
    stride = max(1, int(np.ceil(total / points)))
    idx = list(range(0, total + 1, stride))
    if idx[-1] != total:
        idx.append(total)
    return idx


def _path_row(name: str, r, label_vi: Optional[str] = None, max_mdd_pct: float = STRESS_MAX_MDD_PCT,
              with_path: bool = True) -> Dict[str, Any]:
    """Đường vốn lãi kép từ chuỗi lợi suất ngày `r` (thập phân) -> các số đo của MỘT kịch bản.
    Hệ số ngày = max(0, 1 + r): chạm 0 thì vốn ở lại 0 (cháy). mdd_pct/terminal_ret_pct/worst_day_pct tính theo %."""
    r = np.asarray(r, dtype=float)
    eq = np.cumprod(np.maximum(0.0, 1.0 + r))
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    mdd = float(((peak - eq) / peak).max() * 100.0)
    ruin = bool(eq.min() <= 0.0)
    row: Dict[str, Any] = {
        "name": name, "label_vi": label_vi or STRESS_LABELS_VI.get(name, name),
        "mdd_pct": round(mdd, 2), "terminal_ret_pct": round(float(eq[-1] - 1.0) * 100.0, 2),
        "worst_day_pct": round(float(r.min()) * 100.0, 2), "days_underwater": int((eq < peak).sum()),
        "ruin": ruin, "days": int(len(r)), "passed": bool(mdd < max_mdd_pct and not ruin),
    }
    if with_path:
        full = np.r_[1.0, eq]
        idx = _sample_idx(len(r))
        row["path"] = {"days": idx, "ret_pct": [round(float(full[i] - 1.0) * 100.0, 2) for i in idx]}
    return row


def longest_losing_run(d) -> np.ndarray:
    """Đoạn ngày LỖ (< 0) liên tiếp dài nhất của chuỗi (gặp ngày >= 0 thì đứt); trùng độ dài thì lấy đoạn xuất hiện trước."""
    d = np.asarray(d, dtype=float)
    best_lo, best_len, lo = 0, 0, None
    for i, x in enumerate(d):
        if x < 0:
            lo = i if lo is None else lo
            if i - lo + 1 > best_len:
                best_lo, best_len = lo, i - lo + 1
        else:
            lo = None
    return d[best_lo:best_lo + best_len].copy()


def stress_scenarios(daily, scale: float = 1.0, extra_cost_daily: Optional[float] = None,
                     max_mdd_pct: float = STRESS_MAX_MDD_PCT, with_path: bool = True) -> List[Dict[str, Any]]:
    """5 kịch bản cực xấu TẤT ĐỊNH dựng từ chính chuỗi lợi suất ngày (`daily` x `scale`); mỗi cái cho một đường vốn.
    (kịch bản thứ 6, worst_bootstrap, lấy từ bootstrap nên do hàm chạy bootstrap thêm vào.)
      worst_days_first          chuỗi xếp TĂNG dần: mọi ngày lỗ trước, tệ nhất trước, rồi phần còn lại (cực xấu theo cấu trúc).
      reversed_order            chuỗi lịch sử đảo ngược.
      crash_day                 một ngày sập = 2 x ngày tệ nhất lịch sử (chặn -95%; không có ngày lỗ thì không sập) ở ĐẦU, rồi lịch sử.
      cost_x2                   mọi ngày có hoạt động (lợi suất != 0) trừ thêm `extra_cost_daily` (phí khứ hồi bổ sung = chi phí gấp đôi).
                                `extra_cost_daily` = (taker+trượt giá) x 2 x vòng quay vốn/ngày nếu nguồn biết; None -> STRESS_COST_FALLBACK_DAILY.
      longest_losing_streak_x2  chuỗi lỗ liên tiếp dài nhất lặp 2 lần liền nhau ở ĐẦU, rồi toàn bộ lịch sử (không có ngày lỗ thì giữ nguyên).
    Độ dài = số ngày lịch sử (cộng phần chèn thêm), KHÔNG cắt/kéo theo horizon của bootstrap."""
    d = scale * np.asarray(daily, dtype=float)
    if d.size == 0:
        raise ValueError("Cần ít nhất một lợi suất ngày để dựng kịch bản cực xấu")
    c = STRESS_COST_FALLBACK_DAILY if extra_cost_daily is None else float(extra_cost_daily)
    crash = max(-CRASH_CAP, 2.0 * float(d.min())) if d.min() < 0 else 0.0
    streak = longest_losing_run(d)
    seqs = {
        "worst_days_first": np.sort(d),
        "reversed_order": d[::-1],
        "crash_day": np.r_[crash, d],
        "cost_x2": np.where(d != 0.0, d - c, d),
        "longest_losing_streak_x2": np.r_[streak, streak, d],
    }
    rows = []
    for name, seq in seqs.items():
        row = _path_row(name, seq, max_mdd_pct=max_mdd_pct, with_path=with_path)
        if name == "cost_x2":
            row["note_vi"] = (f"Trừ thêm {c * 100:.3f}%/ngày hoạt động "
                              + ("(ước lượng từ vòng quay vốn của nguồn)" if extra_cost_daily is not None
                                 else "(hằng số bảo thủ: (taker 0,05% + trượt giá 0,02%) x 2 x vòng quay 0,5x/ngày)"))
        rows.append(row)
    return rows


def estimate_extra_daily_cost(n_trades: int, n_days: int, notional_fraction: float,
                              taker: float = STRESS_COST_TAKER, slippage: float = STRESS_COST_SLIPPAGE) -> float:
    """Phí/ngày bổ sung cho cost_x2 từ dữ liệu thật của alpha: (taker+trượt giá) x 2 x vòng quay vốn trung bình mỗi ngày,
    vòng quay/ngày = số lệnh x tỉ trọng vị thế (order_size x đòn bẩy, phần vốn) / số ngày."""
    if n_days <= 0:
        return STRESS_COST_FALLBACK_DAILY
    return (taker + slippage) * 2.0 * (n_trades * notional_fraction / n_days)


def evaluate_mc_gate(simulations: int, p_mdd_ge_ruin_pct: Optional[float], stress: Optional[List[Dict[str, Any]]], *,
                     min_simulations: int = MC_MIN_SIMULATIONS, max_ruin_pct: float = MC_MAX_RUIN_PCT,
                     ruin_threshold_pct: float = MC_RUIN_THRESHOLD_PCT, stress_max_mdd_pct: float = STRESS_MAX_MDD_PCT,
                     ) -> Dict[str, Any]:
    """Gate Monte Carlo (thuần): đạt khi CẢ 4 check qua. Mỗi check trả {label, required, actual, passed}.
      simulations   số kịch bản bootstrap >= min_simulations (không đủ -> gate_eligible=False, gate KHÔNG đạt)
      ruin          P(MDD >= ruin_threshold) <= max_ruin_pct
      stress_mdd    MDD của mọi kịch bản cực xấu (gồm worst_bootstrap) < stress_max_mdd_pct
      stress_ruin   không kịch bản cực xấu nào chạm vốn 0
    Thiếu stress / thiếu P(MDD) -> check tương ứng trượt."""
    def chk(label, required, actual, passed, detail=None):
        c = {"label": label, "required": required, "actual": actual, "passed": bool(passed)}
        if detail:
            c["detail"] = detail
        return c

    rows = list(stress or [])
    worst = max(rows, key=lambda x: x["mdd_pct"]) if rows else None
    ruined = [x["name"] for x in rows if x["ruin"]]
    over = [x["name"] for x in rows if x["mdd_pct"] >= stress_max_mdd_pct]
    eligible = int(simulations) >= int(min_simulations)
    checks = {
        "simulations": chk("Số kịch bản bootstrap", f">= {int(min_simulations)}", int(simulations), eligible),
        "ruin": chk(f"P(MDD >= {ruin_threshold_pct:.0f}%) trong bootstrap", f"<= {max_ruin_pct}%", p_mdd_ge_ruin_pct,
                    p_mdd_ge_ruin_pct is not None and p_mdd_ge_ruin_pct <= max_ruin_pct),
        "stress_mdd": chk("MDD tệ nhất trong các kịch bản cực xấu", f"< {stress_max_mdd_pct:g}%", worst["mdd_pct"] if worst else None,
                          bool(worst) and not over, f"{worst['name']}" if worst else "thiếu kịch bản cực xấu"),
        "stress_ruin": chk("Kịch bản cực xấu chạm vốn 0", "không có", len(ruined), bool(rows) and not ruined, ", ".join(ruined) or None),
    }
    return {"passed": all(c["passed"] for c in checks.values()), "gate_eligible": eligible, "checks": checks,
            "min_simulations": int(min_simulations), "ruin_max_pct": float(max_ruin_pct),
            "stress_max_mdd_pct": float(stress_max_mdd_pct)}


def strip_paths(rows: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    """Bỏ điểm vẽ khỏi bảng kịch bản (để lưu bằng chứng gọn)."""
    return [{k: v for k, v in r.items() if k != "path"} for r in rows] if rows is not None else None


# ─── Bootstrap theo lệnh/ngày (chia lô, tiết kiệm RAM) ──────────────────────────────────────────────────
def run_monte_carlo(
    trades: List[Dict[str, Any]],
    simulations: int = 1000,
    initial_capital: float = 10000.0,
    ruin_threshold_pct: float = 30.0,
    confidence_levels: Optional[List[float]] = None,
    block_size: int = 1,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Thực hiện mô phỏng Monte Carlo vector tốc độ cao trên mảng PnL (lãi kép).

    Xử lý theo LÔ (MC_CHUNK_ELEMS) để RAM không tỉ lệ với số mô phỏng; số RNG gọi/ thứ tự gọi giữ nguyên bản một-khối
    (cùng seed + cùng số mô phỏng -> cùng từng con số). Kết quả có thêm `worst_bootstrap` (đường có MDD lớn nhất)."""
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

    # ─── Kế hoạch bootstrap: chỉ số (nhỏ) rút MỘT lần; mỗi lô dựng lại phần pnl từ kế hoạch ───────────────
    if block_size <= 1:
        # Trade Bootstrap độc lập có hoàn lại (rng.choice(replace=True) = rng.integers rồi lấy phần tử)
        plan = rng.integers(0, trades_count, size=(simulations, trades_count))

        def gather(rows):
            return pnl_pct_array[plan[rows]]
    else:
        # Vectorized Block Bootstrap để bảo tồn tương quan chuỗi lệnh
        num_blocks = int(np.ceil(trades_count / block_size))
        max_start = max(1, trades_count - block_size + 1)
        plan = rng.integers(0, max_start, size=(simulations, num_blocks))
        offsets = np.arange(block_size)

        def gather(rows):
            starts = plan[rows]
            indices = (starts[:, :, None] + offsets[None, None, :]).reshape(starts.shape[0], -1)[:, :trades_count]
            return pnl_pct_array[indices]

    def equities(sampled_pcts):
        # ─── Compounded Equity Curves (Lãi kép): r = pnl_pct / 100.0; multiplier = max(0.0, 1.0 + r)
        step_multipliers = np.maximum(0.0, 1.0 + (sampled_pcts / 100.0))
        cum_returns = np.cumprod(step_multipliers, axis=1)
        return np.hstack([
            np.full((sampled_pcts.shape[0], 1), initial_capital, dtype=np.float64),
            initial_capital * cum_returns,
        ])

    total_steps = trades_count + 1
    step_stride = max(1, total_steps // 60)
    sample_indices = list(range(0, total_steps, step_stride))
    if sample_indices[-1] != total_steps - 1:
        sample_indices.append(total_steps - 1)

    sim_max_drawdowns = np.empty(simulations)
    terminal_equities = np.empty(simulations)
    sampled_matrix = np.empty((simulations, len(sample_indices)))
    chunk = max(1, MC_CHUNK_ELEMS // total_steps)
    for a in range(0, simulations, chunk):
        b = min(simulations, a + chunk)
        eq = equities(gather(slice(a, b)))
        # ─── Max Drawdown Calculation ───
        running_max = np.maximum.accumulate(eq, axis=1)
        drawdowns = (running_max - eq) / np.maximum(running_max, 1e-9) * 100.0
        sim_max_drawdowns[a:b] = np.max(drawdowns, axis=1)
        terminal_equities[a:b] = eq[:, -1]
        sampled_matrix[a:b] = eq[:, sample_indices]
        del eq, running_max, drawdowns

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

    exported_paths = []
    for c_idx in chosen_indices:
        row_eq = equities(gather(np.array([c_idx])))[0]
        exported_paths.append([round(float(row_eq[s]), 2) for s in sample_indices])

    # Step-by-step quantile envelopes across sampled steps
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

    # Đường bootstrap tệ nhất theo MDD (hoà -> đường đầu tiên): dựng lại từ kế hoạch, cùng công thức hệ số ngày
    worst_mdd_idx = int(np.argmax(sim_max_drawdowns))
    worst_bootstrap = _path_row("worst_bootstrap", gather(np.array([worst_mdd_idx]))[0] / 100.0)

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
        "worst_bootstrap": worst_bootstrap,
        "seed": seed,
        "summary": {
            "avg_mdd_pct": round(float(np.mean(sim_max_drawdowns)), 2),
            "median_profit_usd": round(float(np.median(terminal_equities - initial_capital)), 2),
            "win_ratio_of_simulations": win_ratio_of_simulations,
            "min_terminal_equity": round(float(np.min(terminal_equities)), 2),
            "max_terminal_equity": round(float(np.max(terminal_equities)), 2),
        },
    }


def _daily_bootstrap(d, n: int, block_days: int, horizon_days: int, seed, scale: float, cols=None):
    """Vòng bootstrap ngày dùng chung (giữ NGUYÊN thứ tự RNG: mỗi mô phỏng một lệnh rng.integers).
    -> (mdds, rets, fan_vals|None, chỉ số ngày của đường có MDD lớn nhất). `cols` = cột đường vốn cần lấy cho fan."""
    rng = np.random.default_rng(seed)
    mdds, rets = np.empty(n), np.empty(n)
    fan_vals = np.empty((n, len(cols))) if cols is not None else None
    worst_mdd, worst_idx = -1.0, None
    for k in range(n):
        idx = (rng.integers(0, len(d), horizon_days // block_days + 1)[:, None] + np.arange(block_days)).ravel()[:horizon_days] % len(d)
        eq = np.cumprod(1 + scale * d[idx])
        peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
        mdds[k] = ((peak - eq) / peak).max()
        rets[k] = eq[-1] - 1
        if mdds[k] > worst_mdd:
            worst_mdd, worst_idx = mdds[k], idx
        if fan_vals is not None:
            fan_vals[k] = eq[cols] - 1
    return mdds, rets, fan_vals, worst_idx


def run_monte_carlo_daily(
    daily_returns,
    simulations: int = MC_MIN_SIMULATIONS,
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
    Mặc định MC_MIN_SIMULATIONS (10.000): số nhỏ hơn chỉ để thử nhanh, không dùng làm gate."""
    d = np.asarray(daily_returns, dtype=float)
    if len(d) == 0:
        raise ValueError("Cần ít nhất một lợi suất ngày để chạy Monte Carlo")
    n = int(simulations)
    mdds, rets, _, _ = _daily_bootstrap(d, n, block_days, horizon_days, seed, scale)
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


def run_monte_carlo_daily_gate(
    daily_returns,
    simulations: int = MC_MIN_SIMULATIONS,
    block_days: int = 5,
    horizon_days: int = 365,
    ruin_threshold_pct: float = MC_RUIN_THRESHOLD_PCT,
    seed: int = 1,
    scale: float = 1.0,
    max_ruin_pct: float = MC_MAX_RUIN_PCT,
    stress_max_mdd_pct: float = STRESS_MAX_MDD_PCT,
    extra_cost_daily: Optional[float] = None,
) -> Dict[str, Any]:
    """MC ngày dạng GATE: `summary` (trùng bit run_monte_carlo_daily) + `stress` (5 kịch bản tất định + worst_bootstrap, không điểm vẽ)
    + `gate` (evaluate_mc_gate). Dùng cho gate WFA danh mục."""
    d = np.asarray(daily_returns, dtype=float)
    if len(d) == 0:
        raise ValueError("Cần ít nhất một lợi suất ngày để chạy Monte Carlo")
    n = int(simulations)
    mdds, rets, _, worst_idx = _daily_bootstrap(d, n, block_days, horizon_days, seed, scale)
    summary = _daily_summary(mdds, rets, ruin_threshold_pct, n, block_days, horizon_days, seed)
    stress = strip_paths(stress_scenarios(d, scale, extra_cost_daily, stress_max_mdd_pct)
                         + [_path_row("worst_bootstrap", scale * d[worst_idx], max_mdd_pct=stress_max_mdd_pct)])
    return {**summary, "stress": stress, "extra_cost_daily": extra_cost_daily,
            "gate": evaluate_mc_gate(n, summary["p_mdd_ge_ruin_pct"], stress, max_ruin_pct=max_ruin_pct,
                                     ruin_threshold_pct=ruin_threshold_pct, stress_max_mdd_pct=stress_max_mdd_pct)}


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
    simulations: int = MC_MIN_SIMULATIONS,
    block_days: int = 5,
    horizon_days: int = 365,
    ruin_threshold_pct: float = 30.0,
    seed: int = 1,
    scale: float = 1.0,
    max_ruin_pct: float = MC_MAX_RUIN_PCT,
    stress_max_mdd_pct: float = STRESS_MAX_MDD_PCT,
    extra_cost_daily: Optional[float] = None,
) -> Dict[str, Any]:
    """Như run_monte_carlo_daily (CÙNG RNG, CÙNG thứ tự gọi -> `summary` trùng từng bit) nhưng thêm dữ liệu vẽ:
    fan = phân vị 5/25/50/75/95 của đường vốn (% lãi từ đầu) lấy mẫu mỗi FAN_STEP_DAYS ngày, histogram MDD và lãi cuối (%),
    `stress` (6 kịch bản cực xấu, có `path` để vẽ), `worst_path` (= đường worst_bootstrap, mốc ngày theo fan) và `gate` (evaluate_mc_gate;
    `gate.gate_eligible` = False khi số mô phỏng < MC_MIN_SIMULATIONS)."""
    d = np.asarray(daily_returns, dtype=float)
    if len(d) == 0:
        raise ValueError("Cần ít nhất một lợi suất ngày để chạy Monte Carlo")
    n = int(simulations)
    days = sorted({0, *range(FAN_STEP_DAYS, int(horizon_days) + 1, FAN_STEP_DAYS), int(horizon_days)})
    cols = np.asarray([k - 1 for k in days if k > 0], dtype=int)      # đường vốn sau k ngày = eq[k-1]
    mdds, rets, fan_vals, worst_idx = _daily_bootstrap(d, n, block_days, horizon_days, seed, scale, cols)
    summary = _daily_summary(mdds, rets, ruin_threshold_pct, n, block_days, horizon_days, seed)
    q = np.percentile(fan_vals * 100, FAN_QUANTILES, axis=0)
    fan: Dict[str, Any] = {"days": days}
    for name, row in zip(("p5", "p25", "p50", "p75", "p95"), q):
        fan[name] = [0.0] + [round(float(x), 2) for x in row]
    worst = _path_row("worst_bootstrap", scale * d[worst_idx], max_mdd_pct=stress_max_mdd_pct)
    stress = stress_scenarios(d, scale, extra_cost_daily, stress_max_mdd_pct) + [worst]
    gate = evaluate_mc_gate(n, summary["p_mdd_ge_ruin_pct"], stress, max_ruin_pct=max_ruin_pct,
                            ruin_threshold_pct=ruin_threshold_pct, stress_max_mdd_pct=stress_max_mdd_pct)
    return {
        "summary": summary, "fan": fan,
        "mdd_hist": _hist(mdds * 100), "ret_hist": _hist(rets * 100),
        "stress": stress, "worst_path": worst["path"], "gate": gate,
        "params": {"simulations": n, "block_days": int(block_days), "horizon_days": int(horizon_days),
                   "ruin_threshold_pct": float(ruin_threshold_pct), "seed": seed, "scale": float(scale), "n_days": int(len(d)),
                   "extra_cost_daily": extra_cost_daily if extra_cost_daily is not None else STRESS_COST_FALLBACK_DAILY},
    }


# Alias for backward compatibility
run_monte_carlo_simulation = run_monte_carlo
