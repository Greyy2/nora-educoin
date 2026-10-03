"""Phễu kiểm duyệt alpha (backend/optimize/funnel): ngưỡng, DSR, PBO, lân cận, tìm s, kho/resume, thống kê, API, lệnh tính lại.

Dữ liệu giả lập 3 tài sản perp (như test_strategy_book, không mạng); phễu chạy TUẦN TỰ trong tiến trình (workers=0). Ngưỡng được nới bằng monkeypatch
CHỈ TRONG TEST (để alpha ngẫu nhiên đi hết các tầng) — phần ngưỡng thật được kiểm riêng bằng hàm evaluate_*.
"""
import json
import math
import os

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from job_modules import launched
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.data.resampler import save_resampled_dataset
from backend.optimize.funnel import antiluck, gates, sizing, stats as fstats
from backend.optimize.funnel.generate import alpha_id_of, iter_params, validate_alpha
from backend.optimize.funnel.storage import RunStore

T0 = 1_700_006_400_000
SYMS = ("AAA", "BBB", "CCC")
DAYS = 56


def _series(days, seed, vol):
    n = days * 1440
    rng = np.random.default_rng(seed)
    r = rng.normal(0.00002, vol, n)
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open_time": T0 + np.arange(n, dtype=np.int64) * 60_000, "open": o,
                         "high": np.maximum(o, c) * (1 + vol / 3), "low": np.minimum(o, c) * (1 - vol / 3),
                         "close": c, "volume": 10.0})


@pytest.fixture(scope="module")
def market(tmp_path_factory):
    root = tmp_path_factory.mktemp("fdata") / "data"
    old = os.environ.get("NORA_LOCAL_DATA_ROOT")
    os.environ["NORA_LOCAL_DATA_ROOT"] = str(root)
    meta = {"venue": "cex", "checksums_verified": True, "exchange": "binance"}
    for k, sym in enumerate(SYMS):
        df = _series(DAYS, 20 + k, 0.0008 * (k + 1))
        end = int(df.open_time.max())
        for name, out, extra in ((sym, root / "cex", {}), ("perp", root / "cex" / sym, {"exchange": "binance_usdm", "market": "perp"})):
            save_resampled_dataset(symbol=name, output_dir=str(out), df_1m_raw=df, pool_address="x", crawl_ok=True,
                                   requested_start_ts=T0, requested_end_ts=end, extra_meta={**meta, **extra})
        ft = T0 + np.arange(1, DAYS * 3) * 8 * 3_600_000
        pd.DataFrame({"funding_time": ft, "interval_h": 8.0, "rate": 0.0001}).to_pickle(root / "cex" / sym / "perp" / "funding.pkl")
    yield root
    if old is None:
        os.environ.pop("NORA_LOCAL_DATA_ROOT", None)
    else:
        os.environ["NORA_LOCAL_DATA_ROOT"] = old


@pytest.fixture(autouse=True)
def _data_root(market):
    os.environ["NORA_LOCAL_DATA_ROOT"] = str(market)   # conftest khôi phục sau mỗi test -> đặt lại
    yield


@pytest.fixture
def small_book(monkeypatch):
    """Chiến lược test + vũ trụ 3 tài sản; ngưỡng NỚI (chỉ test): mọi alpha có lệnh đi hết các tầng."""
    from backend.core.strategy import book as sb
    f = sb.f
    cands = [{"id": "t_long", "family": "x", "side": "LONG", "description": "test",
              "tree": sb.cond((f("15m", "rsi_14"), "<", sb.p("lo", 40))), "position": {},
              "space": {"sig.lo": [35, 40, 45], "stop_loss_rate": [2.0], "take_profit_rate": [2.0], "timeout": [720]}}]
    monkeypatch.setattr(sb, "UNIVERSE", list(SYMS))
    monkeypatch.setattr(sb, "CANDIDATES", cands)
    return sb


@pytest.fixture
def lenient(monkeypatch):
    for k, v in dict(S1_MIN_RET_PCT=-1000.0, S1_MAX_MDD_PCT=1000.0, S1_MIN_TRADES=1, S1_MIN_SYMBOLS_POSITIVE=0, S2_DSR_MIN=0.0,
                     S2_NEIGHBOUR_MIN_PROFIT_RATIO=0.0, S2_PBO_MAX=1.0, S3_MIN_FOLDS=2, S3_MIN_POSITIVE_FOLD_RATIO=0.0,
                     S3_MIN_COMPOUNDED_OOS_PCT=-1000.0, S3_MAX_FOLD_MDD_PCT=1000.0, S3_MIN_AVG_IS_RET_PCT=-1000.0,
                     S4_MIN_SIMULATIONS=200, S4_MAX_RUIN_PCT=100.0, S4_STRESS_MAX_MDD_PCT=1000.0, S4_MIN_DAYS=5,
                     S6_MIN_RET_PCT=-1000.0, S6_MAX_MDD_PCT=1000.0).items():
        monkeypatch.setattr(gates, k, v)


def _cfg(**kw):
    from backend.optimize.funnel.orchestrator import FunnelConfig
    return FunnelConfig(strategies=["t_long"], n_per_strategy=3, seed=7, train_days=5, test_days=4, **kw)


def _run(run_id, **kw):
    from backend.optimize.funnel import orchestrator as orch
    return orch.run_funnel(_cfg(), run_id=run_id, workers=0, log=lambda s: None, **kw)


