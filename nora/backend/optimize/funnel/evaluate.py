"""Phía WORKER của phễu: backtest danh mục một alpha, WFA cố định tham số, Monte Carlo, tìm/xác nhận hệ số s, holdout.

Mọi hàm `w_*` là hàm cấp module (pickle được qua ProcessPoolExecutor), nhận một dict `job` thuần dữ liệu và trả dict thuần dữ liệu.
Máy chạy là PortfolioEngine DÙNG LẠI (cùng đường với build_strategy_book giai đoạn A / validate_book): không có logic mô phỏng riêng ở đây.
Dữ liệu giá + kernel đọc qua mmap dùng chung (backend/core/data/shared.py) khi `shared_dir` có đặt; không thì tự dựng (cùng kết quả từng bit).
"""
import contextlib
import io
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from . import gates, sizing
from backend.core.metrics.portfolio import flat_extras, series_metrics
from backend.core.metrics.returns import daily_stats, sortino
from backend.core.metrics.trades import trade_rows, trade_stats
from backend.core.backtest.run import BacktestJob
from backend.core.backtest.run import make_engine as _make_engine

DAY = 86_400_000


# ── Engine ──────────────────────────────────────────────────────────────────
def risk_dict(kill: bool) -> Dict[str, Any]:
    """Giới hạn danh mục của sổ (RISK); kill=False = đánh giá tham số (kill switch tắt, như build_strategy_book giai đoạn A/IS)."""
    from backend.core.strategy.book import RISK
    return {**RISK, "kill_switch_dd_pct": RISK["kill_switch_dd_pct"] if kill else 0}


def to_job(job: Dict[str, Any]) -> BacktestJob:
    """Job phễu (dict: strategy, params, window, stop_fill, kill, rpt, symbols, shared_dir, base_frame) -> đặc tả chung BacktestJob."""
    return BacktestJob([(job["strategy"], job["params"])], (int(job["window"][0]), int(job["window"][1])), job["stop_fill"],
                       risk_dict(job["kill"]), job["rpt"], list(job["symbols"]), job.get("shared_dir"), job.get("base_frame", "1m"))


def make_engine(job: Dict[str, Any]):
    return _make_engine(to_job(job))


def _outputs(res: Dict[str, Any], start: int, want_trades: bool) -> Dict[str, Any]:
    """get_results() của một lần chạy -> {"metrics", "daily", "daily_start", "trades"} (số đo phẳng của phễu, không gồm chuỗi ngày)."""
    from backend.core.metrics.portfolio import portfolio_metrics
    pm = portfolio_metrics(res, start)
    daily = pm["daily"]
    first = next((c["time"] for c in res["equity_curve"] if c["time"] >= start), None)
    rows = trade_rows(res["positions"])
    ds = daily_stats(daily)
    m = {
        "ret_pct": pm["ret_pct"], "mdd_pct": pm["mdd_pct"], "sharpe": pm["sharpe"], "sortino": round(sortino(daily) or 0.0, 2),
        "trades": pm["trades"], "symbols_positive": pm["symbols_positive"], **trade_stats(rows),
        "sr_daily": round(ds["sr_daily"], 6), "skew": round(ds["skew"], 4), "kurt": round(ds["kurt"], 4), "n_days": ds["n_days"],
        "fees_usd": pm["fees_usd"], "funding_usd": pm["funding_usd"], "halted": bool(pm["halted_at"]),
        "by_symbol": pm["by_symbol"],
        "mdd_intrabar_pct": pm["mdd_intrabar_pct"], "mdd_daily_pct": pm["mdd_daily_pct"], "mdd_basis": "intrabar", **flat_extras(pm["stats"]),
    }
    return {"metrics": m, "daily": daily, "daily_start": f"{pd.Timestamp(int(first), unit='ms'):%Y-%m-%d}" if first is not None else None,
            "trades": rows if want_trades else None}


