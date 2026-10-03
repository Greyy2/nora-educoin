"""WFA danh mục + Monte Carlo ngày: số đo dùng chung, fold không chồng, không nhìn trước, tái lập, gate, validate_book.

Dữ liệu giả lập 3 tài sản perp 70 ngày (fixture `market` của test_strategy_book). Pool song song được thay bằng bản
chạy tuần tự trong tiến trình (seam `_pool_map`) để ghi lại job; test cuối chạy validate_book.main với pool thật.
"""
import json

import numpy as np
import pytest

from backend.wfa import walk_forward as pw
from backend.wfa.walk_forward import generate_folds
from test_strategy_book import T0, _load_script, _small_book, market  # noqa: F401  (market là fixture)

DAY = 86_400_000
RISK = {"max_positions": 3, "max_per_symbol": 1, "max_gross_exposure": 3.0, "kill_switch_dd_pct": 30.0}
CFG = pw.PortfolioWfaConfig(train_days=15, test_days=10, min_is_trades=1, mc_simulations=300)
START = T0 + 20 * DAY


def _cands():
    return [
        {"id": "t_long", "configs": [{"sig.lo": 35, "stop_loss_rate": 2.0, "take_profit_rate": 2.0, "timeout": 720},
                                      {"sig.lo": 40, "stop_loss_rate": 2.0, "take_profit_rate": 2.0, "timeout": 720}]},
        {"id": "t_short", "configs": [{"stop_loss_rate": 1.5, "trailing_stop": 2.0, "timeout": 720},
                                      {"stop_loss_rate": 2.5, "trailing_stop": 2.0, "timeout": 720}]},
    ]


def _serial(monkeypatch):
    """Thay pool bằng chạy tuần tự trong tiến trình và ghi lại (nhãn, job)."""
    log = []

    def fake(fn, jobs, workers, label):
        log.append((label, list(jobs)))
        return [fn(j) for j in jobs]
    monkeypatch.setattr(pw, "_pool_map", fake)
    return log


def _run(sb, tmp_path, tag, end_days=66, cands=None):
    return pw.run_portfolio_wfa(cands or _cands(), sb.perp_symbols(), START, T0 + end_days * DAY, CFG, RISK, 0.5, 1,
                                str(tmp_path / tag))


def _stable(res):
    return {k: v for k, v in res.items() if k != "mem"}