# ─── Ngưỡng + hàm thuần ─────────────────────────────────────────────────────
def test_gate_constants_match_existing_gates():
    from backend.carlo import monte_carlo as mc
    from backend.core.strategy.book import BASE_RISK_PER_TRADE_PCT, GATES
    from backend.wfa import walk_forward as pw
    assert gates.S1_MIN_TRADES == GATES["min_trades"] and gates.S1_MIN_SYMBOLS_POSITIVE == GATES["min_symbols_positive"]
    assert gates.S1_MAX_MDD_PCT == GATES["max_mdd_pct"] and gates.BASE_RISK_PER_TRADE_PCT == BASE_RISK_PER_TRADE_PCT
    assert gates.S3_MIN_FOLDS == pw.MIN_FOLDS and gates.S3_MIN_POSITIVE_FOLD_RATIO == pw.MIN_POSITIVE_FOLD_RATIO
    assert gates.S3_MAX_FOLD_MDD_PCT == pw.MAX_FOLD_MDD_PCT and gates.S3_MIN_AVG_IS_RET_PCT == pw.MIN_AVG_IS_RET_PCT
    assert (gates.S3_TRAIN_DAYS, gates.S3_TEST_DAYS) == (120, 30)
    assert gates.S4_MIN_SIMULATIONS == mc.MC_MIN_SIMULATIONS == 10_000 and gates.S4_MAX_RUIN_PCT == mc.MC_MAX_RUIN_PCT == 5.0
    assert gates.S4_STRESS_MAX_MDD_PCT == mc.STRESS_MAX_MDD_PCT == 50.0 and gates.S4_RUIN_THRESHOLD_PCT == mc.MC_RUIN_THRESHOLD_PCT
    assert (gates.S2_DSR_MIN, gates.S2_NEIGHBOUR_MIN_PROFIT_RATIO, gates.S2_PBO_MAX, gates.S2_PBO_BLOCKS) == (0.95, 0.60, 0.5, 16)
    assert (gates.S5_S_MIN, gates.S5_S_MAX, gates.S5_TOLERANCE) == (0.2, 1.0, 0.01)
    assert gates.STAGES[0] == "S0_generate" and gates.STAGES[-1] == "FINAL" and len(gates.STAGES) == 8


def test_windows_match_build_strategy_book(market):
    from backend.optimize.funnel.gates import compute_windows
    import importlib
    bsb = importlib.import_module("backend.optimize.book")
    syms = [f"{s}@perp" for s in SYMS]
    assert compute_windows(syms) == bsb.windows(syms)


def test_reject_codes_and_messages():
    ok = {"ret_pct": 5.0, "mdd_pct": 10.0, "trades": 100, "symbols_positive": 6}
    assert gates.evaluate_s1(ok)[0]
    assert gates.evaluate_s1({**ok, "ret_pct": -1})[1] == "S1.ret_nonpositive"
    assert gates.evaluate_s1({**ok, "mdd_pct": 31})[1] == "S1.mdd"
    assert gates.evaluate_s1({**ok, "trades": 10})[1] == "S1.min_trades"
    assert gates.evaluate_s1({**ok, "symbols_positive": 2})[1] == "S1.symbols_positive"
    ok_, code, msg = gates.evaluate_s1({**ok, "trades": 10})
    assert msg.startswith("S1.min_trades: ") and "10 < 40" in msg
    assert gates.evaluate_s2(0.99, 0.8, 0.2)[0]
    assert gates.evaluate_s2(0.99, 0.8, 0.6)[1] == "S2.pbo"
    assert gates.evaluate_s2(0.5, 0.8, 0.2)[1] == "S2.dsr"
    assert gates.evaluate_s2(0.99, 0.5, 0.2)[1] == "S2.neighbor"
    s3 = {"folds": 8, "positive_ratio": 0.75, "compounded_oos_ret_pct": 3.0, "worst_fold_mdd": 12.0, "is_ret_avg": 4.0}
    assert gates.evaluate_s3(s3)[0]
    assert gates.evaluate_s3({**s3, "folds": 4})[1] == "S3.folds"
    assert gates.evaluate_s3({**s3, "positive_ratio": 0.4})[2] == "S3.positive_ratio: Tỉ lệ fold lãi < 60% (40% < 60%)"
    assert gates.evaluate_s3({**s3, "compounded_oos_ret_pct": 0})[1] == "S3.oos_compound"
    assert gates.evaluate_s3({**s3, "worst_fold_mdd": 31})[1] == "S3.worst_fold_mdd"
    assert gates.evaluate_s3({**s3, "is_ret_avg": -1})[1] == "S3.avg_is"
    lv = {"ret_pct": 2.0, "mdd_pct": 10.0}
    assert gates.evaluate_s6(lv, lv)[0]
    assert gates.evaluate_s6(lv, {**lv, "ret_pct": -1})[1] == "S6.holdout_ret"
    assert gates.evaluate_s6({**lv, "mdd_pct": 40}, lv)[1] == "S6.holdout_mdd"
    for code in gates.REASON_LABELS:
        assert code.split(".")[0] in gates.STAGE_IDX or code.split(".")[0] in {"S0", "S1", "S2", "S3", "S4", "S5", "S6"}


def test_dsr_matches_hand_computed_example():
    """N = 10 lần thử, phương sai Sharpe 4e-4: SR0 = 0.02·(0.4228·Φ⁻¹(0.9) + 0.5772·Φ⁻¹(1 − 1/(10e))) = 0.02·(0.4228·1.28155 + 0.5772·1.79085) ≈ 0.031492
    (Φ⁻¹ tra bảng chuẩn). SR = 0.1/ngày, T = 252, skew −0.5, kurt 5:
    mẫu số = sqrt(1 − (−0.5)(0.1) + (5 − 1)/4·0.01) = sqrt(1.06) = 1.029563; z = (0.1 − 0.031492)·sqrt(251)/1.029563 = 1.0542 ->
    DSR = Φ(z)."""
    sr0 = antiluck.expected_max_sr(10, 0.0004)
    assert sr0 == pytest.approx(0.031492, abs=2e-6)
    d = antiluck.deflated_sharpe(0.1, 252, -0.5, 5.0, 10, 0.0004)
    z = (0.1 - 0.0314920) * math.sqrt(251) / math.sqrt(1.06)
    assert z == pytest.approx(1.0542, abs=2e-4)
    expect = 0.5 * math.erfc(-z / math.sqrt(2))
    assert d["dsr"] == pytest.approx(expect, abs=1e-4) and d["dsr"] == pytest.approx(0.8541, abs=2e-3)
    # một lần thử duy nhất (N = 1) hoặc không có phương sai: SR0 = 0 -> DSR = xác suất SR > 0
    assert antiluck.expected_max_sr(1, 0.01) == 0.0
    assert antiluck.deflated_sharpe(0.1, 252, 0.0, 3.0, 1, 0.0)["dsr"] == pytest.approx(0.94299, abs=1e-4)   # Φ(0.1·√251) = Φ(1.5843)
    # alpha kém hơn kỳ vọng SR lớn nhất -> DSR < 0,5
    assert antiluck.deflated_sharpe(0.02, 252, 0.0, 3.0, 1000, 0.0004)["dsr"] < 0.5