def run_backtest(job: Dict[str, Any], want_trades: bool = False) -> Dict[str, Any]:
    """Một lần PortfolioEngine -> {"metrics", "daily", "daily_start", "trades"}."""
    eng, start = make_engine(job)
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    return _outputs(eng.get_results(), start, want_trades)


def signal_key(job: Dict[str, Any]) -> str:
    """Khoá nhóm cho run_many: cùng chiến lược + cùng cây tín hiệu sau khi thay tham số + cùng đơn vị thoát / khung ATR + cùng cửa sổ/tài sản/
    kill/stop_fill -> dữ liệu và tín hiệu dùng chung; chỉ tham số vị thế/thoát lệnh khác nhau."""
    import json
    from backend.core.strategy import book as sb
    by_id = {c["id"]: c for c in sb.CANDIDATES}
    st = sb.materialize(by_id[job["strategy"]], job["params"], stop_fill=job["stop_fill"], risk_per_trade_pct=job["rpt"])
    pos = st["position"]
    return json.dumps([job["strategy"], st["tree"], st.get("stop"), pos.get("exit_unit"), pos.get("atr_frame"), pos.get("atr_period"),
                       job["window"], job["kill"], list(job["symbols"]), job.get("base_frame", "1m")], sort_keys=True, default=str)