# ── Bước 1: số đo dùng chung ────────────────────────────────────────────────
def _old_bootstrap(daily, scale, n=4000, block=5, horizon=365, seed=1, mdd_limit=30.0):
    """Bản gốc trong backend/optimize/book.py trước khi chuyển (giữ nguyên để so từng bit)."""
    rng = np.random.default_rng(seed)
    d = np.asarray(daily, dtype=float)
    mdds, rets = np.empty(n), np.empty(n)
    for k in range(n):
        idx = (rng.integers(0, len(d), horizon // block + 1)[:, None] + np.arange(block)).ravel()[:horizon] % len(d)
        eq = np.cumprod(1 + scale * d[idx])
        peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
        mdds[k] = ((peak - eq) / peak).max()
        rets[k] = eq[-1] - 1
    return {"median_ret_pct": round(float(np.median(rets) * 100), 1), "p05_ret_pct": round(float(np.percentile(rets, 5) * 100), 1),
            "mdd_p95_pct": round(float(np.percentile(mdds, 95) * 100), 1),
            "p_mdd_ge_30_pct": round(float((mdds >= mdd_limit / 100).mean() * 100), 2)}


@pytest.mark.parametrize("scale", [0.25, 1.0, 3.0])
def test_bootstrap_daily_identical_to_old_implementation(scale):
    from backend.carlo.monte_carlo import bootstrap_daily
    from backend.carlo.monte_carlo import run_monte_carlo_daily
    daily = np.random.default_rng(3).normal(0.001, 0.02, 300)
    old = _old_bootstrap(daily, scale, n=500, seed=5)
    assert bootstrap_daily(daily, scale, n=500, seed=5) == old
    mc = run_monte_carlo_daily(daily, simulations=500, seed=5, scale=scale)
    assert {"median_ret_pct": mc["median_ret_pct"], "p05_ret_pct": mc["p05_ret_pct"], "mdd_p95_pct": mc["mdd_p95_pct"],
            "p_mdd_ge_30_pct": mc["p_mdd_ge_ruin_pct"]} == old
    assert mc["simulations"] == 500 and mc["block_days"] == 5 and mc["horizon_days"] == 365 and mc["seed"] == 5
    assert 0 <= mc["mdd_p50_pct"] <= mc["mdd_p95_pct"]


def test_script_aliases_still_point_to_shared_metrics():
    from backend.carlo.monte_carlo import bootstrap_daily
    from backend.core.metrics.portfolio import portfolio_metrics
    mod = _load_script("build_strategy_book")
    assert mod.metrics is portfolio_metrics and mod.bootstrap is bootstrap_daily


# ── Bước 2: fold, OOS, không nhìn trước, tái lập ────────────────────────────
def test_folds_do_not_overlap_and_oos_daily_only_from_test_windows(market, monkeypatch, tmp_path):
    sb = _small_book(monkeypatch)
    _serial(monkeypatch)
    seen = []  # (start_ts, thời điểm đầu/cuối của đường vốn, số ngày) cho từng lần tính số đo
    orig = pw.portfolio_metrics

    def spy(res, start_ts):
        m = orig(res, start_ts)
        times = [p["time"] for p in res["equity_curve"] if p["time"] >= start_ts]
        seen.append((start_ts, min(times), max(times), len(m["daily"])))
        return m
    monkeypatch.setattr(pw, "portfolio_metrics", spy)

    res = _run(sb, tmp_path, "a")
    folds = res["folds"]
    ref = generate_folds(START, T0 + 66 * DAY, CFG.train_days, CFG.test_days, CFG.step_days)
    assert len(folds) == len(ref) == 3
    assert folds[0]["test_ts"][0] == START + CFG.train_days * DAY          # test đầu = start + train
    for a, b in zip(folds, folds[1:]):
        assert a["test_ts"][1] <= b["test_ts"][0]                           # OOS không chồng
    for f in folds:
        assert f["train_ts"][1] <= f["test_ts"][0]
        for sf in ("level", "extreme"):
            daily = f[f"oos_daily_{sf}"]
            assert CFG.test_days <= len(daily) <= CFG.test_days + 1         # chỉ các ngày của cửa sổ test (ngày UTC lẻ đầu/cuối)
    oos = [s for s in seen if any(s[0] == f["test_ts"][0] for f in folds)]
    assert len(oos) == 2 * len(folds)
    for f in folds:
        for start, first, last, _ in (s for s in oos if s[0] == f["test_ts"][0]):
            assert f["test_ts"][0] <= first and last <= f["test_ts"][1]     # đường vốn tính số đo nằm trong cửa sổ test
    s = res["summary"]
    assert s["oos_days"] == len(s["oos_daily"]["extreme"]) == sum(len(f["oos_daily_extreme"]) for f in folds)
    assert s["mc"] is not None and s["mc"]["simulations"] == CFG.mc_simulations
    assert set(res["gate"]["checks"]) == {"folds", "avg_is_return", "active_folds", "fold_t", "ex_best_fold", "worst_fold_mdd", "compounded_oos",
                                          "mc_ruin", "mc_simulations", "mc_stress_mdd", "mc_stress_ruin"}
    assert res["gate"]["checks"]["mc_simulations"]["passed"] is False       # 300 < 10.000 kịch bản
    assert res["gate"]["checks"]["folds"]["passed"] is False                # 3 fold < 5 -> gate trượt


def test_is_selection_never_sees_oos_data(market, monkeypatch, tmp_path):
    sb = _small_book(monkeypatch)
    log = _serial(monkeypatch)
    res = _run(sb, tmp_path, "full")
    folds = generate_folds(START, T0 + 66 * DAY, CFG.train_days, CFG.test_days, CFG.step_days)
    is_jobs = next(jobs for label, jobs in log if "WFA-IS" in label)
    oos_jobs = next(jobs for label, jobs in log if "WFA-OOS" in label)
    assert len(is_jobs) == len(folds) * 4
    windows = {(f["train_start_ts"], f["train_end_ts"]): f for f in folds}
    for job in is_jobs:
        assert job[0] and len(job[0]) == 1 and job[2] == "level" and job[3]["kill_switch_dd_pct"] == 0
        fold = windows[job[1]]                                              # đúng cửa sổ train của một fold
        assert job[1][1] <= fold["test_start_ts"]                           # IS kết thúc trước đầu test
    test_windows = sorted(job[1] for job in oos_jobs)
    for a, b in zip(test_windows, test_windows[1:]):
        assert a[1] <= b[0] or a == b                                       # level/extreme cùng cửa sổ; khác cửa sổ thì không chồng
    assert all(job[3]["kill_switch_dd_pct"] == 30.0 for job in oos_jobs) and {j[2] for j in oos_jobs} == {"level", "extreme"}

    # Bỏ fold cuối (cắt dữ liệu tương lai): lựa chọn + kết quả của các fold còn lại KHÔNG đổi
    short = _run(sb, tmp_path, "short", end_days=56)
    assert len(short["folds"]) == 2
    for a, b in zip(short["folds"], res["folds"]):
        assert a == b


def test_wfa_is_deterministic(market, monkeypatch, tmp_path):
    sb = _small_book(monkeypatch)
    _serial(monkeypatch)
    one = _run(sb, tmp_path, "r1")
    two = _run(sb, tmp_path, "r2")
    assert json.dumps(_stable(one), sort_keys=True, default=str) == json.dumps(_stable(two), sort_keys=True, default=str)


def test_select_best_ties_go_to_first_and_min_trades():
    rows = [{"ret_pct": 5.0, "mdd_pct": 2.0, "trades": 20}, {"ret_pct": 5.0, "mdd_pct": 2.0, "trades": 30},
            {"ret_pct": 50.0, "mdd_pct": 1.0, "trades": 3}]
    assert pw.select_best(rows, 10) == 0           # hoà -> đứng trước; cấu hình ít lệnh bị loại dù điểm cao
    assert pw.select_best(rows, 100) is None
    assert pw.is_score({"ret_pct": 4.0, "mdd_pct": 0.2, "trades": 50}, 10) == 4.0   # mẫu số tối thiểu 1


# ── Gate ────────────────────────────────────────────────────────────────────
def _mc(**kw):
    """MC giả đạt gate: 10.000 kịch bản, P(MDD>=30%) 1,5%, mọi kịch bản cực xấu MDD 20% và không cháy."""
    row = {"name": "worst_days_first", "mdd_pct": 20.0, "ruin": False}
    mc = {"p_mdd_ge_ruin_pct": 1.5, "simulations": 10_000, "stress": [row, {**row, "name": "worst_bootstrap"}]}
    mc.update(kw)
    return mc


def _summary(**kw):
    s = {"n_folds": 6, "avg_is_ret_pct": 3.0, "positive_ratio_pct": 66.7, "fold_t": 1.5, "oos_ex_best_pct": 1.0, "n_active_folds": 6,
         "worst_fold_mdd_pct": {"level": 8.0, "extreme": 12.0},
         "compounded_oos_ret_pct": {"level": 10.0, "extreme": 6.0}, "mc": _mc()}
    s.update(kw)
    return s


def test_gate_checks_on_crafted_result():
    g = pw.evaluate_gate(_summary())
    assert g["passed"] and all(c["passed"] for c in g["checks"].values())
    assert g["checks"]["worst_fold_mdd"]["actual"] == 12.0 and g["checks"]["mc_ruin"]["required"] == "<= 5.0%"
    cases = {
        "folds": _summary(n_folds=4), "avg_is_return": _summary(avg_is_ret_pct=-0.1), "active_folds": _summary(n_active_folds=2),
        "fold_t": _summary(fold_t=0.99), "ex_best_fold": _summary(oos_ex_best_pct=-2.01),
        "worst_fold_mdd": _summary(worst_fold_mdd_pct={"level": 5.0, "extreme": 30.5}),
        "compounded_oos": _summary(compounded_oos_ret_pct={"level": 9.0, "extreme": -0.01}),
        "mc_ruin": _summary(mc=_mc(p_mdd_ge_ruin_pct=5.01)),
        "mc_simulations": _summary(mc=_mc(simulations=9_999)),
        "mc_stress_mdd": _summary(mc=_mc(stress=[{"name": "crash_day", "mdd_pct": 50.0, "ruin": False}])),
        "mc_stress_ruin": _summary(mc=_mc(stress=[{"name": "crash_day", "mdd_pct": 49.0, "ruin": True}])),
    }
    for name, summary in cases.items():
        res = pw.evaluate_gate(summary)
        assert not res["passed"] and [k for k, c in res["checks"].items() if not c["passed"]] == [name]
    assert pw.evaluate_gate(_summary(positive_ratio_pct=20.0))["passed"]     # tỉ lệ fold lãi không còn là cổng (lãi lệch phải)
    edge = pw.evaluate_gate(_summary(n_folds=5, avg_is_ret_pct=0.0, fold_t=1.0, oos_ex_best_pct=-2.0, n_active_folds=3,
                                     worst_fold_mdd_pct={"level": 1.0, "extreme": 30.0},
                                     compounded_oos_ret_pct={"level": 0.0, "extreme": 0.0}, mc=_mc(p_mdd_ge_ruin_pct=5.0, simulations=10_000)))
    assert edge["passed"]                                       # đúng ngưỡng thì qua
    miss = pw.evaluate_gate(_summary(mc=None))["checks"]
    assert not any(miss[k]["passed"] for k in ("mc_ruin", "mc_simulations", "mc_stress_mdd", "mc_stress_ruin"))   # thiếu MC -> trượt hết
    assert not pw.evaluate_gate(_summary(avg_is_ret_pct=None))["passed"]                # không có fold TRADED


def test_aggregate_folds_on_crafted_folds():
    def fold(i, ext_ret, ext_mdd, daily, cfg_pick, status="TRADED"):
        m = lambda r, d: {"ret_pct": r, "mdd_pct": d, "trades": 5, "halted_at": None}
        return {"fold": i, "status": status, "is_ret_pct": 2.0, "chosen_idx": {"s": cfg_pick if status == "TRADED" else None},
                "chosen": {"s": {"x": cfg_pick}}, "oos_level": m(ext_ret + 1, ext_mdd), "oos_extreme": m(ext_ret, ext_mdd),
                "oos_daily_level": daily, "oos_daily_extreme": daily, "trades": {"level": 5, "extreme": 5}}
    folds = [fold(1, 5.0, 4.0, [0.01] * 30, 0), fold(2, -2.0, 9.0, [-0.002] * 30, 0), fold(3, 3.0, 5.0, [0.001] * 30, 1)]
    folds.append(fold(4, 0.0, 0.0, [0.0] * 30, None, status="NO_TRADE") | {"oos_level": None, "oos_extreme": None})
    s = pw.aggregate_folds(folds, pw.PortfolioWfaConfig(mc_simulations=200))
    assert s["n_folds"] == 4 and s["n_traded_folds"] == 3 and s["positive_folds"] == 2 and s["positive_ratio_pct"] == 50.0
    x = [5.0, -2.0, 3.0]                                                    # fold NO_TRADE trung tính: không vào t-stat
    t = (sum(x) / 3) / ((sum((v - 2.0) ** 2 for v in x) / 2) ** 0.5 / 3 ** 0.5)
    assert s["n_active_folds"] == 3 and s["fold_t"] == round(t, 4) and s["oos_ex_best_pct"] == round((0.98 * 1.03 * 1.0 - 1) * 100, 4)
    assert s["worst_fold_mdd_pct"]["extreme"] == 9.0 and s["avg_is_ret_pct"] == 2.0
    expect = (1.01 ** 30) * (0.998 ** 30) * (1.001 ** 30) - 1
    assert s["compounded_oos_ret_pct"]["extreme"] == round(expect * 100, 2)
    assert s["param_stability"]["s"] == {"share": round(2 / 3, 4), "folds_chosen": 3, "distinct": 2}
    assert s["oos_days"] == 120 and s["mc"]["p_mdd_ge_ruin_pct"] >= 0


# ── Bước 3: validate_book ───────────────────────────────────────────────────
def test_candidates_from_report_picks_topk_of_accepted():
    vb = _load_script("validate_book")
    neg = float("-inf")
    stage_a = {"a": [{"params": {"k": 1}, "score": 1.0}, {"params": {"k": 2}, "score": 3.0}, {"params": {"k": 3}, "score": 2.0},
                     {"params": {"k": 4}, "score": neg}],
               "b": [{"params": {"k": 9}, "score": 5.0}]}
    report = {"candidates": {"a": {"accepted": True}, "b": {"accepted": False}}}
    assert vb.candidates_from_report(stage_a, report, 2, False) == [{"id": "a", "configs": [{"k": 2}, {"k": 3}]}]
    both = vb.candidates_from_report(stage_a, report, 5, True)
    assert [c["id"] for c in both] == ["a", "b"] and both[0]["configs"] == [{"k": 2}, {"k": 3}, {"k": 1}]


def test_candidates_from_report_old_report_with_string_bools():
    """Báo cáo cũ (json default=str) lưu 'False'/'True' dạng chuỗi: 'False' KHÔNG được coi là đạt."""
    vb = _load_script("validate_book")
    stage_a = {"a": [{"params": {"k": 1}, "score": 1.0}], "b": [{"params": {"k": 2}, "score": 2.0}],
               "c": [{"params": {"k": 3}, "score": 3.0}], "d": [{"params": {"k": 4}, "score": 4.0}]}
    report = {"candidates": {"a": {"accepted": "True"}, "b": {"accepted": "False"}, "c": {"accepted": True}, "d": {}}}
    assert [c["id"] for c in vb.candidates_from_report(stage_a, report, 1, False)] == ["a", "c"]


def test_wfa_job_rejects_unknown_params():
    vb = _load_script("validate_book")
    with pytest.raises(ValueError, match="tham số lạ"):
        vb.run_job({"candidates": "t_long", "bogus": 1})


def test_validate_book_main_end_to_end(market, monkeypatch, tmp_path):
    _small_book(monkeypatch)
    vb = _load_script("validate_book")
    start, end = (f"{__import__('pandas').Timestamp(t, unit='ms'):%Y-%m-%d}" for t in (START, T0 + 66 * DAY))
    res = vb.run_job({"candidates": "t_long,t_short", "n": 2, "workers": 2, "per_worker_mb": 300,
                      "start": start, "end": end, "train_days": 15, "test_days": 10, "sims": 200})
    reports = sorted((market / "_cache" / "book_wfa").glob("*/report.json"))
    assert reports
    rep = json.loads(reports[-1].read_text())
    assert len(rep["folds"]) == 3 and rep["summary"]["n_folds"] == 3 and rep["gate"]["passed"] is False
    assert {c["id"] for c in rep["candidates"]} == {"t_long", "t_short"} and all(len(c["configs"]) == 2 for c in rep["candidates"])
    assert rep["summary"]["mc"]["simulations"] == 200
    assert res["summary"]["compounded_oos_ret_pct"] == rep["summary"]["compounded_oos_ret_pct"]
    assert not (reports[-1].parent / "_shared").exists()                      # đã dọn dữ liệu dùng chung


def test_bootstrap_daily_default_sims_is_mc_minimum():
    import inspect
    from backend.carlo.monte_carlo import MC_MIN_SIMULATIONS
    from backend.carlo.monte_carlo import bootstrap_daily
    assert inspect.signature(bootstrap_daily).parameters["n"].default == MC_MIN_SIMULATIONS


def test_wfa_regime_learn_maps_come_from_train_only(market, monkeypatch, tmp_path):
    from backend.core.regime.learn import OBSERVE
    sb = _small_book(monkeypatch)
    log = _serial(monkeypatch)
    off = _run(sb, tmp_path, "off")
    res = pw.run_portfolio_wfa(_cands(), sb.perp_symbols(), START, T0 + 66 * DAY, CFG, RISK, 0.5, 1, str(tmp_path / "learn"),
                               regime="learn")
    assert res["regime"] == "learn" and "regime" not in off and all("regime_map" not in f for f in off["folds"])
    rg_jobs = next(jobs for label, jobs in log if "WFA-REGIME" in label)
    oos_jobs = [j for label, jobs in log if "WFA-OOS" in label for j in jobs][-6:]   # OOS của lần chạy learn
    for f in res["folds"]:
        job = next(j for j in rg_jobs if j.window == tuple(f["train_ts"]))          # học trên đúng cửa sổ train của fold
        assert job.window[1] <= f["test_ts"][0] and all(v == OBSERVE for v in job.regime.values())
        assert isinstance(f["train_by_regime"], dict) and isinstance(f["regime_map"], dict)
        for j in (j for j in oos_jobs if j.window == tuple(f["test_ts"])):
            assert (j.regime or {}) == f["regime_map"]                              # OOS dùng bảng học từ train
    # IS / chọn cấu hình không đổi khi bật learn
    assert [f["chosen"] for f in res["folds"]] == [f["chosen"] for f in off["folds"]]
    with pytest.raises(ValueError):
        pw.run_portfolio_wfa(_cands(), sb.perp_symbols(), START, T0 + 66 * DAY, CFG, RISK, 0.5, 1, str(tmp_path / "bad"), regime="static")
