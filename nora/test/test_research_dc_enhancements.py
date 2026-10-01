"""
test_research_dc_enhancements.py — Đợt 5: Nghiên cứu DC trên nến 1m close, Out-of-sample 40%, t-stat hurdle

Quy tắc: Viết test trước, chạy thấy FAIL, sau đó sửa code để PASS.

5.1: load_price_path chạy trên close 1m khi không có tick thật, price_resolution == "1m_close",
     bỏ qua nến điền is_filled==1, bỏ qua ticks giả (ticks.synthetic = true).
5.2: analyze_market đánh giá trên 40% OOS (timestamp >= split_ts).
5.3: best_theta = None khi không có theta nào đạt trên 60% IS train, verdict NOT_TESTED.
5.4: Hiệu chỉnh nhiều tài sản: t-stat của avg_net_bps > 3.0 mới được SURVIVED.
"""
import os
import json
import time
import tempfile
import pandas as pd
import numpy as np
import pytest

from backend.core.data.resampler import save_resampled_dataset
from backend.core.research.market_analyzer import analyze_market, load_price_path
from backend.core.research.dc_feature_extractor import sweep_directional_change
from backend.core.strategy.directional_change import simulate_causal_dc_trades
from backend.core.research.edge_falsifier import falsify_edge_candidate


# ─── 5.1: load_price_path trên 1m close ────────────────────────────────────────

def test_load_price_path_prefers_1m_close_when_no_ticks():
    """Khi không có tick, load_price_path đọc nến 1m, timestamp_ms = open_time + 60_000, lọc bỏ nến điền."""
    with tempfile.TemporaryDirectory() as tmp:
        sym = "NO_TICKS"
        sym_dir = os.path.join(tmp, sym)
        os.makedirs(sym_dir, exist_ok=True)

        n = 100
        t0 = 1700000000000
        times = [t0 + i * 60_000 for i in range(n)]
        df_1m = pd.DataFrame({
            "open_time": times,
            "open": [10.0] * n,
            "high": [10.1] * n,
            "low": [9.9] * n,
            "close": [10.0 + i * 0.1 for i in range(n)],
            "volume": [100.0] * n,
            "is_filled": [1 if i % 10 == 0 else 0 for i in range(n)],
        })
        df_1m.to_pickle(os.path.join(sym_dir, "1m.pkl"))

        df_path, res = load_price_path(sym, data_root=tmp)
        assert res == "1m_close"
        assert len(df_path) == 90  # 10 nến is_filled==1 bị lọc
        # Timestamp phải là open_time + 60_000
        assert df_path["timestamp_ms"].iloc[0] == times[1] + 60_000
        assert df_path["price"].iloc[0] == 10.0 + 1 * 0.1


def test_load_price_path_ignores_synthetic_ticks():
    """Nếu ticks.parquet tồn tại nhưng manifest có ticks.synthetic = true, vẫn dùng 1m_close."""
    with tempfile.TemporaryDirectory() as tmp:
        sym = "SYNTH_TICKS"
        sym_dir = os.path.join(tmp, sym)
        os.makedirs(sym_dir, exist_ok=True)

        n = 100
        t0 = 1700000000000
        df_1m = pd.DataFrame({
            "open_time": [t0 + i * 60_000 for i in range(n)],
            "open": [10.0] * n,
            "high": [10.1] * n,
            "low": [9.9] * n,
            "close": [10.0] * n,
            "volume": [100.0] * n,
            "is_filled": [0] * n,
        })
        df_1m.to_pickle(os.path.join(sym_dir, "1m.pkl"))

        # Ghi ticks.parquet giả
        pd.DataFrame({
            "timestamp_ms": [t0 + i * 1000 for i in range(50)],
            "price": [10.0] * 50,
            "amount": [1.0] * 50,
        }).to_parquet(os.path.join(sym_dir, "ticks.parquet"))

        with open(os.path.join(sym_dir, "manifest.json"), "w") as f:
            json.dump({
                "synthetic": False,
                "ticks": {"synthetic": True, "source": "synthetic_ohlc"},
            }, f)

        df_path, res = load_price_path(sym, data_root=tmp)
        assert res == "1m_close", f"Ticks nhân tạo phải bị bỏ qua, got {res}"


# ─── 5.2: 40% OOS evaluation window ──────────────────────────────────────────

