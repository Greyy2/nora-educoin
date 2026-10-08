"""Phễu kiểm duyệt alpha (backend/optimize/funnel): ngưỡng, DSR, PBO, lân cận, tìm s, kho/resume, thống kê, API, lệnh tính lại.

Dữ liệu giả lập 3 tài sản perp (như test_strategy_book, không mạng); phễu chạy TUẦN TỰ trong tiến trình (workers=0). Ngưỡng được nới bằng monkeypatch
CHỈ TRONG TEST (để alpha ngẫu nhiên đi hết các tầng) — phần ngưỡng thật được kiểm riêng bằng hàm evaluate_*.
"""
import json
import math
import os
import sqlite3

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from job_modules import launched
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.crawl.store import save_resampled_dataset
from backend.carlo import carlo
from backend.wfa import wfa as wfa_mod
from backend.optimize.funnel import stages as gates, stages as sizing, stages as fstats
from backend.optimize.search.generate import alpha_id_of, iter_params, validate_alpha
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
    from backend.optimize.book import build as sb
    from backend.alpha.compile import cond, f, tree_p
    cands = [{"id": "t_long", "family": "x", "side": "LONG", "description": "test",
              "tree": cond((f("15m", "rsi_14"), "<", tree_p("lo", 40))), "position": {},
              "space": {"sig.lo": [35, 40, 45], "stop_loss_rate": [2.0], "take_profit_rate": [2.0], "timeout": [720]}}]
    monkeypatch.setattr(sb, "UNIVERSE", list(SYMS))
    monkeypatch.setattr(sb, "CANDIDATES", cands)
    return sb


@pytest.fixture
def lenient(monkeypatch):
    for k, v in dict(S1_MIN_RET_PCT=-1000.0, S1_MAX_MDD_PCT=1000.0, S1_MIN_TRADES=1, S1_MIN_SYMBOLS_POSITIVE=0, S2_DSR_TOP_FRAC=1.0,
                     S2_NEIGHBOUR_MIN_PROFIT_RATIO=0.0, S2_PBO_MAX=1.0, S3_MIN_FOLDS=2, S3_MIN_TRADED_FOLDS=0, S3_MIN_FOLD_T=-1e9, S3_MIN_EX_BEST_FOLD_PCT=-1e9,
                     S3_MIN_COMPOUNDED_OOS_PCT=-1000.0, S3_MAX_FOLD_MDD_PCT=1000.0, S3_MIN_AVG_IS_RET_PCT=-1000.0,
                     S4_MIN_SIMULATIONS=200, S4_MAX_RUIN_PCT=100.0, S4_STRESS_MAX_MDD_PCT=1000.0, S4_MIN_DAYS=5,
                     S6_MIN_RET_PCT=-1000.0, S6_MAX_MDD_PCT=1000.0).items():
        monkeypatch.setattr(gates, k, v)


def _cfg(**kw):
    from backend.optimize.funnel.stages import FunnelConfig
    return FunnelConfig(strategies=["t_long"], n_per_strategy=3, seed=7, train_days=5, test_days=4, **kw)


def _run(run_id, **kw):
    from backend.optimize.funnel import stages as orch
    return orch.run_funnel(_cfg(), run_id=run_id, workers=0, log=lambda s: None, **kw)


# ─── Ngưỡng + hàm thuần ─────────────────────────────────────────────────────
def test_gate_constants_match_existing_gates():
    from backend.carlo import carlo as mc
    from backend.core.params import BASE_RISK_PER_TRADE_PCT
    from backend.optimize.book.build import GATES
    from backend.wfa import wfa as pw
    assert gates.S1_MIN_TRADES == GATES["min_trades"] and gates.S1_MIN_SYMBOLS_POSITIVE == GATES["min_symbols_positive"]
    assert gates.S1_MAX_MDD_PCT == GATES["max_mdd_pct"] and gates.BASE_RISK_PER_TRADE_PCT == BASE_RISK_PER_TRADE_PCT
    assert gates.S3_MIN_FOLDS == pw.MIN_FOLDS and gates.S3_MIN_FOLD_T == pw.MIN_FOLD_T
    assert gates.S3_MIN_EX_BEST_FOLD_PCT == pw.MIN_EX_BEST_FOLD_PCT and gates.S3_MIN_TRADED_FOLDS == pw.MIN_TRADED_FOLDS
    assert gates.S3_MAX_FOLD_MDD_PCT == pw.MAX_FOLD_MDD_PCT and gates.S3_MIN_AVG_IS_RET_PCT == pw.MIN_AVG_IS_RET_PCT
    assert (gates.S3_TRAIN_DAYS, gates.S3_TEST_DAYS) == (120, 30)
    assert gates.S4_MIN_SIMULATIONS == mc.MC_MIN_SIMULATIONS == 10_000 and gates.S4_MAX_RUIN_PCT == mc.MC_MAX_RUIN_PCT == 5.0
    assert gates.S4_STRESS_MAX_MDD_PCT == mc.STRESS_MAX_MDD_PCT == 50.0 and gates.S4_RUIN_THRESHOLD_PCT == mc.MC_RUIN_THRESHOLD_PCT
    assert (gates.S2_DSR_TOP_FRAC, gates.S2_DSR_TOP_MIN, gates.S2_NEIGHBOUR_MIN_PROFIT_RATIO, gates.S2_PBO_MAX, gates.S2_PBO_BLOCKS) == (0.05, 3, 0.60, 0.5, 16)
    assert (gates.S5_S_MIN, gates.S5_S_MAX, gates.S5_TOLERANCE) == (0.2, 3.0, 0.01)
    assert gates.STAGES[0] == "S0_generate" and gates.STAGES[-1] == "FINAL" and len(gates.STAGES) == 7
    assert "S2_antiluck" not in gates.STAGES and gates.LEGACY_STAGE not in gates.STAGE_IDX      # không còn tầng chống ăn may riêng
    assert [gates.STAGE_IDX[x] for x in gates.STAGES] == [0, 1, 3, 4, 5, 6, 7] and gates.ALL_STAGE_IDX[gates.LEGACY_STAGE] == 2   # khe số 2: khớp kho cũ


