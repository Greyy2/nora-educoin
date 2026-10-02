"""Monte Carlo trên lợi suất NGÀY mark-to-market cho đường đơn tài sản (WFA -> MC -> cổng optimize_alphas).

1. daily_returns_from_curve = đúng chuỗi ngày mà portfolio_metrics từng tự tính (so với bản cũ, từng bit).
2. WFA đơn tài sản xuất aggregate_oos_daily_returns (chỉ fold TRADED, chỉ trong cửa sổ test).
3. MC chọn basis daily/trades; fallback có ghi chú; cùng seed -> cùng kết quả.
4. optimize_alphas.monte_carlo_gate: cổng ruin đọc MC ngày, giữ MC lệnh làm tham chiếu.
"""
import importlib.util
import os
import time

import numpy as np
import pandas as pd
import pytest

from backend.core.metrics.returns import daily_returns_from_curve
from backend.core.metrics.portfolio import portfolio_metrics
from backend.core.data.resampler import save_resampled_dataset
from test_round3_completion import FLOW_1M, T0, D, _rw_1m

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ── 1. Số đo dùng chung ─────────────────────────────────────────────────────
def _old_portfolio_daily(res, start_ts):
    """Bản gốc của portfolio_metrics (trước khi tách daily_returns_from_curve) — giữ nguyên để so từng bit."""
    curve = pd.DataFrame(res["equity_curve"])
    curve = curve[curve["time"] >= start_ts]
    eq = curve["equity"].to_numpy()
    worst = curve["equity_worst"].to_numpy()
    init = res["initial_capital"]
    peak = np.maximum.accumulate(np.r_[init, eq])[1:]
    mdd = float(np.max((peak - np.minimum(eq, worst)) / peak) * 100) if len(eq) else 0.0
    s = pd.Series(eq, index=pd.to_datetime(curve["time"], unit="ms"))
    daily = s.resample("1D").last().ffill()
    daily = pd.concat([pd.Series([init], index=[daily.index[0] - pd.Timedelta(days=1)]), daily]).pct_change().dropna()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(365)) if daily.std() > 0 else 0.0
    return daily, mdd, sharpe


def _synthetic_res(n_days=40, seed=11):
    rng = np.random.default_rng(seed)
    t = T0 + 3_600_000 * 5 + np.arange(n_days * 96, dtype=np.int64) * 900_000     # 15 phút/điểm, lệch ngày
    eq = 10_000 * np.cumprod(1 + rng.normal(0.0002, 0.004, len(t)))
    keep = np.ones(len(t), bool)
    keep[500:700] = False                                                         # khoảng trống -> ffill
    rows = [{"time": int(a), "equity": round(float(b), 4), "equity_worst": round(float(b) * 0.995, 4)}
            for a, b, k in zip(t, eq, keep) if k]
    return {"equity_curve": rows, "initial_capital": 10_000.0}


def test_daily_returns_from_curve_identical_to_old_portfolio_series():
    res = _synthetic_res()
    start = T0 + 3 * D + 7 * 3_600_000                                            # cắt giữa ngày (bỏ warmup)
    old_daily, old_mdd, old_sharpe = _old_portfolio_daily(res, start)
    new = daily_returns_from_curve(res["equity_curve"], start, res["initial_capital"])
    assert new == [float(x) for x in old_daily.to_numpy()]                        # bit-identical, chưa làm tròn
    full = dict(res, final_equity=10_500.0, positions=[], by_symbol={}, by_strategy={},
                rejected_for_risk=0, rejected_for_capital=0, halted_at=None)
    m = portfolio_metrics(full, start)
    assert m["daily"] == [round(float(x), 6) for x in old_daily.to_numpy()]
    assert m["sharpe"] == round(old_sharpe, 2) and m["mdd_pct"] == round(old_mdd, 2)


def test_daily_returns_from_curve_empty_and_before_start():
    assert daily_returns_from_curve([], 0, 1000.0) == []
    rows = [{"time": 1000, "equity": 1000.0, "equity_worst": 1000.0}]
    assert daily_returns_from_curve(rows, 10**13, 1000.0) == []


# ── 2. WFA đơn tài sản ──────────────────────────────────────────────────────
@pytest.fixture
def clean_asset(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    df = _rw_1m(40)
    save_resampled_dataset(symbol="CLEAN", output_dir=str(root), df_1m_raw=df, pool_address="0xclean", crawl_ok=True,
                           requested_start_ts=int(df.open_time.min()), requested_end_ts=int(df.open_time.max()))
    return "CLEAN"


def _wfa(sym):
    from backend.api.jobs.store import create_wfa_job, get_wfa_job
    from backend.core.contracts import StrategySnapshot, WfaFoldConfig
    from backend.wfa.walk_forward import execute_wfa_pipeline
    snap = StrategySnapshot(name="DailyMC", symbol=sym, flows=[FLOW_1M], start_ts=T0 + 6 * D, end_ts=T0 + 39 * D)
    job_id = create_wfa_job(sym, "DailyMC", 0)
    execute_wfa_pipeline(job_id, snap, WfaFoldConfig(train_days=10, test_days=5, min_folds=3), "h")
    job = get_wfa_job(job_id)
    assert job["status"] == "completed", job.get("error")
    return job_id, job["result"]


# ── 3. Chọn basis của Monte Carlo ───────────────────────────────────────────
def _wait_mc(job_id, timeout=30):
    from backend.api.jobs.store import get_mc_job
    end = time.time() + timeout
    while time.time() < end:
        job = get_mc_job(job_id)
        if job and job.get("status") in ("completed", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("MC job không kết thúc")


def _fake_wfa(daily, trades):
    from backend.api.jobs.store import complete_wfa_job, create_wfa_job
    job_id = create_wfa_job("CLEAN", "S", 4)
    res = {"acceptance_gate_passed": True, "aggregate_oos_trades": trades, "strategy_name": "S", "symbol": "CLEAN"}
    if daily is not None:
        res["aggregate_oos_daily_returns"] = daily
    complete_wfa_job(job_id, res)
    return job_id


def _run_mc(job_id, **kw):
    from backend.api.jobs.store import create_mc_job
    from backend.carlo.monte_carlo import execute_monte_carlo_pipeline
    from backend.core.contracts import MonteCarloRunRequest
    req = MonteCarloRunRequest(source_wfa_id=job_id, simulations=200, **kw)
    mid = create_mc_job("CLEAN", "S", 200, source_wfa_id=job_id)
    execute_monte_carlo_pipeline(mid, req, [])
    job = _wait_mc(mid)
    assert job["status"] == "completed", job.get("error")
    return job["result"]


# ── 4. Cổng MC của optimize_alphas ──────────────────────────────────────────
def _load_optimize():
    spec = importlib.util.spec_from_file_location("optimize_alphas_mod", os.path.join(NORA_ROOT, "backend", "optimize", "optimize_alphas.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