def test_pbo_overfit_high_robust_low():
    rng = np.random.default_rng(3)
    T, N, B = 16 * 20, 60, 20
    over = np.zeros((T, N))
    for j in range(N):   # mỗi alpha lãi ở nửa số khối, lỗ ở nửa còn lại (cân bằng): tốt nhất ở IS thì tệ nhất ở OOS
        sign = np.array([1] * 8 + [-1] * 8)
        rng.shuffle(sign)
        over[:, j] = np.repeat(sign, B) * 0.003 + rng.normal(0, 0.01, T)
    rob = np.zeros((T, N))
    for j in range(N):   # chênh lệch kỹ năng BỀN: alpha j có drift 0.0003·j ở mọi khối
        rob[:, j] = 0.0003 * j + rng.normal(0, 0.01, T)
    po, pr = antiluck.pbo_cscv(over), antiluck.pbo_cscv(rob)
    assert po["n_splits"] == 12870 and po["pbo"] > 0.6
    assert pr["pbo"] < 0.1
    assert gates.evaluate_s2(0.99, 0.9, po["pbo"])[1] == "S2.pbo"
    assert antiluck.pbo_cscv(over[:10])["pbo"] is None   # không đủ ngày


def test_neighbours_and_alpha_ids():
    space = {"a": [1, 2, 3], "b": [10], "c": [0.5, 1.5]}
    nb = antiluck.neighbours(space, {"a": 2, "b": 10, "c": 0.5})
    assert sorted((tuple(sorted(n.items()))) for n in nb) == sorted([(("a", 1), ("b", 10), ("c", 0.5)), (("a", 3), ("b", 10), ("c", 0.5)),
                                                                     (("a", 2), ("b", 10), ("c", 1.5))])
    assert antiluck.neighbours(space, {"a": 1, "b": 10, "c": 1.5}) == [{"a": 2, "b": 10, "c": 1.5}, {"a": 1, "b": 10, "c": 0.5}]
    assert alpha_id_of("s", {"a": 1, "b": 2}) == alpha_id_of("s", {"b": 2, "a": 1}) != alpha_id_of("s2", {"a": 1, "b": 2})
    a = list(iter_params(space, 4, 7))
    assert a == list(iter_params(space, 4, 7)) and len({alpha_id_of("s", p) for p in a}) == 4
    assert len(list(iter_params(space, None, 7, full_grid=True))) == 6 == len(list(iter_params(space, 99, 7)))


def test_validate_alpha_rejects_bad_params():
    from backend.core.strategy.book import CANDIDATES
    c = CANDIDATES[0]
    ok = next(iter_params(c["space"], 1, 7))
    assert validate_alpha(c, ok) is None
    assert "khoá tham số" in validate_alpha(c, {**ok, "nope": 1})
    assert validate_alpha(c, {**ok, "stop_loss_rate": float("nan")})
    assert "đòn bẩy" in validate_alpha({**c, "position": {"leverage": 50}}, ok)


def test_sizing_binary_search_and_confirmation():
    calls = []

    def check(s):
        calls.append(s)
        return {"passed": s <= 0.63, "p_mdd_ge_30": 100 * s, "stress_max_mdd": 70 * s}
    s, steps = sizing.search_scale(check)
    assert s == 0.62 and steps[0]["s"] == 1.0 and not steps[0]["passed"] and steps[1]["s"] == 0.2
    assert all(0.2 <= x <= 1.0 for x in calls) and abs(max(x["s"] for x in steps if x["passed"]) - 0.63) <= 0.01
    assert sizing.search_scale(lambda s: {"passed": True})[0] == 1.0
    assert sizing.search_scale(lambda s: {"passed": False})[0] is None            # s < 0,2 -> loại
    assert sizing.search_scale(lambda s: {"passed": s <= 0.2})[0] == 0.2
    # xác nhận thật trượt ở s đầu -> hạ từng bước 0,05 tới khi qua
    s2, att = sizing.confirm_with_stepdown(0.62, lambda s: {"passed": s <= 0.52})
    assert s2 == 0.52 and [round(a["s"], 2) for a in att] == [0.62, 0.57, 0.52]
    assert sizing.confirm_with_stepdown(0.3, lambda s: {"passed": False})[0] is None
    assert sizing.confirm_with_stepdown(0.21, lambda s: {"passed": s < 0.2})[0] is None   # s < S_MIN: dừng
    pos = {"sizing": "risk", "risk_per_trade_pct": 0.5}
    assert sizing.scale_position(pos, 0.4)["risk_per_trade_pct"] == 0.2
    assert sizing.scale_position({"sizing": "margin_pct", "order_size_pct": 50.0}, 0.5)["order_size_pct"] == 25.0
    assert sizing.risk_for_scale(0.62) == pytest.approx(0.31)


def test_stats_histogram_bins_and_in_out():
    rng = np.random.default_rng(1)
    vals = np.r_[rng.normal(0, 1, 500), [50.0, -50.0]]       # 2 giá trị ngoại lai: dồn vào bin đầu/cuối
    edges = fstats.make_edges(vals)
    assert len(edges) == 31
    assert edges[0] == pytest.approx(np.percentile(vals, 1)) and edges[-1] == pytest.approx(np.percentile(vals, 99))
    hin, hout = fstats.histogram(vals, edges), fstats.histogram(vals[vals > 0], edges)
    assert len(hin["bins"]) == 30 == len(hout["bins"]) and sum(b["count"] for b in hin["bins"]) == len(vals) == hin["n"]
    assert [b["lo"] for b in hin["bins"]] == [b["lo"] for b in hout["bins"]]       # cùng bin cho in và out
    assert sum(b["count"] for b in hout["bins"]) == int((vals > 0).sum())
    assert set(hin) == {"bins", "n", "p5", "p50", "p95"}
    assert fstats.histogram(np.array([]), None)["bins"] == []


