"""B3/B4 trên lần chạy engine THẬT (custom_run.run_job, binance_hist TOP10 spot, 2019-12-31 → 2024-12-31): benchmark luôn long, lý do thoát thật, ngày có vị thế,
chế độ thị trường, điều kiện chặn. Thiếu data/binance_hist (hoặc NORA_XNO_DATA_ROOT) -> bỏ qua. Cùng cách chạy với test_xno_parity.py."""
import json
import os

import numpy as np
import pytest

from backend.core.strategy.pydsl.weights import TOP10

HERE = os.path.dirname(__file__)
FIX = os.path.join(HERE, "fixtures", "xno")
ROOT = os.path.abspath(os.environ.get("NORA_XNO_DATA_ROOT") or os.path.join(HERE, "..", "data", "binance_hist"))

pytestmark = pytest.mark.skipif(not all(os.path.isfile(os.path.join(ROOT, "cex", s, "24h.pkl")) for s in TOP10),
                                reason=f"chưa có dữ liệu lịch sử TOP10 spot (nến 24h) tại {ROOT}")

# ba vế: a luôn đúng, b (RSI > 40) đúng phần lớn, c (đóng cửa > EMA20 × 1.15) hiếm -> c là vế chặn
CODE_3 = """
class ThreeConjuncts(SimpleAlgorithm):
    def __algorithm__(self):
        close = self.data.pv_close
        ema = self.feat.ema(close, timeperiod=20)
        rsi = self.feat.rsi(close, timeperiod=14)
        a = close > 0
        b = rsi > 40
        c = close > ema * 1.15
        self.set_positions(a & b & c, position=1)
        self.set_positions(close < ema, position=0)
"""


def _fixture_code(name):
    return json.load(open(os.path.join(FIX, name), encoding="utf-8"))["strategy"]["code"]


def _run(code, monkeypatch, **extra):
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", ROOT)
    from backend.core.backtest import custom_run
    from backend.core.backtest.portfolio import data_cache_clear
    from backend.core.data.loader import CandleLoader
    CandleLoader.clear_cache()
    data_cache_clear()
    params = {"code": code, "profile": "xno", "universe": "TOP10", "start": "2019-12-31", "end": "2024-12-31", "train_ratio": 0.7, "initial_capital": 100_000, **extra}
    from backend.db.data_layout import DATA_HOME
    if os.path.dirname(ROOT) == os.path.abspath(DATA_HOME):
        params["exchange"] = os.path.basename(ROOT)
    return custom_run.run_job(params)


def _assert_regime_consistent(out):
    reg = out["diagnostics"]["regime_analysis"]
    assert reg["available"] and reg["market"] == "BTC"
    total = len(out["series"]["times"]) - 1
    assert reg["total_days"] == total
    assert sum(reg[k]["days"] for k in ("bull", "bear", "unknown")) == total
    assert sum(reg[k]["trades_entered"] for k in ("bull", "bear", "unknown")) == out["diagnostics"]["signal_activity"]["total_trades"]
    pnl = sum(reg[k]["pnl_usd"] for k in ("bull", "bear", "unknown"))
    assert pnl == pytest.approx(out["final_equity"] - out["config"]["initial_capital"], abs=0.05)
    assert reg["bull"]["days"] > 0 and reg["bear"]["days"] > 0
    return reg


def test_e1_always_long_benchmark_is_itself(monkeypatch):
    """E1 (luôn long) chạy qua custom_run: benchmark luôn long = chính nó -> beta 1, tương quan 1, vốn cuối benchmark = vốn cuối chiến lược, excess 0."""
    out = _run(_fixture_code("E1_long_all.json"), monkeypatch)
    mc = out["diagnostics"]["market_comparison"]
    assert mc["available"]
    assert mc["beta"] == pytest.approx(1.0, abs=0.02)
    assert mc["correlation"] >= 0.99
    assert mc["excess_cagr"] == pytest.approx(0.0, abs=0.05)
    assert mc["market_cagr"] == mc["strategy_cagr"] and mc["market_mdd"] == mc["strategy_mdd"]
    bench = out["series"]["benchmark"]
    assert bench["final_equity"] == pytest.approx(out["final_equity"], abs=0.01)
    assert bench["times"] == out["series"]["times"] and len(bench["equity"]) == len(out["series"]["equity"])
    assert mc["strategy_cagr"] not in (40.0, 0.0) and mc["market_mdd"] != 75.0          # không còn hằng số giả
    st = out["series"]["stages"]                                                            # chuỗi giai đoạn do backend tính (dữ liệu thật, hạ mẫu chỉ để vẽ)
    assert st["all"]["downsample"]["source_points"] == len(out["series"]["times"]) and st["all"]["downsample"]["points"] <= 1200
    assert st["all"]["equity"][-1] == out["series"]["equity"][-1] and st["all"]["benchmark"]["equity"][-1] == bench["equity"][-1]
    tb = st["test"]["benchmark"]                                                            # luôn long: benchmark chạy lại trên cửa sổ test = đường vốn test của chính nó (không co dãn)
    assert tb["equity"][0] == st["test"]["equity"][0] == 100_000
    assert tb["equity"] == st["test"]["equity"] and tb["pnl"] == st["test"]["pnl"]
    assert out["series"]["test"]["benchmark"]["final_equity"] == pytest.approx(out["series"]["test"]["equity"][-1], abs=0.01)
    sig = out["diagnostics"]["signal_activity"]
    assert sig["exit_reasons"] == {"open_at_end": 100.0} and sig["open_trades"] == 10 and sig["closed_trades"] == 0
    assert sig["days_in_market_pct"] > 99.0 and sig["avg_exposure_pct"] > 95.0          # luôn long: đầy vốn (SOL niêm yết muộn nên < 100)
    _assert_regime_consistent(out)
    ids = [i["id"] for i in out["insights"]]
    assert "beta_driven" in ids and "negative_excess" not in ids
    assert all(i["evidence"] for i in out["insights"])