def run_backtest_many(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Nhiều alpha CÙNG signal_key: nạp dữ liệu + tính tín hiệu một lần (engine của job đầu), chạy các bộ tham số vị thế bằng
    PortfolioEngine.run_many (trùng từng bit với chạy riêng — test_kernel_parity / test_funnel)."""
    from backend.core.strategy import book as sb
    by_id = {c["id"]: c for c in sb.CANDIDATES}
    eng, start = make_engine(jobs[0])
    with contextlib.redirect_stdout(io.StringIO()):
        eng.load_data()
        results = eng.run_many([sb.materialize(by_id[j["strategy"]], j["params"], stop_fill=j["stop_fill"], risk_per_trade_pct=j["rpt"])["position"]
                                for j in jobs])
    return [_outputs(r, start, bool(j.get("trades"))) for r, j in zip(results, jobs)]


def base_job(strategy: str, params: Dict[str, Any], window, stop_fill: str, kill: bool, rpt: float, symbols, shared_dir,
             base_frame: str = "1m") -> Dict[str, Any]:
    return {"strategy": strategy, "params": params, "window": [int(window[0]), int(window[1])], "stop_fill": stop_fill, "kill": kill,
            "rpt": rpt, "symbols": list(symbols), "shared_dir": shared_dir, "base_frame": base_frame}


# ── Monte Carlo (DÙNG LẠI backend/carlo/monte_carlo.py) ─────────────────────
def _mc_kwargs(scale: float) -> Dict[str, Any]:
    return dict(simulations=gates.S4_MIN_SIMULATIONS, block_days=gates.S4_BLOCK_DAYS, horizon_days=gates.S4_HORIZON_DAYS,
                ruin_threshold_pct=gates.S4_RUIN_THRESHOLD_PCT, seed=gates.S4_SEED, scale=scale,
                max_ruin_pct=gates.S4_MAX_RUIN_PCT, stress_max_mdd_pct=gates.S4_STRESS_MAX_MDD_PCT)


def _gate_of(simulations: int, ruin: float, stress) -> Dict[str, Any]:
    from backend.carlo.monte_carlo import evaluate_mc_gate
    return evaluate_mc_gate(simulations, ruin, stress, min_simulations=gates.S4_MIN_SIMULATIONS, max_ruin_pct=gates.S4_MAX_RUIN_PCT,
                            ruin_threshold_pct=gates.S4_RUIN_THRESHOLD_PCT, stress_max_mdd_pct=gates.S4_STRESS_MAX_MDD_PCT)


def mc_check(series, scale: float) -> Dict[str, Any]:
    """MC dạng gate (không điểm vẽ) trên chuỗi ngày × scale -> {"passed", "p_mdd_ge_30", "stress_max_mdd", "gate", "summary"}."""
    from backend.carlo.monte_carlo import run_monte_carlo_daily_gate
    r = run_monte_carlo_daily_gate(series, **_mc_kwargs(scale))
    gate = _gate_of(r["simulations"], r["p_mdd_ge_ruin_pct"], r["stress"])
    return {"passed": bool(gate["passed"]), "p_mdd_ge_30": r["p_mdd_ge_ruin_pct"],
            "stress_max_mdd": max((x["mdd_pct"] for x in r["stress"]), default=None), "gate": gate,
            "summary": {k: r[k] for k in ("median_ret_pct", "p05_ret_pct", "mdd_p50_pct", "mdd_p95_pct", "p_mdd_ge_ruin_pct", "simulations")}}


def mc_detail(series, scale: float, basis: str = "extreme") -> Dict[str, Any]:
    """MC chi tiết (quạt, histogram, kịch bản cực xấu có đường vẽ) + gate theo ngưỡng của phễu. Ghi vào mc/<alpha_id>.json."""
    from backend.carlo.monte_carlo import run_monte_carlo_daily_detail
    out = run_monte_carlo_daily_detail(series, **_mc_kwargs(scale))
    out["gate"] = _gate_of(out["summary"]["simulations"], out["summary"]["p_mdd_ge_ruin_pct"], out["stress"])
    out["params"] = {**out["params"], "basis": basis}
    return out


# ── WFA tham số cố định ─────────────────────────────────────────────────────
def fold_job_plan(folds: List[Dict[str, int]]) -> List[Dict[str, Any]]:
    from backend.optimize.funnel.gates import iso_date
    return [{"fold": i + 1, "train": [f["train_start_ts"], f["train_end_ts"]], "test": [f["test_start_ts"], f["test_end_ts"]],
             "train_iso": [iso_date(f["train_start_ts"]), iso_date(f["train_end_ts"])],
             "test_iso": [iso_date(f["test_start_ts"]), iso_date(f["test_end_ts"])]} for i, f in enumerate(folds)]


def run_wfa(strategy: str, params: Dict[str, Any], folds: List[Dict[str, Any]], symbols, rpt: float, shared_dir: Optional[str],
            base_frame: str = "1m") -> Dict[str, Any]:
    """Mỗi fold: IS = backtest cửa sổ train (SL level, kill tắt); OOS = backtest cửa sổ test (SL extreme = khớp bi quan, kill BẬT).
    Cùng quy ước validate_book với một cấu hình duy nhất (không chọn lại tham số). Cơ sở kết luận là OOS extreme."""
    out = []
    for f in folds:
        is_r = run_backtest(base_job(strategy, params, f["train"], "level", False, rpt, symbols, shared_dir, base_frame))
        oos = run_backtest(base_job(strategy, params, f["test"], "extreme", True, rpt, symbols, shared_dir, base_frame), want_trades=True)
        out.append({"fold": f["fold"], "train": f["train_iso"], "test": f["test_iso"], "is_ret_pct": is_r["metrics"]["ret_pct"],
                    "is_trades": is_r["metrics"]["trades"], "oos": oos["metrics"], "daily": oos["daily"],
                    "daily_start": oos["daily_start"] or f["test_iso"][0], "trades": oos["trades"]})
    return {"folds": out}


def aggregate_wfa(folds: List[Dict[str, Any]]) -> Dict[str, Any]:
    """-> {"summary" (cho evaluate_s3), "metrics" (stage_metrics S3), "series" (chuỗi ngày OOS nối), "trades" (có cột fold), "daily" (theo fold)}."""
    n = len(folds)
    series = [x for f in folds for x in f["daily"]]
    trades = [{**t, "fold": f["fold"]} for f in folds for t in (f["trades"] or [])]
    positive = sum(1 for f in folds if f["oos"]["ret_pct"] > 0)
    compounded = round(float((np.prod(1.0 + np.asarray(series, dtype=float)) - 1.0) * 100), 2) if series else 0.0
    is_avg = round(sum(f["is_ret_pct"] for f in folds) / n, 2) if n else None
    summary = {"folds": n, "positive_ratio": (positive / n) if n else 0.0, "compounded_oos_ret_pct": compounded,
               "worst_fold_mdd": max((f["oos"]["mdd_pct"] for f in folds), default=0.0), "is_ret_avg": is_avg}
    metrics = {**series_metrics(series, trades), "folds": n, "folds_profitable": positive, "positive_ratio": round(summary["positive_ratio"], 4),
               "worst_fold_mdd": summary["worst_fold_mdd"], "is_ret_avg": is_avg,
               "fold_detail": [{"fold": f["fold"], "train": f["train"], "test": f["test"], "is_ret_pct": f["is_ret_pct"],
                                "oos_ret_pct": f["oos"]["ret_pct"], "oos_mdd_pct": f["oos"]["mdd_pct"], "trades": f["oos"]["trades"],
                                "halted": f["oos"]["halted"]} for f in folds]}
    daily = [{"fold": f["fold"], "start": f["daily_start"], "rets": f["daily"]} for f in folds]
    return {"summary": summary, "metrics": metrics, "series": series, "trades": trades, "daily": daily}


# ── Hàm worker (một job = một alpha) ────────────────────────────────────────
def w_backtest(job: Dict[str, Any]) -> Dict[str, Any]:
    """S1 / điểm lân cận (S2) / tính lại lệnh: job gồm các khoá của base_job + "trades": False | True | "pass" (chỉ trả lệnh khi qua S1)."""
    try:
        out = run_backtest(job, want_trades=bool(job.get("trades")))
        if job.get("trades") == "pass" and not gates.evaluate_s1(out["metrics"])[0]:
            out["trades"] = None   # alpha bị loại ở S1: chỉ lưu thống kê (lệnh tính lại khi cần)
        return out
    except ValueError as exc:   # tham số không hợp lệ ngoài dự kiến (S0 đã lọc phần lớn) -> loại alpha này, không sập cả lượt
        return {"error": f"{type(exc).__name__}: {exc}"}


def w_backtest_group(group: Dict[str, Any]) -> List[Dict[str, Any]]:
    """S1 theo nhóm: group = {"jobs": [job w_backtest, ...]} cùng signal_key -> danh sách kết quả cùng thứ tự (như w_backtest từng job).
    Lỗi tham số ở một job -> chạy riêng từng job của nhóm để chỉ alpha lỗi bị loại."""
    jobs = group["jobs"]
    try:
        outs = run_backtest_many(jobs)
    except ValueError:
        return [w_backtest(j) for j in jobs]
    for j, out in zip(jobs, outs):
        if j.get("trades") == "pass" and not gates.evaluate_s1(out["metrics"])[0]:
            out["trades"] = None
    return outs


def w_backtest_group_rss(group: Dict[str, Any]) -> Dict[str, Any]:
    """w_backtest_group + RAM RIÊNG của worker sau nhóm (heap, không gồm trang mmap dùng chung) -> progress.worker_peak_rss_mb."""
    from backend.utils.memwatch import rss_anon_mb
    outs = w_backtest_group(group)
    return {"outs": outs, "rss_anon_mb": round(rss_anon_mb(), 1)}


def w_wfa(job: Dict[str, Any]) -> Dict[str, Any]:
    """S3: job = {strategy, params, folds (fold_job_plan), symbols, rpt, shared_dir}."""
    try:
        return run_wfa(job["strategy"], job["params"], job["folds"], job["symbols"], job["rpt"], job["shared_dir"], job.get("base_frame", "1m"))
    except ValueError as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def w_mc(job: Dict[str, Any]) -> Dict[str, Any]:
    """S4: job = {series}. Chi tiết ở s = 1 (ghi mc/<alpha>.json) + gate ở hệ số tối thiểu S5_S_MIN (alpha còn cứu được bằng giảm khối lượng không?)."""
    series = job["series"]
    if len(series) < gates.S4_MIN_DAYS:
        return {"days": len(series), "detail": None, "min_size": None}
    detail = mc_detail(series, 1.0)
    mn = mc_check(series, gates.S5_S_MIN)
    return {"days": len(series), "detail": detail, "min_size": {"s": gates.S5_S_MIN, **{k: mn[k] for k in ("passed", "p_mdd_ge_30", "stress_max_mdd", "gate")}}}


def w_sizing(job: Dict[str, Any]) -> Dict[str, Any]:
    """S5: tìm nhị phân s trên chuỗi ngày nhân s; xác nhận bằng S1 + WFA + MC thật ở s (hạ s từng bước nếu trượt).
    job = {strategy, params, series, windows {start, dev1_end}, folds, symbols, shared_dir}."""
    series = np.asarray(job["series"], dtype=float)
    s_star, steps = sizing.search_scale(lambda s: mc_check(series, s))
    if s_star is None:
        return {"s": None, "search": steps, "attempts": [], "reason": "scale_low"}
    keep: Dict[str, Any] = {}

    def confirm(s: float) -> Dict[str, Any]:
        rpt = sizing.risk_for_scale(s)
        r1 = run_backtest(base_job(job["strategy"], job["params"], (job["windows"]["start"], job["windows"]["dev1_end"]), "level", False, rpt,
                                   job["symbols"], job["shared_dir"], job.get("base_frame", "1m")))
        ok1 = gates.evaluate_s1(r1["metrics"])
        att: Dict[str, Any] = {"backtest": ok1[0], "backtest_ret_pct": r1["metrics"]["ret_pct"], "backtest_mdd_pct": r1["metrics"]["mdd_pct"],
                               "wfa": None, "mc": None, "passed": False}
        if not ok1[0]:
            att["reason"] = ok1[2]
            return att
        wfa = aggregate_wfa(run_wfa(job["strategy"], job["params"], job["folds"], job["symbols"], rpt, job["shared_dir"],
                                    job.get("base_frame", "1m"))["folds"])
        ok3 = gates.evaluate_s3(wfa["summary"])
        att["wfa"] = ok3[0]
        if not ok3[0]:
            att["reason"] = ok3[2]
            return att
        if len(wfa["series"]) < gates.S4_MIN_DAYS:
            att["mc"], att["reason"] = False, "quá ít ngày OOS"
            return att
        mcr = mc_check(wfa["series"], 1.0)
        att["mc"], att["p_mdd_ge_30"], att["stress_max_mdd"] = mcr["passed"], mcr["p_mdd_ge_30"], mcr["stress_max_mdd"]
        att["passed"] = bool(mcr["passed"])
        if not att["passed"]:
            att["reason"] = gates.evaluate_mc_checks(mcr["gate"], "S5")[2]
        else:
            keep.update(s=s, wfa=wfa, backtest=r1)
        return att

    s_ok, attempts = sizing.confirm_with_stepdown(s_star, confirm)
    out: Dict[str, Any] = {"s": s_ok, "s_search": s_star, "search": steps, "attempts": attempts}
    if s_ok is None:
        out["reason"] = "scale_low" if (attempts and attempts[-1]["s"] - gates.S5_CONFIRM_STEP < gates.S5_S_MIN - 1e-9) else "confirm"
        return out
    wfa = keep["wfa"]
    out.update({"wfa": wfa, "backtest": {"metrics": keep["backtest"]["metrics"]}, "mc_detail": mc_detail(wfa["series"], 1.0, basis="confirmed_wfa_at_s")})
    return out


def w_holdout(job: Dict[str, Any]) -> Dict[str, Any]:
    """S6: chạy MỘT lần ở hệ số s trên holdout: SL khớp đúng mức ("level") và giá xấu nhất ("extreme"), kill switch BẬT."""
    win = (job["windows"]["dev2_end"], job["windows"]["end"])
    out = {}
    for fill in ("level", "extreme"):
        out[fill] = run_backtest(base_job(job["strategy"], job["params"], win, fill, True, job["rpt"], job["symbols"], job["shared_dir"],
                                          job.get("base_frame", "1m")), want_trades=True)
    return out