# ─── Chạy phễu trên dữ liệu giả lập ─────────────────────────────────────────
@pytest.fixture(scope="module")
def full_run(market):
    """Một lượt đầy đủ S0 → FINAL (ngưỡng nới) dùng chung cho các test đọc kết quả."""
    mp = pytest.MonkeyPatch()
    from backend.core.strategy import book as sb
    f = sb.f
    cands = [{"id": "t_long", "family": "x", "side": "LONG", "description": "test",
              "tree": sb.cond((f("15m", "rsi_14"), "<", sb.p("lo", 40))), "position": {},
              "space": {"sig.lo": [35, 40, 45], "stop_loss_rate": [2.0], "take_profit_rate": [2.0], "timeout": [720]}}]
    mp.setattr(sb, "UNIVERSE", list(SYMS))
    mp.setattr(sb, "CANDIDATES", cands)
    for k, v in dict(S1_MIN_RET_PCT=-1000.0, S1_MAX_MDD_PCT=1000.0, S1_MIN_TRADES=1, S1_MIN_SYMBOLS_POSITIVE=0, S2_DSR_MIN=0.0,
                     S2_NEIGHBOUR_MIN_PROFIT_RATIO=0.0, S2_PBO_MAX=1.0, S3_MIN_FOLDS=2, S3_MIN_POSITIVE_FOLD_RATIO=0.0,
                     S3_MIN_COMPOUNDED_OOS_PCT=-1000.0, S3_MAX_FOLD_MDD_PCT=1000.0, S3_MIN_AVG_IS_RET_PCT=-1000.0,
                     S4_MIN_SIMULATIONS=200, S4_MAX_RUIN_PCT=100.0, S4_STRESS_MAX_MDD_PCT=1000.0, S4_MIN_DAYS=5,
                     S6_MIN_RET_PCT=-1000.0, S6_MAX_MDD_PCT=1000.0).items():
        mp.setattr(gates, k, v)
    old = os.environ.get("NORA_LOCAL_DATA_ROOT")
    os.environ["NORA_LOCAL_DATA_ROOT"] = str(market)
    res = _run("fr-test-full")
    yield res
    mp.undo()
    if old is not None:
        os.environ["NORA_LOCAL_DATA_ROOT"] = old


def test_full_pipeline_stage_transitions_and_storage(full_run):
    res = full_run
    c = {x["stage"]: x for x in res["counts"]}
    assert res["status"] == "done"
    assert c["S0_generate"]["done"] == 3 and c["S0_generate"]["passed"] == 3
    for prev, cur in zip(gates.STAGES, gates.STAGES[1:]):    # input của tầng sau = số qua của tầng trước
        assert c[cur]["input"] == c[prev]["passed"], (prev, cur)
        assert c[cur]["passed"] + c[cur]["rejected"] == c[cur]["done"] == c[cur]["input"]
    assert c["S1_backtest"]["passed"] >= 1 and c["FINAL"]["passed"] >= 1
    store = RunStore(res["run_dir"], read_only=True)
    try:
        for fa in res["final_alphas"]:
            assert fa["stage_reached"] == "FINAL" and fa["rejected_stage"] is None and 0.2 <= fa["final_scale"] <= 1.0
            a = fa["alpha_id"]
            sm = store.alpha_metrics(a)
            assert set(sm) == set(gates.STAGES[1:])     # có số đo ở mọi tầng S1..FINAL
            assert {"dsr", "neighbor_ratio", "pbo_strategy", "pbo_flag"} <= set(sm["S2_antiluck"])
            assert {"folds", "folds_profitable", "positive_ratio", "worst_fold_mdd", "is_ret_avg"} <= set(sm["S3_wfa"])
            assert {"p_mdd_ge_30", "stress_max_mdd", "simulations", "mdd_p95"} <= set(sm["S4_montecarlo"])
            assert sm["S5_sizing"]["final_scale"] == fa["final_scale"] == sm["FINAL"]["final_scale"]
            t1, t3, t5, t6 = (store.read_trades(a, s) for s in ("S1_backtest", "S3_wfa", "S5_sizing", "S6_holdout"))
            assert t1 and t3 and t6
            assert set(t3[0]) == set(__import__("backend.optimize.funnel.storage", fromlist=["TRADE_COLS"]).TRADE_COLS)
            assert all(r["fold"] in (1, 2) for r in t3) and all(r["fold"] is None for r in t1)
            assert {r["stage"] for r in t6} == {"S6_holdout", "S6_holdout_extreme"}
            assert store.read_daily(a, "S1_backtest") and store.read_daily(a, "S3_wfa", "S3_wfa") and store.read_daily(a, "S6_holdout")
            mc = store.read_mc(a)
            assert mc["mc"]["summary"]["simulations"] >= 200 and mc["mc"]["fan"]["p50"] and mc["scale_search"]
            assert mc["verified"] == {"backtest": True, "wfa": True, "mc": True}
    finally:
        store.close()
    for fn in ("run.json", "results.sqlite", "progress.json"):
        assert os.path.isfile(os.path.join(res["run_dir"], fn))
    run = json.load(open(os.path.join(res["run_dir"], "run.json"), encoding="utf-8"))
    assert run["status"] == "done" and all(run["stages"][s]["status"] == "done" for s in gates.STAGES)
    assert run["config"]["strategies"] == ["t_long"] and run["config"]["data_sha256"] and run["config"]["thresholds"]["S2_DSR_MIN"] == 0.0
    assert not os.path.exists(os.path.join(res["run_dir"], "_shared"))


def test_stage_stats_payload_shape(full_run):
    store = RunStore(full_run["run_dir"], read_only=True)
    try:
        for stage in gates.STAGES:
            s = fstats.stage_stats(store, stage)
            assert {"stage", "input", "passed", "rejected", "reject_reasons", "distributions", "by_strategy", "param_survival", "top"} <= set(s)
            assert s["passed"] + s["rejected"] == s["input"]
            assert [b["strategy"] for b in s["by_strategy"]] == ["t_long"] and sum(b["input"] for b in s["by_strategy"]) == s["input"]
            if stage == "S0_generate":
                assert s["distributions"] == {}
                continue
            assert set(s["distributions"]) == set(fstats.DIST_KEYS)
            for key, d in s["distributions"].items():
                assert len(d["in"]["bins"]) == 30 and d["in"]["n"] == s["input"]
                assert d["out"]["n"] == s["passed"] and len(d["out"]["bins"]) == 30
                assert [b["lo"] for b in d["in"]["bins"]] == [b["lo"] for b in d["out"]["bins"]]
                assert sum(b["count"] for b in d["in"]["bins"]) == s["input"]
        s1 = fstats.stage_stats(store, "S1_backtest")
        ps = {p["param"]: p for p in s1["param_survival"]}
        assert [v["value"] for v in ps["sig.lo"]["values"]] == [35, 40, 45] and sum(v["input"] for v in ps["sig.lo"]["values"]) == 3
        assert s1["top"][0]["metrics"]["ret_pct"] is not None and s1["by_strategy"][0]["best_alpha_id"]
    finally:
        store.close()


