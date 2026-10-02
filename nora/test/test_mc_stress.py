"""Monte Carlo >= 10.000 kịch bản + kịch bản cực xấu tất định + gate.

1. Dựng kịch bản trên chuỗi thủ công: MDD / lãi cuối / ngày xấu nhất / ngày chìm đúng từng số.
2. evaluate_mc_gate: mỗi check lật độc lập.
3. Tái lập 10.000 kịch bản; trùng bit bản bootstrap CŨ (cùng seed + số mô phỏng), bất kể kích thước lô; RAM bị chặn.
4. API: mặc định 10.000, tối đa 50.000, gate_eligible, bảng stress + worst_path.
5. optimize_alphas.monte_carlo_gate ghi mc.simulations / mc.stress / mc.gate.
"""
import importlib.util
import json
import os
import tracemalloc

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers import book as book_router
from backend.carlo import monte_carlo as mcm
from backend.carlo.monte_carlo import (MC_MIN_SIMULATIONS, STRESS_COST_FALLBACK_DAILY, STRESS_MAX_MDD_PCT, evaluate_mc_gate,
                                       longest_losing_run, run_monte_carlo, run_monte_carlo_daily, run_monte_carlo_daily_detail,
                                       stress_scenarios)

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NAMES = ["worst_days_first", "reversed_order", "crash_day", "cost_x2", "longest_losing_streak_x2"]


def by_name(rows):
    return {r["name"]: r for r in rows}


# ── 1. Kịch bản cực xấu trên chuỗi thủ công ─────────────────────────────────
def test_constants_and_scenario_names():
    assert MC_MIN_SIMULATIONS == 10_000 and STRESS_MAX_MDD_PCT == 50.0
    assert [r["name"] for r in stress_scenarios([0.1, -0.1])] == NAMES
    assert STRESS_COST_FALLBACK_DAILY == pytest.approx(0.0007)


def test_worst_days_first_and_reversed_exact():
    s = by_name(stress_scenarios([0.1, -0.1]))
    w = s["worst_days_first"]                          # [-0.1, +0.1]: 1 -> 0.9 -> 0.99
    assert (w["mdd_pct"], w["terminal_ret_pct"], w["worst_day_pct"], w["days_underwater"], w["ruin"]) == (10.0, -1.0, -10.0, 2, False)
    r = s["reversed_order"]                            # đảo [0.1, -0.1] -> [-0.1, 0.1]
    assert (r["mdd_pct"], r["terminal_ret_pct"], r["days_underwater"]) == (10.0, -1.0, 2)
    d = [0.10, -0.20, 0.05, -0.10, 0.0, -0.05, -0.05, 0.02]
    w = by_name(stress_scenarios(d))["worst_days_first"]
    assert w["mdd_pct"] == round((1 - 0.8 * 0.9 * 0.95 * 0.95) * 100, 2) == 35.02       # xếp tăng dần: mọi ngày lỗ trước
    assert w["days"] == len(d)


def test_crash_day_is_twice_worst_day_at_start_and_capped():
    c = by_name(stress_scenarios([0.1, -0.1]))["crash_day"]          # [-0.2, 0.1, -0.1] -> 0.8, 0.88, 0.792
    assert (c["mdd_pct"], c["terminal_ret_pct"], c["worst_day_pct"], c["days_underwater"], c["days"]) == (20.8, -20.8, -20.0, 3, 3)
    capped = by_name(stress_scenarios([0.05, -0.6, 0.05]))["crash_day"]
    assert capped["worst_day_pct"] == -95.0                          # 2 x -60% = -120% -> chặn -95%
    assert capped["mdd_pct"] == pytest.approx(100 * (1 - 0.05 * 1.05 * 0.4), abs=0.01)    # [-95%, +5%, -60%, +5%]
    none = by_name(stress_scenarios([0.01, 0.02]))["crash_day"]      # không có ngày lỗ -> không sập
    assert (none["mdd_pct"], none["worst_day_pct"], none["ruin"]) == (0.0, 0.0, False)