def test_windows_match_build_strategy_book(market):
    from backend.optimize.funnel.stages import compute_windows
    import importlib
    bsb = importlib.import_module("backend.optimize.book.build")
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
    assert gates.evaluate_dsr(0.3, 0.3)[0]                                       # đúng ngưỡng top: qua (DSR thấp vẫn đi tiếp nếu ở top)
    assert gates.evaluate_dsr(0.29, 0.3)[1] == "S2.dsr_rank"
    assert gates.evaluate_dsr(0.5, None)[1] == "S2.dsr_rank"                     # chiến lược không có alpha qua S1
    assert gates.evaluate_neighbour(0.8)[0] and gates.evaluate_neighbour(None)[0]
    assert gates.evaluate_neighbour(0.5)[1] == "S2.neighbor"
    assert gates.dsr_cut([0.1 * i for i in range(100)]) == 0.1 * 95              # top 5% của 100 = 5 alpha -> giá trị thứ 5
    assert gates.dsr_cut([0.2, 0.9]) == 0.2 and gates.dsr_cut([]) is None        # ít hơn 3 alpha: lấy hết
    s3 = {"folds": 8, "traded_folds": 8, "positive_ratio": 0.75, "compounded_oos_ret_pct": 3.0, "fold_t": 1.4, "oos_ex_best_pct": 0.5,
          "worst_fold_mdd": 12.0, "is_ret_avg": 4.0}
    assert gates.evaluate_s3(s3)[0]
    assert gates.evaluate_s3({**s3, "folds": 4})[1] == "S3.folds"
    assert gates.evaluate_s3({**s3, "positive_ratio": 0.4})[0]                  # tỉ lệ fold lãi không còn là cổng
    assert gates.evaluate_s3({**s3, "traded_folds": 2})[1] == "S3.traded_folds"
    assert gates.evaluate_s3({**s3, "fold_t": 0.8})[2] == "S3.fold_t: Lãi theo fold không đủ ý nghĩa (t < 1) (t = 0.8 < 1)"
    assert gates.evaluate_s3({**s3, "oos_ex_best_pct": -2.5})[1] == "S3.ex_best"
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
    sr0 = carlo.expected_max_sr(10, 0.0004)
    assert sr0 == pytest.approx(0.031492, abs=2e-6)
    d = carlo.deflated_sharpe(0.1, 252, -0.5, 5.0, 10, 0.0004)
    z = (0.1 - 0.0314920) * math.sqrt(251) / math.sqrt(1.06)
    assert z == pytest.approx(1.0542, abs=2e-4)
    expect = 0.5 * math.erfc(-z / math.sqrt(2))
    assert d["dsr"] == pytest.approx(expect, abs=1e-4) and d["dsr"] == pytest.approx(0.8541, abs=2e-3)
    # một lần thử duy nhất (N = 1) hoặc không có phương sai: SR0 = 0 -> DSR = xác suất SR > 0
    assert carlo.expected_max_sr(1, 0.01) == 0.0
    assert carlo.deflated_sharpe(0.1, 252, 0.0, 3.0, 1, 0.0)["dsr"] == pytest.approx(0.94299, abs=1e-4)   # Φ(0.1·√251) = Φ(1.5843)
    # alpha kém hơn kỳ vọng SR lớn nhất -> DSR < 0,5
    assert carlo.deflated_sharpe(0.02, 252, 0.0, 3.0, 1000, 0.0004)["dsr"] < 0.5


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
    po, pr = wfa_mod.pbo_cscv(over), wfa_mod.pbo_cscv(rob)
    assert po["n_splits"] == 12870 and po["pbo"] > 0.6
    assert pr["pbo"] < 0.1
    assert wfa_mod.pbo_cscv(over[:10])["pbo"] is None   # không đủ ngày


