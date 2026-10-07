"""B3/B4 trên lần chạy engine THẬT (custom_run.run_job, kho dữ liệu OKX perp BTC + ETH, 2024-06-01 → 2025-05-31): benchmark luôn long, lý do thoát thật, ngày có vị thế,
chế độ thị trường, điều kiện chặn. Thiếu dữ liệu 24h/1m của BTC, ETH trong kho thật -> bỏ qua."""
import os

import pytest

from backend.crawl import store

SYMBOLS = ["BTC", "ETH"]


def _real_root():
    """Gốc dữ liệu OKX thật (conftest trỏ NORA_LOCAL_DATA_ROOT vào thư mục tạm): market/okx (mới) hoặc okx (cũ)."""
    for sub in (("market", "okx"), ("okx",)):
        root = os.path.join(store.DATA_HOME, *sub)
        if os.path.isdir(os.path.join(root, "cex")):
            return root
    return None


ROOT = _real_root()
pytestmark = pytest.mark.skipif(not ROOT or not all(os.path.isfile(os.path.join(ROOT, "cex", s, "perp", "1m.pkl")) for s in SYMBOLS),
                                reason="chưa có dữ liệu OKX perp BTC/ETH trong kho thật")

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

CODE_ALWAYS_LONG = """
class AlwaysLong(SimpleAlgorithm):
    def __algorithm__(self):
        self.set_positions(self.data.pv_close > 0, position=1)
"""

CODE_KEMA = """
class CustomStrategy(SimpleAlgorithm):
    def __algorithm__(self):
        close = self.data.pv_close
        high = self.data.pv_high
        low = self.data.pv_low
        ema = self.feat.ema(close, timeperiod=30)
        atr = self.feat.atr(high, low, close, timeperiod=14)
        rsi = self.feat.rsi(close, timeperiod=14)
        kc_up = ema + 2.0 * atr
        long_entry = (close > kc_up) & (rsi > 50)
        exit_cond = close < ema
        self.set_positions(exit_cond, position=0)
        self.set_positions(long_entry, position=1.0)
"""


def _run(code, **extra):
    from backend.core.backtest import custom_run
    from backend.core.backtest.portfolio import data_cache_clear
    from backend.core.data.loader import CandleLoader
    CandleLoader.clear_cache()
    data_cache_clear()
    params = {"code": code, "symbols": SYMBOLS, "start": "2024-06-01", "end": "2025-05-31", "train_ratio": 0.7, "initial_capital": 100_000, **extra}
    return custom_run.run_job(params)


@pytest.fixture(autouse=True)
def _real_store(monkeypatch):
    monkeypatch.delenv("NORA_JOB_DIR", raising=False)
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", ROOT)


def _assert_regime_consistent(out):
    reg = out["diagnostics"]["regime_analysis"]
    assert reg["available"] and reg["market"] == "BTC"
    total = len(out["series"]["times"]) - 1
    assert reg["total_days"] == total
    assert sum(reg[k]["days"] for k in ("bull", "bear", "unknown")) == total
    assert sum(reg[k]["trades_entered"] for k in ("bull", "bear", "unknown")) == out["diagnostics"]["signal_activity"]["total_trades"]
    pnl = sum(reg[k]["pnl_usd"] for k in ("bull", "bear", "unknown"))
    assert pnl == pytest.approx(out["final_equity"] - out["config"]["initial_capital"], abs=0.05)
    return reg


def test_always_long_diagnostics_are_real_and_consistent():
    out = _run(CODE_ALWAYS_LONG)
    mc = out["diagnostics"]["market_comparison"]
    assert mc["available"], out["warnings"]
    assert -1.0 <= mc["correlation"] <= 1.0 and mc["beta"] is not None
    assert mc["strategy_cagr"] not in (40.0, 0.0) and mc["market_mdd"] != 75.0          # không còn hằng số giả
    bench = out["series"]["benchmark"]
    assert bench["times"] == out["series"]["times"] and len(bench["equity"]) == len(out["series"]["equity"])
    st = out["series"]["stages"]                                                            # chuỗi giai đoạn do backend tính (dữ liệu thật, hạ mẫu chỉ để vẽ)
    assert st["all"]["downsample"]["source_points"] == len(out["series"]["times"]) and st["all"]["downsample"]["points"] <= 1200
    assert st["all"]["equity"][-1] == out["series"]["equity"][-1] and st["all"]["benchmark"]["equity"][-1] == bench["equity"][-1]
    tb = st["test"]["benchmark"]
    assert tb["equity"][0] == st["test"]["equity"][0] == 100_000
    sig = out["diagnostics"]["signal_activity"]
    assert sig["days_in_market_pct"] > 90.0
    assert sum(sig["exit_reason_counts"].values()) == sig["total_trades"] == len(out["trades"]) + len(out["positions_open"])
    _assert_regime_consistent(out)
    assert all(i["evidence"] for i in out["insights"])


def test_kema_real_exit_reasons_and_exposure():
    out = _run(CODE_KEMA)
    d = out["diagnostics"]
    sig = d["signal_activity"]
    assert set(sig["exit_reasons"]) <= {"signal", "stop_loss", "take_profit", "trailing_stop", "timeout", "liquidation", "open_at_end"}
    assert sum(sig["exit_reason_counts"].values()) == sig["total_trades"] == len(out["trades"]) + len(out["positions_open"])
    assert 0.0 < sig["days_in_market_pct"] < 100.0 and 0.0 <= sig["avg_exposure_pct"] <= 100.0
    assert set(sig["time_in_market_by_coin"]) == {f"{s}@perp" for s in SYMBOLS} or set(sig["time_in_market_by_coin"]) == set(SYMBOLS)
    mc = d["market_comparison"]
    assert mc["available"] and mc["market_cagr"] != 40.0 and mc["market_mdd"] != 75.0
    assert (mc["beta"], mc["correlation"]) != (0.95, 0.85)
    assert out["metrics"]["simulate"]["mdd_pct"] == pytest.approx(mc["strategy_mdd"], abs=0.01)
    _assert_regime_consistent(out)
    entry = next(r for r in d["binding_condition"]["rules"] if r["side"] == "LONG")
    assert entry["n_conjuncts"] == 2
    for i in out["insights"]:
        assert i["evidence"], i["id"]


def test_three_conjunct_strategy_binding_condition_real_run():
    out = _run(CODE_3)
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
    _run(CODE_KEMA)
    assert len(calls) == 4 and len(custom_run._BENCH_CACHE) == 2       # chính + test + benchmark toàn kỳ + benchmark test
    _run(CODE_3)                                                       # chương trình khác, cùng cấu hình -> benchmark dùng lại; cache vẫn 2 mục (toàn kỳ + cửa sổ test)
    assert len(calls) == 6 and len(custom_run._BENCH_CACHE) == 2