def test_cost_x2_penalises_only_active_days_and_uses_given_cost():
    s = by_name(stress_scenarios([0.1, 0.0, -0.1], extra_cost_daily=0.01))["cost_x2"]    # [0.09, 0, -0.11]
    assert s["terminal_ret_pct"] == round((1.09 * 0.89 - 1) * 100, 2) == -2.99
    assert s["mdd_pct"] == round((1 - 0.89) * 100, 2) == 11.0
    assert s["worst_day_pct"] == -11.0 and "0.010%" not in s["note_vi"] and "1.000%" in s["note_vi"]
    fb = by_name(stress_scenarios([0.1, 0.0, -0.1]))["cost_x2"]                         # không có số liệu -> hằng số bảo thủ 0,07%
    assert fb["worst_day_pct"] == pytest.approx(-10.07, abs=0.005) and "hằng số bảo thủ" in fb["note_vi"]
    assert mcm.estimate_extra_daily_cost(78, 434, 0.5) == pytest.approx((0.0005 + 0.0002) * 2 * 78 * 0.5 / 434)


def test_longest_losing_streak_x2_exact():
    d = [0.1, -0.1, -0.1, 0.1]
    assert list(longest_losing_run(d)) == [-0.1, -0.1]
    assert list(longest_losing_run([0.1, -0.1, 0.0, -0.1, -0.2, -0.3, 0.0])) == [-0.1, -0.2, -0.3]   # ngày 0 làm đứt chuỗi
    assert len(longest_losing_run([0.1, 0.2])) == 0
    s = by_name(stress_scenarios(d))["longest_losing_streak_x2"]     # [S, S, hist] = 4 ngày -0.1, +0.1, -0.1, -0.1, +0.1
    assert s["days"] == 8
    assert s["mdd_pct"] == round((1 - 0.9 ** 4 * 1.1 * 0.9 * 0.9) * 100, 2) == 41.54
    assert s["worst_day_pct"] == -10.0
    same = by_name(stress_scenarios([0.1, 0.2]))["longest_losing_streak_x2"]
    assert same["days"] == 2 and same["mdd_pct"] == 0.0               # không có ngày lỗ -> giữ nguyên


def test_ruin_when_equity_hits_zero_and_scale():
    s = by_name(stress_scenarios([-1.0, 0.5]))["worst_days_first"]
    assert s["ruin"] is True and s["mdd_pct"] == 100.0 and s["terminal_ret_pct"] == -100.0 and s["passed"] is False
    x = by_name(stress_scenarios([0.1, -0.1], scale=2.0))["worst_days_first"]    # [-0.2, +0.2]: 0.8 -> 0.96
    assert x["mdd_pct"] == 20.0 and x["terminal_ret_pct"] == -4.0
    with pytest.raises(ValueError):
        stress_scenarios([])


def test_stress_paths_are_sampled_and_end_at_terminal():
    d = list(np.random.default_rng(1).normal(0.001, 0.02, 400))
    for r in stress_scenarios(d):
        p = r["path"]
        assert p["days"][0] == 0 and p["days"][-1] == r["days"] and len(p["days"]) <= 75
        assert p["ret_pct"][0] == 0.0 and p["ret_pct"][-1] == r["terminal_ret_pct"]
    assert all("path" not in r for r in mcm.strip_paths(stress_scenarios(d)))
    json.dumps(stress_scenarios(d), allow_nan=False)


# ── 2. Gate: mỗi check lật độc lập ──────────────────────────────────────────
def _stress(**over):
    rows = [{"name": n, "mdd_pct": 20.0, "ruin": False} for n in NAMES + ["worst_bootstrap"]]
    for i, (k, v) in enumerate(over.items()):
        rows[i].update(v)
    return rows


def test_gate_each_check_flips_independently():
    ok = evaluate_mc_gate(10_000, 5.0, _stress())
    assert ok["passed"] and ok["gate_eligible"] and set(ok["checks"]) == {"simulations", "ruin", "stress_mdd", "stress_ruin"}
    assert ok["checks"]["simulations"] == {"label": "Số kịch bản bootstrap", "required": ">= 10000", "actual": 10_000, "passed": True}
    assert ok["checks"]["ruin"]["required"] == "<= 5.0%" and ok["checks"]["stress_mdd"]["required"] == "< 50%"
    cases = {
        "simulations": evaluate_mc_gate(9_999, 5.0, _stress()),
        "ruin": evaluate_mc_gate(10_000, 5.01, _stress()),
        "stress_mdd": evaluate_mc_gate(10_000, 5.0, _stress(a={"mdd_pct": 50.0})),
        "stress_ruin": evaluate_mc_gate(10_000, 5.0, _stress(a={"ruin": True})),
    }
    for name, g in cases.items():
        assert not g["passed"] and [k for k, c in g["checks"].items() if not c["passed"]] == [name]
    assert cases["simulations"]["gate_eligible"] is False and ok["gate_eligible"] is True
    assert cases["stress_mdd"]["checks"]["stress_mdd"]["actual"] == 50.0 and cases["stress_mdd"]["checks"]["stress_mdd"]["detail"]
    assert cases["stress_ruin"]["checks"]["stress_ruin"]["actual"] == 1
    assert evaluate_mc_gate(10_000, 5.0, _stress(a={"mdd_pct": 49.99}))["passed"]          # đúng dưới ngưỡng thì qua
    assert evaluate_mc_gate(10_000, 5.0, _stress(a={"mdd_pct": 55.0}), stress_max_mdd_pct=60.0)["passed"]   # ngưỡng cấu hình được
    for g in (evaluate_mc_gate(10_000, None, _stress()), evaluate_mc_gate(10_000, 1.0, None), evaluate_mc_gate(10_000, 1.0, [])):
        assert not g["passed"]                                                              # thiếu số liệu -> trượt