def test_trades_recompute_identical_to_stored_for_passer(full_run):
    from backend.optimize.funnel.recompute import recompute_s1
    a = full_run["final_alphas"][0]["alpha_id"]
    store = RunStore(full_run["run_dir"], read_only=True)
    try:
        stored = store.read_trades(a, "S1_backtest")
    finally:
        store.close()
    got = recompute_s1(full_run["run_dir"], a)["trades"]
    assert len(got) == len(stored) > 0
    stored.sort(key=lambda r: (r["enter_time"], r["symbol"]))
    got.sort(key=lambda r: (r["enter_time"], r["symbol"]))
    for s, g in zip(stored, got):
        assert {k: s[k] for k in g} == {k: g[k] for k in g}   # trùng từng bit (cùng float, cùng số nguyên)


@pytest.fixture
def client(monkeypatch):
    from backend.api.routers import funnel as fr
    app = FastAPI()
    app.include_router(fr.router)
    return TestClient(app)


def test_api_endpoints_on_full_run(full_run, client, tmp_path, monkeypatch):
    rid, base = full_run["run_id"], "/api/studio/funnel"
    r = client.get(f"{base}/runs")
    assert r.status_code == 200
    run = next(x for x in r.json()["runs"] if x["run_id"] == rid)
    assert run["status"] == "done" and run["strategies"] == ["t_long"]
    assert [c["stage"] for c in run["counts"]][0] == "S0_generate" and {"stage", "input", "passed", "top_reject"} <= set(run["counts"][1])
    d = client.get(f"{base}/runs/{rid}").json()
    assert d["config"]["seed"] == 7 and d["counts"] == run["counts"] and "stages" in d and "started" in d and "job_id" in d
    assert client.get(f"{base}/runs/nonexistent-run").status_code == 404
    st = client.get(f"{base}/runs/{rid}/stages/S3_wfa/stats").json()
    assert st["stage"] == "S3_wfa" and len(st["distributions"]["ret_pct"]["in"]["bins"]) == 30
    assert client.get(f"{base}/runs/{rid}/stages/S9_nope/stats").status_code == 404
    al = client.get(f"{base}/runs/{rid}/alphas", params={"stage": "S1_backtest", "status": "passed", "sort": "-ret_pct", "limit": 2}).json()
    assert al["total"] == 3 and len(al["items"]) == 2 and al["items"][0]["metrics"]["ret_pct"] >= al["items"][1]["metrics"]["ret_pct"]
    assert {"alpha_id", "strategy", "params", "stage_reached", "rejected_stage", "reject_code", "reject_msg", "final_scale", "metrics"} <= set(al["items"][0])
    asc = client.get(f"{base}/runs/{rid}/alphas", params={"stage": "S1_backtest", "sort": "ret_pct"}).json()["items"]
    assert [i["metrics"]["ret_pct"] for i in asc] == sorted(i["metrics"]["ret_pct"] for i in asc)
    assert client.get(f"{base}/runs/{rid}/alphas", params={"sort": "-bogus"}).status_code == 422
    assert client.get(f"{base}/runs/{rid}/alphas", params={"status": "rejected", "stage": "S1_backtest"}).json()["total"] == 0
    a = full_run["final_alphas"][0]["alpha_id"]
    det = client.get(f"{base}/runs/{rid}/alphas/{a}").json()
    assert det["stage_reached"] == "FINAL" and det["final_scale"] and set(det["stage_metrics"]) == set(gates.STAGES[1:])
    assert {"S1_backtest", "S3_wfa", "S5_sizing", "S6_holdout"} <= set(det["nav"]) and len(det["nav"]["S1_backtest"]["dates"]) == len(det["nav"]["S1_backtest"]["values"])
    assert {"summary", "fan", "stress", "gate"} <= set(det["mc"]) and det["scale_search"] and det["verified"]["mc"] is True
    tr = client.get(f"{base}/runs/{rid}/alphas/{a}/trades", params={"stage": "S3_wfa", "limit": 3}).json()
    assert tr["stored"] is True and tr["total"] > 3 and len(tr["items"]) == 3 and tr["folds"] == [1, 2] and "recomputed" not in tr
    assert tr["items"][0]["enter_time"].endswith("Z") and tr["items"][0]["fold"] in (1, 2)
    f2 = client.get(f"{base}/runs/{rid}/alphas/{a}/trades", params={"stage": "S3_wfa", "fold": 2, "limit": 1000}).json()
    assert f2["items"] and all(i["fold"] == 2 for i in f2["items"])
    pg = client.get(f"{base}/runs/{rid}/alphas/{a}/trades", params={"stage": "S1_backtest", "offset": 1, "limit": 2}).json()
    assert pg["offset"] == 1 and len(pg["items"]) == min(2, pg["total"] - 1)
    # promote: cần confirm; ghi registry.json (giữ mục cũ), khoá funnel mới, cấu hình testnet
    ad = tmp_path / "alphas"
    ad.mkdir()
    (ad / "registry.json").write_text(json.dumps({"generated_at": 1, "alphas": [{"alpha_id": "old__SOL", "x": 1}], "gates": {}}), encoding="utf-8")
    monkeypatch.setenv("NORA_ALPHAS_DIR", str(ad))
    assert client.post(f"{base}/runs/{rid}/alphas/{a}/promote", json={}).status_code == 400
    p = client.post(f"{base}/runs/{rid}/alphas/{a}/promote", json={"confirm": True, "note": "t"})
    assert p.status_code == 200, p.text
    pj = p.json()
    assert pj["alpha_id"] == a and pj["final_scale"] == det["final_scale"] and os.path.isfile(pj["registry_path"]) and os.path.isfile(pj["testnet_config"])
    reg = json.loads((ad / "registry.json").read_text(encoding="utf-8"))
    assert [x["alpha_id"] for x in reg["alphas"]][0] == "old__SOL" and len(reg["alphas"]) == 2
    new = reg["alphas"][1]
    assert new["funnel"]["final_scale"] == det["final_scale"] and new["funnel"]["run_id"] == rid and new["strategy"] == "t_long" and new["market"] == "perp"
    assert new["position"]["risk_per_trade_pct"] == pytest.approx(sizing.risk_for_scale(det["final_scale"]))
    assert client.post(f"{base}/runs/{rid}/alphas/{a}/promote", json={"confirm": True}).status_code == 200
    assert len(json.loads((ad / "registry.json").read_text(encoding="utf-8"))["alphas"]) == 2   # idempotent
    # alpha chưa FINAL không đưa vào kho
    rej = client.get(f"{base}/runs/{rid}/alphas", params={"stage": "FINAL", "status": "rejected"}).json()
    assert rej["total"] == 0