def test_neighbours_and_alpha_ids():
    space = {"a": [1, 2, 3], "b": [10], "c": [0.5, 1.5]}
    nb = wfa_mod.neighbours(space, {"a": 2, "b": 10, "c": 0.5})
    assert sorted((tuple(sorted(n.items()))) for n in nb) == sorted([(("a", 1), ("b", 10), ("c", 0.5)), (("a", 3), ("b", 10), ("c", 0.5)),
                                                                     (("a", 2), ("b", 10), ("c", 1.5))])
    assert wfa_mod.neighbours(space, {"a": 1, "b": 10, "c": 1.5}) == [{"a": 2, "b": 10, "c": 1.5}, {"a": 1, "b": 10, "c": 0.5}]
    assert alpha_id_of("s", {"a": 1, "b": 2}) == alpha_id_of("s", {"b": 2, "a": 1}) != alpha_id_of("s2", {"a": 1, "b": 2})
    a = list(iter_params(space, 4, 7))
    assert a == list(iter_params(space, 4, 7)) and len({alpha_id_of("s", p) for p in a}) == 4
    assert len(list(iter_params(space, None, 7, full_grid=True))) == 6 == len(list(iter_params(space, 99, 7)))


def test_validate_alpha_rejects_bad_params():
    from backend.optimize.book.build import CANDIDATES
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
    s, steps = sizing.search_scale(check, hi=1.0)
    assert s == 0.62 and steps[0]["s"] == 1.0 and not steps[0]["passed"] and steps[1]["s"] == 0.2
    assert all(0.2 <= x <= 1.0 for x in calls) and abs(max(x["s"] for x in steps if x["passed"]) - 0.63) <= 0.01
    assert sizing.search_scale(lambda s: {"passed": True})[0] == 3.0                # trần mặc định S5_S_MAX
    assert 1.69 <= sizing.search_scale(lambda s: {"passed": s <= 1.7})[0] <= 1.7
    assert sizing.search_scale(lambda s: {"passed": False})[0] is None            # s < 0,2 -> loại
    assert sizing.search_scale(lambda s: {"passed": s <= 0.2})[0] == 0.2
    # xác nhận thật trượt ở s đầu -> hạ từng bước 0,05 tới khi qua
    s2, att = sizing.confirm_with_stepdown(0.62, lambda s: {"passed": s <= 0.52})
    assert s2 == 0.52 and [round(a["s"], 2) for a in att] == [0.62, 0.57, 0.52]
    assert sizing.confirm_with_stepdown(0.3, lambda s: {"passed": False})[0] is None
    s3, att3 = sizing.confirm_with_stepdown(3.0, lambda s: {"passed": s <= 1.5})   # s > 1: hạ 15% mỗi bước, không dưới 1 trước khi trừ 0,05
    assert [a["s"] for a in att3] == [3.0, 2.55, 2.17, 1.84, 1.56, 1.33] and s3 == 1.33
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
    assert set(hin) == {"bins", "n", "n_missing", "p5", "p50", "p95"} and hin["n_missing"] == 0
    assert fstats.histogram(np.array([]), None)["bins"] == []