# ── 3. Tái lập, trùng bit bản cũ, RAM ───────────────────────────────────────
def _old_run_monte_carlo(trades, simulations, block_size, seed, ruin_threshold_pct=30.0, initial_capital=10000.0):
    """Bản run_monte_carlo TRƯỚC khi chia lô/thêm kịch bản cực xấu (một khối, rng.choice) — để so từng bit."""
    rng = np.random.default_rng(seed)
    pnl = np.array([float(t["pnl_pct"]) for t in trades])
    n = len(pnl)
    if block_size <= 1:
        sampled = rng.choice(pnl, size=(simulations, n), replace=True)
    else:
        nb = int(np.ceil(n / block_size))
        starts = rng.integers(0, max(1, n - block_size + 1), size=(simulations, nb))
        idx = (starts[:, :, None] + np.arange(block_size)[None, None, :]).reshape(simulations, -1)[:, :n]
        sampled = pnl[idx]
    cum = np.cumprod(np.maximum(0.0, 1.0 + sampled / 100.0), axis=1)
    eq = np.hstack([np.full((simulations, 1), initial_capital), initial_capital * cum])
    rm = np.maximum.accumulate(eq, axis=1)
    mdd = np.max((rm - eq) / np.maximum(rm, 1e-9) * 100.0, axis=1)
    term = eq[:, -1]
    tr = (term - initial_capital) / initial_capital * 100.0
    out = {"risk_of_ruin_pct": round(float(np.sum(mdd >= ruin_threshold_pct) / simulations * 100.0), 2),
           "percentile_mdd": {"p50": round(float(np.percentile(mdd, 50)), 2), "p90": round(float(np.percentile(mdd, 90)), 2),
                              "p95": round(float(np.percentile(mdd, 95)), 2), "p99": round(float(np.percentile(mdd, 99)), 2),
                              "worst": round(float(np.max(mdd)), 2)},
           "terminal_return_pct": {"p10": round(float(np.percentile(tr, 10)), 2), "p50": round(float(np.percentile(tr, 50)), 2),
                                   "p90": round(float(np.percentile(tr, 90)), 2), "worst": round(float(np.min(tr)), 2),
                                   "best": round(float(np.max(tr)), 2)},
           "summary": {"avg_mdd_pct": round(float(np.mean(mdd)), 2), "median_profit_usd": round(float(np.median(term - initial_capital)), 2),
                       "win_ratio_of_simulations": round(float(np.sum(tr > 0) / simulations * 100.0), 1),
                       "min_terminal_equity": round(float(np.min(term)), 2), "max_terminal_equity": round(float(np.max(term)), 2)}}
    chosen = {int(np.argmin(term)), int(np.argmax(term)), int(np.argsort(term)[simulations // 2])}
    for i in rng.choice(simulations, size=min(35, simulations), replace=False):
        chosen.add(int(i))
        if len(chosen) >= min(35, simulations):
            break
    steps = eq.shape[1]
    sidx = list(range(0, steps, max(1, steps // 60)))
    if sidx[-1] != steps - 1:
        sidx.append(steps - 1)
    out["sample_paths"] = [[round(float(eq[c, s]), 2) for s in sidx] for c in chosen]
    sm = eq[:, sidx]
    out["quantile_curves"] = {"steps": len(sidx), **{f"p{q}": [round(float(v), 2) for v in np.percentile(sm, q, axis=0)] for q in (5, 25, 50, 75, 95)},
                              "best": [round(float(v), 2) for v in np.max(sm, axis=0)], "worst": [round(float(v), 2) for v in np.min(sm, axis=0)]}
    return out, float(mdd.max())


@pytest.mark.parametrize("block,sims,chunk", [(5, 10_000, None), (1, 10_000, None), (5, 2_000, 7_000), (1, 1_500, 3_000), (3, 777, 1_000)])
def test_run_monte_carlo_bit_identical_to_previous_implementation(monkeypatch, block, sims, chunk):
    if chunk:
        monkeypatch.setattr(mcm, "MC_CHUNK_ELEMS", chunk)        # ép chia lô nhỏ: kết quả không được phụ thuộc kích thước lô
    rng = np.random.default_rng(5)
    trades = [{"pnl_pct": float(x)} for x in rng.normal(0.08, 2.5, 434)]
    ref, ref_worst = _old_run_monte_carlo(trades, sims, block, seed=7)
    new = run_monte_carlo(trades, simulations=sims, block_size=block, seed=7)
    wb = new.pop("worst_bootstrap")
    for k, v in ref.items():
        assert new[k] == v, k
    assert wb["name"] == "worst_bootstrap" and wb["mdd_pct"] == round(ref_worst, 2) == new["percentile_mdd"]["worst"]
    assert wb["days"] == 434


def test_run_monte_carlo_daily_identical_to_previous_bootstrap_loop():
    d = np.random.default_rng(11).normal(0.001, 0.015, 300)
    rng = np.random.default_rng(3)
    n, m, rets = 10_000, 365, []
    mdds = np.empty(n)
    rets = np.empty(n)
    for k in range(n):                                    # vòng lặp gốc của run_monte_carlo_daily
        idx = (rng.integers(0, len(d), m // 5 + 1)[:, None] + np.arange(5)).ravel()[:m] % len(d)
        eq = np.cumprod(1 + d[idx])
        peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
        mdds[k] = ((peak - eq) / peak).max()
        rets[k] = eq[-1] - 1
    ref = {"median_ret_pct": round(float(np.median(rets) * 100), 1), "p05_ret_pct": round(float(np.percentile(rets, 5) * 100), 1),
           "mdd_p50_pct": round(float(np.percentile(mdds, 50) * 100), 1), "mdd_p95_pct": round(float(np.percentile(mdds, 95) * 100), 1),
           "p_mdd_ge_ruin_pct": round(float((mdds >= 0.3).mean() * 100), 2), "simulations": n, "block_days": 5, "horizon_days": 365, "seed": 3}
    assert run_monte_carlo_daily(d, simulations=n, seed=3) == ref
    det = run_monte_carlo_daily_detail(d, simulations=n, seed=3)
    assert det["summary"] == ref
    worst = by_name(det["stress"])["worst_bootstrap"]                      # đường bootstrap tệ nhất = MDD lớn nhất của 10.000 đường
    assert worst["mdd_pct"] == pytest.approx(float(mdds.max()) * 100, abs=0.006)
    assert det["worst_path"] == worst["path"]
    defaults = run_monte_carlo_daily(d, seed=3)                             # mặc định = 10.000
    assert defaults["simulations"] == 10_000 and defaults == ref


def test_10k_is_deterministic_and_seed_sensitive():
    d = list(np.random.default_rng(2).normal(0.001, 0.012, 200))
    a = run_monte_carlo_daily_detail(d, seed=9)
    b = run_monte_carlo_daily_detail(d, seed=9)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["params"]["simulations"] == 10_000 and a["gate"]["gate_eligible"] is True
    assert run_monte_carlo_daily_detail(d, seed=10)["summary"] != a["summary"]
    assert [r["name"] for r in a["stress"]] == NAMES + ["worst_bootstrap"]
    # chuỗi kịch bản tất định: KHÔNG phụ thuộc seed
    assert run_monte_carlo_daily_detail(d, seed=10)["stress"][:5] == a["stress"][:5]


def test_chunked_memory_stays_bounded():
    trades = [{"pnl_pct": float(x)} for x in np.random.default_rng(4).normal(0.1, 2.0, 434)]
    tracemalloc.start()
    run_monte_carlo(trades, simulations=10_000, block_size=5, seed=7)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert peak < 200 * 1024 * 1024, peak / 1e6          # trước đây ~ >300 MB cho 10.000 x 434 (6 mảng 35 MB)


# ── 4. API ──────────────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / "data"))
    app = FastAPI()
    app.include_router(book_router.router)
    return TestClient(app)


DAILY = list(np.random.default_rng(11).normal(0.0012, 0.008, 150))


def test_api_defaults_stress_table_and_gate(client):
    out = client.post("/api/studio/book/mc", json={"daily_returns": DAILY}).json()
    assert out["params"]["simulations"] == 10_000 and out["gate"]["gate_eligible"] is True
    assert [r["name"] for r in out["stress"]] == NAMES + ["worst_bootstrap"]
    for r in out["stress"]:
        assert {"name", "label_vi", "mdd_pct", "terminal_ret_pct", "worst_day_pct", "days_underwater", "ruin", "passed", "path"} <= set(r)
    assert out["worst_path"] == out["stress"][-1]["path"] and out["worst_path"]["days"][-1] == 365
    g = out["gate"]
    assert set(g["checks"]) == {"simulations", "ruin", "stress_mdd", "stress_ruin"} and g["stress_max_mdd_pct"] == 50.0
    assert g["passed"] == all(c["passed"] for c in g["checks"].values())
    assert out["stress"][0]["mdd_pct"] == by_name(stress_scenarios(DAILY))["worst_days_first"]["mdd_pct"]


def test_api_low_count_runs_but_is_not_gate_eligible_and_max_allowed(client):
    low = client.post("/api/studio/book/mc", json={"daily_returns": DAILY, "simulations": 500, "mode": "advanced"}).json()
    assert low["gate"]["gate_eligible"] is False and low["gate"]["passed"] is False and low["gate"]["checks"]["simulations"]["actual"] == 500
    assert client.post("/api/studio/book/mc", json={"daily_returns": DAILY, "simulations": 50_001}).status_code == 422
    r = client.post("/api/studio/book/mc", json={"daily_returns": DAILY, "simulations": 50_000, "stress_max_mdd_pct": 5,
                                                  "extra_cost_daily_pct": 0.2, "mode": "advanced"})
    assert r.status_code == 200 and r.json()["params"]["simulations"] == 50_000
    assert r.json()["gate"]["stress_max_mdd_pct"] == 5.0 and r.json()["gate"]["checks"]["stress_mdd"]["passed"] is False
    assert r.json()["params"]["extra_cost_daily"] == pytest.approx(0.002)


# ── 5. optimize_alphas.monte_carlo_gate ─────────────────────────────────────
def _load_optimize():
    spec = importlib.util.spec_from_file_location("optimize_alphas_mod2", os.path.join(NORA_ROOT, "backend", "optimize", "optimize_alphas.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_optimize_alphas_gate_records_simulations_stress_and_gate():
    mod = _load_optimize()
    rng = np.random.default_rng(1)
    daily = [float(x) for x in rng.normal(0.001, 0.006, 200)]
    trades = [{"pnl_pct": float(x)} for x in rng.normal(0.5, 1.0, 60)]
    folds = [{"status": "TRADED", "chosen_params": {"order_size_pct": 50, "leverage": 2}}]
    res = {"aggregate_oos_trades": trades, "aggregate_oos_daily_returns": daily, "folds": folds}
    mc, mc_trades = mod.monte_carlo_gate(res)
    assert mc["simulations"] == mc_trades["simulations"] == 10_000 and mc["gate"]["gate_eligible"] is True
    assert [r["name"] for r in mc["stress"]] == NAMES + ["worst_bootstrap"] and all("path" not in r for r in mc["stress"])
    assert mc["gate"]["passed"] == all(c["passed"] for c in mc["gate"]["checks"].values())
    assert mc["extra_cost_daily"] == pytest.approx((0.0005 + 0.0002) * 2 * 60 * (0.5 * 2) / 200)       # vòng quay thật từ lệnh + tham số
    assert "stress" not in mc_trades and (mc, mc_trades) == mod.monte_carlo_gate(res)
    json.dumps(mc, allow_nan=False)
    low, _ = mod.monte_carlo_gate(res, sims=2000)                                                       # có thể chạy ít hơn nhưng không đủ gate
    assert low["gate"]["gate_eligible"] is False and low["gate"]["passed"] is False
    short, _ = mod.monte_carlo_gate({"aggregate_oos_trades": trades, "aggregate_oos_daily_returns": [0.01] * 10})
    assert short["risk_of_ruin_pct"] is None and short["gate"]["passed"] is False
    wild = {"aggregate_oos_trades": trades, "aggregate_oos_daily_returns": [float(x) for x in rng.normal(0.0, 0.05, 200)]}
    assert mod.monte_carlo_gate(wild)[0]["gate"]["passed"] is False