def test_s1_rejects_store_stats_only_and_recompute_endpoint(small_book, monkeypatch, client):
    """Alpha bị loại ở S1: chỉ thống kê + daily (cho PBO), KHÔNG có lệnh; API trả stored=false, recompute=true tính lại tất định."""
    monkeypatch.setattr(gates, "S1_MIN_TRADES", 10 ** 6)
    res = _run("fr-test-s1rej", until="S1_backtest")
    c = {x["stage"]: x for x in res["counts"]}
    assert c["S1_backtest"]["rejected"] == 3 and c["S1_backtest"]["passed"] == 0 and c["S2_antiluck"]["input"] == 0
    store = RunStore(res["run_dir"], read_only=True)
    try:
        rows = list(store.iter_stage_metrics("S1_backtest"))
        assert len(rows) == 3
        a = rows[0][0]
        assert not store.read_trades(a) and store.read_daily(a, "S1_backtest")
        al = store.get_alpha(a)
        assert al["reject_code"] == "S1.min_trades" and al["reject_msg"].startswith("S1.min_trades: ") and al["rejected_stage"] == "S1_backtest"
    finally:
        store.close()
    from backend.api.routers import funnel as fr
    from backend.optimize.funnel.recompute import cache_path, recompute_s1
    from backend.optimize.funnel.storage import atomic_write_json
    calls = []
    monkeypatch.setattr(fr, "_run_recompute_subprocess", lambda run_id, aid: (calls.append(aid), atomic_write_json(cache_path(res["run_dir"], aid), recompute_s1(res["run_dir"], aid))))
    base = f"/api/studio/funnel/runs/{res['run_id']}/alphas/{a}/trades"
    j = client.get(base, params={"stage": "S1_backtest"}).json()
    assert j["stored"] is False and j["items"] == [] and j["can_recompute"] is True and not calls
    j = client.get(base, params={"stage": "S1_backtest", "recompute": "true", "limit": 1000}).json()
    assert j["recomputed"] is True and j["total"] == rows[0][2]["trades"] and len(j["items"]) == j["total"] and calls == [a]
    j2 = client.get(base, params={"stage": "S1_backtest", "recompute": "true", "limit": 1000}).json()
    assert j2["items"] == j["items"] and calls == [a]    # lần sau đọc từ đệm
    ets = [i["enter_time"] for i in j["items"]]
    assert ets == sorted(ets)


def test_real_strict_gates_reject_with_codes_and_counts(small_book):
    """Ngưỡng THẬT (S1: >= 40 lệnh, >= 5/8 tài sản có lãi...): mọi alpha hoặc qua đúng điều kiện hoặc bị loại kèm mã + câu tiếng Việt."""
    res = _run("fr-test-strict", until="S2_antiluck")
    store = RunStore(res["run_dir"], read_only=True)
    try:
        for a, _, m, _ in store.iter_stage_metrics("S1_backtest"):
            al = store.get_alpha(a)
            ok, code, msg = gates.evaluate_s1(m)
            assert (al["rejected_stage"] is None) == ok and al["reject_code"] == code and al["reject_msg"] == msg
            assert al["stage_reached"] == "S1_backtest" or (ok and al["stage_reached"] == "S2_antiluck")
        c = {x["stage"]: x for x in store.stage_counts()}
        assert c["S1_backtest"]["passed"] + c["S1_backtest"]["rejected"] == 3
        reasons = {r["code"] for r in fstats.stage_stats(store, "S1_backtest")["reject_reasons"]}
        assert reasons <= {"S1.ret_nonpositive", "S1.mdd", "S1.min_trades", "S1.symbols_positive"}
    finally:
        store.close()


# ─── Resume ─────────────────────────────────────────────────────────────────
def _dump(run_dir):
    import sqlite3
    con = sqlite3.connect(os.path.join(run_dir, "results.sqlite"))
    out = {"alphas": con.execute("SELECT * FROM alphas ORDER BY alpha_id").fetchall(),
           "stage_metrics": con.execute("SELECT * FROM stage_metrics ORDER BY alpha_id, stage").fetchall(),
           "kv": con.execute("SELECT * FROM kv ORDER BY key").fetchall()}
    con.close()
    for kind in ("trades", "daily"):
        rows = []
        for st in sorted(os.listdir(os.path.join(run_dir, kind))) if os.path.isdir(os.path.join(run_dir, kind)) else []:
            for fn in sorted(os.listdir(os.path.join(run_dir, kind, st))):
                rows += pq.read_table(os.path.join(run_dir, kind, st, fn)).to_pylist()
        out[kind] = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True))
    return out


def test_resume_after_crash_is_identical(small_book, lenient, monkeypatch, tmp_path):
    from backend.optimize.funnel import orchestrator as orch
    monkeypatch.setitem(orch.FLUSH_N, "S1_backtest", 1)      # mỗi alpha một lô -> sập giữa chừng thật sự
    ref = _run("fr-test-ref", until="S2_antiluck")
    assert ref["status"] == "done"
    monkeypatch.setenv("NORA_TEST_FUNNEL_FAIL_AFTER_COMMITS", "2")
    with pytest.raises(RuntimeError, match="mô phỏng sập"):
        _run("fr-test-kill", until="S2_antiluck")
    kill_dir = os.path.join(orch.funnel_root(), "fr-test-kill")
    part = RunStore(kill_dir, read_only=True)
    try:
        assert 0 < sum(1 for _ in part.iter_stage_metrics("S1_backtest")) < 3     # dở dang thật
    finally:
        part.close()
    assert json.load(open(os.path.join(kill_dir, "run.json")))["status"] == "failed"
    # file parquet mồ côi (lô đã ghi file nhưng chưa commit) phải bị dọn khi mở lại
    orphan = os.path.join(kill_dir, "daily", "S1_backtest", "part-000099.parquet")
    open(orphan, "wb").write(b"junk")
    monkeypatch.delenv("NORA_TEST_FUNNEL_FAIL_AFTER_COMMITS")
    res = _run("fr-test-kill", until="S2_antiluck")
    assert res["status"] == "done" and not os.path.exists(orphan)
    a, b = _dump(ref["run_dir"]), _dump(res["run_dir"])
    assert a["alphas"] == b["alphas"] and a["stage_metrics"] == b["stage_metrics"] and a["kv"] == b["kv"]
    assert a["trades"] == b["trades"] and a["daily"] == b["daily"] and len(a["daily"]) == 3
    assert [x["done"] for x in ref["counts"]] == [x["done"] for x in res["counts"]]
    # chạy tiếp lượt đã xong = không làm lại gì
    again = _run("fr-test-kill", until="S2_antiluck")
    assert _dump(again["run_dir"])["stage_metrics"] == b["stage_metrics"]