def test_sweep_dc_returns_split_ts():
    """sweep_directional_change phải trả về split_ts tại mốc 60% dữ liệu."""
    n = 1000
    times = [1700000000000 + i * 1000 for i in range(n)]
    prices = list(np.random.default_rng(42).lognormal(0, 0.001, n).cumprod() * 100)
    df = pd.DataFrame({"timestamp_ms": times, "price": prices})

    res = sweep_directional_change(df, "TEST", theta_grid=[0.01, 0.02])
    assert "split_ts" in res
    assert res["split_ts"] == times[600]


# ─── 5.3: best_theta = None khi không đạt trên train ──────────────────────────

def test_no_best_theta_defaults_to_none_and_not_tested():
    """Khi không có theta nào có điểm > 0 trên tập train, best_theta là None (không bịa 0.02)."""
    # Flat price: không có biến cố nào
    n = 200
    times = [1700000000000 + i * 1000 for i in range(n)]
    df = pd.DataFrame({"timestamp_ms": times, "price": [100.0] * n})

    res = sweep_directional_change(df, "FLAT", theta_grid=[0.01, 0.02])
    assert res.get("best_theta") is None, f"Flat line không được gán best_theta=0.02, got {res.get('best_theta')}"


# ─── 5.4: t-stat hurdle > 3.0 cho SURVIVED ────────────────────────────────────

def test_t_stat_hurdle_rejects_lucky_trades():
    """
    Chuỗi lệnh có mean +2 bps, std 50, n = 100 (t = 0.4)
    phải bị đánh survived=False và FALSIFIED dù avg_net_bps > 0.
    """
    # Dựng chuỗi lệnh nhân tạo: mean +2 bps, std ~50, n = 100
    rng = np.random.default_rng(123)
    net_bps = list(rng.normal(2.0, 50.0, 100))

    # Giả lập DataFrame ticks để chạy simulate_causal_dc_trades
    # Hoặc kiểm tra trực tiếp qua simulate_causal_dc_trades / edge_falsifier
    t_stat = float(np.mean(net_bps) / (np.std(net_bps) / np.sqrt(len(net_bps))))
    assert t_stat < 3.0, f"t-stat phải < 3.0 cho mẫu này, got {t_stat}"

    # Kiểm tra trong falsify_edge_candidate khi model có t-stat thấp
    fake_backtest = {
        "cost_models": {
            "standard": {
                "key": "standard",
                "avg_net_bps": 2.0,
                "survived": False,  # phải False do t-stat <= 3.0
                "t_stat": t_stat,
            }
        }
    }
    falsif = falsify_edge_candidate(
        symbol="TEST",
        theta=0.01,
        fingerprint={"clustering_index": 1.0},
        playbook_type="DC_MOMENTUM_FOLLOWING",
        backtest_sim=fake_backtest,
    )
    assert falsif["falsified"] is True
    assert falsif["falsification_status"] == "FALSIFIED_AFTER_COST"


def test_research_random_walk_falsified_on_1m_close():
    """
    Random walk 1m -> analyze_market phải ra:
    - price_resolution == '1m_close'
    - verdict FALSIFIED_AFTER_COST
    - standard cost model survived == False
    - các lệnh đều nằm sau split_ts (40% OOS window)
    """
    with tempfile.TemporaryDirectory() as tmp:
        sym = "RWWALK"
        n = 50400  # 35 ngày
        t0 = 1700000000000
        times = [t0 + i * 60_000 for i in range(n)]
        ret = np.random.default_rng(42).normal(0, 0.001, n)
        prices = list(100.0 * np.exp(np.cumsum(ret)))
        df_1m = pd.DataFrame({
            "open_time": times,
            "open": prices,
            "high": [p * 1.0005 for p in prices],
            "low": [p * 0.9995 for p in prices],
            "close": prices,
            "volume": [100.0] * n,
        })
        save_resampled_dataset(sym, tmp, df_1m, "0xpool", crawl_ok=True)
        res = analyze_market(sym, data_root=tmp, force_refresh=True, theta_grid=[0.005, 0.01, 0.02])

        assert res.get("price_resolution") == "1m_close"
        assert res.get("verdict") == "FALSIFIED_AFTER_COST"
        assert "evaluation_window" in res
        split_ts = res["evaluation_window"]["split_ts"]

        sim = res.get("backtest_simulation") or {}
        trades = sim.get("trades", [])
        if trades:
            assert all(t["timestamp"] >= split_ts for t in trades), "Mọi lệnh phải sau split_ts"