def test_kema_xno_real_exit_reasons_and_exposure(monkeypatch):
    out = _run(_fixture_code("KEMA_long.json"), monkeypatch)
    d = out["diagnostics"]
    sig = d["signal_activity"]
    assert set(sig["exit_reasons"]) <= {"signal", "open_at_end"}                          # xno: không SL/TP -> không bao giờ stop_loss/take_profit
    assert "stop_loss" not in sig["exit_reasons"] and "take_profit" not in sig["exit_reasons"]
    assert sig["exit_reason_counts"].get("signal", 0) == sig["closed_trades"] > 0
    assert 0.0 < sig["days_in_market_pct"] < 100.0
    assert 0.0 < sig["avg_exposure_pct"] < 100.0 and sig["avg_exposure_pct"] <= sig["days_in_market_pct"]
    assert set(sig["time_in_market_by_coin"]) == set(TOP10) and all(0.0 < v < 100.0 for v in sig["time_in_market_by_coin"].values())
    # trùng khớp với danh sách lệnh của kết quả
    assert sig["closed_trades"] == len(out["trades"]) and sig["open_trades"] == len(out["positions_open"])
    mc = d["market_comparison"]
    assert mc["available"] and mc["market_cagr"] != 40.0 and mc["market_mdd"] != 75.0
    assert (mc["beta"], mc["correlation"]) != (0.95, 0.85) and 0.0 < mc["correlation"] < 0.99
    assert mc["strategy_mdd"] < mc["market_mdd"]                                          # KEMA thoát khi giá dưới EMA: sụt giảm nông hơn luôn long
    assert out["metrics"]["simulate"]["nora"]["mdd_pct"] == pytest.approx(mc["strategy_mdd"], abs=0.01)
    reg = _assert_regime_consistent(out)
    assert reg["bull"]["days_in_market_pct"] > reg["bear"]["days_in_market_pct"]          # theo xu hướng: ở trong thị trường nhiều hơn khi BTC trên SMA200
    bc = d["binding_condition"]["rules"]
    entry = next(r for r in bc if r["side"] == "LONG")
    assert entry["n_conjuncts"] == 2 and entry["near_miss_bars"] > 0
    assert entry["binding"]["index"] == 1 and "EMA" in entry["binding"]["text_vi"]       # vế phá vỡ kênh Keltner chặn gần hết các nến suýt vào
    for i in out["insights"]:
        assert i["evidence"], i["id"]


def test_three_conjunct_strategy_binding_condition_real_run(monkeypatch):
    out = _run(CODE_3, monkeypatch)
    rule = next(r for r in out["diagnostics"]["binding_condition"]["rules"] if r["side"] == "LONG")
    assert rule["n_conjuncts"] == 3
    a, b, c = rule["conjuncts"]
    assert a["pct_true"] == 100.0 and a["only_false_bars"] == 0
    assert c["pct_true"] < b["pct_true"] < 100.0
    assert rule["binding"]["index"] == 3 and "1.15" in rule["binding"]["text_vi"]
    assert rule["binding"]["share_of_near_miss_pct"] >= 50.0
    ins = next(i for i in out["insights"] if i["id"] == "binding_condition")
    assert ins["evidence"]["conjunct_index"] == 3 and ins["evidence"]["near_miss_bars"] == rule["near_miss_bars"]
    assert rule["binding"]["text_vi"] in ins["message_vi"]
    _assert_regime_consistent(out)


def test_benchmark_runs_once_per_config(monkeypatch):
    from backend.core.backtest import custom_run
    custom_run._BENCH_CACHE.clear()
    calls = []
    real = custom_run.execute
    monkeypatch.setattr(custom_run, "execute", lambda plan, *a, **k: (calls.append(plan.strategies[0]["id"]) or real(plan, *a, **k)))
    _run(_fixture_code("KEMA_long.json"), monkeypatch)
    n_first = sum(1 for c in calls if "_long_" in c)
    assert n_first > 0
    n_before = len(calls)
    _run(_fixture_code("E9_kema_nrsi.json"), monkeypatch)                                 # chương trình khác, cùng cấu hình -> benchmark dùng lại (chỉ chạy chính + lần test); cache giữ 2 mục: cửa sổ toàn kỳ + cửa sổ test
    new = calls[n_before:]
    assert len(new) == 2 and len(custom_run._BENCH_CACHE) == 2