# ─── Chạy phễu trên dữ liệu giả lập ─────────────────────────────────────────
@pytest.fixture(scope="module")
def full_run(market):
    """Một lượt đầy đủ S0 → FINAL (ngưỡng nới) dùng chung cho các test đọc kết quả."""
    mp = pytest.MonkeyPatch()
    from backend.optimize.book import build as sb
    from backend.alpha.compile import cond, f, tree_p
    cands = [{"id": "t_long", "family": "x", "side": "LONG", "description": "test",
              "tree": cond((f("15m", "rsi_14"), "<", tree_p("lo", 40))), "position": {},
              "space": {"sig.lo": [35, 40, 45], "stop_loss_rate": [2.0], "take_profit_rate": [2.0], "timeout": [720]}}]
    mp.setattr(sb, "UNIVERSE", list(SYMS))
    mp.setattr(sb, "CANDIDATES", cands)
    for k, v in dict(S1_MIN_RET_PCT=-1000.0, S1_MAX_MDD_PCT=1000.0, S1_MIN_TRADES=1, S1_MIN_SYMBOLS_POSITIVE=0, S2_DSR_TOP_FRAC=1.0,
                     S2_NEIGHBOUR_MIN_PROFIT_RATIO=0.0, S2_PBO_MAX=1.0, S3_MIN_FOLDS=2, S3_MIN_TRADED_FOLDS=0, S3_MIN_FOLD_T=-1e9, S3_MIN_EX_BEST_FOLD_PCT=-1e9,
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
            assert fa["stage_reached"] == "FINAL" and fa["rejected_stage"] is None and gates.S5_S_MIN <= fa["final_scale"] <= gates.S5_S_MAX
            a = fa["alpha_id"]
            sm = store.alpha_metrics(a)
            assert set(sm) == set(gates.STAGES[1:])     # có số đo ở mọi tầng S1..FINAL
            assert {"folds", "folds_profitable", "positive_ratio", "worst_fold_mdd", "is_ret_avg"} <= set(sm["S3_wfa"])
            assert {"neighbor_ratio", "neighbor_n", "pbo_strategy", "pbo_flag"} <= set(sm["S3_wfa"])      # lân cận + PBO chạy trong S3
            assert {"p_mdd_ge_30", "stress_max_mdd", "simulations", "mdd_p95"} <= set(sm["S4_montecarlo"])
            assert {"dsr", "dsr_cut", "n_trials", "n_trials_raw"} <= set(sm["S4_montecarlo"])             # DSR chạy trong S4
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
    assert run["config"]["strategies"] == ["t_long"] and run["config"]["data_sha256"] and run["config"]["thresholds"]["S2_DSR_TOP_FRAC"] == 1.0
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
    from backend.optimize.funnel.stages import recompute_s1
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
    from backend.routes import optimize
    app = FastAPI()
    app.include_router(optimize.funnel_router)
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
    assert c["S1_backtest"]["rejected"] == 3 and c["S1_backtest"]["passed"] == 0 and c["S3_wfa"]["input"] == 0
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
    from backend.routes import optimize
    from backend.optimize.funnel.stages import cache_path, recompute_s1
    from backend.optimize.funnel.storage import atomic_write_json
    calls = []
    monkeypatch.setattr(optimize, "_run_recompute_subprocess", lambda run_id, aid: (calls.append(aid), atomic_write_json(cache_path(res["run_dir"], aid), recompute_s1(res["run_dir"], aid))))
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
    res = _run("fr-test-strict", until="S1_backtest")
    store = RunStore(res["run_dir"], read_only=True)
    try:
        for a, _, m, _ in store.iter_stage_metrics("S1_backtest"):
            al = store.get_alpha(a)
            ok, code, msg = gates.evaluate_s1(m)
            assert (al["rejected_stage"] is None) == ok and al["reject_code"] == code and al["reject_msg"] == msg
            assert al["stage_reached"] == "S1_backtest"
        c = {x["stage"]: x for x in store.stage_counts()}
        assert c["S1_backtest"]["passed"] + c["S1_backtest"]["rejected"] == 3
        reasons = {r["code"] for r in fstats.stage_stats(store, "S1_backtest")["reject_reasons"]}
        assert reasons <= {"S1.ret_nonpositive", "S1.mdd", "S1.min_trades", "S1.symbols_positive"}
    finally:
        store.close()


# ─── Resume ─────────────────────────────────────────────────────────────────
def _dump(run_dir):
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
    from backend.optimize.funnel import stages as orch
    monkeypatch.setitem(orch.FLUSH_N, "S1_backtest", 1)      # mỗi alpha một lô -> sập giữa chừng thật sự
    ref = _run("fr-test-ref", until="S3_wfa")
    assert ref["status"] == "done"
    monkeypatch.setenv("NORA_TEST_FUNNEL_FAIL_AFTER_COMMITS", "2")
    with pytest.raises(RuntimeError, match="mô phỏng sập"):
        _run("fr-test-kill", until="S3_wfa")
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
    res = _run("fr-test-kill", until="S3_wfa")
    assert res["status"] == "done" and not os.path.exists(orphan)
    a, b = _dump(ref["run_dir"]), _dump(res["run_dir"])
    assert a["alphas"] == b["alphas"] and a["stage_metrics"] == b["stage_metrics"] and a["kv"] == b["kv"]
    assert a["trades"] == b["trades"] and a["daily"] == b["daily"] and len(a["daily"]) >= 3
    assert [x["done"] for x in ref["counts"]] == [x["done"] for x in res["counts"]]
    # chạy tiếp lượt đã xong = không làm lại gì
    again = _run("fr-test-kill", until="S3_wfa")
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
    from backend.optimize.process import process as batch_jobs
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
    from backend.routes import optimize
    stub = json.load(open(os.path.join(optimize.funnel_root(), j["run_id"], "run.json"), encoding="utf-8"))
    assert stub["status"] == "queued" and stub["config"]["seed"] == 3
    jobs = batch_jobs.list_jobs(5, "funnel_run")
    assert any(x["id"] == j["job_id"] for x in jobs)
    assert client.post(f"{base}/runs", json={"strategies": ["t_long"]}).status_code == 422                       # thiếu n_per_strategy / full_grid
    assert client.post(f"{base}/runs", json={"strategies": ["t_long"], "n_per_strategy": 2, "full_grid": True}).status_code == 422
    assert client.post(f"{base}/runs", json={"strategies": ["khong_co"], "n_per_strategy": 2}).status_code == 422
    monkeypatch.setattr(optimize, "LARGE_ALPHAS", 2)
    assert client.post(f"{base}/runs", json={"strategies": ["t_long"], "n_per_strategy": 3}).status_code == 422   # > ngưỡng lớn, không force_large
    assert client.post(f"{base}/runs", json={"strategies": ["t_long"], "n_per_strategy": 3, "force_large": True}).status_code == 200
    assert launched(FakePopen.calls[-1])[1]["force_large"] is True
    monkeypatch.setattr(optimize, "MAX_ALPHAS", 2)
    assert client.post(f"{base}/runs", json={"strategies": ["t_long"], "n_per_strategy": 3, "force_large": True}).status_code == 422   # trần cứng
    assert client.post(f"{base}/runs", json={"strategies": ["t_long"], "n_per_strategy": 2, "windows": {"foo": "2025-01-01"}}).status_code == 422
    est = client.get(f"{base}/estimate", params={"strategies": "t_long", "n_per_strategy": 100, "workers": 4}).json()
    # P9.13: chưa có lượt đo thật nào cùng khung -> KHÔNG có hằng số "đo sẵn": null + lý do (giao diện hiện "chưa có số đo")
    assert est["total_alphas"] == 3 and est["workers"] == 4 and est["workers_source"] == "client"
    assert est["sec_per_backtest"] is None and est["s1_eta_s"] is None and est["measure"]["n_runs"] == 0 and "chưa có lượt" in est["measure"]["reason"]
    # có lượt đã xong cùng khung 15m: giây/backtest = wall_s × workers / input (trung vị), ETA = alpha × giây / workers
    root = optimize.funnel_root()
    for rid, wall, n, w, fin in (("fr-ref-a", 100.0, 1000, 4, 2.0), ("fr-ref-b", 300.0, 1000, 4, 3.0), ("fr-ref-c", 50.0, 500, 2, 1.0)):
        os.makedirs(os.path.join(root, rid), exist_ok=True)
        with open(os.path.join(root, rid, "run.json"), "w") as fh:
            json.dump({"run_id": rid, "status": "done", "finished": fin, "workers": w, "config": {"timeframe": "15m", "regime": "off"},
                       "stages": {"S1_backtest": {"status": "done", "wall_s": wall, "input": n}}}, fh)
    os.makedirs(os.path.join(root, "fr-ref-1h"), exist_ok=True)         # khung khác: không dùng
    with open(os.path.join(root, "fr-ref-1h", "run.json"), "w") as fh:
        json.dump({"run_id": "fr-ref-1h", "status": "done", "finished": 9.0, "workers": 1, "config": {"timeframe": "1h", "regime": "off"},
                   "stages": {"S1_backtest": {"status": "done", "wall_s": 9999.0, "input": 10}}}, fh)
    est = client.get(f"{base}/estimate", params={"strategies": "t_long", "n_per_strategy": 100, "workers": 4}).json()
    assert est["measure"]["n_runs"] == 3 and est["sec_per_backtest"] == pytest.approx(0.4)        # trung vị của 0,4 / 1,2 / 0,2
    assert est["s1_eta_s"] == pytest.approx(3 * 0.4 / 4, abs=0.1)
    assert client.get(f"{base}/estimate", params={"strategies": "t_long", "n_per_strategy": 100, "regime": "both"}).json()["sec_per_backtest"] is None
    dflt = client.get(f"{base}/estimate", params={"strategies": "t_long", "n_per_strategy": 100}).json()
    from backend.optimize.process.workers import default_workers
    from backend.optimize.funnel.stages import PER_WORKER_MB
    assert dflt["workers_source"] == "server_default" and dflt["workers"] == default_workers(PER_WORKER_MB) >= 1


def test_pool_mode_matches_serial_with_shared_data(small_book, lenient):
    """Chạy bằng pool 2 worker + dữ liệu dùng chung mmap cho KẾT QUẢ y hệt chạy tuần tự (S1..S3), và dọn _shared khi xong."""
    from backend.optimize.funnel import stages as orch
    ser = _run("fr-test-serial", until="S3_wfa")
    par = orch.run_funnel(_cfg(), run_id="fr-test-pool", workers=2, until="S3_wfa", log=lambda s: None)
    a, b = _dump(ser["run_dir"]), _dump(par["run_dir"])
    assert a["alphas"] == b["alphas"] and a["stage_metrics"] == b["stage_metrics"] and a["trades"] == b["trades"] and a["daily"] == b["daily"]
    assert len(b["trades"]) > 0 and not os.path.exists(os.path.join(par["run_dir"], "_shared"))


def test_funnel_job_kind_registered_in_batch_with_label():
    from backend.optimize.process import process as batch
    assert batch.KINDS["funnel_run"]["module"] == "backend.optimize.funnel.stages" and batch.KINDS["funnel_run"]["func"] == "run_funnel_run"
    lab = batch.job_label("funnel_run", {"strategies": ["trend_long", "breakout_4h_long"], "n_per_strategy": 40, "symbols": ["BTC@perp"]})
    assert lab == "Phễu · trend_long, breakout_4h_long · n=40/chiến lược · BTC"
    assert batch.job_label("funnel_run", {"resume": "fr-x"}) == "Phễu · chạy tiếp fr-x"


def test_s1_grouped_run_many_equals_individual_runs(small_book):
    """S1 theo nhóm (cùng tín hiệu, nhiều bộ tham số vị thế -> run_many) phải TRÙNG TỪNG BIT với chạy từng alpha riêng."""
    from backend.optimize.search import evaluate as ev
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
    from backend.optimize.book.build import schema_space
    from backend.optimize.search import generate as gen
    # bản riêng của module sổ chiến lược (fixture phạm vi module khác đang thay CANDIDATES bằng chiến lược test)
    path = os.path.join(os.path.dirname(__file__), "..", "backend", "optimize", "book", "build.py")
    spec = importlib.util.spec_from_file_location("book_fresh_for_test", path)
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    from legacy_candidates import LEGACY_BY_ID
    cand = LEGACY_BY_ID["trend_long"]
    assert fresh.CANDIDATES                                            # module sổ chiến lược nạp lại được độc lập
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
    from backend.optimize.search import evaluate as bt
    from backend.optimize.funnel import stages as orch
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
        info = store.get_kv("strategy_level:t_long")
        assert info["n_trials_raw"] == 6                                        # cả 2 biến thể là lần thử
        assert 1 <= info["n_trials"] <= 6                                       # N hiệu dụng (gom lần thử tương quan) <= N
        windows = store.read_run()["windows_ms"]
    finally:
        store.close()
    folds = {tuple(f["test"]): tuple(f["train"]) for f in bt.fold_job_plan(orch.wfa_folds(windows, 5, 4))}
    oos = [(w, lw) for w, lw in seen if w in folds]
    assert oos and all(lw == folds[w] and lw[1] <= w[0] for w, lw in oos)    # OOS chỉ học trên train của fold


def test_s3_gate_is_skew_robust(monkeypatch):
    """Cổng S3 03/10: lãi lệch phải (đa số fold lỗ nhẹ, một fold lãi lớn) không bị loại chỉ vì tỉ lệ fold lãi; nhưng phải có t >= 1 và không
    dựa vào đúng một fold; fold 0 lệnh trung tính."""
    from backend.wfa.wfa import fold_stats
    # ngưỡng thật (fixture full_run nới ngưỡng ở phạm vi module — đặt lại cho test này)
    for k, v in dict(S3_MIN_FOLDS=5, S3_MIN_TRADED_FOLDS=3, S3_MIN_FOLD_T=1.0, S3_MIN_EX_BEST_FOLD_PCT=-2.0, S3_MIN_COMPOUNDED_OOS_PCT=0.0,
                     S3_MAX_FOLD_MDD_PCT=30.0, S3_MIN_AVG_IS_RET_PCT=0.0).items():
        monkeypatch.setattr(gates, k, v)
    base = {"folds": 10, "worst_fold_mdd": 5.0, "is_ret_avg": 1.0}
    skew = [3.0, -0.3, 2.5, -0.2, 4.0, -0.4, 1.5, -0.1, 2.0, -0.3]           # 50% fold lãi, lãi đều nhiều fold
    fs = fold_stats(skew, [True] * 10)
    assert fs["positive_ratio"] == 0.5 and fs["fold_t"] >= 1.0
    s = {**base, **fs, "compounded_oos_ret_pct": 12.0}
    assert gates.evaluate_s3(s)[0]
    lucky = [-0.5] * 9 + [15.0]                                                # chỉ một fold may mắn
    fl = fold_stats(lucky, [True] * 10)
    v = gates.evaluate_s3({**base, **fl, "compounded_oos_ret_pct": 10.0})
    assert not v[0] and v[1] in ("S3.fold_t", "S3.ex_best")
    assert fl["oos_ex_best_pct"] < -2.0
    quiet = fold_stats([0.0] * 8 + [1.0, 2.0], [False] * 8 + [True, True])  # 8 fold không lệnh: trung tính, nhưng chỉ còn 2 fold có lệnh
    assert quiet["traded_folds"] == 2
    assert gates.evaluate_s3({**base, **quiet, "compounded_oos_ret_pct": 3.0})[1] == "S3.traded_folds"
    assert gates.evaluate_s3({**base, **fs, "compounded_oos_ret_pct": 0.0})[1] == "S3.oos_compound"


def test_effective_trials_clusters_correlated_trials():
    rng = np.random.default_rng(0)
    base = rng.normal(0, 0.01, (300, 3))                                       # 3 nguồn độc lập
    cols = [base[:, i % 3] + rng.normal(0, 0.001, 300) for i in range(30)]   # 30 lần thử = 3 cụm gần trùng
    M = np.column_stack(cols)
    assert carlo.effective_trials(M, 30) == 3
    assert carlo.effective_trials(M, 3000) == 300                          # phóng theo tỉ lệ cụm / mẫu
    indep = rng.normal(0, 0.01, (300, 20))
    assert carlo.effective_trials(indep, 20) == 20
    assert carlo.effective_trials(np.zeros((0, 0)), 50) == 50               # không có mẫu: giữ N (bảo thủ)


def test_funnel_book_publish_checks_wfa_and_scores_holdout(full_run, tmp_path):
    """Xuất bản sổ từ alpha FINAL (optimize/funnel/publish.py): job WFA phải đúng cấu hình + rủi ro + gate qua; holdout chấm một lần;
    registry.write_book ghi book.json (+ testnet/book.json chỉ khi holdout đạt)."""
    from backend.optimize.book import registry as publish
    from backend.optimize.book.registry import write_book
    store = RunStore(full_run["run_dir"], read_only=True)
    try:
        aid = next(a for a, _, _, _ in store.iter_stage_metrics("FINAL"))
        params = {k: v for k, v in store.get_alpha(aid)["params"].items() if k != "regime"}
    finally:
        store.close()
    wfa = {"candidates": [{"id": "t_long", "configs": [params]}], "risk_per_trade_pct": 0.5, "gate": {"passed": True}, "summary": {"n_folds": 5}}
    rep = publish.build_report(full_run["run_dir"], [aid], 0.5, wfa)
    assert [s["id"] for s in rep["book"]["strategies"]] == ["t_long"] and rep["book"]["risk_per_trade_pct"] == 0.5
    h = rep["book"]["final"]["holdout"]
    assert set(h) == {"level", "extreme"} and isinstance(rep["book"]["holdout_pass"], bool)
    assert rep["book"]["holdout_pass"] == (h["level"]["ret_pct"] > 0 and h["extreme"]["ret_pct"] > 0
                                           and h["level"]["mdd_pct"] <= gates.S6_MAX_MDD_PCT and h["extreme"]["mdd_pct"] <= gates.S6_MAX_MDD_PCT)
    paths = write_book(rep, str(tmp_path / "alphas"), source="test")
    book = json.load(open(paths[0], encoding="utf-8"))
    assert book["status"] == ("READY_FOR_TESTNET" if rep["book"]["holdout_pass"] else "HOLDOUT_FAILED")
    assert (len(paths) == 2) == rep["book"]["holdout_pass"]
    for bad in ({**wfa, "risk_per_trade_pct": 1.0}, {**wfa, "gate": {"passed": False}},
                {**wfa, "candidates": [{"id": "t_long", "configs": [{**params, "sig.lo": -1}]}]}):
        with pytest.raises(ValueError):
            publish.build_report(full_run["run_dir"], [aid], 0.5, bad)
    with pytest.raises(ValueError):
        publish.build_report(full_run["run_dir"], [aid, aid], 0.5, wfa)                 # mỗi chiến lược một alpha


def test_funnel_explore_book_accepts_unvalidated_alpha(full_run, tmp_path):
    """Sổ thử nghiệm (explore): alpha qua S1 nhưng chưa FINAL được nhận, không cần WFA; ghi explore/book.json status EXPLORE_DEMO +
    danh sách unvalidated; sổ chính vẫn từ chối alpha đó."""
    from backend.optimize.book import registry as publish
    from backend.optimize.book.registry import EXPLORE_STATUS, write_explore_book
    import shutil
    run_dir = str(tmp_path / "run")
    shutil.copytree(full_run["run_dir"], run_dir)
    con = sqlite3.connect(os.path.join(run_dir, "results.sqlite"))
    aid = con.execute("select alpha_id from alphas where stage_reached = 'FINAL' limit 1").fetchone()[0]
    con.execute("update alphas set stage_reached='S3_wfa', stage_idx=3, rejected_stage='S3_wfa', reject_code='S3.fold_t' where alpha_id=?",
                (aid,))                                                              # giả lập alpha dừng ở S3
    low = con.execute("select alpha_id from alphas where stage_idx < 2 limit 1").fetchone()
    con.commit()
    con.close()
    row = (aid,)
    with pytest.raises(ValueError):
        publish.build_report(run_dir, [row[0]], 0.5, {"gate": {"passed": True}})
    if low is not None:
        with pytest.raises(ValueError):
            publish.build_report(run_dir, [low[0]], 0.5, {}, explore=True)
    rep = publish.build_report(run_dir, [row[0]], 0.5, {}, explore=True)
    assert rep["book"]["explore"] is True and rep["gates"]["wfa_gate"] is None
    paths = write_explore_book(rep, str(tmp_path / "explore"), source="test")
    book = json.load(open(paths[0], encoding="utf-8"))
    assert book["status"] == EXPLORE_STATUS and book["unvalidated"] == [book["strategies"][0]["id"]]


def test_aggregate_wfa_measures_turnover_from_oos_trades():
    """P9.13: S3 ghi vòng quay vốn/ngày đo từ lệnh OOS (danh nghĩa mở / vốn lúc vào lệnh / số ngày) để MC dựng cost_x2; thiếu lệnh -> None + lý do."""
    from backend.optimize.search import evaluate as ev
    H = 3_600_000

    def tr(pnl, notional_margin, lev, eq, t):
        return {"symbol": "BTC@perp", "strategy": "s", "side": "LONG", "enter_time": t, "close_time": t + H, "pnl_usd": pnl, "pnl_pct": pnl / eq * 100 if eq else 0.0,
                "fees_usd": 0.0, "funding_usd": 0.0, "status": "TP", "layers": 1, "mae_pct": 0.0, "margin_usd": notional_margin, "leverage": lev, "entry_equity": eq}

    def fold(i, trades):
        return {"fold": i, "train": ["a", "b"], "test": ["c", "d"], "is_ret_pct": 1.0, "is_trades": 3, "daily": [0.001] * 10, "daily_start": "2025-01-01",
                "oos": {"ret_pct": 1.0, "trades": len(trades or []), "mdd_pct": 1.0, "halted": False}, "trades": trades}
    folds = [fold(1, [tr(5.0, 100.0, 5.0, 1000.0, 0), tr(-2.0, 200.0, 5.0, 1000.0, 10 * H)]), fold(2, [tr(1.0, 100.0, 1.0, 1000.0, 0)])]
    m = ev.aggregate_wfa(folds)["metrics"]
    assert m["turnover_daily"] == pytest.approx((0.5 + 1.0 + 0.1) / 20) and m["turnover_note"] is None
    m2 = ev.aggregate_wfa([fold(1, [tr(5.0, 100.0, 5.0, 1000.0, 0)]), fold(2, None)])["metrics"]       # một fold không có danh sách lệnh
    assert m2["turnover_daily"] is None and "không có danh sách lệnh" in m2["turnover_note"]
    m3 = ev.aggregate_wfa([fold(1, [tr(5.0, 100.0, 5.0, 0.0, 0)])])["metrics"]                          # thiếu vốn lúc vào lệnh
    assert m3["turnover_daily"] is None and "thiếu danh nghĩa hoặc vốn" in m3["turnover_note"]


# ─── Chống ăn may gộp vào S3 / S4 (không còn tầng S2 riêng) ─────────────────
def test_neighbour_rejection_now_happens_in_s3_with_same_code(small_book, lenient, monkeypatch):
    """Alpha từng bị S2 loại vì lân cận (S2.neighbor) nay bị S3 loại cùng mã; chỉ alpha đã qua WFA mới tốn backtest lân cận."""
    seen = []

    def fake(ctx, strategy, cand, rows):
        seen.append(len(rows))
        return {r["alpha_id"]: (0.0, 4) for r in rows}
    monkeypatch.setattr(gates, "_neighbour_ratios", fake)
    monkeypatch.setattr(gates, "S2_NEIGHBOUR_MIN_PROFIT_RATIO", 0.60)      # mặc định thật (fixture lenient hạ về 0)
    res = _run("fr-test-nb-s3", until="S3_wfa")
    c = {x["stage"]: x for x in res["counts"]}
    assert "S2_antiluck" not in c and c["S3_wfa"]["input"] == c["S1_backtest"]["passed"] >= 1
    assert c["S3_wfa"]["rejected"] == c["S3_wfa"]["done"] and seen and sum(seen) == c["S3_wfa"]["done"]
    store = RunStore(res["run_dir"], read_only=True)
    try:
        for a, _, m, _ in store.iter_stage_metrics("S3_wfa"):
            al = store.get_alpha(a)
            assert al["rejected_stage"] == "S3_wfa" and al["reject_code"] == "S2.neighbor" and al["reject_msg"].startswith("S2.neighbor: ")
            assert m["neighbor_ratio"] == 0.0 and m["neighbor_n"] == 4 and "pbo_flag" in m
        assert store.get_kv("strategy_level:t_long")["n_trials_raw"] == 3
    finally:
        store.close()


def test_dsr_rejection_now_happens_in_s4_before_monte_carlo(small_book, lenient, monkeypatch):
    """Alpha từng bị S2 loại vì DSR ngoài top (S2.dsr_rank) nay bị S4 loại cùng mã, trước khi chạy Monte Carlo."""
    monkeypatch.setattr(gates, "dsr_cut", lambda dsrs: 1e9)
    res = _run("fr-test-dsr-s4", until="S4_montecarlo")
    c = {x["stage"]: x for x in res["counts"]}
    assert c["S3_wfa"]["passed"] >= 1 and c["S4_montecarlo"]["input"] == c["S3_wfa"]["passed"]
    assert c["S4_montecarlo"]["rejected"] == c["S4_montecarlo"]["done"] == c["S4_montecarlo"]["input"] and c["S4_montecarlo"]["passed"] == 0
    store = RunStore(res["run_dir"], read_only=True)
    try:
        for a, _, m, _ in store.iter_stage_metrics("S4_montecarlo"):
            al = store.get_alpha(a)
            assert al["rejected_stage"] == "S4_montecarlo" and al["reject_code"] == "S2.dsr_rank" and al["reject_msg"].startswith("S2.dsr_rank: ")
            assert "dsr" in m and "simulations" not in m and store.read_mc(a) is None      # chưa tốn Monte Carlo
    finally:
        store.close()


def test_legacy_run_with_s2_block_still_reads(small_book, lenient):
    """Kho cũ có khối S2_antiluck (stage_idx 2): vẫn đếm / hiển thị thống kê như tầng cũ, và là đầu vào hợp lệ của S3; không ghi lại dữ liệu."""
    res = _run("fr-test-legacy", until="S1_backtest")
    con = sqlite3.connect(os.path.join(res["run_dir"], "results.sqlite"))
    a = con.execute("SELECT alpha_id FROM alphas WHERE stage_idx=1 AND rejected_idx IS NULL LIMIT 1").fetchone()[0]
    con.execute("UPDATE alphas SET stage_reached='S2_antiluck', stage_idx=2 WHERE alpha_id=?", (a,))
    con.execute("INSERT INTO stage_metrics(alpha_id, stage, metrics_json, passed, ret_pct) VALUES (?, 'S2_antiluck', '{\"dsr\": 0.5, \"ret_pct\": 1.0}', 1, 1.0)", (a,))
    con.commit()
    con.close()
    store = RunStore(res["run_dir"], read_only=True)
    try:
        names = [x["stage"] for x in store.stage_counts()]
        assert names == ["S0_generate", "S1_backtest", "S2_antiluck", "S3_wfa", "S4_montecarlo", "S5_sizing", "S6_holdout", "FINAL"]
        c = {x["stage"]: x for x in store.stage_counts()}
        assert c["S2_antiluck"]["passed"] == 1 and c["S3_wfa"]["input"] == 1
        assert store.count_pending(gates.STAGE_IDX["S1_backtest"]) >= 1 and a in {r["alpha_id"] for r in store.pending(gates.STAGE_IDX["S1_backtest"])}
        assert "S2_antiluck" in store.alpha_metrics(a) and fstats.stage_stats(store, "S2_antiluck")["stage"] == "S2_antiluck"
    finally:
        store.close()
    with pytest.raises(KeyError):          # lượt mới không có tầng S2
        fresh = RunStore(_run("fr-test-nolegacy", until="S1_backtest")["run_dir"], read_only=True)
        try:
            fstats.stage_stats(fresh, "S2_antiluck")
        finally:
            fresh.close()