# ─── API tạo lượt ───────────────────────────────────────────────────────────
class FakePopen:
    calls = []

    def __init__(self, cmd, **kw):
        FakePopen.calls.append((cmd, kw))
        self.pid = 2 ** 22 + 54321
        self.returncode = None

    def wait(self):
        return 0


def test_api_post_run_launches_job_and_writes_queued_stub(small_book, client, monkeypatch):
    from backend.api.jobs import batch as batch_jobs
    FakePopen.calls = []
    monkeypatch.setattr(batch_jobs.subprocess, "Popen", FakePopen)
    base = "/api/studio/funnel"
    r = client.post(f"{base}/runs", json={"strategies": ["t_long"], "n_per_strategy": 5, "seed": 3, "windows": {"start": "2025-01-01"}})
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j) == {"run_id", "job_id"} and j["run_id"].startswith("fr-")
    kind, p = launched(FakePopen.calls[0])
    assert FakePopen.calls[0][0][0].endswith("run_limited.sh") and kind == "funnel_run"
    assert p["run_id"] == j["run_id"] and p["n_per_strategy"] == 5
    assert p["strategies"] == ["t_long"] and p["windows"] == {"start": "2025-01-01"}
    queued = [x for x in client.get(f"{base}/runs").json()["runs"] if x["run_id"] == j["run_id"]][0]
    assert queued["job_id"] == j["job_id"] and queued["strategies"] == ["t_long"] and queued["total_alphas"] == 3
    from backend.api.routers import funnel as fr
    stub = json.load(open(os.path.join(fr.funnel_root(), j["run_id"], "run.json"), encoding="utf-8"))
    assert stub["status"] == "queued" and stub["config"]["seed"] == 3
    jobs = batch_jobs.list_jobs(5, "funnel_run")
    assert any(x["id"] == j["job_id"] for x in jobs)
    assert client.post(f"{base}/runs", json={"strategies": ["t_long"]}).status_code == 422                       # thiếu n_per_strategy / full_grid
    assert client.post(f"{base}/runs", json={"strategies": ["t_long"], "n_per_strategy": 2, "full_grid": True}).status_code == 422
    assert client.post(f"{base}/runs", json={"strategies": ["khong_co"], "n_per_strategy": 2}).status_code == 422
    monkeypatch.setattr(fr, "LARGE_ALPHAS", 2)
    assert client.post(f"{base}/runs", json={"strategies": ["t_long"], "n_per_strategy": 3}).status_code == 422   # > ngưỡng lớn, không force_large
    assert client.post(f"{base}/runs", json={"strategies": ["t_long"], "n_per_strategy": 3, "force_large": True}).status_code == 200
    assert launched(FakePopen.calls[-1])[1]["force_large"] is True
    monkeypatch.setattr(fr, "MAX_ALPHAS", 2)
    assert client.post(f"{base}/runs", json={"strategies": ["t_long"], "n_per_strategy": 3, "force_large": True}).status_code == 422   # trần cứng
    assert client.post(f"{base}/runs", json={"strategies": ["t_long"], "n_per_strategy": 2, "windows": {"foo": "2025-01-01"}}).status_code == 422
    est = client.get(f"{base}/estimate", params={"strategies": "t_long", "n_per_strategy": 100, "workers": 4}).json()
    assert est["total_alphas"] == 3 and est["s1_eta_s"] == pytest.approx(3 * est["sec_per_backtest"] / 4, abs=0.1)


def test_pool_mode_matches_serial_with_shared_data(small_book, lenient):
    """Chạy bằng pool 2 worker + dữ liệu dùng chung mmap cho KẾT QUẢ y hệt chạy tuần tự (S1..S3), và dọn _shared khi xong."""
    from backend.optimize.funnel import orchestrator as orch
    ser = _run("fr-test-serial", until="S3_wfa")
    par = orch.run_funnel(_cfg(), run_id="fr-test-pool", workers=2, until="S3_wfa", log=lambda s: None)
    a, b = _dump(ser["run_dir"]), _dump(par["run_dir"])
    assert a["alphas"] == b["alphas"] and a["stage_metrics"] == b["stage_metrics"] and a["trades"] == b["trades"] and a["daily"] == b["daily"]
    assert len(b["trades"]) > 0 and not os.path.exists(os.path.join(par["run_dir"], "_shared"))


def test_funnel_job_kind_registered_in_batch_with_label():
    from backend.api.jobs import batch
    assert batch.KINDS["funnel_run"]["module"] == "backend.optimize.funnel.run"
    lab = batch.job_label("funnel_run", {"strategies": ["trend_long", "breakout_4h_long"], "n_per_strategy": 40, "symbols": ["BTC@perp"]})
    assert lab == "Phễu · trend_long, breakout_4h_long · n=40/chiến lược · BTC"
    assert batch.job_label("funnel_run", {"resume": "fr-x"}) == "Phễu · chạy tiếp fr-x"


def test_s1_grouped_run_many_equals_individual_runs(small_book):
    """S1 theo nhóm (cùng tín hiệu, nhiều bộ tham số vị thế -> run_many) phải TRÙNG TỪNG BIT với chạy từng alpha riêng."""
    from backend.optimize.funnel import evaluate as ev
    start, end = T0 + 3 * 86_400_000, T0 + 20 * 86_400_000
    params = [{"sig.lo": 40, "stop_loss_rate": sl, "take_profit_rate": tp, "timeout": to}
              for sl, tp, to in ((2.0, 2.0, 720), (1.0, 3.0, 0), (3.0, 1.5, 1440), (0.8, 0.8, 360))]
    jobs = [{**ev.base_job("t_long", p, (start, end), "level", False, 0.5, [f"{s}@perp" for s in SYMS], None), "trades": True} for p in params]
    assert len({ev.signal_key(j) for j in jobs}) == 1
    other = {**jobs[0], "params": {**params[0], "sig.lo": 35}}
    assert ev.signal_key(other) != ev.signal_key(jobs[0])                    # khác tín hiệu -> khác nhóm
    grouped = ev.w_backtest_group({"jobs": jobs})
    single = [ev.w_backtest(j) for j in jobs]
    assert len(grouped) == len(single) == 4 and any(g["metrics"]["trades"] for g in grouped)
    for g, s in zip(grouped, single):
        assert json.dumps(g, sort_keys=True, default=str) == json.dumps(s, sort_keys=True, default=str)


def test_schema_space_factored_sampling_deterministic_unique_grouped():
    """space=schema: lưới rời rạc từ params_schema; lấy mẫu phân tầng tất định, không lặp, mỗi bộ tín hiệu có PER_SIGNAL bộ vị thế."""
    import importlib.util
    from backend.core.params.modes import schema_space
    from backend.optimize.funnel import generate as gen
    # bản riêng của module sổ chiến lược (fixture phạm vi module khác đang thay CANDIDATES bằng chiến lược test)
    path = os.path.join(os.path.dirname(__file__), "..", "backend", "core", "strategy", "book.py")
    spec = importlib.util.spec_from_file_location("book_fresh_for_test", path)
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    cand = next(c for c in fresh.CANDIDATES if c["id"] == "trend_long")
    sp = schema_space(cand)
    assert "risk_per_trade_pct" not in sp and sp["sig.trend_tf"] == cand["params_schema"]["sig.trend_tf"]["choices"]
    assert gen.grid_size(sp) > 10 ** 20
    a = list(gen.iter_params_factored(sp, 100, 3))
    assert a == list(gen.iter_params_factored(sp, 100, 3)) and len({gen.canonical_params(p) for p in a}) == 100
    sig = lambda p: tuple((k, v) for k, v in sorted(p.items()) if k.startswith("sig.") or k in gen.SIGNAL_POSITION_KEYS)  # noqa: E731
    groups = {}
    for p in a:
        groups.setdefault(sig(p), []).append(p)
    assert len(groups) == 100 // gen.PER_SIGNAL and all(len(v) == gen.PER_SIGNAL for v in groups.values())
    valid = [p for p in a if gen.validate_alpha(cand, p, "schema") is None]
    assert len(valid) >= 80                                           # phần lớn hợp lệ; EMA nhanh >= chậm / DCA quá ngân sách bị loại ở S0


def test_sigterm_right_after_commit_exits_cleanly(tmp_path):
    """SIGTERM tới ngay SAU khi COMMIT xong (handler ném SystemExit ở dòng COMMIT): phải thoát bằng SystemExit (huỷ gọn),
    không bị che bởi lỗi 'cannot rollback - no transaction is active'; lô đã commit vẫn còn (resume không mất việc)."""
    from backend.optimize.funnel.storage import RunStore, StageResult
    store = RunStore(str(tmp_path / "run"))
    store.add_alphas([{"alpha_id": "a1", "strategy": "t_long", "params": {"x": 1}, "ord": 0}])
    real = store._con

    class Con:
        def __init__(self, c):
            self.c = c

        def __getattr__(self, name):
            return getattr(self.c, name)

        def execute(self, sql, *a):
            out = self.c.execute(sql, *a)
            if sql == "COMMIT":
                raise SystemExit(143)
            return out

    store._con = Con(real)
    with pytest.raises(SystemExit):
        store.commit_results([StageResult("a1", "S1_backtest", {"ret_pct": 1.0, "mdd_pct": 1.0}, True)])
    store._con = real
    assert dict(store.metrics_of(["a1"], "S1_backtest"))["a1"]["ret_pct"] == 1.0
    store.close()



def test_regime_both_variants_are_separate_trials_and_learn_on_train(small_book, lenient, monkeypatch):
    """P2.7: regime="both" -> mỗi bộ tham số thành 2 alpha (off + learn) -> DSR/PBO đếm N = tổng số biến thể. Biến thể learn học bảng regime
    trên cửa sổ HỌC: S1 = chính dev1 (trong mẫu, đã là một lần thử), WFA OOS = train của fold, holdout = toàn bộ trước holdout."""
    from backend.optimize.funnel import evaluate as bt
    from backend.optimize.funnel import orchestrator as orch
    seen = []
    orig = bt.learned_regime

    def spy(job):
        seen.append((tuple(job["window"]), tuple(job.get("learn_window") or job["window"])))
        return orig(job)
    monkeypatch.setattr(bt, "learned_regime", spy)
    res = orch.run_funnel(_cfg(regime="both"), run_id="fr-test-regime", workers=0, log=lambda s: None, until="S3_wfa")
    store = RunStore(res["run_dir"], read_only=True)
    try:
        c = {x["stage"]: x for x in store.stage_counts()}
        assert c["S0_generate"]["passed"] + c["S0_generate"]["rejected"] == 6
        learn = [a for a, _, m, _ in store.iter_stage_metrics("S1_backtest") if store.get_alpha(a)["params"].get("regime") == "learn"]
        off = [a for a, _, m, _ in store.iter_stage_metrics("S1_backtest") if "regime" not in store.get_alpha(a)["params"]]
        assert len(learn) == 3 and len(off) == 3
        m1 = store.metrics_of(learn, "S1_backtest")
        assert all(isinstance(m1[a]["regime_blocked"], list) for a in learn)
        assert all("regime_blocked" not in m for m in store.metrics_of(off, "S1_backtest").values())
        m2 = store.metrics_of(learn + off, "S2_antiluck")
        assert {m["n_trials"] for m in m2.values()} == {6}                      # cả 2 biến thể là lần thử
        windows = store.read_run()["windows_ms"]
    finally:
        store.close()
    folds = {tuple(f["test"]): tuple(f["train"]) for f in bt.fold_job_plan(orch.wfa_folds(windows, 5, 4))}
    oos = [(w, lw) for w, lw in seen if w in folds]
    assert oos and all(lw == folds[w] and lw[1] <= w[0] for w, lw in oos)    # OOS chỉ học trên train của fold
